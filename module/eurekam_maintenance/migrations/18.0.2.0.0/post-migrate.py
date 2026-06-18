"""Data migration for eurekam_maintenance 18.0.2.0.0.

Converts the two former Selection fields into the new editable relational
lists, preserving existing values, and deactivates the two module-billing
entries dropped per team feedback.

Every step is guarded: a failure is logged but never raised, so a partial
data quirk can never break the module update / build.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1) Contract.market_type (selection) -> market_type_ids (many2many)
    try:
        by_code = {
            m.code: m.id
            for m in env['eurekam.market.type'].search([]) if m.code
        }
        contracts = env['eurekam.maintenance.contract'].search([
            ('market_type', '!=', False),
            ('market_type_ids', '=', False),
        ])
        migrated = 0
        for contract in contracts:
            target = by_code.get(contract.market_type)
            if target:
                contract.market_type_ids = [(4, target)]
                migrated += 1
        _logger.info(
            "eurekam_maintenance: migrated market_type on %d/%d contract(s).",
            migrated, len(contracts),
        )
    except Exception as exc:  # noqa: BLE001 - never break the update
        _logger.warning("eurekam_maintenance: market_type migration skipped (%s).", exc)

    # 2) Partner.central_purchasing (selection) -> central_purchasing_id (m2o)
    try:
        by_code = {
            m.code: m.id
            for m in env['eurekam.central.purchasing'].search([]) if m.code
        }
        partners = env['res.partner'].search([
            ('central_purchasing', '!=', False),
            ('central_purchasing_id', '=', False),
        ])
        migrated = 0
        for partner in partners:
            target = by_code.get(partner.central_purchasing)
            if target:
                partner.central_purchasing_id = target
                migrated += 1
        _logger.info(
            "eurekam_maintenance: migrated central_purchasing on %d/%d partner(s).",
            migrated, len(partners),
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "eurekam_maintenance: central_purchasing migration skipped (%s).", exc,
        )

    # 3) Deactivate the legacy module-billing entries (kept in DB for existing
    #    references, just hidden from the selection lists).
    try:
        for xmlid in ('eurekam_maintenance.mod_bill_none',
                      'eurekam_maintenance.mod_bill_free_valued'):
            rec = env.ref(xmlid, raise_if_not_found=False)
            if rec and rec.active:
                rec.active = False
                _logger.info("eurekam_maintenance: deactivated %s.", xmlid)
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "eurekam_maintenance: module-billing deactivation skipped (%s).", exc,
        )
