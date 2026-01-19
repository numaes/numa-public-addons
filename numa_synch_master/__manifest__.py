{
    'name': 'Numa Synch Master',
    'version': '18.0.1.0.0',
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
        'sale',
        'stock',
        'account',
    ],
    'data': [],
    'installable': True,
    'application': False,
}
