{
    'name': 'Numa Synch AI Assisted',
    'version': '18.0.1.0.0',
    'summary': 'AI-assisted schema adaptation for synchronization with non-Odoo systems',
    'description': """
        Numa Synch AI Assisted Module
        ============================
        
        This module extends the Numa Synch synchronization system with AI-assisted
        schema adaptation capabilities. When standard metadata validation fails
        (e.g., connecting to non-Odoo systems or modified schemas), this module
        uses AI to generate transformation maps.
        
        Features:
        - Automatic schema mapping using AI
        - Cached transformation maps for performance
        - Gap analysis logging for unresolved issues
        - Dynamic payload transformation
    """,
    'author': 'Gustavo Marino <gamarino@numaes.com>',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'numa_synch',
        'numa_ai',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/numa_synch_ai_map_views.xml',
        'views/numa_synch_issue_views.xml',
    ],
    'installable': True,
    'application': False,
}
