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
    # Computed from the customer orders rather than stored: every invoice now
    # comes from a quotation, so the link runs line -> sale.order.line
    # (maintenance_line_id) -> invoice. The field used to be filled only by the
    # contract's direct-invoicing action, which was removed; left stored it
    # would have stayed empty for ever while still showing on screen.
    invoice_ids = fields.Many2many(
        'account.move',
        string='Invoices',
        compute='_compute_invoice_status',
        help="Customer invoices covering this yearly line, through the "
             "customer orders issued for it. A line may have several invoices "
             "depending on the frequency: 4 quarterly, 2 semi-annual, "
             "1 annual.",
    )
    invoice_count = fields.Integer(
        string='Invoices Count',
        compute='_compute_invoice_status',
    )
    is_invoiced = fields.Boolean(
        string='Invoiced',
        compute='_compute_invoice_status',
        help="Checked as soon as at least one invoice covers the line.",
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

    def _compute_invoice_status(self):
        """Walk line -> order lines -> invoices.

        sale.order.line.maintenance_line_id is set by the order wizard, so a
        yearly line knows every invoice issued against it without any stored
        link of its own. Cancelled invoices are ignored: they cover nothing.
        """
        SaleLine = self.env['sale.order.line']
        for rec in self:
            factures = self.env['account.move']
            if rec.id:
                lignes = SaleLine.search([('maintenance_line_id', '=', rec.id)])
                factures = lignes.invoice_lines.move_id.filtered(
                    lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
                )
            rec.invoice_ids = factures
            rec.invoice_count = len(factures)
            rec.is_invoiced = bool(factures)

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
