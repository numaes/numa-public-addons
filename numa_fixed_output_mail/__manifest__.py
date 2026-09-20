# -*- coding: utf-8 -*-
{
    'name': 'Fixed Output Mail (Force SMTP Sender)',
    'version': '20.0.1.0.0',
    'summary': 'Force outgoing emails to use the SMTP user as sender, preserving the '
               'display name and aligning Reply-To/Return-Path.',
    'description': """
Fixed Output Mail
=================

Adds a **Force SMTP Sender** switch to each outgoing mail server. When it is on and the
server has an ``smtp_user``, every message sent through it is rewritten so that the
technical sender is that user, while the human-readable display name is preserved:

* ``From``: keeps the display name, forces the address to ``smtp_user``.
* ``Reply-To`` and ``Return-Path``: set to ``smtp_user``.

Some providers require the ``From`` domain to match the credentials (SPF/DKIM/DMARC). If
Odoo puts an end user's personal mailbox in ``From`` while authenticating with a
departmental account, alignment and reply flows break.
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Productivity/Discuss',
    'depends': ['mail'],
    'data': [
        'views/ir_mail_server_views.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
