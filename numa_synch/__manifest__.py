{
    'name': 'Numa Synch',
    'version': '18.0.1.0.0',
    'summary': 'Foundational core module for offline-first synchronization system',
    'description': """
        Numa Synch Core Module
        ======================
        
        This module provides the foundational infrastructure for a distributed 
        synchronization system. It acts as a library/dependency for future modules 
        (numa_synch_master and numa_synch_slave).
        
        Features:
        - Identity mapping between local and remote IDs
        - Synchronization rules with domain filters
        - Abstract serialization engine
    """,
    'author': 'Gustavo Marino <gamarino@numaes.com>',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'base',
        'mail',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/numa_synch_map_views.xml',
        'views/numa_synch_rule_views.xml',
    ],
    'installable': True,
    'application': False,
}
