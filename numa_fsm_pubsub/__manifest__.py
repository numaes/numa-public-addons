# -*- coding: utf-8 -*-
{
    'name': 'Numa FSM Pub/Sub',
    'version': '18.0.1.0.0',
    'summary': 'Event-Driven Architecture for FSM Instances using Pub/Sub pattern',
    'description': """
Numa FSM Pub/Sub
================

Transforms Odoo from a monolithic passive system to a reactive event-driven architecture,
allowing FSM instances to communicate asynchronously and decoupled using the Actor Model
and Pub/Sub pattern.

Key Features:
-------------
* **Actor Model**: Each `fsm.instance` acts as an Actor with identity, state, and message inbox
* **Pub/Sub Topology**: Actors publish to Topics and subscribers receive notifications
* **Schema-on-Read**: Transport mechanism doesn't validate data; validation occurs at reception
* **Asynchronous Delivery**: All message delivery is asynchronous using `numa_asynch_exec`
* **Dynamic Dispatcher**: Automatic routing to topic-specific handlers or FSM events
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': [
        'base',
        'mail',
        'numa_fsm',
        'numa_asynch_exec',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/fsm_topic_data.xml',
        'data/ir_actions_server.xml',
        'views/fsm_topic_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
