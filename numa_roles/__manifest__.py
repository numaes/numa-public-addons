# -*- coding: utf-8 -*-
{
    'name': 'Numa Roles',
    'version': '18.0.1.0.0',
    'summary': 'RBAC (Role-Based Access Control) system for Odoo',
    'description': """
Numa Roles - RBAC System
=========================

This module implements a strict RBAC (Role-Based Access Control) architecture
on top of Odoo's native res.groups model, separating the concepts of "Roles"
and "Permissions" while maintaining technical compatibility.

Architecture:
-------------
* **Permissions**: Atomic access units (e.g., 'perm_approve_discount'). 
                  Not assigned directly to users.
* **Roles**: Collections of permissions (e.g., 'role_sales_manager'). 
            Assigned to users.
* **System**: Native Odoo groups (Legacy).

Key Features:
-------------
* Separation of Roles and Permissions
* Technical code for permissions (immutable, unique)
* Template flag to distinguish system vs user-created roles
* Constraints to enforce RBAC rules:
  - Permissions cannot have users assigned
  - Permissions cannot inherit from roles
* Conditional views based on type
* Menu structure for easy management
    """,
    'author': 'NUMA Extreme Systems',
    'website': 'https://www.numaes.com',
    'license': 'LGPL-3',
    'category': 'Security',
    'depends': [
        'base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/res_groups_views.xml',
        'data/security_demo.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
