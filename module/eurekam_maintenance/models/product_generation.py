from odoo import fields, models


class EurekamProductGeneration(models.Model):
    """Drugcam generation a maintenance contract covers.

    User-manageable list (Configuration menu), like the market types: the
    sales team asked to be able to add a generation -- GEN3 and beyond --
    without waiting for a code change and a deployment, which a hard-coded
    Selection required.
    """

    _name = 'eurekam.product.generation'
    _description = "Drugcam Generation"
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', "The generation code must be unique."),
    ]
