# -*- coding: utf-8 -*-
"""Repare les devis par periode emis sans annee.

Avant la 18.0.2.5.1, le mode "un devis par periode" posait 0 dans
eurekam_maintenance_year. Consequences : l onglet Maintenance affichait
"0", les periodes deja devisees n etaient plus reconnues, et relancer
l assistant heurtait la contrainte d unicite au lieu de completer les
trimestres manquants.

Corriger le code ne corrige pas les devis deja emis : l annee se deduit
de la ligne annuelle que chaque ligne de commande designe. Ne touche
qu aux devis portant une periode ET aucune annee, et seulement quand
leurs lignes s accordent sur une seule annee.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    commandes = env['sale.order'].search([
        ('eurekam_maintenance_period', '!=', False),
        ('eurekam_maintenance_year', 'in', [0, False]),
    ])
    if not commandes:
        _logger.info("eurekam_maintenance: aucun devis par periode a reparer")
        return

    repares, ambigus = 0, []
    for commande in commandes:
        annees = {ligne.maintenance_line_id.year
                  for ligne in commande.order_line
                  if ligne.maintenance_line_id}
        annees.discard(0)
        if len(annees) == 1:
            # eurekam_sync pour ne pas relancer la synchronisation vers les
            # lignes : on ne corrige qu une etiquette.
            commande.with_context(eurekam_sync=True).write({
                'eurekam_maintenance_year': annees.pop(),
            })
            repares += 1
        else:
            ambigus.append((commande.name, sorted(annees)))

    _logger.info("eurekam_maintenance: %d devis par periode reannotes, "
                 "%d laisses de cote", repares, len(ambigus))
    for nom, annees in ambigus:
        _logger.warning("eurekam_maintenance: %s - annees %s, non tranchable",
                        nom, annees or 'aucune')
