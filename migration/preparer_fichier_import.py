# -*- coding: utf-8 -*-
"""Prepare les fichiers de relecture avant integration des contrats Notion.

Ne touche a AUCUNE base : lit l'export Notion et les fichiers de
correspondance, et ecrit dans livraison/ trois fichiers destines a l'equipe :

  contrats_a_importer.csv  ce qui sera cree, une ligne par contrat
  contrats_ecartes.csv     ce qui ne sera PAS cree, avec le motif
  points_a_valider.csv     les anomalies qui demandent une decision humaine

Le nom des partenaires Odoo est resolu sur une base de TEST, en lecture seule,
uniquement pour rendre le fichier relisible. Aucune ecriture n'est faite.

Usage :
    python migration/preparer_fichier_import.py
    python migration/preparer_fichier_import.py --url https://eurekam-recette.odoo.com
    python migration/preparer_fichier_import.py --sans-odoo   # hors ligne
"""

import argparse
import csv
import io
import json
import os
import sys
import xmlrpc.client

BASE = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(BASE)
SORTIE = os.path.join(RACINE, 'livraison')
DECISIONS = os.path.join(SORTIE, 'decisions_equipe.csv')

# On reutilise les mappings et la logique de l'import : le fichier relu doit
# decrire exactement ce que l'import fera, sinon la relecture ne sert a rien.
sys.path.insert(0, BASE)
import importlib.util

_spec = importlib.util.spec_from_file_location(
    'importeur', os.path.join(BASE, 'importer_contrats.py'))
imp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(imp)

ANNEES = [str(a) for a in range(2023, 2031)]


# charger_decisions() vit dans importer_contrats.py : les deux scripts doivent
# lire les arbitrages de la meme facon, sinon le fichier relu cesse de decrire
# ce que l'import fera.
charger_decisions = imp.charger_decisions


