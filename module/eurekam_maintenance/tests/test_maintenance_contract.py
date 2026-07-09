"""Unit tests of the eurekam_maintenance module.

Covers the 12 mandatory cases defined in CLAUDE.md:
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

Run with:
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
    """Functional tests of the Eurekam Maintenance module.

    `post_install` tag: tests run after the full database installation, which
    guarantees that account/mail/etc. are available.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # ---- Establishment partner (allowed for contracts) ----
        cls.partner = cls.env['res.partner'].create({
            'name': 'CHU Test',
            'is_company': True,
            'is_maintenance_establishment': True,
            'department_number': '69',
            'email': 'chu.test@example.com',
        })

        # ---- Users: a salesperson (user) and a manager ----
        cls.user_commercial = cls.env['res.users'].create({
            'name': 'Salesperson Test',
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

        # ---- Product ----
        cls.product = cls.env['product.template'].create({
            'name': 'Drugcam Maintenance (test)',
            'type': 'service',
        })

    # ----------------------------------------------------------------------
    # Helper
    # ----------------------------------------------------------------------
    def _make_contract(self, **vals):
        """Create a contract with overridable default values.

        By default requires_customer_order=False so the historical tests
        (test_invoice_creation*) can keep calling
        action_create_invoices_for_contract directly.
        To test the SO workflow, pass requires_customer_order=True explicitly.
        """
        defaults = {
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'commercial_id': self.user_commercial.id,
            'date_start': date(2026, 1, 1),
            'date_end': date(2026, 12, 31),
            'duration': '1y',
            'maintenance_amount': 10000.0,
            'requires_customer_order': False,
        }
        defaults.update(vals)
        return self.env['eurekam.maintenance.contract'].create(defaults)

    # ======================================================================
    # 1. Creation with mandatory fields
    # ======================================================================
    def test_contract_creation(self):
        contract = self._make_contract()
        self.assertEqual(contract.state, 'draft')
        self.assertEqual(contract.partner_id, self.partner)
        self.assertTrue(contract.sequence_number)
        self.assertNotEqual(contract.sequence_number, 'New')
        self.assertTrue(contract.name)

        # partner_id is mandatory
        with self.assertRaises(Exception):
            self.env['eurekam.maintenance.contract'].create({
                'product_id': self.product.id,
                'maintenance_amount': 1000.0,
            })

    # ======================================================================
    # 2. Sequence generation MAINT/YYYY/NNNN
    # ======================================================================
    def test_sequence_generation(self):
        c1 = self._make_contract()
        c2 = self._make_contract()
        self.assertRegex(c1.sequence_number, r'^MAINT/\d{4}/\d+$')
        self.assertRegex(c2.sequence_number, r'^MAINT/\d{4}/\d+$')
        self.assertNotEqual(c1.sequence_number, c2.sequence_number)

    # ======================================================================
    # 3. State transitions draft -> active -> cancelled -> draft
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

        # Activation impossible without dates
        contract2 = self._make_contract()
        contract2.write({'date_start': False, 'date_end': False})
        with self.assertRaises(UserError):
            contract2.action_activate()

    # ======================================================================
    # 4. Correct computation of the yearly line totals
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

        # Editing a line -> total recompute
        line_2027 = contract.line_ids.filtered(lambda l: l.year == 2027)
        line_2027.amount = 20000.0
        contract.invalidate_recordset()
        self.assertEqual(
            contract.total_contract_value,
            15000.0 + 20000.0 + 15000.0,
        )

    # ======================================================================
    # 5. UNIQUE(contract_id, year) constraint
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
    # 6. Expiring/expired cron switch
    # ======================================================================
    def test_expiry_cron_job(self):
        today = ofields.Date.context_today(self.env['res.partner'])
        # NB: we deliberately force the state to 'active' with write() instead of
        # calling action_activate(). action_activate() re-evaluates the lifecycle
        # state immediately (active/expiring/expired based on date_end), which
        # would already transition c1/c2 BEFORE the cron runs, leaving nothing
        # for the cron to do. Forcing 'active' lets us assert the cron itself
        # performs the transition.
        # c1: expires in 30 days -> the cron should switch it to 'expiring'
        c1 = self._make_contract(
            date_start=today - timedelta(days=300),
            date_end=today + timedelta(days=30),
        )
        # c2: expired 10 days ago -> the cron should switch it to 'expired'
        c2 = self._make_contract(
            date_start=today - timedelta(days=400),
            date_end=today - timedelta(days=10),
        )
        # c3: expires in 200 days -> stays 'active'
        c3 = self._make_contract(
            date_start=today - timedelta(days=100),
            date_end=today + timedelta(days=200),
        )
        (c1 + c2 + c3).write({'state': 'active'})

        Contract = self.env['eurekam.maintenance.contract']
        result = Contract._cron_check_expiring_contracts()

        self.assertIn(c1.id, result['expiring'])
        self.assertIn(c2.id, result['expired'])
        self.assertNotIn(c3.id, result['expiring'])
        self.assertNotIn(c3.id, result['expired'])
        self.assertEqual(c1.state, 'expiring')
        self.assertEqual(c2.state, 'expired')
        self.assertEqual(c3.state, 'active')

        # Idempotency: a second call must change nothing
        result2 = Contract._cron_check_expiring_contracts()
        self.assertNotIn(c1.id, result2['expiring'])

    # ======================================================================
    # 7. Renewal wizard: pre-fill
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
    # 8. Renewal wizard: Syntec application + creation
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
    # 9. Invoice creation from contract (by frequency)
    # ======================================================================
    def test_invoice_creation(self):
        """Default annual frequency: 1 invoice for 1 yearly line."""
        today_year = ofields.Date.context_today(self.env['res.partner']).year
        contract = self._make_contract(
            date_start=date(today_year, 1, 1),
            date_end=date(today_year, 12, 31),
            maintenance_amount=8000.0,
        )
        contract.action_activate()
        contract.action_generate_lines()

        # No frequency set -> default 'annual' -> 1 invoice for 8000 EUR
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

        # Re-invoice -> error (all remaining periods already covered)
        with self.assertRaises(UserError):
            contract.action_create_invoices_for_contract()

    def test_invoice_creation_quarterly(self):
        """Quarterly frequency: 4 invoices of a quarter of the amount per year."""
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
        # 1 yearly line * 4 quarters = 4 invoices
        self.assertEqual(len(invoice_ids), 4)
        invoices = self.env['account.move'].browse(invoice_ids)
        # Each invoice = 10000 / 4 = 2500 untaxed
        for inv in invoices:
            self.assertAlmostEqual(inv.invoice_line_ids.price_unit, 2500.0, places=2)
        # The yearly line points to 4 invoices
        line = contract.line_ids.filtered(lambda l: l.year == today_year)
        self.assertEqual(line.invoice_count, 4)
        self.assertTrue(line.is_invoiced)

    def test_invoice_rounding_no_cent_lost(self):
        """Amount not divisible by 4: the sum of the 4 quarterly invoices must
        be EXACTLY equal to the yearly amount (no cent lost).

        48314.25 / 4 = 12078.5625 -> 3 x 12078.56 + 1 x 12078.57 = 48314.25.
        """
        freq_quarterly = self.env.ref('eurekam_maintenance.freq_quarterly')
        freq_overdue = self.env.ref('eurekam_maintenance.freq_overdue')
        today_year = ofields.Date.context_today(self.env['res.partner']).year
        contract = self._make_contract(
            date_start=date(today_year, 1, 1),
            date_end=date(today_year, 12, 31),
            maintenance_amount=48314.25,
            billing_frequency_ids=[(6, 0, [freq_quarterly.id, freq_overdue.id])],
        )
        contract.action_activate()
        contract.action_generate_lines()
        action = contract.action_create_invoices_for_contract()
        invoice_ids = action['domain'][0][2]
        self.assertEqual(len(invoice_ids), 4)
        invoices = self.env['account.move'].browse(invoice_ids)
        total = sum(invoices.mapped(lambda m: m.invoice_line_ids.price_unit))
        self.assertAlmostEqual(total, 48314.25, places=2)
        # 3 fractions of 12078.56 + 1 of 12078.57
        prices = sorted(invoices.mapped(lambda m: m.invoice_line_ids.price_unit))
        self.assertAlmostEqual(prices[0], 12078.56, places=2)
        self.assertAlmostEqual(prices[-1], 12078.57, places=2)

    def test_billable_module_invoices(self):
        """A billable module produces its own invoice lines, only for the years
        within its window, split by the contract cadence (annual here)."""
        freq_annual = self.env.ref('eurekam_maintenance.freq_annual')
        today_year = ofields.Date.context_today(self.env['res.partner']).year
        contract = self._make_contract(
            date_start=date(today_year, 1, 1),
            date_end=date(today_year + 1, 12, 31),
            duration='2y',
            maintenance_amount=10000.0,
            billing_frequency_ids=[(6, 0, [freq_annual.id])],
        )
        contract.action_activate()
        contract.action_generate_lines()
        # Module billed only from next year onward.
        self.env['eurekam.contract.module.line'].create({
            'contract_id': contract.id,
            'module_billing_id': self.env.ref(
                'eurekam_maintenance.mod_bill_stats_premium').id,
            'amount': 4000.0,
            'start_year': today_year + 1,
        })
        action = contract.action_create_invoices_for_contract()
        invoices = self.env['account.move'].browse(action['domain'][0][2])
        # 2 maintenance (1/year x 2 years) + 1 module (next year only) = 3
        self.assertEqual(len(invoices), 3)
        module_invoices = invoices.filtered(
            lambda m: 'Premium Statistics' in (m.invoice_line_ids.name or '')
        )
        self.assertEqual(len(module_invoices), 1)
        self.assertAlmostEqual(
            module_invoices.invoice_line_ids.price_unit, 4000.0, places=2,
        )

    def test_order_wizard_with_module(self):
        """The customer order wizard adds the billable module as its own SO line."""
        freq_annual = self.env.ref('eurekam_maintenance.freq_annual')
        today_year = ofields.Date.context_today(self.env['res.partner']).year
        contract = self._make_contract(
            date_start=date(today_year, 1, 1),
            date_end=date(today_year, 12, 31),
            maintenance_amount=10000.0,
            billing_frequency_ids=[(6, 0, [freq_annual.id])],
            requires_customer_order=True,
        )
        contract.action_activate()
        contract.action_generate_lines()
        self.env['eurekam.contract.module.line'].create({
            'contract_id': contract.id,
            'module_billing_id': self.env.ref(
                'eurekam_maintenance.mod_bill_stats_premium').id,
            'amount': 2000.0,
            'start_year': today_year,
        })
        wizard = self.env['eurekam.maintenance.order.wizard'].with_context(
            default_contract_id=contract.id,
        ).create({
            'year': today_year,
            'customer_po_reference': 'PO-MOD-001',
            'customer_po_date': ofields.Date.context_today(self.env['res.partner']),
        })
        sale_order = self.env['sale.order'].browse(
            wizard.action_create_sale_order()['res_id'])
        # 1 maintenance line + 1 module line
        self.assertEqual(len(sale_order.order_line), 2)
        module_lines = sale_order.order_line.filtered(
            lambda l: 'Premium Statistics' in (l.name or ''))
        self.assertEqual(len(module_lines), 1)
        self.assertAlmostEqual(module_lines.price_unit, 2000.0, places=2)

    def test_billing_unicity_constraint(self):
        """Constraint: 2 period frequencies are forbidden."""
        freq_quarterly = self.env.ref('eurekam_maintenance.freq_quarterly')
        freq_semi_annual = self.env.ref('eurekam_maintenance.freq_semi_annual')
        contract = self._make_contract()
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            contract.billing_frequency_ids = [
                (6, 0, [freq_quarterly.id, freq_semi_annual.id])
            ]

    # ======================================================================
    # 13. sale.order workflow (phase B): order creation from the wizard
    # ======================================================================
    def test_create_customer_order_quarterly(self):
        """Quarterly frequency + requires_customer_order=True: the wizard
        creates a sale.order with 4 lines (Q1/Q2/Q3/Q4), each line = 1
        future invoice."""
        freq_quarterly = self.env.ref('eurekam_maintenance.freq_quarterly')
        freq_overdue = self.env.ref('eurekam_maintenance.freq_overdue')
        today_year = ofields.Date.context_today(self.env['res.partner']).year
        contract = self._make_contract(
            date_start=date(today_year, 1, 1),
            date_end=date(today_year, 12, 31),
            maintenance_amount=20000.0,
            billing_frequency_ids=[(6, 0, [freq_quarterly.id, freq_overdue.id])],
            requires_customer_order=True,
        )
        contract.action_activate()
        contract.action_generate_lines()

        # With requires_customer_order, direct billing is blocked
        with self.assertRaises(UserError):
            contract.action_create_invoices_for_contract()

        # Create the wizard and validate
        wizard = self.env['eurekam.maintenance.order.wizard'].with_context(
            default_contract_id=contract.id,
        ).create({
            'year': today_year,
            'customer_po_reference': 'PO-TEST-001',
            'customer_po_date': ofields.Date.context_today(self.env['res.partner']),
        })
        action = wizard.action_create_sale_order()
        self.assertEqual(action['res_model'], 'sale.order')

        sale_order = self.env['sale.order'].browse(action['res_id'])
        self.assertEqual(sale_order.partner_id, self.partner)
        self.assertEqual(sale_order.eurekam_maintenance_contract_id, contract)
        self.assertEqual(sale_order.eurekam_maintenance_year, today_year)
        self.assertEqual(sale_order.client_order_ref, 'PO-TEST-001')
        # 4 lines of 5000 EUR (= 20000 / 4)
        self.assertEqual(len(sale_order.order_line), 4)
        for line in sale_order.order_line:
            self.assertAlmostEqual(line.price_unit, 5000.0, places=2)
            self.assertEqual(line.product_uom_qty, 1.0)
        # The contract sees the order
        self.assertEqual(contract.sale_order_count, 1)

    # ======================================================================
    # Auto-flag: a company becomes a maintenance establishment on contract
    # ======================================================================
    def test_contract_autoflags_establishment(self):
        """A plain company (not pre-flagged) is automatically marked as a
        maintenance establishment when a contract is created for it; the
        partner_id domain no longer restricts selection to flagged partners."""
        company = self.env['res.partner'].create({
            'name': 'CH Auto-Flag Test',
            'is_company': True,
        })
        self.assertFalse(company.is_maintenance_establishment)
        contract = self._make_contract(partner_id=company.id)
        self.assertTrue(
            company.is_maintenance_establishment,
            "The establishment must be auto-flagged on contract creation.",
        )
        # Re-pointing an existing contract to another company flags it too.
        company2 = self.env['res.partner'].create({
            'name': 'CH Auto-Flag Test 2',
            'is_company': True,
        })
        contract.write({'partner_id': company2.id})
        self.assertTrue(company2.is_maintenance_establishment)

    # ======================================================================
    # 10. res.partner extension
    # ======================================================================
    def test_partner_extension(self):
        # Note refactor option A: we no longer use eurekam.establishment.type
        # but the standard res.partner.category tag. We create a test tag to
        # validate that the classification works through the Odoo tags.
        ch_tag = self.env['res.partner.category'].create({'name': 'CH (Test)'})
        partner = self.env['res.partner'].create({
            'name': 'CHU Bordeaux Test',
            'is_company': True,
            'is_maintenance_establishment': True,
            'department_number': '33',
            'category_id': [(6, 0, [ch_tag.id])],
            'establishment_status': 'client_eurekam',
            'central_purchasing_id': self.env.ref('eurekam_maintenance.cp_uniha').id,
            'nb_workstations': 12,
        })
        self.assertTrue(partner.is_maintenance_establishment)
        self.assertEqual(partner.department_number, '33')
        self.assertIn(ch_tag, partner.category_id)
        self.assertEqual(partner.maintenance_contract_count, 0)

        # Creating a contract -> counter goes to 1
        self._make_contract(partner_id=partner.id)
        partner.invalidate_recordset()
        self.assertEqual(partner.maintenance_contract_count, 1)

    # ======================================================================
    # 11. Security: user vs manager (perm_unlink)
    # ======================================================================
    def test_security_user_vs_manager(self):
        contract = self._make_contract()
        # The salesperson (user) CANNOT delete
        with self.assertRaises(AccessError):
            contract.with_user(self.user_commercial).unlink()
        # The manager can delete
        contract.with_user(self.user_manager).unlink()
        self.assertFalse(contract.exists())

    # ======================================================================
    # 12. Multi-company isolation (record rule)
    # ======================================================================
    def test_company_isolation(self):
        company2 = self.env['res.company'].create({
            'name': 'Eurekam Subsidiary Test',
        })
        partner_co2 = self.env['res.partner'].create({
            'name': 'Establishment Co2',
            'is_company': True,
            'is_maintenance_establishment': True,
            'company_id': company2.id,
        })
        contract_co1 = self._make_contract()
        contract_co2 = self._make_contract(
            partner_id=partner_co2.id,
            company_id=company2.id,
        )

        # The salesperson is linked only to co1 (the default company)
        self.user_commercial.write({
            'company_ids': [(6, 0, [self.env.company.id])],
            'company_id': self.env.company.id,
        })
        contracts_visible = self.env['eurekam.maintenance.contract'].with_user(
            self.user_commercial,
        ).search([])
        self.assertIn(contract_co1, contracts_visible)
        self.assertNotIn(contract_co2, contracts_visible)
