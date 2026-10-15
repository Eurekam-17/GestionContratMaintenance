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
    # Order lines issued against this yearly line. Declared explicitly so the
    # invoicing status below has a real dependency path Odoo can track; it also
    # makes the orders reachable from the line.
    sale_line_ids = fields.One2many(
        'sale.order.line',
        'maintenance_line_id',
        string='Order Lines',
    )
    # Derived from the customer orders rather than stored on the line: every
    # invoice now comes from a quotation, so the link runs line -> order line
    # -> invoice. These used to be filled only by the contract's
    # direct-invoicing action, which was removed; left as they were they would
    # have stayed empty for ever while still showing on screen.
    invoice_ids = fields.Many2many(
        'account.move',
        string='Invoices',
        compute='_compute_invoice_ids',
        help="Customer invoices covering this yearly line, through the "
             "customer orders issued for it. A line may have several invoices "
             "depending on the frequency: 4 quarterly, 2 semi-annual, "
             "1 annual.",
    )
    # Stored, unlike invoice_ids: the Yearly Lines search view filters on them
    # ("Invoiced", "Not Invoiced", "Partially Invoiced"), and Odoo refuses to
    # validate a filter whose field cannot be searched -- which broke the whole
    # module update on 2026-10-15.
    invoice_count = fields.Integer(
        string='Invoices Count',
        compute='_compute_invoice_status',
        store=True,
    )
    is_invoiced = fields.Boolean(
        string='Invoiced',
        compute='_compute_invoice_status',
        store=True,
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

    def _factures_couvrantes(self):
        """Invoices covering the line: line -> order lines -> invoices.

        maintenance_line_id is set by the order wizard, so a yearly line knows
        every invoice issued against it. Cancelled invoices are ignored: they
        cover nothing.
        """
        self.ensure_one()
        return self.sale_line_ids.invoice_lines.move_id.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
        )

    @api.depends('sale_line_ids.invoice_lines.move_id.state',
                 'sale_line_ids.invoice_lines.move_id.move_type')
    def _compute_invoice_ids(self):
        for rec in self:
            rec.invoice_ids = rec._factures_couvrantes()

    # Kept apart from _compute_invoice_ids: these two are stored and that one
    # is not, and Odoo 18 warns about an "inconsistent 'store'" when a single
    # compute serves both.
    @api.depends('sale_line_ids.invoice_lines.move_id.state',
                 'sale_line_ids.invoice_lines.move_id.move_type')
    def _compute_invoice_status(self):
        for rec in self:
            factures = rec._factures_couvrantes()
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
