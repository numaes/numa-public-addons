# -*- coding: utf-8 -*-
{
    'name': 'Numa Roles',
    'version': '20.0.1.0.0',
    'summary': 'Roles and permissions on top of res.groups: roles are assigned, '
               'permissions are not',
    'description': """
Numa Roles
==========

Odoo has one concept where role-based access control has two. A group both *grants*
something and *is granted* to people, so a security model written in groups says what
somebody can do only by listing every group they carry -- and nothing stops that list from
drifting into a pile that nobody can audit.

This module does not add a mechanism. Everything still runs on ``res.groups`` and
``implied_ids``, and nothing here is consulted when Odoo checks access. What it adds is a
**discipline**, and it enforces it:

* a **permission** is an atomic unit of access, carries a stable technical code, and is
  never assigned to a user directly;
* a **role** is a named bundle of permissions, and is the only thing a user gets;
* a **system** group is a native Odoo group, left alone.

And it gives that discipline an API, which is what makes it worth using:
``user.has_permission('perm_approve_discount')``. A business rule asks for a permission by
name instead of naming a group's XML id, so the security model can be rearranged without
touching the rule.
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Hidden/Tools',
    'depends': [
        'web',
    ],
    'data': [
        'views/res_groups_views.xml',
        'views/numa_roles_menus.xml',
    ],
    'demo': [
        'demo/numa_roles_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'numa_roles/static/src/components/permission_matrix/permission_matrix.scss',
            'numa_roles/static/src/components/permission_matrix/permission_matrix.js',
            'numa_roles/static/src/components/permission_matrix/permission_matrix.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
