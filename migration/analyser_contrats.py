# -*- coding: utf-8 -*-
"""Analyse a blanc de la migration Notion -> Odoo des contrats de maintenance.

N'ECRIT RIEN. Construit la table de resolution des etablissements (rapprochement
de juillet + arbitrages de Loic), la croise avec l'export des 147 contrats, et
dit precisement ce qui est importable et ce qui ne l'est pas.

Sortie : migration/rapport_analyse.csv (une ligne par contrat Notion).
"""

import csv
import io
import json
import os
import re
import xmlrpc.client

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(BASE), 'config', 'odoo_test.json')
CORRESP = os.path.join(BASE, 'correspondance_etablissements.csv')
VALID = os.path.join(BASE, 'validation_etablissements.csv')
CONTRATS = os.path.join(
    BASE, 'Assistance DO 79ad412a774a4b35addf604d357bdf28_all.csv')
RAPPORT = os.path.join(BASE, 'rapport_analyse.csv')

cfg = json.load(io.open(CONFIG, encoding='utf-8'))
URL, DB, USER = cfg['url'], cfg['database'], cfg['username']
PWD = cfg.get('password') or cfg.get('api_key')
assert cfg.get('environment') == 'TEST' and 'sandbox' in DB
print('>> ENVIRONNEMENT : TEST -- Base : %s  (LECTURE SEULE)\n' % DB)

uid = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/common').authenticate(
    DB, USER, PWD, {})
models = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/object', allow_none=True)


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, PWD, model, method, list(args), kw)


# ---------------------------------------------------------------- resolution
resolution = {}   # nom Notion -> partner_id
ecartes = {}      # nom Notion -> motif

for l in csv.DictReader(io.open(CORRESP, encoding='utf-8-sig'), delimiter=';'):
    nom, statut = l['notion_nom'], l['statut']
    if statut == 'CERTAIN' and l['odoo_id'].strip().isdigit():
        resolution[nom] = int(l['odoo_id'])
    elif statut in ('HORS PERIMETRE', 'DOUBLON NOTION'):
        ecartes[nom] = statut

# Les arbitrages de Loic priment sur le rapprochement automatique.
ambigus = []
for l in csv.DictReader(io.open(VALID, encoding='utf-8-sig'), delimiter=';'):
    nom = l['notion_nom']
    dec = (l.get('DECISION') or '').strip()
    prop_id = (l.get('proposition_id') or '').strip()
    prop_nom = (l.get('proposition_odoo') or '').strip()
    if not dec:
        ecartes[nom] = 'SANS DECISION'
    elif dec.upper() == 'IGNORER':
        ecartes[nom] = 'IGNORE PAR LOIC'
    elif dec == prop_nom and prop_id.isdigit():
        resolution[nom] = int(prop_id)
    else:
        # Decision differente du libelle propose : on resout sur le NAS ou le
        # nom exact, et on refuse de deviner si c'est ambigu.
        trouves = call('res.partner', 'search_read',
                       ['|', ('public_nas_name', '=', dec), ('name', '=', dec),
                        ('is_company', '=', True)],
                       fields=['id', 'name', 'public_nas_name'])
        if len(trouves) == 1:
            resolution[nom] = trouves[0]['id']
        else:
            ecartes[nom] = 'DECISION AMBIGUE'
            ambigus.append((nom, dec, prop_id, prop_nom, trouves))

print('etablissements resolus  : %d' % len(resolution))
print('etablissements ecartes  : %d' % len(ecartes))
for nom, motif in sorted(ecartes.items()):
    print('    %-22s %s' % (motif, nom))

if ambigus:
    print('\n!! DECISIONS A LEVER :')
    for nom, dec, pid, pnom, trouves in ambigus:
        print('   Notion   : %s' % nom)
        print('   decision : "%s"' % dec)
        print('   proposee : [%s] %s' % (pid, pnom))
        for t in trouves:
            print('     candidat [%d] nom="%s" nas="%s"'
                  % (t['id'], t['name'], t.get('public_nas_name') or '-'))

