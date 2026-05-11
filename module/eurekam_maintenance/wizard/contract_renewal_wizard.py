"""Wizard de renouvellement d'un contrat de maintenance.

Pre-remplit un nouveau contrat depuis l'ancien, decale les dates,
applique optionnellement la revision Syntec, cree le nouveau contrat
en etat 'active' et bascule l'ancien en etat 'renewed'.

Les deux contrats sont chaines via le champ renewed_from_id sur le nouveau.
"""

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Mapping de la duree (Selection) vers nombre d'unites pour relativedelta.
# 6 mois est un cas particulier traite a part.
DURATION_TO_YEARS = {
    '1y': 1,
    '2y': 2,
    '3y': 3,
    '4y': 4,
    '5y': 5,
}

# Coefficient Syntec par defaut applique si l'utilisateur ne le modifie pas.
DEFAULT_SYNTEC_RATE = 3.0


def _calc_end_date(start, duration):
    """Calcule la date de fin depuis date_start et un code de duree.

    La date de fin est inclusive : un contrat de 1 an demarrant le 01/01/2026
    finit le 31/12/2026 (et non le 01/01/2027).
    """
    if not start or not duration:
        return False
    if duration == '6m':
        return start + relativedelta(months=6, days=-1)
    years = DURATION_TO_YEARS.get(duration, 1)
    return start + relativedelta(years=int(years), days=-1)


class EurekamContractRenewalWizard(models.TransientModel):
    _name = 'eurekam.contract.renewal.wizard'
    _description = "Assistant de renouvellement d'un contrat de maintenance"

    # ------------------------------------------------------------------
    # Contrat source
    # ------------------------------------------------------------------
    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contrat à renouveler',
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='contract_id.partner_id',
        string='Établissement',
        readonly=True,
    )
    product_id = fields.Many2one(
        related='contract_id.product_id',
        string='Produit',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Nouveau contrat — dates et durée
    # ------------------------------------------------------------------
    new_date_start = fields.Date(
        string='Nouvelle date de début',
        required=True,
    )
    new_date_end = fields.Date(
        string='Nouvelle date de fin',
        required=True,
    )
    new_duration = fields.Selection(
        [
            ('6m', '6 mois'),
            ('1y', '1 an'),
            ('2y', '2 ans'),
            ('3y', '3 ans'),
            ('4y', '4 ans'),
            ('5y', '5 ans'),
        ],
        string='Durée',
        required=True,
    )

    # ------------------------------------------------------------------
    # Revision Syntec
    # ------------------------------------------------------------------
    apply_syntec = fields.Boolean(
        string='Appliquer la révision Syntec',
        default=False,
    )
    syntec_rate = fields.Float(
        string='Taux Syntec (%)',
        default=DEFAULT_SYNTEC_RATE,
        digits=(5, 2),
        help="Pourcentage de revalorisation appliqué au montant de maintenance.",
    )

    # ------------------------------------------------------------------
    # Montants
    # ------------------------------------------------------------------
    old_amount = fields.Monetary(
        string='Ancien montant',
        currency_field='currency_id',
        readonly=True,
    )
    syntec_delta = fields.Monetary(
        string='Augmentation Syntec',
        currency_field='currency_id',
        compute='_compute_syntec_delta',
    )
    new_maintenance_amount = fields.Monetary(
        string='Nouveau montant de maintenance',
        currency_field='currency_id',
        required=True,
    )

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------
    generate_lines = fields.Boolean(
        string='Générer les lignes annuelles du nouveau contrat',
        default=True,
    )
    cancel_old_lines_invoiced = fields.Boolean(
        string="Marquer les lignes non facturées comme transférées",
        default=False,
        help="Ajoute une note dans les lignes annuelles non facturées de "
             "l'ancien contrat pour signaler le report sur le nouveau.",
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
        """Met à jour le nouveau montant quand on (dé)coche Syntec."""
        if self.apply_syntec and self.old_amount:
            self.new_maintenance_amount = round(
                self.old_amount * (1 + self.syntec_rate / 100.0), 2
            )
        elif not self.apply_syntec:
            self.new_maintenance_amount = self.old_amount

    @api.onchange('new_date_start', 'new_duration')
    def _onchange_duration(self):
        """Recalcule new_date_end automatiquement."""
        if self.new_date_start and self.new_duration:
            self.new_date_end = _calc_end_date(self.new_date_start, self.new_duration)

    # ==================================================================
    # Default get : pre-remplissage depuis le contrat source
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
    # Action principale
    # ==================================================================

    def action_renew(self):
        """Cree le nouveau contrat (etat actif) et bascule l'ancien en 'renewed'."""
        self.ensure_one()
        old = self.contract_id

        if old.state in ('renewed', 'cancelled'):
            raise UserError(_(
                "Ce contrat est %s, impossible de le renouveler.",
                dict(old._fields['state'].selection).get(old.state),
            ))
        if not self.new_date_start or not self.new_date_end:
            raise UserError(_("Renseigner la nouvelle date de début et de fin."))
        if self.new_date_end < self.new_date_start:
            raise UserError(_(
                "La nouvelle date de fin doit être postérieure à la date de début."
            ))
        if self.new_maintenance_amount < 0:
            raise UserError(_("Le nouveau montant ne peut pas être négatif."))

        # --- Construction des valeurs du nouveau contrat -------------------
        new_comment_parts = [_(
            "Renouvellement de %(seq)s du %(start)s au %(end)s.",
            seq=old.sequence_number,
            start=old.date_start or '?',
            end=old.date_end or '?',
        )]
        if self.apply_syntec:
            new_comment_parts.append(_(
                "Révision Syntec appliquée : +%(rate).2f %% (delta = %(delta).2f).",
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
            'market_type': old.market_type,
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
            'renewed_from_id': old.id,
        }
        new_contract = self.env['eurekam.maintenance.contract'].create(new_vals)

        # --- Lignes annuelles du nouveau contrat ---------------------------
        if self.generate_lines:
            new_contract.action_generate_lines()

        # --- Note sur les lignes anciennes non facturees -------------------
        if self.cancel_old_lines_invoiced:
            for line in old.line_ids.filtered(lambda l: not l.is_invoiced):
                note = _(
                    "Reportée sur le renouvellement %(seq)s.",
                    seq=new_contract.sequence_number,
                )
                line.notes = (line.notes or '') + ('\n' if line.notes else '') + note

        # --- Bascule l'ancien en 'renewed' ---------------------------------
        old.message_post(body=_(
            "Contrat renouvelé via le wizard. Nouveau contrat : %s.",
            new_contract.sequence_number,
        ))
        new_contract.message_post(body=_(
            "Renouvellement de %s.",
            old.sequence_number,
        ))
        old.write({'state': 'renewed'})

        # --- Ouvre le nouveau contrat --------------------------------------
        return {
            'name': _("Nouveau contrat — %s", new_contract.sequence_number),
            'type': 'ir.actions.act_window',
            'res_model': 'eurekam.maintenance.contract',
            'res_id': new_contract.id,
            'view_mode': 'form',
            'target': 'current',
        }
