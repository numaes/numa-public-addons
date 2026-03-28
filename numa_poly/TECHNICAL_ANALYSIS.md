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

#### `_setup_base()` — primary field injection hook

Overrides `BaseModel._setup_base`. After Odoo's standard field population runs
(`_original_BaseModel._setup_base`), it calls `_build_poly_fields` for any model whose
MRO contains a non-empty `_depend_models`.

```python
def _setup_base(self):
    _original_BaseModel._setup_base(self)
    if _poly_is_polymorphic(type(self)):
        type(self)._build_poly_fields(calling_self=self)
```

This hook fires in every `setup_models` cycle (including test-framework resets), ensuring
poly-related fields are always present and up-to-date.

#### `_build_poly_fields()` — field injection engine

Classmethod that injects `related` proxy fields for all fields from dependency models.

**Algorithm**:
```
1. Guard: skip ir.poly_base; skip if _poly_fields_built already set for this cycle.
2. Set _poly_fields_built = True (recursion guard).
3. For each (base_model_name, link_field) in _depend_models:
   a. _poly_ensure_poly_ref → inject PolyReference(base_model) if missing.
   b. For each fname in base._fields:
      - Skip technical fields.
      - If fname in cls._fields AND field is _poly_injected+non-stored → skip (already correct).
      - Otherwise (stale stored entry from MRO bleed or first run) → replace/inject.
      - Resolve absolute origin via _poly_resolve_field_origin.
      - Copy field; set related='link_field.origin_fname', store=False, compute=None.
      - Mark new_field._poly_injected = True.
      - _poly_inject_field(cls, fname, new_field).
```

**Why the tightened skip guard matters:**
Phase-1 MRO injection adds the dependency model's registry class to the child's
`__bases__`. The registry class's definition ancestors (without `pool`) appear in
`_model_classes__`, so `_setup_base` picks up their `_field_definitions` and adds those
fields as stored, non-related entries. Without the tightened guard, `_build_poly_fields`
would skip them, leaving stored direct fields instead of related proxies.

**Analysis**:
- ✅ **Runs every cycle**: Correct fields guaranteed after any `setup_models`.
- ✅ **Stale-field replacement**: Detects and overwrites stored entries from MRO bleed.
- ✅ **Idempotent**: `_poly_injected` flag prevents redundant re-injection within one cycle.
- ⚠️ **Order**: `_depend_models` order determines which link field wins on name collisions.

#### `_build_dependant_model_attributes()` (legacy, retained)

An older classmethod that copies fields and methods from dependency models. It is no
longer the primary field injection path — that role belongs to `_build_poly_fields`. It
is retained for method propagation, deep hierarchies, and edge cases. It is a no-op for
non-polymorphic models (`_poly_is_polymorphic` returns False → early return).

#### MRO Injection — `_poly_registry_setup_models` Phase 1

Before calling the original `setup_models`, the poly hook:
1. Identifies all models with non-empty `_depend_models`.
2. Adds each dependency model's *registry class* to the child's `__bases__`.
3. Syncs `__base_classes` to match `__bases__` (prevents `_prepare_setup` from
   undoing the injection).

**Side effect (handled):** Adding the dependency registry class bleeds its definition
ancestors' `_field_definitions` into the child's `_model_classes__`. The tightened guard
in `_build_poly_fields` corrects this.

**`PolyBase` in global MRO:**
```python
if PolyBase not in odoo.models.Model.__bases__:
    odoo.models.Model.__bases__ = (PolyBase,)
```
This replaces the former `odoo.models.AbstractModel = PolyBase` approach, which caused
C3 MRO errors due to inconsistent `__base_classes` when classes were imported in
different orders relative to this module.

**Analysis**:
- ✅ **Stable**: `Model.__bases__` mutation is import-order-independent.
- ✅ **Idempotent**: Membership check guards repeated loads.
- ⚠️ **Side effect**: Dependency registry class in `__bases__` bleeds field definitions
  (mitigated by stale-field replacement in `_build_poly_fields`).

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
- **Odoo 18 Compatibility**: The poly engine injects dependency model registry classes into child `__bases__` (Phase-1 MRO) so that inherited methods are always accessible. `PolyBase` is inserted into the global `Model.__bases__` chain via `__bases__` mutation (not module-alias replacement) to avoid C3 MRO errors. Shared Many2many relation tables are handled by patching `Many2many.setup_nonrelated`. Emergency View Recovery and Model Initialization Batching ensure stability during incremental loading and module updates (`-u`).
- **Field and Relation Metadata Recovery**: Enhanced proactive label and relation metadata recovery to avoid `NotNullViolation` in `ir_model_relation` and `ir_model_fields` by ensuring `_module`, `_modules`, and physical metadata (relation, columns) are correctly populated. Relational fields from non-polymorphic ancestors are no longer cloned but instead trigger a re-setup of the model to let Odoo's standard engine resolve physical metadata correctly.
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

