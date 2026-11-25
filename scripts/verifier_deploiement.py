# -*- coding: utf-8 -*-
"""Verifie qu'une version du module est REELLEMENT en place sur une instance.

LECTURE SEULE. N'ecrit rien, ne declenche rien.

Pourquoi ce script existe : un bump de sous-module n'est pas un deploiement.
Odoo.sh peut abandonner un build, ou un build peut echouer en laissant tourner
l'ANCIEN code pendant que git a l'air parfaitement sain. Et meme quand le code
est bien en ligne, un champ calcule STOCKE ne se recalcule pas quand sa logique
change : le 2026-11-24, tous les controles techniques etaient au vert sur des
donnees fausses.

Ce script controle donc deux choses distinctes :
  - la PRESENCE du code (version, champs, vues, modeles, droits) ;
  - le COMPORTEMENT attendu (assertions metier).

Usage :
    python scripts/verifier_deploiement.py
    python scripts/verifier_deploiement.py --url https://eurekam-recette.odoo.com
    python scripts/verifier_deploiement.py --production OUI-JE-VALIDE-LA-PRODUCTION \
        --url https://eurekam.odoo.com

Code de sortie 0 si tout est conforme, 1 sinon.
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.request
import xmlrpc.client

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(BASE), 'config', 'odoo_test.json')

JETON_PRODUCTION = 'OUI-JE-VALIDE-LA-PRODUCTION'
URL_PRODUCTION = 'https://eurekam.odoo.com'
MOTIF_BASE_PRODUCTION = r'^tecliberp-eurekam-main-\d+$'
MOTS_TEST = ('test', 'staging', 'sandbox', 'recette', 'dev', 'preprod')
MOTIF_BASE_DEFAUT = r'^eurekam-(sandbox|staging|recette|test|dev|preprod)(-\d+)?$'

VERSION_ATTENDUE = '18.0.2.5.0'
LIGNE = 'eurekam.maintenance.contract.line'
CONTRAT = 'eurekam.maintenance.contract'

CHAMPS_LIGNE = ('order_state', 'order_count', 'order_ids')
CHAMPS_CONTRAT = (('sale_order_header_ids', 'one2many'),
                  ('sale_order_ids', 'many2many'))
FILTRES = ('filter_to_order', 'filter_to_order_due', 'filter_ordered',
           'group_order_state')
MODELES_ASSISTANT = ('eurekam.maintenance.attach.order.wizard',
                     'eurekam.maintenance.attach.order.line')


def resoudre_base(url):
    """Demande a l'instance le nom de sa base.

    Une reponse qui n'est pas du JSON ne veut pas dire que l'instance est
    tombee : l'alias de branche odoo.sh peut rediriger ailleurs alors que le
    build tourne. On le dit explicitement plutot que de laisser remonter une
    trace d'erreur JSON illisible.
    """
    req = urllib.request.Request(
        url + '/web/database/list',
        data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                         'params': {}}).encode(),
        headers={'Content-Type': 'application/json'})
    reponse = urllib.request.urlopen(req, timeout=60)
    arrivee = reponse.geturl()
    brut = reponse.read()
    try:
        return json.loads(brut)['result'][0]
    except (ValueError, KeyError, IndexError):
        sys.exit(
            "STOP : %s n'a pas repondu en JSON.\n"
            "       Requete arrivee sur : %s\n"
            "       L'instance n'est pas forcement tombee : sur odoo.sh\n"
            "       l'alias de branche peut cesser de pointer sur le build\n"
            "       alors que celui-ci tourne. Ouvrir la branche sur\n"
            "       odoo.sh, relever l'adresse du bouton CONNECT (de la\n"
            "       forme https://<projet>-<branche>-<build>.dev.odoo.com)\n"
            "       et relancer avec --url sur cette adresse." % (url, arrivee))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url')
    ap.add_argument('--production', metavar='JETON')
    ap.add_argument('--version', default=VERSION_ATTENDUE)
    args = ap.parse_args()

    cfg = json.load(io.open(CONFIG, encoding='utf-8'))
    url = (args.url or cfg['url']).rstrip('/')

    # --- Garde-fou, AVANT tout contact reseau ---
    if args.production:
        if args.production != JETON_PRODUCTION:
            sys.exit("STOP : --production attend le jeton exact %r. "
                     "Aucune requete n'a ete envoyee." % JETON_PRODUCTION)
        if url.lower() != URL_PRODUCTION:
            sys.exit("STOP : --production n'autorise que %s. "
                     "Aucune requete n'a ete envoyee." % URL_PRODUCTION)
        db = resoudre_base(url)
        if not re.match(MOTIF_BASE_PRODUCTION, db):
            sys.exit('STOP : base %r inattendue.' % db)
        print('>> ENVIRONNEMENT : *** PRODUCTION *** -- Base : %s' % db)
    else:
        u = url.lower()
        if not any(mot in u for mot in MOTS_TEST):
            sys.exit("STOP : l'URL %s ne contient aucun mot-cle de test. "
                     "Aucune requete n'a ete envoyee." % url)
        for mot in ('prod', 'production'):
            if mot in u and 'preprod' not in u:
                sys.exit("STOP : mot-cle interdit '%s' dans l'URL." % mot)
        db = resoudre_base(url)
        if not re.match(MOTIF_BASE_DEFAUT, db):
            sys.exit('STOP : base %r hors du motif de test.' % db)
        print('>> ENVIRONNEMENT : TEST -- Base : %s' % db)
    print('>> MODE          : LECTURE SEULE')
    print('>> VERSION VISEE : %s\n' % args.version)

    pwd = cfg.get('password') or cfg.get('api_key')
    uid = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common').authenticate(
        db, cfg['username'], pwd, {})
    if not uid:
        sys.exit('STOP : authentification refusee.')
    models = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object',
                                       allow_none=True)

    def call(model, method, *a, **kw):
        kw.setdefault('context', {})['lang'] = 'fr_FR'
        return models.execute_kw(db, uid, pwd, model, method, list(a), kw)

    ok = True

    def verdict(bon, libelle, detail=''):
        nonlocal ok
        ok = ok and bon
        print('  %-7s %s%s' % ('OK' if bon else 'ECHEC', libelle,
                               ('  %s' % detail) if detail else ''))

    # ---- 1. Presence du code --------------------------------------------
    print('--- Module ---')
    mod = call('ir.module.module', 'search_read',
               [('name', '=', 'eurekam_maintenance')],
               fields=['state', 'latest_version', 'write_date'])
    if not mod:
        print('  ECHEC   module introuvable'); sys.exit(1)
    m = mod[0]
    verdict(m['state'] == 'installed', 'module installe', m['state'])
    verdict(m['latest_version'] == args.version, 'version en ligne',
            '%s (ecrit le %s UTC)' % (m['latest_version'], m['write_date']))

    print('\n--- Champs ---')
    presents = {c['name'] for c in call(
        'ir.model.fields', 'search_read',
        [('model', '=', LIGNE), ('name', 'in', list(CHAMPS_LIGNE))],
        fields=['name'])}
    for nom in CHAMPS_LIGNE:
        verdict(nom in presents, '%s.%s' % (LIGNE, nom))
    types = call(CONTRAT, 'fields_get', [], ['type'])
    for nom, attendu in CHAMPS_CONTRAT:
        c = types.get(nom)
        verdict(bool(c) and c['type'] == attendu,
                '%s.%s' % (CONTRAT, nom), c['type'] if c else 'absent')

    print('\n--- Vues et assistant ---')
    vues = call('ir.ui.view', 'search_read',
                [('model', '=', LIGNE), ('type', '=', 'list'),
                 ('inherit_id', '=', False)], fields=['name'])
    verdict(len(vues) == 1,
            'une seule vue liste autonome sur la ligne annuelle',
            '%d trouvee(s)' % len(vues))
    arch = call(LIGNE, 'get_view', **{'view_type': 'search'})['arch']
    for nom in FILTRES:
        verdict('name="%s"' % nom in arch, 'filtre %s' % nom)
    liste = call(LIGNE, 'get_view', **{'view_type': 'list'})['arch']
    for champ in ('contract_id', 'partner_id', 'order_state'):
        verdict('name="%s"' % champ in liste,
                'colonne %s dans la liste du menu' % champ)
    for modele in MODELES_ASSISTANT:
        verdict(bool(call('ir.model', 'search_count',
                          [('model', '=', modele)])), 'modele %s' % modele)
    acl = call('ir.model.access', 'search_count',
               [('model_id.model', 'in', list(MODELES_ASSISTANT))])
    verdict(acl >= 4, 'droits d acces de l assistant', '%d / 4' % acl)
    # get_view rend la vue TELLE QUE LA VOIT LE COMPTE qui interroge : Odoo
    # en retire les elements reserves a un groupe. Lance avec un compte en
    # lecture seule, il ferait echouer le controle des boutons alors que le
    # deploiement est parfait. Les assertions sur le contenu de NOTRE
    # formulaire lisent donc l arche stockee, traduite par le contexte de
    # langue et independante du lecteur. L appel a get_view reste, comme
    # test de fumee : une vue heritee cassee leve ici.
    call(CONTRAT, 'get_view', **{'view_type': 'form'})
    vue_contrat = call('ir.model.data', 'search_read',
                       [('module', '=', 'eurekam_maintenance'),
                        ('name', '=', 'view_maintenance_contract_form')],
                       fields=['res_id'])
    form = call('ir.ui.view', 'read', [vue_contrat[0]['res_id']],
                fields=['arch_db'])[0]['arch_db'] if vue_contrat else ''
    # Ce controle porte sur la METHODE, pas sur le libelle : le libelle est
    # verifie plus bas, dans la section des traductions. Le dire ici evite
    # de lire "OK" pour un bouton qui s affiche en anglais.
    verdict('action_open_attach_order_wizard' in form,
            'bouton de rattachement present (methode)')
    verdict('name="order_state"' in form,
            'pastille Commande dans l onglet Montants annuels')

    print('\n--- Planification ---')
    # active_test=False : ce cron est livre DESACTIVE, et une recherche Odoo
    # ecarte les inactifs par defaut. Sans ce contexte, le controle declare
    # absent un cron parfaitement en place.
    crons = call('ir.cron', 'search_read',
                 [('code', 'like', '_cron_check_years_to_order')],
                 fields=['name', 'active'],
                 context={'active_test': False, 'lang': 'fr_FR'})
    verdict(bool(crons), 'cron des annees sans devis present')
    if crons:
        verdict(not crons[0]['active'],
                'cron livre DESACTIVE (a activer apres le rattachement)',
                'actif=%s' % crons[0]['active'])
    # Recherche par xmlid, pas par res_model : la base porte deja des types
    # d'activite sur sale.order ("Commande additionnelle"), et un controle par
    # modele repondait OK sans rien verifier de ce que nous livrons.
    def type_active(nom_xml):
        return bool(call('ir.model.data', 'search_count',
                         [('module', '=', 'eurekam_maintenance'),
                          ('model', '=', 'mail.activity.type'),
                          ('name', '=', nom_xml)]))

    verdict(type_active('activity_type_year_to_order'),
            'type d activite "Devis annuel a emettre"')
    periodiques = call('ir.cron', 'search_read',
                       [('code', 'like', '_cron_check_periods_due')],
                       fields=['active'],
                       context={'active_test': False, 'lang': 'fr_FR'})
    verdict(bool(periodiques), 'cron des periodes echues present')
    if periodiques:
        verdict(periodiques[0]['active'],
                'cron des periodes livre ACTIF (il ne voit que les devis '
                'emis par le module)')
    verdict(type_active('activity_type_period_due'),
            'type d activite "Periode de maintenance echue"')

    print('\n--- Rythme des documents ---')
    champs_ligne = call('sale.order.line', 'fields_get', [], ['type'])
    for nom in ('maintenance_period_start', 'maintenance_period_end',
                'maintenance_billing_date'):
        verdict(nom in champs_ligne, 'sale.order.line.%s' % nom)
    champs_cmd = call('sale.order', 'fields_get', [], ['type'])
    verdict('eurekam_maintenance_period' in champs_cmd,
            'sale.order.eurekam_maintenance_period')
    modes = call(CONTRAT, 'fields_get', ['billing_document_mode'],
                 ['selection'])
    codes = [c for c, _l in (modes.get('billing_document_mode') or
                             {}).get('selection', [])]
    verdict(sorted(codes) == ['annual_quote', 'quote_per_period'],
            'les deux rythmes de document sur le contrat', str(codes))
    wiz = call('eurekam.maintenance.order.wizard', 'fields_get',
               ['coverage_mode'], ['selection'])
    codes_wiz = [c for c, _l in (wiz.get('coverage_mode') or
                                 {}).get('selection', [])]
    verdict('period_split' in codes_wiz,
            'mode "un devis par periode" dans l assistant', str(codes_wiz))

    print('\n--- Filtres sur les commandes clients ---')

    def arch_recherche(xmlid):
        mod, nom = xmlid.split('.')
        d = call('ir.model.data', 'search_read',
                 [('module', '=', mod), ('name', '=', nom)], fields=['res_id'])
        if not d:
            return ''
        return call('sale.order', 'get_view',
                    **{'view_id': d[0]['res_id'],
                       'view_type': 'search'})['arch']

    # Les deux listes, pas une seule : Ventes a deux vues de recherche
    # soeurs, et "Devis pas encore envoye" n a de sens que cote devis.
    for etiquette, xmlid in (
            ('liste des devis', 'sale.sale_order_view_search_inherit_quotation'),
            ('liste des commandes', 'sale.sale_order_view_search_inherit_sale')):
        arch = arch_recherche(xmlid)
        for filtre in ('eurekam_has_contract', 'eurekam_period_due',
                       'eurekam_not_sent'):
            verdict('name="%s"' % filtre in arch,
                    'filtre %s sur la %s' % (filtre, etiquette))

    # Une annee est un libelle, pas une quantite : sans cette option elle
    # s affiche "2 026".
    for etiquette, modele, type_vue in (
            ('onglet Montants annuels', CONTRAT, 'form'),
            ('menu Lignes annuelles', LIGNE, 'list')):
        arch = call(modele, 'get_view', **{'view_type': type_vue})['arch']
        bloc = arch.split('name="year"')
        verdict(len(bloc) > 1 and "'format': false" in bloc[1][:80],
                'annee non formatee en milliers (%s)' % etiquette)

    print('\n--- Niveau lecture seule ---')

    def ref_id(xmlid):
        mod, nom = xmlid.split('.')
        d = call('ir.model.data', 'search_read',
                 [('module', '=', mod), ('name', '=', nom)], fields=['res_id'])
        return d[0]['res_id'] if d else 0

    id_lecture = ref_id('eurekam_maintenance.group_maintenance_readonly')
    id_user = ref_id('eurekam_maintenance.group_maintenance_user')
    verdict(bool(id_lecture), 'groupe Lecture seule present')

    # Le controle qui compte : group_maintenance_user a ete cree dans un
    # bloc noupdate, donc l implication ne peut pas etre declaree en XML et
    # vient d une migration. Si elle manque, tout le reste parait en place.
    implies = call('res.groups', 'read', [id_user],
                   fields=['implied_ids'])[0]['implied_ids'] if id_user else []
    verdict(bool(id_lecture) and id_lecture in implies,
            '"Utilisateur" implique "Lecture seule"',
            '' if id_lecture and id_lecture in implies
            else 'migration 18.0.2.5.0 non appliquee')

    # Sans ce garde-fou, un domaine ('group_id', '=', 0) remonte les droits
    # SANS groupe et le controle s auto-felicite sur 38 lignes etrangeres.
    acl = call('ir.model.access', 'search_read',
               [('group_id', '=', id_lecture)],
               fields=['name', 'model_id', 'perm_read', 'perm_write',
                       'perm_create', 'perm_unlink']) if id_lecture else []
    verdict(len(acl) == 10, 'droits de lecture seule', '%d ligne(s)' % len(acl))
    ecrivent = [a['name'] for a in acl
                if a['perm_write'] or a['perm_create'] or a['perm_unlink']]
    verdict(bool(acl) and not ecrivent,
            'aucun droit d ecriture en lecture seule',
            ', '.join(ecrivent) or ('' if acl else 'aucun droit a controler'))
    assistants = [a['name'] for a in acl if 'wizard' in a['model_id'][1]]
    verdict(bool(acl) and not assistants,
            'aucun assistant ouvert en lecture seule',
            ', '.join(assistants) or ('' if acl else 'aucun droit a controler'))

    for xmlid, etiquette in (
            ('rule_maintenance_contract_company_readonly', 'contrats'),
            ('rule_maintenance_contract_line_company_readonly', 'lignes')):
        rid = ref_id('eurekam_maintenance.' + xmlid)
        if not rid:
            verdict(False, 'regle de societe (%s) en lecture seule' % etiquette)
            continue
        regle = call('ir.rule', 'read', [rid],
                     fields=['perm_read', 'perm_write', 'active'])[0]
        verdict(regle['active'] and regle['perm_read']
                and not regle['perm_write'],
                'regle de societe (%s) en lecture seule' % etiquette)

    id_menu = ref_id('eurekam_maintenance.menu_root_maintenance')
    groupes_menu = call('ir.ui.menu', 'read', [id_menu],
                        fields=['groups_id'])[0]['groups_id'] if id_menu else []
    verdict(id_lecture in groupes_menu, 'menu Maintenance ouvert a la lecture')

    # L arche STOCKEE (lue plus haut), pas celle rendue : Odoo retire
    # l attribut groups de l arche servie au client, un get_view ne le
    # montrerait jamais.
    brut = form
    attendus = ('action_activate', 'action_generate_lines',
                'action_open_renewal_wizard', 'action_open_create_order_wizard',
                'action_open_attach_order_wizard', 'action_recompute_state',
                'action_cancel', 'action_draft')
    sans_garde = []
    for nom in attendus:
        marque = 'name="%s"' % nom
        pos = brut.find(marque)
        if pos < 0 or 'group_maintenance_user' not in brut[pos:pos + 400]:
            sans_garde.append(nom)
    verdict(not sans_garde, 'les 8 boutons d action sont reserves',
            ', '.join(sans_garde))

    print('\n--- Traductions francaises ---')
    # Lues sur l arche RENDUE en fr_FR, pas dans le fichier .po : un msgid
    # qui ne correspond pas a la chaine source donne une traduction morte,
    # que le .po seul ne revele jamais.
    E, A = u'é', u'à'
    attendus = (
        (form, u'Rattacher une commande', 'bouton de rattachement'),
        (form, u'Cr%ser le devis' % E, 'bouton de creation de devis'),
    )
    if id_lecture:
        nom_groupe = call('res.groups', 'read', [id_lecture],
                          fields=['name'])[0]['name']
        verdict(nom_groupe == u'Lecture seule',
                'libelle francais : groupe lecture seule', nom_groupe)
    arch_cmd = arch_recherche('sale.sale_order_view_search_inherit_sale')
    for terme, etiquette in (
            (u'Contrat de maintenance', 'filtre contrat de maintenance'),
            (u'P%(e)sriode de maintenance %(e)schue' % {'e': E},
             'filtre periode echue'),
            (u'Devis pas encore envoy%s' % E, 'filtre devis non envoye')):
        attendus += ((arch_cmd, terme, etiquette),)
    for arch, terme, etiquette in attendus:
        verdict(terme in arch, 'libelle francais : %s' % etiquette,
                '' if terme in arch else 'attendu %r' % terme)

    # ---- 2. Comportement attendu ----------------------------------------
    print('\n--- Assertions metier ---')
    try:
        groupes = call(LIGNE, 'read_group', [], ['id'], ['order_state'])
        repartition = {g['order_state'] or '(vide)': g['order_state_count']
                       for g in groupes}
        verdict(bool(groupes), 'le statut de commande repond',
                ', '.join('%s=%d' % kv for kv in sorted(repartition.items())))
    except Exception as exc:
        verdict(False, 'le statut de commande repond', str(exc)[:90])

    fermes = call(LIGNE, 'search_count',
                  [('order_state', '=', 'to_order'),
                   ('contract_state', 'in', ['draft', 'expired', 'cancelled'])])
    verdict(fermes == 0,
            'aucune ligne "a commander" sur un contrat ferme',
            '%d trouvee(s)' % fermes)

    g = call(LIGNE, 'read_group', [], ['year', 'amount'], ['contract_id'])
    verdict(not (g and 'year' in g[0]),
            'l annee n est pas totalisee par groupe')

    print('\n==> %s' % ('DEPLOIEMENT CONFORME' if ok
                        else 'DEPLOIEMENT NON CONFORME'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
