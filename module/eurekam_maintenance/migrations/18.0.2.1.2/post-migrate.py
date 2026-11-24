"""Force the recompute of the yearly lines' ordering status.

`order_state` and `order_count` are **stored** computed fields. Odoo fills a
stored computed field when it is *added* to the model -- which happened in
18.0.2.1.0 -- but not when its compute logic later changes: no dependency of
the existing records moved, so Odoo has no reason to pass over them again.

18.0.2.1.1 excluded expired contracts from the "to order" list. The code was
deployed, every deployment check came back green -- right version, fields in
the registry, filters in the view -- and the three yearly lines of the expired
CHU Caen contract were still reported as "to order", because their stored value
dated from the previous rule.

Hence this script: it marks both fields as to-compute on every existing line
and flushes, so the stored values match the code that is actually running.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODEL = 'eurekam.maintenance.contract.line'
FIELDS = ('order_state', 'order_count')


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env[MODEL]
    lines = Line.search([])
    if not lines:
        _logger.info("Ordering status: no yearly line, nothing to recompute.")
        return

    _logger.info("Ordering status: recomputing %s on %d yearly lines.",
                 ', '.join(FIELDS), len(lines))

    for name in FIELDS:
        env.add_to_compute(Line._fields[name], lines)
    # flush_all() rather than the more targeted flush_model(): a failing
    # migration fails the build, and a failed build leaves the OLD code
    # running on the instance while git looks perfectly healthy.
    env.flush_all()

    # Logged on purpose: the build output is the only trace left once the
    # migration has run, and this is what tells apart "it ran" from "it ran and
    # actually changed something".
    cr.execute("""
        SELECT order_state, COUNT(*)
          FROM eurekam_maintenance_contract_line
      GROUP BY order_state
      ORDER BY 2 DESC
    """)
    for state, count in cr.fetchall():
        _logger.info("Ordering status: %-16s %d", state or '(null)', count)
