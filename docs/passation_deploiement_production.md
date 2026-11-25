# Passation — déploiement de `eurekam_maintenance` en production

**Destinataire : prestataire Odoo (Scalizer).**
Version cible : **18.0.2.4.1**. Mis à jour le 2026-11-25.
Toutes les mesures ci-dessous ont été relevées sur les instances ce jour-là.

---

## 1. Où en est-on

| Branche de `ScalizerOrg/eurekam` | Instance | Pointeur du sous-module | Version |
|---|---|---|---|
| `main` | **production** `eurekam.odoo.com` | `a007d99` | 18.0.2.0.0 (12/11) |
| `Staging` | recette `eurekam-recette.odoo.com` | `a007d99` | 18.0.2.0.0 |
| `sandbox` | sandbox `eurekam-sandbox.odoo.com` | `aece7d6` | **18.0.2.4.1** ✅ |

La sandbox porte la version cible, vérifiée fonctionnellement le 25/11.
La production et la recette ont sept versions de retard.

## 2. Ce qu'il y a à faire

Faire pointer le sous-module `Eurekam-17/GestionContratMaintenance` sur la tête
de `main` du dépôt module dans `ScalizerOrg/eurekam`, d'abord sur `Staging`,
puis sur `main` après recette.

```
Eurekam-17/GestionContratMaintenance : a007d99 → (tête de main)
```

Seul `module/eurekam_maintenance/` est chargé par Odoo. Les répertoires
`migration/`, `livraison/`, `docs/` et `scripts/` que ces commits apportent ne
contiennent pas de manifeste et sont ignorés par le serveur.

### Les commits portés

| Commit | Effet visible |
|---|---|
| `28d31d4` | Statut « À commander » sur les lignes annuelles : champ, filtres, pastille |
| `2db0c4e` | Les contrats expirés sortent de la liste « à commander » |
| `ee3184b` | **Migration** de recalcul des lignes existantes |
| `386eaca` | Vue orpheline supprimée, année non sommée en mode groupé |
| `5c3dde7` | Cron hebdomadaire des années sans devis (**livré désactivé**) |
| `9f00006` | Assistant « Rattacher une commande » |
| `aece7d6` | Suivi des périodes : un document à la fois, chacun à sa date |

## 3. Points d'attention

### 3.1 La migration `18.0.2.1.2` est obligatoire

`module/eurekam_maintenance/migrations/18.0.2.1.2/post-migrate.py` s'exécute
automatiquement à la mise à jour. Elle **recalcule** `order_state` et
`order_count` sur toutes les lignes annuelles.

Elle n'est pas optionnelle : `order_state` est un champ calculé **stocké**, et
Odoo ne le remplit qu'à l'ajout du champ, pas quand sa logique change. Sans
elle, les contrats expirés resteraient affichés « à commander » — ce qui s'est
effectivement produit sur la sandbox le 24/11, avec tous les indicateurs
techniques au vert.

### 3.2 Une vue est supprimée

`view_maintenance_contract_line_inline_list` disparaît. Elle n'était référencée
nulle part — le formulaire du contrat intègre sa propre liste — mais à priorité
égale Odoo départage sur `(priority, name, id)`, et `…inline.list` passait avant
`…list`. L'orpheline gagnait, et le menu « Lignes annuelles » affichait depuis
des mois une vue amputée, sans contrat ni établissement.

Odoo supprimera l'enregistrement à la mise à jour, son `xmlid` appartenant au
module. **La production porte encore les deux vues** : le script du §4 le
signale.

### 3.3 Une vue `sale.order` est désormais héritée

`views/sale_order_views.xml` hérite de `sale.view_order_form` et de
`sale.sale_order_view_search_inherit_sale`. Les ancrages ont été vérifiés sur
l'instance avant livraison, et l'ajout de colonnes se fait `position="inside"`
sur l'élément `<list>` plutôt qu'avant un champ nommé, la vue commande étant
fortement personnalisée chez Eurekam.

C'est le point le plus susceptible de frotter avec vos propres héritages. Si le
build échoue, regarder là en premier.

### 3.4 Deux crons, deux régimes

