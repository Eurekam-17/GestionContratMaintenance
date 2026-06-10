from odoo import fields, models


class EurekamBillingFrequency(models.Model):
    """Billing frequency applied to a maintenance contract.

    Frequencies are multi-valued (Many2many on the contract) because a single
    contract may combine for example an Annual + Overdue billing.
    """

    _name = 'eurekam.billing.frequency'
    _description = "Billing Frequency"
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "The billing frequency code must be unique."),
    ]
