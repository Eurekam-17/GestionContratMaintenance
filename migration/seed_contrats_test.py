# -*- coding: utf-8 -*-
"""Recree le jeu de contrats de maintenance de test sur la SANDBOX.

Couvre les 5 scenarios decrits dans CLAUDE.md (demo_data.xml) et, en plus, les
retours testeur de juillet : revision Syntec applicable a la commande, et
libelle de ligne "Libelle produit - N postes - periode".

Idempotent : un contrat portant deja le meme couple (etablissement, libelle
produit) est repris au lieu d'etre recree, pour que le script puisse etre
relance apres un rebuild sans empiler les doublons.

Tous les contrats sont assignes a l'utilisateur courant : le cron d'expiration
notifie le commercial du contrat, et on ne veut pas arroser les collegues
depuis une base de test.
"""

import json
import io
import xmlrpc.client

CONFIG = r'C:\ClaudeDev\GestionContratMaintenance\config\odoo_test.json'

cfg = json.load(io.open(CONFIG, encoding='utf-8'))
URL, DB, USER = cfg['url'], cfg['database'], cfg['username']
PWD = cfg.get('password') or cfg.get('api_key')

# --- garde-fou : jamais ailleurs que sur une base de test ---
assert cfg.get('environment') == 'TEST', 'environnement non TEST'
assert 'sandbox' in DB, 'base cible inattendue : %s' % DB
print('>> ENVIRONNEMENT : TEST -- Base : %s' % DB)

uid = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/common').authenticate(
    DB, USER, PWD, {})
models = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/object', allow_none=True)


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, PWD, model, method, list(args), kw)


FREQ = {r['code']: r['id'] for r in
        call('eurekam.billing.frequency', 'search_read', [], fields=['code'])}
MARKET = {r['name']: r['id'] for r in
          call('eurekam.market.type', 'search_read', [], fields=['name'])}
# Generation : liste editable depuis 0402bdf, plus une selection figee.
GENERATION = {r['code']: r['id'] for r in
              call('eurekam.product.generation', 'search_read', [],
                   fields=['code'])}

# product_name est saisi explicitement : le "Descriptif du devis" des articles
# est encore le meme texte copie-colle sur toute la gamme (signale a l'equipe
# commerciale), il donnerait des libelles faux sur 4 des 5 contrats.
CONTRATS = [
    {
        'cle': 'croix_rousse_gen2',
        'partner_id': 2598,          # HCL HOP Nord - Croix Rousse
        'product_id': 485,           # Assistance DRUGCAM GEN2 Oncology FR
        'product_name': 'Assistance DRUGCAM Oncology GEN2',
        'gen': 'gen2',
        'marche': 'UniHA 2024',
        'order_status': 'received',
        'date_start': '2025-01-01', 'date_end': '2027-12-31', 'duration': '3y',
        'maintenance_amount': 20000.0, 'nb_products': 4,
        'syntec_revision': 'yes', 'billing_level': '100',
        'freqs': ['quarterly', 'overdue'],
        'montants': {2025: 20000.0, 2026: 20600.0, 2027: 21218.0},
        'activer': True,
        'note': 'Actif 3 ans, trimestriel a echu, Syntec OUI -- contrat pivot '
                'pour tester la revision Syntec a la commande et le libelle '
                '"... - 4 postes - 1er trimestre 2026".',
    },
    {
        'cle': 'nice_gen1_expirant',
        'partner_id': 952,           # CHU DE NICE
        'product_id': 531,           # Assistance DRUGCAM Sterile FR
        'product_name': 'Assistance DRUGCAM Sterile GEN1',
        'gen': 'gen1',
        'marche': 'AGEPS',
        'order_status': 'received',
        'date_start': '2025-12-01', 'date_end': '2026-11-30', 'duration': '1y',
        'maintenance_amount': 8000.0, 'nb_products': 2,
        'syntec_revision': 'no', 'billing_level': '100',
        'freqs': ['semi_annual', 'upcoming'],
        'montants': {2025: 8000.0, 2026: 8000.0},
        'activer': True,
        'note': 'Expire dans ~2 mois -> doit basculer en "Expire bientot" et '
                'declencher l\'alerte du cron.',
    },
    {
        'cle': 'amiens_suspendu',
        'partner_id': 1481,          # CHU AMIENS PICARDIE
        'product_id': 507,           # Assistance Module Statistique PREMIUM FR
        'product_name': 'Assistance Module Statistique Premium',
        'gen': 'gen2',
        'marche': 'UniHA 2025',
        'order_status': 'suspended',
        'date_start': '2025-06-01', 'date_end': '2028-05-31', 'duration': '3y',
        'maintenance_amount': 22000.0, 'nb_products': 5,
        'syntec_revision': 'yes', 'billing_level': '75',
        'freqs': ['annual', 'overdue'],
        'montants': {2025: 22000.0, 2026: 22660.0, 2027: 23340.0, 2028: 24040.0},
        'activer': True,
        'module_facturable': {'module_billing_id': 5, 'amount': 2500.0,
                              'start_year': 2026},
        'note': 'Statut commande "Suspendue", niveau de facturation 75 %, '
                'et un module facturable a partir de 2026.',
    },
    {
        'cle': 'rennes_deploiement',
        'partner_id': 17513,         # CHU Rennes - Hopital Sud - Maternite
        'product_id': 486,           # Assistance DRUGCAM GEN2 Oncology UE
        'product_name': 'Assistance DRUGCAM Upgrade GEN2',
        'gen': 'upgrade_gen2',
        'marche': 'Internal Market',
        'order_status': 'deploying',
        'date_start': '2026-10-01', 'date_end': '2027-09-30', 'duration': '1y',
        'maintenance_amount': 12500.0, 'nb_products': 1,
        'syntec_revision': 'no', 'billing_level': '100',
        'freqs': ['quarterly', 'upcoming'],
        'montants': {2026: 3125.0, 2027: 9375.0},
        'activer': True,
        'note': 'En deploiement, trimestriel a echoir, 1 seul poste -> verifie '
                'le singulier "1 poste" dans le libelle.',
    },
    {
        'cle': 'caen_expire',
        'partner_id': 17443,         # CHU Caen Normandie
        'product_id': 532,           # Assistance DRUGCAM Sterile Dom Tom
        'product_name': 'Assistance DRUGCAM Legacy GEN1',
        'gen': 'gen1',
        'marche': 'UniHA 2021',
        'order_status': 'received',
        'date_start': '2023-01-01', 'date_end': '2025-12-31', 'duration': '3y',
        'maintenance_amount': 7500.0, 'nb_products': 2,
        'syntec_revision': 'yes', 'billing_level': '100',
        'freqs': ['annual', 'upcoming'],
        'montants': {2023: 7000.0, 2024: 7250.0, 2025: 7500.0},
        'activer': True,
        'note': 'Historique 2023-2025, date de fin depassee -> doit basculer '
                'automatiquement en "Expire" des l\'activation.',
    },
]

