# -*- coding: utf-8 -*-
"""Prepare la liste des etablissements Notion restes a trancher par Loic.

Le rapprochement de juillet (match_etablissements.py) ne comparait que le champ
`public_nas_name`. Tout partenaire Odoo sans NAS lui etait donc invisible, ce qui
explique la plupart des 13 "INTROUVABLE" : Grenoble, Nantes et Perpignan existent
bel et bien dans Odoo, mais sans NAS. On elargit donc la recherche au `name`.

LECTURE SEULE sur Odoo. Produit migration/validation_etablissements.csv, a
completer dans la colonne DECISION.
"""

import csv
import io
import json
import re
import unicodedata
import xmlrpc.client

CONFIG = r'C:\ClaudeDev\GestionContratMaintenance\config\odoo_test.json'
SOURCE = r'C:\ClaudeDev\GestionContratMaintenance\migration\correspondance_etablissements.csv'
SORTIE = r'C:\ClaudeDev\GestionContratMaintenance\migration\validation_etablissements.csv'

cfg = json.load(io.open(CONFIG, encoding='utf-8'))
URL, DB, USER = cfg['url'], cfg['database'], cfg['username']
PWD = cfg.get('password') or cfg.get('api_key')
assert cfg.get('environment') == 'TEST' and 'sandbox' in DB, 'base cible inattendue'
print('>> ENVIRONNEMENT : TEST -- Base : %s' % DB)

uid = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/common').authenticate(
    DB, USER, PWD, {})
models = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/object', allow_none=True)


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, PWD, model, method, list(args), kw)


def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


# Mots trop frequents pour discriminer un etablissement.
MOTS_VIDES = {
    'ch', 'chu', 'chr', 'chru', 'chi', 'cl', 'clcc', 'hp', 'gh', 'ght', 'gcs',
    'hia', 'pcl', 'de', 'du', 'des', 'la', 'le', 'les', 'et', 'sur',
    'hopital', 'hopitaux', 'centre', 'clinique', 'polyclinique', 'site',
    'institut', 'universitaire', 'prive', 'privee', 'groupe', 'hospitalier',
}

# Tous les partenaires societes : NAS quand il existe, nom sinon.
partenaires = call('res.partner', 'search_read',
                   [('is_company', '=', True)],
                   fields=['id', 'name', 'public_nas_name'])
print('partenaires societes charges : %d' % len(partenaires))

index = []
for p in partenaires:
    nas = (p.get('public_nas_name') or '').strip()
    index.append({
        'id': p['id'],
        'nas': nas,
        'nom': p['name'] or '',
        'n_nas': norm(nas),
        'n_nom': norm(p['name']),
    })


def candidats(notion_nom, k=3):
    """Classe les partenaires par jetons communs, en bonifiant le departement."""
    dept = notion_nom.split('-')[0].strip()
    jetons = [j for j in norm(notion_nom).split()
              if j not in MOTS_VIDES and len(j) > 2 and not j.isdigit()]
    if not jetons:
        return []
    classes = []
    for p in index:
        # On confronte le nom ET le NAS, puis on garde le meilleur des deux.
        # Les deux divergent parfois : l'Hopital Prive Nancy Lorraine porte le
        # NAS "54 - Nancy - Polyclinique de Gentilly", si bien qu'un
        # rapprochement sur le seul NAS -- celui de juillet -- le manquait.
        meilleur = None
        for champ, cible in (('nas', p['n_nas']), ('nom', p['n_nom'])):
            if not cible:
                continue
            communs = sum(1 for j in jetons if j in cible)
            if not communs:
                continue
            score = communs / float(len(jetons))
            if dept.isdigit() and cible.startswith(dept):
                score += 0.5
            if meilleur is None or score > meilleur[0]:
                meilleur = (score, communs, champ)
        if meilleur is None:
            continue
        score, communs, champ = meilleur
        p = dict(p, via=champ)
        classes.append((score, communs, p))
    classes.sort(key=lambda t: (-t[0], -t[1]))
    return classes[:k]


