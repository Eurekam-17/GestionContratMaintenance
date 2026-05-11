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
        'data/establishment_data.xml',
        'data/billing_frequency_data.xml',
        'data/module_billing_data.xml',
        'views/establishment_config_views.xml',
        'views/billing_config_views.xml',
        'views/res_partner_views.xml',
        'views/maintenance_contract_views.xml',
        'views/maintenance_contract_line_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
