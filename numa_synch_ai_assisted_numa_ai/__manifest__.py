# -*- coding: utf-8 -*-
{
    'name': 'Numa Synch AI Assisted - numa_ai bridge',
    'version': '20.0.1.0.0',
    'summary': 'Lets numa_synch_ai_assisted ask numa_ai to analyse a schema mismatch',
    'description': """
Numa Synch AI Assisted - numa_ai bridge
=======================================

`numa_synch_ai_assisted` knows what to ask an AI and what to do with the answer: the
schema it reads, the prompt it builds, the transformation map it caches, the gap report
it logs. It does not know **who** answers, and it does not depend on any particular
provider -- a database without one still installs it and uses its cached and
hand-written maps.

This module is the wire. It implements the provider seam `_ask_llm` on top of
`numa.ai.engine`, and nothing else.

It installs itself as soon as both sides are present (`auto_install`), and it is the
only place that names `numa_ai`.
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'numa_synch_ai_assisted',
        'numa_ai',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': True,
}
