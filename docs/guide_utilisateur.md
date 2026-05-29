# Guide utilisateur — Module Maintenance Eurekam

> **Public visé** : commerciaux, ADV, support, manageurs Eurekam qui vont tester
> et utiliser le module de gestion des contrats de maintenance.
>
> **Version** : 18.0.1.0.0 — module `eurekam_maintenance`

---

## Sommaire

1. [À qui s'adresse ce module](#1-à-qui-sadresse-ce-module)
2. [Vocabulaire à connaître](#2-vocabulaire-à-connaître)
3. [Prérequis avant de commencer](#3-prérequis-avant-de-commencer)
4. [Workflow standard : du contrat à la facture (pas-à-pas)](#4-workflow-standard--du-contrat-à-la-facture-pas-à-pas)
5. [Cas spéciaux](#5-cas-spéciaux)
6. [Pour les équipes support : voir le statut d'un client](#6-pour-les-équipes-support--voir-le-statut-dun-client)
7. [Suivi et tableaux de bord](#7-suivi-et-tableaux-de-bord)
8. [Configuration (réservé aux Manageurs)](#8-configuration-réservé-aux-manageurs)
9. [FAQ et dépannage](#9-faq-et-dépannage)
10. [Glossaire des champs](#10-glossaire-des-champs)

---

## 1. À qui s'adresse ce module

Le module **Maintenance Eurekam** remplace le suivi historique des contrats
maintenance Drugcam fait dans Notion (table « Assistance DO »). Il centralise
dans Odoo :

- Les contrats clients pluriannuels (durée, montants annuels, marché, GEN)
- Les commandes clients (BC) reçues pour déclencher la facturation
- La génération automatique des factures selon la cadence négociée
- Les renouvellements avec révision Syntec
- Les alertes d'expiration
- L'historique complet par établissement client

Trois profils types d'utilisateurs :

| Profil | Ce qu'il fait dans le module |
|---|---|
| **Commercial** | Crée et active les contrats, saisit les BC clients, renouvelle |
| **ADV** | Valide les commandes, facture, suit les expirations |
| **Support / Helpdesk** | Consulte le statut maintenance d'un client (lecture seule) |
| **Manager** | Configure les listes (cadences, modules), gère les droits, supprime |

---

## 2. Vocabulaire à connaître

| Terme | Sens |
|---|---|
| **Contrat de maintenance** | Le contrat signé avec le client. Couvre N années (1 à 5). Identifié par un numéro `MAINT/AAAA/NNNN`. |
| **Ligne annuelle** | Une ligne par année du contrat, avec le montant correspondant. Ex : un contrat 2024→2028 a 5 lignes annuelles. |
| **Cadence de facturation** | Annuelle, Semestrielle, Trimestrielle ou Période intégrale. Détermine en combien de factures une année est découpée. |
| **Termes (échus / à échoir)** | Date d'émission de la facture : fin de période pour "échus", début pour "à échoir". |
| **BC client** (Bon de Commande) | Document que le client envoie à Eurekam pour déclencher la facturation. Stocké dans Odoo comme **commande client** (`sale.order`). |
| **Commande client** | Le `sale.order` qui matérialise le BC client dans Odoo. Contient N lignes (1 par future facture). |
| **Établissement** | Un partenaire (`res.partner`) marqué comme « Établissement de maintenance ». Hôpital, clinique, distributeur, etc. |
| **Marché** | UniHA 2024, AGEPS, Privé, etc. Type de marché public ou privé. |
| **GEN** | Version du produit Drugcam (GEN1 ou GEN2). |
| **Révision Syntec** | Indexation annuelle des prix sur l'indice Syntec (typiquement +3 %/an). |

---

## 3. Prérequis avant de commencer

### 3.1 Vérifier que tu as les bons droits

Demande à un Manager Eurekam de te donner le bon profil :

- **Maintenance Eurekam → Utilisateur** : pour gérer tes contrats
- **Maintenance Eurekam → Manager** : en plus, pour configurer et supprimer

Si tu ne vois pas le menu **Maintenance** dans la barre du haut, contacte le
Manager pour qu'il t'attribue les droits via **Configuration → Utilisateurs**.

### 3.2 Vérifier que l'établissement existe dans les Contacts

Avant de créer un contrat, vérifie que ton client existe dans **Contacts** :

1. Ouvrir le menu **Contacts** standard d'Odoo
2. Chercher le nom de l'établissement (ex: "CH de Cornouaille")
3. Si oui : ouvrir la fiche pour vérifier qu'il est bien marqué
   « **Établissement de maintenance** » (case à cocher dans le bandeau du
   formulaire, sous les Étiquettes)
4. Si non : créer la fiche normalement, puis cocher
   « Établissement de maintenance »

Une fois la case cochée, **un nouvel onglet « Maintenance Eurekam »** apparaît
sur la fiche. Le remplir avec :

- **N° département** (ex: "29" pour Finistère)
- **Statut** : Client Eurekam, Prospect, etc.
- **Centrale d'achat** : UniHA, AGEPS, Unicancer, Privé, etc.
- **Nombre de postes** (ex: 5)
- **Statuts modules** : Beta-test, Activé/valorisé, Statistique, Essais cliniques, etc.
- **Équipements spéciaux** : Robot, Spectro
- **Responsable commercial** + **Responsable ADV**

> 📝 **Note** : le type d'établissement (CH/CHU/CLCC/Université/...) et la
> version Drugcam (GEN1/GEN2) se gèrent dans les **Étiquettes** standard du
> contact (tags affichés dans le bandeau du formulaire), pas dans cet onglet.

---

## 4. Workflow standard : du contrat à la facture (pas-à-pas)

Le scénario type Eurekam est le suivant :

```
[Création contrat] → [Activation] → [Génération lignes annuelles]
        ↓
[Réception BC client annuel]
        ↓
[Création commande client (sale.order)]
        ↓
[Confirmation de la commande]
        ↓
À chaque échéance : [Facturation d'une ligne du SO] → [Validation facture]
```

### 4.1 Créer un nouveau contrat

1. **Maintenance → Contrats → Nouveau**
2. Remplir les champs :

   **Identification**
   - **Établissement** : le client (liste filtrée sur les établissements maintenance)
   - **Produit** : le produit Drugcam de la base articles (ex: "Assistance DRUGCAM GEN2 Oncology FR")
   - **Libellé produit** (optionnel) : texte libre si tu veux préciser
   - **Commercial** : pré-rempli sur toi
   - **Pays** : pré-rempli depuis l'établissement

   **Caractéristiques**
   - **Génération** : GEN1, GEN2 ou Upgrade GEN2
   - **Marché** : UniHA 2024, AGEPS, Privé, etc.
   - **Statut commande** : Reçue, En attente, Pas de BC, En déploiement, Suspendue
   - **Nombre de produits** : ex 5

   **Onglet Dates et durée**
   - **Date de début** + **Date de fin** (obligatoires)
   - **Durée commandée** : 6 mois, 1 an, 2 ans, 3 ans, 4 ans, 5 ans

   **Onglet Facturation**
   - **Montant de maintenance** (€/an)
   - **Niveau de facturation** : 100 %, 75 %, 50 %, 25 %, 0 %
   - **Révision Syntec** : Oui / Non
   - **Nécessite une commande client** : ✅ par défaut. Décocher uniquement pour
     les rares cas (privés sans BC) où on facture directement sans passer par
     une commande.
   - **Cadences de facturation** (Many2many) :
     - Choisir UNE cadence "période" : **Annuelle**, **Semestrielle**,
       **Trimestrielle** ou **Période intégrale**
     - Choisir UN timing : **À échu** ou **À échoir**
     - Si tu cumules plusieurs, Odoo bloque avec un message d'erreur.

   **Onglet Notes** : commentaires libres.

3. Cliquer **Save**. Le numéro `MAINT/2026/0001` est généré automatiquement.

### 4.2 Activer le contrat

Sur la fiche du contrat brouillon : cliquer le bouton **Activer** dans le
bandeau du haut.

- L'état passe de **Brouillon** à **Actif**
- Si la date de fin est déjà passée (contrat historique) : il passera
  directement en **Expiré** automatiquement
- Si la date de fin est dans 0–90 jours : il passera en **Expire bientôt**

### 4.3 Générer les lignes annuelles

Toujours sur la fiche : cliquer **Générer les lignes annuelles** dans le bandeau.

→ Une ligne par année du contrat est créée (ex: contrat 2024→2028 = 5 lignes
2024, 2025, 2026, 2027, 2028), chacune avec le montant `maintenance_amount`.

→ Aller dans l'onglet **Montants annuels** pour modifier le montant de chaque
année individuellement (cas fréquent : montant qui évolue Syntec d'année en
année).

→ Le **Total contrat** et **Montant année courante** se mettent à jour
automatiquement (visibles dans l'onglet **Facturation**, bloc "Totaux").

### 4.4 À réception du BC client : créer la commande

Quand le client envoie son Bon de Commande (en général 1 BC par année avec N
lignes selon la cadence), tu crées la commande dans Odoo :

1. Sur la fiche du contrat, cliquer **Créer une commande client** dans le bandeau
2. Le wizard s'ouvre :

   - **Année couverte** : pré-rempli sur la première année future non couverte
     (ex: 2026). Tu peux modifier (ex: 2024 si tu rattrapes une année passée).
   - **Référence BC client** (obligatoire) : le numéro du BC envoyé par le
     client (ex: `BC-CHSTLOUIS-2026-T1234`)
   - **Date de réception du BC** : aujourd'hui par défaut
   - **Périmètre de la commande** :
     - **Année (découpée selon cadence)** = cas standard. Le BC comporte N
       lignes selon la cadence (1 pour annuelle, 2 pour semestrielle, 4 pour
       trimestrielle).
     - **Intégralité du contrat** = cas rare. Le BC couvre toutes les années
       restantes du contrat en une seule fois (paiement d'avance).

   - **Aperçu** affiche le nombre de lignes et le montant total qui seront
     créés. Vérifie avant de valider.

3. Cliquer **Créer la commande**.

→ Une commande Odoo (`sale.order`) est créée en **Brouillon** avec N lignes.
La page de la commande s'ouvre directement.

### 4.5 Confirmer la commande

Sur la commande qui vient d'être créée :

1. Vérifier les lignes (produit, montant, période — ex: "Maintenance Drugcam
   GEN2 — T1 2026" à 3 637,50 €)
2. Cliquer **Confirmer la commande** (bouton standard Odoo Sales)

→ La commande passe de **Brouillon (devis)** à **Bon de commande**.

### 4.6 Facturer une période (à chaque échéance)

À chaque échéance trimestrielle (ou semestrielle, ou annuelle, selon ta
cadence) :

1. Ouvrir la commande client correspondante (depuis le smart-button
   « Commandes » du contrat, ou depuis **Ventes → Commandes**)
2. Cliquer **Créer une facture** (bouton standard Odoo Sales en haut)
3. Dans le popup :
   - **Type de facture** : "Facture régulière"
   - **Quantité à facturer** : laisser tel que. Pour ne facturer qu'une seule
     ligne (ex: T1), mettre `0` pour les autres lignes.
4. Cliquer **Créer le brouillon**

→ Une facture brouillon (`account.move`) est créée pour la ligne sélectionnée
avec le bon produit, le bon compte de revenu (résolu auto depuis le produit) et
la TVA (auto).

5. Vérifier la facture, puis cliquer **Confirmer** pour la valider.

> Astuce : depuis la fiche du contrat, le smart-button **Factures** affiche
> toutes les factures liées (via les commandes client + cas directs).

---

## 5. Cas spéciaux

### 5.1 Renouveler un contrat

Quand un contrat arrive à échéance, on crée le contrat de renouvellement :

1. Sur la fiche du contrat existant (Actif ou Expirant), cliquer **Renouveler**
2. Le wizard se pré-remplit :

   - **Nouvelles dates** : début = ancienne date_end + 1 jour ;
     fin = nouvelle date_start + durée
   - **Nouvelle durée** : copiée de l'ancien
   - **Appliquer la révision Syntec** : pré-coché si l'ancien contrat avait
     `Syntec = Oui`
   - **Taux Syntec** : 3 % par défaut, modifiable
   - **Nouveau montant** : calculé automatiquement (ancien × 1.03 si Syntec)
   - **Générer les lignes annuelles** : coché par défaut

3. Vérifier et cliquer **Créer le nouveau contrat**.

→ Un nouveau contrat (`MAINT/AAAA/NNNN+1`) est créé en **Actif**, avec toutes
les valeurs pré-remplies. L'ancien contrat passe en **Renouvelé**. Les deux
sont liés via les smart-buttons **Renouvelé depuis** et **Renouvelé vers** sur
chaque fiche.

### 5.2 Contrat sans BC (très rare, établissements privés)

Certains clients privés ne fonctionnent pas avec des BC. Dans ce cas :

1. Sur la fiche du contrat, dans l'onglet **Facturation**,
   **décocher la case "Nécessite une commande client"**
2. Le bouton **Créer une commande client** disparaît du bandeau, remplacé par
   **Créer les factures du contrat**
3. Cliquer ce bouton → génère directement toutes les factures brouillon
   couvrant la durée restante du contrat (selon la cadence)

### 5.3 Période intégrale (cas rare : paiement d'avance global)

Pour facturer l'intégralité du contrat en une seule facture :

1. Sur le contrat, sélectionner la cadence **Période intégrale** dans
   l'onglet Facturation (à la place de Annuelle/Semestrielle/Trimestrielle)
2. Ouvrir le wizard **Créer une commande client**
3. Choisir le périmètre **Intégralité du contrat**
4. → Le SO créé n'aura **qu'une seule ligne** pour le total du contrat
   (ex: 248 818 € HT pour 5 ans à 49 763 €/an)

### 5.4 Forcer la mise à jour de l'état (sans attendre le cron)

Le statut d'un contrat (Actif → Expire bientôt → Expiré) est recalculé
automatiquement chaque nuit par un cron. Si tu veux forcer le recalcul
immédiatement (par exemple après avoir modifié `date_end`) :

→ Bouton **Recalculer l'état** dans le bandeau du contrat.

Pratique aussi en environnement de test où les crons peuvent être désactivés.

---

## 6. Pour les équipes support : voir le statut d'un client

Quand le support ouvre la fiche d'un partenaire (depuis Contacts ou depuis un
ticket Helpdesk), un **bandeau coloré** apparaît en haut de la fiche si le
client est un établissement de maintenance :

| Couleur | Sens | Action support |
|---|---|---|
| **🟢 Vert — Maintenance ACTIVE** | Au moins 1 contrat en cours | Support normal, le client est sous contrat |
| **🟡 Jaune — Maintenance EXPIRE BIENTÔT** | Aucun actif, mais ≥1 expire dans les 90j | Vérifier que le renouvellement est en cours côté commercial |
| **🔴 Rouge — Maintenance EXPIRÉE** | Tous les contrats sont expirés | Alerter le commercial, support peut être limité |
| **⚪ Gris — Aucun contrat** | Pas d'historique de contrat | Voir avec le commercial avant tout support |

Le bandeau est aussi visible dans la **vue liste des Contacts** (colonne
"Statut maintenance" disponible via le bouton "Options" en haut à droite).

**Smart-button Contrats** : sur la fiche partner, l'icône "Contrats" amène
directement à la liste des contrats de ce client.

---

## 7. Suivi et tableaux de bord

### 7.1 Liste des contrats

**Maintenance → Contrats** ouvre la liste filtrée sur les contrats actifs par
défaut. Pour voir tout (renouvelés, expirés, annulés), retirer le filtre
"Actifs".

Vues disponibles (boutons en haut à droite) :
- **Liste** : tableur, triable, exportable
- **Kanban** : cartes regroupées par statut commande
- **Pivot** : analyse croisée (établissements × génération × montants)
- **Graph** : histogramme par marché
- **Calendrier** : timeline des contrats par date début/fin

### 7.2 Tableau de bord

**Maintenance → Tableau de bord** ouvre directement le pivot + graph configurés :
- Lignes = établissements
- Colonnes = génération (GEN1, GEN2)
- Mesures = montant maintenance + valeur totale contrat

### 7.3 Suivi des lignes annuelles

**Maintenance → Lignes annuelles** liste toutes les lignes annuelles avec leur
statut de facturation. Utile pour :
- Voir quelle année reste à facturer
- Filtrer "Année courante" pour voir le CA en cours
- Filtrer "Non facturées" pour identifier les rattrapages

### 7.4 Alertes d'expiration

Un cron quotidien :
- Bascule les contrats en **Expire bientôt** quand `date_end` est dans 0-90 jours
- Bascule en **Expiré** quand `date_end` est passée
- Envoie un email au **commercial** pour "Expire bientôt"
- Envoie un email au **commercial + tous les managers** pour "Expiré"

Pour déclencher le cron manuellement (test) : Manager → Settings → Technical →
Scheduled Actions → "Eurekam Maintenance : vérification contrats expirants" →
Run Manually.

---

## 8. Configuration (réservé aux Manageurs)

**Maintenance → Configuration** donne accès aux 4 tables de configuration :

### 8.1 Statuts module
Beta-test, Activé/non valorisé, Activé/valorisé, Non précisé, Statistique,
Essais cliniques. Modifiable selon les besoins.

### 8.2 Équipements spéciaux
Robot, Spectro. Ajoutable selon les nouveaux équipements client.

### 8.3 Cadences de facturation
Annuelle, À échu, À échoir, Période intégrale, Semestrielle, Trimestrielle.
**Ne pas modifier les codes** (`annual`, `quarterly`, etc.) — utilisés par le
code pour résoudre les cadences. Le libellé est modifiable.

### 8.4 Facturation modules
Gratuit (valorisé), Module Statistique, Module Essai Clinique, Aucun module.

> **Types d'établissement et Versions produit** se gèrent dans les **Étiquettes
> Contact** standard d'Odoo (`res.partner.category`) et non dans la
> configuration Maintenance. Pour les ajouter : Contacts → Configuration →
> Étiquettes contact.

---

## 9. FAQ et dépannage

### Le menu Maintenance n'apparaît pas
→ Demande à un Manager de t'attribuer le groupe "Maintenance Eurekam /
Utilisateur" via Configuration → Utilisateurs → ton compte → onglet "Droits
d'accès".

### J'ai créé un contrat mais je ne peux pas l'activer
→ Vérifier que les **dates de début et fin** sont remplies + que le **produit**
est renseigné (champ "Produit", pas juste "Libellé produit").

### Le bouton "Créer les factures du contrat" n'apparaît pas
→ Le contrat a `Nécessite une commande client` coché (cas par défaut). Utilise
**"Créer une commande client"** à la place. Si tu veux vraiment facturer sans
BC, décoche la case dans l'onglet Facturation.

### Le bouton "Créer une commande client" est grisé
→ Vérifier que le contrat est dans l'état **Actif** ou **Expire bientôt** (pas
Brouillon, Renouvelé, Annulé).

### La commande créée a 4 lignes mais je voudrais en facturer une seule
→ C'est exactement le but. Sur la commande confirmée, clique "Créer une facture"
→ dans le popup, mets `0` dans la colonne "Quantité à facturer" pour les
3 lignes que tu ne veux pas facturer maintenant. Reviens facturer plus tard
quand le client paie le trimestre suivant.

### Un contrat est marqué "Actif" mais sa date de fin est passée
→ Le cron quotidien n'a pas encore tourné. Clique **Recalculer l'état** dans le
bandeau du contrat pour forcer la bascule immédiate. Sur la prod, ça se règle
automatiquement en 24h.

### "Une seule cadence de période est autorisée" lors de la sauvegarde
→ Tu as sélectionné plusieurs cadences de période (ex: Annuelle + Trimestrielle).
Garde-en une seule (la plus fine si plusieurs s'appliquent : Trimestrielle >
Semestrielle > Annuelle > Période intégrale).

### Le wizard renouvellement propose une date de début bizarre
→ Le wizard part de `date_end + 1 jour` du contrat précédent. Si l'ancien
contrat n'a pas de `date_end`, modifie manuellement dans le wizard.

### Je veux supprimer un contrat de test
→ Seul un **Manager** peut supprimer. Les utilisateurs standards ne peuvent
qu'annuler (état Annulé). Demande à un manager si tu veux purger.

### Le client a envoyé un avenant qui change le montant 2027
→ Va dans l'onglet **Montants annuels** du contrat → modifie la ligne 2027 →
Save. Le `Total contrat` se met à jour automatiquement. Si une commande client
2027 avait déjà été créée, supprime-la et recrée une nouvelle avec le bon
montant via le wizard.

---

## 10. Glossaire des champs

### Sur un contrat (`eurekam.maintenance.contract`)

| Champ visible | Nom technique | Description |
|---|---|---|
| Référence | `name` | Construit auto : "MAINT/AAAA/NNNN - Établissement - Produit" |
| Numéro | `sequence_number` | "MAINT/AAAA/NNNN" |
| Établissement | `partner_id` | Lien vers le contact client |
| Produit | `product_id` | Lien vers la base articles |
| Libellé produit | `product_name` | Texte libre, optionnel |
| Commercial | `commercial_id` | Utilisateur Odoo en charge |
| Génération | `gen` | GEN1, GEN2, Upgrade GEN2 |
| Marché | `market_type` | UniHA 2019/21/23/24/25, AGEPS, Privé, etc. |
| Statut commande | `order_status` | Reçue, En attente, Pas de BC, En déploiement, Suspendue |
| Début / Fin | `date_start` / `date_end` | Dates du contrat |
| Durée commandée | `duration` | 6m, 1y, 2y, 3y, 4y, 5y |
| Jours avant expiration | `days_to_expiry` | Calculé en temps réel |
| Montant de maintenance | `maintenance_amount` | €/an de référence |
| Niveau de facturation | `billing_level` | 0/25/50/75/100 % |
| Révision Syntec | `syntec_revision` | Oui / Non |
| Cadences de facturation | `billing_frequency_ids` | Many2many vers les cadences |
| Nécessite une commande client | `requires_customer_order` | True = workflow BC, False = facture directe |
| État | `state` | Brouillon / Actif / Expire bientôt / Expiré / Renouvelé / Annulé |

### Sur une commande client (`sale.order`)

| Champ visible | Nom technique | Description |
|---|---|---|
| Référence | `name` | Numéro auto Odoo Sales |
| Référence BC client | `client_order_ref` | N° BC saisi à la création |
| Contrat maintenance | `eurekam_maintenance_contract_id` | Lien vers le contrat (champ ajouté par notre module) |
| Année couverte | `eurekam_maintenance_year` | Année du contrat couverte (0 = intégralité) |
| Origine | `origin` | Numéro de séquence du contrat |

### Sur une ligne de commande (`sale.order.line`)

| Champ | Nom technique | Description |
|---|---|---|
| Période maintenance | `maintenance_period_label` | "T1 2026", "S2 2026", "Année 2026", "Période intégrale" |
| Ligne annuelle | `maintenance_line_id` | Lien vers la ligne annuelle du contrat |

---

## Contact / signalement de bug

Pour toute question ou bug rencontré pendant le test, contacter
**loic.tamarelle@eurekam.fr** en précisant :

- L'URL exacte de l'écran qui pose problème (visible dans le navigateur)
- La séquence des actions effectuées
- Le message d'erreur exact (si applicable)
- Une copie d'écran si possible

---

*Dernière mise à jour : 2026-05-29 — pour la version 18.0.1.0.0 du module `eurekam_maintenance`.*
