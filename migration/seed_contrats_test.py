# -*- coding: utf-8 -*-
"""Recree le jeu de contrats de maintenance de test sur une base de TEST.

Les 5 scenarios ne sont plus inventes : chacun reprend un contrat REEL de la
base Notion "Assistance DO" (etablissement, marche, GEN, cadence, niveau de
facturation, revision Syntec, nombre de postes, dates et montants annuels),
tout en conservant le role de test qui lui est propre.

Choix de fidelite, pour que le jeu reste exploitable :

* Etablissements : uniquement des correspondances `CERTAIN` de
  correspondance_etablissements.csv. Beaucoup de rapprochements Notion->Odoo
  sont douteux (trois etablissements lyonnais distincts pointent sur le meme
  partenaire 1845, Croix Rousse pointe sur une clinique privee) ; en retenir un
  seul douteux rendrait le jeu de test trompeur.
* Produit : Notion ne porte AUCUNE reference article. Le produit et son libelle
  sont donc choisis ici, coherents avec la GEN et le pays. C'est la seule
  donnee du jeu qui ne vient pas de Notion, et c'est assume.
* `duration` : Notion stocke le nombre d'annees COMMANDEES, pas la duree du
  contrat. D'ou des contrats 2023->2027 marques "1 an". On reproduit cette
  bizarrerie telle quelle : c'est ce que les testeurs verront dans les vraies
  donnees.
* Montants : ceux de Notion. Les annees que Notion laisse vides sont
  pre-remplies par le module avec le montant de reference, comme en production.

Idempotent : un contrat portant deja le meme couple (etablissement, libelle
produit) est repris au lieu d'etre recree, pour que le script puisse etre
relance apres un rebuild sans empiler les doublons.

Tous les contrats sont assignes a l'utilisateur courant : le cron d'expiration
notifie le commercial du contrat, et on ne veut pas arroser les collegues
depuis une base de test.

Usage :
    python migration/seed_contrats_test.py
    python migration/seed_contrats_test.py --url https://eurekam-recette.odoo.com
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

MOTS_TEST = ('test', 'staging', 'dev', 'preprod', 'recette', 'sandbox')
MOTIF_BASE_DEFAUT = r'^eurekam-(sandbox|staging|recette|test|dev|preprod)(-\d+)?$'


def verifier_url(url, cfg):
    """Controle l'URL AVANT tout contact reseau."""
    if cfg.get('environment') != 'TEST':
        sys.exit("STOP : la configuration ne declare pas environment='TEST'")
    u = url.lower()
    if not any(mot in u for mot in MOTS_TEST):
        sys.exit("STOP : l'URL %s ne contient aucun mot-cle de test (%s). "
                 "Aucune requete n'a ete envoyee." % (url, ', '.join(MOTS_TEST)))
    interdits = (cfg.get('safety_check', {}) or {}).get(
        'forbidden_url_keywords', ('prod', 'production', 'main'))
    for mot in interdits:
        if mot.lower() in u and not (mot.lower() == 'prod' and 'preprod' in u):
            sys.exit("STOP : l'URL %s contient le mot-cle interdit '%s'. "
                     "Aucune requete n'a ete envoyee." % (url, mot))


def resoudre_base(url):
    req = urllib.request.Request(
        url + '/web/database/list',
        data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                         'params': {}}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        bases = json.load(urllib.request.urlopen(req, timeout=30))['result']
    except Exception as exc:
        sys.exit('STOP : impossible de lister les bases sur %s (%s).'
                 % (url, type(exc).__name__))
    if len(bases) != 1:
        sys.exit('STOP : %d bases visibles sur %s, cible ambigue : %s'
                 % (len(bases), url, bases))
    return bases[0]


def verifier_base(db, cfg):
    motif = cfg.get('database_pattern') or MOTIF_BASE_DEFAUT
    if not re.match(motif, db):
        sys.exit("STOP : la base %r ne correspond pas au motif de test %r"
                 % (db, motif))


