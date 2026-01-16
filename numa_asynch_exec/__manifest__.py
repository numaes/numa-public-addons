{
    'name': 'Asynchronous Execution Infrastructure',
    'version': '1.0',
    'author': 'Numaes',
    'website': 'www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Technical',
    'depends': ['base', 'numa_exceptions'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
