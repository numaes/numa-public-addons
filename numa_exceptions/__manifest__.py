# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems.
#  
#    Copyright (C) 2013 NUMA Extreme Systems (<http:www.numaes.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
{
    'name': 'NUMA Exceptions',
    'author': 'Numa Extreme Systems',
    'website': 'https://www.numaes.com',
    'category': 'Technical Settings',
    'version': '20.0.1.0.0',
    'license': 'LGPL-3',
    'summary': 'Advanced Exception Logging and Traceability',
    'description': """
NUMA Exceptions
===============
This module provides a robust infrastructure for capturing, persisting, and analyzing 
system exceptions directly within the Odoo database.

Key Features:
-------------
* **Persistent Logging:** Exception information is stored in the database, allowing 
  historical analysis even after server restarts.
* **Detailed Traceability:** Records the complete stack trace, including source code 
  snippets, local variable values, and method parameters for each frame.
* **Automatic Capture:** Hooks ``ir.http._handle_error`` and ``ir.cron._callback``,
  so unhandled exceptions of every dispatcher (HTTP, JSON-RPC and JSON2) and of every
  scheduled action are logged.
* **User Support:** When an error occurs, the user is provided with a unique exception 
  reference ID to facilitate communication with system administrators.
* **Online Inspection:** Administrators can view detailed error reports directly 
  through the Odoo interface without needing direct server or log file access.
* **Automatic Decorator:** Easy-to-use `@exception_managed` decorator for models 
  to automate traceability with minimal code changes.
* **Retention Policy:** A daily cron purges old exception records. The retention
  period defaults to 30 days and is set with the ``numa_exceptions.retention_days``
  system parameter; 0 disables the purge.

Technical Information:
----------------------
The module uses a separate database cursor for logging, ensuring that exception
details are persisted even if the main transaction is rolled back.

Migrated to Odoo 20.0. See README.md for the list of API changes.
""",
    'depends': ['mail'],
    'data': [
        'security/ir.access.csv',
        'views/exceptions_views.xml',
        'views/menu_views.xml',
        'data/exceptions_data.xml',
    ],
    'auto_install': False,
    'application': False,
}
