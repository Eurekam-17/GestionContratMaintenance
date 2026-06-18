"""Billable module line attached to a maintenance contract.

Use case (team feedback): add an assistance module to an in-progress contract,
give it its own annual cost and a start year (e.g. "Statistics Premium module,
billed from 2027" on a contract that began in 2025), and have that module show
up as its own article line in the customer order / invoices.

The amount is annual; when generating the order or the invoices for a given
year, it is split by the same billing cadence as the contract (1 line for
Annual, 2 for Semi-annual, 4 for Quarterly), but only for the years within the
module's [start_year, end_year] window.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EurekamContractModuleLine(models.Model):
    _name = 'eurekam.contract.module.line'
    _description = "Contract Billable Module"
    _order = 'contract_id, start_year, id'

    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contract',
        required=True,
        ondelete='cascade',
        index=True,
    )
    module_billing_id = fields.Many2one(
        'eurekam.module.billing',
        string='Module',
        required=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Invoiced Article',
        help="Article used on the order / invoice line for this module. "
             "If empty, the module's default article is used, otherwise the "
             "contract product.",
    )
    amount = fields.Monetary(
        string='Annual Amount',
        currency_field='currency_id',
        help="Annual amount of the module. Split by the contract cadence when "
             "billed.",
    )
    start_year = fields.Integer(
        string='Billed From (Year)',
        required=True,
        help="First year the module is billed (e.g. 2027).",
    )
    end_year = fields.Integer(
        string='Billed Until (Year)',
        help="Last year the module is billed. Leave empty to bill until the "
             "contract end year.",
    )
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        readonly=True,
    )
    company_id = fields.Many2one(
        related='contract_id.company_id',
        store=True,
        readonly=True,
    )
    notes = fields.Char(string='Notes')

    @api.constrains('start_year', 'end_year')
    def _check_years(self):
        for rec in self:
            if rec.start_year and (rec.start_year < 2000 or rec.start_year > 2100):
                raise ValidationError(_(
                    "The module start year (%s) looks invalid.", rec.start_year,
                ))
            if rec.end_year and rec.end_year < rec.start_year:
                raise ValidationError(_(
                    "The module end year (%(end)s) must be after the start "
                    "year (%(start)s).",
                    end=rec.end_year, start=rec.start_year,
                ))

    def _effective_end_year(self):
        """End year of the module billing window (falls back to contract end)."""
        self.ensure_one()
        if self.end_year:
            return self.end_year
        if self.contract_id.date_end:
            return self.contract_id.date_end.year
        return self.start_year

    def _is_billable_for_year(self, year):
        self.ensure_one()
        return self.start_year <= year <= self._effective_end_year()

    def _get_invoice_product(self):
        """Resolve the product.product to use on the order / invoice line.

        Priority: line product -> module default product -> contract product.
        """
        self.ensure_one()
        if self.product_id:
            return self.product_id
        module_product = self.module_billing_id.product_id
        if module_product:
            return module_product
        contract_tmpl = self.contract_id.product_id
        return contract_tmpl.product_variant_id if contract_tmpl else False