Odoo 18 changed registry construction (incremental pool loading) and class management in
ways that required significant adaptations in the poly engine. The current implementation
is stable against these changes as of **commit `e7591ad`**.

### 1. Global PolyBase Injection — `Model.__bases__`

Odoo 18 makes `AbstractModel` a direct alias for `BaseModel` (the same Python object).
Replacing the module attribute with `odoo.models.AbstractModel = PolyBase` mixed
`_original_BaseModel`-based and `PolyBase`-based entries in registry class `__base_classes`,
breaking C3 linearisation.

**Current approach:** `Model.__bases__ = (PolyBase,)` — idempotent, import-order-
independent, and inherently consistent across all model classes.

`odoo.models.BaseModel = PolyBase` is retained as a backward-compatibility alias for
`isinstance(obj, BaseModel)` checks in third-party code.

### 2. Pre-Setup MRO Injection — `_poly_registry_setup_models` Phase 1

Before `_original_Registry_setup_models` runs, the poly hook adds each dependency model's
registry class to the polymorphic child's `__bases__`. This makes the dependency model's
methods accessible and ensures the child's `_setup_base` sees the expected inheritance.

`__base_classes` is synced to `__bases__` immediately afterward so that Odoo's
`_prepare_setup` (`cls.__bases__ = cls.__base_classes`) does not undo the injection.

**Known side effect:** The dependency registry class carries definition ancestors without
`pool`, which end up in `_model_classes__` and bleed their `_field_definitions` into the
child (see §3).

### 3. Stale-Field Replacement — `_build_poly_fields` Tightened Guard

**Problem:** When MRO Phase 1 adds `numa.planning.node`'s registry class to
`project.task.__bases__`, Odoo's `_setup_base` picks up `NumaPlanningNode._field_definitions`
and adds fields such as `pln_required_resource_ids` as stored, non-related entries in
`project.task._fields`. The previous guard `if fname in cls._fields: continue` left those
stale entries intact, causing test failures.

**Fix:** A field is skipped only if already correctly poly-injected:

```python
if getattr(existing, '_poly_injected', False) and not getattr(existing, 'store', True):
    continue  # Already correct
# Otherwise: replace stale entry
```

### 4. `_poly_fields_built` Cleared Before Every `setup_models`

The per-class flag `_poly_fields_built` guards against redundant re-injection within one
`setup_models` cycle. It is cleared from all registry classes at the start of
`_poly_registry_setup_models` so that test-framework registry resets (which call
`setup_models` again) trigger a full re-injection.

### 5. Proxy Classes Synchronization

Odoo 18 uses proxy classes. After modifying a registry class's `__bases__`, the proxy
class is synchronized via `_poly_sync_proxy_class`, which updates `__bases__`,
`__base_classes`, and calls `ctypes.pythonapi.PyType_Modified` to invalidate Python's
internal MRO cache.

### 6. Polymorphic Many2many Collisions

`odoo.fields.Many2many.setup_nonrelated` is patched to suppress the collision `TypeError`
when two polymorphic relatives share the same relation table. The inverse field binding
that Odoo skips on collision is manually restored.

### 7. View Resilience and Metadata Enforcement

- **Emergency View Recovery**: `ir.ui.view` is patched to intercept `ParseError` during
  view validation. Missing members present in the MRO are reactively injected.
- **Model Initialization Batching**: `_poly_registry_init_models` forces `setup_models`
  and sets `registry_invalidated = True` during the `init_models` phase of extending
  modules to ensure SQL columns exist before dependent views are created.
- **Relation Metadata Enforcement**: `_auto_init` proactively enforces `relation`,
  `columns`, and `_modules` on relational fields to satisfy NOT NULL constraints in
  `ir_model_relation` and `ir_model_fields`.

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
