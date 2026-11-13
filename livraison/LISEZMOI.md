# Relecture avant intégration des contrats de maintenance

Trois fichiers à relire avant que les contrats Notion ne soient créés dans Odoo.
Aucun d'eux n'a été appliqué : à ce stade **rien n'a été écrit en production**.

| Fichier | Contenu |
|---|---|
| `contrats_a_importer.csv` | 119 contrats qui **seront créés** — une ligne par contrat |
| `contrats_ecartes.csv` | 28 contrats qui **ne seront pas créés**, avec le motif |
| `points_a_valider.csv` | 137 anomalies qui demandent une décision de votre part |

Ces fichiers sont produits par `migration/preparer_fichier_import.py`, qui
rejoue exactement la logique de `migration/importer_contrats.py`. Ce que vous
lisez est donc ce que l'import fera, pas une approximation.

---

## ⚠️ À lire avant tout : l'extrait Notion n'est pas à jour

Ces fichiers sont bâtis sur l'export Notion du **2 octobre 2026**. Or Notion a
bougé depuis :

| | Export du 2 oct. | Notion aujourd'hui |
|---|---|---|
| lignes | 147 | **149** |
| somme des montants annuels | 6 665 366,02 € | **7 252 630,09 €** |
| contrats avec date de début | 126 | **131** |
| contrats avec date de fin | 123 | **128** |
| révision Syntec « oui » | 61 | **62** |
| total postes | 409 | **411** |

**+587 264,07 € d'écart.** Il ne s'agit pas seulement des 2 lignes créées
depuis : des contrats existants ont été modifiés.

**Ces fichiers servent donc à relire la structure, les règles et les points de
décision — pas à valider les montants.** Pour obtenir les chiffres définitifs,
il faut réexporter « Assistance DO » depuis Notion (Notion → `...` → Export →
CSV, sans sous-pages), remplacer le fichier dans `migration/`, et relancer le
générateur. Les trois fichiers sont alors régénérés avec les valeurs du jour.

---

## Ce qu'il faut vérifier, par ordre d'importance

### 1. Les 62 contrats sans produit (`points_a_valider.csv`)

Notion ne contient **aucune référence article**. Ces 62 contrats seront créés en
**brouillon** et ne pourront pas être activés tant qu'un produit ne leur est pas
affecté. Rien n'est inventé à leur place.

C'est le principal chantier à prévoir après l'intégration.

### 2. Les 15 correspondances d'établissement à confirmer

La colonne `qualite_correspondance` indique la fiabilité du rapprochement
Notion → Odoo. Tout ce qui n'est pas `CERTAIN` est à vérifier.

Cas connus et préoccupants :

- Trois établissements lyonnais distincts dans Notion — **Édouard Herriot**,
  **Mère-Enfant** et **Lyon Sud** — pointent vers le **même** partenaire Odoo
  (1845). Seul Lyon Sud est certain ; les deux autres sont marqués
  « À VALIDER » et leurs contrats partiront donc sur le mauvais établissement
  s'ils sont validés tels quels.
- **Croix Rousse** pointe vers « Hôpital privé Jean Mermoz », ce qui est
  manifestement faux.

### 3. Les 42 montants hors période

Des contrats portent des montants sur des années situées **avant leur date de
début ou après leur date de fin**. Exemple : un contrat qui démarre le
16/07/2025 et porte un montant 2024.

Ces montants seront **importés tels quels**, volontairement : les perdre
silencieusement serait pire. Mais il faut décider si c'est une saisie Notion à
corriger ou une réalité de facturation.

### 4. Les 9 établissements portant plusieurs contrats

Sept établissements en ont 2, deux en ont 3. À confirmer qu'il s'agit bien de
contrats distincts et non de doublons Notion.

### 5. Les 8 contrats sans date

`date_debut` ou `date_fin` vide. Ils seront créés, mais ne basculeront pas
automatiquement en « expire bientôt » / « expiré ».

---

## Les 28 contrats écartés

| Motif | Nombre | Montant non repris |
|---|---|---|
| aucun montant annuel dans Notion | 11 | — |
| hors France (Belgique) | 10 | |
| hors France (Espagne) | 3 | |
| hors France (Allemagne) | 2 | |
| hors France (Italie) | 1 | |
| aucun établissement renseigné | 1 | |

Total non repris : **211 779,00 €**, essentiellement le lot étranger.

Le périmètre France a été arrêté d'un commun accord : les 16 contrats étrangers
feront un second lot, une fois leur table de correspondance établissements
construite. Les 11 contrats sans aucun montant annuel sont des coquilles vides
dans Notion.

---

## Comment lire `contrats_a_importer.csv`

Les colonnes reprennent les valeurs **telles qu'elles seront écrites dans
Odoo**, pas les libellés Notion :

- `generation` : `gen1`, `gen2`, `upgrade_gen2`
- `statut_commande` : `received`, `pending`, `no_po`, `deploying`, `suspended`
- `cadence` : codes séparés par `+`, ex. `quarterly+overdue`
- `duree_commandee` : la durée **commandée** au sens Notion, qui n'est pas la
  durée réelle du contrat. Beaucoup de contrats courant sur 5 ans sont marqués
  `1y`. C'est fidèle à Notion et volontairement conservé.
- `2023` … `2030` : les montants annuels, qui deviennent les lignes annuelles
- `montant_reference` : le montant de maintenance de référence, qui n'est **pas**
  ce qui sera facturé — il sert à pré-remplir les années vides

---

## Après validation

Une fois les trois fichiers relus et les décisions prises :

1. réexporter Notion et régénérer les fichiers (voir l'avertissement ci-dessus) ;
2. corriger dans Notion ce qui doit l'être, plutôt que dans le CSV — ainsi la
   source reste la référence ;
3. l'intégration elle-même reste **à votre main**. Elle n'a été jouée que sur
   les bases de test (sandbox et recette).
