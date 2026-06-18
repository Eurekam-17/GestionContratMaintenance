"""Maintenance contract renewal wizard.

Pre-fills a new contract from the old one, shifts the dates, optionally applies
the Syntec revision, creates the new contract in 'active' state and switches
the old one to 'renewed'.

Both contracts are chained through the renewed_from_id field on the new one.
"""

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Mapping from the duration (Selection) to a number of units for relativedelta.
# 6 months is a special case handled separately.
DURATION_TO_YEARS = {
    '1y': 1,
    '2y': 2,
    '3y': 3,
    '4y': 4,
    '5y': 5,
}

# Default Syntec coefficient applied if the user does not change it.
DEFAULT_SYNTEC_RATE = 3.0


def _calc_end_date(start, duration):
    """Compute the end date from date_start and a duration code.

    The end date is inclusive: a 1-year contract starting on 2026-01-01 ends on
    2026-12-31 (and not 2027-01-01).
    """
    if not start or not duration:
        return False
    if duration == '6m':
        return start + relativedelta(months=6, days=-1)
    years = DURATION_TO_YEARS.get(duration, 1)
    return start + relativedelta(years=int(years), days=-1)


class EurekamContractRenewalWizard(models.TransientModel):
    _name = 'eurekam.contract.renewal.wizard'
    _description = "Maintenance Contract Renewal Wizard"

    # ------------------------------------------------------------------
    # Source contract
    # ------------------------------------------------------------------
    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contract to Renew',
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='contract_id.partner_id',
        string='Establishment',
        readonly=True,
    )
    product_id = fields.Many2one(
        related='contract_id.product_id',
        string='Product',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # New contract — dates and duration
    # ------------------------------------------------------------------
    new_date_start = fields.Date(
        string='New Start Date',
        required=True,
    )
    new_date_end = fields.Date(
        string='New End Date',
        required=True,
    )
    new_duration = fields.Selection(
        [
            ('6m', '6 months'),
            ('1y', '1 year'),
            ('2y', '2 years'),
            ('3y', '3 years'),
            ('4y', '4 years'),
            ('5y', '5 years'),
        ],
        string='Duration',
        required=True,
    )

    # ------------------------------------------------------------------
    # Syntec revision
    # ------------------------------------------------------------------
    apply_syntec = fields.Boolean(
        string='Apply Syntec Revision',
        default=False,
    )
    syntec_rate = fields.Float(
        string='Syntec Rate (%)',
        default=DEFAULT_SYNTEC_RATE,
        digits=(5, 2),
        help="Percentage of revaluation applied to the maintenance amount.",
    )

    # ------------------------------------------------------------------
    # Amounts
    # ------------------------------------------------------------------
    old_amount = fields.Monetary(
        string='Previous Amount',
        currency_field='currency_id',
        readonly=True,
    )
    syntec_delta = fields.Monetary(
        string='Syntec Increase',
        currency_field='currency_id',
        compute='_compute_syntec_delta',
    )
    new_maintenance_amount = fields.Monetary(
        string='New Maintenance Amount',
        currency_field='currency_id',
        required=True,
    )

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------
    generate_lines = fields.Boolean(
        string='Generate the New Contract Yearly Lines',
        default=True,
    )
    cancel_old_lines_invoiced = fields.Boolean(
        string="Flag Unbilled Lines as Transferred",
        default=False,
        help="Adds a note on the unbilled yearly lines of the old contract to "
             "signal the carry-over to the new one.",
    )

    # ==================================================================
    # Compute
    # ==================================================================

    @api.depends('apply_syntec', 'syntec_rate', 'old_amount')
    def _compute_syntec_delta(self):
        for w in self:
            if w.apply_syntec and w.old_amount:
                w.syntec_delta = w.old_amount * (w.syntec_rate / 100.0)
            else:
                w.syntec_delta = 0.0

    # ==================================================================
    # Onchange
    # ==================================================================

    @api.onchange('apply_syntec', 'syntec_rate', 'old_amount')
    def _onchange_apply_syntec(self):
        """Update the new amount when Syntec is (un)checked."""
        if self.apply_syntec and self.old_amount:
            self.new_maintenance_amount = round(
                self.old_amount * (1 + self.syntec_rate / 100.0), 2
            )
        elif not self.apply_syntec:
            self.new_maintenance_amount = self.old_amount

    @api.onchange('new_date_start', 'new_duration')
    def _onchange_duration(self):
        """Recompute new_date_end automatically."""
        if self.new_date_start and self.new_duration:
            self.new_date_end = _calc_end_date(self.new_date_start, self.new_duration)

    # ==================================================================
    # Default get: pre-fill from the source contract
    # ==================================================================

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contract_id = (
            self.env.context.get('default_contract_id')
            or self.env.context.get('active_id')
        )
        if contract_id:
            contract = self.env['eurekam.maintenance.contract'].browse(contract_id)
            duration = contract.duration or '1y'
            new_start = (
                contract.date_end + relativedelta(days=1)
                if contract.date_end else fields.Date.context_today(self)
            )
            new_end = _calc_end_date(new_start, duration)
            apply_syntec = contract.syntec_revision == 'yes'
            new_amount = contract.maintenance_amount
            if apply_syntec:
                new_amount = round(
                    contract.maintenance_amount * (1 + DEFAULT_SYNTEC_RATE / 100.0), 2
                )
            res.update({
                'contract_id': contract.id,
                'old_amount': contract.maintenance_amount,
                'new_maintenance_amount': new_amount,
                'new_date_start': new_start,
                'new_date_end': new_end,
                'new_duration': duration,
                'apply_syntec': apply_syntec,
            })
        return res

    # ==================================================================
    # Main action
    # ==================================================================

    def action_renew(self):
        """Create the new contract (active state) and switch the old one to 'renewed'."""
        self.ensure_one()
        old = self.contract_id

        if old.state in ('renewed', 'cancelled'):
            raise UserError(_(
                "This contract is %s, it cannot be renewed.",
                dict(old._fields['state'].selection).get(old.state),
            ))
        if not self.new_date_start or not self.new_date_end:
            raise UserError(_("Set the new start and end dates."))
        if self.new_date_end < self.new_date_start:
            raise UserError(_(
                "The new end date must be after the start date."
            ))
        if self.new_maintenance_amount < 0:
            raise UserError(_("The new amount cannot be negative."))

        # --- Build the new contract values ---------------------------------
        new_comment_parts = [_(
            "Renewal of %(seq)s from %(start)s to %(end)s.",
            seq=old.sequence_number,
            start=old.date_start or '?',
            end=old.date_end or '?',
        )]
        if self.apply_syntec:
            new_comment_parts.append(_(
                "Syntec revision applied: +%(rate).2f %% (delta = %(delta).2f).",
                rate=self.syntec_rate,
                delta=self.syntec_delta,
            ))
        if old.comment:
            new_comment_parts.append("---")
            new_comment_parts.append(old.comment)

        new_vals = {
            'product_id': old.product_id.id,
            'product_name': old.product_name,
            'partner_id': old.partner_id.id,
            'commercial_id': old.commercial_id.id,
            'gen': old.gen,
            'market_type_ids': [(6, 0, old.market_type_ids.ids)],
            'order_status': old.order_status,
            'date_start': self.new_date_start,
            'date_end': self.new_date_end,
            'duration': self.new_duration,
            'billing_level': old.billing_level,
            'maintenance_amount': self.new_maintenance_amount,
            'syntec_revision': old.syntec_revision,
            'nb_products': old.nb_products,
            'comment': '\n'.join(new_comment_parts),
            'state': 'active',
            'company_id': old.company_id.id,
            'billing_frequency_ids': [(6, 0, old.billing_frequency_ids.ids)],
            'module_billing_ids': [(6, 0, old.module_billing_ids.ids)],
            'contract_module_line_ids': [
                (0, 0, {
                    'module_billing_id': ml.module_billing_id.id,
                    'product_id': ml.product_id.id,
                    'amount': ml.amount,
                    'start_year': ml.start_year,
                    'end_year': ml.end_year,
                    'notes': ml.notes,
                })
                for ml in old.contract_module_line_ids
            ],
            'renewed_from_id': old.id,
        }
        new_contract = self.env['eurekam.maintenance.contract'].create(new_vals)

        # --- Yearly lines of the new contract ------------------------------
        if self.generate_lines:
            new_contract.action_generate_lines()

        # --- Note on the old unbilled lines --------------------------------
        if self.cancel_old_lines_invoiced:
            for line in old.line_ids.filtered(lambda l: not l.is_invoiced):
                note = _(
                    "Carried over to renewal %(seq)s.",
                    seq=new_contract.sequence_number,
                )
                line.notes = (line.notes or '') + ('\n' if line.notes else '') + note

        # --- Switch the old one to 'renewed' -------------------------------
        old.message_post(body=_(
            "Contract renewed through the wizard. New contract: %s.",
            new_contract.sequence_number,
        ))
        new_contract.message_post(body=_(
            "Renewal of %s.",
            old.sequence_number,
        ))
        old.write({'state': 'renewed'})

        # --- Open the new contract -----------------------------------------
        return {
            'name': _("New Contract — %s", new_contract.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract',
            'res_id': new_contract.id,
            'view_mode': 'form',
            'target': 'current',
        }
