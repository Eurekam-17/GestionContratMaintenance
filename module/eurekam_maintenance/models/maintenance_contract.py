import logging
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Codes de cadence "période" (mutuellement exclusifs sur un même contrat)
PERIOD_CODES = ('annual', 'semi_annual', 'quarterly', 'full_period')
# Codes de timing (mutuellement exclusifs sur un même contrat)
TIMING_CODES = ('overdue', 'upcoming')


class EurekamMaintenanceContract(models.Model):
    _name = 'eurekam.maintenance.contract'
    _description = 'Contrat de maintenance Eurekam'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end desc, sequence_number desc'
    _rec_name = 'name'

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Référence',
        compute='_compute_name',
        store=True,
        index=True,
    )
    sequence_number = fields.Char(
        string='Numéro',
        required=True,
        copy=False,
        readonly=True,
        default='Nouveau',
        index=True,
    )

    # ------------------------------------------------------------------
    # Produit & client
    # ------------------------------------------------------------------
    product_id = fields.Many2one(
        'product.template',
        string='Produit',
        tracking=True,
    )
    product_name = fields.Char(
        string='Libellé produit',
        help="Saisie libre si pas de produit lié.",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Établissement',
        required=True,
        tracking=True,
        index=True,
        domain="[('is_maintenance_establishment', '=', True)]",
        help="Seuls les contacts marqués comme « Établissement de maintenance » "
             "(onglet Maintenance Eurekam de la fiche partenaire) sont sélectionnables.",
    )
    commercial_id = fields.Many2one(
        'res.users',
        string='Commercial',
        default=lambda self: self.env.user,
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Caractéristiques produit / marché
    # ------------------------------------------------------------------
    gen = fields.Selection(
        [
            ('gen1', 'GEN1'),
            ('gen2', 'GEN2'),
            ('upgrade_gen2', 'Upgrade GEN2'),
        ],
        string='Génération',
        tracking=True,
    )
    market_type = fields.Selection(
        [
            ('uniha_2019', 'UniHA 2019'),
            ('uniha_2021', 'UniHA 2021'),
            ('uniha_2023', 'UniHA 2023'),
            ('uniha_2024', 'UniHA 2024'),
            ('uniha_2025', 'UniHA 2025'),
            ('ageps', 'AGEPS'),
            ('market_internal', 'Marché interne'),
            ('private', 'Privé'),
            ('distributor', 'Distributeur'),
        ],
        string='Marché',
        tracking=True,
    )
    order_status = fields.Selection(
        [
            ('received', 'Reçue'),
            ('pending', 'En attente'),
            ('no_po', 'Pas de bon de commande'),
            ('deploying', 'En déploiement'),
            ('suspended', 'Suspendue'),
        ],
        string='Statut commande',
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Dates & durée
    # ------------------------------------------------------------------
    date_start = fields.Date(string='Début du contrat', tracking=True)
    date_end = fields.Date(string='Fin du contrat', tracking=True)
    duration = fields.Selection(
        [
            ('6m', '6 mois'),
            ('1y', '1 an'),
            ('2y', '2 ans'),
            ('3y', '3 ans'),
            ('4y', '4 ans'),
            ('5y', '5 ans'),
        ],
        string='Durée commandée',
        tracking=True,
    )
    days_to_expiry = fields.Integer(
        string='Jours avant expiration',
        compute='_compute_days_to_expiry',
        store=False,
    )
    is_expiring_soon = fields.Boolean(
        string='Expire bientôt',
        compute='_compute_days_to_expiry',
        store=False,
        search='_search_is_expiring_soon',
    )

    # ------------------------------------------------------------------
    # Facturation
    # ------------------------------------------------------------------
    billing_level = fields.Selection(
        [
            ('100', '100 %'),
            ('75', '75 %'),
            ('50', '50 %'),
            ('25', '25 %'),
            ('0', '0 %'),
        ],
        string='Niveau de facturation',
        tracking=True,
    )
    maintenance_amount = fields.Monetary(
        string='Montant de maintenance',
        currency_field='currency_id',
        tracking=True,
    )
    syntec_revision = fields.Selection(
        [('yes', 'Oui'), ('no', 'Non')],
        string='Révision Syntec',
        default='no',
        tracking=True,
    )
    nb_products = fields.Integer(string='Nombre de produits', default=1)
    billing_frequency_ids = fields.Many2many(
        'eurekam.billing.frequency',
        'maintenance_contract_billing_frequency_rel',
        'contract_id', 'frequency_id',
        string='Cadences de facturation',
        tracking=True,
        help="Une meme contrat peut combiner plusieurs cadences (ex: Annuelle + a echu).",
    )
    module_billing_ids = fields.Many2many(
        'eurekam.module.billing',
        'maintenance_contract_module_billing_rel',
        'contract_id', 'module_billing_id',
        string='Facturation Assistance module',
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Lignes annuelles (montants par année 2023, 2024, ...)
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        'eurekam.maintenance.contract.line',
        'contract_id',
        string='Montants annuels',
        copy=True,
    )
    total_contract_value = fields.Monetary(
        string='Valeur totale du contrat',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help="Somme des montants annuels de toutes les lignes du contrat.",
    )
    current_year_amount = fields.Monetary(
        string='Montant année courante',
        currency_field='currency_id',
        compute='_compute_totals',
        store=False,
        help="Montant de la ligne annuelle correspondant à l'année en cours.",
    )
    line_count = fields.Integer(
        string='Nb de lignes annuelles',
        compute='_compute_totals',
        store=True,
    )

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    comment = fields.Text(string='Commentaire')

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------
    state = fields.Selection(
        [
            ('draft', 'Brouillon'),
            ('active', 'Actif'),
            ('expiring', 'Expire bientôt'),
            ('expired', 'Expiré'),
            ('renewed', 'Renouvelé'),
            ('cancelled', 'Annulé'),
        ],
        string='État',
        default='draft',
        tracking=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Société / devise / pays
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    country_id = fields.Many2one(
        'res.country',
        string='Pays',
        compute='_compute_country',
        store=True,
    )

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Couleur')

    # ------------------------------------------------------------------
    # Renouvellement (chainage entre contrats)
    # ------------------------------------------------------------------
    renewed_from_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contrat précédent (renouvelé depuis)',
        readonly=True,
        copy=False,
        index=True,
        help="Renseigné automatiquement par le wizard de renouvellement.",
    )
    renewed_to_ids = fields.One2many(
        'eurekam.maintenance.contract',
        'renewed_from_id',
        string='Contrats suivants (renouvelés vers)',
    )
    renewed_to_count = fields.Integer(
        string='Nb renouvellements',
        compute='_compute_renewed_to_count',
    )

    # ------------------------------------------------------------------
    # Facturation (lien vers account.move + sale.order)
    # ------------------------------------------------------------------
    invoice_count = fields.Integer(
        string='Nb factures',
        compute='_compute_invoice_count',
    )
    requires_customer_order = fields.Boolean(
        string="Nécessite une commande client",
        default=True,
        tracking=True,
        help="Si coché (cas majoritaire), la facturation passe obligatoirement "
             "par une commande client (sale.order) créée à réception du Bon de "
             "Commande client. L'action « Créer les factures du contrat » est "
             "alors désactivée — utiliser « Créer une commande client » à la "
             "place.\n"
             "Si décoché (cas rare : certains établissements privés), la "
             "facturation se fait directement sur le contrat sans BC.",
    )
    sale_order_ids = fields.One2many(
        'sale.order',
        'eurekam_maintenance_contract_id',
        string="Commandes client",
    )
    sale_order_count = fields.Integer(
        string="Nb commandes client",
        compute='_compute_sale_order_count',
    )

    # ==================================================================
    # Compute / Search / Constraints
    # ==================================================================

    @api.depends('sequence_number', 'partner_id', 'product_id', 'product_name')
    def _compute_name(self):
        for rec in self:
            seq = rec.sequence_number or ''
            partner = rec.partner_id.display_name or ''
            prod = rec.product_id.display_name or rec.product_name or ''
            parts = [p for p in (seq, partner, prod) if p and p != 'Nouveau']
            rec.name = ' - '.join(parts) if parts else 'Contrat de maintenance'

    @api.depends('date_end')
    def _compute_days_to_expiry(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_end:
                rec.days_to_expiry = (rec.date_end - today).days
                rec.is_expiring_soon = 0 <= rec.days_to_expiry <= 90
            else:
                rec.days_to_expiry = 0
                rec.is_expiring_soon = False

    @api.depends('partner_id')
    def _compute_country(self):
        for rec in self:
            rec.country_id = rec.partner_id.country_id

    @api.depends('line_ids', 'line_ids.amount', 'line_ids.year')
    def _compute_totals(self):
        today_year = fields.Date.context_today(self).year
        for rec in self:
            rec.total_contract_value = sum(rec.line_ids.mapped('amount'))
            rec.line_count = len(rec.line_ids)
            current = rec.line_ids.filtered(lambda l: l.year == today_year)
            rec.current_year_amount = sum(current.mapped('amount'))

    @api.depends('renewed_to_ids')
    def _compute_renewed_to_count(self):
        for rec in self:
            rec.renewed_to_count = len(rec.renewed_to_ids)

    @api.depends('line_ids.invoice_ids')
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.line_ids.mapped('invoice_ids'))

    @api.depends('sale_order_ids')
    def _compute_sale_order_count(self):
        for rec in self:
            rec.sale_order_count = len(rec.sale_order_ids)

    def _search_is_expiring_soon(self, operator, value):
        today = fields.Date.context_today(self)
        in_90_days = fields.Date.add(today, days=90)
        truthy = (operator == '=' and value) or (operator == '!=' and not value)
        if truthy:
            return [('date_end', '>=', today), ('date_end', '<=', in_90_days)]
        return ['|', ('date_end', '<', today), ('date_end', '>', in_90_days)]

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_(
                    "La date de fin (%(end)s) doit être postérieure à la date "
                    "de début (%(start)s).",
                    end=rec.date_end, start=rec.date_start,
                ))

    @api.constrains('billing_frequency_ids')
    def _check_billing_unicity(self):
        """Garantit l'unicite des cadences :
        - au plus 1 cadence de periode (annual/semi_annual/quarterly/full_period)
        - au plus 1 cadence de timing (overdue/upcoming)
        Les conditions sont bloquees le temps du contrat, donc inutile d'en cumuler.
        """
        for rec in self:
            codes = rec.billing_frequency_ids.mapped('code')
            periods = [c for c in codes if c in PERIOD_CODES]
            timings = [c for c in codes if c in TIMING_CODES]
            if len(periods) > 1:
                names = rec.billing_frequency_ids.filtered(
                    lambda f: f.code in PERIOD_CODES
                ).mapped('name')
                raise ValidationError(_(
                    "Une seule cadence de période est autorisée par contrat "
                    "(Annuelle, Semestrielle, Trimestrielle ou Période intégrale).\n"
                    "Actuellement sélectionné(es) : %s",
                    ', '.join(names),
                ))
            if len(timings) > 1:
                names = rec.billing_frequency_ids.filtered(
                    lambda f: f.code in TIMING_CODES
                ).mapped('name')
                raise ValidationError(_(
                    "Une seule cadence de timing est autorisée par contrat "
                    "(À échu ou À échoir).\n"
                    "Actuellement sélectionné(es) : %s",
                    ', '.join(names),
                ))

    # ==================================================================
    # CRUD
    # ==================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('sequence_number') or vals.get('sequence_number') == 'Nouveau':
                vals['sequence_number'] = self.env['ir.sequence'].next_by_code(
                    'eurekam.maintenance.contract'
                ) or 'Nouveau'
        return super().create(vals_list)

    # ==================================================================
    # Actions
    # ==================================================================

    def action_activate(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled'):
                raise UserError(_(
                    "Seul un contrat en brouillon ou annulé peut être activé."
                ))
            if not rec.date_start or not rec.date_end:
                raise UserError(_(
                    "Renseigner les dates de début et de fin avant d'activer."
                ))
            if not rec.product_id:
                raise UserError(_(
                    "Renseigner le produit (champ « Produit » lié à la base "
                    "articles) avant d'activer le contrat. Le champ « Libellé "
                    "produit » seul ne suffit pas : les factures générées "
                    "ensuite ont besoin du product_id pour résoudre "
                    "automatiquement le compte de revenu et les taxes."
                ))
            rec.state = 'active'
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state != 'cancelled':
                rec.state = 'cancelled'
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_(
                    "Seul un contrat annulé peut revenir en brouillon."
                ))
            rec.state = 'draft'
        return True

    def action_generate_lines(self):
        """Génère les lignes annuelles vides entre date_start et date_end.

        Crée une ligne par année (year = date_start.year ... date_end.year),
        avec amount=0 par défaut. Les lignes existantes ne sont pas écrasées.
        Si maintenance_amount > 0 et qu'aucune ligne n'existe encore, on
        pré-remplit chaque ligne avec ce montant comme valeur de départ.
        """
        Line = self.env['eurekam.maintenance.contract.line']
        for rec in self:
            if not rec.date_start or not rec.date_end:
                raise UserError(_(
                    "Définir les dates de début et de fin avant de générer "
                    "les lignes annuelles."
                ))
            existing_years = set(rec.line_ids.mapped('year'))
            default_amount = rec.maintenance_amount if not existing_years else 0.0
            new_vals = []
            for year in range(rec.date_start.year, rec.date_end.year + 1):
                if year not in existing_years:
                    new_vals.append({
                        'contract_id': rec.id,
                        'year': year,
                        'amount': default_amount,
                    })
            if new_vals:
                Line.create(new_vals)
        return True

    def action_view_lines(self):
        """Ouvre la vue liste des lignes annuelles filtrée sur ce contrat."""
        self.ensure_one()
        return {
            'name': _("Lignes annuelles — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract.line',
            'view_mode': 'list,pivot,graph,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }

    def action_open_renewal_wizard(self):
        """Ouvre le wizard de renouvellement pre-rempli depuis ce contrat."""
        self.ensure_one()
        if self.state in ('renewed', 'cancelled'):
            raise UserError(_(
                "Ce contrat est %s, impossible de le renouveler.",
                dict(self._fields['state'].selection).get(self.state),
            ))
        return {
            'name': _("Renouveler — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.contract.renewal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    def action_view_renewed_from(self):
        """Ouvre le contrat dont celui-ci est le renouvellement."""
        self.ensure_one()
        if not self.renewed_from_id:
            return False
        return {
            'name': _("Contrat précédent"),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract',
            'res_id': self.renewed_from_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_renewed_to(self):
        """Ouvre le ou les contrats qui ont renouvele celui-ci."""
        self.ensure_one()
        if not self.renewed_to_ids:
            return False
        if len(self.renewed_to_ids) == 1:
            return {
                'name': _("Contrat de renouvellement"),
                'type': 'ir.actions.act_window',
                'res_model': 'eurekam.maintenance.contract',
                'res_id': self.renewed_to_ids[0].id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'name': _("Contrats de renouvellement"),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.renewed_to_ids.ids)],
        }

    # ==================================================================
    # Facturation (creation de account.move)
    # ==================================================================

    # ==================================================================
    # Facturation : helpers de cadence
    # ==================================================================

    def _get_billing_period_code(self):
        """Code de période courante du contrat (annual par defaut si non defini)."""
        self.ensure_one()
        for code in self.billing_frequency_ids.mapped('code'):
            if code in PERIOD_CODES:
                return code
        return 'annual'

    def _get_billing_timing_code(self):
        """Code de timing : 'overdue' (echu) ou 'upcoming' (a echoir, par defaut)."""
        self.ensure_one()
        for code in self.billing_frequency_ids.mapped('code'):
            if code in TIMING_CODES:
                return code
        return 'upcoming'

    @staticmethod
    def _periods_for_year(year, amount, period_code):
        """Retourne la liste des sous-periodes d'une annee :
        [(label, fraction_amount, period_start, period_end), ...]

        - 'annual'      -> 1 periode (annee entiere)
        - 'semi_annual' -> 2 periodes (S1, S2), fraction = amount/2
        - 'quarterly'   -> 4 periodes (T1..T4), fraction = amount/4
        - 'full_period' -> traite a part (action_create_invoices_for_contract)
        """
        if period_code == 'quarterly':
            return [
                ("T1 %s" % year, amount / 4.0, date(year, 1, 1), date(year, 3, 31)),
                ("T2 %s" % year, amount / 4.0, date(year, 4, 1), date(year, 6, 30)),
                ("T3 %s" % year, amount / 4.0, date(year, 7, 1), date(year, 9, 30)),
                ("T4 %s" % year, amount / 4.0, date(year, 10, 1), date(year, 12, 31)),
            ]
        if period_code == 'semi_annual':
            return [
                ("S1 %s" % year, amount / 2.0, date(year, 1, 1), date(year, 6, 30)),
                ("S2 %s" % year, amount / 2.0, date(year, 7, 1), date(year, 12, 31)),
            ]
        # 'annual' par defaut
        return [
            ("Année %s" % year, amount, date(year, 1, 1), date(year, 12, 31)),
        ]

    @staticmethod
    def _invoice_date_for_period(period_start, period_end, timing_code):
        """Date d'emission d'une facture pour une periode donnee.

        - 'overdue'  (echu)     -> fin de periode
        - 'upcoming' (a echoir) -> debut de periode (defaut)
        """
        if timing_code == 'overdue':
            return period_end
        return period_start

    # ==================================================================
    # Facturation : actions
    # ==================================================================

    def action_create_invoices_for_contract(self):
        """Cree toutes les factures brouillon couvrant la duree restante du contrat.

        Selon la cadence (billing_frequency_ids) :
          - 'annual'      -> 1 facture par annee restante
          - 'semi_annual' -> 2 factures par annee restante (S1, S2)
          - 'quarterly'   -> 4 factures par annee restante (T1..T4)
          - 'full_period' -> 1 facture globale = somme de toutes les lignes
          - 'overdue'     -> date facture = fin de periode
          - 'upcoming'    -> date facture = debut de periode (defaut)

        Idempotent : les periodes deja facturees ne sont pas recreees.
        """
        today = fields.Date.context_today(self)
        created_invoices = self.env['account.move']

        for contract in self:
            if contract.requires_customer_order:
                raise UserError(_(
                    "Le contrat %s nécessite une commande client (BC). "
                    "La facturation directe est désactivée pour ce contrat.\n"
                    "Cliquer sur « Créer une commande client » à la place : "
                    "un sale.order sera créé avec les lignes correspondant à "
                    "la cadence, et chaque ligne pourra ensuite être facturée "
                    "indépendamment via le workflow Sales natif.",
                    contract.sequence_number,
                ))
            if not contract.line_ids:
                raise UserError(_(
                    "Aucune ligne annuelle pour ce contrat. Cliquer sur "
                    "« Générer les lignes annuelles » d'abord."
                ))
            if not contract.product_id:
                raise UserError(_(
                    "Le contrat %s n'a pas de produit lié (champ « Produit »).\n"
                    "Renseigner un produit de la base articles avant de générer "
                    "les factures, sinon le compte de revenu et les taxes ne "
                    "pourront pas être résolus automatiquement.",
                    contract.sequence_number,
                ))

            period_code = contract._get_billing_period_code()
            timing_code = contract._get_billing_timing_code()

            # ---- Cas 1 : Période intégrale = 1 facture globale ----
            if period_code == 'full_period':
                existing = contract.line_ids.mapped('invoice_ids')
                if existing:
                    raise UserError(_(
                        "Une ou plusieurs factures existent déjà pour ce contrat "
                        "en « Période intégrale » : %s. Supprimer les factures "
                        "existantes d'abord si rejeu nécessaire.",
                        ', '.join(existing.mapped('display_name')),
                    ))
                invoice = contract._create_invoice_full_period()
                contract.line_ids.write({'invoice_ids': [(4, invoice.id)]})
                created_invoices |= invoice
                continue

            # ---- Cas 2 : cadence sous-annuelle (annual/semi_annual/quarterly) ----
            # Iterer sur les lignes futures (annee courante et au-dela).
            future_lines = contract.line_ids.filtered(lambda l: l.year >= today.year)
            for line in future_lines.sorted(key=lambda l: l.year):
                periods = contract._periods_for_year(
                    line.year, line.amount, period_code,
                )
                # On suppose que les N premieres periodes ont deja ete creees
                # dans l'ordre chronologique (donc invoice_count = nb deja faites)
                already_created = line.invoice_count
                for label, fraction, p_start, p_end in periods[already_created:]:
                    inv_date = contract._invoice_date_for_period(
                        p_start, p_end, timing_code,
                    )
                    invoice = contract._create_invoice_period(
                        line, label, fraction, inv_date,
                    )
                    line.invoice_ids = [(4, invoice.id)]
                    created_invoices |= invoice

        if not created_invoices:
            raise UserError(_(
                "Aucune nouvelle facture à créer (toutes les périodes restantes "
                "sont déjà facturées)."
            ))

        for contract in self:
            contract.message_post(body=_(
                "%d facture(s) brouillon créée(s) selon la cadence du contrat.",
                len(created_invoices),
            ))

        return {
            'name': _("Factures créées (%d)", len(created_invoices)),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_invoices.ids)],
            'target': 'current',
        }

    def _create_invoice_period(self, line, period_label, fraction_amount, invoice_date):
        """Cree une facture brouillon pour une sous-periode (T1, S1, Année N, etc.)."""
        self.ensure_one()
        product = self.product_id
        product_var = product.product_variant_id if product else False
        description = _(
            "Maintenance %(prod)s — %(period)s",
            prod=product.name or self.product_name or '',
            period=period_label,
        )
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_origin': "%s / %s" % (self.sequence_number, period_label),
            'invoice_date': invoice_date,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': description,
                'product_id': product_var.id if product_var else False,
                'quantity': 1.0,
                'price_unit': fraction_amount,
            })],
        })
        return invoice

    def _create_invoice_full_period(self):
        """Cree une facture brouillon unique couvrant l'integralite du contrat.

        Une seule ligne de facture pour la somme totale (total_contract_value).
        Date d'emission selon le timing :
          - a echoir (upcoming) -> date_start
          - echu     (overdue)  -> date_end
          - defaut              -> aujourd'hui
        """
        self.ensure_one()
        timing_code = self._get_billing_timing_code()
        if timing_code == 'overdue':
            invoice_date = self.date_end or fields.Date.context_today(self)
        else:
            invoice_date = self.date_start or fields.Date.context_today(self)

        product = self.product_id
        product_var = product.product_variant_id if product else False
        total = sum(self.line_ids.mapped('amount'))
        description = _(
            "Maintenance %(prod)s — Période intégrale (%(start)s → %(end)s)",
            prod=product.name or self.product_name or '',
            start=self.date_start or '?',
            end=self.date_end or '?',
        )
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_origin': self.sequence_number,
            'invoice_date': invoice_date,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': description,
                'product_id': product_var.id if product_var else False,
                'quantity': 1.0,
                'price_unit': total,
            })],
        })
        return invoice

    def action_view_invoices(self):
        """Ouvre les factures clients liees a ce contrat."""
        self.ensure_one()
        # Factures directes (cas sans BC) + factures via sale.order (cas standard)
        invoices_direct = self.line_ids.mapped('invoice_ids')
        invoices_from_so = self.sale_order_ids.mapped('invoice_ids')
        invoices = invoices_direct | invoices_from_so
        if not invoices:
            raise UserError(_("Aucune facture n'est encore liée à ce contrat."))
        if len(invoices) == 1:
            return {
                'name': _("Facture"),
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': invoices.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'name': _("Factures — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
        }

    # ==================================================================
    # Commandes client (sale.order)
    # ==================================================================

    def action_open_create_order_wizard(self):
        """Ouvre le wizard de creation d'une commande client maintenance."""
        self.ensure_one()
        if self.state in ('cancelled', 'renewed'):
            raise UserError(_(
                "Impossible de créer une commande sur un contrat %s.",
                dict(self._fields['state'].selection).get(self.state),
            ))
        return {
            'name': _("Créer une commande client — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.order.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    def action_view_sale_orders(self):
        """Ouvre les commandes client (sale.order) liees a ce contrat."""
        self.ensure_one()
        orders = self.sale_order_ids
        if not orders:
            raise UserError(_(
                "Aucune commande client n'est encore liée à ce contrat. "
                "Cliquer sur « Créer une commande client » pour en créer une."
            ))
        if len(orders) == 1:
            return {
                'name': _("Commande client"),
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': orders.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'name': _("Commandes client — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', orders.ids)],
        }

    # ==================================================================
    # Cron expiration et templates de notification
    # ==================================================================

    def _get_expiring_recipients(self):
        """Destinataires de l'email 'expirant bientot' : commercial seul."""
        self.ensure_one()
        partners = self.env['res.partner']
        if self.commercial_id.partner_id:
            partners |= self.commercial_id.partner_id
        return partners

    def _get_expired_recipients(self):
        """Destinataires de l'email 'expire' : commercial + tous les managers."""
        self.ensure_one()
        partners = self._get_expiring_recipients()
        managers_group = self.env.ref(
            'eurekam_maintenance.group_maintenance_manager',
            raise_if_not_found=False,
        )
        if managers_group:
            partners |= managers_group.users.mapped('partner_id').filtered('email')
        return partners

    @api.model
    def _cron_check_expiring_contracts(self):
        """Job quotidien : bascule les etats actif/expirant/expire et envoie les emails.

        Regles :
        - Si 0 <= days_to_expiry <= 90 et state == 'active' : passe en 'expiring',
          envoie email au commercial.
        - Si days_to_expiry < 0 et state in ('active', 'expiring') : passe en 'expired',
          envoie email au commercial + aux managers.

        Idempotent : si l'etat est deja le bon (deja notifie precedemment),
        rien n'est fait pour ce contrat.
        """
        today = fields.Date.context_today(self)
        candidates = self.search([
            ('state', 'in', ('active', 'expiring')),
            ('date_end', '!=', False),
        ])
        _logger.info(
            "Cron expiration : %d contrats a verifier.",
            len(candidates),
        )

        expiring_template = self.env.ref(
            'eurekam_maintenance.mail_template_contract_expiring',
            raise_if_not_found=False,
        )
        expired_template = self.env.ref(
            'eurekam_maintenance.mail_template_contract_expired',
            raise_if_not_found=False,
        )

        passed_to_expiring = self.env['eurekam.maintenance.contract']
        passed_to_expired = self.env['eurekam.maintenance.contract']

        for contract in candidates:
            days = (contract.date_end - today).days
            if days < 0 and contract.state != 'expired':
                contract.write({'state': 'expired'})
                passed_to_expired |= contract
            elif 0 <= days <= 90 and contract.state == 'active':
                contract.write({'state': 'expiring'})
                passed_to_expiring |= contract

        # ---- Envoi des emails (en queue, pas force_send=True) -----
        if expiring_template:
            for contract in passed_to_expiring:
                try:
                    expiring_template.with_context(
                        lang=contract.commercial_id.lang or 'fr_FR',
                    ).send_mail(
                        contract.id,
                        force_send=False,
                        email_layout_xmlid='mail.mail_notification_light',
                    )
                except Exception as exc:
                    _logger.warning(
                        "Echec envoi email 'expirant' pour %s : %s",
                        contract.sequence_number, exc,
                    )

        if expired_template:
            for contract in passed_to_expired:
                try:
                    expired_template.with_context(
                        lang=contract.commercial_id.lang or 'fr_FR',
                    ).send_mail(
                        contract.id,
                        force_send=False,
                        email_layout_xmlid='mail.mail_notification_light',
                    )
                except Exception as exc:
                    _logger.warning(
                        "Echec envoi email 'expire' pour %s : %s",
                        contract.sequence_number, exc,
                    )

        _logger.info(
            "Cron expiration : %d -> 'expiring', %d -> 'expired'.",
            len(passed_to_expiring),
            len(passed_to_expired),
        )
        return {
            'expiring': passed_to_expiring.ids,
            'expired': passed_to_expired.ids,
        }