# Correspondances verifiees a la main : le classement automatique se trompe
# quand le departement du NAS prime sur le nom, ou quand l'orthographe differe
# entre Notion et Odoo ("Montfermeuil" / "Montfermeil", "St Anne" / "Sainte
# Anne"). Elles priment sur la proposition calculee.
VERIFIEES = {
    '35 - Saint-Malo - CH': (314, 'Centre Hospitalier de Saint-Malo'),
    '83 - Toulon - HIA St Anne': (
        552, "Hopital d'Instruction des Armees - Sainte Anne"),
    '93- Montfermeuil et Aulnay -  GHT GPNE': (
        17650, 'Groupe Hospitalier Intercommunal Le Raincy Montfermeil'),
    '69 - Lyon - GHN - Hôpital de la Croix Rousse': (
        2598, 'HCL HOP Nord - Croix Rousse'),
    '69 - Lyon - GHC - Hôpital Edouard Herriot': (
        1682, 'HCL HOPITAL E. HERRIOT'),
    '69 - Lyon - GHE - Hôpital Mère-Enfant': (
        17770, 'HCL - GHE - HOP Femme Mere Enfant'),
    '54 - Nancy - Hôpital Privé Nancy Lorraine': (
        2101, 'Hopital Prive Nancy Lorraine'),
    '66 - Perpignan - CH': (301, 'Centre Hospitalier de Perpignan'),
}

def fmt_c(c):
    lib = c[2]['nom'] if c[2].get('via') == 'nom' else (
        c[2]['nas'] or c[2]['nom'])
    return '[%d] %s' % (c[2]['id'], lib[:52])


lignes = list(csv.DictReader(io.open(SOURCE, encoding='utf-8-sig'),
                             delimiter=';'))
a_trancher = [l for l in lignes if l['statut'] in ('A VALIDER', 'INTROUVABLE')]

with io.open(SORTIE, 'w', encoding='utf-8-sig', newline='') as fh:
    w = csv.writer(fh, delimiter=';')
    w.writerow(['notion_nom', 'statut_juillet', 'proposition_id',
                'proposition_odoo', 'indice', 'alternative_1', 'alternative_2',
                'DECISION'])
    for l in a_trancher:
        nom = l['notion_nom']
        if nom in VERIFIEES:
            pid, plib = VERIFIEES[nom]
            autres = candidats(nom, 2)
            w.writerow([nom, l['statut'], pid, plib,
                        'VERIFIE A LA MAIN', fmt_c(autres[0]) if autres else '',
                        fmt_c(autres[1]) if len(autres) > 1 else '', ''])
            continue
        if l['statut'] == 'A VALIDER':
            prop_id, prop_nom = l['odoo_id'], l['odoo_nas']
            indice = 'score juillet %s' % l['score']
            autres = candidats(nom, 3)
            alts = [c for c in autres if str(c[2]['id']) != str(prop_id)][:2]
        else:
            autres = candidats(nom, 3)
            if autres:
                prop_id = autres[0][2]['id']
                prop_nom = (autres[0][2]['nom']
                            if autres[0][2].get('via') == 'nom'
                            else (autres[0][2]['nas'] or autres[0][2]['nom']))
                indice = 'retrouve par %s (%d jeton(s), score %.2f)' % (
                    autres[0][2].get('via', '?'), autres[0][1], autres[0][0])
            else:
                prop_id, prop_nom, indice = '', '', 'aucun candidat'
            alts = autres[1:3]
        w.writerow([nom, l['statut'], prop_id, prop_nom, indice,
                    fmt_c(alts[0]) if len(alts) > 0 else '',
                    fmt_c(alts[1]) if len(alts) > 1 else '', ''])

print('\necrit : %s (%d lignes a trancher)' % (SORTIE, len(a_trancher)))
sans = sum(1 for l in a_trancher
           if l['statut'] == 'INTROUVABLE' and not candidats(l['notion_nom'], 1))
print('dont sans aucun candidat : %d' % sans)