| Cron | Cadence | Livré |
|---|---|---|
| `cron_check_years_to_order` | hebdomadaire | **désactivé** |
| `cron_check_periods_due` | quotidien | **actif** |

Le premier ne doit **pas** être activé au déploiement : il lève une activité sur
chaque année de contrat sans devis rattaché, et tant que les devis historiques
ne sont pas repris il alerterait à tort sur presque tous les contrats vivants.

Le second peut rester actif sans risque : il ne regarde que les lignes portant
des bornes de période, c'est-à-dire les devis que le module émet lui-même. Les
commandes historiques n'en ont pas, donc le premier passage ne trouve rien.

### 3.5 Quatre lignes d'ACL

Ajoutées pour les deux modèles transitoires de l'assistant de rattachement.
Sans elles, l'assistant est inutilisable pour tout utilisateur non
administrateur.

### 3.6 Un build échoué laisse tourner l'ancien code

Déjà rencontré en octobre avec les champs fantômes des modules `s6r_*`.

À noter aussi : c'est l'**attente avant le build** qui s'étire, pas le build.
Sur la sandbox le 25/11, un bump a mis environ 45 minutes à être pris en compte,
puis a été construit en 31 secondes. Ne pas conclure trop vite à un blocage ; et
ne jamais relancer par « Rebuild », qui réinitialiserait la base.

### 3.7 L'adresse courte d'une branche peut cesser de résoudre

`eurekam-sandbox.odoo.com` et `eurekam-recette.odoo.com` ne sont pas des alias
automatiques : ce sont des **domaines personnalisés** déclarés dans les
paramètres de la branche, et leur enregistrement DNS doit viser le serveur du
build en cours (`<projet>-<branche>-<build>.dev.odoo.com`).

Le 25/11, celui de la sandbox a cessé de résoudre : Odoo.sh l'affichait
*« Unknown server »*, le nom pointait sur l'IP générique d'odoo.com au lieu de
celle de la plateforme, et toute requête finissait sur une page projet
inexistante. **L'instance, elle, tournait normalement** sur l'adresse longue.

Si cela arrive en recette ou en production : ouvrir la branche sur Odoo.sh,
Settings → Custom domains, cliquer l'icône d'information du domaine. Elle
indique l'état de résolution et l'adresse exacte à viser. En attendant, tout
reste joignable sur l'adresse du bouton **CONNECT**.

## 4. Vérification après déploiement

```
python scripts/verifier_deploiement.py --url https://eurekam-recette.odoo.com
```

puis, après bascule en production :

```
python scripts/verifier_deploiement.py --production OUI-JE-VALIDE-LA-PRODUCTION --url https://eurekam.odoo.com
```

Lecture seule, garde-fou avant tout contact réseau, code de sortie 0 si
conforme. Il contrôle deux choses distinctes :

- **la présence du code** : version, champs, modèles, vues, filtres, droits,
  crons et leur état, types d'activité (recherchés par `xmlid`, pas par modèle) ;
- **le comportement attendu** : aucune ligne « à commander » sur un contrat
  fermé, année non totalisée par groupe, statut qui répond réellement à une
  lecture groupée.

Le second bloc est le seul qui ait détecté le défaut de recalcul du 24/11.
Ne pas conclure sur la seule version du module.

Sortie attendue en fin d'exécution : `==> DEPLOIEMENT CONFORME`.

## 5. Ce qui suit, et qui n'est pas de votre ressort

Une fois la version en production, Eurekam lancera la reprise des devis
historiques (`migration/rattacher_devis.py`) : 154 lignes prêtes sur 109 devis,
1 607 247 €, pour les années 2026 et au-delà. Le fichier de relecture
`livraison/rattachement_devis_a_relire.csv` est en attente de validation par
l'équipe Eurekam.

Cette reprise n'ajoute qu'un **lien** : elle ne modifie ni les montants, ni les
libellés, ni l'état des devis. Elle ne doit pas précéder le déploiement, car
sans cette version les rattachements au niveau ligne resteraient invisibles —
les compteurs du contrat lisent encore le seul lien d'en-tête.

Le cron hebdomadaire du §3.4 sera activé après cette reprise.
