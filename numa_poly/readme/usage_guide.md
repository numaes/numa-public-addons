# Numa Poly: Practical Usage Guide (Cookbook)

This guide provides practical patterns and solutions for common problems when using `numa_poly`. For architectural details, see `architecture.md`.

## 1. The Golden Rule: When to Use `numa_poly`

-   **Use standard Odoo `_inherit`:** When you want to add simple fields or methods to an existing model.
-   **Use `numa_poly` (`_depend_models`):** When you want to add a complex, self-contained "behavior" (like a state machine, versioning, etc.) to one or more models.

---

## 2. Core Patterns (Recipes)

### Pattern 1: Creating a Reusable Behavior (Polymorphic Base)

To create a behavior that other models can "plug in" (like `fsm.instance`), the base model must be part of the poly system.

**Example: `my.behavior.mixin`**
```python
class MyBehaviorMixin(models.Model):
    _name = 'my.behavior.mixin'
    # This line makes the model a polymorphic base, ready to be inherited.
    _depend_models = {} 

    my_field = fields.Char()

    def my_method(self):
        return "Behavior logic"
```

### Pattern 2: Applying a Behavior to a Model (The "Child")

To make your business model (`my.business.model`) use the behavior, you use `_depend_models`.

**Example: `my.business.model`**
```python
class MyBusinessModel(models.Model):
    _name = 'my.business.model'
    _inherit = ['my.business.model'] # Standard Odoo extension
    
    # This injects 'my.behavior.mixin' into this model.
    # 'my_behavior_id' is the name of the linking field that will be created.
    _depend_models = {'my.behavior.mixin': 'my_behavior_id'}

    # You can now access fields and methods from the mixin
    def some_action(self):
        self.my_method()
        self.my_field = "Hello"
```

---

## 3. Troubleshooting Common Errors

### Error 1: `KeyError: Field '...' referenced in related field ... does not exist.`

-   **Cause:** You are using a standard Odoo `related` field to access a field injected by `numa_poly`. Odoo tries to resolve this during model setup, before `numa_poly` has done its work.

-   **Solution:** Use a `compute` field with `store=True` instead. It's evaluated later.

    **Wrong:**
    ```python
    # This will fail
    behavior_field = fields.Char(related='my_behavior_id.my_field')
    ```

    **Correct:**
    ```python
    behavior_field = fields.Char(compute='_compute_behavior_field', store=True)

    @api.depends('my_behavior_id.my_field')
    def _compute_behavior_field(self):
        for record in self:
            record.behavior_field = record.my_behavior_id.my_field
    ```

### Error 2: `TypeError: Cannot create a consistent method resolution order (MRO)`

-   **Cause:** Your model and a `numa_poly` mixin both inherit from a common ancestor (like `mail.thread`) in an incompatible order.

-   **Solution:** If you are using standard `_inherit` to mix models (not the recommended `_depend_models` pattern), try changing the order. Place the most complex or "dominant" model first.

    **Wrong (May Fail):**
    ```python
    _inherit = ['my.business.model', 'fsm.instance']
    ```

    **Correct (Likely to Work):**
    ```python
    _inherit = ['fsm.instance', 'my.business.model']
    ```
    *Note: This is a workaround. The preferred method is using `_depend_models`.*

### Error 3: `TypeError: Model '...' does not exist in registry.`

-   **Cause:** The order in which Python files are imported in `models/__init__.py` is incorrect. A model is being used in a field (`Many2one`, etc.) before its own file has been loaded.

-   **Solution:** In your `models/__init__.py`, ensure that models are imported before they are referenced by other models.

    **Wrong:**
    ```python
    from . import model_that_uses_other
    from . import other_model
    ```

    **Correct:**
    ```python
    from . import other_model
    from . import model_that_uses_other
    ```
---

## 4. Lifecycle and Field Access

-   **When can I access injected fields (e.g., `self.fsm_instance_id`)?**
    -   Safely in any method called after the record is created (`create`, `write`, button actions, etc.).
-   **When can I NOT access them?**
    -   Directly in the class definition for `related` fields, `domain` fields, or other static definitions that Odoo evaluates at boot time. Use `compute` fields as a workaround.
