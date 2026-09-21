{
    'name': 'Numa Synch Master',
    'version': '20.0.1.0.0',
    'summary': 'Master server implementation for offline-first synchronization system',
    'description': """
        Numa Synch Master Module
        ========================
        
        This module turns an Odoo instance into the "Central Server" (Master).
        It exposes API endpoints for Slaves to connect to and handles incoming
        data processing using the "Two-Phase Write" strategy to handle circular
        dependencies.
        
        Features:
        - JSON-RPC API endpoint for receiving synchronization batches
        - Two-Phase Write strategy (Skeleton + Decoration)
        - Last Write Wins (LWW) conflict resolution
        - Namespace safety (only allowed models)
        - Reference safety (graceful handling of missing references)
    """,
    'author': 'Gustavo Marino <gamarino@numaes.com>',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'numa_synch',
        # `sale`, `stock` and `account` used to be here and nothing in this module
        # refers to any of them. What the Master accepts is decided by the
        # synchronization rules, and a rule can only name a model that is installed,
        # so the three dependencies bought nothing and made the Master impossible to
        # put on a database that does not sell, stock or invoice.
    ],
    'data': [],
    'installable': True,
    'application': False,
}
