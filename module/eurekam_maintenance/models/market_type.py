from odoo import fields, models


class EurekamMarketType(models.Model):
    """Market / public tender type applied to a maintenance contract.

    User-manageable list (Configuration menu) so the team can freely add or
    edit values. Used as a Many2many on the contract because a contract may be
    attached to several markets.
    """

    _name = 'eurekam.market.type'
    _description = "Market Type"
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', "The market type code must be unique."),
    ]
