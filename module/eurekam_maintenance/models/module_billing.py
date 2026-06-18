from odoo import fields, models


class EurekamModuleBilling(models.Model):
    """Billing type for Drugcam assistance modules.

    Each contract may be linked to one or more types depending on the
    establishment configuration (free valued, statistics, ...).
    """

    _name = 'eurekam.module.billing'
    _description = "Module Billing Type"
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)
    product_id = fields.Many2one(
        'product.product',
        string='Default Article',
        help="Catalogue article used by default on the order / invoice lines "
             "when this module is billed on a contract.",
    )

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "The module billing type code must be unique."),
    ]