resultats = []
for spec in CONTRATS:
    existant = call('eurekam.maintenance.contract', 'search',
                    [('partner_id', '=', spec['partner_id']),
                     ('product_name', '=', spec['product_name'])], limit=1)
    if existant:
        cid = existant[0]
        print('= deja present, repris : %s' % spec['cle'])
    else:
        cid = call('eurekam.maintenance.contract', 'create', {
            'partner_id': spec['partner_id'],
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
        })
        print('+ cree : %s (id %d)' % (spec['cle'], cid))

    if spec['activer']:
        etat = call('eurekam.maintenance.contract', 'read', [cid],
                    fields=['state'])[0]['state']
        if etat == 'draft':
            call('eurekam.maintenance.contract', 'action_activate', [cid])

    call('eurekam.maintenance.contract', 'action_generate_lines', [cid])

    # Montants annuels differencies : un contrat dont toutes les annees valent
    # la meme chose ne teste ni les totaux ni le tableau de bord.
    for ligne in call('eurekam.maintenance.contract.line', 'search_read',
                      [('contract_id', '=', cid)], fields=['year', 'amount']):
        cible = spec['montants'].get(ligne['year'])
        if cible is not None and abs(ligne['amount'] - cible) > 0.01:
            call('eurekam.maintenance.contract.line', 'write',
                 [ligne['id']], {'amount': cible})

    if spec.get('module_facturable'):
        mf = spec['module_facturable']
        deja = call('eurekam.contract.module.line', 'search_count',
                    [('contract_id', '=', cid),
                     ('module_billing_id', '=', mf['module_billing_id'])])
        if not deja:
            call('eurekam.contract.module.line', 'create', dict(
                mf, contract_id=cid))

    rec = call('eurekam.maintenance.contract', 'read', [cid],
               fields=['sequence_number', 'state', 'partner_id',
                       'total_contract_value'])[0]
    resultats.append((rec['sequence_number'], rec['state'],
                      rec['partner_id'][1], rec['total_contract_value'],
                      spec['cle']))

print('\n%-18s %-10s %-34s %12s' % ('REFERENCE', 'ETAT', 'ETABLISSEMENT', 'TOTAL'))
for seq, st, part, tot, cle in resultats:
    print('%-18s %-10s %-34s %12.2f' % (seq, st, part[:34], tot))
print('\n%d contrats en place.' % len(resultats))
