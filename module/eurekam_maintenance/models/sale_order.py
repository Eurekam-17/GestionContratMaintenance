"""Extension of sale.order to link sale orders to maintenance contracts.

Main use case at Eurekam: 1 customer order per contract year, with as many
lines as the billing rhythm (1 for Annual, 2 for Semi-annual, 4 for Quarterly).
Each SO line becomes an independent invoice through Odoo's native Sales workflow.

Rare cases:
- 1 SO covering the whole contract ('full_contract' mode of the wizard)
- No SO at all: contract with requires_customer_order=False, billed directly
  as before (private healthcare establishments).
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    eurekam_maintenance_contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string="Maintenance Contract",
        index=True,
        copy=False,
        help="Eurekam maintenance contract this customer order was issued for.",
    )
    eurekam_maintenance_year = fields.Integer(
        string="Covered Maintenance Year",
        copy=False,
        help="Contract year covered by this customer order. "
             "0 if the order covers the whole contract (rare case).",
    )

    @api.constrains('eurekam_maintenance_contract_id', 'eurekam_maintenance_year', 'state')
    def _check_maintenance_order_unicity(self):
        """A contract year can only be ordered once.

        Guardrail against duplicates: without it the wizard can be replayed
        indefinitely and recreate an order that already exists. Enforced on the
        model (not only in the wizard) so that imports/migrations, the API and
        manual entry are covered too.

        Cancelled orders are ignored: an order that was cancelled -- or deleted --
        can legitimately be recreated.
        """
        for order in self:
            contract = order.eurekam_maintenance_contract_id
            if not contract or order.state == 'cancel':
                continue
            duplicate = self.sudo().search([
                ('id', '!=', order.id),
                ('eurekam_maintenance_contract_id', '=', contract.id),
                ('eurekam_maintenance_year', '=', order.eurekam_maintenance_year),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if not duplicate:
                continue
            if order.eurekam_maintenance_year:
                raise ValidationError(_(
                    "Order %(existing)s already covers year %(year)s of contract "
                    "%(contract)s.\n\n"
                    "A maintenance year can only be ordered once. To recreate it, "
                    "first cancel or delete %(existing)s.",
                    existing=duplicate.name,
                    year=order.eurekam_maintenance_year,
                    contract=contract.sequence_number,
                ))
            raise ValidationError(_(
                "Order %(existing)s already covers the whole contract %(contract)s.\n\n"
                "To recreate it, first cancel or delete %(existing)s.",
                existing=duplicate.name,
                contract=contract.sequence_number,
            ))


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    maintenance_line_id = fields.Many2one(
        'eurekam.maintenance.contract.line',
        string="Maintenance Yearly Line",
        index=True,
        copy=False,
        ondelete='set null',
        help="Yearly line of the maintenance contract this order line invoices "
             "a fraction of (e.g. Q1 2026).",
    )
    maintenance_period_label = fields.Char(
        string="Maintenance Period",
        copy=False,
        help="Label of the period covered by this order line "
             "(e.g. 'Q1 2026', 'H2 2026', 'Year 2026', 'Full period').",
    )
