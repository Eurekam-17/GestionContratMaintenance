import logging
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# "Period" billing codes (mutually exclusive on a given contract)
PERIOD_CODES = ('annual', 'semi_annual', 'quarterly', 'full_period')
# "Timing" billing codes (mutually exclusive on a given contract)
TIMING_CODES = ('overdue', 'upcoming')

# ----------------------------------------------------------------------------
# Customer-facing wording, written in French on purpose.
#
# These strings end up verbatim on the quotation, the customer order and the
# invoice the hospital receives, so the sales team specified their exact French
# form ("4 postes - 1er trimestre 2026").
#
# They are NOT wrapped in _(): Odoo does not extract this module's Python
# translatable terms on the odoo.sh deployment -- exporting `sale` in fr_FR
# yields 140 `code:` entries, exporting this module yields 0 -- so every _()
# string here renders in English whatever the user's language. Writing the
# French directly is the only way to honour the specification today.
#
# Everything else in the module keeps the English-source + fr.po convention;
# model, field, view and data translations work normally. If the extraction
# problem is ever solved, only this block has to move back to _().
# ----------------------------------------------------------------------------
PERIOD_LABELS = {
    'Q1': "1er trimestre %(year)s",
    'Q2': "2ème trimestre %(year)s",
    'Q3': "3ème trimestre %(year)s",
    'Q4': "4ème trimestre %(year)s",
    'H1': "1er semestre %(year)s",
    'H2': "2ème semestre %(year)s",
    'Y': "Année %(year)s",
}
WORKSTATION_LABEL = {'one': "%(n)s poste", 'many': "%(n)s postes"}
FULL_PERIOD_LABEL = "Période complète (du %(start)s au %(end)s)"
MODULE_FULL_PERIOD_LABEL = "%(module)s - Période complète (%(n)d an(s))"


def _split_amount(amount, n):
    """Split an amount into n fractions rounded to 2 decimals.

    The first n-1 fractions are round(amount/n, 2); the last one absorbs the
    rounding remainder so that the sum of the fractions is EXACTLY equal to the
    initial amount (avoids losing the cent on the quarterly / semi-annual
    frequencies).
    """
    if n <= 1:
        return [amount]
    base = round(amount / n, 2)
    parts = [base] * (n - 1)
    parts.append(round(amount - base * (n - 1), 2))
    return parts


