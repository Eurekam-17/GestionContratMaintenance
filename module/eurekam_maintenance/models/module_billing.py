from odoo import fields, models


class EurekamModuleBilling(models.Model):
    """Type de facturation pour les modules d'assistance Drugcam.

    Chaque contrat peut etre rattache a un ou plusieurs types selon la
    configuration de l'etablissement (gratuit valorise, statistique, ...).
    """

    _name = 'eurekam.module.billing'
    _description = "Type de facturation module"
    _order = 'sequence, name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    color = fields.Integer(string='Couleur')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "Le code du type de facturation module doit être unique."),
    ]
