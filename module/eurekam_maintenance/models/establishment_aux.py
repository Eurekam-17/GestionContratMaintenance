"""Modeles auxiliaires pour caracteriser un etablissement de maintenance.

Ces 2 modeles partagent une meme structure (name, code, sequence, color, active)
et servent uniquement de tables de reference rattachees a res.partner.

Note (refactor option A) : on ne stocke plus le type d'etablissement ni la
version produit dans des modeles dedies. Eurekam utilise deja les tags
standard res.partner.category (CH, CHU, CLCC, Clinique, Universite, GEN1,
GEN2, ...). Les modeles eurekam.establishment.type et eurekam.product.version
ont ete supprimes pour eviter le doublon conceptuel et profiter du widget
many2many_tags deja affiche par la vue partner standard.

Les modeles restants (statut module, equipement special) n'ont pas
d'equivalent en tag dans la base Eurekam donc on les conserve.
"""

from odoo import fields, models


class EurekamModuleStatus(models.Model):
    """Statut d'activation d'un module Drugcam chez l'etablissement."""

    _name = 'eurekam.module.status'
    _description = "Statut module Drugcam"
    _order = 'sequence, name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    color = fields.Integer(string='Couleur')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "Le code du statut module doit être unique."),
    ]


class EurekamSpecialEquipment(models.Model):
    """Equipement special associe a l'etablissement (Robot, Spectro, ...)."""

    _name = 'eurekam.special.equipment'
    _description = "Équipement spécial"
    _order = 'sequence, name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    color = fields.Integer(string='Couleur')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "Le code de l'équipement spécial doit être unique."),
    ]
