# -*- coding: utf-8 -*-
{
    'name': 'NUMA IMAP',
    'version': '20.0.1.0.0',
    'summary': "Fetch IMAP mail by UID instead of by the read/unread flag",
    'description': """
NUMA IMAP
=========

Odoo reads an IMAP mailbox by searching for ``UNSEEN`` messages. That makes the read flag
the bookmark, and the flag belongs to everyone: a phone client, a webmail or a colleague
opening the mailbox marks messages as seen, and Odoo then skips them for good.

This module reads by **UID** instead:

* The highest processed UID is the bookmark, and it is checked against the folder's
  UIDVALIDITY so a renumbering on the server resets it rather than skipping everything.
* Messages are fetched with ``BODY.PEEK[]``, which never sets the read flag, instead of
  setting it and clearing it again.
* The ``\\All`` folder is preferred over INBOX, so mail filed away by a server-side rule
  is imported too.
* ``initially_from`` bounds the first import; left empty, the last seven days.

It also keeps a readable copy of each incoming message as a ``mail.mail`` when the server
has *Keep Original* on, and records which server brought a message in.
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Productivity/Discuss',
    # [20.0] `fetchmail` stopped being a module of its own: `fetchmail.server` lives in
    # `mail` now (mail/models/fetchmail.py).
    'depends': ['mail'],
    'data': [
        'views/fetchmail_views.xml',
    ],
    'auto_install': False,
    'application': False,
    'installable': True,
}
