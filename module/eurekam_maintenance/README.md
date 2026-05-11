# Eurekam Maintenance

Module Odoo 18 de suivi des contrats de maintenance Drugcam pour Eurekam.
Remplace le suivi historique fait dans Notion (table « Assistance DO »).

## État du développement

| Phase | Contenu | Statut |
|-------|---------|--------|
| 0 | Garde-fou environnement TEST | ✅ Fait |
| 1 | Modèle `eurekam.maintenance.contract` (de base) + vues + sécurité + séquence | ✅ Fait |
| 2 | Lignes annuelles `eurekam.maintenance.contract.line` + montants 2023→2029 | ✅ Fait |
| 3 | Extension `res.partner` (établissements, équipements, modules…) | ✅ Fait |
| 4 | Cadences de facturation + facturation modules | ✅ Fait |
| 5 | Wizard de renouvellement + révision Syntec | ✅ Fait |
| 6 | Création de facture depuis contrat | ✅ Fait |
| 7 | Cron d'expiration + emails | ✅ Fait |
| 8 | Dashboard pivot/graph + rapport PDF | ✅ Fait |
| 9 | Tests unitaires + données de démo | ✅ Fait |

## Installation

⚠️ **Tout déploiement passe par les scripts de `scripts/` qui appellent en
première étape le garde-fou `00_check_environment.py` pour s'assurer qu'on
cible la base de TEST. Voir le `CLAUDE.md` à la racine du dépôt.**

## Auteur

Eurekam — https://www.eurekam.fr
