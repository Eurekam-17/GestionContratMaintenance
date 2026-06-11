import logging
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# "Period" billing codes (mutually exclusive on a given contract)
PERIOD_CODES = ('annual', 'semi_annual', 'quarterly', 'full_period')
# "Timing" billing codes (mutually exclusive on a given contract)
TIMING_CODES = ('overdue', 'upcoming')


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
        help="Free text if no linked product.",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Establishment',
        required=True,
        tracking=True,
        index=True,
        domain="[('is_maintenance_establishment', '=', True)]",
        help="Only contacts flagged as Maintenance Establishment "
             "(Eurekam Maintenance tab of the partner form) can be selected.",
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
        string='Market',
        tracking=True,
    )
    order_status = fields.Selection(
        [
            ('received', 'Received'),
            ('pending', 'Pending'),
            ('no_po', 'No Purchase Order'),
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
        string='Ordered Duration',
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
    requires_customer_order = fields.Boolean(
        string="Requires Customer Order",
        default=True,
        tracking=True,
        help="If checked (most common case), billing must go through a customer "
             "order (sale.order) created upon receipt of the customer purchase "
             "order. The 'Create Contract Invoices' action is then disabled — "
             "use 'Create Customer Order' instead.\n"
             "If unchecked (rare case: some private establishments), billing is "
             "done directly on the contract without a purchase order.",
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
        return super().create(vals_list)

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
                rec.message_post(body=_(
                    "Activation followed by an immediate re-evaluation based on "
                    "date_end (%(end)s, %(days)s days): status adjusted to "
                    "\"%(state)s\".",
                    end=rec.date_end,
                    days=(rec.date_end - fields.Date.context_today(rec)).days,
                    state=dict(rec._fields['state'].selection).get(new_state),
                ))
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
                rec.message_post(body=_(
                    "Manual state recompute: %(old)s -> %(new)s.",
                    old=dict(rec._fields['state'].selection).get(rec.state),
                    new=dict(rec._fields['state'].selection).get(new_state),
                ))
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
        """Generate the empty yearly lines between date_start and date_end.

        Creates one line per year (year = date_start.year ... date_end.year),
        with amount=0 by default. Existing lines are not overwritten.
        If maintenance_amount > 0 and no line exists yet, each line is
        pre-filled with that amount as a starting value.
        """
        Line = self.env['eurekam.maintenance.contract.line']
        for rec in self:
            if not rec.date_start or not rec.date_end:
                raise UserError(_(
                    "Set the start and end dates before generating the yearly lines."
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
    def _periods_for_year(year, amount, period_code):
        """Return the list of sub-periods of a year:
        [(label, fraction_amount, period_start, period_end), ...]

        - 'annual'      -> 1 period (full year)
        - 'semi_annual' -> 2 periods (H1, H2), fraction = amount/2
        - 'quarterly'   -> 4 periods (Q1..Q4), fraction = amount/4
        - 'full_period' -> handled separately (action_create_invoices_for_contract)
        """
        if period_code == 'quarterly':
            f = _split_amount(amount, 4)
            return [
                ("Q1 %s" % year, f[0], date(year, 1, 1), date(year, 3, 31)),
                ("Q2 %s" % year, f[1], date(year, 4, 1), date(year, 6, 30)),
                ("Q3 %s" % year, f[2], date(year, 7, 1), date(year, 9, 30)),
                ("Q4 %s" % year, f[3], date(year, 10, 1), date(year, 12, 31)),
            ]
        if period_code == 'semi_annual':
            f = _split_amount(amount, 2)
            return [
                ("H1 %s" % year, f[0], date(year, 1, 1), date(year, 6, 30)),
                ("H2 %s" % year, f[1], date(year, 7, 1), date(year, 12, 31)),
            ]
        # 'annual' by default
        return [
            ("Year %s" % year, amount, date(year, 1, 1), date(year, 12, 31)),
        ]

    @staticmethod
    def _invoice_date_for_period(period_start, period_end, timing_code):
        """Invoice issue date for a given period.

        - 'overdue'  -> end of period
        - 'upcoming' -> start of period (default)
        """
        if timing_code == 'overdue':
            return period_end
        return period_start

    # ==================================================================
    # Billing: actions
    # ==================================================================

    def action_create_invoices_for_contract(self):
        """Create all the draft invoices covering the remaining contract duration.

        Depending on the frequency (billing_frequency_ids):
          - 'annual'      -> 1 invoice per remaining year
          - 'semi_annual' -> 2 invoices per remaining year (H1, H2)
          - 'quarterly'   -> 4 invoices per remaining year (Q1..Q4)
          - 'full_period' -> 1 global invoice = sum of all lines
          - 'overdue'     -> invoice date = end of period
          - 'upcoming'    -> invoice date = start of period (default)

        Idempotent: already invoiced periods are not recreated.
        """
        today = fields.Date.context_today(self)
        created_invoices = self.env['account.move']

        for contract in self:
            if contract.requires_customer_order:
                raise UserError(_(
                    "Contract %s requires a customer order (PO). Direct billing "
                    "is disabled for this contract.\n"
                    "Click 'Create Customer Order' instead: a sale.order will be "
                    "created with the lines matching the frequency, and each line "
                    "can then be invoiced independently through the native Sales "
                    "workflow.",
                    contract.sequence_number,
                ))
            if not contract.line_ids:
                raise UserError(_(
                    "No yearly line for this contract. Click 'Generate Yearly "
                    "Lines' first."
                ))
            if not contract.product_id:
                raise UserError(_(
                    "Contract %s has no linked product (the 'Product' field).\n"
                    "Set a product from the catalog before generating the "
                    "invoices, otherwise the income account and taxes cannot be "
                    "resolved automatically.",
                    contract.sequence_number,
                ))

            period_code = contract._get_billing_period_code()
            timing_code = contract._get_billing_timing_code()

            # ---- Case 1: Full period = 1 global invoice ----
            if period_code == 'full_period':
                existing = contract.line_ids.mapped('invoice_ids')
                if existing:
                    raise UserError(_(
                        "One or more invoices already exist for this 'Full "
                        "period' contract: %s. Delete the existing invoices "
                        "first if a replay is needed.",
                        ', '.join(existing.mapped('display_name')),
                    ))
                invoice = contract._create_invoice_full_period()
                contract.line_ids.write({'invoice_ids': [(4, invoice.id)]})
                created_invoices |= invoice
                continue

            # ---- Case 2: sub-annual frequency (annual/semi_annual/quarterly) ----
            # Iterate over the future lines (current year and beyond).
            prefix = contract.sequence_number + " / "
            future_lines = contract.line_ids.filtered(lambda l: l.year >= today.year)
            for line in future_lines.sorted(key=lambda l: l.year):
                periods = contract._periods_for_year(
                    line.year, line.amount, period_code,
                )
                # Already invoiced periods: read the suffix after " / " in the
                # invoice_origin of the invoices already linked to the line.
                # More robust than a simple counter: if a middle invoice (e.g.
                # Q2) was deleted, it is recreated without duplicating Q1/Q3/Q4.
                already_labels = set()
                for inv in line.invoice_ids:
                    origin = inv.invoice_origin or ''
                    if origin.startswith(prefix):
                        already_labels.add(origin[len(prefix):])
                for label, fraction, p_start, p_end in periods:
                    if label in already_labels:
                        continue
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
                "No new invoice to create (all remaining periods are already "
                "invoiced)."
            ))

        for contract in self:
            contract.message_post(body=_(
                "%d draft invoice(s) created according to the contract frequency.",
                len(created_invoices),
            ))

        return {
            'name': _("Invoices Created (%d)", len(created_invoices)),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_invoices.ids)],
            'target': 'current',
        }

    def _create_invoice_period(self, line, period_label, fraction_amount, invoice_date):
        """Create a draft invoice for a sub-period (Q1, H1, Year N, etc.)."""
        self.ensure_one()
        product = self.product_id
        product_var = product.product_variant_id if product else False
        description = _(
            "%(prod)s — %(period)s",
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
        """Create a single draft invoice covering the whole contract.

        A single invoice line for the total amount (total_contract_value).
        Issue date based on the timing:
          - upcoming -> date_start
          - overdue  -> date_end
          - default  -> today
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
            "%(prod)s — Full period (%(start)s → %(end)s)",
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
        """Open the customer invoices linked to this contract."""
        self.ensure_one()
        # Direct invoices (no-PO case) + invoices via sale.order (standard case)
        invoices_direct = self.line_ids.mapped('invoice_ids')
        invoices_from_so = self.sale_order_ids.mapped('invoice_ids')
        invoices = invoices_direct | invoices_from_so
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
