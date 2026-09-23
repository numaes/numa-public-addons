{
    'name': 'Numa Website Compatibility',
    'version': '20.0.1.0.0',
    'summary': 'Lets modules that do not depend on website upgrade on a database that has it.',
    'description': """
Odoo 20 made ``ir.ui.view.visibility`` (added by website) required, with a default
that only the ORM knows. During an upgrade, modules that do not depend on website are
loaded before it, while the registry does not know the field yet: a new view they
insert gets NULL and the upgrade aborts on the NOT NULL constraint. This module gives
the column the same default at database level. It installs itself wherever website is
installed.
""",
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Hidden',
    'depends': ['website'],
    'data': [],
    'auto_install': True,
    'installable': True,
}
