# -*- coding: utf-8 -*-
"""Rattache les devis d'Assistance existants aux annees de contrat.

Eurekam avait des annees de devis derriere elle quand le module a ete
installe. Ces commandes ne pointent vers aucun contrat, si bien que chaque
compteur et chaque « annee a commander » declare un contrat sans devis alors
que le devis dort dans Odoo, signe.

Ce script fait en masse ce que l'assistant « Rattacher une commande » fait a
l'unite, et selon exactement les memes regles.

PRINCIPE : il ne decide jamais a la place de l'equipe. Il classe chaque ligne,
ecrit un fichier de relecture, et n'ecrit en base que les lignes classees
PRET. Tout ce qui demande un jugement est laisse de cote et motive.

Perimetre par defaut : les devis couvrant **2026 et au-dela**. L'historique
ancien n'a pas de valeur de suivi et son appariement serait du travail perdu.

Usage :
    python migration/rattacher_devis.py                      # passage a blanc TEST
    python migration/rattacher_devis.py --apply              # ecrit sur TEST
    python migration/rattacher_devis.py --depuis 2027        # autre borne
    python migration/rattacher_devis.py --production OUI-JE-VALIDE-LA-PRODUCTION \
        --url https://eurekam.odoo.com                       # passage a blanc PROD
    ... --apply                                              # ecrit en PROD
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
import xmlrpc.client
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(BASE)
CONFIG = os.path.join(RACINE, 'config', 'odoo_test.json')
RELECTURE = os.path.join(RACINE, 'livraison',
                         'rattachement_devis_a_relire.csv')

JETON_PRODUCTION = 'OUI-JE-VALIDE-LA-PRODUCTION'
URL_PRODUCTION = 'https://eurekam.odoo.com'
MOTIF_BASE_PRODUCTION = r'^tecliberp-eurekam-main-\d+$'
MOTS_TEST = ('test', 'staging', 'sandbox', 'recette', 'dev', 'preprod')
MOTIF_BASE_DEFAUT = r'^eurekam-(sandbox|staging|recette|test|dev|preprod)(-\d+)?$'

# Meme expression que _deduire_annee dans l'assistant : 936 des 1 068 lignes a
# rattacher ecrivent leur annee en clair (« Assistance 2 Postes - Annee 1 avec
# Garantie - 2027 »). C'est le meilleur signal disponible.
ANNEE_DANS_LIBELLE = re.compile(r'\b(20\d{2})\b')

ENTETES = [
    'statut', 'motif', 'devis', 'etat_devis', 'date_commande',
    'etablissement', 'article', 'libelle_ligne', 'montant_ligne',
    'annee_deduite', 'contrat', 'annee_contrat', 'montant_annee',
    'total_lignes_annee', 'ecart',
    'id_ligne_commande', 'id_ligne_annuelle',
]


# ----------------------------------------------------------------- garde-fou
def verifier_production(url, jeton):
    if jeton != JETON_PRODUCTION:
        sys.exit("STOP : --production attend le jeton exact %r. "
                 "Aucune requete n'a ete envoyee." % JETON_PRODUCTION)
    if url.rstrip('/').lower() != URL_PRODUCTION:
        sys.exit("STOP : --production n'autorise que %s, pas %s. "
                 "Aucune requete n'a ete envoyee." % (URL_PRODUCTION, url))


def verifier_url(url, cfg):
    """Controle l'URL AVANT tout contact reseau. L'ordre compte."""
    if cfg.get('environment') != 'TEST':
        sys.exit("STOP : la configuration ne declare pas environment='TEST'")
    u = url.lower()
    if not any(mot in u for mot in MOTS_TEST):
        sys.exit("STOP : l'URL %s ne contient aucun mot-cle de test (%s). "
                 "Aucune requete n'a ete envoyee."
                 % (url, ', '.join(MOTS_TEST)))
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
    return json.load(urllib.request.urlopen(req, timeout=60))['result'][0]


# -------------------------------------------------------------- appariement
def deduire_annee(libelle, annee_entete, date_commande):
    """Meme regle que _deduire_annee dans l'assistant, dans le meme ordre."""
    trouvees = set(ANNEE_DANS_LIBELLE.findall(libelle or ''))
    if len(trouvees) == 1:
        return int(trouvees.pop())
    if annee_entete:
        return int(annee_entete)
    if len(trouvees) > 1:
        # Plusieurs annees dans un meme libelle : ambigu a dessein. Mieux vaut
        # laisser l'equipe trancher que placer la ligne au mauvais endroit.
        return 0
    if date_commande:
        return int(str(date_commande)[:4])
    return 0


