"""Extension of res.partner for Eurekam maintenance establishments.

Adds the business fields specific to the Drugcam contract tracking:
classification, equipment, modules, managers, and a reverse link to the
maintenance contracts.
"""

from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # Main flag: is this contact a maintenance establishment?
    # ------------------------------------------------------------------
    is_maintenance_establishment = fields.Boolean(
        string="Maintenance Establishment",
        default=False,
        index=True,
        help="Tick if this contact is a client establishment tracked for the "
             "Eurekam maintenance contracts. Only ticked contacts appear in the "
             "selection list when creating a contract.",
    )

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------
    department_number = fields.Char(
        string="Department No.",
        help="French department number (01, 02, ..., 95, 2A, 2B, 971, ...).",
    )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------
    # Note (refactor option A): the establishment type (CH, CHU, CLCC...) is no
    # longer stored in a dedicated model. We use the standard category_id field
    # (Many2many to res.partner.category) already shown by the Odoo partner view.
    # The CH/CHU/CLCC/Clinic/University tags already exist in the Eurekam DB.

    establishment_status = fields.Selection(
        [
            ('client_eurekam', 'Eurekam Customer'),
            ('prospect_eurekam', 'Eurekam Prospect'),
            ('client_distributor', 'Distributor Customer'),
            ('prospect_distributor', 'Distributor Prospect'),
            ('client_referrer', 'Referrer Customer'),
            ('prospect_referrer', 'Referrer Prospect'),
        ],
        # Label intentionally NOT "Status": res.users delegates res.partner
        # fields, and auth_signup already defines a "Status" (state) field on
        # res.users. A plain "Status" here triggers Odoo's duplicate-label
        # warning, so we qualify it.
        string="Establishment Status",
    )
    central_purchasing = fields.Selection(
        [
            ('uniha', 'UniHA'),
            ('ageps', 'AGEPS'),
            ('private', 'Private'),
            ('internal', 'Internal Market'),
            ('unicancer', 'Unicancer'),
            ('industrial', 'Industrial'),
        ],
        string="Central Purchasing",
    )

    # ------------------------------------------------------------------
    # Installed equipment & modules
    # ------------------------------------------------------------------
    # Note (refactor option A): the product version (GEN1, GEN2) is no longer
    # stored in a dedicated model. We use the standard res.partner.category tags
    # (GEN1, GEN2 already present in the Eurekam DB).

    module_status_ids = fields.Many2many(
        'eurekam.module.status',
        'res_partner_module_status_rel',
        'partner_id', 'status_id',
        string="Module Statuses",
    )
    nb_workstations = fields.Integer(
        string="Number of Workstations",
        help="Number of Drugcam workstations installed on site.",
    )
    special_equipment_ids = fields.Many2many(
        'eurekam.special.equipment',
        'res_partner_special_equipment_rel',
        'partner_id', 'equipment_id',
        string="Special Equipment",
    )

    # ------------------------------------------------------------------
    # Eurekam managers
    # ------------------------------------------------------------------
    commercial_responsible_id = fields.Many2one(
        'res.users',
        string="Sales Manager",
    )
    adv_responsible_id = fields.Many2one(
        'res.users',
        string="Sales Admin Manager",
        help="Sales administration.",
    )

    # ------------------------------------------------------------------
    # Reverse link to the contracts
    # ------------------------------------------------------------------
    maintenance_contract_ids = fields.One2many(
        'eurekam.maintenance.contract',
        'partner_id',
        string="Maintenance Contracts",
    )
    maintenance_contract_count = fields.Integer(
        string="Maintenance Contracts Count",
        compute='_compute_maintenance_contract_count',
        store=False,
    )
    active_maintenance_contract_count = fields.Integer(
        string="Active Contracts Count",
        compute='_compute_maintenance_contract_count',
        store=False,
    )
    expiring_maintenance_contract_count = fields.Integer(
        string="Expiring Contracts Count",
        compute='_compute_maintenance_contract_count',
        store=False,
    )
    expired_maintenance_contract_count = fields.Integer(
        string="Expired Contracts Count",
        compute='_compute_maintenance_contract_count',
        store=False,
    )
    maintenance_status = fields.Selection(
        [
            ('none', "No commercial relationship"),
            ('client_no_contract', "Customer WITHOUT maintenance contract"),
            ('active', "Maintenance ACTIVE"),
            ('expiring', "Maintenance EXPIRING SOON"),
            ('expired', "Maintenance EXPIRED"),
        ],
        string="Maintenance Status",
        compute='_compute_maintenance_status',
        store=False,
        help="Synthetic indicator visible to the whole team (notably support) "
             "summarizing the maintenance contract state and the commercial "
             "relationship of the establishment. Computed in real time.\n"
             "- ACTIVE: at least 1 active contract\n"
             "- EXPIRING SOON: no active one but at least 1 expiring within 90 days\n"
             "- EXPIRED: all contracts are expired\n"
             "- Customer WITHOUT contract: no contract but at least 1 customer "
             "order (potential to convert)\n"
             "- No commercial relationship: neither contract nor order in Odoo",
    )

    @api.depends('maintenance_contract_ids', 'maintenance_contract_ids.state')
    def _compute_maintenance_contract_count(self):
        for rec in self:
            rec.maintenance_contract_count = len(rec.maintenance_contract_ids)
            rec.active_maintenance_contract_count = len(
                rec.maintenance_contract_ids.filtered(lambda c: c.state == 'active')
            )
            rec.expiring_maintenance_contract_count = len(
                rec.maintenance_contract_ids.filtered(lambda c: c.state == 'expiring')
            )
            rec.expired_maintenance_contract_count = len(
                rec.maintenance_contract_ids.filtered(lambda c: c.state == 'expired')
            )

    @api.depends(
        'maintenance_contract_ids',
        'active_maintenance_contract_count',
        'expiring_maintenance_contract_count',
        'expired_maintenance_contract_count',
        'sale_order_ids',  # native sale module: One2many to sale.order
    )
    def _compute_maintenance_status(self):
        """Synthetic summary of the maintenance status + commercial relationship.

        Status priority (from most to least important):
        - 'active'             : >=1 active contract
        - 'expiring'           : 0 active, but >=1 expiring soon
        - 'expired'            : 0 active, 0 expiring, but >=1 expired
        - 'client_no_contract' : 0 maintenance contract, but >=1 sale.order
                                 (= known customer, to convert)
        - 'none'               : no contract, no order
        """
        for rec in self:
            if rec.active_maintenance_contract_count > 0:
                rec.maintenance_status = 'active'
            elif rec.expiring_maintenance_contract_count > 0:
                rec.maintenance_status = 'expiring'
            elif rec.expired_maintenance_contract_count > 0:
                rec.maintenance_status = 'expired'
            elif rec.sale_order_ids:
                # No contract (or all draft/renewed/cancelled),
                # but at least one customer order: potential to convert.
                rec.maintenance_status = 'client_no_contract'
            else:
                rec.maintenance_status = 'none'

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_maintenance_contracts(self):
        """Open the maintenance contracts linked to this partner."""
        self.ensure_one()
        return {
            'name': _("Contracts — %s", self.display_name),
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
        """Toggle the is_maintenance_establishment flag.

        Handy to quickly flag an existing partner as a maintenance
        establishment so it becomes selectable in the contracts.
        """
        for rec in self:
            rec.is_maintenance_establishment = not rec.is_maintenance_establishment
