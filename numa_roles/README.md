# Numa Roles - RBAC System

Strict RBAC (Role-Based Access Control) implementation for Odoo 18.0.

## Overview

This module implements a Role-Based Access Control system on top of Odoo's native `res.groups` model, separating the concepts of "Roles" and "Permissions" while maintaining full technical compatibility.

## Architecture

### Three Types of Groups

The module classifies `res.groups` records into three types using the `numa_type` field:

1. **Permissions** (`numa_type='permission'`):
   - Atomic access units
   - Examples: `perm_approve_discount`, `perm_view_dashboard`, `perm_export_data`
   - **Cannot** be assigned directly to users
   - Must have a unique `technical_code` (immutable)
   - Can only inherit from other permissions or system groups

2. **Roles** (`numa_type='role'`):
   - Collections of permissions
   - Examples: `role_sales_manager`, `role_data_analyst`
   - **Can** be assigned to users
   - Include permissions via `implied_ids`
   - Can be marked as templates (`is_template=True`)

3. **System** (`numa_type='system'`):
   - Native Odoo groups (legacy)
   - Default type for backward compatibility
   - Works as before

## Key Features

### Constraints

The module enforces RBAC rules through Python constraints:

1. **Permissions cannot have users**:
   - Prevents direct assignment of permissions to users
   - Permissions must be included in roles

2. **Permissions cannot inherit from roles**:
   - Maintains logical hierarchy: Roles → Permissions → System
   - Prevents circular dependencies

3. **Technical code required for permissions**:
   - Must be unique
   - Immutable once set
   - Auto-generated from name if not provided

### Views

Conditional views based on `numa_type`:

- **For Permissions**:
  - Hide: Users, Rules, Views, Menus tabs
  - Show: Technical code, category, inherited permissions (filtered)

- **For Roles**:
  - Hide: Views, Menus, Rules tabs (technical)
  - Show: Permissions tab (editable tree), Users tab

- **For System**:
  - Standard Odoo view (unchanged)

### Menu Structure

- **Gestión de Accesos** (Access Management)
  - **Roles**: List of all roles
  - **Permisos**: List of all permissions

## Usage

### Creating a Permission

1. Go to **Settings > Gestión de Accesos > Permisos**
2. Create new permission
3. Set `numa_type` to "Permiso"
4. Enter `technical_code` (e.g., `perm_approve_discount`)
5. Set category and description

### Creating a Role

1. Go to **Settings > Gestión de Accesos > Roles**
2. Create new role
3. Set `numa_type` to "Rol"
4. In "Permisos" tab, add permissions via `implied_ids`
5. Assign role to users in "Usuarios" tab

### Assigning Roles to Users

1. Open user form
2. Go to "Access Rights" tab
3. Assign roles (groups with `numa_type='role'`)
4. User automatically gets all permissions included in the roles

## Technical Details

### Model Extension

The module extends `res.groups` with:

- `numa_type`: Selection field (role/permission/system)
- `technical_code`: Char field (required for permissions, immutable)
- `is_template`: Boolean (marks system-defined vs user-created)
- `permission_count`: Computed field (number of permissions in a role)

### Constraints Implementation

All constraints are implemented in Python using `@api.constrains`:

```python
@api.constrains('numa_type', 'users')
def _check_permission_no_users(self):
    # Prevents permissions from having users
```

### Auto-generation of technical_code

If a permission is created without `technical_code`, it's auto-generated from the name:
- Convert to lowercase
- Replace spaces/hyphens with underscores
- Prefix with `perm_`
- Remove special characters

Example: "View Dashboard" → `perm_view_dashboard`

## Data Examples

The module includes demo data:

- **Permission**: `perm_view_dashboard` (View Dashboard)
- **Permission**: `perm_export_data` (Export Data)
- **Role**: `role_data_analyst` (Data Analyst) - includes both permissions

## Migration Notes

### From Old Structure

If migrating from the old `is_role` boolean field:

1. Existing groups with `is_role=True` should be updated to `numa_type='role'`
2. New permissions should be created with `numa_type='permission'`
3. System groups remain with `numa_type='system'` (default)

### Backward Compatibility

- All existing `res.groups` records default to `numa_type='system'`
- Standard Odoo functionality remains unchanged
- Only new RBAC features are added

## License

LGPL-3
