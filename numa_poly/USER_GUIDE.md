# Numa Poly - User Guide

## Table of Contents

1. [Introduction](#introduction)
2. [Polymorphic Widget Overview](#polymorphic-widget-overview)
3. [Backend Setup](#backend-setup)
4. [Frontend Configuration](#frontend-configuration)
5. [Usage Examples](#usage-examples)
6. [Advanced Features](#advanced-features)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## Introduction

Numa Poly provides a powerful polymorphic inheritance system for Odoo 18.0 that allows creating polymorphic child records in One2Many lists without forcing immediate database writes. This is achieved through a "Trojan Horse" DTO (Data Transfer Object) pattern that serializes subclass-specific fields into a JSON payload.

### Key Concepts

- **Polymorphic Base Model**: Abstract model (`numa.poly.base`) that provides the foundation for polymorphic records
- **Payload Injection**: JSON-based transport mechanism for subclass-specific data
- **Virtual Records**: In-memory records created before database persistence
- **Concrete Model**: The specific subclass model that implements the polymorphic behavior

---

## Polymorphic Widget Overview

The `numa_polimorphic_widget` is a custom OWL widget that extends the standard X2Many field behavior to support:

1. **Polymorphic Creation**: Select and create records of different subclasses
2. **Type Selection**: Dialog-based selection when multiple subclasses are available
3. **Direct Navigation**: Opens concrete model forms instead of inline editing
4. **Payload Transport**: Automatically serializes and injects subclass data

### Architecture Flow

```
User clicks "Add" 
  → Widget fetches available subclasses
  → If multiple: Shows selection dialog
  → Opens form for selected subclass
  → User fills form
  → Data serialized to JSON payload
  → Virtual record created with payload
  → Backend processes payload on parent save
```

---

## Backend Setup

### Step 1: Declare Polymorphic Base Model

Your polymorphic base model must declare `_depend_models = {}` to enable polymorphic behavior:

```python
from odoo import models, fields, api

class MyPolyModel(models.Model):
    _name = 'my.poly.model'
    # Declare as polymorphic base model
    _depend_models = {}
    
    name = fields.Char('Name', required=True)
    
    # Your model-specific fields here
```

### Step 2: Implement get_poly_subclasses_info

Override the `get_poly_subclasses_info()` method to return available subclasses:

```python
def get_poly_subclasses_info(self):
    """
    Returns information about valid polymorphic subclasses.
    
    Returns:
        list: List of dicts with 'model' and 'name' keys
    """
    return [
        {'model': 'project.crane', 'name': 'Crane'},
        {'model': 'project.excavator', 'name': 'Excavator'},
        {'model': 'project.truck', 'name': 'Truck'},
    ]
```

### Step 3: Define Concrete Models

Create the concrete subclass models:

```python
# Base definition in inital module

class Equipment(models.Model):
    _name = 'project.equipment'
    # declare a polimorphic base model
    _depend_models = {}

    manufacturers_name = fields.Char('Manufactures name')
    quantity = fields.Integer('Quantity')

    @api.model
    def get_poly_subclasses_info(self):
        base_subclasses = super().get_poly_subclasses_info()
        return base_subclasses + [{'model': 'project.crane', 'name': 'Crane'}]


class ProjectCrane(models.Model):
    _name = 'project.crane'
    _depend_models = {'project.equipment': equipment_id}
    
    # Crane-specific fields
    lifting_capacity = fields.Float('Lifting Capacity (tons)')
    boom_length = fields.Float('Boom Length (meters)')

# In an extension module
class Equipment(models.Model):
    _inherit = 'project.equipment'

    @api.model
    def get_poly_subclasses_info(self):
        base_subclasses = super().get_poly_subclasses_info()
        return base_subclasses + [{'model': 'project.excavator', 'name': 'Excavator'}]


class ProjectExcavator(models.Model):
    _name = 'project.excavator'
    _depend_models = {'project.equipment': equipment_id}
    
    # Excavator-specific fields
    bucket_capacity = fields.Float('Bucket Capacity (cubic meters)')
    digging_depth = fields.Float('Digging Depth (meters)')
```

### Step 4: Create Parent Model with One2Many Field

```python
class ProjectSite(models.Model):
    _name = 'project.site'
    
    name = fields.Char('Site Name', required=True)
    
    # One2Many field pointing to polymorphic base
    equipment_ids = fields.One2many(
        'project.equipment', 
        'parent_id',
        string='Equipment'
    )
```

---

## Frontend Configuration

### Step 1: Include poly_payload in List View

**CRITICAL**: The `poly_payload` field MUST be included in the list view, even if invisible:

```xml
<field name="equipment_ids" widget="numa_polimorphic_widget">
    <list>
        <field name="concrete_model_id" string="Type"/>
        <field name="manufacturers_name" string="Man.Name"/>
        <field name="quantity" string="Quantity used"/>
        <!-- 
        CRITICAL: poly_payload must be included in the list
        for the widget to function correctly. It can be invisible.
        -->
        <field name="poly_payload" column_invisible="1"/>
    </list>
</field>
```

### Step 2: Complete Form View Example

```xml
<record id="project_site_form_view" model="ir.ui.view">
    <field name="name">project.site.form</field>
    <field name="model">project.site</field>
    <field name="arch" type="xml">
        <form string="Project Site">
            <sheet>
                <group>
                    <field name="name"/>
                </group>
                
                <notebook>
                    <page string="Equipment">
                        <field name="equipment_ids" widget="numa_polimorphic_widget">
                            <list>
                                <field name="concrete_model_id" string="Type"/>
                                <field name="manufacturers_name" string="Man.Name"/>
                                <field name="quantity" string="Quantity used"/>
                                <field name="poly_payload" column_invisible="1"/>
                            </list>
                        </field>
                    </page>
                </notebook>
            </sheet>
        </form>
    </field>
</record>
```

### Step 3: List View (Optional)

If you want a standalone list view:

```xml
<record id="project_site_list_view" model="ir.ui.view">
    <field name="name">project.site.list</field>
    <field name="model">project.site</field>
    <field name="arch" type="xml">
        <list string="Project Sites">
            <field name="concrete_model_id" string="Type"/>
            <field name="manufacturers_name" string="Man.Name"/>
            <field name="quantity" string="Quantity used"/>
            <field name="poly_payload" column_invisible="1"/>
        </list>
    </field>
</record>
```

---

## Usage Examples

### Example 1: Basic Polymorphic List

**Scenario**: A project site with different types of equipment.

**Backend** (`models/project_site.py`):

```python
from odoo import models, fields

class ProjectSite(models.Model):
    _name = 'project.site'
    
    name = fields.Char('Site Name', required=True)
    equipment_ids = fields.One2many(
        'project.equipment',
        'site_id',
        string='Equipment'
    )
    
```

**Frontend** (`views/project_site_views.xml`):

```xml
<field name="equipment_ids" widget="numa_polimorphic_widget">
    <list>
        <field name="concrete_model_id" string="Type"/>
        <field name="manufactures_name"/>
        <field name="quantity"/>
        <field name="poly_payload" column_invisible="1"/>
    </list>
</field>
```

### Example 2: Single Subclass (No Selection Dialog)

If `get_poly_subclasses_info()` returns only one subclass, the widget will skip the selection dialog and directly open the form:

```python
def get_poly_subclasses_info(self):
    return [
        {'model': 'project.crane', 'name': 'Crane'},
    ]
```

### Example 3: Complex Hierarchy

For more complex scenarios with multiple levels:

```python
class BaseEquipment(models.Model):
    _name = 'base.equipment'

    _depend_models = {}
    
    name = fields.Char('Name', required=True)
    purchase_date = fields.Date('Purchase Date')
    cost = fields.Monetary('Cost')

class ProjectCrane(models.Model):
    _name = 'project.crane'
    _depend_models = {'project.equipment': equipment_id}
    
    lifting_capacity = fields.Float('Lifting Capacity')
    certification_number = fields.Char('Certification Number')
```

---

## Advanced Features

### Custom Payload Processing

You can customize how the payload is processed in the backend:

```python
@api.model_create_multi
def create(self, vals_list):
    # Custom preprocessing before payload injection
    for vals in vals_list:
        if 'poly_payload' in vals:
            # Add custom data to payload
            payload = json.loads(vals.get('poly_payload', '{}'))
            payload['custom_field'] = 'custom_value'
            vals['poly_payload'] = json.dumps(payload)
    
    return super().create(vals_list)
```

### Validation Before Payload Injection

Add validation logic:

```python
def write(self, vals):
    # Validate before processing payload
    if 'poly_payload' in vals:
        payload = json.loads(vals['poly_payload'])
        if not payload.get('required_field'):
            raise ValidationError("Required field is missing in payload")
    
    return super().write(vals)
```

### Dynamic Subclass Selection

Make subclass selection dynamic based on context:

```python
def get_poly_subclasses_info(self):
    # Filter subclasses based on user or context
    user = self.env.user
    subclasses = []
    
    if user.has_group('project.group_project_manager'):
        subclasses.append({'model': 'project.crane', 'name': 'Crane'})
    
    if user.has_group('project.group_project_user'):
        subclasses.append({'model': 'project.excavator', 'name': 'Excavator'})
    
    return subclasses
```

---

## Troubleshooting

### Issue: Widget Not Appearing

**Symptoms**: The widget doesn't show up, or standard X2Many behavior is used.

**Solutions**:
1. Verify `poly_payload` field is included in the list view (even if invisible)
2. Check that `widget="numa_polimorphic_widget"` is correctly specified
3. Ensure the module is properly installed and assets are loaded
4. Check browser console for JavaScript errors

### Issue: Selection Dialog Not Showing

**Symptoms**: Form opens directly even when multiple subclasses exist.

**Solutions**:
1. Verify `get_poly_subclasses_info()` returns multiple items
2. Check RPC call is successful (browser console)
3. Ensure the method is accessible (not private with `_` prefix)

### Issue: Payload Not Processed

**Symptoms**: Data from form is not merged into the record.

**Solutions**:
1. Verify the model has `_depend_models = {}` declared (for base) or `_depend_models = {'base.model': 'field_id'}` (for subclasses)
2. Check that `create()` and `write()` methods call `super()`
3. Verify JSON payload is valid (check browser console)
4. Check server logs for JSON parsing errors
5. Ensure `poly_payload` field is included in the list view (even if invisible)

### Issue: Field Not Found Errors

**Symptoms**: Errors about missing fields when accessing subclass fields.

**Solutions**:
1. Ensure concrete model fields are properly defined
2. Verify field names match between payload and model definition
3. Check that fields are not readonly or computed without store

---

## Best Practices

### 1. Field Naming

- Use descriptive names for fields in concrete models
- Avoid generic names that might conflict with base model fields
- Prefix mixin fields to avoid collisions (e.g., `equipment_name` vs `name`)

### 2. Payload Structure

Keep payload structure simple and flat when possible:

```python
# Good
payload = {
    'concrete_model_id': 'project.crane',
    'name': 'Crane #1',
    'lifting_capacity': 50.0,
}

# Avoid nested structures when possible
payload = {
    'concrete_model_id': 'project.crane',
    'data': {
        'name': 'Crane #1',  # Nested - harder to process
    }
}
```

### 3. Error Handling

Always handle JSON parsing errors gracefully:

```python
try:
    payload_data = json.loads(payload)
except json.JSONDecodeError as e:
    _logger.error("Invalid JSON payload: %s", str(e))
    raise ValidationError(_("Invalid data format"))
```

### 4. Performance Considerations

- Keep payload size reasonable (avoid large binary data)
- Use `column_invisible="1"` for `poly_payload` to avoid loading unnecessary data
- Consider pagination for large lists

### 5. Security

- Validate payload data before processing
- Use access rights to control which subclasses are available
- Sanitize user input in payload fields

### 6. Testing

Test the following scenarios:
- Creating records with single subclass
- Creating records with multiple subclasses (selection dialog)
- Editing existing polymorphic records
- Deleting polymorphic records
- Validation errors in payload
- Invalid JSON in payload

---

## ⚠️ PRODUCTION WARNING - EXPERIMENTAL STATUS

**Numa Poly** is currently in **EXPERIMENTAL** status. While it provides powerful architectural capabilities, its use in production environments is **STRONGLY DISCOURAGED** for mission-critical systems at this stage.

### Known Constraints and Risks:
1.  **Monkey Patching:** It modifies Odoo's core `BaseModel`. While guarded, it may conflict with other deeply-integrating modules or break during Odoo core updates.
2.  **Performance Overheads:** Polymorphic operations (CRUD) involve multiple database tables, which can increase the total number of queries compared to standard Odoo models.
3.  **Data Consistency:** Although the system handles "legacy" (orphan) records gracefully, the best practice is to have a clean polymorphic state. Mixing legacy data and polymorphic data in the same model may lead to complex debugging scenarios.
4.  **Security Granularity:** Security rules (ACLs) must be carefully managed across the entire polymorphic hierarchy.

**Conclusion:** Use Numa Poly for prototyping, non-critical modules, or when the architectural benefits clearly outweigh the maintenance risks. Always perform exhaustive testing in a staging environment before any production deployment.

---

## Migration from Odoo 17

If you're migrating from Odoo 17 or earlier versions:

1. **Replace `<tree>` with `<list>`**: All tree views must be updated to use `<list>` tag
2. **Update field attributes**: Some field attributes may have changed
3. **Review widget registration**: Ensure widget is properly registered in Odoo 18 format

### Example Migration

**Before (Odoo 17)**:
```xml
<field name="equipment_ids" widget="numa_polimorphic_widget">
    <tree>
        <field name="name"/>
    </tree>
</field>
```

**After (Odoo 18)**:
```xml
<field name="equipment_ids" widget="numa_polimorphic_widget">
    <list>
        <field name="name"/>
        <field name="poly_payload" column_invisible="1"/>
    </list>
</field>
```

---

## Additional Resources

- **Module Documentation**: See `README.rst` for architectural details
- **Code Examples**: Check `views/poly_views.xml` for complete examples
- **API Reference**: See `models/numa_poly_base.py` for backend API

---

## Support

For issues, questions, or contributions:
- **Author**: NUMA Extreme Systems
- **Website**: https://www.numaes.com
- **License**: AGPL-3

---

*Last Updated: 2024*
