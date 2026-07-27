"""Wizard to create a customer order (sale.order) for a contract.

Use case: upon receipt of a customer purchase order, a sale.order is created
pre-filled with N lines according to the contract frequency (1 for Annual,
2 for Semi-annual, 4 for Quarterly).

The user can also choose the 'Full contract' mode which creates an SO with a
single line covering all the remaining contract years.

After creation, the SO is a draft. The user then confirms it through Odoo's
native Sales workflow (Confirm), then invoices each line over time (Q1 first,
then Q2 three months later, etc.) via the native 'Create Invoice' button.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Default Syntec coefficient proposed when the user applies the revision.
# Kept aligned with the renewal wizard so both entry points suggest the same
# rate; the user remains free to override it.
DEFAULT_SYNTEC_RATE = 3.0


class EurekamMaintenanceOrderWizard(models.TransientModel):
    _name = 'eurekam.maintenance.order.wizard'
    _description = "Maintenance Customer Order Wizard"

    # ------------------------------------------------------------------
    # Source contract
    # ------------------------------------------------------------------
    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contract',
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='contract_id.partner_id',
        string='Customer',
        readonly=True,
    )
    product_id = fields.Many2one(
        related='contract_id.product_id',
        string='Product',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # User choices
    # ------------------------------------------------------------------
    coverage_mode = fields.Selection(
        [
            ('annual_split', "Year (split by frequency)"),
            ('full_contract', "Whole contract (rare case)"),
        ],
        string='Order Scope',
        default='annual_split',
        required=True,
    )
    year = fields.Integer(
        string='Covered Year',
        help="Contract year covered by the order. "
             "Ignored if scope = Whole contract.",
    )
    customer_po_reference = fields.Char(
        string='Customer PO Reference',
        required=True,
        help="Purchase order number sent by the customer.",
    )
    customer_po_date = fields.Date(
        string='PO Receipt Date',
        required=True,
        default=fields.Date.context_today,
    )

    # ------------------------------------------------------------------
    # Syntec revision (only for contracts flagged syntec_revision = 'yes')
    # ------------------------------------------------------------------
    syntec_revision = fields.Selection(
        related='contract_id.syntec_revision',
        string='Contract Under Syntec Revision',
        readonly=True,
    )
    apply_syntec = fields.Boolean(
        string='Apply Syntec Revision',
        help="Revalues the covered year before creating the order. The revised "
             "amount is written back onto the contract's yearly line, so the "
             "contract, the order and the invoices stay consistent.\n"
             "Only available on the 'Year' scope: revaluing the whole contract "
             "in one go is done through the renewal wizard.",
    )
    syntec_rate = fields.Float(
        string='Syntec Rate (%)',
        default=DEFAULT_SYNTEC_RATE,
        digits=(5, 2),
    )
    base_amount = fields.Monetary(
        string='Contract Amount for the Year',
        compute='_compute_base_amount',
        currency_field='currency_id',
        help="Amount currently recorded on the contract's yearly line.",
    )
    revised_amount = fields.Monetary(
        string='Revised Amount',
        currency_field='currency_id',
        help="Amount actually ordered and written back onto the contract. "
             "Suggested from the rate, but freely editable (e.g. to match the "
             "exact figure of the customer purchase order).",
    )
    syntec_delta = fields.Monetary(
        string='Revision Delta',
        compute='_compute_syntec_delta',
        currency_field='currency_id',
    )

    # ------------------------------------------------------------------
    # Preview (shown for info in the wizard view)
    # ------------------------------------------------------------------
    preview_period_count = fields.Integer(
        string='Number of Lines to Create',
        compute='_compute_preview',
    )
    preview_total_amount = fields.Monetary(
        string='Total Amount (untaxed)',
        compute='_compute_preview',
        currency_field='currency_id',
    )

    # ==================================================================
    # Compute
    # ==================================================================
    @api.depends('contract_id', 'year')
    def _compute_base_amount(self):
        for w in self:
            line = w._yearly_line()
            w.base_amount = line.amount if line else 0.0

    @api.depends('apply_syntec', 'revised_amount', 'base_amount')
    def _compute_syntec_delta(self):
        for w in self:
            if w.apply_syntec:
                w.syntec_delta = w.revised_amount - w.base_amount
            else:
                w.syntec_delta = 0.0

    @api.onchange('apply_syntec', 'syntec_rate', 'base_amount', 'coverage_mode')
    def _onchange_apply_syntec(self):
        """Suggest the revised amount; the user can still adjust it."""
        if self.coverage_mode != 'annual_split':
            self.apply_syntec = False
        if self.apply_syntec:
            self.revised_amount = round(
                self.base_amount * (1 + self.syntec_rate / 100.0), 2
            )
        else:
            self.revised_amount = self.base_amount

    @api.depends('contract_id', 'year', 'coverage_mode',
                 'apply_syntec', 'revised_amount')
    def _compute_preview(self):
        for w in self:
            if not w.contract_id:
                w.preview_period_count = 0
                w.preview_total_amount = 0.0
                continue
            if w.coverage_mode == 'full_contract':
                count = 1
                total = sum(w.contract_id.line_ids.mapped('amount'))
                contract_years = sorted(w.contract_id.line_ids.mapped('year'))
                for ml in w.contract_id.contract_module_line_ids.filtered(lambda m: m.amount):
                    covered = [y for y in contract_years if ml._is_billable_for_year(y)]
                    if covered:
                        count += 1
                        total += round(ml.amount * len(covered), 2)
                w.preview_period_count = count
                w.preview_total_amount = total
                continue
            # annual_split
            line = w._yearly_line()
            if not line:
                w.preview_period_count = 0
                w.preview_total_amount = 0.0
                continue
            period_code = w.contract_id._get_billing_period_code()
            periods = w.contract_id._periods_for_year(
                w.year, w._effective_year_amount(), period_code,
            )
            count = len(periods)
            total = sum(p[2] for p in periods)
            # Billable modules active that year add their own lines.
            for ml in w.contract_id._active_module_lines_for_year(w.year):
                m_periods = w.contract_id._periods_for_year(w.year, ml.amount, period_code)
                count += len(m_periods)
                total += sum(p[2] for p in m_periods)
            w.preview_period_count = count
            w.preview_total_amount = total

    # ==================================================================
    # Helpers
    # ==================================================================

    def _yearly_line(self):
        """Contract yearly line covered by this order ('annual_split' mode)."""
        self.ensure_one()
        if not self.contract_id or not self.year:
            return self.env['eurekam.maintenance.contract.line']
        return self.contract_id.line_ids.filtered(
            lambda l, y=self.year: l.year == y
        )

    def _effective_year_amount(self):
        """Amount actually ordered for the year: revised one when the Syntec
        revision is applied, contract amount otherwise."""
        self.ensure_one()
        if self.apply_syntec and self.coverage_mode == 'annual_split':
            return self.revised_amount
        line = self._yearly_line()
        return line.amount if line else 0.0

    # ==================================================================
    # Default get
    # ==================================================================
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contract_id = (
            self.env.context.get('default_contract_id')
            or self.env.context.get('active_id')
        )
        if contract_id:
            contract = self.env['eurekam.maintenance.contract'].browse(contract_id)
            res['contract_id'] = contract.id
            # Default proposed year: the first future year not yet covered by an order.
            # A cancelled order covers nothing: its year stays proposable, so a
            # cancelled (or deleted) order can be recreated.
            covered_years = set(
                contract.sale_order_ids
                .filtered(lambda o: o.state != 'cancel')
                .mapped('eurekam_maintenance_year')
            )
            today_year = fields.Date.context_today(self).year
            for line in contract.line_ids.sorted(key=lambda l: l.year):
                if line.year >= today_year and line.year not in covered_years:
                    res['year'] = line.year
                    break
            else:
                res['year'] = today_year
            # Start from the contract amount: the Syntec block only deviates
            # from it once the user ticks 'Apply Syntec Revision'.
            covered_line = contract.line_ids.filtered(
                lambda l, y=res['year']: l.year == y
            )
            res['revised_amount'] = covered_line.amount if covered_line else 0.0
        return res

    # ==================================================================
    # Syntec revision
    # ==================================================================

    def _apply_syntec_on_line(self, line):
        """Revalue the contract yearly line and return the amount to order.

        Returns the contract amount untouched when the revision is not applied.
        When it is, the yearly line is updated in place and the move is traced
        in the contract chatter: the contract stays the single source of truth
        for the amounts shown on the dashboard and reused by later orders.
        """
        self.ensure_one()
        if not self.apply_syntec or self.coverage_mode != 'annual_split':
            return line.amount

        if self.contract_id.syntec_revision != 'yes':
            raise UserError(_(
                "Contract %s is not flagged for Syntec revision. Set 'Syntec "
                "Revision' to Yes on the contract before applying a revision.",
                self.contract_id.sequence_number,
            ))
        if self.revised_amount <= 0:
            raise UserError(_("The revised amount must be greater than zero."))

        old_amount = line.amount
        line.amount = self.revised_amount
        self.contract_id.message_post(body=_(
            "Syntec revision applied on year %(year)s when creating the "
            "customer order: %(old).2f -> %(new).2f (%(rate).2f %%, delta "
            "%(delta).2f). The contract yearly line has been updated.",
            year=self.year,
            old=old_amount,
            new=self.revised_amount,
            rate=self.syntec_rate,
            delta=self.revised_amount - old_amount,
        ))
        return self.revised_amount

    # ==================================================================
    # Main action
    # ==================================================================
    def action_create_sale_order(self):
        """Create the sale.order with the matching lines."""
        self.ensure_one()
        contract = self.contract_id
        if not contract:
            raise UserError(_("No contract selected."))
        if contract.state in ('cancelled', 'renewed'):
            raise UserError(_(
                "Cannot create an order on a %s contract.",
                dict(contract._fields['state'].selection).get(contract.state),
            ))
        if not contract.product_id:
            raise UserError(_(
                "Contract %s has no linked product. Set the 'Product' field "
                "before creating an order.",
                contract.sequence_number,
            ))

        # Guardrail: a contract year can only be ordered once. Checked here for a
        # clear message before anything is created; sale.order also enforces it
        # (_check_maintenance_order_unicity) for imports/API/manual entry.
        # Cancelled orders are ignored -> a cancelled/deleted order is recreatable.
        year_key = self.year if self.coverage_mode == 'annual_split' else 0
        existing = contract.sale_order_ids.filtered(
            lambda o: o.state != 'cancel' and o.eurekam_maintenance_year == year_key
        )
        if existing:
            if year_key:
                raise UserError(_(
                    "Year %(year)s of contract %(contract)s is already covered by "
                    "order %(existing)s.\n\n"
                    "To recreate it, first cancel or delete %(existing)s.",
                    year=year_key,
                    contract=contract.sequence_number,
                    existing=existing[0].name,
                ))
            raise UserError(_(
                "Contract %(contract)s is already fully covered by order "
                "%(existing)s.\n\n"
                "To recreate it, first cancel or delete %(existing)s.",
                contract=contract.sequence_number,
                existing=existing[0].name,
            ))

        # Build the SO values
        so_vals = {
            'partner_id': contract.partner_id.id,
            'eurekam_maintenance_contract_id': contract.id,
            'eurekam_maintenance_year': self.year if self.coverage_mode == 'annual_split' else 0,
            'client_order_ref': self.customer_po_reference,
            'date_order': fields.Datetime.to_datetime(self.customer_po_date) or fields.Datetime.now(),
            'currency_id': contract.currency_id.id,
            'company_id': contract.company_id.id,
            'origin': contract.sequence_number,
        }

        # ---- Build the lines ----
        product_template = contract.product_id
        product_variant = product_template.product_variant_id
        if not product_variant:
            raise UserError(_(
                "Product %s has no variant. Cannot create the order.",
                product_template.name,
            ))

        order_lines = []

        if self.coverage_mode == 'full_contract':
            # ---- Rare case: 1 line for the whole contract ----
            total = sum(contract.line_ids.mapped('amount'))
            if not total:
                raise UserError(_(
                    "The contract has no yearly lines with an amount. "
                    "Generate the yearly lines first."
                ))
            order_lines.append((0, 0, {
                'product_id': product_variant.id,
                'name': contract._billing_line_description(
                    contract._full_period_label()
                ),
                'product_uom_qty': 1.0,
                'price_unit': total,
                'maintenance_period_label': _("Full period"),
            }))
            # ---- Billable modules over the whole contract ----
            contract_years = sorted(contract.line_ids.mapped('year'))
            for ml in contract.contract_module_line_ids.filtered(lambda m: m.amount):
                covered = [y for y in contract_years if ml._is_billable_for_year(y)]
                if not covered:
                    continue
                ml_product = ml._get_invoice_product() or product_variant
                order_lines.append((0, 0, {
                    'product_id': ml_product.id,
                    'name': _(
                        "%(module)s — Full period (%(n)d year(s))",
                        module=ml.module_billing_id.name or _("Module"),
                        n=len(covered),
                    ),
                    'product_uom_qty': 1.0,
                    'price_unit': round(ml.amount * len(covered), 2),
                    'maintenance_period_label': _("Full period"),
                }))
        else:
            # ---- Main case: 1 SO per year, N lines by frequency ----
            if not self.year:
                raise UserError(_("The year to cover is required in 'Year split' mode."))
            line = contract.line_ids.filtered(lambda l: l.year == self.year)
            if not line:
                raise UserError(_(
                    "No yearly line for year %s. "
                    "Click 'Generate Yearly Lines' on the contract first.",
                    self.year,
                ))
            if len(line) > 1:
                raise UserError(_("Inconsistency: several lines for year %s.", self.year))

            # Syntec revision: revalue the year BEFORE splitting it into
            # periods, and write the revised amount back onto the contract so
            # the contract, the order and the dashboard all agree.
            year_amount = self._apply_syntec_on_line(line)

            period_code = contract._get_billing_period_code()
            periods = contract._periods_for_year(self.year, year_amount, period_code)

            for code, label, fraction, _start, _end in periods:
                order_lines.append((0, 0, {
                    'product_id': product_variant.id,
                    'name': contract._billing_line_description(label),
                    'product_uom_qty': 1.0,
                    'price_unit': fraction,
                    'maintenance_line_id': line.id,
                    'maintenance_period_label': code,
                }))

            # ---- Billable modules active that year ----
            for ml in contract._active_module_lines_for_year(self.year):
                ml_product = ml._get_invoice_product() or product_variant
                module_name = ml.module_billing_id.name or _("Module")
                m_periods = contract._periods_for_year(self.year, ml.amount, period_code)
                for base_code, base_label, fraction, _s, _e in m_periods:
                    order_lines.append((0, 0, {
                        'product_id': ml_product.id,
                        'name': "%s - %s" % (module_name, base_label),
                        'product_uom_qty': 1.0,
                        'price_unit': fraction,
                        'maintenance_line_id': line.id,
                        'maintenance_period_label': "%s — %s" % (module_name, base_code),
                    }))

        so_vals['order_line'] = order_lines

        # ---- Actual creation ----
        sale_order = self.env['sale.order'].create(so_vals)

        contract.message_post(body=_(
            "Customer order %(so)s created for PO %(po)s (%(n)d line(s), %(mode)s).",
            so=sale_order.name,
            po=self.customer_po_reference,
            n=len(order_lines),
            mode=dict(self._fields['coverage_mode'].selection).get(self.coverage_mode),
        ))

        # Return the action to open the SO
        return {
            'name': _("Order %s", sale_order.name),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }
