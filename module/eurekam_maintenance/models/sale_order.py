"""Extension of sale.order to link sale orders to maintenance contracts.

Main use case at Eurekam: 1 customer order per contract year, with as many
lines as the billing rhythm (1 for Annual, 2 for Semi-annual, 4 for Quarterly).
Each SO line becomes an independent invoice through Odoo's native Sales workflow.

Rare cases:
- 1 SO covering the whole contract ('full_contract' mode of the wizard)
- No SO at all: contract with requires_customer_order=False, billed directly
  as before (private healthcare establishments).
"""

from odoo import fields, models


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
