"""Extension of account.move to handle the recompute of maintenance lines.

Bug: when an account.move (invoice) linked to one or more
eurekam.maintenance.contract.line through the invoice_ids m2m is deleted, the
relation table is cleaned but the stored computed fields depending on it
(invoice_count, is_invoiced) are not automatically recomputed.

Solution: override unlink to capture the linked maintenance lines before the
deletion, then invalidate and recompute afterwards.
"""

from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def unlink(self):
        # Capture the linked maintenance lines BEFORE deletion
        # (after unlink the m2m is cleaned and the ids can no longer be found).
        #
        # IMPORTANT: we use sudo(). Deleting an invoice is a standard accounting
        # operation, available to users who do NOT have the Maintenance module
        # rights (accountants, etc.). Without sudo(), the search() below raises
        # an AccessError on eurekam.maintenance.contract.line and breaks the
        # deletion of any invoice (regression on the standard account tests).
        maint_lines = self.env['eurekam.maintenance.contract.line'].sudo()
        affected_lines = maint_lines.search([('invoice_ids', 'in', self.ids)])
        res = super().unlink()
        if affected_lines:
            # Force the recompute of the stored fields depending on invoice_ids
            # (recordset already in sudo -> writing stored fields is allowed).
            affected_lines.invalidate_recordset(
                fnames=['invoice_count', 'is_invoiced'],
            )
            affected_lines._compute_invoice_status()
        return res
