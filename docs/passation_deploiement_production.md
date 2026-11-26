# Passation — déploiement de `eurekam_maintenance` en production

**Destinataire : prestataire Odoo (Scalizer).**
Version cible : **18.0.2.5.2**. Mis à jour le 2026-11-26.
Toutes les mesures ci-dessous ont été relevées sur les instances ce jour-là.

---

## 1. Où en est-on

| Branche de `ScalizerOrg/eurekam` | Instance | Pointeur du sous-module | Version |
|---|---|---|---|
| `main` | **production** `eurekam.odoo.com` | `a007d99` | 18.0.2.0.0 (12/11) |
| `Staging` | recette `eurekam-recette.odoo.com` | `a007d99` | 18.0.2.0.0 |
| `sandbox` | sandbox `eurekam-sandbox.odoo.com` | `58a1533` | **18.0.2.5.2** ✅ |

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
| `1f9720f` | Les trois défauts remontés par votre relecture (§3.9) |
| `58a1533` | Le test de rattachement corrigé, les champs invisibles justifiés (§3.10) |

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

### 3.8 Un troisième niveau de droits, et sa migration obligatoire

La catégorie « Eurekam Maintenance » passe à trois niveaux : **Lecture seule**,
Utilisateur, Gestionnaire. Le premier consulte contrats, lignes annuelles,
établissements et tableau de bord sans rien pouvoir modifier ; les huit boutons
d'action de l'en-tête du contrat lui sont masqués, les assistants n'ont aucune
ligne de droits pour lui, et la Configuration reste réservée aux gestionnaires.

**`migrations/18.0.2.5.0/post-migrate.py` n'est pas optionnelle.** Le groupe
Utilisateur a été créé dans un bloc `<data noupdate="1">` : une mise à jour du
module saute ces enregistrements, donc l'implication « Utilisateur implique
Lecture seule » ne peut pas être déclarée en XML — elle ne produirait ni erreur
ni effet. Sans elle, deux conséquences : les utilisateurs standard perdent le
menu Maintenance (ouvert au niveau lecture seule), et le sélecteur de droits
affiche trois cases indépendantes au lieu d'une échelle, Odoo construisant
celle-ci à partir du graphe d'implication.

Pour la même raison, les deux règles d'isolation par société du niveau lecture
seule sont des règles **neuves**, hors bloc `noupdate`, et non une modification
des deux existantes.

Le script du §4 contrôle les neuf points, l'implication comprise.

### 3.9 Trois correctifs issus de votre relecture (18.0.2.5.1)

Merci — les trois étaient réels et reproduits avant correction.

**`groups=` dans une arborescence de vue exige l'xmlid complet.** Les huit
boutons du contrat portaient `groups="group_maintenance_user"` : Odoo ne résout
pas ce nom par rapport au module courant, n'émet rien de visible, et masque
l'élément **pour tout le monde**, gestionnaires compris. Vérifié sur l'instance :
compte Gestionnaire, zéro bouton rendu sur huit. Tous les `groups=` du module
sont désormais qualifiés, y compris les `menuitem`, où le chargeur XML qualifie
pourtant tout seul — une règle sans exception se retient mieux.

**Les compteurs de devis et de factures passent en `sudo()`.** Un lecteur sans
droits Ventes ne pouvait pas ouvrir un contrat. En complément de votre
prescription : `sudo()` suffit pour un compteur, qui est un entier rendu par le
serveur, mais **pas** pour les colonnes `order_ids` et `invoice_ids` en
`many2many_tags` — le client va lire lui-même le nom des commandes et des
factures et se fait refuser. Ces cinq colonnes sont réservées à
`sales_team.group_sale_salesman`, le plus petit groupe donnant la lecture sur
`sale.order`, `sale.order.line` et `account.move` sur cette instance.

**Le mode « un devis par période » stampille l'année.** La valeur réutilise
`year_key`, déjà calculé pour le garde-fou d'unicité, au lieu d'une seconde
expression qui pouvait en diverger — c'était exactement la cause. La migration
`18.0.2.5.1` réannote les devis déjà émis avec 0, en déduisant l'année de la
ligne annuelle que chaque ligne de commande désigne, et laisse de côté ceux dont
les lignes ne s'accordent pas.

### 3.10 Le build du 26/11 : un seul échec sur cinq est à nous

Merci pour ce build — il nous a appris quelque chose que nos propres builds ne
pouvaient pas nous dire.

**Nos tests n'avaient jamais tourné.** La sandbox est une branche de type
*staging* : Odoo.sh y met les modules à jour sans lancer la suite. Votre build
sur une branche de dev est la **première exécution** des 26 tests ajoutés
depuis la version 18.0.2.0.0 qui tourne en production.

`TestMaintenanceContract.test_attach_refuses_lines_without_a_year` : le test
avait tort, pas le code. Il supposait qu'une ligne de commande sans année dans
son libellé n'est pas cochée par l'assistant de rattachement. Or
`_deduire_annee` a un troisième signal, délibéré : la date de la commande —
c'est lui qui place les 648 devis historiques dont le libellé ne dit rien. Le
devis fabriqué par le test étant daté du jour, il tombait dans le contrat et la
ligne était bien cochée. Comportement reproduit sur la sandbox avant
correction. Le test date désormais le devis hors du contrat, et un second test
couvre le signal lui-même, qui n'en avait aucun.

**Les quatre autres échecs ne peuvent pas venir de nous** : `mail` (2 tours),
`account_accountant` (bank rec, paiement). Le module n'hérite que de
`res.partner`, `sale.order` et `sale.order.line`, et ne touche ni
`account.payment`, ni le rapprochement bancaire, ni Discuss. Ces échecs
s'accompagnent de `RuntimeError: can't start new thread` et de `Failed to
fetch` répétés : le conteneur était à bout de ressources.

**À savoir pour lire le rapport** : le runner s'arrête à 5 échecs. Nos tests
passent par ordre alphabétique et celui qui tombait est le **5ᵉ sur 56** — les
51 suivants ont été *skipped*, pas réussis. Un nouveau build de dev reste donc
nécessaire pour valider l'ensemble ; nous n'avons aucun moyen de le faire de
notre côté.

**Les champs toujours invisibles** signalés en tête de log : c'est le test
`TestInvisibleField.test_uncommented_invisible_field` d'Odoo 18 lui-même
(`odoo/addons/base/tests/test_views.py`). Il n'échoue pas, il écrit des lignes
`ERROR`. Sa règle exacte : un champ toujours invisible d'une vue *list* ou
*form* doit être suivi **immédiatement** d'un commentaire XML disant pourquoi
il est là — un commentaire placé *avant* la balise ne compte pas, et sa regex
attrape aussi `column_invisible="1"`. Les quatre champs sont légitimes (deux
`currency_id` qui portent des widgets Monetary, `syntec_revision` et
`maintenance_status` lus par des expressions `invisible=`) : ils sont
désormais justifiés sur place, et le script du §4 rejoue la regex d'Odoo sur
l'arche stockée de l'instance, pour que ce contrôle ne dépende plus d'un build
de dev.

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
