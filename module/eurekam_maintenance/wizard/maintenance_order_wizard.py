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
    @api.depends('contract_id', 'year', 'coverage_mode')
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
            line = w.contract_id.line_ids.filtered(lambda l, y=w.year: l.year == y)
            if not line:
                w.preview_period_count = 0
                w.preview_total_amount = 0.0
                continue
            period_code = w.contract_id._get_billing_period_code()
            periods = w.contract_id._periods_for_year(w.year, line.amount, period_code)
            count = len(periods)
            total = sum(p[1] for p in periods)
            # Billable modules active that year add their own lines.
            for ml in w.contract_id._active_module_lines_for_year(w.year):
                m_periods = w.contract_id._periods_for_year(w.year, ml.amount, period_code)
                count += len(m_periods)
                total += sum(p[1] for p in m_periods)
            w.preview_period_count = count
            w.preview_total_amount = total

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
            # Default proposed year: the first future year not yet covered by an order
            covered_years = set(
                contract.sale_order_ids.mapped('eurekam_maintenance_year')
            )
            today_year = fields.Date.context_today(self).year
            for line in contract.line_ids.sorted(key=lambda l: l.year):
                if line.year >= today_year and line.year not in covered_years:
                    res['year'] = line.year
                    break
            else:
                res['year'] = today_year
        return res

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
            label = _(
                "%(prod)s — Full period (%(start)s → %(end)s)",
                prod=product_template.name or '',
                start=contract.date_start or '?',
                end=contract.date_end or '?',
            )
            order_lines.append((0, 0, {
                'product_id': product_variant.id,
                'name': label,
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

            period_code = contract._get_billing_period_code()
            periods = contract._periods_for_year(self.year, line.amount, period_code)

            for label, fraction, _start, _end in periods:
                order_lines.append((0, 0, {
                    'product_id': product_variant.id,
                    'name': _(
                        "%(prod)s — %(period)s",
                        prod=product_template.name or '',
                        period=label,
                    ),
                    'product_uom_qty': 1.0,
                    'price_unit': fraction,
                    'maintenance_line_id': line.id,
                    'maintenance_period_label': label,
                }))

            # ---- Billable modules active that year ----
            for ml in contract._active_module_lines_for_year(self.year):
                ml_product = ml._get_invoice_product() or product_variant
                module_name = ml.module_billing_id.name or _("Module")
                m_periods = contract._periods_for_year(self.year, ml.amount, period_code)
                for base_label, fraction, _s, _e in m_periods:
                    order_lines.append((0, 0, {
                        'product_id': ml_product.id,
                        'name': "%s — %s" % (module_name, base_label),
                        'product_uom_qty': 1.0,
                        'price_unit': fraction,
                        'maintenance_line_id': line.id,
                        'maintenance_period_label': "%s — %s" % (module_name, base_label),
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
