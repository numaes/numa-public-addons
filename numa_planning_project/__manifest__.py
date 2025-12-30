{
    'name': 'Numa Planning - Project Bridge',
    'version': '18.0.1.0.0',
    'summary': 'Bridge module. Automaps Project Tasks to Numa Planning Nodes.',
    'description': """
Numa Planning - Project Bridge
==============================
This module integrates standard Odoo Project Tasks with the Numa Planning Engine.
It uses polymorphic inheritance to make each Task a Planning Node, enabling
advanced scheduling, CPM, and resource leveling for projects.

Key Features:
- Automatic mapping of Task Deadlines to Planning Constraints.
- Synchronization of Planned Hours with Planning Effort.
- Feedback of calculated planning dates back to Project Tasks.
- Integration of the Planning Engine interface within the Task form.
- Automated dependency synchronization.
    """,
    'category': 'Services/Project',
    'author': 'Numa',
    'website': 'https://numa.com',
    'license': 'AGPL-3',
    'depends': [
        'project',
        'numa_planning',
    ],
    'data': [
        'views/project_task_views.xml',
    ],
    'demo': [
        'data/demo.xml',
    ],
    'auto_install': True,
    'installable': True,
}