class EurekamMaintenanceContract(models.Model):
    _name = 'eurekam.maintenance.contract'
    _description = 'Eurekam Maintenance Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end desc, sequence_number desc'
    _rec_name = 'name'

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Reference',
        compute='_compute_name',
        store=True,
        index=True,
    )
    sequence_number = fields.Char(
        string='Number',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        index=True,
    )

    # ------------------------------------------------------------------
    # Product & customer
    # ------------------------------------------------------------------
    product_id = fields.Many2one(
        'product.template',
        string='Product',
        tracking=True,
    )
    product_name = fields.Char(
        string='Product Label',
        help="Wording used on the customer order and invoice lines, before the "
             "number of workstations and the billed period.\n"
             "Pre-filled from the product's sales description ('Sales' tab, "
             "'Sales Description'); can be overridden manually.",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Establishment',
        required=True,
        tracking=True,
        index=True,
        domain="[('is_company', '=', True)]",
        help="Any client company can be selected. It is automatically flagged "
             "as a Maintenance Establishment when the contract is created.",
    )
    commercial_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        default=lambda self: self.env.user,
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Product / market characteristics
    # ------------------------------------------------------------------
    gen = fields.Selection(
        [
            ('gen1', 'GEN1'),
            ('gen2', 'GEN2'),
            ('upgrade_gen2', 'Upgrade GEN2'),
        ],
        string='Generation',
        tracking=True,
    )
    # DEPRECATED: replaced by market_type_ids (editable, multi-valued list).
    # Kept one release so the migration can copy values; removed in a later
    # version. No longer shown in any view.
    market_type = fields.Selection(
        [
            ('uniha_2019', 'UniHA 2019'),
            ('uniha_2021', 'UniHA 2021'),
            ('uniha_2023', 'UniHA 2023'),
            ('uniha_2024', 'UniHA 2024'),
            ('uniha_2025', 'UniHA 2025'),
            ('ageps', 'AGEPS'),
            ('market_internal', 'Internal Market'),
            ('private', 'Private'),
            ('distributor', 'Distributor'),
        ],
        string='Market (legacy)',
    )
    market_type_ids = fields.Many2many(
        'eurekam.market.type',
        'maintenance_contract_market_type_rel',
        'contract_id', 'market_type_id',
        string='Market',
        tracking=True,
        help="Market / public tender. Editable list, several values allowed.",
    )
    order_status = fields.Selection(
        [
            ('quote_sent', 'Quote Sent'),
            ('received', 'Received'),
            ('pending', 'Pending'),
            ('no_po', 'Billing Without PO'),
            ('deploying', 'Deploying'),
            ('suspended', 'Suspended'),
        ],
        string='Order Status',
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Dates & duration
    # ------------------------------------------------------------------
    date_start = fields.Date(string='Contract Start', tracking=True)
    date_end = fields.Date(string='Contract End', tracking=True)
    duration = fields.Selection(
        [
            ('6m', '6 months'),
            ('1y', '1 year'),
            ('2y', '2 years'),
            ('3y', '3 years'),
            ('4y', '4 years'),
            ('5y', '5 years'),
        ],
        string='Contract Duration',
        help="Duration the contract was ordered for. Informational: the "
             "billing periods are derived from the start and end dates, "
             "not from this field.",
        tracking=True,
    )
    days_to_expiry = fields.Integer(
        string='Days to Expiry',
        compute='_compute_days_to_expiry',
        store=False,
    )
    is_expiring_soon = fields.Boolean(
        string='Expiring Soon',
        compute='_compute_days_to_expiry',
        store=False,
        search='_search_is_expiring_soon',
    )

    # ------------------------------------------------------------------
    # Billing
    # ------------------------------------------------------------------
    billing_level = fields.Selection(
        [
            ('100', '100 %'),
            ('75', '75 %'),
            ('50', '50 %'),
            ('25', '25 %'),
            ('0', '0 %'),
        ],
        string='Billing Level',
        tracking=True,
    )
    maintenance_amount = fields.Monetary(
        string='Maintenance Amount',
        currency_field='currency_id',
        tracking=True,
        help="Reference amount per year, used to pre-fill the yearly lines on "
             "the first 'Generate Yearly Lines'.\n"
             "It is NOT what gets billed: the contract value and the invoices "
             "are built from the 'Yearly Amounts' tab, which is where an "
             "amount that changes from year to year must be entered.",
    )
    syntec_revision = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Syntec Revision',
        default='no',
        tracking=True,
    )
    nb_products = fields.Integer(string='Number of Products', default=1)
    billing_frequency_ids = fields.Many2many(
        'eurekam.billing.frequency',
        'maintenance_contract_billing_frequency_rel',
        'contract_id', 'frequency_id',
        string='Billing Frequencies',
        tracking=True,
        help="A single contract may combine several frequencies (e.g. Annual + Overdue).",
    )
    module_billing_ids = fields.Many2many(
        'eurekam.module.billing',
        'maintenance_contract_module_billing_rel',
        'contract_id', 'module_billing_id',
        string='Module Assistance Billing',
        tracking=True,
    )
    contract_module_line_ids = fields.One2many(
        'eurekam.contract.module.line',
        'contract_id',
        string='Billable Modules',
        copy=True,
        help="Assistance modules billed on top of the maintenance, each with "
             "its own annual amount and a start year. They generate their own "
             "order / invoice lines for the years within their window.",
    )

    # ------------------------------------------------------------------
    # Yearly lines (amounts per year 2023, 2024, ...)
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        'eurekam.maintenance.contract.line',
        'contract_id',
        string='Yearly Amounts',
        copy=True,
    )
    total_contract_value = fields.Monetary(
        string='Total Contract Value',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help="Sum of the yearly amounts of all contract lines.",
    )
    current_year_amount = fields.Monetary(
        string='Current Year Amount',
        currency_field='currency_id',
        compute='_compute_current_year_amount',
        store=False,
        help="Amount of the yearly line matching the current year.",
    )
    line_count = fields.Integer(
        string='Yearly Lines Count',
        compute='_compute_totals',
        store=True,
    )

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    comment = fields.Text(string='Comment')

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('expiring', 'Expiring Soon'),
            ('expired', 'Expired'),
            ('renewed', 'Renewed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Company / currency / country
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    country_id = fields.Many2one(
        'res.country',
        string='Country',
        compute='_compute_country',
        store=True,
    )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color')

    # ------------------------------------------------------------------
    # Renewal (chaining between contracts)
    # ------------------------------------------------------------------
    renewed_from_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Previous Contract (renewed from)',
        readonly=True,
        copy=False,
        index=True,
        help="Set automatically by the renewal wizard.",
    )
    renewed_to_ids = fields.One2many(
        'eurekam.maintenance.contract',
        'renewed_from_id',
        string='Next Contracts (renewed to)',
    )
    renewed_to_count = fields.Integer(
        string='Renewals Count',
        compute='_compute_renewed_to_count',
    )

    # ------------------------------------------------------------------
    # Billing (link to account.move + sale.order)
    # ------------------------------------------------------------------
    invoice_count = fields.Integer(
        string='Invoices Count',
        compute='_compute_invoice_count',
    )
    sale_order_ids = fields.One2many(
        'sale.order',
        'eurekam_maintenance_contract_id',
        string="Customer Orders",
    )
    sale_order_count = fields.Integer(
        string="Customer Orders Count",
        compute='_compute_sale_order_count',
    )

    # ==================================================================
    # Compute / Search / Constraints
    # ==================================================================

    @api.depends('sequence_number', 'partner_id', 'partner_id.display_name',
                 'product_id', 'product_id.display_name', 'product_name')
    def _compute_name(self):
        for rec in self:
            seq = rec.sequence_number or ''
            partner = rec.partner_id.display_name or ''
            prod = rec.product_id.display_name or rec.product_name or ''
            parts = [p for p in (seq, partner, prod) if p and p != 'New']
            rec.name = ' - '.join(parts) if parts else 'Maintenance Contract'

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

    @api.depends('partner_id', 'partner_id.country_id')
    def _compute_country(self):
        for rec in self:
            rec.country_id = rec.partner_id.country_id

    @api.depends('line_ids', 'line_ids.amount')
    def _compute_totals(self):
        # Stored computed fields only (store=True). Kept in a dedicated method,
        # separate from the non-stored current_year_amount, to avoid Odoo 18's
        # "inconsistent 'store'/'compute_sudo'" warning that is raised when a
        # single compute method feeds both stored and non-stored fields.
        for rec in self:
            rec.total_contract_value = sum(rec.line_ids.mapped('amount'))
            rec.line_count = len(rec.line_ids)

    @api.depends('line_ids', 'line_ids.amount', 'line_ids.year')
    def _compute_current_year_amount(self):
        # Non-stored (store=False): depends on the current year, which changes
        # over time without the record being written, so it must be recomputed
        # on read rather than persisted.
        today_year = fields.Date.context_today(self).year
        for rec in self:
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
                    "The end date (%(end)s) must be after the start date (%(start)s).",
                    end=rec.date_end, start=rec.date_start,
                ))

    # ==================================================================
    # Onchange
    # ==================================================================

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Pre-fill the product label from the product's sales description.

        The 'Sales Description' (product.template.description_sale, shown as
        "Description du devis" in the Sales tab) is the wording the sales team
        maintains for quotations; reusing it keeps the contract, the customer
        order and the invoice consistent. Falls back to the product name when
        no sales description is set. The user can still override the result.
        """
        for rec in self:
            if not rec.product_id:
                continue
            description = (rec.product_id.description_sale or '').strip()
            rec.product_name = description or rec.product_id.name

    @api.constrains('billing_frequency_ids')
    def _check_billing_unicity(self):
        """Ensure billing frequency uniqueness:
        - at most 1 period frequency (annual/semi_annual/quarterly/full_period)
        - at most 1 timing frequency (overdue/upcoming)
        Conditions are locked for the contract duration, no need to combine them.
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
                    "Only one period frequency is allowed per contract "
                    "(Annual, Semi-annual, Quarterly or Full period).\n"
                    "Currently selected: %s",
                    ', '.join(names),
                ))
            if len(timings) > 1:
                names = rec.billing_frequency_ids.filtered(
                    lambda f: f.code in TIMING_CODES
                ).mapped('name')
                raise ValidationError(_(
                    "Only one timing frequency is allowed per contract "
                    "(Overdue or Upcoming).\n"
                    "Currently selected: %s",
                    ', '.join(names),
                ))

    # ==================================================================
    # CRUD
    # ==================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('sequence_number') or vals.get('sequence_number') == 'New':
                vals['sequence_number'] = self.env['ir.sequence'].next_by_code(
                    'eurekam.maintenance.contract'
                ) or 'New'
        contracts = super().create(vals_list)
        contracts._ensure_establishments_flagged()
        return contracts

    def write(self, vals):
        res = super().write(vals)
        if vals.get('partner_id'):
            self._ensure_establishments_flagged()
        return res

    def _ensure_establishments_flagged(self):
        """A company that gets a maintenance contract becomes a maintenance
        establishment: it then shows up in the Establishments menu and exposes
        the Eurekam Maintenance tab on its contact form. sudo() because a
        maintenance user may not have write access on res.partner."""
        to_flag = self.partner_id.filtered(
            lambda p: not p.is_maintenance_establishment
        )
        if to_flag:
            to_flag.sudo().write({'is_maintenance_establishment': True})

    # ==================================================================
    # Lifecycle helpers & actions
    # ==================================================================

    def _evaluate_lifecycle_state(self):
        """Determine the expected state of a contract based on date_end and today.

        Does not modify the record. Returns the expected state code.
        Logic:
        - draft / renewed / cancelled / expired -> final states, unchanged
        - otherwise (active / expiring), recompute based on days_to_expiry:
            * days < 0       -> 'expired'
            * 0 <= days <=90 -> 'expiring'
            * days > 90      -> 'active'

        Used by action_activate and action_recompute_state, and mirrors the
        logic of _cron_check_expiring_contracts (without sending emails).
        """
        self.ensure_one()
        if self.state in ('draft', 'renewed', 'cancelled', 'expired'):
            return self.state
        if not self.date_end:
            return self.state
        today = fields.Date.context_today(self)
        days = (self.date_end - today).days
        if days < 0:
            return 'expired'
        if 0 <= days <= 90:
            return 'expiring'
        return 'active'

    def action_activate(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled'):
                raise UserError(_(
                    "Only a draft or cancelled contract can be activated."
                ))
            if not rec.date_start or not rec.date_end:
                raise UserError(_(
                    "Set the start and end dates before activating."
                ))
            if not rec.product_id:
                raise UserError(_(
                    "Set the product (the 'Product' field linked to the product "
                    "catalog) before activating the contract. The 'Product Label' "
                    "field alone is not enough: the invoices generated afterwards "
                    "need the product_id to resolve the income account and taxes "
                    "automatically."
                ))
            # Transient switch to 'active' then immediate re-evaluation on date_end.
            # Covers the historical-import case / activation of a contract whose
            # date_end is already past (without waiting for the daily cron).
            rec.state = 'active'
            new_state = rec._evaluate_lifecycle_state()
            if new_state != rec.state:
                rec.message_post(body=(
                    "Activation suivie d'une réévaluation immédiate sur la "
                    "date de fin (%(end)s, %(days)s jours) : statut ajusté à "
                    "« %(state)s »." % dict(
                    end=rec.date_end,
                    days=(rec.date_end - fields.Date.context_today(rec)).days,
                    state=dict(rec._fields['state'].selection).get(new_state),
                )))
                rec.state = new_state
        return True

    def action_recompute_state(self):
        """Manual button: re-evaluate the state based on the current date_end.

        Useful on databases where the daily cron is disabled (Odoo.sh sandbox).
        On production the cron runs daily and catches up the transitions
        automatically.
        """
        for rec in self:
            new_state = rec._evaluate_lifecycle_state()
            if new_state != rec.state:
                rec.message_post(body=(
                    "Recalcul manuel du statut : %(old)s → %(new)s." % dict(
                        old=dict(rec._fields['state'].selection).get(rec.state),
                        new=dict(rec._fields['state'].selection).get(new_state),
                    )))
                rec.state = new_state
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
                    "Only a cancelled contract can be set back to draft."
                ))
            rec.state = 'draft'
        return True

    def action_generate_lines(self):
        """Generate the missing yearly lines between date_start and date_end.

        Creates one line per year (year = date_start.year ... date_end.year),
        pre-filled with `maintenance_amount`. Existing years are left alone --
        only the missing ones are created, so nothing already priced is ever
        overwritten.

        The pre-fill used to apply only when the contract had no line at all,
        which made it useless in practice: generating the lines before entering
        the amount, or extending the contract by a year, produced lines at zero
        with no way to get the pre-fill back (reported 2026-10-15).
        """
        Line = self.env['eurekam.maintenance.contract.line']
        for rec in self:
            if not rec.date_start or not rec.date_end:
                raise UserError(_(
                    "Set the start and end dates before generating the yearly lines."
                ))
            existing_years = set(rec.line_ids.mapped('year'))
            new_vals = []
            for year in range(rec.date_start.year, rec.date_end.year + 1):
                if year not in existing_years:
                    new_vals.append({
                        'contract_id': rec.id,
                        'year': year,
                        'amount': rec.maintenance_amount,
                    })
            if new_vals:
                Line.create(new_vals)
        return True

    def action_view_lines(self):
        """Open the yearly lines list filtered on this contract."""
        self.ensure_one()
        return {
            'name': _("Yearly Lines — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract.line',
            'view_mode': 'list,pivot,graph,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }

    def action_open_renewal_wizard(self):
        """Open the renewal wizard pre-filled from this contract."""
        self.ensure_one()
        if self.state in ('renewed', 'cancelled'):
            raise UserError(_(
                "This contract is %s, it cannot be renewed.",
                dict(self._fields['state'].selection).get(self.state),
            ))
        return {
            'name': _("Renew — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.contract.renewal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    def action_view_renewed_from(self):
        """Open the contract this one is the renewal of."""
        self.ensure_one()
        if not self.renewed_from_id:
            return False
        return {
            'name': _("Previous Contract"),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract',
            'res_id': self.renewed_from_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_renewed_to(self):
        """Open the contract(s) that renewed this one."""
        self.ensure_one()
        if not self.renewed_to_ids:
            return False
        if len(self.renewed_to_ids) == 1:
            return {
                'name': _("Renewal Contract"),
                'type': 'ir.actions.act_window',
                'res_model': 'eurekam.maintenance.contract',
                'res_id': self.renewed_to_ids[0].id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'name': _("Renewal Contracts"),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.renewed_to_ids.ids)],
        }

    # ==================================================================
    # Billing: frequency helpers
    # ==================================================================

    def _get_billing_period_code(self):
        """Current period code of the contract ('annual' by default if unset)."""
        self.ensure_one()
        for code in self.billing_frequency_ids.mapped('code'):
            if code in PERIOD_CODES:
                return code
        return 'annual'

    def _get_billing_timing_code(self):
        """Timing code: 'overdue' or 'upcoming' (default)."""
        self.ensure_one()
        for code in self.billing_frequency_ids.mapped('code'):
            if code in TIMING_CODES:
                return code
        return 'upcoming'

    @staticmethod
    def _periods_for_year(year, amount, period_code,
                          date_start=None, date_end=None):
        """Return the list of sub-periods of a year:
        [(code, label, fraction_amount, period_start, period_end), ...]

        - 'annual'      -> 1 period (full year)
        - 'semi_annual' -> 2 periods (H1, H2)
        - 'quarterly'   -> 4 periods (Q1..Q4)
        - 'full_period' -> single period covering the whole contract

        `date_start` / `date_end` are the contract's own dates. Only the periods
        that actually overlap them are returned, and `amount` -- which is the
        yearly line, i.e. what that contract year is worth -- is split across
        the periods kept, not across the four calendar quarters. A contract
        starting on 1 October and billed quarterly in arrears therefore yields a
        single Q4 line carrying the whole yearly amount, instead of four lines
        of a quarter each, three of which would bill periods predating the
        contract (reported by the sales team on CHU Grenoble, 2026-10-14).
        Omitting both dates keeps the full calendar year.

        `code` is a stable, never-translated technical key ("Q1 2026"). It is
        what gets stored in invoice_origin and maintenance_period_label, so the
        idempotency checks keep working -- and the orders/invoices created
        before the labels were reworded still match. `label` is the
        customer-facing wording ("1er trimestre 2026"), only ever used inside
        line descriptions. See PERIOD_LABELS for why it is written in French.
        """
        def lab(key):
            return PERIOD_LABELS[key] % {'year': year}

        if period_code == 'quarterly':
            bornes = [('Q1', date(year, 1, 1), date(year, 3, 31)),
                      ('Q2', date(year, 4, 1), date(year, 6, 30)),
                      ('Q3', date(year, 7, 1), date(year, 9, 30)),
                      ('Q4', date(year, 10, 1), date(year, 12, 31))]
            cles = {'Q1': 'Q1 %s', 'Q2': 'Q2 %s', 'Q3': 'Q3 %s', 'Q4': 'Q4 %s'}
        elif period_code == 'semi_annual':
            bornes = [('H1', date(year, 1, 1), date(year, 6, 30)),
                      ('H2', date(year, 7, 1), date(year, 12, 31))]
            cles = {'H1': 'H1 %s', 'H2': 'H2 %s'}
        else:  # 'annual' by default
            bornes = [('Y', date(year, 1, 1), date(year, 12, 31))]
            cles = {'Y': 'Year %s'}

        # Keep only the periods the contract actually covers.
        retenues = [b for b in bornes
                    if not (date_end and b[1] > date_end)
                    and not (date_start and b[2] < date_start)]
        if not retenues:
            return []

        parts = _split_amount(amount, len(retenues))
        return [(cles[cle] % year, lab(cle), parts[i], debut, fin)
                for i, (cle, debut, fin) in enumerate(retenues)]

    def _format_workstations(self):
        """'4 postes' fragment inserted in the billing line descriptions.

        Empty string when the contract does not carry a meaningful count, so
        the description degrades to "<label> - <period>" instead of showing a
        misleading "0 postes". See PERIOD_LABELS for why the wording is French.
        """
        self.ensure_one()
        count = self.nb_products or 0
        if count <= 0:
            return ''
        key = 'one' if count == 1 else 'many'
        return WORKSTATION_LABEL[key] % {'n': count}

    def _billing_line_description(self, period_label):
        """Description of a maintenance billing line (customer order / invoice).

        Format asked for by the sales team:
            "<Libellé produit> - <N> postes - <période>"
        e.g. "Assistance DRUGCAM Oncology GEN2 - 4 postes - 1er trimestre 2026".

        The product label falls back to the product name when the contract has
        no explicit label (older contracts created before the field was
        pre-filled from the product's sales description).
        """
        self.ensure_one()
        base = (self.product_name or '').strip() or self.product_id.name or ''
        parts = [p for p in (base, self._format_workstations(), period_label) if p]
        return ' - '.join(parts)

    def _full_period_label(self):
        """Customer-facing wording of the 'whole contract' period.

        French for the same reason as PERIOD_LABELS.
        """
        self.ensure_one()
        return FULL_PERIOD_LABEL % {
            'start': self.date_start or '?',
            'end': self.date_end or '?',
        }

    @staticmethod
    def _invoice_date_for_period(period_start, period_end, timing_code):
        """Invoice issue date for a given period.

        - 'overdue'  -> end of period
        - 'upcoming' -> start of period (default)
        """
        if timing_code == 'overdue':
            return period_end
        return period_start

    def _active_module_lines_for_year(self, year):
        """Billable module lines that apply to a given contract year (amount>0)."""
        self.ensure_one()
        return self.contract_module_line_ids.filtered(
            lambda m: m.amount and m._is_billable_for_year(year)
        )

    # ==================================================================
    # Billing: actions
    # ==================================================================

    def action_view_invoices(self):
        """Open the customer invoices linked to this contract."""
        self.ensure_one()
        # Every invoice is born from a customer order: the direct-billing
        # path was removed, so the orders are the single source.
        invoices = self.sale_order_ids.mapped('invoice_ids')
        if not invoices:
            raise UserError(_("No invoice is linked to this contract yet."))
        if len(invoices) == 1:
            return {
                'name': _("Invoice"),
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': invoices.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'name': _("Invoices — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
        }

    # ==================================================================
    # Customer orders (sale.order)
    # ==================================================================

    def action_open_create_order_wizard(self):
        """Open the maintenance customer order creation wizard."""
        self.ensure_one()
        if self.state in ('cancelled', 'renewed'):
            raise UserError(_(
                "Cannot create an order on a %s contract.",
                dict(self._fields['state'].selection).get(self.state),
            ))
        return {
            'name': _("Create Customer Order — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.order.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    def action_view_sale_orders(self):
        """Open the customer orders (sale.order) linked to this contract."""
        self.ensure_one()
        orders = self.sale_order_ids
        if not orders:
            raise UserError(_(
                "No customer order is linked to this contract yet. "
                "Click 'Create Customer Order' to create one."
            ))
        if len(orders) == 1:
            return {
                'name': _("Customer Order"),
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': orders.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'name': _("Customer Orders — %s", self.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', orders.ids)],
        }

    # ==================================================================
    # Expiry cron and notification templates
    # ==================================================================

    def _get_expiring_recipients(self):
        """Recipients of the 'expiring soon' email: salesperson only."""
        self.ensure_one()
        partners = self.env['res.partner']
        if self.commercial_id.partner_id:
            partners |= self.commercial_id.partner_id
        return partners

    def _get_expired_recipients(self):
        """Recipients of the 'expired' email: salesperson + all managers."""
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
        """Daily job: switch the active/expiring/expired states and send emails.

        Rules:
        - If 0 <= days_to_expiry <= 90 and state == 'active': switch to
          'expiring', send an email to the salesperson.
        - If days_to_expiry < 0 and state in ('active', 'expiring'): switch to
          'expired', send an email to the salesperson + managers.

        Idempotent: if the state is already correct (already notified before),
        nothing is done for that contract.
        """
        today = fields.Date.context_today(self)
        candidates = self.search([
            ('state', 'in', ('active', 'expiring')),
            ('date_end', '!=', False),
        ])
        _logger.info(
            "Expiry cron: %d contracts to check.",
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
            # Uses the same helper as action_activate / action_recompute_state
            new_state = contract._evaluate_lifecycle_state()
            if new_state == contract.state:
                continue
            old_state = contract.state
            contract.write({'state': new_state})
            if new_state == 'expired':
                passed_to_expired |= contract
            elif new_state == 'expiring' and old_state == 'active':
                passed_to_expiring |= contract

        # ---- Send emails (queued, not force_send=True) ----
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
                        "Failed to send 'expiring' email for %s: %s",
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
                        "Failed to send 'expired' email for %s: %s",
                        contract.sequence_number, exc,
                    )

        _logger.info(
            "Expiry cron: %d -> 'expiring', %d -> 'expired'.",
            len(passed_to_expiring),
            len(passed_to_expired),
        )
        return {
            'expiring': passed_to_expiring.ids,
            'expired': passed_to_expired.ids,
        }
