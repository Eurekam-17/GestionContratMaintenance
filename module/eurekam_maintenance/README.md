# Eurekam Maintenance

Module Odoo 18 de suivi des contrats de maintenance Drugcam pour Eurekam.
Remplace le suivi historique fait dans Notion (table « Assistance DO »).

## État du développement

| Phase | Contenu | Statut |
|-------|---------|--------|
| 0 | Garde-fou environnement TEST | ✅ Fait |
| 1 | Modèle `eurekam.maintenance.contract` (de base) + vues + sécurité + séquence | 🟢 En cours |
| 2 | Lignes annuelles `eurekam.maintenance.contract.line` + montants 2023→2029 | ⏳ À faire |
| 3 | Extension `res.partner` (établissements, équipements, modules…) | ⏳ À faire |
| 4 | Cadences de facturation + facturation modules | ⏳ À faire |
| 5 | Wizard de renouvellement + révision Syntec | ⏳ À faire |
| 6 | Création de facture depuis contrat | ⏳ À faire |
| 7 | Cron d'expiration + emails | ⏳ À faire |
| 8 | Dashboard pivot/graph + rapport PDF | ⏳ À faire |
| 9 | Tests unitaires + données de démo | ⏳ À faire |

## Installation

⚠️ **Tout déploiement passe par les scripts de `scripts/` qui appellent en
première étape le garde-fou `00_check_environment.py` pour s'assurer qu'on
cible la base de TEST. Voir le `CLAUDE.md` à la racine du dépôt.**

## Auteur

Eurekam — https://www.eurekam.fr