def choisir_contrat(contrats, tmpl_article):
    """Un seul contrat, ou un seul portant le bon article. Sinon : arbitrage."""
    if len(contrats) == 1:
        return contrats[0], ''
    exacts = [c for c in contrats
              if (c['product_id'] or [0])[0] == tmpl_article]
    if len(exacts) == 1:
        return exacts[0], ''
    return None, ('%d contrats pour cet etablissement, %d avec le bon article'
                  % (len(contrats), len(exacts)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true',
                    help="Ecrit en base. Sans ce drapeau : passage a blanc.")
    ap.add_argument('--depuis', type=int, default=2026,
                    help="Annee minimale couverte (defaut 2026).")
    ap.add_argument('--url')
    ap.add_argument('--production', metavar='JETON')
    args = ap.parse_args()

    cfg = json.load(io.open(CONFIG, encoding='utf-8'))
    user = cfg['username']
    pwd = cfg.get('password') or cfg.get('api_key')
    url = args.url.rstrip('/') if args.url else cfg['url']

    if args.production:
        verifier_production(url, args.production)
        db = resoudre_base(url)
        if not re.match(MOTIF_BASE_PRODUCTION, db):
            sys.exit('STOP : base %r inattendue pour la production (motif %r).'
                     % (db, MOTIF_BASE_PRODUCTION))
        print('>> ENVIRONNEMENT : *** PRODUCTION *** -- Base : %s' % db)
    else:
        verifier_url(url, cfg)
        db = resoudre_base(url)
        motif = cfg.get('database_pattern') or MOTIF_BASE_DEFAUT
        if not re.match(motif, db):
            sys.exit('STOP : base %r hors du motif de test %r.' % (db, motif))
        print('>> ENVIRONNEMENT : TEST -- Base : %s' % db)
    print('>> MODE          : %s' % ('ECRITURE (--apply)' if args.apply
                                     else 'PASSAGE A BLANC (lecture seule)'))
    print('>> PERIMETRE     : devis couvrant %d et au-dela\n' % args.depuis)

    uid = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common').authenticate(
        db, user, pwd, {})
    if not uid:
        sys.exit('STOP : authentification refusee.')
    models = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object',
                                       allow_none=True)

    def call(model, method, *a, **kw):
        # lang explicite : sans lui Odoo repond en en_US, ou les articles
        # portent encore leurs noms d'avant septembre 2025.
        kw.setdefault('context', {})['lang'] = 'fr_FR'
        return models.execute_kw(db, uid, pwd, model, method, list(a), kw)

    # ---- 1. Le catalogue d'Assistance -----------------------------------
    articles = call('product.product', 'search_read',
                    [('name', 'ilike', 'Assistance')],
                    fields=['name', 'product_tmpl_id'],
                    context={'active_test': False, 'lang': 'fr_FR'})
    tmpl_par_variante = {a['id']: (a['product_tmpl_id'] or [0])[0]
                         for a in articles}
    print('articles d Assistance            : %d' % len(articles))

    # ---- 2. Les contrats, par etablissement ------------------------------
    contrats = call('eurekam.maintenance.contract', 'search_read',
                    [('state', 'not in', ['cancelled'])],
                    fields=['sequence_number', 'partner_id', 'product_id'])
    par_partenaire = defaultdict(list)
    for c in contrats:
        par_partenaire[(c['partner_id'] or [0])[0]].append(c)
    annuelles = call('eurekam.maintenance.contract.line', 'search_read',
                     [('contract_id', 'in', [c['id'] for c in contrats])],
                     fields=['contract_id', 'year', 'amount'])
    annuelle_par_cle = {((a['contract_id'] or [0])[0], a['year']): a
                        for a in annuelles}
    print('contrats vivants                 : %d' % len(contrats))

    # ---- 3. Les lignes de commande candidates ----------------------------
    lignes = call('sale.order.line', 'search_read',
                  [('product_id', 'in', list(tmpl_par_variante)),
                   ('order_id.state', '!=', 'cancel')],
                  fields=['order_id', 'product_id', 'name', 'price_subtotal',
                          'maintenance_line_id'])
    cmd_ids = sorted({(l['order_id'] or [0])[0] for l in lignes})
    entetes = {o['id']: o for o in call(
        'sale.order', 'search_read', [('id', 'in', cmd_ids)],
        fields=['name', 'partner_id', 'date_order', 'state',
                'eurekam_maintenance_contract_id', 'eurekam_maintenance_year'])}
    print('lignes d Assistance vivantes     : %d sur %d commandes\n'
          % (len(lignes), len(entetes)))

    # ---- 4. Classement ----------------------------------------------------
    # Qui couvre deja quelle annee ? (lignes rattachees existantes)
    occupee_par = {}
    for l in lignes:
        if l['maintenance_line_id']:
            occupee_par.setdefault((l['maintenance_line_id'] or [0])[0],
                                   set()).add((l['order_id'] or [0])[0])

    propositions = defaultdict(list)       # id ligne annuelle -> [lignes cmd]
    rapport = []

    def noter(statut, motif, l, o, annee=0, contrat=None, annuelle=None):
        # `ecart` est volontairement laisse vide ici : une commande decoupe
        # souvent l'annee en 2 ou 4 lignes de periode, et comparer UNE ligne
        # au montant de l'annee entiere ferait crier au loup sur chaque devis
        # trimestriel. Il est calcule plus bas sur le TOTAL des lignes
        # rattachees a la meme annee, seule comparaison qui ait un sens.
        rapport.append({
            'statut': statut,
            'motif': motif,
            'devis': o['name'] if o else '',
            'etat_devis': o['state'] if o else '',
            'date_commande': (o or {}).get('date_order') or '',
            'etablissement': ((o or {}).get('partner_id') or [0, ''])[1],
            'article': (l['product_id'] or [0, ''])[1],
            'libelle_ligne': (l['name'] or '').replace('\n', ' | ')[:160],
            'montant_ligne': round(l['price_subtotal'], 2),
            'annee_deduite': annee or '',
            'contrat': contrat['sequence_number'] if contrat else '',
            'annee_contrat': annuelle['year'] if annuelle else '',
            'montant_annee': round(annuelle['amount'], 2) if annuelle else '',
            'total_lignes_annee': '',
            'ecart': '',
            'id_ligne_commande': l['id'],
            'id_ligne_annuelle': annuelle['id'] if annuelle else '',
        })

    for l in lignes:
        o = entetes.get((l['order_id'] or [0])[0])
        if not o:
            continue
        if l['maintenance_line_id']:
            noter('DEJA_RATTACHEE', '', l, o)
            continue
        annee = deduire_annee(l['name'], o['eurekam_maintenance_year'],
                              o['date_order'])
        if not annee:
            # Un libelle portant plusieurs annees, toutes anterieures a la
            # borne, n'est pas « illisible » : il est simplement hors
            # perimetre. Le distinguer evite de gonfler la pile a relire avec
            # des lignes de 2021 que personne ne rattachera jamais.
            vues = {int(a) for a in ANNEE_DANS_LIBELLE.findall(l['name'] or '')}
            if vues and max(vues) < args.depuis:
                noter('HORS_PERIMETRE',
                      'libelle couvrant %s, borne a %d'
                      % ('-'.join(str(a) for a in sorted(vues)), args.depuis),
                      l, o)
            else:
                noter('ANNEE_ILLISIBLE',
                      'aucune annee deductible du libelle ni de la commande',
                      l, o)
            continue
        if annee < args.depuis:
            noter('HORS_PERIMETRE', 'couvre %d, borne a %d'
                  % (annee, args.depuis), l, o, annee)
            continue
        lot = par_partenaire.get((o['partner_id'] or [0])[0], [])
        if not lot:
            noter('SANS_CONTRAT',
                  'aucun contrat en base pour cet etablissement', l, o, annee)
            continue
        contrat, motif = choisir_contrat(
            lot, tmpl_par_variante.get((l['product_id'] or [0])[0]))
        if not contrat:
            noter('ARBITRAGE', motif, l, o, annee)
            continue
        annuelle = annuelle_par_cle.get((contrat['id'], annee))
        if not annuelle:
            noter('ANNEE_ABSENTE_DU_CONTRAT',
                  'le contrat ne porte pas de ligne %d' % annee,
                  l, o, annee, contrat)
            continue
        autres = occupee_par.get(annuelle['id'], set()) - {o['id']}
        if autres:
            noter('DEJA_COUVERTE',
                  'annee deja couverte par une autre commande',
                  l, o, annee, contrat, annuelle)
            continue
        propositions[annuelle['id']].append((l, o, contrat, annuelle))

    # Conflit a l'interieur du lot : deux commandes differentes visant la
    # meme annee. Aucune des deux n'est evidente, les deux partent en
    # arbitrage.
    for aid, lot in propositions.items():
        cmds = {o['id'] for _l, o, _c, _a in lot}
        if len(cmds) > 1:
            noms = ', '.join(sorted({o['name'] for _l, o, _c, _a in lot}))
            for l, o, c, a in lot:
                noter('ARBITRAGE',
                      'plusieurs devis visent la meme annee : %s' % noms,
                      l, o, a['year'], c, a)
        else:
            for l, o, c, a in lot:
                noter('PRET', '', l, o, a['year'], c, a)

    # ---- 4bis. Ecart calcule sur le TOTAL d'une annee --------------------
    # Une commande decoupe souvent l'annee selon la cadence : 4 lignes
    # trimestrielles de 6 300 EUR face a une annee de 25 200 EUR ne sont pas
    # un ecart, c'est la meme somme. Seul le total a un sens.
    totaux = defaultdict(float)
    for r in rapport:
        if r['statut'] == 'PRET':
            totaux[r['id_ligne_annuelle']] += r['montant_ligne']
    for r in rapport:
        if r['statut'] == 'PRET':
            total = round(totaux[r['id_ligne_annuelle']], 2)
            r['total_lignes_annee'] = total
            r['ecart'] = round(total - float(r['montant_annee']), 2)

    # ---- 5. Synthese ------------------------------------------------------
    compte = defaultdict(int)
    montant = defaultdict(float)
    for r in rapport:
        compte[r['statut']] += 1
        montant[r['statut']] += r['montant_ligne']
    print('--- Classement des %d lignes ---' % len(rapport))
    for statut in sorted(compte, key=lambda s: -compte[s]):
        print('  %-26s %5d   %12.2f EUR'
              % (statut, compte[statut], montant[statut]))

    prets = [r for r in rapport if r['statut'] == 'PRET']
    print('\n  devis concernes par les PRET : %d'
          % len({r['devis'] for r in prets}))

    # Le controle qui compte : le total rattache a une annee colle-t-il au
    # montant de cette annee ?
    seaux = defaultdict(int)
    for aid, total in totaux.items():
        ref = next(float(r['montant_annee']) for r in prets
                   if r['id_ligne_annuelle'] == aid)
        ecart = abs(round(total, 2) - ref)
        if ecart < 0.01:
            seaux['au centime pres'] += 1
        elif ref and ecart / ref < 0.05:
            seaux['moins de 5 %'] += 1
        else:
            seaux['A VERIFIER (plus de 5 %)'] += 1
    print('\n  --- Annees couvertes : total devis vs montant de l annee ---')
    for k in ('au centime pres', 'moins de 5 %', 'A VERIFIER (plus de 5 %)'):
        if seaux.get(k):
            print('    %-26s %3d annee(s)' % (k, seaux[k]))

    # ---- 6. Fichier de relecture -----------------------------------------
    os.makedirs(os.path.dirname(RELECTURE), exist_ok=True)
    with io.open(RELECTURE, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=ENTETES, delimiter=';')
        w.writeheader()
        ordre = {'ARBITRAGE': 0, 'SANS_CONTRAT': 1,
                 'ANNEE_ABSENTE_DU_CONTRAT': 2, 'DEJA_COUVERTE': 3,
                 'ANNEE_ILLISIBLE': 4, 'PRET': 5, 'HORS_PERIMETRE': 6,
                 'DEJA_RATTACHEE': 7}
        for r in sorted(rapport, key=lambda x: (ordre.get(x['statut'], 9),
                                                x['etablissement'],
                                                x['devis'])):
            w.writerow(r)
    print('\nfichier de relecture : %s' % RELECTURE)

    if not args.apply:
        print('\nPassage a blanc termine. Rien n a ete ecrit.')
        print('Relisez le fichier, puis relancez avec --apply.')
        return

    # ---- 7. Ecriture ------------------------------------------------------
    print('\n--- Ecriture des %d lignes PRET ---' % len(prets))
    for i in range(0, len(prets), 50):
        lot = prets[i:i + 50]
        for r in lot:
            call('sale.order.line', 'write', [r['id_ligne_commande']], {
                'maintenance_line_id': r['id_ligne_annuelle'],
                'maintenance_kind': 'contract',
                # maintenance_period_label laisse VIDE a dessein : c'est la
                # cle sur laquelle _sync_vers_devis redecoupe une annee. Vide,
                # le module ne reecrira jamais un devis qu'un hopital a deja
                # recu signe.
            }, context={'eurekam_sync': True, 'lang': 'fr_FR'})
        print('  %d / %d' % (min(i + 50, len(prets)), len(prets)))

    # ---- 8. En-tete, seulement quand il ne ment pas ----------------------
    print('\n--- En-tetes ---')
    poses = 0
    for nom_devis in sorted({r['devis'] for r in prets}):
        o = next((e for e in entetes.values() if e['name'] == nom_devis), None)
        if not o or o['eurekam_maintenance_contract_id']:
            continue
        lignes_o = call('sale.order.line', 'search_read',
                        [('order_id', '=', o['id']),
                         ('maintenance_line_id', '!=', False)],
                        fields=['maintenance_line_id'])
        ids_annuelles = [(l['maintenance_line_id'] or [0])[0]
                         for l in lignes_o]
        details = call('eurekam.maintenance.contract.line', 'read',
                       ids_annuelles, fields=['contract_id', 'year'])
        ctrs = {(d['contract_id'] or [0])[0] for d in details}
        if len(ctrs) != 1:
            # Un devis couvrant plusieurs contrats garde un en-tete vide :
            # un Many2one ne sait pas porter trois contrats (cas Mondor).
            continue
        ans = {d['year'] for d in details}
        call('sale.order', 'write', [o['id']], {
            'eurekam_maintenance_contract_id': ctrs.pop(),
            'eurekam_maintenance_year': ans.pop() if len(ans) == 1 else 0,
        })
        poses += 1
    print('  %d en-tete(s) renseigne(s)' % poses)
    print('\nTermine.')


if __name__ == '__main__':
    main()
