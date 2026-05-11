{
    'name': 'Eurekam - Suivi Contrats de Maintenance',
    'version': '18.0.1.0.0',
    'category': 'Sales/Maintenance',
    'summary': 'Gestion du cycle de vie des contrats de maintenance Drugcam',
    'description': """
Suivi des contrats de maintenance Eurekam
=========================================

Module de gestion du cycle de vie des contrats de maintenance Drugcam :
contrats multi-annuels, revision Syntec, cadences de facturation,
alertes d'expiration, suivi par etablissement.

Ce module remplace le suivi actuellement fait dans Notion.
""",
    'author': 'Eurekam',
    'website': 'https://www.eurekam.fr',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'product',
        'contacts',
    ],
    'data': [
        'security/maintenance_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'views/maintenance_contract_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
