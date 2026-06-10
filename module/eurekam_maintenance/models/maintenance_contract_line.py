from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EurekamMaintenanceContractLine(models.Model):
    _name = 'eurekam.maintenance.contract.line'
    _description = "Eurekam Maintenance Contract Yearly Line"
    _order = 'contract_id, year'
    _rec_name = 'display_name'

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contract',
        required=True,
        ondelete='cascade',
        index=True,
    )
    year = fields.Integer(
        string='Year',
        required=True,
        index=True,
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        required=True,
        default=0.0,
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'eurekam_maintenance_line_invoice_rel',
        'line_id', 'invoice_id',
        string='Invoices',
        copy=False,
        domain="[('move_type', '=', 'out_invoice')]",
        help="Customer invoices linked to this yearly line. A line may have "
             "several invoices depending on the frequency: 4 quarterly, "
             "2 semi-annual, 1 annual. Set automatically by the "
             "'Create Invoices' action of the contract.",
    )
    invoice_count = fields.Integer(
        string='Invoices Count',
        compute='_compute_invoice_status',
        store=True,
    )
    is_invoiced = fields.Boolean(
        string='Invoiced',
        compute='_compute_invoice_status',
        store=True,
        help="Checked automatically when at least one invoice is linked to the line.",
    )
    notes = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # Related fields (handy for search / security)
    # ------------------------------------------------------------------
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='contract_id.partner_id',
        string='Establishment',
        store=True,
        readonly=True,
    )
    commercial_id = fields.Many2one(
        related='contract_id.commercial_id',
        string='Salesperson',
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
        string='Contract Status',
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Display
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

    @api.depends('invoice_ids')
    def _compute_invoice_status(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids)
            rec.is_invoiced = bool(rec.invoice_ids)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    _sql_constraints = [
        (
            'unique_contract_year',
            'UNIQUE(contract_id, year)',
            "Only one yearly line is allowed per contract and per year.",
        ),
    ]

    @api.constrains('year')
    def _check_year(self):
        for rec in self:
            if rec.year < 2000 or rec.year > 2100:
                raise ValidationError(_(
                    "The year (%s) must be between 2000 and 2100.",
                    rec.year,
                ))

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_(
                    "A yearly line amount cannot be negative."
                ))
