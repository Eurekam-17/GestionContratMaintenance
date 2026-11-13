# Relecture avant intégration des contrats de maintenance

**Version 2** — intègre les corrections de la relecture du 13 novembre.

Aucun de ces fichiers n'a été appliqué : **rien n'a été écrit en production.**

| Fichier | Contenu |
|---|---|
| `contrats_a_importer.csv` | 121 contrats qui **seront créés** — 6 591 087,02 € |
| `contrats_ecartes.csv` | 26 contrats **non repris**, avec le motif et votre annotation |
| `points_a_valider.csv` | 128 points demandant encore une décision |
| `decisions_equipe.csv` | **Vos arbitrages.** C'est le seul fichier à modifier. |

---

## Ce qui a changé depuis la version 1

### Vos annotations sont désormais prises en compte par l'import

Elles ont été reprises dans `decisions_equipe.csv`, qui est lu **à la fois** par
le générateur de ces fichiers et par le script d'import. Vos arbitrages ne sont
donc plus perdus à chaque régénération, et ce que vous lisez reste exactement ce
que l'import fera.

Colonne `decision`, trois valeurs possibles :

| valeur | effet |
|---|---|
| *(vide)* | le contrat est importé normalement |
| `inactif` | importé puis passé en **annulé** : gardé pour l'historique, mais ne compte ni comme actif ni comme expirant, et ne déclenche aucune alerte |
| `ignorer` | pas créé du tout |

La colonne `statut_equipe` est recopiée dans le commentaire du contrat Odoo,
préfixée `[Relecture équipe]`.

### Jean Perrin → inactif

Le contrat du CRLCC Jean Perrin (Clermont-Ferrand, 2020-2025, 14 769,72 €) est
marqué `inactif`, avec la mention du transfert de l'équipement vers le CH de
Vichy.

À noter : **le CH de Vichy existe bien dans Odoo** (Jacques Lacarin) mais
**n'a aucune ligne de contrat dans Notion**. Il n'y a donc rien à y créer pour
l'instant. Si un contrat doit y être ouvert, il faudra le saisir.

### Deux contrats à paiement unique récupérés

Ma règle « aucun montant annuel → écarté » était fausse. Vos annotations l'ont
révélé : un contrat en cadence **Période intégrale** n'a par construction aucun
montant annuel, tout est porté par le montant de référence.

| | montant | votre annotation |
|---|---|---|
| CLCC Henri Becquerel (Rouen) | 73 660 € | contrat paiement intégral. En cours de renouvellement. |
| Institut Sainte-Catherine (Avignon) | 63 840 € | paiement intégral jusqu'au 2028 |

Ils sont maintenant importés, avec une ligne unique posée sur leur année de
début. C'est ce qui explique le passage de 119 à 121 contrats et de 6 453 587 €
à 6 591 087 €.

### Les contrats multiples par établissement ne sont plus signalés

Vous avez confirmé que c'est normal — réassorts, ou postes placés sur des
marchés différents — et que Notion garde volontairement une ligne par réassort
pour en suivre la date de garantie. Le contrôle produisait 9 faux positifs, il a
été retiré. **Une ligne Notion reste un contrat Odoo** : aucun regroupement
automatique n'est fait, y compris pour Curie.

### `contrats_a_importer complété.csv` : rien à en tirer

Ce fichier ne contient aucune correction de fond. Les 117 lignes qui diffèrent
sont uniquement des dates reformatées par Excel à l'ouverture
(`2024-05-01` → `01/05/2024`). Si vous voulez annoter des contrats *à importer*,
passez par `decisions_equipe.csv` : Excel y touchera moins, et surtout l'import
le lira.

---

## ⚠️ L'extrait Notion n'est toujours pas à jour

Ces fichiers restent bâtis sur l'export Notion du **2 octobre 2026**, qui a
divergé :

| | Export du 2 oct. | Notion aujourd'hui |
|---|---|---|
| lignes | 147 | **149** |
| somme des montants annuels | 6 665 366,02 € | **7 252 630,09 €** |
| contrats avec date de début | 126 | **131** |
| révision Syntec « oui » | 61 | **62** |

Un exemple concret du risque : **Rouen Becquerel porte aujourd'hui 18 240 € sur
2027 dans Notion**, montant absent de l'extrait d'octobre. Avec des données
fraîches, ce contrat cesserait d'être traité comme un paiement unique et
n'arriverait qu'avec ses 18 240 €, au lieu de ses 73 660 €. **C'est précisément
le genre d'arbitrage qu'il faut faire sur des données à jour.**

Pour régénérer : exporter « Assistance DO » depuis Notion (`···` → Export →
CSV, sans sous-pages), remplacer le fichier dans `migration/`, puis relancer

```bash
python migration/preparer_fichier_import.py --url https://eurekam-recette.odoo.com
```

---

## Ce qui reste à décider

### 1. Les 62 contrats sans produit

Notion ne porte aucune référence article. Ces contrats seront créés en
**brouillon** et ne pourront pas être activés tant qu'un produit ne leur est pas
affecté. C'est le principal chantier d'après-intégration : plus de la moitié du
lot.

### 2. Les 15 correspondances d'établissement à confirmer

Tout ce qui n'est pas `CERTAIN` dans la colonne `qualite_correspondance`.
Deux cas manifestement faux :

- **Édouard Herriot**, **Mère-Enfant** et **Lyon Sud** pointent tous vers le
  même partenaire Odoo (1845). Seul Lyon Sud est certain.
- **Croix Rousse** pointe vers « Hôpital privé Jean Mermoz ».

### 3. Les 42 montants hors période

Montants portés sur des années situées avant le début ou après la fin du
contrat. Ils sont importés tels quels — les perdre silencieusement serait pire —
mais il faut trancher : saisie Notion à corriger, ou réalité de facturation ?

### 4. Les 8 contrats sans date

Ils seront créés, mais ne basculeront jamais en « expire bientôt » ni
« expiré », faute de date de fin.

---

## Les 26 contrats écartés — 211 779 € non repris

| Motif | Nombre |
|---|---|
| hors France (Belgique) | 10 |
| aucun montant annuel dans Notion | 9 |
| hors France (Espagne) | 3 |
| hors France (Allemagne) | 2 |
| hors France (Italie) | 1 |
| aucun établissement renseigné | 1 |

Vos annotations confirment que les 9 « aucun montant annuel » restants sont des
déploiements en cours ou des équipements non installés — donc sans contrat à ce
jour. Le lot étranger (16 contrats) fera un second passage, une fois sa table de
correspondance établissements construite.

Une seule ligne écartée n'a pas d'annotation : la **ligne 133**, qui n'a aucun
établissement renseigné dans Notion. C'est probablement une ligne vide à
supprimer côté Notion.

---

## Après validation

1. réexporter Notion et régénérer (voir l'avertissement ci-dessus) ;
2. compléter `decisions_equipe.csv` pour les contrats à passer en `inactif` ou
   à `ignorer` ;
3. corriger dans **Notion** ce qui relève de la donnée, pas dans les CSV — ainsi
   la source reste la référence ;
4. l'intégration reste **à votre main**. Elle n'a été jouée que sur les bases de
   test (sandbox et recette).
