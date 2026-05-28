"""Tests unitaires du module eurekam_maintenance.

Couvre les 12 cas obligatoires definis dans le CLAUDE.md :
    1. test_contract_creation
    2. test_sequence_generation
    3. test_workflow_transitions
    4. test_line_total_computation
    5. test_unique_year_per_contract
    6. test_expiry_cron_job
    7. test_renewal_wizard
    8. test_renewal_syntec_revision
    9. test_invoice_creation
    10. test_partner_extension
    11. test_security_user_vs_manager
    12. test_company_isolation

Lancement :
    python odoo-bin -d <db> -i eurekam_maintenance --test-enable \\
        --test-tags eurekam_maintenance --stop-after-init
"""

from datetime import date, timedelta

from odoo import fields as ofields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'eurekam_maintenance')
class TestMaintenanceContract(TransactionCase):
    """Tests fonctionnels du module Eurekam Maintenance.

    Tag `post_install` : les tests s'executent apres l'installation complete
    de la base, ce qui garantit que account/mail/etc. sont disponibles.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # ---- Partenaire etablissement (autorise pour les contrats) ----
        cls.partner = cls.env['res.partner'].create({
            'name': 'CHU Test',
            'is_company': True,
            'is_maintenance_establishment': True,
            'department_number': '69',
            'email': 'chu.test@example.com',
        })

        # ---- Utilisateurs : un commercial (user) et un manager ----
        cls.user_commercial = cls.env['res.users'].create({
            'name': 'Commercial Test',
            'login': 'eurekam.test.commercial@example.com',
            'email': 'eurekam.test.commercial@example.com',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('eurekam_maintenance.group_maintenance_user').id,
            ])],
        })
        cls.user_manager = cls.env['res.users'].create({
            'name': 'Manager Test',
            'login': 'eurekam.test.manager@example.com',
            'email': 'eurekam.test.manager@example.com',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('eurekam_maintenance.group_maintenance_manager').id,
            ])],
        })

        # ---- Produit ----
        cls.product = cls.env['product.template'].create({
            'name': 'Maintenance Drugcam (test)',
            'type': 'service',
        })

    # ----------------------------------------------------------------------
    # Helper
    # ----------------------------------------------------------------------
    def _make_contract(self, **vals):
        """Cree un contrat avec des valeurs par defaut surchargeables."""
        defaults = {
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'commercial_id': self.user_commercial.id,
            'date_start': date(2026, 1, 1),
            'date_end': date(2026, 12, 31),
            'duration': '1y',
            'maintenance_amount': 10000.0,
        }
        defaults.update(vals)
        return self.env['eurekam.maintenance.contract'].create(defaults)

    # ======================================================================
    # 1. Creation avec champs obligatoires
    # ======================================================================
    def test_contract_creation(self):
        contract = self._make_contract()
        self.assertEqual(contract.state, 'draft')
        self.assertEqual(contract.partner_id, self.partner)
        self.assertTrue(contract.sequence_number)
        self.assertNotEqual(contract.sequence_number, 'Nouveau')
        self.assertTrue(contract.name)

        # partner_id est obligatoire
        with self.assertRaises(Exception):
            self.env['eurekam.maintenance.contract'].create({
                'product_id': self.product.id,
                'maintenance_amount': 1000.0,
            })

    # ======================================================================
    # 2. Generation de la sequence MAINT/AAAA/NNNN
    # ======================================================================
    def test_sequence_generation(self):
        c1 = self._make_contract()
        c2 = self._make_contract()
        self.assertRegex(c1.sequence_number, r'^MAINT/\d{4}/\d+$')
        self.assertRegex(c2.sequence_number, r'^MAINT/\d{4}/\d+$')
        self.assertNotEqual(c1.sequence_number, c2.sequence_number)

    # ======================================================================
    # 3. Transitions d'etat draft -> active -> cancelled -> draft
    # ======================================================================
    def test_workflow_transitions(self):
        contract = self._make_contract()
        self.assertEqual(contract.state, 'draft')
        contract.action_activate()
        self.assertEqual(contract.state, 'active')
        contract.action_cancel()
        self.assertEqual(contract.state, 'cancelled')
        contract.action_draft()
        self.assertEqual(contract.state, 'draft')

        # Activation impossible sans dates
        contract2 = self._make_contract()
        contract2.write({'date_start': False, 'date_end': False})
        with self.assertRaises(UserError):
            contract2.action_activate()

    # ======================================================================
    # 4. Calcul correct des totaux des lignes annuelles
    # ======================================================================
    def test_line_total_computation(self):
        contract = self._make_contract(
            date_start=date(2026, 1, 1),
            date_end=date(2028, 12, 31),
            duration='3y',
            maintenance_amount=15000.0,
        )
        contract.action_generate_lines()
        self.assertEqual(len(contract.line_ids), 3)
        self.assertEqual(contract.line_count, 3)
        self.assertEqual(contract.total_contract_value, 15000.0 * 3)

        # Modification d'une ligne -> recalcul du total
        line_2027 = contract.line_ids.filtered(lambda l: l.year == 2027)
        line_2027.amount = 20000.0
        contract.invalidate_recordset()
        self.assertEqual(
            contract.total_contract_value,
            15000.0 + 20000.0 + 15000.0,
        )

    # ======================================================================
    # 5. Contrainte UNIQUE(contract_id, year)
    # ======================================================================
    def test_unique_year_per_contract(self):
        contract = self._make_contract()
        Line = self.env['eurekam.maintenance.contract.line']
        Line.create({
            'contract_id': contract.id,
            'year': 2026,
            'amount': 10000.0,
        })
        with self.assertRaises(Exception):
            Line.create({
                'contract_id': contract.id,
                'year': 2026,
                'amount': 5000.0,
            })

    # ======================================================================
    # 6. Cron de bascule expiring/expired
    # ======================================================================
    def test_expiry_cron_job(self):
        today = ofields.Date.context_today(self.env['res.partner'])
        # c1 : expire dans 30 jours -> doit passer en 'expiring'
        c1 = self._make_contract(
            date_start=today - timedelta(days=300),
            date_end=today + timedelta(days=30),
        )
        c1.action_activate()
        # c2 : expiree depuis 10 jours -> doit passer en 'expired'
        c2 = self._make_contract(
            date_start=today - timedelta(days=400),
            date_end=today - timedelta(days=10),
        )
        c2.action_activate()
        # c3 : expire dans 200 jours -> reste 'active'
        c3 = self._make_contract(
            date_start=today - timedelta(days=100),
            date_end=today + timedelta(days=200),
        )
        c3.action_activate()

        Contract = self.env['eurekam.maintenance.contract']
        result = Contract._cron_check_expiring_contracts()

        self.assertIn(c1.id, result['expiring'])
        self.assertIn(c2.id, result['expired'])
        self.assertNotIn(c3.id, result['expiring'])
        self.assertNotIn(c3.id, result['expired'])
        self.assertEqual(c1.state, 'expiring')
        self.assertEqual(c2.state, 'expired')
        self.assertEqual(c3.state, 'active')

        # Idempotence : second appel ne doit rien changer
        result2 = Contract._cron_check_expiring_contracts()
        self.assertNotIn(c1.id, result2['expiring'])

    # ======================================================================
    # 7. Wizard de renouvellement : pre-remplissage
    # ======================================================================
    def test_renewal_wizard(self):
        contract = self._make_contract(
            date_start=date(2025, 1, 1),
            date_end=date(2025, 12, 31),
            duration='1y',
            maintenance_amount=12000.0,
            syntec_revision='no',
        )
        contract.action_activate()
        wizard = self.env['eurekam.contract.renewal.wizard'].with_context(
            default_contract_id=contract.id,
        ).create({})
        self.assertEqual(wizard.contract_id, contract)
        self.assertEqual(wizard.old_amount, 12000.0)
        self.assertEqual(wizard.new_date_start, date(2026, 1, 1))
        self.assertEqual(wizard.new_date_end, date(2026, 12, 31))
        self.assertEqual(wizard.new_duration, '1y')
        self.assertFalse(wizard.apply_syntec)
        self.assertEqual(wizard.new_maintenance_amount, 12000.0)

    # ======================================================================
    # 8. Wizard de renouvellement : application Syntec + creation
    # ======================================================================
    def test_renewal_syntec_revision(self):
        contract = self._make_contract(
            date_start=date(2025, 1, 1),
            date_end=date(2025, 12, 31),
            duration='1y',
            maintenance_amount=10000.0,
            syntec_revision='yes',
        )
        contract.action_activate()
        wizard = self.env['eurekam.contract.renewal.wizard'].with_context(
            default_contract_id=contract.id,
        ).create({})
        self.assertTrue(wizard.apply_syntec)
        self.assertEqual(wizard.syntec_rate, 3.0)
        self.assertAlmostEqual(wizard.new_maintenance_amount, 10300.0, places=2)

        action = wizard.action_renew()
        self.assertEqual(action['res_model'], 'eurekam.maintenance.contract')
        new_contract = self.env['eurekam.maintenance.contract'].browse(action['res_id'])
        self.assertEqual(new_contract.state, 'active')
        self.assertAlmostEqual(new_contract.maintenance_amount, 10300.0, places=2)
        self.assertEqual(new_contract.renewed_from_id, contract)
        self.assertEqual(contract.state, 'renewed')

    # ======================================================================
    # 9. Creation de factures depuis contrat (selon cadence)
    # ======================================================================
    def test_invoice_creation(self):
        """Test cadence annuelle par défaut : 1 facture pour 1 ligne annuelle."""
        today_year = ofields.Date.context_today(self.env['res.partner']).year
        contract = self._make_contract(
            date_start=date(today_year, 1, 1),
            date_end=date(today_year, 12, 31),
            maintenance_amount=8000.0,
        )
        contract.action_activate()
        contract.action_generate_lines()

        # Sans cadence definie -> defaut 'annual' -> 1 facture pour 8000 EUR
        action = contract.action_create_invoices_for_contract()
        self.assertEqual(action['res_model'], 'account.move')
        # action['domain'] = [('id', 'in', [id1, id2, ...])]
        invoice_ids = action['domain'][0][2]
        self.assertEqual(len(invoice_ids), 1)
        invoice = self.env['account.move'].browse(invoice_ids[0])
        self.assertEqual(invoice.move_type, 'out_invoice')
        self.assertEqual(invoice.partner_id, self.partner)
        self.assertEqual(len(invoice.invoice_line_ids), 1)
        self.assertEqual(invoice.invoice_line_ids.price_unit, 8000.0)

        line = contract.line_ids.filtered(lambda l: l.year == today_year)
        self.assertTrue(line.is_invoiced)
        self.assertIn(invoice, line.invoice_ids)
        self.assertEqual(contract.invoice_count, 1)

        # Re-facturer -> erreur (toutes les périodes restantes déjà couvertes)
        with self.assertRaises(UserError):
            contract.action_create_invoices_for_contract()

    def test_invoice_creation_quarterly(self):
        """Test cadence trimestrielle : 4 factures de quart de montant par annee."""
        freq_quarterly = self.env.ref('eurekam_maintenance.freq_quarterly')
        freq_overdue = self.env.ref('eurekam_maintenance.freq_overdue')
        today_year = ofields.Date.context_today(self.env['res.partner']).year
        contract = self._make_contract(
            date_start=date(today_year, 1, 1),
            date_end=date(today_year, 12, 31),
            maintenance_amount=10000.0,
            billing_frequency_ids=[(6, 0, [freq_quarterly.id, freq_overdue.id])],
        )
        contract.action_activate()
        contract.action_generate_lines()

        action = contract.action_create_invoices_for_contract()
        invoice_ids = action['domain'][0][2]
        # 1 ligne annuelle * 4 trimestres = 4 factures
        self.assertEqual(len(invoice_ids), 4)
        invoices = self.env['account.move'].browse(invoice_ids)
        # Chaque facture = 10000 / 4 = 2500 HT
        for inv in invoices:
            self.assertAlmostEqual(inv.invoice_line_ids.price_unit, 2500.0, places=2)
        # La ligne annuelle pointe vers 4 factures
        line = contract.line_ids.filtered(lambda l: l.year == today_year)
        self.assertEqual(line.invoice_count, 4)
        self.assertTrue(line.is_invoiced)

    def test_billing_unicity_constraint(self):
        """Test contrainte : 2 cadences de periode interdites."""
        freq_quarterly = self.env.ref('eurekam_maintenance.freq_quarterly')
        freq_semi_annual = self.env.ref('eurekam_maintenance.freq_semi_annual')
        contract = self._make_contract()
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            contract.billing_frequency_ids = [
                (6, 0, [freq_quarterly.id, freq_semi_annual.id])
            ]

    # ======================================================================
    # 10. Extension res.partner
    # ======================================================================
    def test_partner_extension(self):
        # Note refactor option A : on n'utilise plus eurekam.establishment.type
        # mais le tag standard res.partner.category. On cree un tag de test
        # pour valider que la classification fonctionne via les tags Odoo.
        ch_tag = self.env['res.partner.category'].create({'name': 'CH (Test)'})
        partner = self.env['res.partner'].create({
            'name': 'CHU Bordeaux Test',
            'is_company': True,
            'is_maintenance_establishment': True,
            'department_number': '33',
            'category_id': [(6, 0, [ch_tag.id])],
            'establishment_status': 'client_eurekam',
            'central_purchasing': 'uniha',
            'nb_workstations': 12,
        })
        self.assertTrue(partner.is_maintenance_establishment)
        self.assertEqual(partner.department_number, '33')
        self.assertIn(ch_tag, partner.category_id)
        self.assertEqual(partner.maintenance_contract_count, 0)

        # Creation d'un contrat -> compteur passe a 1
        self._make_contract(partner_id=partner.id)
        partner.invalidate_recordset()
        self.assertEqual(partner.maintenance_contract_count, 1)

    # ======================================================================
    # 11. Securite : user vs manager (perm_unlink)
    # ======================================================================
    def test_security_user_vs_manager(self):
        contract = self._make_contract()
        # Le commercial (user) ne peut PAS supprimer
        with self.assertRaises(AccessError):
            contract.with_user(self.user_commercial).unlink()
        # Le manager peut supprimer
        contract.with_user(self.user_manager).unlink()
        self.assertFalse(contract.exists())

    # ======================================================================
    # 12. Isolation multi-societe (record rule)
    # ======================================================================
    def test_company_isolation(self):
        company2 = self.env['res.company'].create({
            'name': 'Eurekam Subsidiary Test',
        })
        partner_co2 = self.env['res.partner'].create({
            'name': 'Etablissement Co2',
            'is_company': True,
            'is_maintenance_establishment': True,
            'company_id': company2.id,
        })
        contract_co1 = self._make_contract()
        contract_co2 = self._make_contract(
            partner_id=partner_co2.id,
            company_id=company2.id,
        )

        # Le commercial est lie uniquement a co1 (la company par defaut)
        self.user_commercial.write({
            'company_ids': [(6, 0, [self.env.company.id])],
            'company_id': self.env.company.id,
        })
        contracts_visible = self.env['eurekam.maintenance.contract'].with_user(
            self.user_commercial,
        ).search([])
        self.assertIn(contract_co1, contracts_visible)
        self.assertNotIn(contract_co2, contracts_visible)
