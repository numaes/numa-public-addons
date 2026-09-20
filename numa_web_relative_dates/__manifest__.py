# -*- coding: utf-8 -*-
{
    'name': 'Numa Web Relative Dates',
    'version': '20.0.1.0.0',
    'summary': 'Says out loud that a relative date filter is counted from today',
    'description': """
Numa Web Relative Dates
=======================

Odoo can build **relative** date filters that survive being saved as a favourite: the
domain is made of expressions, not of concrete dates::

    ["date", ">=", "today -1m"]
    ["date", "<=", "today"]

Favourites store ``ir.filters.domain`` as text and re-evaluate it on every use, so such a
filter keeps moving with the current date. What the editor does not say is what the range
is counted FROM, or that a saved filter will be recalculated.

This module adds that missing information where the user is actually looking: a short
``from today`` marker next to the amount/unit selectors, plus a tooltip explaining that the
filter is recalculated on each run. It changes no behaviour and no stored data.

Migrated to Odoo 20.0
---------------------

The anchor moved. Up to 18.0 the free-form relative editor was the ``within`` operator,
whose template was ``web.TreeEditor.Within``; Odoo 20 replaced it with the ``is in range``
operator plus a value type, and the editor is now ``web.TreeEditor.relativeRange``.

Odoo 20 also ships named relative presets -- *Last month*, *Year to date*, *Last 365
days* -- which are generated as smart dates and are therefore relative too, and the
free-form *Relative range* value type is ``debugOnly``. So this hint now reaches fewer
users than it did in 18.0: see the README.
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'web',
    ],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'numa_web_relative_dates/static/src/relative_range_hint.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
}
