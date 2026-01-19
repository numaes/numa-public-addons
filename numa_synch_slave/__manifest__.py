{
    'name': 'Numa Synch Slave',
    'version': '18.0.1.0.0',
    'summary': 'Slave/Branch node implementation for offline-first synchronization system',
    'description': """
        Numa Synch Slave Module
        =======================
        
        This module turns an Odoo instance into a "Branch Node" (Slave).
        It runs a scheduled job to detect local changes, serialize them,
        send them to the Master via HTTP, and process responses to update
        local mappings.
        
        Features:
        - Scheduled synchronization (configurable cron job)
        - Delta detection based on write_date
        - Dependency resolution (BFS exploration)
        - Batch processing with atomic commits
        - Automatic UUID generation for slave identification
        - Connection testing and manual sync trigger
    """,
    'author': 'Gustavo Marino <gamarino@numaes.com>',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'numa_synch',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/numa_synch_connection_views.xml',
    ],
    'installable': True,
    'application': False,
}
