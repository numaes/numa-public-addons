# -*- coding: utf-8 -*-
{
    'name': 'Mail Messages Easy.'
            ' Show all messages, Show sent messages, Reply to message, Edit message, Forward message, Quote message, Move message'
            ' Email client style for messages views and more',
    'version': '13.0.6.3',
    'summary': """Read and manage all Odoo messages in one place!""",
    'author': 'Ivan Sokolov, Cetmix',
    'category': 'Discuss',
    'license': 'LGPL-3',
    'website': 'https://cetmix.com',
    'description': """
 Show all messages, Show sent message, Reply to messages, Forward messages, Edit messages, Delete messages, Move messages, Quote messages
""",
    'depends': ['base', 'mail'],
    'live_test_url': 'https://demo.cetmix.com',
    'images': ['static/description/banner.png'],

    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/rules.xml',
        'views/prt_mail.xml',
        'views/mail_assign.xml',
        'views/conversation.xml',
        'views/partner.xml',
        'views/message_edit.xml',
        'views/res_config_settings.xml',
        'views/actions.xml',
        'views/templates.xml',
        'data/data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False
}
