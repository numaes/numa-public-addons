# Numa Poly: Developer Implementation Guide

This guide details the practical implementation patterns and best practices for leveraging the `numa_poly` polymorphic system in Odoo 18.

## 1. Choosing Your Inheritance Strategy

| Feature | Standard `_inherit` | Numa Poly `_depend_models` |
|---------|---------------------|----------------------------|
| Purpose | Extending existing models with a few fields/methods. | Implementing complex, reusable, and independent behaviors. |
| DB Structure | Adds columns to the same table. | Separate tables sharing the same ID (Horizontal scaling). |
| Complexity | Low. | High (True polymorphic). |
| Flexibility | Rigid (linked to model identity). | Modular (pluggable behaviors). |

## 2. Core Implementation Patterns

### Pattern A: Creating a Reusable Behavioral Base
A "Behavior" is a model designed to be mixed into others. To make it pluggable, mark it as a polymorphic base.

```python
class VersioningMixin(models.Model):
    _name = 'versioning.mixin'
    _depend_models = {} # Crucial: Enables polymorphic injection
    
    version_number = fields.Integer('Version', default=1)
    
    def increment_version(self):
        self.version_number += 1
```

### Pattern B: Injecting Behaviors (Plugging in)
When a business model needs a behavior, use `_depend_models`. `numa_poly` will automatically inject all fields from the base as `related` fields.

```python
class Project(models.Model):
    _name = 'project.project'
    _inherit = ['project.project']
    
    _depend_models = {'versioning.mixin': 'versioning_id'}
    
    def some_action(self):
        # Accessing 'version_number' directly as if it were a local field
        self.increment_version()
        _logger.info(f"Project version is: {self.version_number}")
```

## 3. Advanced API Methods

### `as_concrete_model()`
In polymorphic hierarchies, you often hold a reference to a base model (e.g., `ir.poly_base` or a common base like `fsm.definition`). To access the specific logic of the final implementation:

```python
# Returns the record cast to its specific model (e.g., project.task)
concrete_record = any_base_record.as_concrete_model()
```
*Note: Includes a fallback mechanism for legacy records, returning `self` if no concrete mapping exists.*

## 4. Developer Best Practices & Troubleshooting

### Name Collision Protection
The `numa_poly` system processes the Method Resolution Order (MRO) carefully. 
*   **Warning System**: During startup, if a base model field attempts to overwrite an existing field in the child class, a `_logger.warning` is triggered.
*   **Golden Rule**: Use specific prefixes for fields in your Mixins/Behaviors (e.g., `fsm_state` instead of just `state`) to avoid collisions with standard Odoo fields.

### Related Field Limitations
Standard Odoo `related` fields defined in Python are evaluated early during registry setup. If you need to point to a field that is itself injected by `numa_poly`, Odoo might not "see" it yet.
*   **Workaround**: Use a non-stored `compute` field instead of a `related` field for these edge cases.

### Safe Field Access
Injected fields (like `self.versioning_id`) are safely accessible in any method called after record creation (`create`, `write`, actions). Avoid using them in static class-level definitions (like `domain` strings or `attrs`) unless the fields are explicitly defined in the XML views as well.

### Creation Performance
`numa_poly` guarantees atomic creation. When you call `Model.create()`, the system:
1. Generates a new ID via `ir.poly_base`.
2. Propagates this ID to all base tables.
3. Finalizes the concrete record creation.
*All within a single database transaction.*

---
For technical support or architectural consultation, contact **NUMA Extreme Systems**.