def charger_resolution(call):
    """Rejoue la resolution des etablissements de importer_contrats.py."""
    resolution, ecartes, qualite = {}, {}, {}
    for l in csv.DictReader(io.open(imp.CORRESP, encoding='utf-8-sig'),
                            delimiter=';'):
        nom, statut = l['notion_nom'], l['statut']
        qualite[nom] = statut
        if statut == 'CERTAIN' and l['odoo_id'].strip().isdigit():
            resolution[nom] = int(l['odoo_id'])
        elif statut in ('HORS PERIMETRE', 'DOUBLON NOTION'):
            ecartes[nom] = statut
    for l in csv.DictReader(io.open(imp.VALID, encoding='utf-8-sig'),
                            delimiter=';'):
        nom, dec = l['notion_nom'], (l.get('DECISION') or '').strip()
        pid = (l.get('proposition_id') or '').strip()
        pnom = (l.get('proposition_odoo') or '').strip()
        qualite[nom] = 'VALIDE A LA MAIN' if dec else 'SANS DECISION'
        if not dec:
            ecartes[nom] = 'SANS DECISION'
        elif dec.upper() == 'IGNORER':
            ecartes[nom] = 'IGNORE'
        elif dec == pnom and pid.isdigit():
            resolution[nom] = int(pid)
        elif call:
            t = call('res.partner', 'search',
                     ['|', ('public_nas_name', '=', dec), ('name', '=', dec),
                      ('is_company', '=', True)])
            if len(t) == 1:
                resolution[nom] = t[0]
            else:
                ecartes[nom] = 'DECISION AMBIGUE'
        else:
            ecartes[nom] = 'DECISION A RESOUDRE SUR ODOO'
    return resolution, ecartes, qualite


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', help='Base de TEST ou lire les noms de '
                                  'partenaires (lecture seule).')
    ap.add_argument('--sans-odoo', action='store_true',
                    help='Ne se connecte a aucune base.')
    args = ap.parse_args()

    cfg = json.load(io.open(os.path.join(RACINE, 'config', 'odoo_test.json'),
                            encoding='utf-8'))
    call = None
    if not args.sans_odoo:
        url = args.url.rstrip('/') if args.url else cfg['url']
        imp.verifier_url(url, cfg)
        db = imp.resoudre_base(url) if args.url else cfg['database']
        imp.verifier_base(db, cfg)
        pwd = cfg.get('password') or cfg.get('api_key')
        uid = xmlrpc.client.ServerProxy(
            url + '/xmlrpc/2/common').authenticate(db, cfg['username'], pwd, {})
        models = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object',
                                           allow_none=True)

        def call(model, method, *a, **kw):
            return models.execute_kw(db, uid, pwd, model, method, list(a), kw)

        print('>> noms de partenaires lus sur %s (base %s), en LECTURE SEULE'
              % (url, db))

    resolution, ecartes, qualite = charger_resolution(call)
    decisions = charger_decisions()
    if decisions:
        print('>> %d decision(s) d\'equipe reprises depuis %s'
              % (len(decisions), os.path.basename(DECISIONS)))

    noms_odoo = {}
    if call:
        ids = sorted(set(resolution.values()))
        for p in call('res.partner', 'read', ids, fields=['name']):
            noms_odoo[p['id']] = p['name']

    lignes = list(csv.DictReader(io.open(imp.CONTRATS, encoding='utf-8-sig')))
    a_importer, rejetes, points = [], [], []

    for i, c in enumerate(lignes, 1):
        etabs = imp.noms_etab(c.get('Etablissements ', ''))
        etab = next((e for e in etabs if e == imp.ICO_ANGERS),
                    etabs[0] if etabs else '')
        annees = {a: imp.montant(c.get(a)) for a in ANNEES}
        annees = {a: v for a, v in annees.items() if v}
        pays = imp.premier(c.get('Pays') or '')

        ref = imp.montant(c.get('Montant de maintenance')) or 0.0
        cadence_brute = (c.get('Cadence de facturation') or '')
        # Un contrat a paiement unique ("Periode integrale") n'a par
        # construction aucun montant annuel : tout est porte par le montant de
        # reference. L'ancienne regle "aucun montant annuel -> ecarte" les
        # jetait, alors que ce sont de vrais contrats -- signale par l'equipe
        # sur Rouen Becquerel (73 660 EUR) et Avignon Sainte-Catherine
        # (63 840 EUR), tous deux annotes "paiement integral".
        paiement_unique = bool(ref) and 'Période intégrale' in cadence_brute

        decision = decisions.get(i, {})
        motif = None
        if decision.get('decision') == 'ignorer':
            motif = 'ecarte par l\'equipe : %s' % (
                decision.get('statut_equipe') or 'sans motif')
        elif not etab:
            motif = 'aucun etablissement renseigne dans Notion'
        elif etab in ecartes:
            motif = 'etablissement %s' % ecartes[etab]
        elif etab not in resolution:
            motif = ('hors France (%s)' % pays) if pays and pays != 'France' \
                else 'etablissement sans correspondance Odoo certaine'
        elif not annees and not paiement_unique:
            motif = 'aucun montant annuel dans Notion'

        debut = imp.date_iso(c.get('Début Contrat'))
        fin = imp.date_iso(c.get('Fin Contrat'))
        if not motif and debut and fin and fin < debut:
            motif = 'date de fin anterieure a la date de debut'

        if motif:
            rejetes.append({
                'ligne_notion': i, 'etablissement_notion': etab,
                'pays': pays, 'produit': (c.get('Produit') or '').strip(),
                'motif': motif,
                'montant_perdu': round(sum(annees.values()), 2) or '',
                'statut_equipe': decision.get('statut_equipe', ''),
            })
            continue

        pid = resolution[etab]
        cad = [imp.CADENCE[x.strip()] for x in
               (c.get('Cadence de facturation') or '').split(',')
               if x.strip() in imp.CADENCE]
        mods = [imp.MODULE_FACT[x.strip()] for x in
                (c.get('Facturation Assistance module') or '').split(',')
                if x.strip() in imp.MODULE_FACT]

        rec = {
            'ligne_notion': i,
            'etablissement_notion': etab,
            'odoo_partner_id': pid,
            'odoo_partner_nom': noms_odoo.get(pid, '(non resolu)'),
            'qualite_correspondance': qualite.get(etab, '?'),
            'produit_notion': (c.get('Produit') or '').strip(),
            'generation': imp.GEN.get((c.get('GEN') or '').strip(), ''),
            'marche': imp.MARCHE.get((c.get('Marché') or '').strip(), ''),
            'statut_commande': imp.STATUT.get(
                (c.get('Status de Cde') or '').strip(), ''),
            'date_debut': debut or '',
            'date_fin': fin or '',
            'duree_commandee': imp.DUREE.get(
                (c.get("Nbre d'années commandées") or '').strip(), ''),
            'cadence': '+'.join(cad),
            'niveau_facturation': imp.NIVEAU.get(
                (c.get('Niveau de facturation') or '').strip(), ''),
            'montant_reference': imp.montant(
                c.get('Montant de maintenance')) or 0.0,
            'revision_syntec': 'oui' if (c.get('Révision Syntec') or '').strip()
                               == 'oui' else 'non',
            'modules_factures': '+'.join(mods),
            'nb_postes': int(imp.montant(c.get('Nbre de produits')) or 0),
            'commentaire_notion': (c.get('Commentaire') or '').strip(),
            'commercial': imp.premier(c.get('Commercial') or ''),
            'decision_equipe': decision.get('decision', ''),
            'statut_equipe': decision.get('statut_equipe', ''),
            'paiement_unique': 'oui' if paiement_unique and not annees else '',
        }
        for a in ANNEES:
            rec[a] = annees.get(a, '')
        rec['total_contrat'] = round(sum(annees.values()), 2) or (
            ref if paiement_unique else 0.0)
        a_importer.append(rec)

        # ---- points qui demandent une decision humaine ----
        if not rec['produit_notion']:
            points.append({
                'ligne_notion': i, 'etablissement': rec['odoo_partner_nom'],
                'point': 'Aucun produit',
                'detail': "Notion ne porte pas de reference article. Le contrat "
                          "sera cree en BROUILLON et ne pourra pas etre active "
                          "tant qu'un produit n'est pas choisi.",
            })
        hors = [a for a in annees
                if (debut and int(a) < int(debut[:4]))
                or (fin and int(a) > int(fin[:4]))]
        if hors:
            points.append({
                'ligne_notion': i, 'etablissement': rec['odoo_partner_nom'],
                'point': 'Montant hors periode',
                'detail': "Montants sur %s alors que le contrat court du %s au "
                          "%s. Ils seront importes tels quels."
                          % (', '.join(sorted(hors)), debut or '?', fin or '?'),
            })
        if not debut or not fin:
            points.append({
                'ligne_notion': i, 'etablissement': rec['odoo_partner_nom'],
                'point': 'Date manquante',
                'detail': 'debut=%s fin=%s' % (debut or 'VIDE', fin or 'VIDE'),
            })
        if qualite.get(etab) != 'CERTAIN':
            points.append({
                'ligne_notion': i, 'etablissement': rec['odoo_partner_nom'],
                'point': 'Correspondance etablissement a confirmer',
                'detail': "Notion : %s -> Odoo : %s (%s)"
                          % (etab, rec['odoo_partner_nom'], qualite.get(etab)),
            })
        if len(etabs) > 1:
            points.append({
                'ligne_notion': i, 'etablissement': rec['odoo_partner_nom'],
                'point': 'Plusieurs etablissements',
                'detail': "Notion rattache ce contrat a : %s. Un seul est "
                          "retenu : %s." % (' / '.join(etabs), etab),
            })

    # Plusieurs contrats sur un meme etablissement ne sont PAS une anomalie :
    # l'equipe a confirme que cela vient des reassorts et des postes places sur
    # des marches differents, et que Notion garde volontairement une ligne par
    # reassort pour en suivre la date de garantie. Ce controle a donc ete
    # retire : il produisait 9 faux positifs.

    if not os.path.isdir(SORTIE):
        os.makedirs(SORTIE)

    def ecrire(nom, lignes_, entetes):
        chemin = os.path.join(SORTIE, nom)
        with io.open(chemin, 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=entetes, delimiter=';')
            w.writeheader()
            w.writerows(lignes_)
        print('   %-28s %4d ligne(s)' % (nom, len(lignes_)))
        return chemin

    print('\n--- fichiers de relecture ---')
    entetes = ['ligne_notion', 'etablissement_notion', 'odoo_partner_id',
               'odoo_partner_nom', 'qualite_correspondance', 'produit_notion',
               'generation', 'marche', 'statut_commande', 'date_debut',
               'date_fin', 'duree_commandee', 'cadence', 'niveau_facturation',
               'montant_reference', 'revision_syntec', 'modules_factures',
               'nb_postes', 'commercial'] + ANNEES + [
                   'total_contrat', 'paiement_unique', 'decision_equipe',
                   'statut_equipe', 'commentaire_notion']
    ecrire('contrats_a_importer.csv', a_importer, entetes)
    ecrire('contrats_ecartes.csv', rejetes,
           ['ligne_notion', 'etablissement_notion', 'pays', 'produit',
            'motif', 'montant_perdu', 'statut_equipe'])
    ecrire('points_a_valider.csv', points,
           ['ligne_notion', 'etablissement', 'point', 'detail'])

    total = round(sum(r['total_contrat'] for r in a_importer), 2)
    perdu = round(sum(r['montant_perdu'] or 0 for r in rejetes), 2)
    print('\n--- synthese ---')
    print('  contrats a importer : %d  (%.2f EUR)' % (len(a_importer), total))
    print('  contrats ecartes    : %d  (%.2f EUR non repris)'
          % (len(rejetes), perdu))
    print('  points a valider    : %d' % len(points))
    sans_produit = sum(1 for r in a_importer if not r['produit_notion'])
    print('  dont sans produit   : %d contrats resteront en BROUILLON'
          % sans_produit)


if __name__ == '__main__':
    main()
