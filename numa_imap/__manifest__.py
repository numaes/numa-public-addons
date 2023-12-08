{
    'name': 'NUMA IMAP',
    'author' : 'Numa Extreme Systems',
    'category' : 'Specific Numa Applications',
    'description': """
NUMA IMAP extension
===================
    * Leave read mails from IMAP servers as unread on server
""",
	'summary': "IMAP extension",
    'version': '1.0',
    'depends': ['base','fetchmail'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/fetchmail_views.xml',
    ],
    'auto_install': False,
    'application': False,
    'installable': False,
    'license': 'LGPL-3',
}
