# GestionContratMaintenance

Module Odoo 18 Enterprise pour la gestion du cycle de vie des contrats de
maintenance Drugcam d'**Eurekam**.

Ce projet remplace le suivi historique réalisé dans Notion (table
« Assistance DO ») et centralise dans Odoo : les contrats multi-annuels, les
montants par année, les cadences de facturation, la révision Syntec, les
alertes d'expiration et le suivi par établissement.

---

## Sommaire

- [Contexte](#contexte)
- [Architecture](#architecture)
- [Avancement](#avancement)
- [Sécurité — règle absolue](#sécurité--règle-absolue)
- [Mise en route](#mise-en-route)
- [Déploiement sur odoo.sh](#déploiement-sur-odoosh)
- [Structure du dépôt](#structure-du-dépôt)
- [Documentation](#documentation)
- [Auteur & licence](#auteur--licence)

---

## Contexte

Eurekam commercialise des solutions Drugcam auprès d'hôpitaux (CH, CHU, CLCC,
CL, HIA) en France et à l'international. Chaque client a un ou plusieurs
contrats de maintenance annuels avec des montants évolutifs, des cadences de
facturation variées (annuelle, semestrielle, trimestrielle, échu, à échoir…)
et des révisions tarifaires basées sur l'indice Syntec.

Le module unifie le tout dans Odoo avec :

- Cycle de vie complet : brouillon → actif → expire bientôt → expiré → renouvelé
- Suivi des montants annuels (2023 → 2029 et au-delà)
- Workflow de renouvellement avec révision Syntec automatique
- Alertes d'expiration (cron quotidien) avec emails au commercial / manager
- Création de facture depuis un contrat (lien vers `account.move`)
- Tableau de bord pivot / graph + rapport PDF
- Extension de `res.partner` pour les établissements clients (type, statut,
  centrale d'achat, équipements, postes, modules…)

---

## Architecture

| | |
|---|---|
| **Cible**         | Odoo 18.0 Enterprise sur [odoo.sh](https://www.odoo.sh) |
| **Module**        | `eurekam_maintenance` |
| **Dépendances**   | `base`, `mail`, `product`, `contacts` (Phase 1) — `sale_management`, `account` ajoutés en Phase 6 |
| **Instance TEST** | `https://eurekam-recette.odoo.com` (staging odoo.sh, base renommée à chaque rebuild) |
| **Instance PROD** | déploiement manuel par Loïc après validation finale |

---

## Avancement

| Phase | Contenu                                                                                  | Statut |
|------:|------------------------------------------------------------------------------------------|--------|
|     0 | Garde-fou environnement TEST (`scripts/00_check_environment.py`)                         | Fait   |
|     1 | Modèle `eurekam.maintenance.contract` + vues form/list/kanban/search + sécurité + séquence | Fait   |
|     2 | Lignes annuelles `eurekam.maintenance.contract.line` (2023 → 2029)                       | Fait   |
|     3 | Extension `res.partner` (établissements, équipements, modules, versions produit)         | Fait   |
|     4 | Cadences de facturation + facturation modules (`billing_frequency`, `module_billing`)    | Fait   |
|     5 | Wizard de renouvellement + révision Syntec                                               | Fait   |
|     6 | Création de facture depuis contrat (intégration `account`)                               | Fait   |
|     7 | Cron d'expiration + emails de notification                                               | Fait   |
|     8 | Dashboard pivot/graph + rapport PDF                                                      | Fait   |
|     9 | Tests unitaires + données de démo                                                        | Fait   |

---

## Sécurité — règle absolue

> **Ce module est développé, installé et testé EXCLUSIVEMENT sur la base de
> TEST odoo.sh d'Eurekam.**
>
> **Aucune action n'est exécutée sur la base de PRODUCTION tant que Loïc ne
> l'a pas explicitement validé en fin de projet.**

Le script `scripts/00_check_environment.py` est appelé en **première étape** de
toute opération automatisée et vérifie :

1. Le fichier `config/odoo_test.json` existe et est lisible.
2. Le champ `environment` vaut `TEST`.
3. L'URL contient au moins un mot-clé de test
   (`test`, `staging`, `dev`, `preprod`, `recette`, `sandbox`).
4. L'URL ne contient aucun mot-clé interdit (`prod`, `production`, `main`).
5. La base Odoo cible est résolue (nom exact, ou auto-découverte via
   `database_pattern` regex sur `db.list()`).
6. La connexion XML-RPC aboutit et la version serveur est lisible.
7. L'authentification réussit avec les credentials fournis.

Si une vérification échoue, le script renvoie un code d'erreur ≠ 0 et toute
opération appelante doit être annulée.

---

## Mise en route

### 1. Cloner le dépôt

```bash
git clone https://github.com/Eurekam-17/GestionContratMaintenance.git
cd GestionContratMaintenance
```

### 2. Préparer la configuration

```bash
cp config/odoo_test.json.example config/odoo_test.json
# Editer config/odoo_test.json :
#   - url       : URL de l'instance staging (ex: https://eurekam-recette.odoo.com)
#   - database  : nom EXACT de la base courante (change a chaque rebuild odoo.sh)
#   - username  : email Odoo
#   - password  : mot de passe ou cle API Odoo
```

> Le fichier `config/odoo_test.json` est gitignored : il ne doit **jamais** être committé.

### 3. Vérifier l'environnement

```bash
python scripts/00_check_environment.py
```

Sortie attendue :

```
============================================================
>> ENVIRONNEMENT : TEST
>> URL           : https://eurekam-recette.odoo.com
============================================================
>> Base resolue  : eurekam-staging-XXXXXXXX
OK Connexion XML-RPC reussie. Version serveur : 18.0+e
OK Authentification reussie (uid=X) sur la base 'eurekam-staging-XXXXXXXX'.

OK Toutes les verifications sont passees. Vous pouvez continuer.
```

Si la base a été renommée par un rebuild odoo.sh (warning au lancement), il
suffit de mettre à jour le champ `database` dans `config/odoo_test.json` avec
le nouveau nom (visible dans l'onglet **Builds** d'odoo.sh).

---

## Déploiement sur odoo.sh

1. Connecter ce dépôt GitHub à l'instance odoo.sh
   (**Settings → Repository → Connect GitHub repository**).
2. Configurer la branche `main` comme branche de **staging / dev** (jamais
   directement comme branche de production tant que le module n'est pas validé).
3. odoo.sh build automatiquement une nouvelle instance à chaque push
   (5 à 15 min).
4. Une fois le build vert :
   - Se connecter à `https://eurekam-recette.odoo.com`
   - **Apps → Mettre à jour la liste des Apps**
   - Rechercher « Eurekam », installer le module
5. Vérifier l'apparition du menu **Maintenance → Contrats**.

---

## Structure du dépôt

```
.
├── CLAUDE.md                       Regles de developpement & specifications detaillees
├── README.md                       Ce fichier
├── .gitignore                      Exclut credentials, caches, fichiers locaux
├── .gitattributes                  Normalise les fins de ligne (LF/CRLF)
├── config/
│   ├── odoo_test.json.example      Modele de configuration (sans credentials)
│   └── odoo_test.json              Credentials reels (gitignored)
├── scripts/
│   └── 00_check_environment.py     Garde-fou environnement TEST
└── module/
    └── eurekam_maintenance/        Le module Odoo
        ├── __init__.py
        ├── __manifest__.py
        ├── README.md               Description visible dans Odoo Apps
        ├── data/                   Sequences, donnees initiales
        ├── models/                 Modeles Python
        ├── security/               Groupes, ACL, record rules
        └── views/                  Vues XML form / list / kanban / search / menus
```

---

## Documentation

- **[docs/guide_utilisateur.md](docs/guide_utilisateur.md)** — guide pas-à-pas
  en français pour les testeurs Eurekam (commerciaux, ADV, support,
  manageurs). Contient le workflow standard, les cas spéciaux, les indicateurs
  fiche partenaire pour le support, et une FAQ.
- **[CLAUDE.md](CLAUDE.md)** — règles de développement complètes, architecture
  détaillée des modèles, correspondance Notion ↔ Odoo, checklist de validation
  finale.
- **[module/eurekam_maintenance/README.md](module/eurekam_maintenance/README.md)**
  — description du module (visible dans Odoo Apps).

---

## Auteur & licence

- **Auteur** : [Eurekam](https://www.eurekam.fr) — Loïc Tamarelle
- **Licence** : LGPL-3
