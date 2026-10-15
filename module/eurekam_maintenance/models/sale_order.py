"""Extension of sale.order to link sale orders to maintenance contracts.

Main use case at Eurekam: 1 customer order per contract year, with as many
lines as the billing rhythm (1 for Annual, 2 for Semi-annual, 4 for Quarterly).
Each SO line becomes an independent invoice through Odoo's native Sales workflow.

Every invoice is normally born from a customer order.

Rare cases:
- 1 SO covering the whole contract ('full_contract' mode of the wizard)
- No SO at all: managers keep a direct-billing fallback on the contract
  ('Create Contract Invoices'), for exceptional situations only.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    eurekam_maintenance_contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string="Maintenance Contract",
        index=True,
        copy=False,
        help="Eurekam maintenance contract this customer order was issued for.",
    )
    eurekam_maintenance_year = fields.Integer(
        string="Covered Maintenance Year",
        copy=False,
        help="Contract year covered by this customer order. "
             "0 if the order covers the whole contract (rare case).",
    )

    @api.constrains('eurekam_maintenance_contract_id', 'eurekam_maintenance_year', 'state')
    def _check_maintenance_order_unicity(self):
        """A contract year can only be ordered once.

        Guardrail against duplicates: without it the wizard can be replayed
        indefinitely and recreate an order that already exists. Enforced on the
        model (not only in the wizard) so that imports/migrations, the API and
        manual entry are covered too.

        Cancelled orders are ignored: an order that was cancelled -- or deleted --
        can legitimately be recreated.
        """
        for order in self:
            contract = order.eurekam_maintenance_contract_id
            if not contract or order.state == 'cancel':
                continue
            duplicate = self.sudo().search([
                ('id', '!=', order.id),
                ('eurekam_maintenance_contract_id', '=', contract.id),
                ('eurekam_maintenance_year', '=', order.eurekam_maintenance_year),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if not duplicate:
                continue
            if order.eurekam_maintenance_year:
                raise ValidationError(_(
                    "Order %(existing)s already covers year %(year)s of contract "
                    "%(contract)s.\n\n"
                    "A maintenance year can only be ordered once. To recreate it, "
                    "first cancel or delete %(existing)s.",
                    existing=duplicate.name,
                    year=order.eurekam_maintenance_year,
                    contract=contract.sequence_number,
                ))
            raise ValidationError(_(
                "Order %(existing)s already covers the whole contract %(contract)s.\n\n"
                "To recreate it, first cancel or delete %(existing)s.",
                existing=duplicate.name,
                contract=contract.sequence_number,
            ))


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    maintenance_line_id = fields.Many2one(
        'eurekam.maintenance.contract.line',
        string="Maintenance Yearly Line",
        index=True,
        copy=False,
        ondelete='set null',
        help="Yearly line of the maintenance contract this order line invoices "
             "a fraction of (e.g. Q1 2026).",
    )
    maintenance_period_label = fields.Char(
        string="Maintenance Period",
        copy=False,
        help="Label of the period covered by this order line "
             "(e.g. 'Q1 2026', 'H2 2026', 'Year 2026', 'Full period').",
    )
    # Both the maintenance lines and the billable-module lines carry
    # maintenance_line_id, so the link alone cannot tell them apart. Only the
    # 'contract' ones make up the yearly amount; counting a module line into it
    # would inflate the contract.
    maintenance_kind = fields.Selection(
        [('contract', 'Contract Maintenance'), ('module', 'Billable Module')],
        string="Maintenance Line Type",
        copy=False,
    )

    # ------------------------------------------------------------------
    # Synchronisation with the contract's yearly line
    # ------------------------------------------------------------------
    def _sync_vers_ligne_annuelle(self):
        """Push the order's total back onto the contract's yearly line.

        The yearly line is worth what is actually being sold for that year, so
        amending a quotation -- renegotiating, adding a discount -- must be
        reflected on the contract instead of leaving the two to drift apart
        (reported by the sales team, 2026-10-15).

        Cancelled orders are excluded: they sell nothing.
        """
        annuelles = self.filtered(
            lambda l: l.maintenance_kind == 'contract' and l.maintenance_line_id
        ).maintenance_line_id
        for annuelle in annuelles:
            lignes = annuelle.sale_line_ids.filtered(
                lambda l: l.maintenance_kind == 'contract'
                and l.order_id.state != 'cancel'
            )
            if not lignes:
                continue
            total = round(sum(lignes.mapped('price_subtotal')), 2)
            if abs(total - annuelle.amount) < 0.01:
                continue
            ancien = annuelle.amount
            annuelle.with_context(eurekam_sync=True).write({'amount': total})
            annuelle.contract_id.message_post(body=_(
                "Year %(year)s updated from order %(order)s: "
                "%(old).2f -> %(new).2f.",
                year=annuelle.year,
                order=', '.join(lignes.mapped('order_id.name')),
                old=ancien, new=total,
            ))

    @api.model_create_multi
    def create(self, vals_list):
        lignes = super().create(vals_list)
        if not self.env.context.get('eurekam_sync'):
            lignes._sync_vers_ligne_annuelle()
        return lignes

    def write(self, vals):
        res = super().write(vals)
        suivis = {'price_unit', 'product_uom_qty', 'discount',
                  'maintenance_line_id', 'maintenance_kind'}
        if suivis & set(vals) and not self.env.context.get('eurekam_sync'):
            self._sync_vers_ligne_annuelle()
        return res

    def unlink(self):
        annuelles = self.filtered(
            lambda l: l.maintenance_kind == 'contract' and l.maintenance_line_id
        ).maintenance_line_id
        res = super().unlink()
        if annuelles and not self.env.context.get('eurekam_sync'):
            # Les lignes supprimees ne comptent plus : on recalcule depuis
            # celles qui restent, via une ligne survivante de chaque annee.
            restantes = self.env['sale.order.line'].search([
                ('maintenance_line_id', 'in', annuelles.ids),
                ('maintenance_kind', '=', 'contract'),
            ])
            restantes._sync_vers_ligne_annuelle()
        return res
