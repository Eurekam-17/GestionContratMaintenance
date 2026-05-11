# CLAUDE.md — Développement du module `eurekam_maintenance` sur base de TEST Odoo

## ⚠️ RÈGLE ABSOLUE — LIRE AVANT TOUTE ACTION

> **CE MODULE DOIT ÊTRE DÉVELOPPÉ, INSTALLÉ ET TESTÉ EXCLUSIVEMENT SUR LA BASE DE TEST ODOO D'EUREKAM.**
>
> **AUCUNE action (installation, mise à jour, modification de données, création d'enregistrement) ne doit être exécutée sur la base de PRODUCTION tant que l'utilisateur Loïc ne l'a pas explicitement validé en fin de projet.**

Claude Code doit respecter les garde-fous suivants à chaque lancement :

1. **Vérifier l'URL de connexion** avant toute opération : l'URL doit contenir le mot `test`, `staging`, `dev`, `preprod` ou équivalent. Si l'URL contient `prod`, `production`, ou correspond à l'URL principale de production, **STOPPER IMMÉDIATEMENT** et demander confirmation à l'utilisateur.
2. **Vérifier le nom de la base de données** : il doit correspondre explicitement à la base de test configurée dans `config/odoo_test.json`.
3. **Afficher dans la console** à chaque démarrage : `🟢 ENVIRONNEMENT : TEST — Base : <nom_base>` afin que l'utilisateur puisse confirmer visuellement.
4. **Interdire toute modification de fichier sous `C:\Odoo_Production\`** ou tout chemin contenant `prod`.
5. **En cas de doute**, demander confirmation avant d'exécuter.

---

## 🎯 Objectif du projet

Développer un module Odoo 18 nommé `eurekam_maintenance` qui remplace le suivi actuellement fait dans Notion pour gérer le cycle de vie complet des contrats de maintenance client chez Eurekam. Le développement et les tests se font sur la **base de test uniquement**. Le déploiement en production sera fait manuellement par Loïc après validation complète.

---

## 📁 Arborescence de travail Windows

Tout le développement doit se faire sous :

```
C:\ClaudeDev\eurekam_maintenance\
├── config\
│   ├── odoo_test.json          ← Connexion à la base de TEST (à créer manuellement par Loïc)
│   └── odoo_test.json.example  ← Modèle sans credentials
├── module\
│   └── eurekam_maintenance\    ← Le module Odoo lui-même (code source)
├── scripts\
│   ├── 00_check_environment.py ← Vérifie qu'on est bien sur TEST
│   ├── 01_install_module.bat   ← Installe le module sur la base de test
│   ├── 02_update_module.bat    ← Met à jour le module après modifications
│   ├── 03_run_tests.bat        ← Lance les tests unitaires
│   └── 99_reset_test_db.bat    ← Réinitialise la base de test (avec confirmation)
├── docs\
│   ├── installation_windows.md
│   ├── guide_utilisateur.md
│   └── correspondance_notion.md
└── README.md
```

### Fichier `config/odoo_test.json.example`

```json
{
    "environment": "TEST",
    "url": "https://eurekam-test.odoo.com",
    "database": "eurekam-test",
    "username": "loic.tamarelle@eurekam.fr",
    "api_key": "REMPLACER_PAR_LA_CLE_API_DE_TEST",
    "safety_check": {
        "require_test_in_url": true,
        "forbidden_url_keywords": ["prod", "production", "main"],
        "require_explicit_confirmation": false
    }
}
```

**Important** : le vrai fichier `config/odoo_test.json` doit être créé manuellement par Loïc et ajouté à `.gitignore`. Il ne doit **jamais** contenir les credentials de production.

---

## 🛡️ Script de garde-fou `scripts/00_check_environment.py`

Ce script DOIT être exécuté avant toute autre opération. Il doit :

1. Lire le fichier `config/odoo_test.json`
2. Vérifier que `environment == "TEST"`
3. Vérifier que l'URL contient au moins un mot-clé de test (`test`, `staging`, `dev`, `preprod`)
4. Vérifier que l'URL ne contient AUCUN mot-clé interdit
5. Se connecter à Odoo et vérifier le nom de la base
6. Afficher le résultat et bloquer l'exécution si une vérification échoue

Exemple de logique à implémenter :

```python
import json
import sys
import xmlrpc.client

# 1. Charger la config
with open("config/odoo_test.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# 2. Vérifier le champ "environment"
if config["environment"] != "TEST":
    print("❌ STOP : le champ 'environment' doit être 'TEST'")
    sys.exit(1)

# 3. Vérifier l'URL contient un mot-clé de test
url = config["url"].lower()
mots_cles_test = ["test", "staging", "dev", "preprod"]
if not any(mot in url for mot in mots_cles_test):
    print(f"❌ STOP : l'URL {url} ne ressemble pas à une base de test")
    sys.exit(1)

# 4. Vérifier pas de mot-clé interdit
mots_interdits = config["safety_check"]["forbidden_url_keywords"]
for mot in mots_interdits:
    if mot in url:
        print(f"❌ STOP : l'URL contient le mot interdit '{mot}'")
        sys.exit(1)

# 5. Se connecter et récupérer la version
common = xmlrpc.client.ServerProxy(f"{config['url']}/xmlrpc/2/common")
version = common.version()
print(f"🟢 ENVIRONNEMENT : TEST — Base : {config['database']}")
print(f"🟢 Version Odoo : {version.get('server_version')}")
print("✅ Vérifications OK, vous pouvez continuer.")
```

**Tout script d'installation, de mise à jour ou d'import doit appeler ce garde-fou en première étape.** S'il renvoie un code d'erreur, l'opération est annulée.

---

## 📋 Contexte métier

Eurekam commercialise des solutions Drugcam auprès d'hôpitaux (CH, CHU, CLCC, CL, HIA) en France et à l'international. Chaque client possède un ou plusieurs contrats de maintenance annuels avec des montants évolutifs par année, des cadences de facturation variées, et des révisions tarifaires (indice Syntec). Le suivi est actuellement éclaté entre Notion (contrats) et Odoo 18 (facturation, contacts, ventes). L'objectif est de tout centraliser dans Odoo.

### État Odoo (constaté sur l'instance)

- **Version** : Odoo 18.0 Enterprise
- **Modules installés pertinents** : `sale`, `sale_management`, `account` (Invoicing), `contacts`, `web_studio`, `studio_customization`
- **Module subscription** : NON installé (pas nécessaire pour ce projet)
- **Pas de modèle custom maintenance** existant
- **Produits maintenance existants** : plusieurs articles de type "service" (ex: "Maintenance logicielle et matérielle", "Maintenance Assistance DRUGCAM Oncology FR")

---

## 🏗️ Architecture du module

### Structure des fichiers à générer

```
module/eurekam_maintenance/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── maintenance_contract.py        # Modèle principal
│   ├── maintenance_contract_line.py   # Lignes annuelles
│   ├── billing_frequency.py           # Cadences de facturation
│   ├── module_billing.py              # Types de facturation module
│   └── res_partner.py                 # Extension des contacts (établissements)
├── views/
│   ├── maintenance_contract_views.xml
│   ├── maintenance_contract_line_views.xml
│   ├── res_partner_views.xml
│   ├── billing_config_views.xml
│   ├── menu_views.xml
│   └── dashboard_views.xml
├── security/
│   ├── ir.model.access.csv
│   └── maintenance_security.xml
├── data/
│   ├── billing_frequency_data.xml
│   ├── module_billing_data.xml
│   ├── sequence_data.xml
│   ├── cron_data.xml
│   └── mail_template_data.xml
├── wizard/
│   ├── __init__.py
│   ├── contract_renewal_wizard.py
│   └── contract_renewal_wizard_views.xml
├── report/
│   ├── contract_report.xml
│   └── contract_report_templates.xml
├── tests/
│   ├── __init__.py
│   └── test_maintenance_contract.py
├── i18n/
│   └── fr.po
├── static/
│   └── description/
│       └── icon.png
└── README.md
```

### Manifeste (`__manifest__.py`)

```python
{
    'name': 'Eurekam - Suivi Contrats de Maintenance',
    'version': '18.0.1.0.0',
    'category': 'Sales/Maintenance',
    'summary': 'Gestion du cycle de vie des contrats de maintenance Drugcam',
    'description': "Module de suivi des contrats de maintenance pour Eurekam. "
                   "Gere les contrats multi-annuels, la revision Syntec, "
                   "les cadences de facturation et le suivi par etablissement.",
    'author': 'Eurekam',
    'website': 'https://www.eurekam.fr',
    'license': 'LGPL-3',
    'depends': ['sale_management', 'account', 'contacts', 'mail'],
    'data': [
        'security/maintenance_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/billing_frequency_data.xml',
        'data/module_billing_data.xml',
        'data/cron_data.xml',
        'data/mail_template_data.xml',
        'wizard/contract_renewal_wizard_views.xml',
        'views/maintenance_contract_views.xml',
        'views/maintenance_contract_line_views.xml',
        'views/res_partner_views.xml',
        'views/billing_config_views.xml',
        'views/menu_views.xml',
        'views/dashboard_views.xml',
        'report/contract_report.xml',
        'report/contract_report_templates.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
```

---

## 📊 Modèles de données

### 1. `eurekam.maintenance.contract` — Contrat de maintenance

Correspond à une ligne de la table Notion "Assistance DO".

| Champ Odoo | Type | Correspond à (Notion) | Valeurs / Notes |
|---|---|---|---|
| `name` | Char (computed) | — | Format : `[Séquence] - [Établissement] - [Produit]` |
| `sequence_number` | Char | — | Auto : `MAINT/2025/0001` |
| `product_id` | Many2one → `product.template` | `Produit` | |
| `product_name` | Char | `Produit` | Saisie libre si pas de produit lié |
| `partner_id` | Many2one → `res.partner` | `Etablissements` | Filtré `is_maintenance_establishment=True` |
| `commercial_id` | Many2one → `res.users` | `Commercial` | |
| `gen` | Selection | `GEN` | `gen1`, `gen2`, `upgrade_gen2` |
| `market_type` | Selection | `Marché` | `uniha_2019`, `uniha_2021`, `uniha_2023`, `uniha_2024`, `uniha_2025`, `ageps`, `market_internal`, `private`, `distributor` |
| `order_status` | Selection | `Status de Cde` | `received`, `pending`, `no_po`, `deploying`, `suspended` |
| `date_start` | Date | `Début Contrat` | |
| `date_end` | Date | `Fin Contrat` | |
| `duration` | Selection | `Nbre d'années commandées` | `6m`, `1y`, `2y`, `3y`, `4y`, `5y` |
| `billing_frequency_ids` | Many2many → `eurekam.billing.frequency` | `Cadence de facturation` | |
| `billing_level` | Selection | `Niveau de facturation` | `100`, `75`, `50`, `25`, `0` |
| `maintenance_amount` | Float | `Montant de maintenance` | € |
| `syntec_revision` | Selection | `Révision Syntec` | `yes`, `no` |
| `module_billing_ids` | Many2many → `eurekam.module.billing` | `Facturation Assistance module` | |
| `nb_products` | Integer | `Nbre de produits` | |
| `comment` | Text | `Commentaire` | |
| `state` | Selection | — | `draft`, `active`, `expiring`, `expired`, `renewed`, `cancelled` |
| `line_ids` | One2many → `eurekam.maintenance.contract.line` | Colonnes 2023-2029 | |
| `country_id` | Many2one → `res.country` | `Pays` (rollup) | Computed depuis partner_id |
| `currency_id` | Many2one → `res.currency` | — | EUR par défaut |
| `company_id` | Many2one → `res.company` | — | |
| `active` | Boolean | — | |
| `color` | Integer | — | Kanban |

**Héritage** : `mail.thread`, `mail.activity.mixin`

**Champs calculés** :
- `total_contract_value` : somme des `line_ids.amount`
- `current_year_amount` : montant de la ligne de l'année courante
- `days_to_expiry` : `(date_end - today).days`
- `is_expiring_soon` : True si `0 <= days_to_expiry <= 90`

**Méthodes** :
- `action_activate()` → passe en `active`
- `action_renew()` → ouvre le wizard de renouvellement
- `action_cancel()` → passe en `cancelled`
- `action_create_invoice()` → crée un `account.move` de type `out_invoice` pour l'année courante
- `_cron_check_expiring_contracts()` → job quotidien, bascule les états et envoie les alertes email
- `_compute_days_to_expiry()`, `_compute_total_contract_value()`, `_compute_current_year_amount()`

### 2. `eurekam.maintenance.contract.line` — Ligne annuelle

| Champ | Type | Description |
|---|---|---|
| `contract_id` | Many2one → contrat | Parent |
| `year` | Integer | Ex: 2025 |
| `amount` | Float | Montant € |
| `is_invoiced` | Boolean | Facturée ? |
| `invoice_id` | Many2one → `account.move` | Facture liée |
| `notes` | Text | |

**Contrainte** : `(contract_id, year)` doit être unique.

### 3. `eurekam.billing.frequency` — Cadences de facturation

| Champ | Type | Valeurs initiales (fichier XML) |
|---|---|---|
| `name` | Char | Annuelle, échu, échoir, Période intégrale, Semestrielle, Trimestrielle |
| `code` | Char | `annual`, `overdue`, `upcoming`, `full_period`, `semi_annual`, `quarterly` |
| `active` | Boolean | |

### 4. `eurekam.module.billing` — Types facturation module

| Champ | Type | Valeurs initiales |
|---|---|---|
| `name` | Char | gratuit (valorisé), Facturation Module Statistique, Facturation Module Essai Clinique, Aucun module |
| `code` | Char | `free_valued`, `stats`, `clinical_trial`, `none` |
| `active` | Boolean | |

### 5. Extension de `res.partner` (héritage `_inherit`)

| Champ | Type | Correspond à (Notion BD Etablissements) | Valeurs |
|---|---|---|---|
| `is_maintenance_establishment` | Boolean | — | |
| `department_number` | Char | `N° Département` | |
| `establishment_type_ids` | Many2many → `eurekam.establishment.type` | `Type` | CH, CHU, CLCC, CL, HIA, Distributeur, Labo, Université |
| `establishment_status` | Selection | `Status` | `client_eurekam`, `prospect_eurekam`, `client_distributor`, `prospect_distributor`, `client_referrer`, `prospect_referrer` |
| `central_purchasing` | Selection | `Centrale d'Achat` | `uniha`, `ageps`, `private`, `internal`, `unicancer`, `industrial` |
| `product_version_ids` | Many2many → `eurekam.product.version` | `Version` | GEN1, GEN2, Upgrade en cours, Dgm Vaccine, Mdc, Dgm Formation, DO module |
| `module_status_ids` | Many2many → `eurekam.module.status` | `Module` | beta-test, activé/non valorisé, activé/valorisé, Non précisé, Statistique, Essais Cliniques |
| `nb_workstations` | Integer | `Nb Postes` | |
| `special_equipment_ids` | Many2many → `eurekam.special.equipment` | `Equipements Speciaux` | Robot, Spectro |
| `commercial_responsible_id` | Many2one → `res.users` | `Responsable Commercial` | |
| `adv_responsible_id` | Many2one → `res.users` | `Responsable ADV` | |
| `maintenance_contract_ids` | One2many → contrats | — | |
| `maintenance_contract_count` | Integer (compute) | — | |

---

## 🖥️ Vues et interface

### Menu principal "Maintenance" (niveau 1)

Sous-menus :
1. **Contrats** — vues liste/kanban/formulaire/pivot/graph/calendrier
2. **Établissements** — liste filtrée `is_maintenance_establishment=True`
3. **Tableau de bord** — vue pivot par défaut (années × établissements)
4. **Configuration** (manager uniquement) — cadences, types de modules, types d'établissement, versions produit

### Vue formulaire contrat — onglets

1. **Informations générales** : produit, établissement, GEN, marché, statut commande, commercial
2. **Dates et durée** : début, fin, durée, jours restants (progressbar)
3. **Facturation** : montant, cadence, niveau de facturation, révision Syntec, modules
4. **Montants annuels** : one2many inline éditable avec total
5. **Notes** : commentaires

**En-tête** : statusbar + boutons "Activer", "Renouveler", "Créer facture", "Annuler"

### Vue liste contrat (colonnes par défaut, reproduit vue "Contrats" Notion)

Produit, Établissement, Statut, Marché, GEN, Modules, Nbre produits, 2024, 2025, 2026, 2027, 2028, 2029, Début, Fin, Durée, Syntec

**Groupements** : par statut, par GEN, par Syntec, par marché

### Vue Kanban

Colonnes par `order_status`. Carte affiche : nom, établissement, montant année courante, date fin, couleur selon `is_expiring_soon`.

### Vue Pivot (Dashboard)

Mesures : `maintenance_amount`, `total_contract_value`, `current_year_amount`
Axes : `partner_id`, `gen`, `market_type`, `year` (via ligne)

### Vue Calendrier

Basée sur `date_start` / `date_end`, couleur par `state`.

---

## 🔄 Logique métier

### Workflow

```
draft → active → expiring → expired
             ↘ renewed (crée un nouveau contrat via wizard)
             ↘ cancelled
```

### Cron quotidien `_cron_check_expiring_contracts`

1. Lire tous les contrats en `state='active'`
2. Pour chaque, calculer `days_to_expiry`
3. Si `0 <= days_to_expiry <= 90` → `state = 'expiring'` + email au commercial
4. Si `days_to_expiry < 0` → `state = 'expired'` + email au commercial + manager

### Wizard de renouvellement

1. Pré-remplit tous les champs du nouveau contrat depuis l'ancien
2. Dates décalées : `date_start = old.date_end + 1 jour`, `date_end = date_start + duration`
3. Si `syntec_revision == 'yes'` : propose un champ pour le nouveau montant (avec suggestion basée sur un coefficient modifiable, ex: +3 %)
4. Crée le nouveau contrat en `state='active'`
5. Passe l'ancien en `state='renewed'`
6. Lie les deux via un champ `renewed_from_id` / `renewed_to_id`

### Création de facture

Bouton → crée `account.move` type `out_invoice` :
- `partner_id` = contract.partner_id
- `invoice_line_ids` = 1 ligne avec `product_id`, `price_unit` = current_year_amount, `quantity` = 1
- Coche la ligne annuelle `is_invoiced=True` et lie `invoice_id`

---

## 🔐 Sécurité

### Groupes (`maintenance_security.xml`)

- `group_maintenance_user` : voir/modifier contrats et lignes
- `group_maintenance_manager` : + configuration + suppression + voir tout

### ACL (`ir.model.access.csv`)

| Modèle | Groupe | R | W | C | D |
|---|---|---|---|---|---|
| `eurekam.maintenance.contract` | user | ✅ | ✅ | ✅ | ❌ |
| `eurekam.maintenance.contract` | manager | ✅ | ✅ | ✅ | ✅ |
| `eurekam.maintenance.contract.line` | user | ✅ | ✅ | ✅ | ❌ |
| `eurekam.maintenance.contract.line` | manager | ✅ | ✅ | ✅ | ✅ |
| `eurekam.billing.frequency` | user | ✅ | ❌ | ❌ | ❌ |
| `eurekam.billing.frequency` | manager | ✅ | ✅ | ✅ | ✅ |
| `eurekam.module.billing` | user | ✅ | ❌ | ❌ | ❌ |
| `eurekam.module.billing` | manager | ✅ | ✅ | ✅ | ✅ |

### Record rules

- User standard : voit uniquement les contrats de sa `company_id`
- Manager : voit tout

---

## 🚀 Installation sur la base de TEST

### Étape 1 — Préparer le fichier de config

Loïc crée `C:\ClaudeDev\eurekam_maintenance\config\odoo_test.json` à partir du modèle `.example` et y renseigne ses credentials de test.

### Étape 2 — Vérifier l'environnement

Avant toute installation, Claude Code lance :

```batch
python scripts\00_check_environment.py
```

**Sortie attendue** :
```
🟢 ENVIRONNEMENT : TEST — Base : eurekam-test
🟢 Version Odoo : 18.0
✅ Vérifications OK, vous pouvez continuer.
```

Si l'un des contrôles échoue, toute opération suivante doit être annulée.

### Étape 3 — Installer le module

Deux options selon le type d'hébergement :

**Option A — Odoo SaaS standard (odoo.com)** : les modules custom ne peuvent PAS être déployés directement par fichier sur une instance SaaS standard. Si la base de test est sur odoo.com, **s'arrêter et en informer Loïc** pour choisir une alternative :
- soit utiliser Odoo Studio uniquement (moins flexible mais possible sans code)
- soit migrer la base de test vers odoo.sh ou une instance on-premise

**Option B — Odoo on-premise ou odoo.sh** : copier le dossier `module/eurekam_maintenance/` dans le répertoire `addons` d'Odoo et lancer :

```batch
scripts\01_install_module.bat
```

Contenu du script :
```batch
@echo off
echo === Verification environnement ===
python scripts\00_check_environment.py
if errorlevel 1 (
    echo Echec des verifications, installation annulee.
    pause
    exit /b 1
)

echo === Installation du module eurekam_maintenance sur la TEST ===
REM Ajuster les chemins ODOO_PATH, PYTHON_PATH selon l'installation Windows de Loic
set ODOO_PATH=C:\odoo18
set PYTHON_PATH=C:\Python310\python.exe
set ADDONS_PATH=%ODOO_PATH%\odoo\addons,%ODOO_PATH%\addons,%~dp0..\module
set DB_NAME=eurekam-test

"%PYTHON_PATH%" "%ODOO_PATH%\odoo-bin" ^
    --addons-path="%ADDONS_PATH%" ^
    -d %DB_NAME% ^
    -i eurekam_maintenance ^
    --stop-after-init

echo Installation terminee
pause
```

### Étape 4 — Mise à jour après modification

Script `scripts\02_update_module.bat` : identique mais avec `-u` au lieu de `-i`.

### Étape 5 — Lancer les tests

```batch
scripts\03_run_tests.bat
```

Contenu :
```batch
@echo off
python scripts\00_check_environment.py
if errorlevel 1 exit /b 1

set DB_NAME=eurekam-test-tests
"%PYTHON_PATH%" "%ODOO_PATH%\odoo-bin" ^
    --addons-path="%ADDONS_PATH%" ^
    -d %DB_NAME% ^
    --test-enable ^
    --test-tags eurekam_maintenance ^
    -i eurekam_maintenance ^
    --stop-after-init
```

---

## 🧪 Tests unitaires (`tests/test_maintenance_contract.py`)

Tests obligatoires à écrire :

1. `test_contract_creation` — création avec champs obligatoires
2. `test_sequence_generation` — numéro auto `MAINT/AAAA/NNNN`
3. `test_workflow_transitions` — draft → active → expiring → expired
4. `test_line_total_computation` — somme correcte des lignes
5. `test_unique_year_per_contract` — contrainte d'unicité
6. `test_expiry_cron_job` — bascule d'état + envoi email (mock)
7. `test_renewal_wizard` — pré-remplissage du nouveau contrat
8. `test_renewal_syntec_revision` — application du coefficient
9. `test_invoice_creation` — facture générée correctement
10. `test_partner_extension` — champs sur `res.partner`
11. `test_security_user_vs_manager` — droits appliqués
12. `test_company_isolation` — record rules multi-société

**Tous les tests doivent passer avant toute demande de déploiement production.**

---

## 📦 Données de démo (`demo/demo_data.xml`, chargées uniquement en mode demo)

- 3 partenaires-établissements (CH, CHU, CLCC)
- 5 contrats couvrant les cas :
  - actif GEN2 UniHA 2024 annuel 3 ans
  - expirant bientôt GEN1 Ageps semestriel
  - suspendu avec Syntec
  - en déploiement marché interne
  - expiré avec historique 2023-2026

---

## 🔗 Correspondance Notion ↔ Odoo (récap)

| Donnée Notion | Modèle Odoo | Champ |
|---|---|---|
| Table "Assistance DO" | `eurekam.maintenance.contract` | — |
| Produit | contract | `product_id` / `product_name` |
| Etablissements | contract | `partner_id` |
| GEN | contract | `gen` |
| Marché | contract | `market_type` |
| Status de Cde | contract | `order_status` |
| Début/Fin Contrat | contract | `date_start` / `date_end` |
| Nbre années | contract | `duration` |
| Cadence facturation | contract | `billing_frequency_ids` |
| Niveau facturation | contract | `billing_level` |
| Montant maintenance | contract | `maintenance_amount` |
| Révision Syntec | contract | `syntec_revision` |
| Facturation Assistance module | contract | `module_billing_ids` |
| Nbre produits | contract | `nb_products` |
| Commentaire | contract | `comment` |
| Colonnes 2023–2029 | `eurekam.maintenance.contract.line` | `year` + `amount` |
| Commercial | contract | `commercial_id` |
| Table "BD Etablissements" | `res.partner` (héritage) | champs étendus |

---

## ✅ Checklist finale avant validation par Loïc

Claude Code doit s'assurer de cocher ces points avant de remettre le module :

- [ ] Le script `00_check_environment.py` renvoie OK sur la base de TEST
- [ ] Le module s'installe sans erreur (`-i eurekam_maintenance`)
- [ ] Le module se met à jour sans erreur (`-u eurekam_maintenance`)
- [ ] Tous les tests unitaires passent (12 tests minimum)
- [ ] Les vues formulaire, liste, kanban, pivot, graph, calendrier s'affichent sans erreur dans l'interface
- [ ] Le cron d'expiration peut être déclenché manuellement et fonctionne
- [ ] Le wizard de renouvellement crée correctement un nouveau contrat
- [ ] La création de facture depuis un contrat fonctionne
- [ ] Les droits (user vs manager) se comportent comme attendu
- [ ] Données de démo chargées : 5 contrats visibles
- [ ] Documentation `docs/guide_utilisateur.md` rédigée en français
- [ ] **Aucune modification n'a été faite sur la base de production**

Une fois la checklist validée par Loïc, le déploiement production se fera manuellement par lui (ou sur sa demande explicite, lors d'une conversation dédiée avec Claude). Jamais automatiquement.

---

## 📝 Règles de travail pour Claude Code

1. **Commencer par créer** `scripts/00_check_environment.py` et `config/odoo_test.json.example`. S'arrêter et demander à Loïc de remplir son fichier `odoo_test.json` avant la suite.
2. **Tester localement** le garde-fou avant d'écrire quoi que ce soit d'autre.
3. **Développer modèle par modèle**, pas tout d'un coup : d'abord le contrat de base, valider qu'il s'installe, puis les lignes, puis les extensions `res.partner`, etc.
4. **Commit Git à chaque étape** si un dépôt est initialisé (commit messages clairs en français).
5. **Encodage UTF-8** partout, accents français conservés.
6. **Demander confirmation à Loïc** avant : toute suppression de données, tout import massif, tout déploiement production.
7. **En cas d'erreur inattendue**, s'arrêter et demander — ne pas improviser sur une base de test partagée.
