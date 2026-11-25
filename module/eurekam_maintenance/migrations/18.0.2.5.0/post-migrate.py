# -*- coding: utf-8 -*-
"""Rattache le groupe Utilisateur au nouveau groupe Lecture seule.

Pourquoi un script plutot qu une ligne de XML : group_maintenance_user a
ete cree dans un bloc <data noupdate="1">. Odoo saute ces enregistrements
a chaque mise a jour, donc declarer implied_ids dessus ne produirait
rien - ni erreur, ni effet. C est exactement le genre de modification qui
passe tous les controles de deploiement au vert sans jamais s appliquer.

L implication compte doublement :
  - un Utilisateur doit garder acces a tout ce qui est ouvert a la lecture
    seule (le menu racine, notamment) ;
  - Odoo construit l echelle du selecteur de droits a partir du graphe
    d implication, pas du nom ni de l identifiant. Sans elle, les trois
    niveaux s affichent comme des cases a cocher independantes au lieu
    d une echelle Lecture seule / Utilisateur / Gestionnaire.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    lecture = env.ref('eurekam_maintenance.group_maintenance_readonly',
                      raise_if_not_found=False)
    utilisateur = env.ref('eurekam_maintenance.group_maintenance_user',
                          raise_if_not_found=False)
    if not lecture or not utilisateur:
        _logger.warning(
            "eurekam_maintenance: groupes introuvables, implication non posee")
        return

    if lecture in utilisateur.implied_ids:
        _logger.info("eurekam_maintenance: implication deja en place")
    else:
        utilisateur.write({'implied_ids': [(4, lecture.id)]})
        _logger.info(
            "eurekam_maintenance: 'Utilisateur' implique desormais "
            "'Lecture seule'")

    # Odoo propage l implication aux membres existants a l ecriture ; on le
    # verifie plutot que de le supposer.
    manquants = utilisateur.users.filtered(lambda u: lecture not in u.groups_id)
    if manquants:
        lecture.write({'users': [(4, u.id) for u in manquants]})
        _logger.info(
            "eurekam_maintenance: %d utilisateur(s) ajoute(s) au groupe "
            "Lecture seule", len(manquants))

    _logger.info(
        "eurekam_maintenance: Lecture seule = %d membre(s), "
        "Utilisateur = %d, Gestionnaire = %d",
        len(lecture.users), len(utilisateur.users),
        len(env.ref('eurekam_maintenance.group_maintenance_manager').users))
