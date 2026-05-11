from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EurekamMaintenanceContractLine(models.Model):
    _name = 'eurekam.maintenance.contract.line'
    _description = "Ligne annuelle de contrat de maintenance Eurekam"
    _order = 'contract_id, year'
    _rec_name = 'display_name'

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contrat',
        required=True,
        ondelete='cascade',
        index=True,
    )
    year = fields.Integer(
        string='Année',
        required=True,
        index=True,
    )
    amount = fields.Monetary(
        string='Montant',
        currency_field='currency_id',
        required=True,
        default=0.0,
    )
    is_invoiced = fields.Boolean(
        string='Facturée',
        default=False,
        help="Coché automatiquement par l'action « Créer la facture » sur le "
             "contrat. Peut aussi être basculé manuellement si la facture a "
             "été émise hors Odoo.",
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Facture',
        readonly=True,
        copy=False,
        domain="[('move_type', '=', 'out_invoice')]",
        help="Facture client liée à cette ligne annuelle. Renseignée "
             "automatiquement par l'action « Créer la facture » du contrat.",
    )
    notes = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # Champs related (pratique pour recherche / sécurité)
    # ------------------------------------------------------------------
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='contract_id.partner_id',
        string='Établissement',
        store=True,
        readonly=True,
    )
    commercial_id = fields.Many2one(
        related='contract_id.commercial_id',
        string='Commercial',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        related='contract_id.company_id',
        store=True,
        readonly=True,
    )
    contract_state = fields.Selection(
        related='contract_id.state',
        string='État du contrat',
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('contract_id.sequence_number', 'year')
    def _compute_display_name(self):
        for rec in self:
            seq = rec.contract_id.sequence_number or ''
            rec.display_name = f"{seq} - {rec.year}" if seq else str(rec.year)

    # ------------------------------------------------------------------
    # Contraintes
    # ------------------------------------------------------------------
    _sql_constraints = [
        (
            'unique_contract_year',
            'UNIQUE(contract_id, year)',
            "Une seule ligne annuelle est autorisée par contrat et par année.",
        ),
    ]

    @api.constrains('year')
    def _check_year(self):
        for rec in self:
            if rec.year < 2000 or rec.year > 2100:
                raise ValidationError(_(
                    "L'année (%s) doit être comprise entre 2000 et 2100.",
                    rec.year,
                ))

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_(
                    "Le montant d'une ligne annuelle ne peut pas être négatif."
                ))
