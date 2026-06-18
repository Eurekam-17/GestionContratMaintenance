{
    'name': 'Eurekam - Maintenance Contracts Tracking',
    'version': '18.0.2.0.0',
    'category': 'Sales/Maintenance',
    'summary': 'Lifecycle management of Drugcam maintenance contracts',
    'description': """
Eurekam maintenance contracts tracking
======================================

Module managing the lifecycle of the Drugcam maintenance contracts:
multi-year contracts, Syntec revision, billing frequencies,
expiry alerts, tracking per establishment.

This module replaces the tracking currently done in Notion.
""",
    'author': 'Eurekam',
    'website': 'https://www.eurekam.fr',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'product',
        'contacts',
        'account',
        'sale_management',
    ],
    'data': [
        'security/maintenance_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/establishment_data.xml',
        'data/billing_frequency_data.xml',
        'data/module_billing_data.xml',
        'data/market_type_data.xml',
        'data/central_purchasing_data.xml',
        'data/mail_template_data.xml',
        'data/cron_data.xml',
        'wizard/contract_renewal_wizard_views.xml',
        'wizard/maintenance_order_wizard_views.xml',
        'views/establishment_config_views.xml',
        'views/billing_config_views.xml',
        'views/res_partner_views.xml',
        'views/maintenance_contract_views.xml',
        'views/maintenance_contract_line_views.xml',
        'views/menu_views.xml',
        'report/contract_report.xml',
        'report/contract_report_templates.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
