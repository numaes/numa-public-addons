{
    'name': 'Numa Synch AI Assisted',
    'version': '20.0.1.0.0',
    'summary': 'AI-assisted schema adaptation for synchronization with non-Odoo systems',
    'description': """
        Numa Synch AI Assisted Module
        ============================
        
        This module extends the Numa Synch synchronization system with AI-assisted
        schema adaptation capabilities. When standard metadata validation fails
        (e.g., connecting to non-Odoo systems or modified schemas), this module
        uses AI to generate transformation maps.
        
        Features:
        - Cached transformation maps, hand-written or AI-generated
        - Gap analysis logging for unresolved issues
        - Dynamic payload transformation
        - A provider seam: install `numa_ai` and the bridge module
          `numa_synch_ai_assisted_numa_ai` wires it in by itself
    """,
    'author': 'Gustavo Marino <gamarino@numaes.com>',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    # `numa_ai` is deliberately NOT here. This module knows what to ask an AI and what
    # to do with the answer; it does not know who answers. The provider is wired in by
    # `numa_synch_ai_assisted_numa_ai`, which installs itself when both sides are
    # present. A database without any provider still installs this one and uses its
    # cached and hand-written maps.
    'depends': [
        'numa_synch',
    ],
    'data': [
        'security/ir.access.csv',
        'views/numa_synch_ai_map_views.xml',
        'views/numa_synch_issue_views.xml',
    ],
    'installable': True,
    'application': False,
}
