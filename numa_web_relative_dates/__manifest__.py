# -*- coding: utf-8 -*-
{
    'name': 'Numa Web Relative Dates',
    'version': '18.0.1.0.0',
    'summary': 'Makes the native relative date filter discoverable in custom search filters',
    'description': """
Numa Web Relative Dates
=======================

Odoo 18 can already build **relative** date filters that survive being saved as a favourite:
the ``within`` operator ("is within") in *Add Custom Filter* produces a domain made of
expressions, not of concrete dates::

    ["date", ">=", 'context_today().strftime("%Y-%m-%d")']
    ["date", "<=", '(context_today() + relativedelta(months=-1)).strftime("%Y-%m-%d")']

Favourites store ``ir.filters.domain`` as text and re-evaluate it on every use, so such a
filter keeps moving with the current date. The problem is not the feature, it is that nobody
finds it: the operator is called "is within" and nothing on screen says that the range is
anchored on today, or that a saved filter will be recalculated.

This module adds that missing information where the user is actually looking: a short
``from today`` marker next to the amount/unit selectors, plus a tooltip explaining that the
filter is recalculated on each run. It changes no behaviour and no stored data.

What it deliberately does NOT do
--------------------------------
It does not extend the available units. ``Within.options`` only offers days, weeks, months
and years, and that cannot be widened by simply appending to the list:

* ``relativedelta`` has no ``quarters`` keyword.
* For ``datetime`` fields the generated AST combines the shifted date with
  ``datetime.time(0, 0, 0)``, so an hour- or minute-sized delta would be silently discarded.

Both would require forking core conversion logic. See ``docs/filtros_fecha_relativa.md``.
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'AGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'web',
    ],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'numa_web_relative_dates/static/src/within_hint.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
}
