"""Attach an existing customer order to a maintenance contract.

The module was installed on top of years of existing practice: production
carries 648 customer orders bearing an Assistance article and pointing at no
contract, because they were issued long before the module existed. Nothing in
the interface could tie them to a contract -- the only link the order wizard
knows how to write is the one it writes itself, when it creates the order.

So every counter, every "year still to be quoted" and every invoice rollup
reported a contract as unquoted while the quotation sat in Odoo, signed.

This wizard closes that gap. It attaches the order LINE by LINE, because the
line is where the meaning is: quotation 202611234 covers the three Mondor
contracts at once, and a single Many2one on the order header cannot say so.
"""

import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Most historical lines spell the year out ("Assistance 2 Postes - Annee 1
# avec Garantie - 2027"): 936 of the 1068 lines to attach carry one. That is
# the single best signal available, so the proposal leans on it.
YEAR_IN_LABEL = re.compile(r'\b(20\d{2})\b')


class MaintenanceAttachOrderWizard(models.TransientModel):
    _name = 'eurekam.maintenance.attach.order.wizard'
    _description = "Attach an Existing Customer Order to a Contract"

    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string="Contract",
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='contract_id.partner_id',
        string="Establishment",
        readonly=True,
    )
    order_id = fields.Many2one(
        'sale.order',
        string="Customer Order",
        required=True,
        domain="[('partner_id', '=', partner_id), ('state', '!=', 'cancel')]",
        help="An order already in Odoo, issued outside the module.",
    )
    line_ids = fields.One2many(
        'eurekam.maintenance.attach.order.line',
        'wizard_id',
        string="Order Lines",
    )
    warning = fields.Text(compute='_compute_warning')

    @api.depends('line_ids.attach', 'line_ids.maintenance_line_id')
    def _compute_warning(self):
        for wiz in self:
            retenues = wiz.line_ids.filtered('attach')
            sans_annee = retenues.filtered(lambda l: not l.maintenance_line_id)
            messages = []
            if retenues and sans_annee:
                messages.append(_(
                    "%s selected line(s) have no contract year yet. "
                    "Pick one, or clear their checkbox.",
                    len(sans_annee),
                ))
            if not retenues:
                messages.append(_("No line selected: nothing will be attached."))
            wiz.warning = '\n'.join(messages) or False

    # ------------------------------------------------------------------
    # Proposal
    # ------------------------------------------------------------------
    @api.onchange('order_id')
    def _onchange_order_id(self):
        """Propose a contract year for each line of the chosen order."""
        self.line_ids = [(5, 0, 0)]
        if not self.order_id or not self.contract_id:
            return
        par_annee = {l.year: l for l in self.contract_id.line_ids}
        rows = []
        for ligne in self.order_id.order_line:
            if ligne.display_type:
                continue              # section / note, nothing to attach
            annee = self._deduire_annee(ligne)
            annuelle = par_annee.get(annee)
            rows.append((0, 0, {
                'order_line_id': ligne.id,
                'maintenance_line_id': annuelle.id if annuelle else False,
                'maintenance_kind': 'contract',
                # Only tick what we could actually place. A line nobody
                # mapped must not be attached by accident.
                'attach': bool(annuelle),
            }))
        self.line_ids = rows

    def _deduire_annee(self, order_line):
        """Guess the contract year a historical order line covers.

        Three signals, best first: the year written in the line label, the
        year the order wizard stamped on the header, then the order date.
        """
        trouvees = YEAR_IN_LABEL.findall(order_line.name or '')
        if len(set(trouvees)) == 1:
            return int(trouvees[0])
        commande = order_line.order_id
        if commande.eurekam_maintenance_year:
            return commande.eurekam_maintenance_year
        if len(set(trouvees)) > 1:
            # Several years in one label is ambiguous on purpose: better to
            # leave the row blank than to place it wrong.
            return 0
        if commande.date_order:
            return commande.date_order.year
        return 0

    # ------------------------------------------------------------------
    # Attachment
    # ------------------------------------------------------------------
    def action_attach(self):
        self.ensure_one()
        retenues = self.line_ids.filtered('attach')
        if not retenues:
            raise UserError(_("Select at least one line to attach."))
        orphelines = retenues.filtered(lambda l: not l.maintenance_line_id)
        if orphelines:
            raise UserError(_(
                "%s selected line(s) have no contract year. Pick one for "
                "each, or clear their checkbox.",
                len(orphelines),
            ))

        self._check_year_not_already_covered(retenues)

        for row in retenues:
            row.order_line_id.with_context(eurekam_sync=True).write({
                'maintenance_line_id': row.maintenance_line_id.id,
                'maintenance_kind': row.maintenance_kind,
                # maintenance_period_label is left empty on purpose. It is the
                # key _sync_vers_devis matches on to re-split a year across an
                # existing quotation; leaving it blank means the module will
                # never silently rewrite a quotation a hospital already
                # received. These orders were negotiated outside the module
                # and must stay as they were signed.
            })

        self._set_header_if_unambiguous()

        annees = sorted(set(retenues.mapped('maintenance_line_id.year')))
        self.contract_id.message_post(body=(
            "Devis %(order)s rattaché : %(n)d ligne(s) pour "
            "%(years)s." % {
                'order': self.order_id.name,
                'n': len(retenues),
                'years': ', '.join(str(a) for a in annees),
            }))
        _logger.info("Attached order %s to contract %s (%d lines, years %s).",
                     self.order_id.name, self.contract_id.sequence_number,
                     len(retenues), annees)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _check_year_not_already_covered(self, retenues):
        """Refuse to cover a contract year twice.

        Same rule as _check_maintenance_order_unicity on the order header,
        applied here because attaching writes the line link, which that
        constraint does not watch.
        """
        self.ensure_one()
        for annuelle in retenues.mapped('maintenance_line_id'):
            autres = annuelle.sale_line_ids.filtered(
                lambda l: l.order_id != self.order_id
                and l.order_id.state != 'cancel'
                and l.maintenance_kind == 'contract'
            )
            if autres:
                raise UserError(_(
                    "Year %(year)s of this contract is already covered by "
                    "order %(orders)s. Detach it first, or pick another year.",
                    year=annuelle.year,
                    orders=', '.join(sorted(set(
                        autres.mapped('order_id.name')))),
                ))

    def _set_header_if_unambiguous(self):
        """Stamp the contract on the order header when it is not a lie.

        The header carries a single contract, so it is only filled when every
        attached line of the order points at this one. A quotation spanning
        several contracts keeps an empty header and lives on its line links
        alone -- which is exactly what sale_order_ids was reworked to read.
        """
        self.ensure_one()
        commande = self.order_id
        if commande.eurekam_maintenance_contract_id:
            return
        contrats = commande.order_line.mapped(
            'maintenance_line_id.contract_id')
        if len(contrats) != 1 or contrats != self.contract_id:
            return
        annees = set(commande.order_line.mapped('maintenance_line_id.year'))
        commande.write({
            'eurekam_maintenance_contract_id': self.contract_id.id,
            'eurekam_maintenance_year': annees.pop() if len(annees) == 1 else 0,
        })


class MaintenanceAttachOrderLine(models.TransientModel):
    _name = 'eurekam.maintenance.attach.order.line'
    _description = "Line of the Attach Order Wizard"

    wizard_id = fields.Many2one(
        'eurekam.maintenance.attach.order.wizard',
        required=True,
        ondelete='cascade',
    )
    order_line_id = fields.Many2one(
        'sale.order.line',
        string="Order Line",
        required=True,
        readonly=True,
    )
    name = fields.Text(
        related='order_line_id.name',
        string="Description",
        readonly=True,
    )
    product_id = fields.Many2one(
        related='order_line_id.product_id',
        string="Product",
        readonly=True,
    )
    price_subtotal = fields.Monetary(
        related='order_line_id.price_subtotal',
        string="Amount",
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='order_line_id.currency_id',
        readonly=True,
    )
    attach = fields.Boolean(string="Attach", default=False)
    maintenance_line_id = fields.Many2one(
        'eurekam.maintenance.contract.line',
        string="Contract Year",
        domain="[('contract_id', '=', parent.contract_id)]",
    )
    maintenance_kind = fields.Selection(
        [('contract', "Contract Maintenance"),
         ('module', "Billable Module")],
        string="Kind",
        default='contract',
        required=True,
    )