# ---------------------------------------------------------------- contrats
def montant(txt):
    """'7 989,00 €' -> 7989.0 ; vide -> None."""
    if not txt:
        return None
    t = re.sub(r'[^0-9,.-]', '', txt.replace(' ', '').replace('\xa0', ''))
    t = t.replace('.', '').replace(',', '.') if ',' in t else t
    try:
        return float(t)
    except ValueError:
        return None


def date_iso(txt):
    """'01/05/2025' -> '2025-05-01' ; vide -> None."""
    if not txt or not txt.strip():
        return None
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', txt.strip())
    return '%s-%s-%s' % (m.group(3), m.group(2), m.group(1)) if m else None


def nom_etab(txt):
    """'10 - Troyes - CH (https://...)' -> '10 - Troyes - CH'."""
    if not txt:
        return ''
    return re.sub(r'\s*\(https?://[^)]*\)\s*$', '', txt.strip()).strip()


ANNEES = [str(a) for a in range(2023, 2031)]
lignes = list(csv.DictReader(io.open(CONTRATS, encoding='utf-8-sig')))
print('\ncontrats lus : %d' % len(lignes))

stats = {'importable': 0, 'etab_non_resolu': 0, 'etab_absent': 0,
         'hors_france': 0, 'sans_montant': 0}
rapport = []
for i, c in enumerate(lignes, 1):
    etab = nom_etab(c.get('Etablissements ', ''))
    pays = (c.get('Pays') or '').strip()
    annees = {a: montant(c.get(a)) for a in ANNEES}
    annees = {a: v for a, v in annees.items() if v}
    bloquants, avertissements = [], []

    if not etab:
        bloquants.append('aucun etablissement')
        stats['etab_absent'] += 1
    elif etab in ecartes:
        bloquants.append('etablissement %s' % ecartes[etab])
        stats['etab_non_resolu'] += 1
    elif etab not in resolution:
        if pays and pays != 'France':
            bloquants.append('hors France (%s)' % pays)
            stats['hors_france'] += 1
        else:
            bloquants.append('etablissement inconnu de la table')
            stats['etab_non_resolu'] += 1

    if not annees:
        bloquants.append('aucun montant annuel')
        stats['sans_montant'] += 1

    if not date_iso(c.get('Début Contrat')):
        avertissements.append('sans date de debut')
    if not date_iso(c.get('Fin Contrat')):
        avertissements.append('sans date de fin')
    if not (c.get('Produit') or '').strip():
        avertissements.append('sans produit -> restera en brouillon')
    if not (c.get('Cadence de facturation') or '').strip():
        avertissements.append('sans cadence')

    if not bloquants:
        stats['importable'] += 1
    rapport.append({
        'ligne': i,
        'etablissement': etab,
        'pays': pays,
        'partner_id': resolution.get(etab, ''),
        'produit': (c.get('Produit') or '').strip(),
        'debut': date_iso(c.get('Début Contrat')) or '',
        'fin': date_iso(c.get('Fin Contrat')) or '',
        'annees': ' '.join('%s=%.0f' % (a, v) for a, v in sorted(annees.items())),
        'total': round(sum(annees.values()), 2) if annees else 0,
        'bloquants': ' | '.join(bloquants),
        'avertissements': ' | '.join(avertissements),
    })

with io.open(RAPPORT, 'w', encoding='utf-8-sig', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rapport[0].keys()), delimiter=';')
    w.writeheader()
    w.writerows(rapport)

print('\n--- BILAN ---')
print('  importables           : %d' % stats['importable'])
print('  bloques, dont :')
print('     etablissement non resolu : %d' % stats['etab_non_resolu'])
print('     etablissement absent     : %d' % stats['etab_absent'])
print('     hors France              : %d' % stats['hors_france'])
print('     aucun montant annuel     : %d' % stats['sans_montant'])
avert = {}
for r in rapport:
    for a in r['avertissements'].split(' | '):
        if a:
            avert[a] = avert.get(a, 0) + 1
print('  avertissements (non bloquants) :')
for a, n in sorted(avert.items(), key=lambda t: -t[1]):
    print('     %-42s %d' % (a, n))
total = sum(r['total'] for r in rapport if not r['bloquants'])
print('\n  valeur totale importable : %.2f EUR' % total)
print('  rapport detaille : %s' % RAPPORT)
