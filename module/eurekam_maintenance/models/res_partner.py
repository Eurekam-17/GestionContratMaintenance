"""Extension de res.partner pour les etablissements de maintenance Eurekam.

Ajoute les champs metier specifiques au suivi des contrats Drugcam :
classification, equipements, modules, responsables, et un lien inverse
vers les contrats de maintenance.
"""

from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # Marqueur principal : ce contact est-il un etablissement de maintenance ?
    # ------------------------------------------------------------------
    is_maintenance_establishment = fields.Boolean(
        string="Établissement de maintenance",
        default=False,
        index=True,
        help="Cocher si ce contact est un établissement client suivi pour les "
             "contrats de maintenance Eurekam. Seuls les contacts coches "
             "apparaissent dans la liste de selection lors de la creation "
             "d'un contrat.",
    )

    # ------------------------------------------------------------------
    # Localisation
    # ------------------------------------------------------------------
    department_number = fields.Char(
        string="N° Département",
        help="Numéro du département français (01, 02, ..., 95, 2A, 2B, 971, ...).",
    )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------
    # Note (refactor option A) : le type d'établissement (CH, CHU, CLCC...)
    # n'est plus stocké dans un modèle dédié. On utilise le champ standard
    # `category_id` (Many2many vers res.partner.category) déjà affiché par
    # la vue partner Odoo. Les tags CH/CHU/CLCC/Clinique/Université etc.
    # existent déjà dans la base Eurekam.

    establishment_status = fields.Selection(
        [
            ('client_eurekam', 'Client Eurekam'),
            ('prospect_eurekam', 'Prospect Eurekam'),
            ('client_distributor', 'Client distributeur'),
            ('prospect_distributor', 'Prospect distributeur'),
            ('client_referrer', 'Client référent'),
            ('prospect_referrer', 'Prospect référent'),
        ],
        string="Statut",
    )
    central_purchasing = fields.Selection(
        [
            ('uniha', 'UniHA'),
            ('ageps', 'AGEPS'),
            ('private', 'Privé'),
            ('internal', 'Marché interne'),
            ('unicancer', 'Unicancer'),
            ('industrial', 'Industriel'),
        ],
        string="Centrale d'achat",
    )

    # ------------------------------------------------------------------
    # Équipements & modules installés
    # ------------------------------------------------------------------
    # Note (refactor option A) : la version produit (GEN1, GEN2) n'est plus
    # stockée dans un modèle dédié. On utilise les tags res.partner.category
    # standard (GEN1, GEN2 déjà présents dans la base Eurekam).

    module_status_ids = fields.Many2many(
        'eurekam.module.status',
        'res_partner_module_status_rel',
        'partner_id', 'status_id',
        string="Statuts modules",
    )
    nb_workstations = fields.Integer(
        string="Nombre de postes",
        help="Nombre de postes Drugcam installés sur le site.",
    )
    special_equipment_ids = fields.Many2many(
        'eurekam.special.equipment',
        'res_partner_special_equipment_rel',
        'partner_id', 'equipment_id',
        string="Équipements spéciaux",
    )

    # ------------------------------------------------------------------
    # Responsables Eurekam
    # ------------------------------------------------------------------
    commercial_responsible_id = fields.Many2one(
        'res.users',
        string="Responsable commercial",
    )
    adv_responsible_id = fields.Many2one(
        'res.users',
        string="Responsable ADV",
        help="Administration des ventes.",
    )

    # ------------------------------------------------------------------
    # Lien inverse vers les contrats
    # ------------------------------------------------------------------
    maintenance_contract_ids = fields.One2many(
        'eurekam.maintenance.contract',
        'partner_id',
        string="Contrats de maintenance",
    )
    maintenance_contract_count = fields.Integer(
        string="Nb contrats de maintenance",
        compute='_compute_maintenance_contract_count',
        store=False,
    )
    active_maintenance_contract_count = fields.Integer(
        string="Nb contrats actifs",
        compute='_compute_maintenance_contract_count',
        store=False,
    )

    @api.depends('maintenance_contract_ids', 'maintenance_contract_ids.state')
    def _compute_maintenance_contract_count(self):
        for rec in self:
            rec.maintenance_contract_count = len(rec.maintenance_contract_ids)
            rec.active_maintenance_contract_count = len(
                rec.maintenance_contract_ids.filtered(lambda c: c.state == 'active')
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_maintenance_contracts(self):
        """Ouvre la liste des contrats de maintenance lies a ce partenaire."""
        self.ensure_one()
        return {
            'name': _("Contrats — %s", self.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract',
            'view_mode': 'list,kanban,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {
                'default_partner_id': self.id,
                'search_default_filter_active': 0,
            },
        }

    def action_mark_as_maintenance_establishment(self):
        """Bascule le flag is_maintenance_establishment.

        Pratique pour marquer rapidement un partner existant comme
        etablissement de maintenance afin qu'il devienne selectionnable
        dans les contrats.
        """
        for rec in self:
            rec.is_maintenance_establishment = not rec.is_maintenance_establishment
