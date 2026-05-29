"""Wizard de creation d'une commande client (sale.order) pour un contrat.

Cas d'usage : a la reception d'un Bon de Commande client, on cree un
sale.order pre-rempli avec N lignes selon la cadence du contrat
(1 pour Annuelle, 2 pour Semestrielle, 4 pour Trimestrielle).

L'utilisateur peut aussi choisir le mode "Periode integrale" qui cree
un SO avec une seule ligne couvrant toutes les annees restantes du contrat.

Apres creation, le SO est en brouillon. L'utilisateur le valide ensuite
via le workflow Sales natif d'Odoo (Confirmer la commande), puis facture
chaque ligne au fil du temps (T1 d'abord, puis T2 trois mois plus tard,
etc.) via le bouton natif "Creer une facture".
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EurekamMaintenanceOrderWizard(models.TransientModel):
    _name = 'eurekam.maintenance.order.wizard'
    _description = "Assistant de creation d'une commande client maintenance"

    # ------------------------------------------------------------------
    # Contrat source
    # ------------------------------------------------------------------
    contract_id = fields.Many2one(
        'eurekam.maintenance.contract',
        string='Contrat',
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='contract_id.partner_id',
        string='Client',
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
    # Choix de l'utilisateur
    # ------------------------------------------------------------------
    coverage_mode = fields.Selection(
        [
            ('annual_split', "Année (découpée selon cadence)"),
            ('full_contract', "Intégralité du contrat (cas rare)"),
        ],
        string='Périmètre de la commande',
        default='annual_split',
        required=True,
    )
    year = fields.Integer(
        string='Année couverte',
        help="Année du contrat couverte par la commande. "
             "Ignoré si périmètre = Intégralité du contrat.",
    )
    customer_po_reference = fields.Char(
        string='Référence BC client',
        required=True,
        help="Numéro de Bon de Commande envoyé par le client.",
    )
    customer_po_date = fields.Date(
        string='Date de réception du BC',
        required=True,
        default=fields.Date.context_today,
    )

    # ------------------------------------------------------------------
    # Apercu (affiche pour info dans la vue wizard)
    # ------------------------------------------------------------------
    preview_period_count = fields.Integer(
        string='Nombre de lignes à créer',
        compute='_compute_preview',
    )
    preview_total_amount = fields.Monetary(
        string='Montant total HT',
        compute='_compute_preview',
        currency_field='currency_id',
    )

    # ==================================================================
    # Compute
    # ==================================================================
    @api.depends('contract_id', 'year', 'coverage_mode')
    def _compute_preview(self):
        for w in self:
            if not w.contract_id:
                w.preview_period_count = 0
                w.preview_total_amount = 0.0
                continue
            if w.coverage_mode == 'full_contract':
                w.preview_period_count = 1
                w.preview_total_amount = sum(w.contract_id.line_ids.mapped('amount'))
                continue
            # annual_split
            line = w.contract_id.line_ids.filtered(lambda l, y=w.year: l.year == y)
            if not line:
                w.preview_period_count = 0
                w.preview_total_amount = 0.0
                continue
            period_code = w.contract_id._get_billing_period_code()
            periods = w.contract_id._periods_for_year(w.year, line.amount, period_code)
            w.preview_period_count = len(periods)
            w.preview_total_amount = sum(p[1] for p in periods)

    # ==================================================================
    # Default get
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
            res['contract_id'] = contract.id
            # Annee proposee par defaut : la premiere annee future non encore
            # couverte par une commande
            covered_years = set(
                contract.sale_order_ids.mapped('eurekam_maintenance_year')
            )
            today_year = fields.Date.context_today(self).year
            for line in contract.line_ids.sorted(key=lambda l: l.year):
                if line.year >= today_year and line.year not in covered_years:
                    res['year'] = line.year
                    break
            else:
                res['year'] = today_year
        return res

    # ==================================================================
    # Action principale
    # ==================================================================
    def action_create_sale_order(self):
        """Cree le sale.order avec les lignes correspondantes."""
        self.ensure_one()
        contract = self.contract_id
        if not contract:
            raise UserError(_("Aucun contrat sélectionné."))
        if contract.state in ('cancelled', 'renewed'):
            raise UserError(_(
                "Impossible de créer une commande sur un contrat %s.",
                dict(contract._fields['state'].selection).get(contract.state),
            ))
        if not contract.product_id:
            raise UserError(_(
                "Le contrat %s n'a pas de produit lié. Renseigner le champ "
                "« Produit » avant de créer une commande.",
                contract.sequence_number,
            ))

        # Construire les vals du SO
        so_vals = {
            'partner_id': contract.partner_id.id,
            'eurekam_maintenance_contract_id': contract.id,
            'eurekam_maintenance_year': self.year if self.coverage_mode == 'annual_split' else 0,
            'client_order_ref': self.customer_po_reference,
            'date_order': fields.Datetime.to_datetime(self.customer_po_date) or fields.Datetime.now(),
            'currency_id': contract.currency_id.id,
            'company_id': contract.company_id.id,
            'origin': contract.sequence_number,
        }

        # ---- Construction des lignes ----
        product_template = contract.product_id
        product_variant = product_template.product_variant_id
        if not product_variant:
            raise UserError(_(
                "Le produit %s n'a pas de variante. Impossible de créer la commande.",
                product_template.name,
            ))

        order_lines = []

        if self.coverage_mode == 'full_contract':
            # ---- Cas rare : 1 ligne pour tout le contrat ----
            total = sum(contract.line_ids.mapped('amount'))
            if not total:
                raise UserError(_(
                    "Le contrat n'a pas de lignes annuelles avec un montant. "
                    "Générer les lignes annuelles d'abord."
                ))
            label = _(
                "Maintenance %(prod)s — Période intégrale (%(start)s → %(end)s)",
                prod=product_template.name or '',
                start=contract.date_start or '?',
                end=contract.date_end or '?',
            )
            order_lines.append((0, 0, {
                'product_id': product_variant.id,
                'name': label,
                'product_uom_qty': 1.0,
                'price_unit': total,
                'maintenance_period_label': _("Période intégrale"),
            }))
        else:
            # ---- Cas majoritaire : 1 SO par annee, N lignes selon cadence ----
            if not self.year:
                raise UserError(_("L'année à couvrir est obligatoire en mode « Année découpée »."))
            line = contract.line_ids.filtered(lambda l: l.year == self.year)
            if not line:
                raise UserError(_(
                    "Aucune ligne annuelle pour l'année %s. "
                    "Cliquer sur « Générer les lignes annuelles » sur le contrat d'abord.",
                    self.year,
                ))
            if len(line) > 1:
                raise UserError(_("Incohérence : plusieurs lignes pour l'année %s.", self.year))

            period_code = contract._get_billing_period_code()
            periods = contract._periods_for_year(self.year, line.amount, period_code)

            for label, fraction, _start, _end in periods:
                order_lines.append((0, 0, {
                    'product_id': product_variant.id,
                    'name': _(
                        "Maintenance %(prod)s — %(period)s",
                        prod=product_template.name or '',
                        period=label,
                    ),
                    'product_uom_qty': 1.0,
                    'price_unit': fraction,
                    'maintenance_line_id': line.id,
                    'maintenance_period_label': label,
                }))

        so_vals['order_line'] = order_lines

        # ---- Creation effective ----
        sale_order = self.env['sale.order'].create(so_vals)

        contract.message_post(body=_(
            "Commande client %(so)s créée pour le BC %(po)s "
            "(%(n)d ligne(s), %(mode)s).",
            so=sale_order.name,
            po=self.customer_po_reference,
            n=len(order_lines),
            mode=dict(self._fields['coverage_mode'].selection).get(self.coverage_mode),
        ))

        # Renvoyer l'action pour ouvrir le SO
        return {
            'name': _("Commande %s", sale_order.name),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }
