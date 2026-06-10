"""Auxiliary models to characterize a maintenance establishment.

These 2 models share the same structure (name, code, sequence, color, active)
and act only as reference tables linked to res.partner.

Note (refactor option A): the establishment type and the product version are
no longer stored in dedicated models. Eurekam already uses the standard
res.partner.category tags (CH, CHU, CLCC, Clinic, University, GEN1, GEN2, ...).
The eurekam.establishment.type and eurekam.product.version models were removed
to avoid the conceptual duplication and to benefit from the many2many_tags
widget already displayed by the standard partner view.

The remaining models (module status, special equipment) have no tag equivalent
in the Eurekam database, so they are kept.
"""

from odoo import fields, models


class EurekamModuleStatus(models.Model):
    """Activation status of a Drugcam module at the establishment."""

    _name = 'eurekam.module.status'
    _description = "Drugcam Module Status"
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "The module status code must be unique."),
    ]


class EurekamSpecialEquipment(models.Model):
    """Special equipment linked to the establishment (Robot, Spectro, ...)."""

    _name = 'eurekam.special.equipment'
    _description = "Special Equipment"
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "The special equipment code must be unique."),
    ]
