"""Modeles auxiliaires pour caracteriser un etablissement de maintenance.

Ces 4 modeles partagent une meme structure (name, code, sequence, color, active)
et servent uniquement de tables de reference rattachees a res.partner.
"""

from odoo import fields, models


class EurekamEstablishmentType(models.Model):
    """Type d'etablissement client : CH, CHU, CLCC, CL, HIA, Distributeur, Laboratoire, Universite."""

    _name = 'eurekam.establishment.type'
    _description = "Type d'établissement Eurekam"
    _order = 'sequence, name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    color = fields.Integer(string='Couleur')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "Le code du type d'établissement doit être unique."),
    ]


class EurekamProductVersion(models.Model):
    """Version produit Drugcam installee chez l'etablissement."""

    _name = 'eurekam.product.version'
    _description = "Version produit Drugcam"
    _order = 'sequence, name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    color = fields.Integer(string='Couleur')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)',
         "Le code de la version produit doit être unique."),
    ]


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
