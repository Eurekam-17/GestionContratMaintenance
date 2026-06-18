from odoo import fields, models


class EurekamCentralPurchasing(models.Model):
    """Central purchasing body / buying group of an establishment.

    User-manageable list (Configuration menu) so the team can freely add or
    edit values (UniHA, AGEPS, RESAH, private groups such as ELSAN/Ramsay...).
    Used as a Many2one on res.partner (a single establishment belongs to one
    central purchasing body).
    """

    _name = 'eurekam.central.purchasing'
    _description = "Central Purchasing Body"
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "The central purchasing code must be unique."),
    ]
