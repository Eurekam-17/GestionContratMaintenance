"""Extension d'account.move pour gerer le recompute des lignes maintenance.

Bug : quand on supprime une account.move (facture) liee a une ou plusieurs
eurekam.maintenance.contract.line via la m2m invoice_ids, la table de
liaison est bien nettoyee mais les champs computed stored qui en dependent
(invoice_count, is_invoiced) ne sont pas auto-recalcules.

Solution : override unlink pour recuperer les lignes maintenance liees
avant la suppression, puis invalider et recalculer apres.
"""

from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def unlink(self):
        # Recuperer les lignes maintenance liees AVANT la suppression
        # (apres unlink la m2m est cleanee et on ne peut plus retrouver les ids)
        affected_lines = self.env['eurekam.maintenance.contract.line'].search([
            ('invoice_ids', 'in', self.ids),
        ])
        res = super().unlink()
        if affected_lines:
            # Forcer le recompute des champs stored qui dependent de invoice_ids
            affected_lines.invalidate_recordset(
                fnames=['invoice_count', 'is_invoiced'],
            )
            # Recompute explicite pour mettre la valeur stockee a jour
            affected_lines._compute_invoice_status()
        return res
