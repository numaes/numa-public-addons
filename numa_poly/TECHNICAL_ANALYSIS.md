# Detailed Technical Analysis - Numa Poly

## Table of Contents

1. [General Architecture](#general-architecture)
2. [Core Components](#core-components)
3. [Data Flows](#data-flows)
4. [Design Patterns](#design-patterns)
5. [Monkey Patching and ORM Extension](#monkey-patching-and-orm-extension)
6. [Shared ID Management](#shared-id-management)
7. [Related Fields System](#related-fields-system)
8. [Frontend Integration](#frontend-integration)
9. [Performance Analysis](#performance-analysis)
10. [Security and Permissions](#security-and-permissions)
11. [Critical Points and Risks](#critical-points-and-risks)
12. [Potential Improvements](#potential-improvements)
13. [Odoo 18 Compatibility](#odoo-18-compatibility)

---

## General Architecture

### Overview

Numa Poly implements a polymorphic inheritance system that allows a single record to exist simultaneously in multiple models, sharing the same ID. This is achieved through:

1. **Central Model (`ir.poly_base`)**: Master record that stores metadata.
2. **Dependent Models**: Models that share the same ID via `_depend_models`.
3. **Related Fields**: `related` fields that connect dependent models.
4. **PolyReference**: A special field type for polymorphic references.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    ir.poly_base                             │
│  (ID: 100, concrete_model_id, create_uid, create_date)    │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ Same ID (100)
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ res.partner  │   │ hr.employee  │   │ project.crane│
│  (ID: 100)   │   │  (ID: 100)   │   │  (ID: 100)   │
│ name, email  │   │ work_email   │   │ capacity     │
└──────────────┘   └──────────────┘   └──────────────┘
```

---

## Core Components

### 1. IrPolyBase (Central Model)

**Location**: `models/poly.py:42-109`

**Responsibilities**:
- Store metadata of the polymorphic record.
- Maintain a reference to the concrete model (`concrete_model_id`).
- Provide the technical field `poly_payload` for DTO injection.

**Key Fields**:
```python
concrete_model_id = fields.Many2one('ir.model', required=True)
poly_payload = fields.Text(store=False, compute='_compute_payload_dummy', inverse='_inverse_payload_dummy')
```

**Analysis**:
- ✅ **Well-designed**: Centralized model for metadata.
- ⚠️ **Risk**: `poly_payload` uses compute/inverse dummy to allow writing without storage.
- ⚠️ **Consideration**: `concrete_model_id` is a Many2one, not a Char (correct for referential integrity).

### 2. PolyBase (Polymorphic Base Class)

**Location**: `models/poly.py:261-1318`

**Responsibilities**:
- Extend Odoo's `BaseModel` to support polymorphism.
- Construct attributes of dependent models.
- Manage polymorphic create/write/unlink operations.
- Validate dependency cycles.

**Critical Methods**:

#### `_build_model()` (lines 393-465)
```python
@classmethod
def _build_model(cls, pool, cr):
    # Construct the standard model first
    model_class_without_depends = super()._build_model(pool, cr)
    
    # Validate dependency cycles
    cls._validate_dependency_cycles(pool)
    
    # Construct inheritance hierarchy
    # ...
```

**Analysis**:
- ✅ **Cycle Validation**: Detects circular dependencies (lines 468-507).
- ✅ **Multiple Inheritance**: Allows dependencies from multiple models.
- ⚠️ **Complexity**: High level of complexity in class construction.

#### `_build_dependant_model_attributes()` (lines 567-803)

**Responsibilities**:
1. Create technical fields (`poly_base_id`, `concrete_model_id`, `poly_payload`).
2. Create reference fields (`PolyReference`) to base models.
3. Create `related` fields for all fields of dependent models.
4. Copy non-field methods and attributes from base models.

**Workflow**:
```
1. Create poly_base_id (PolyReference to ir.poly_base)
2. Create concrete_model_id (Many2one to ir.model, computed)
3. Create poly_payload (Text, store=False)
4. Create audit fields (create_uid, create_date, etc.)
5. Iterate through _depend_models in reverse order:
   - Create PolyReference for each base
   - Collect all fields from each base
   - Create related fields for each field found
6. Copy methods and non-field attributes
```

**Analysis**:
- ✅ **Comprehensive**: Covers all necessary aspects.
- ⚠️ **Performance**: Costly process during startup.
- ⚠️ **Dependency Order**: Order in `_depend_models` matters (last one wins on collisions).
- ⚠️ **Orphan Records**: Handles legacy records (pre-polymorphic) with graceful metadata degradation.

### 9. Automatic Model Migration (Legacy to Poly)

Numa Poly includes a robust system to migrate existing records when a model converts from "standard" to "polymorphic":

1.  **Detection (`_check_migration_needed`)**: During startup (`_auto_init`), the system checks if there are records in the model's table (or its dependencies) that lack a corresponding entry in `ir.poly_base`.
2.  **Orchestration (`_migrate_to_poly`)**: If orphan records are detected, an atomic migration process starts that:
    - Generates new global IDs from the `ir.poly_base` sequence.
    - Duplicates records across all tables in the polymorphic hierarchy.
    - Preserves audit fields (`create_date`, `create_uid`, etc.).
3.  **Reference Update (`_update_foreign_keys`)**: Automatically updates all references to the old ID in the database, including:
    - Standard Many2one and Many2many fields.
    - Dynamic references (e.g., `res_id` in `ir.attachment`, `mail.message`, `mail.followers`).
    - External IDs (`ir.model.data`).
    - Known models with IDs in logical fields (e.g., `mail.alias`).
4.  **Cleanup**: Deletes old records once reference integrity is ensured.

### 10. Integrity and Resilience Management

- **View Detection**: The engine avoids updating tables that are database views (`information_schema.views`).
- **Type Sanitization**: Deep cleaning of values (recordsets, ID lists) is performed before new record creation.
- **Conflict Resolution**: Handles unique constraint violations (e.g., `mail_followers`, Many2many) by removing redundant records before updating IDs.
- **Transactionality**: Uses database `savepoints` in critical updates to ensure that minor failures (such as third-party tables or complex constraints in Odoo 18) do not abort the entire migration.
- **Odoo 18 Compatibility**: Specific handling for `project.task` by injecting its polymorphic hierarchy (`numa.planning.node`) after registry initialization to prevent loss of inherited methods. It also includes shared Many2many collision handling and deep type cleaning to prevent recordset interference in direct SQL operations.
- **ID Extraction**: Recursive logic implemented to ensure Many2one fields always reduce to integer IDs, eliminating interference from recordsets or tuples returned by the Odoo 18 ORM.
- **Referential Integrity**: Related objects are updated to point to the new ID before physically deleting the old record, satisfying foreign key (FK) constraints.

### 3. PolyReference (Special Field)

**Location**: `models/poly.py:130-257`

**Characteristics**:
- `store=False`: Not stored in the DB.
- `readonly=True`: Cannot be written to directly.
- `auto_join=True`: Allows automatic joins.
- Uses the current record's ID as a reference.

**Key Implementation**:
```python
def convert_to_record(self, value, record):
    # Returns a recordset with the same ID as the current record
    return record.pool[self.comodel_name](record.env, (record.id,), (record.id,))
```

**Analysis**:
- ✅ **Elegant**: Ingenious solution for references without FKs.
- ⚠️ **Performance**: Requires special logic in queries.
- ⚠️ **Searching**: `_search_related()` is complex (lines 203-257).

### 4. Polymorphic Creation System

**Location**: `models/poly.py:806-1018`

**Creation Workflow**:

```
1. Validate permissions in dependent models
2. Process poly_payload (deserialize JSON and merge)
3. If concrete_model_id exists, delegate to concrete model
4. Obtain ID (explicit or create new in ir.poly_base)
5. For each dependent model:
   - Extract relevant fields
   - Create/update record with same ID
6. Create record in current model
7. Return recordset
```

**Critical Code** (lines 969-1002):
```python
# Create new ID via ir.poly_base
new_poly = self.env['ir.poly_base'].create(dict(
    concrete_model_id=self.env['ir.model']._get_id(self._name)
))
new_id = new_poly.id

# Create in all dependent models with the same ID
for base, field_set in bases_to_create.items():
    base_data['id'] = new_id
    base_model.create([base_data])
```

**Analysis**:
- ✅ **Atomic**: All within one transaction.
- ✅ **Consistency**: Same ID guaranteed.
- ⚠️ **Performance**: Multiple creates (potential N+1 problem).
- ⚠️ **Validation**: Does not validate if `concrete_model_id` is a valid subclass.

### 5. Writing System

**Location**: `models/poly.py:1096-1239`

**Characteristics**:
- Processes `poly_payload` before writing.
- Updates audit fields in `ir.poly_base`.
- Uses `_write_multi()` for batch optimization.

**Analysis**:
- ✅ **Efficient**: Uses batch updates when possible.
- ⚠️ **Auditing**: Manually updates `ir.poly_base` (lines 1243-1246).
- ✅ **Payload**: Robust JSON error handling.

---

## Data Flows

### Flow 1: Polymorphic Record Creation

```
User/API
    │
    ▼
Model.create({'name': 'John', 'work_email': 'john@example.com'})
    │
    ▼
PolyBase.create()
    │
    ├─► Validate permissions in dependents
    ├─► Process poly_payload (if exists)
    ├─► Create ir.poly_base → obtain ID
    │
    ├─► For each _depend_models:
    │   └─► base_model.create({'id': new_id, ...fields...})
    │
    └─► self.create({'id': new_id, ...local fields...})
    │
    ▼
Return recordset with shared ID
```

### Flow 2: Related Field Reading

```
record.name  # Field from res.partner
    │
    ▼
Related field: 'partner_id.name'
    │
    ▼
partner_id (PolyReference)
    │
    ▼
convert_to_record() → res.partner.browse(record.id)
    │
    ▼
Access to 'name' field in res.partner
    │
    ▼
Return value
```

### Flow 3: Searching with PolyReference

```
search([('partner_id.name', '=', 'John')])
    │
    ▼
PolyExpression.parse()
    │
    ▼
Detect PolyReference in 'partner_id'
    │
    ▼
_search_related() → construct domain in res.partner
    │
    ▼
Search in res.partner → obtain IDs
    │
    ▼
Convert to domain: [('id', 'in', [100, 101, ...])]
    │
    ▼
Execute final query
```

---

## Design Patterns

### 1. Strategic Monkey Patching

**Location**: `models/poly.py:1445-1450`

```python
odoo.models.BaseModel = PolyBase
odoo.models.AbstractModel = PolyBase
odoo.models.Model = PolyModel
odoo.models.TransientModel = PolyTransientModel
odoo.fields.Many2one.convert_to_read = poly_many2one_convert_to_read
```

**Analysis**:
- ✅ **Transparent**: Requires no changes to existing code.
- ⚠️ **Risk**: Depends on Odoo's internal structure.
- ⚠️ **Maintainability**: Can break with Odoo updates.
- ✅ **Guarded**: Only affects models with `_depend_models`.

### 2. Factory Pattern for Model Construction

The `_build_model()` method acts as a factory that constructs model classes with polymorphic inheritance.

### 3. Strategy Pattern in PolyReference

`_search_related()` implements different strategies depending on the field type and operator.

### 4. Decorator Pattern in Related Fields

Fields from dependent models are "decorated" as `related` to access data in other models.

---

## Monkey Patching and ORM Extension

### Advantages

1. **Transparency**: Existing code works without modifications.
2. **Compatibility**: Studio, Import/Export, and API work out-of-the-box.
3. **Non-invasive**: Only affects models that declare `_depend_models`.

### Disadvantages

1. **Fragility**: Depends on Odoo's internal implementation.
2. **Debugging**: More difficult to trace issues.
3. **Updates**: May require adjustments in new versions.

### Implemented Protections

```python
# Only applies if _depend_models is defined
if hasattr(cls, '_depend_models') and cls._depend_models is not None:
    # ... polymorphic logic
else:
    # Standard Odoo behavior
    return super().create(data_list)
```

---

## Shared ID Management

### Mechanism

1. **Creation**: `ir.poly_base.create()` generates a new ID.
2. **Propagation**: All dependent models use an explicit `id`.
3. **Consistency**: Guaranteed by DB transactions.

### Critical Code

```python
# Lines 969-974
new_poly = self.env['ir.poly_base'].create(dict(
    concrete_model_id=self.env['ir.model']._get_id(self._name)
))
new_id = new_poly.id

# Line 993
base_data['id'] = new_id  # Same ID for everyone
```

### Risks

1. **ID Conflict**: If a record with the same ID exists in a dependent model.
   - **Mitigation**: Validation in lines 953-961.
2. **Sequences**: Sequences of dependent models can become desynchronized.
   - **Mitigation**: `_register_hook()` adjusts sequences (lines 522-564).

### Sequence Analysis

```python
# Lines 545-563
def get_next_id(base_name) -> int:
    # Gets the next ID from the sequence
    self.env.cr.execute(f'''
        SELECT pg_sequence_last_value('{base_model._table}_id_seq')
    ''')
    
# Adjusts ir.poly_base if necessary
if current_id > poly_base_id:
    self.env.cr.execute(f'''
        ALTER SEQUENCE IF EXISTS ir_poly_base_id_seq RESTART WITH {current_id + 1};
    ''')
```

**Analysis**:
- ✅ **Preventive**: Avoids ID conflicts.
- ⚠️ **Risk**: Executes direct SQL (bypasses ORM).
- ⚠️ **Timing**: Only in `_register_hook()` (during startup).

---

## Related Fields System

### Automatic Construction

**Process** (lines 721-791):

1. Collect fields from dependent models.
2. Create a `related` field for each one.
3. Map field types correctly.
4. Handle relations (Many2one, One2many, Many2many).

### Example

```python
# Base model
class Equipment(models.Model):
    _name = 'project.equipment'
    _depend_models = {}
    name = fields.Char('Name')

# Concrete model
class Crane(models.Model):
    _name = 'project.crane'
    _depend_models = {'project.equipment': 'equipment_id'}
    capacity = fields.Float('Capacity')

# Result: Crane automatically has:
# - equipment_id (PolyReference)
# - name (related='equipment_id.name')
```

### Limitations

1. **Dependency Order**: The last model wins in name collisions.
2. **Computed Fields**: Not copied automatically.
3. **Related Fields**: Filtered to avoid duplication (lines 684-685).

---

## Frontend Integration

### OWL Components

#### PolyListRenderer
**Location**: `static/src/views/poly_list/poly_list_renderer.js`

**Functionalities**:
1. Bypass inline editing → opens dialogs.
2. Polymorphic navigation based on `concrete_model_id`.
3. Polymorphic creation with subclass selection.
4. DTO payload injection.

**Creation Workflow**:
```
onAdd()
    │
    ├─► RPC: get_poly_subclasses_info()
    │
    ├─► If >1 subclass: show selection dialog
    │
    ├─► RPC: default_get() for the selected model
    │
    ├─► Create JSON payload with defaults + concrete_model_id
    │
    ├─► Create virtual record in list with poly_payload
    │
    └─► Open form of the concrete model
```

**Analysis**:
- ✅ **UX**: Intuitive workflow for polymorphic creation.
- ⚠️ **RPC**: Multiple RPC calls (could be optimized).
- ⚠️ **Payload**: Depends on the backend processing it correctly.

#### PolyX2ManyField
**Location**: `static/src/views/fields/poly_field.js`

**Analysis**:
- ✅ **Simple**: MInimally extends X2ManyField.
- ✅ **Registry**: Correctly registered as a widget.

### Handling concrete_model_id

**Problem**: `concrete_model_id` is a Many2one, but the frontend needs the model name.

**Current Solution** (lines 75-120 of `poly_list_renderer.js`):
```javascript
// Extract model name via RPC
const modelData = await this.rpc("/web/dataset/call_kw", {
    model: "ir.model",
    method: "read",
    args: [[modelId], ["model"]],
});
```

**Analysis**:
- ⚠️ **Inefficient**: Additional RPC per opening.
- 💡 **Improvement**: Could cache or use a computed field in the frontend.

---

## Performance Analysis

### Optimization Points

#### 1. Batch Creation

**Current Problem** (lines 964-1002):
```python
for data in data_list:  # Loop through each record
    for base, field_set in bases_to_create.items():  # Loop through each base
        base_model.create([base_data])  # Individual create
```

**Impact**: O(n × m) creates where n=records, m=bases.

**Potential Improvement**:
```python
# Group creates by base model
for base, field_set in bases_to_create.items():
    base_data_list = []
    for data in data_list:
        base_data = extract_fields(data, field_set)
        base_data['id'] = get_id_for_record(data)
        base_data_list.append(base_data)
    base_model.create(base_data_list)  # Batch create
```

#### 2. Searching with PolyReference

**Problem**: `_search_related()` can generate complex subqueries.

**Analysis** (lines 203-257):
- Constructs domains recursively.
- Can generate multiple levels of subqueries.
- **Impact**: Slower queries in deep hierarchies.

#### 3. Related Field Loading

**Problem**: Accessing related fields requires multiple queries.

**Example**:
```python
records = self.env['crane'].search([])
for record in records:
    print(record.name)  # Query project.equipment for each access
```

**Mitigation**: Use `read()` with prefetch or `with_context(prefetch_fields=True)`.

### Estimated Metrics

- **Simple creation**: ~3-5 queries (ir.poly_base + N bases + current model).
- **Creation with payload**: +1 query to process JSON.
- **Related field read**: +1 query per field (without prefetch).
- **Search with PolyReference**: +1-3 queries depending on depth.

---

## Security and Permissions

### Permission Validation

**Location**: `models/poly.py:851-861`

```python
for base_name in self._depend_models.keys():
    base_model = self.env[base_name]
    if not base_model.check_access_rights('create', raise_exception=False):
        raise AccessError(...)
```

**Analysis**:
- ✅ **Validation**: Verifies permissions on all base models.
- ⚠️ **Granularity**: Does not validate permissions per field.
- ⚠️ **Write**: Does not validate permissions in `write()` (only in `create()`).

### Usage of sudo()

**Locations**:
1. `_compute_concrete_model_id()` (line 345): To read `ir.poly_base`.
2. `as_concrete_model()` (line 328): To read `ir.poly_base`.

**Justification**: Infrastructure metadata must be accessible.

**Risk**: Potential bypass of access rules if used incorrectly.

### Payload Injection

**Risk**: `poly_payload` allows injecting arbitrary JSON data.

**Mitigations**:
1. JSON validation (lines 891-898).
2. Only merges dicts (lines 882-885).
3. Error logging (lines 892-905).

**Recommendation**: Validate the payload structure according to the concrete model.

---

## Critical Points and Risks

### 1. Dependency Order

**Problem**: The order in `_depend_models` determines which field wins in collisions.

```python
_depend_models = {
    'res.partner': 'partner_id',    # If both have 'name'
    'hr.employee': 'employee_id',   # 'name' comes from hr.employee
}
```

**Risk**: Non-intuitive behavior, difficult to debug.

**Mitigation**: Document clearly, use unique names in mixins.

### 2. concrete_model_id Validation

**Problem** (lines 912-926):
```python
if concrete_model_id:
    concrete_model = self.env['ir.model'].browse(concrete_model_id).exists()
    if concrete_model and concrete_model._name != self._name:
        # Delegates creation without validating if it is a valid subclass
        new_records = concrete_model.create(new_vals_list)
```

**Risk**: Allows creating any model, not just subclasses.

**Potential Improvement**:
```python
# Validate that concrete_model is a subclass
valid_subclasses = self.get_poly_subclasses_info()
valid_models = [s['model'] for s in valid_subclasses]
if concrete_model._name not in valid_models:
    raise ValidationError("Invalid concrete model")
```

### 3. Transactions and Rollback

**Analysis**: If creation fails in a dependent model, is everything rolled back?

**Current Code**: Everything in the same transaction (guaranteed by Odoo).

**Risk**: If an error occurs after creating some bases, it may become inconsistent.

**Mitigation**: DB transactions guarantee atomicity.

### 4. Performance in Deep Hierarchies

**Problem**: Models with multiple levels of dependency.

```
A → B → C → D
```

Each level adds complexity in:
- Construction of related fields.
- Searching with PolyReference.
- Record creation.

**Impact**: O(n) where n = hierarchy depth.

### 5. Compatibility with Odoo Updates

**Risk**: Monkey patching can break with updates.

**Sensitive Areas**:
- `_build_model()`: Odoo internal structure.
- `_write_multi()`: Batch write implementation.
- `_field_to_sql()`: SQL generation.

**Mitigation**: Exhaustive tests, review in each Odoo version.

---

## Potential Improvements

### 1. Batch Creation Optimization

**Implement**:
```python
# Group creates by base model
bases_data = defaultdict(list)
for data in data_list:
    for base, field_set in bases_to_create.items():
        base_data = extract_fields(data, field_set, base)
        base_data['id'] = get_id_for_record(data)
        bases_data[base].append(base_data)

# Create in batch
for base, data_list in bases_data.items():
    base_model.create(data_list)
```

**Benefit**: Reduces N×M creates to M creates.

### 2. Subclass Cache

**Implement**:
```python
@api.model
@tools.ormcache('self._name')
def get_poly_subclasses_info(self):
    # Cache result per model
    ...
```

**Benefit**: Reduces RPC calls from the frontend.

### 3. concrete_model_id Validation

**Implement validation**:
```python
def _validate_concrete_model(self, concrete_model_id):
    if not concrete_model_id:
        return
    valid_subclasses = self.get_poly_subclasses_info()
    valid_models = [s['model'] for s in valid_subclasses]
    concrete_model = self.env['ir.model'].browse(concrete_model_id)
    if concrete_model.model not in valid_models:
        raise ValidationError("Invalid concrete model")
```

### 4. Related Field Prefetch

**Improve**:
```python
# In _build_dependant_model_attributes, mark related fields as prefetch
new_field = field_subclass(
    related=f'{related_bases[model]}.{field_name}',
    prefetch=True,  # Add this
    ...
)
```

### 5. Improved Logging

**Add**:
- Performance metrics.
- Traceability of polymorphic operations.
- Debug mode for development.

### 6. Integration Tests

**Add**:
- Batch creation tests.
- Deep hierarchy tests.
- Performance tests.
- Security tests.

---

## Odoo 18 Compatibility

Odoo version 18 introduced significant changes to registry construction (pool) and class management, requiring critical adaptations in the polymorphic engine.

### 1. Retroactive Dependency Resolution and Registry (Registry Hook)

Odoo 18 builds the pool incrementally and has changed how it manages model inheritance. A model can be "extended" by multiple modules at different stages, which sometimes causes the Python MRO (Method Resolution Order) to freeze before all polymorphic classes have been injected.

*   **Problem**: During registry loading, critical models like `project.task` may lose their inheritance from `numa.planning.node` or `ir.poly_base` if the Odoo framework finalizes the hierarchy prematurely.
*   **Solution (Final)**: A monkey-patch has been implemented in `Registry.setup_models`.
    *   This hook executes after Odoo's standard configuration process.
    *   It dynamically identifies all models in the registry that participate in polymorphic inheritance by inspecting their MRO for `_depend_models` declarations.
    *   It verifies if their MRO contains all declared dependencies.
    *   If a dependency is missing, it uses `_apply_polymorphic_hierarchy` to forcibly inject the missing parents into the Python class hierarchy at runtime.
    *   This ensures that inherited methods (like `pln_get_allocations_view`) and fields from polymorphic extensions are always available in the final model, even in complex incremental loading scenarios.

### 2. Proxy Classes Synchronization and Python Cache

Odoo 18 makes heavy use of **Proxy Classes** (dynamic classes that wrap actual implementations).

*   **Desynchronization**: Modifying the `__bases__` of the implementation class does not always automatically update the Proxy class that the environment (`self.env`) returns to users.
*   **Synchronization Mechanism (`_poly_sync_proxy_class`)**:
    *   `numa_poly` explicitly synchronizes `__bases__` and `__base_classes` between the real class and its Proxy.
    *   Uses `ctypes.pythonapi.PyType_Modified` (via `_poly_force_mro_update`) to force Python to invalidate its internal method resolution caches in both the base class and the Proxy.
    *   Explicitly invalidates the Odoo cache (`pool.model_methods` and `Environment._classes`) to ensure the framework discovers the newly injected methods.

### 3. Polymorphic Many2many Collisions

In standard Odoo, two models cannot share the same relationship table and columns for a `Many2many` relation.

*   **Natural Conflict**: In a polymorphic system, it is **correct** for a model and its counterpart to share the same relationship table (since they are, conceptually, the same record).
*   **Check Intervention**: `odoo.fields.Many2many.setup_nonrelated` was patched to intercept the collision `TypeError`.
    *   If the conflicting models are polymorphic relatives (one is in the other's MRO), the error is silently ignored.
    *   The inverse field binding logic that Odoo skips upon detecting the conflict is manually restored.

### 4. Registry Hierarchy and Field Recovery Guarantee

To ensure that key models never lose their polymorphic capabilities or inherited fields, the system performs a final check upon completing registry loading (`Registry.setup_models`).

If it detects that a model should be polymorphic but its Python MRO does not reflect the full hierarchy, it dynamically injects the missing bases and synchronizes its proxy classes. Additionally, it performs an exhaustive scan of the MRO to "recover" any fields that Odoo's incremental loading might have missed (e.g., standard Odoo fields added by bridge modules). This ensures a robust state for view validation and business logic.

---

## Conclusions

### Strengths

1. ✅ **Solid Architecture**: Well-thought-out design for polymorphism.
2. ✅ **Transparency**: Works with existing code without modifications.
3. ✅ **Comprehensive**: Covers creation, reading, writing, and deletion.
4. ✅ **Extensible**: Easy to add new polymorphic models.

### Weaknesses

1. ⚠️ **Performance**: Multiple queries in common operations.
2. ⚠️ **Complexity**: High level of complexity in construction.
3. ⚠️ **Fragility**: Dependency on Odoo internal structure.
4. ⚠️ **Validation**: Lack of validation at some critical points.

### Recommendations

1. **Short Term**:
   - Implement `concrete_model_id` validation.
   - Optimize batch creation.
   - Add more logging.

2. **Medium Term**:
   - Subclass cache.
   - Related field prefetch.
   - Performance tests.

3. **Long Term**:
   - Consider alternatives to monkey patching.
   - Better documentation of dependency order.
   - Create debugging tools.

---

*Analysis performed: 2024*
*Module version: 18.0.1.0.0*
