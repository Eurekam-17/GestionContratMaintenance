# Passation — déploiement de `eurekam_maintenance` 18.0.2.3.0

**Destinataire : prestataire Odoo (Scalizer).**
Rédigé le 2026-11-24. Toutes les mesures ci-dessous ont été relevées sur les
instances ce jour-là.

---

## 1. Où en est-on

| Branche de `ScalizerOrg/eurekam` | Instance | Pointeur du sous-module | Version |
|---|---|---|---|
| `main` | **production** `eurekam.odoo.com` | `a007d99` | 18.0.2.0.0 (12/11) |
| `Staging` | recette `eurekam-recette.odoo.com` | `a007d99` | 18.0.2.0.0 |
| `sandbox` | sandbox `eurekam-sandbox.odoo.com` | `9f00006` | **18.0.2.3.0** ✅ |

La sandbox porte la version cible, vérifiée fonctionnellement. La production
et la recette ont six versions de retard.

## 2. Ce qu'il y a à faire

Faire pointer le sous-module `Eurekam-17/GestionContratMaintenance` sur
**`074dd47`** (tête de `main` du dépôt module) dans `ScalizerOrg/eurekam`,
d'abord sur `Staging`, puis sur `main` après recette.

```
Eurekam-17/GestionContratMaintenance : a007d99 → 074dd47
```

Seul `module/eurekam_maintenance/` est chargé par Odoo. Les répertoires
`migration/` et `livraison/` que ce commit apporte ne contiennent pas de
manifeste et sont ignorés par le serveur.

### Les six commits portés

| Commit | Effet visible |
|---|---|
| `28d31d4` | Statut « À commander » sur les lignes annuelles : champ, filtres, pastille |
| `2db0c4e` | Les contrats expirés sortent de la liste « à commander » |
| `ee3184b` | **Migration** de recalcul des lignes existantes |
| `386eaca` | Vue orpheline supprimée, année non sommée en mode groupé |
| `5c3dde7` | Cron hebdomadaire des années sans devis (**livré désactivé**) |
| `9f00006` | Assistant « Rattacher une commande » |

15 fichiers, +1183 / −21.

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

Elle journalise la répartition obtenue : c'est la trace qui distingue « la
migration a tourné » de « elle a tourné et a changé quelque chose ».

### 3.2 Une vue est supprimée

`view_maintenance_contract_line_inline_list` disparaît. Elle n'était référencée
nulle part — le formulaire du contrat intègre sa propre liste — mais à priorité
égale Odoo départage sur `(priority, name, id)`, et `…inline.list` passait avant
`…list`. L'orpheline gagnait, et le menu « Lignes annuelles » affichait depuis
des mois une vue amputée, sans contrat ni établissement.

Odoo supprimera l'enregistrement à la mise à jour, son `xmlid` appartenant au
module. **La production porte encore les deux vues** : le script de vérification
le signale.

### 3.3 Nouveaux enregistrements de données

- `mail.activity.type` « Devis annuel à émettre » (`noupdate="1"`)
- `ir.cron` des années sans devis, **`active = False` volontairement**

Le cron ne doit pas être activé lors du déploiement. Il lève une activité sur
chaque année de contrat sans devis rattaché ; tant que les devis historiques ne
sont pas rattachés, il alerterait sur presque tous les contrats vivants, à tort.
Son activation viendra après la reprise décrite au §5.

### 3.4 Quatre lignes d'ACL

Ajoutées pour les deux modèles transitoires de l'assistant. Sans elles,
l'assistant est inutilisable pour tout utilisateur non administrateur.

### 3.5 Un build échoué laisse tourner l'ancien code

Déjà rencontré en octobre avec les champs fantômes des modules `s6r_*` : le
build échouait en ~24 s et la production continuait de servir la version
précédente, pendant que git paraissait sain. D'où le §4.

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
  cron, type d'activité ;
- **le comportement attendu** : aucune ligne « à commander » sur un contrat
  fermé, année non totalisée par groupe, statut qui répond réellement à une
  lecture groupée.

Le second bloc est le seul qui ait détecté le défaut de recalcul du 24/11.
Ne pas conclure sur la seule version du module.

Sortie attendue en fin d'exécution : `==> DEPLOIEMENT CONFORME`.

## 5. Ce qui suit, et qui n'est pas de votre ressort

Une fois la 18.0.2.3.0 en production, Eurekam lancera la reprise des devis
historiques (`migration/rattacher_devis.py`) : 154 lignes prêtes sur 109 devis,
1 607 247 €, pour les années 2026 et au-delà. Le fichier de relecture
`livraison/rattachement_devis_a_relire.csv` est en attente de validation par
l'équipe Eurekam.

Cette reprise n'ajoute qu'un **lien** : elle ne modifie ni les montants, ni les
libellés, ni l'état des devis. Elle ne doit pas précéder le déploiement, car
sans la 18.0.2.3.0 les rattachements au niveau ligne resteraient invisibles —
les compteurs du contrat lisent encore le seul lien d'en-tête.

Le cron du §3.3 sera activé après cette reprise.
