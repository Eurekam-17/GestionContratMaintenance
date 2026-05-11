from odoo import fields, models


class EurekamBillingFrequency(models.Model):
    """Cadence de facturation appliquee a un contrat de maintenance.

    Les cadences sont multi-valeurs (Many2many sur le contrat) car un meme
    contrat peut combiner par exemple une facturation Annuelle + a Echu.
    """

    _name = 'eurekam.billing.frequency'
    _description = "Cadence de facturation"
    _order = 'sequence, name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    color = fields.Integer(string='Couleur')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "Le code de la cadence de facturation doit être unique."),
    ]
