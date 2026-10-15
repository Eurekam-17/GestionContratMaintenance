# -*- coding: utf-8 -*-
"""Import des contrats de maintenance Notion -> Odoo SANDBOX.

Perimetre arrete avec Loic :
  - France uniquement (les 17 contrats etrangers feront un second lot) ;
  - contrats sans aucun montant annuel ecartes (11 coquilles vides) ;
  - creation en BROUILLON : Notion ne porte pas de reference article, et le
    module exige un product_id pour activer. Rien n'est invente.
  - le contrat rattache a deux ICO va sur ICO Angers.

Les lignes annuelles sont creees DIRECTEMENT depuis les colonnes 2023-2030 de
Notion, et non via action_generate_lines : 46 contrats portent des montants hors
de leurs propres dates, qui seraient silencieusement perdus.

Tracabilite : chaque contrat cree recoit un ir.model.data sous le module
`eurekam_migration_notion`, ce qui rend l'import rejouable (--purge) et
identifie sans ambiguite ce qui vient de la migration.

Usage :
    python migration/importer_contrats.py --dry-run      # n'ecrit rien
    python migration/importer_contrats.py --limit 5      # echantillon
    python migration/importer_contrats.py                # tout
    python migration/importer_contrats.py --purge        # efface puis reimporte
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import xmlrpc.client

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(BASE), 'config', 'odoo_test.json')
CORRESP = os.path.join(BASE, 'correspondance_etablissements.csv')
VALID = os.path.join(BASE, 'validation_etablissements.csv')
CONTRATS = os.path.join(
    BASE, 'Assistance DO 79ad412a774a4b35addf604d357bdf28_all.csv')
JOURNAL = os.path.join(BASE, 'journal_import.csv')

MODULE_MIGRATION = 'eurekam_migration_notion'
ANNEES = [str(a) for a in range(2023, 2031)]

# ------------------------------------------------------------------ mappings
# Codes de la liste editable eurekam.product.generation.
GEN = {'GEN1': 'gen1', 'GEN2': 'gen2', 'UpGrade GEN2': 'upgrade_gen2'}
STATUT = {
    'Reçue': 'received',
    'Facturation sans BC': 'no_po',
    'Suspendu': 'suspended',
    'Déploiement': 'deploying',
    'BC demandé': 'pending',
    'En cours': 'pending',
}
DUREE = {'6 mois': '6m', '1 an': '1y', '2 ans': '2y', '3 ans': '3y',
         '4 ans': '4y', '5 ans': '5y'}
MARCHE = {'UniHA 2019': 'UniHA 2019', 'UniHA 2021': 'UniHA 2021',
          'UniHA 2023': 'UniHA 2023', 'UniHA 2024': 'UniHA 2024',
          'UniHA 2025': 'UniHA 2025', 'Ageps': 'AGEPS',
          'Marché interne': 'Internal Market', 'Privé': 'Private',
          'Distributeur': 'Distributor'}
CADENCE = {'Annuelle': 'annual', 'échu': 'overdue', 'échoir': 'upcoming',
           'Période intégrale': 'full_period', 'Semestrielle': 'semi_annual',
           'Trimestrielle': 'quarterly'}
MODULE_FACT = {
    'gratuit (valorisé)': 'Free (valued)',
    'Facturation Module Statistique': 'Statistics Module Billing',
    'Facturation Module Essai Clinique': 'Clinical Trial Module Billing',
    'Aucun module': 'No module',
}
NIVEAU = {'100%': '100', '75%': '75', '50%': '50', '25%': '25', '0%': '0'}
COMMERCIAL = {'Paul Geeregat': 'Paul GEEREGAT',
              'Benoît Tamarelle': 'Benoit TAMARELLE',
              'Jean Chrapecki': 'Jean CHRAPECKI',
              'Martin Leclercq': 'Martin LECLERCQ'}

# Le contrat lie a deux ICO : arbitrage de Loic -> ICO Angers.
ICO_ANGERS = '44 - ICO (Angers)'


# ------------------------------------------------------------------ outils
def montant(txt):
    if not txt:
        return None
    t = re.sub(r'[^0-9,.-]', '',
               txt.replace(' ', '').replace('\xa0', ''))
    t = t.replace('.', '').replace(',', '.') if ',' in t else t
    try:
        v = float(t)
    except ValueError:
        return None
    return v or None


def date_iso(txt):
    if not txt or not txt.strip():
        return None
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', txt.strip())
    return '%s-%s-%s' % (m.group(3), m.group(2), m.group(1)) if m else None


def noms_etab(txt):
    """Renvoie la liste des etablissements cites, sans leurs URL."""
    if not txt:
        return []
    sans_url = re.sub(r'\(https?://[^)]*\)', '\x00', txt)
    return [p.strip() for p in sans_url.split('\x00') if p.strip(' ,\t')]


def premier(txt):
    """Premiere valeur d'un rollup Notion ('Paul Geeregat,Paul Geeregat')."""
    return (txt or '').split(',')[0].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--purge', action='store_true')
    args = ap.parse_args()

    cfg = json.load(io.open(CONFIG, encoding='utf-8'))
    url, db, user = cfg['url'], cfg['database'], cfg['username']
    pwd = cfg.get('password') or cfg.get('api_key')
    if cfg.get('environment') != 'TEST' or 'sandbox' not in db:
        sys.exit('STOP : base cible inattendue (%s)' % db)
    print('>> ENVIRONNEMENT : TEST -- Base : %s%s'
          % (db, '  [DRY-RUN, aucune ecriture]' if args.dry_run else ''))

    uid = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common').authenticate(
        db, user, pwd, {})
    models = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object',
                                       allow_none=True)

    def call(model, method, *a, **kw):
        return models.execute_kw(db, uid, pwd, model, method, list(a), kw)

    # --- deja migre ? ---
    deja = call('ir.model.data', 'search_read',
                [('module', '=', MODULE_MIGRATION),
                 ('model', '=', 'eurekam.maintenance.contract')],
                fields=['res_id', 'name'])
    if deja and args.purge and not args.dry_run:
        ids = [d['res_id'] for d in deja]
        print('purge : suppression de %d contrats deja migres...' % len(ids))
        call('eurekam.maintenance.contract', 'unlink', ids)
        call('ir.model.data', 'unlink', [d['id'] for d in
             call('ir.model.data', 'search_read',
                  [('module', '=', MODULE_MIGRATION)], fields=['id'])])
        deja = []
    elif deja and not args.dry_run:
        sys.exit('STOP : %d contrats deja migres. Relancer avec --purge pour '
                 'les remplacer.' % len(deja))

    # --- referentiels Odoo ---
    marches = {r['name']: r['id'] for r in
               call('eurekam.market.type', 'search_read', [], fields=['name'])}
    cadences = {r['code']: r['id'] for r in
                call('eurekam.billing.frequency', 'search_read', [],
                     fields=['code'])}
    modfact = {r['name']: r['id'] for r in
               call('eurekam.module.billing', 'search_read', [],
                    fields=['name'])}
    generations = {r['code']: r['id'] for r in
                   call('eurekam.product.generation', 'search_read', [],
                        fields=['code'])}
    users = {}
    for notion_nom, odoo_nom in COMMERCIAL.items():
        res = call('res.users', 'search', [('name', '=', odoo_nom)], limit=1)
        if res:
            users[notion_nom] = res[0]

    # --- resolution des etablissements ---
    resolution, ecartes = {}, {}
    for l in csv.DictReader(io.open(CORRESP, encoding='utf-8-sig'),
                            delimiter=';'):
        if l['statut'] == 'CERTAIN' and l['odoo_id'].strip().isdigit():
            resolution[l['notion_nom']] = int(l['odoo_id'])
        elif l['statut'] in ('HORS PERIMETRE', 'DOUBLON NOTION'):
            ecartes[l['notion_nom']] = l['statut']
    for l in csv.DictReader(io.open(VALID, encoding='utf-8-sig'),
                            delimiter=';'):
        nom, dec = l['notion_nom'], (l.get('DECISION') or '').strip()
        pid, pnom = (l.get('proposition_id') or '').strip(), \
                    (l.get('proposition_odoo') or '').strip()
        if not dec:
            ecartes[nom] = 'SANS DECISION'
        elif dec.upper() == 'IGNORER':
            ecartes[nom] = 'IGNORE'
        elif dec == pnom and pid.isdigit():
            resolution[nom] = int(pid)
        else:
            t = call('res.partner', 'search',
                     ['|', ('public_nas_name', '=', dec), ('name', '=', dec),
                      ('is_company', '=', True)])
            if len(t) == 1:
                resolution[nom] = t[0]
            else:
                ecartes[nom] = 'DECISION AMBIGUE'

    # --- parcours des contrats ---
    lignes = list(csv.DictReader(io.open(CONTRATS, encoding='utf-8-sig')))
    journal, cree, saute = [], 0, 0

    for i, c in enumerate(lignes, 1):
        if args.limit and cree >= args.limit:
            break
        etabs = noms_etab(c.get('Etablissements ', ''))
        # Arbitrage ICO : on privilegie Angers quand les deux sont cites.
        etab = next((e for e in etabs if e == ICO_ANGERS), etabs[0] if etabs else '')
        annees = {a: montant(c.get(a)) for a in ANNEES}
        annees = {a: v for a, v in annees.items() if v}
        pays = premier(c.get('Pays') or '')

        motif = None
        if not etab:
            motif = 'aucun etablissement'
        elif etab in ecartes:
            motif = 'etablissement %s' % ecartes[etab]
        elif etab not in resolution:
            motif = ('hors France (%s)' % pays) if pays and pays != 'France' \
                else 'etablissement non resolu'
        elif not annees:
            motif = 'aucun montant annuel'
        if motif:
            saute += 1
            journal.append({'ligne': i, 'etablissement': etab, 'action': 'ECARTE',
                            'motif': motif, 'contrat': '', 'total': ''})
            continue

        debut, fin = date_iso(c.get('Début Contrat')), date_iso(c.get('Fin Contrat'))
        if debut and fin and fin < debut:
            saute += 1
            journal.append({'ligne': i, 'etablissement': etab, 'action': 'ECARTE',
                            'motif': 'date de fin anterieure au debut',
                            'contrat': '', 'total': ''})
            continue

        cad = [CADENCE[x.strip()] for x in
               (c.get('Cadence de facturation') or '').split(',')
               if x.strip() in CADENCE]
        mods = [modfact[MODULE_FACT[x.strip()]] for x in
                (c.get('Facturation Assistance module') or '').split(',')
                if x.strip() in MODULE_FACT]
        march = MARCHE.get((c.get('Marché') or '').strip())

        vals = {
            'partner_id': resolution[etab],
            'product_name': (c.get('Produit') or '').strip() or False,
            'gen_id': generations.get(
                GEN.get((c.get('GEN') or '').strip()), False),
            'order_status': STATUT.get((c.get('Status de Cde') or '').strip(), False),
            'date_start': debut or False,
            'date_end': fin or False,
            'duration': DUREE.get((c.get("Nbre d'années commandées") or '').strip(), False),
            'billing_level': NIVEAU.get((c.get('Niveau de facturation') or '').strip(), False),
            'maintenance_amount': montant(c.get('Montant de maintenance')) or 0.0,
            'syntec_revision': 'yes' if (c.get('Révision Syntec') or '').strip() == 'oui' else 'no',
            'nb_products': int(montant(c.get('Nbre de produits')) or 0),
            'comment': (c.get('Commentaire') or '').strip() or False,
            'line_ids': [(0, 0, {'year': int(a), 'amount': v})
                         for a, v in sorted(annees.items())],
        }
        if march:
            vals['market_type_ids'] = [(6, 0, [marches[march]])]
        if cad:
            vals['billing_frequency_ids'] = [(6, 0, [cadences[x] for x in cad])]
        if mods:
            vals['module_billing_ids'] = [(6, 0, sorted(set(mods)))]
        com = users.get(premier(c.get('Commercial')))
        if com:
            vals['commercial_id'] = com
        if len(etabs) > 1:
            autres = ' / '.join(e for e in etabs if e != etab)
            vals['comment'] = ((vals['comment'] or '') +
                               '\n[Migration] Notion rattachait aussi : %s' % autres).strip()

        total = round(sum(annees.values()), 2)
        if args.dry_run:
            cree += 1
            journal.append({'ligne': i, 'etablissement': etab, 'action': 'A CREER',
                            'motif': '', 'contrat': '(dry-run)', 'total': total})
            continue

        cid = call('eurekam.maintenance.contract', 'create', vals)
        call('ir.model.data', 'create', {
            'module': MODULE_MIGRATION,
            'name': 'contract_notion_%04d' % i,
            'model': 'eurekam.maintenance.contract',
            'res_id': cid,
            'noupdate': True,
        })
        seq = call('eurekam.maintenance.contract', 'read', [cid],
                   fields=['sequence_number'])[0]['sequence_number']
        cree += 1
        journal.append({'ligne': i, 'etablissement': etab, 'action': 'CREE',
                        'motif': '', 'contrat': seq, 'total': total})
        if cree % 20 == 0:
            print('   ... %d contrats crees' % cree)

    with io.open(JOURNAL, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, delimiter=';',
                           fieldnames=['ligne', 'etablissement', 'action',
                                       'motif', 'contrat', 'total'])
        w.writeheader()
        w.writerows(journal)

    print('\n--- RESULTAT ---')
    print('  contrats %s : %d' % ('a creer' if args.dry_run else 'crees', cree))
    print('  ecartes            : %d' % saute)
    tot = sum(j['total'] for j in journal if j['total'])
    print('  valeur cumulee     : %.2f EUR' % tot)
    print('  journal            : %s' % JOURNAL)


if __name__ == '__main__':
    main()