# ---------------------------------------------------------------------------
# Les 5 scenarios, chacun calque sur un contrat reel de Notion.
# ---------------------------------------------------------------------------
CONTRATS = [
    {
        'cle': 'lyon_sud_syntec_trimestriel',
        'notion': '69 - Lyon - GHS - Hopital Lyon SUD',
        'partner_id': 1845,          # HCL Hopital Lyon Sud  (CERTAIN)
        'product_id': 485,           # Assistance DRUGCAM GEN2 Oncology FR
        'product_name': 'Assistance DRUGCAM GEN2 Oncology FR',
        'gen': 'gen2',
        'marche': 'UniHA 2021',
        'order_status': 'received',
        'date_start': '2023-02-23', 'date_end': '2027-12-31', 'duration': '1y',
        'maintenance_amount': 15200.0, 'nb_products': 4,
        'syntec_revision': 'yes', 'billing_level': '75',
        'freqs': ['quarterly', 'overdue'],
        'montants': {2025: 14321.76, 2026: 15200.0, 2027: 15200.0},
        'activer': True,
        'note': "Contrat pivot, calque sur le contrat Notion de Lyon Sud. "
                "Trimestriel a echu + revision Syntec OUI + 4 postes : c'est "
                "celui qui teste la revision Syntec a la creation de commande "
                "et le libelle de ligne \"... - 4 postes - 1er trimestre 2026\". "
                "Niveau de facturation 75 %, comme dans Notion. "
                "Notion ne renseigne pas 2023 et 2024 : ces deux annees sont "
                "pre-remplies au montant de reference par le module.",
    },
    {
        'cle': 'evreux_expirant',
        'notion': '27 - Evreux - CHI Eure-Seine',
        'partner_id': 358,           # Centre hospitalier intercommunal Eure-Seine
        'product_id': 531,           # Assistance DRUGCAM Sterile FR
        'product_name': 'Assistance DRUGCAM Sterile FR',
        'gen': 'gen1',
        'marche': 'UniHA 2021',
        'order_status': 'received',
        'date_start': '2024-10-20', 'date_end': '2026-12-31', 'duration': '1y',
        'maintenance_amount': 3800.0, 'nb_products': 1,
        'syntec_revision': 'no', 'billing_level': '100',
        'freqs': ['annual'],
        'montants': {2025: 3800.0, 2026: 3800.0},
        'activer': True,
        'note': "Contrat reel d'Evreux, qui se termine le 31/12/2026 : il doit "
                "basculer tout seul en \"Expire bientot\" et declencher "
                "l'alerte du cron. Un seul poste -> verifie aussi le singulier "
                "\"1 poste\" dans le libelle de ligne.",
    },
    {
        'cle': 'bourg_en_bresse_module_facturable',
        'notion': '01 - Bourg en Bresse - CH',
        'partner_id': 1779,          # Hopital Fleyriat
        'product_id': 485,
        'product_name': 'Assistance DRUGCAM GEN2 Oncology FR',
        'gen': 'gen2',
        'marche': 'UniHA 2021',
        'order_status': 'received',
        'date_start': '2025-07-16', 'date_end': '2030-07-15', 'duration': '1y',
        'maintenance_amount': 16575.0, 'nb_products': 4,
        'syntec_revision': 'yes', 'billing_level': '100',
        'freqs': ['annual'],
        # 2024 est ANTERIEUR au debut de contrat : c'est le cas, frequent dans
        # Notion, de montants qui debordent des dates. Le script cree la ligne
        # malgre tout, comme le fait l'import de migration, au lieu de la perdre.
        'montants': {2024: 2380.0, 2025: 7211.0, 2026: 16575.0,
                     2027: 18199.0, 2028: 20780.0},
        'module_facturable': {'code': 'stats', 'amount': 2500.0,
                              'start_year': 2026},
        'activer': True,
        'note': "Contrat reel de Bourg-en-Bresse, avec un module facturable "
                "Statistique. Montee en charge reelle (2 380 -> 20 780 EUR) : "
                "utile pour le tableau de bord et les totaux. Porte aussi le "
                "piege Notion d'un montant 2024 anterieur au debut du contrat "
                "(16/07/2025), volontairement conserve.",
    },
    {
        'cle': 'caen_facturation_sans_bc',
        'notion': '14 - Caen - CLCC Francois Baclesse',
        'partner_id': 2682,          # Centre Francois Baclesse
        'product_id': 485,
        'product_name': 'Assistance DRUGCAM GEN2 Oncology FR',
        'gen': 'gen2',
        'marche': 'Private',
        'order_status': 'no_po',
        'date_start': '2025-03-13', 'date_end': '2029-12-31', 'duration': '1y',
        'maintenance_amount': 4200.0, 'nb_products': 1,
        'syntec_revision': 'yes', 'billing_level': '100',
        'freqs': ['annual'],
        'montants': {2025: 3395.0, 2026: 4200.0, 2027: 5965.89},
        'activer': True,
        'note': "Contrat reel du CLCC Baclesse, en \"Facturation sans BC\". "
                "Ce statut remplace le \"Suspendu\" de l'ancien jeu de test : "
                "Notion compte 26 contrats sans BC contre 4 suspendus, dont 3 "
                "distributeurs espagnols hors du perimetre France. Syntec OUI "
                "sur un seul poste.",
    },
    {
        'cle': 'charleville_expire',
        'notion': '08 - Charleville-Mezieres - CH',
        'partner_id': 1223,          # Centre Hospitalier Intercommunal Nord-Ardennes
        'product_id': 531,
        'product_name': 'Assistance DRUGCAM Sterile FR',
        'gen': 'gen1',
        'marche': 'UniHA 2019',
        'order_status': 'received',
        'date_start': '2020-06-25', 'date_end': '2025-12-31', 'duration': '6m',
        'maintenance_amount': 5220.0, 'nb_products': 4,
        'syntec_revision': 'yes', 'billing_level': '50',
        'freqs': ['semi_annual', 'overdue'],
        # Notion ne detaille pas les montants annuels de ce contrat : les
        # lignes sont pre-remplies au montant de reference (5 220 EUR), ce que
        # fait aussi le module en production.
        'montants': {},
        'activer': True,
        'note': "Contrat reel de Charleville-Mezieres, termine le 31/12/2025 : "
                "doit basculer en \"Expire\" des l'activation, avec un "
                "historique 2020-2025. Semestriel a echu, niveau 50 %, "
                "duree commandee \"6 mois\" pour un contrat de 5 ans : "
                "exemple reel de l'ecart entre duree commandee et duree reelle.",
    },
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', help='Autre instance de TEST a viser '
                                  '(ex: https://eurekam-recette.odoo.com).')
    args = ap.parse_args()

    cfg = json.load(io.open(CONFIG, encoding='utf-8'))
    url = args.url.rstrip('/') if args.url else cfg['url']
    verifier_url(url, cfg)                     # avant tout contact reseau
    db = resoudre_base(url) if args.url else cfg['database']
    verifier_base(db, cfg)

    user = cfg['username']
    pwd = cfg.get('password') or cfg.get('api_key')
    print('>> ENVIRONNEMENT : TEST -- Base : %s' % db)
    print('>> URL           : %s\n' % url)

    uid = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common').authenticate(
        db, user, pwd, {})
    if not uid:
        sys.exit('STOP : authentification refusee pour %s sur %s' % (user, db))
    models = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object',
                                       allow_none=True)

    def call(model, method, *a, **kw):
        return models.execute_kw(db, uid, pwd, model, method, list(a), kw)

    FREQ = {r['code']: r['id'] for r in
            call('eurekam.billing.frequency', 'search_read', [],
                 fields=['code'])}
    MARKET = {r['name']: r['id'] for r in
              call('eurekam.market.type', 'search_read', [], fields=['name'])}
    GENERATION = {r['code']: r['id'] for r in
                  call('eurekam.product.generation', 'search_read', [],
                       fields=['code'])}
    MODFACT = {r['code']: r['id'] for r in
               call('eurekam.module.billing', 'search_read', [],
                    fields=['code'])}

    resultats = []
    for spec in CONTRATS:
        # Securite : le partenaire doit exister sur CETTE base.
        if not call('res.partner', 'search_count',
                    [('id', '=', spec['partner_id'])]):
            print('!! partenaire %d introuvable, scenario %s ignore'
                  % (spec['partner_id'], spec['cle']))
            continue

        vals = {
            'product_id': spec['product_id'],
            'product_name': spec['product_name'],
            'commercial_id': uid,
            'gen_id': GENERATION.get(spec['gen'], False),
            'market_type_ids': [(6, 0, [MARKET[spec['marche']]])],
            'order_status': spec['order_status'],
            'date_start': spec['date_start'],
            'date_end': spec['date_end'],
            'duration': spec['duration'],
            'maintenance_amount': spec['maintenance_amount'],
            'nb_products': spec['nb_products'],
            'syntec_revision': spec['syntec_revision'],
            'billing_level': spec['billing_level'],
            'billing_frequency_ids': [(6, 0, [FREQ[f] for f in spec['freqs']])],
            'comment': spec['note'],
        }

        # Ces 5 scenarios sont de VRAIS contrats Notion : si la migration a
        # deja ete jouee sur cette base, elle les a importes en brouillon et
        # sans produit. On complete ce contrat-la plutot que d'en creer un
        # second, sinon l'etablissement apparait deux fois avec les memes
        # dates et les memes montants.
        cid = None
        for domaine, origine in (
            ([('partner_id', '=', spec['partner_id']),
              ('product_name', '=', spec['product_name'])], 'jeu de test'),
            ([('partner_id', '=', spec['partner_id']),
              ('date_start', '=', spec['date_start'])], 'migration Notion'),
        ):
            trouve = call('eurekam.maintenance.contract', 'search', domaine,
                          limit=1)
            if trouve:
                cid = trouve[0]
                call('eurekam.maintenance.contract', 'write', [cid], vals)
                print('= repris (%-16s) : %-34s (id %d)'
                      % (origine, spec['cle'], cid))
                break
        if cid is None:
            vals['partner_id'] = spec['partner_id']
            cid = call('eurekam.maintenance.contract', 'create', vals)
            print('+ cree%-20s : %-34s (id %d)' % ('', spec['cle'], cid))

        if spec['activer']:
            etat = call('eurekam.maintenance.contract', 'read', [cid],
                        fields=['state'])[0]['state']
            if etat == 'draft':
                call('eurekam.maintenance.contract', 'action_activate', [cid])

        call('eurekam.maintenance.contract', 'action_generate_lines', [cid])

        # Montants annuels reels. Une annee presente dans Notion mais hors des
        # dates du contrat n'a pas de ligne generee : on la cree, au lieu de
        # perdre le montant (meme regle que l'import de migration).
        existantes = {l['year']: l for l in
                      call('eurekam.maintenance.contract.line', 'search_read',
                           [('contract_id', '=', cid)],
                           fields=['year', 'amount'])}
        for annee, cible in sorted(spec['montants'].items()):
            ligne = existantes.get(annee)
            if ligne is None:
                call('eurekam.maintenance.contract.line', 'create',
                     {'contract_id': cid, 'year': annee, 'amount': cible})
            elif abs(ligne['amount'] - cible) > 0.01:
                call('eurekam.maintenance.contract.line', 'write',
                     [ligne['id']], {'amount': cible})

        if spec.get('module_facturable'):
            mf = spec['module_facturable']
            mid = MODFACT.get(mf['code'])
            if not mid:
                print('   !! module facturable %r absent de cette base'
                      % mf['code'])
            elif not call('eurekam.contract.module.line', 'search_count',
                          [('contract_id', '=', cid),
                           ('module_billing_id', '=', mid)]):
                call('eurekam.contract.module.line', 'create', {
                    'contract_id': cid, 'module_billing_id': mid,
                    'amount': mf['amount'], 'start_year': mf['start_year']})

        rec = call('eurekam.maintenance.contract', 'read', [cid],
                   fields=['sequence_number', 'state', 'partner_id',
                           'total_contract_value'])[0]
        resultats.append((rec['sequence_number'], rec['state'],
                          rec['partner_id'][1], rec['total_contract_value'],
                          spec['cle']))

    print('\n%-18s %-10s %-36s %12s' % ('REFERENCE', 'ETAT', 'ETABLISSEMENT',
                                        'TOTAL'))
    for seq, st, part, tot, cle in resultats:
        print('%-18s %-10s %-36s %12.2f' % (seq, st, part[:36], tot))
    print('\n%d contrats en place.' % len(resultats))


if __name__ == '__main__':
    main()
