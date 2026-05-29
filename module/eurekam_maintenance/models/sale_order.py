"""Extension de sale.order pour le rattachement aux contrats de maintenance.

Cas d'usage majoritaire chez Eurekam : 1 commande client par annee de contrat,
avec autant de lignes que la rythmicite de facturation (1 pour Annuelle,
2 pour Semestrielle, 4 pour Trimestrielle). Chaque ligne du SO devient une
facture independante via le workflow Sales natif d'Odoo.

Cas rares :
- 1 SO couvrant l'integralite du contrat (mode 'full_contract' du wizard)
- Pas de SO du tout : contrat avec requires_customer_order=False, on facture
  directement comme avant (cas etablissements de sante prives).
"""

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    eurekam_maintenance_contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string="Contrat de maintenance",
        index=True,
        copy=False,
        help="Contrat de maintenance Eurekam pour lequel cette commande client a été émise.",
    )
    eurekam_maintenance_year = fields.Integer(
        string="Année maintenance couverte",
        copy=False,
        help="Année du contrat de maintenance que couvre cette commande client. "
             "0 si la commande couvre l'intégralité du contrat (cas rare).",
    )


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    maintenance_line_id = fields.Many2one(
        'eurekam.maintenance.contract.line',
        string="Ligne annuelle maintenance",
        index=True,
        copy=False,
        ondelete='set null',
        help="Ligne annuelle du contrat de maintenance dont cette ligne de "
             "commande facture une fraction (ex: T1 2026).",
    )
    maintenance_period_label = fields.Char(
        string="Période maintenance",
        copy=False,
        help="Libellé de la période couverte par cette ligne de commande "
             "(ex: 'T1 2026', 'S2 2026', 'Année 2026', 'Période intégrale').",
    )
