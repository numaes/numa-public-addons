# Odoo 18 Polymorphic Inheritance (numa_poly)

This module introduces a powerful polymorphic inheritance mechanism for Odoo 18, enabling models to inherit fields, logic, and behaviors from multiple parent models while maintaining a single, unified identity (shared ID) in the database.

## Overview

Unlike standard Odoo inheritance (`_inherit` or `_inherits`), `numa_poly` allows for a **true polymorphic architecture**. It enables a "one model per concrete class" strategy where a single business instance is composed of multiple model components, all sharing the same primary key.

### Key Technical Features

*   **Multiple Polymorphic Inheritance**: Inherit from several base models simultaneously using the `_depend_models` attribute.
*   **Shared ID Space**: Records share the same ID across the entire inheritance hierarchy (Base -> Concrete).
*   **Automatic Field Injection**: All fields from base models are automatically injected into child models as `related` fields, making them transparently accessible for reading and writing.
*   **Legacy Record Support**: Seamlessly handle records that existed before polymorphic conversion, with automatic fallback mechanisms.
*   **Atomic Creation**: Guaranteed ID consistency during record creation across all base and concrete tables.
*   **Audit Consistency**: Metadata (create/write uid/date) is automatically synchronized via the `ir.poly_base` central registry.

## Installation & Upgrade

1.  Place the `numa_poly` module in your Odoo addons directory.
2.  Restart the Odoo server.
3.  Navigate to **Apps**, update the list, and install/upgrade `numa_poly`.

## Core Concept: The `ir.poly_base` Registry

Every polymorphic record is registered in `ir.poly_base`. This table stores the minimal metadata required to identify the concrete implementation of a record:

| id | concrete_model_id | create_uid | write_uid | create_date | write_date |
|----|-------------------|------------|-----------|-------------|------------|
| 101| project.task      | 2          | 2         | 2025-01-01  | 2025-01-01 |

The `id` here is the same `id` used in `project_task` and all its base model tables.

## Quick Example

To implement polymorphic inheritance, define the `_depend_models` dictionary in your class:

```python
from collections import OrderedDict
from odoo import models, fields

class ProjectBase(models.Model):
    _name = 'project.base'
    _depend_models = OrderedDict() # Mark as polymorphic base
    
    code = fields.Char('Internal Code')

class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task']
    
    # Inject ProjectBase into ProjectTask
    _depend_models = OrderedDict([
        ('project.base', 'project_base_id'),
    ])
    
    # 'code' is now automatically available here as a related field
```

## Backward Compatibility

`numa_poly` is designed to be adopted in existing databases without massive data migrations:

*   **Transparent Navigation**: The system automatically detects "legacy" records (those without an entry in `ir.poly_base`).
*   **Safe Fallback**: Methods like `as_concrete_model()` will return the current record if no more specific representation is found.
*   **No Interference**: Standard Odoo models remain unaffected.

## Benefits for Developers

*   **UML-Driven Design**: Directly implement complex UML class diagrams in Odoo.
*   **Decoupled Logic**: Separate self-contained behaviors (like State Machines or Versioning) into reusable polymorphic bases.
*   **Clean API**: Access inherited fields as if they were local, without manual Many2one traversal or `related` field boilerplate.

---
**Disclaimer**: This module performs low-level monkey patching on Odoo's `BaseModel`. While thoroughly tested for Odoo 18, it should be used with appropriate caution in mission-critical environments.

Maintained by **NUMA Extreme Systems** <info@numaes.com>
