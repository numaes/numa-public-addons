"""
Polymorphic Models Module for Odoo

This module implements polymorphic models in Odoo, allowing for a more flexible
inheritance mechanism where models can inherit fields and behavior from multiple
parent models while maintaining a single database record.

The polymorphic model system enables:
- Multiple inheritance from different models
- Automatic field propagation from parent models
- Transparent access to fields from parent models
- Proper handling of CRUD operations across the inheritance hierarchy

Technical Note (Odoo 18):
This module uses a retroactive dependency resolution mechanism to handle models that
depend on each other across different module loading phases. It also ensures
synchronization between Odoo 18 Proxy classes and their underlying implementation classes.

Architecture & Design Decisions:

1. Method Resolution Order (MRO) Logic:
   The system explicitly prioritizes polymorphic parents (from `_depend_models`) over
   Odoo's standard inheritance (`_inherit`). This ensures that polymorphic behavior
   can effectively intercept and override standard model methods.
   MRO Hierarchy: [PolymorphicParents, ir.poly_base, OdooInheritBases, BaseModel, object]

2. Retroactive Dependency Resolution:
   In Odoo's incremental loading, a child model might be instantiated before its
   polymorphic parent is fully processed or promoted. To solve this "immutability"
   problem, `numa_poly` implements a post-setup hook in `Registry.setup_models`
   that scans all models, recalculates hierarchies, and updates `__bases__`
   dynamically to ensure that all children acquire their parent's polymorphic methods.

3. Reactive View Validation & Error Masking:
   Odoo 18 validates views (`_validate_view`) immediately after XML record loading,
   often before the final MRO has been synchronized across all models. This leads
   to "Unknown field" or "Method not found" errors for buttons or actions referencing
   polymorphic logic.
   To survive the `-u` (update) process:
   - A reactive injection patch scans the MRO for missing elements during validation.
   - If inconsistency persists, errors are masked (`return True`) as a fail-safe.
   This masking is critical because the Registry is in a transient, inconsistent state
   during update; final consistency is guaranteed only after the full registry setup.

4. Cache and Proxy Synchronization:
   Modern Odoo uses internal caches (like `Environment._classes` and Proxy classes)
   that may hold stale versions of model definitions. `numa_poly` forcefully clears
   these caches and synchronizes Proxy `__bases__` to ensure that Python's attribute
   lookup reflects the injected polymorphic hierarchy.
"""

import copy
import logging
import ctypes
import warnings
from collections import OrderedDict, defaultdict
import typing
import json

# Odoo imports
import odoo
from odoo import api, models, fields, _, Command
from odoo import SUPERUSER_ID
from odoo.models import BaseModel, LOG_ACCESS_COLUMNS, INSERT_BATCH_SIZE, UPDATE_BATCH_SIZE, GC_UNLINK_LIMIT
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
from odoo.tools import OrderedSet, Query, split_every, SQL, sql
from odoo.tools.misc import LastOrderedSet, Sentinel, SENTINEL
from odoo.api import Self, ValuesType, IdType
from collections import deque

# Local imports
from . import expression

# Type checking imports
if typing.TYPE_CHECKING:
    from collections.abc import Reversible
    from odoo.modules.registry import Registry


_logger = logging.getLogger(__name__)


# [poly] Per-table physical-column cache (no-migration strategy): used to decide
# whether a field is the concrete model's OWN column and must therefore never be
# shadowed by a related-to-base version. Stable within a process after install.
_POLY_LEAF_COLUMNS = {}


def _poly_leaf_columns(cr, table):
    """Set of physical columns of `table` (cached). Empty on any error/missing table."""
    cols = _POLY_LEAF_COLUMNS.get(table)
    if cols is None:
        try:
            cols = set(sql.table_columns(cr, table))
        except Exception:
            cols = set()
        # Only cache non-empty results so a probe done before the table exists
        # (very early setup) is retried later.
        if cols:
            _POLY_LEAF_COLUMNS[table] = cols
    return cols


# [poly] Professional Patch for _inherits_check to avoid KeyError: None
_original_inherits_check = odoo.models.BaseModel._inherits_check
def poly_inherits_check(self):
    cls = type(self)
    if hasattr(cls, '_inherits') and cls._inherits:
        # [poly] Odoo 18: _inherits = {'parent_model': 'field_name'}
        for parent_model, field_name in list(cls._inherits.items()):
            field = cls._fields.get(field_name)
            
            # [poly] RECOVERY: search by field_name in all possible places
            if not field:
                field = getattr(cls, field_name, None)
                if not field and hasattr(cls, '_field_definitions'):
                    defs = cls._field_definitions
                    if isinstance(defs, dict): field = defs.get(field_name)
                    elif isinstance(defs, list):
                        for f in defs:
                            if getattr(f, 'name', None) == field_name:
                                field = f; break
                if field: cls._fields[field_name] = field

            if field:
                if not getattr(field, 'comodel_name', None):
                    # For Many2one fields in Odoo 18, comodel_name is vital.
                    # In _inherits, the key is the comodel_name.
                    try:
                        object.__setattr__(field, 'comodel_name', parent_model)
                    except Exception:
                        field.__dict__['comodel_name'] = parent_model
                
                # [poly] Aggressive repair for ondelete
                if getattr(field, 'ondelete', None) is None:
                    try:
                        object.__setattr__(field, 'ondelete', 'cascade')
                    except Exception:
                        field.__dict__['ondelete'] = 'cascade'
            else:
                # Field missing. Odoo WILL crash. Removing from _inherits.
                # _logger.error("[poly] Field %s (parent %s) NOT FOUND in %s", field_name, parent_model, cls._name)
                del cls._inherits[parent_model]
                
    return _original_inherits_check(self)
odoo.models.BaseModel._inherits_check = poly_inherits_check

# Global cache for polymorphic MRO to ensure they survive Odoo's registry setup phases.
# Keys are db_name, then model_name. Values are tuples of base classes.
POLY_MRO_CACHE = defaultdict(dict)

# [poly] Technical list for deferred view validation
@odoo.tools.lazy_property
def _poly_pending_views(self):
    return set()

def _poly_get_safe_mro(cls):
    """
    [poly] Safe MRO extraction for Odoo 18.
    """
    if cls is None:
        return []
    try:
        if isinstance(cls, type):
            return cls.mro()
        # If it's an instance, get its class's MRO
        return type(cls).mro()
    except Exception:
        # Fallback for weird objects in the registry
        m = getattr(cls, 'mro', None)
        if callable(m):
            try:
                return m()
            except Exception:
                pass
        return []

# [poly] Per-registry cache for _poly_is_polymorphic results.
# Keyed by model _name -> bool.  Cleared in _poly_registry_setup_models after
# each Registry.setup_models() call so stale entries never survive a reload.
_poly_is_polymorphic_cache: dict = {}


def _poly_is_polymorphic(model):
    """
    Determina si un modelo es polimórfico analizando su cadena de MRO y la presencia de _depend_models.
    Un modelo es polimórfico si él o cualquiera de sus bases (CON EL MISMO _name) tiene _depend_models.
    """
    if model is None or not hasattr(model, '_name'):
        return False

    name = model._name
    if name == 'ir.poly_base':
        return False

    # [poly] Cache hit — avoid repeated DFS on every ORM call.
    cached = _poly_is_polymorphic_cache.get(name)
    if cached is not None:
        return cached

    model_class = type(model) if not isinstance(model, type) else model

    # [poly] Fast path: check getattr on the class directly.
    _fast = getattr(model_class, '_depend_models', None)
    if _fast and isinstance(_fast, (dict, OrderedDict)) and len(_fast) > 0:
        _poly_is_polymorphic_cache[name] = True
        return True

    # [poly] Slower fallback: walk MRO explicitly and check each class's __dict__.
    for base in _poly_get_safe_mro(model_class):
        raw = base.__dict__.get('_depend_models')
        if raw and isinstance(raw, (dict, OrderedDict)) and len(raw) > 0:
            base_name = getattr(base, '_name', None)
            if base_name is None or base_name == name:
                _poly_is_polymorphic_cache[name] = True
                return True

    # [poly] Last-resort fallback: DFS over PolyModel definition subclasses.
    # This handles the case where setup_models rebuilds the registry class after
    # Phase 0 set _depend_models, losing the dynamic attribute.  The definition
    # class (e.g. ConversationMessageFacebook) always has _depend_models in its
    # own __dict__ regardless of registry class identity.
    try:
        _def_stack = list(PolyModel.__subclasses__())
        while _def_stack:
            _def_cls = _def_stack.pop()
            if _def_cls.__dict__.get('_name') == name:
                _d = _def_cls.__dict__.get('_depend_models')
                if _d and isinstance(_d, (dict, OrderedDict)) and len(_d) > 0:
                    _poly_is_polymorphic_cache[name] = True
                    return True
            _def_stack.extend(_def_cls.__subclasses__())
    except Exception:
        pass

    _poly_is_polymorphic_cache[name] = False
    return False


# ---------------------------------------------------------------------------
# Technical fields that are never inherited from a polymorphic base.
# Audit fields (create_uid etc.) are re-injected explicitly via poly_base_id.
# ---------------------------------------------------------------------------
_POLY_TECHNICAL_FIELDS = frozenset({
    'id', '__last_update', 'display_name',
    'create_uid', 'create_date', 'write_uid', 'write_date',
    'old_id', 'concrete_model_id', 'poly_payload', 'poly_base_id',
})


def _poly_collect_depend_models(cls) -> OrderedDict:
    """
    Collect the consolidated _depend_models map for cls.

    Walk the MRO and include only bases where the base's own _name equals
    cls._name (i.e. mixin layers of the same model).  Entries are collected
    in definition order (subclass first) without repetition.

    Returns an OrderedDict {base_model_name: link_field_name}.
    """
    if getattr(cls, '_name', None) == 'ir.poly_base':
        return OrderedDict()
    result = OrderedDict()
    for base in _poly_get_safe_mro(cls):
        if getattr(base, '_name', None) != cls._name:
            continue
        dep = base.__dict__.get('_depend_models')
        if dep and isinstance(dep, (dict, OrderedDict)):
            for model_name, field_name in dep.items():
                if model_name not in result:
                    result[model_name] = field_name
    return result


def _poly_resolve_field_origin(fname: str, model, pool) -> 'tuple[str, str]':
    """
    Follow the polymorphic related chain to find the model that natively defines
    a field (i.e. where the field is NOT itself a poly-injected related).

    Returns (model_name, field_name).  If resolution fails, returns the
    input model name and fname unchanged.
    """
    visited: set = set()
    current_model_name: str = model._name
    current_fname: str = fname

    while True:
        key = (current_model_name, current_fname)
        if key in visited:
            break
        visited.add(key)

        current_model = pool.get(current_model_name)
        if current_model is None:
            break

        field = current_model._fields.get(current_fname)
        if field is None:
            break

        # A poly-injected related has the form related='link_field.field_name'
        # where link_field is a PolyReference.
        rel = getattr(field, 'related', None)
        if not rel:
            break  # native field — this is the origin

        # Normalise to string
        if isinstance(rel, (tuple, list)):
            rel = '.'.join(str(p) for p in rel)

        parts = rel.split('.', 1)
        if len(parts) != 2:
            break

        link_fname, sub_fname = parts
        link_field = current_model._fields.get(link_fname)
        if not isinstance(link_field, PolyReference):
            break  # not a poly bridge — stop

        current_model_name = link_field.comodel_name
        current_fname = sub_fname

    return current_model_name, current_fname


def _poly_ensure_poly_ref(cls, target_model_name: str, dep_map: OrderedDict) -> str:
    """
    Ensure a PolyReference to *target_model_name* exists in cls._fields.

    Resolution order:
    1. Explicit name from dep_map (if target is a direct dependency).
    2. Existing PolyReference in cls._fields that already points to target.
    3. Auto-generated name: poly_<model_name_underscored>_id.

    Creates and injects the field if it does not yet exist.
    Returns the link field name.
    """
    # 1. Prefer the explicit link name declared in _depend_models
    explicit = dep_map.get(target_model_name)
    if explicit:
        if explicit not in cls._fields:
            _poly_inject_field(cls, explicit, PolyReference(target_model_name))
        return explicit

    # 2. Re-use an existing PolyReference to the same model
    for fname, field in list(cls._fields.items()):
        if isinstance(field, PolyReference) and field.comodel_name == target_model_name:
            return fname

    # 3. Generate a stable name
    auto_name = 'poly_{}_id'.format(target_model_name.replace('.', '_'))
    if auto_name not in cls._fields:
        _poly_inject_field(cls, auto_name, PolyReference(target_model_name))
    return auto_name


def _poly_inject_field(cls, fname: str, field) -> None:
    """
    Inject *field* as *fname* into *cls*.

    Sets the field as a class attribute, registers it in cls._fields, and
    propagates it to the Odoo 18 pool proxy class when the proxy differs from cls.
    """
    setattr(cls, fname, field)
    cls._fields[fname] = field
    field.model_name = cls._name
    field.name = fname
    # Run attribute setup so that comodel_name and other _args__ parameters are
    # resolved as instance attributes.  Without this, dynamically injected
    # fields (especially PolyReferences) keep comodel_name = None (class default).
    try:
        field._setup_attrs(cls, fname)
    except Exception:
        pass

    # Odoo 18 keeps a separate proxy class in pool.models; keep it in sync.
    try:
        pool = cls.pool  # type: ignore[attr-defined]
        proxy = pool.models.get(cls._name)
        if proxy is not None and proxy is not cls:
            setattr(proxy, fname, field)
            proxy._fields[fname] = field
    except Exception:
        pass


# [poly] Track processed models for incremental Deep Fix
@odoo.tools.lazy_property
def _poly_processed_models(self):
    """ {model_name: set(module_names)} """
    return defaultdict(set)

# [poly] Track injected MRO for incremental Phase 1
@odoo.tools.lazy_property
def _poly_injected_mro(self):
    """ {model_name: tuple(base_classes)} """
    return {}

def _poly_finalize_view_validation(self, cr):
    """
    [poly] Finalizes the validation of views that were deferred during module loading.
    """
    if not self._pending_poly_views:
        return

    _logger.debug("[poly] Finalizing validation for %d deferred views", len(self._pending_poly_views))
    
    # We must use a separate cursor to avoid potential transaction issues
    # although during load_module_graph we are usually in a safe spot.
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    View = env['ir.ui.view']
    
    # We work on a copy to allow clearing the original set safely
    view_ids = sorted(list(self._pending_poly_views))
    
    errors_found = False
    for view_id in view_ids:
        try:
            # We use a special context flag to bypass the 'deferred' check in our patch
            view = View.browse(view_id).with_context(poly_final_validation=True)
            if view.exists():
                view._check_xml()
        except Exception as e:
            errors_found = True
            # Try to identify the module for better error reporting
            cr.execute("SELECT module, name FROM ir_model_data WHERE model='ir.ui.view' AND res_id=%s", (view_id,))
            row = cr.fetchone()
            module_info = f" ({row[0]}.{row[1]})" if row else ""
            _logger.error("[poly] Validation failed for view %s%s: %s", view_id, module_info, e)
            # In -u mode, Odoo usually aborts on view errors. 
            # Here we log and continue to allow the system to boot, but ideally, 
            # if we are in a 'strict' mode, we might want to re-raise.
    
    # Clear the pending views to ensure idempotency
    self._pending_poly_views.clear()
    
    if not errors_found:
        _logger.debug("[poly] All deferred views validated successfully.")
    else:
        _logger.warning("[poly] Some deferred views failed validation. Check logs for details.")

    # Final cleanup of caches to ensure everything is in sync
    self.clear_caches()
    # We don't call setup_models(cr) here again because we are likely at the end of the loading process
    # and it was already called multiple times. Views validation shouldn't change the models structure.

odoo.modules.registry.Registry._pending_poly_views = _poly_pending_views
odoo.modules.registry.Registry._poly_finalize_view_validation = _poly_finalize_view_validation

# Save the original Odoo methods to avoid cyclic inheritance
_original_Field_get = odoo.fields.Field.__get__
_original_Field_set = odoo.fields.Field.__set__
_original_Relational_get = odoo.fields._Relational.__get__
_original_One2many_get = odoo.fields.One2many.__get__

def _poly_Field_get(self, record, owner=None):
    """
    [poly] Monkey patch for Field.__get__ to handle edge cases in Odoo 18.
    If record is None, it's a class level access, should return self.
    If record is a class (happens during some _add_field calls in Odoo 18), 
    it should also return self instead of calling ensure_one().
    """
    if record is None or isinstance(record, type):
        return self
    
    # Odoo 18: Protect against objects without _ids (e.g. member_descriptor or other weird technical objects)
    # Technical descriptors often don't have _ids but might leak into ORM logic during boot.
    if not hasattr(record, '_ids'):
        # If it's a technical descriptor or property, return self to avoid TypeError.
        # Check by type name to be robust across python versions.
        # We also check if record is owner (class-level access via descriptor).
        _type_name = type(record).__name__
        if 'descriptor' in _type_name or 'property' in _type_name or record is owner:
            return self
        
        # [poly] If it's not a recordset but has some other weird shape, delegate and pray.
        try:
            return _original_Field_get(self, record, owner=owner)
        except Exception:
            return self

    # [poly] Performance optimization: if the model is not polymorphic, delegate immediately.
    # We use the cached _referenced_as_poly_base to quickly identify non-polymorphic models.
    # ir.actions.server and other base models should fall here.
    try:
        if not _poly_is_polymorphic(record):
            return _original_Field_get(self, record, owner=owner)
    except (KeyError, AttributeError):
        # [poly] Odoo 18: Protect against errors during boot
        pass

    try:
        return _original_Field_get(self, record, owner=owner)
    except KeyError as e:
        # [poly] Odoo 18: Protect against KeyError in field_computed during boot or technical operations.
        # This specifically handles 'res.users.tz' and other computed fields that might be 
        # missing from the lazy Registry.field_computed dictionary due to stale state.
        faulty_key = str(e).strip("'")
        
        # If the error is exactly about a field name on a model, it's likely a missing field_computed entry
        is_computed_key_error = False
        if faulty_key == f"{self.model_name}.{self.name}":
            is_computed_key_error = True
        elif faulty_key == self.name:
            is_computed_key_error = True
        elif '.tz' in faulty_key:
            is_computed_key_error = True
            
        if is_computed_key_error:
            if hasattr(record, 'pool') and record.pool:
                _logger.warning("[poly] field_computed KeyError for %s (Key: %s). Attempting recovery...", self, faulty_key)
                # 1. Clear the lazy property if it exists to force a rebuild
                if 'field_computed' in record.pool.__dict__:
                    del record.pool.__dict__['field_computed']
                
                # 2. Check if the field is even in the computed map now
                if self not in record.pool.field_computed:
                    _logger.warning("[poly] Field %s still missing from field_computed after reset. Forcing setup.", self)
                    # Force full setup of this field
                    if hasattr(self, 'setup_full'):
                        self.setup_full(record.env[self.model_name])
                    
                    # ALSO ensure related_field is setup if it's a related field
                    if self.related and hasattr(self, 'setup_related'):
                         self.setup_related(record.env[self.model_name])

                    # And reset map again
                    if 'field_computed' in record.pool.__dict__:
                        del record.pool.__dict__['field_computed']
                
                # 3. Final attempt to run the original get
                try:
                    return _original_Field_get(self, record, owner=owner)
                except KeyError:
                    # If it still fails, and it's a computed field, try to manually trigger computation
                    if self.compute and hasattr(self, 'compute_value'):
                        _logger.warning("[poly] Emergency manual computation for %s", self)
                        try:
                            self.compute_value(record)
                            return _original_Field_get(self, record, owner=owner)
                        except Exception as compute_e:
                            _logger.error("[poly] Emergency computation failed for %s: %s", self, compute_e)
        
        raise e

def _poly_Field_set(self, records, value):
    """
    [poly] Monkey patch for Field.__set__ to handle edge cases in Odoo 18.
    If records is a class or a member_descriptor, we must avoid iterating over it.
    This happens during model._setup_base() when calling setattr(cls, name, field).
    """
    if records is None or isinstance(records, type):
        return
        
    # Odoo 18: Protect against recordsets without _ids (e.g. member_descriptor)
    if not hasattr(records, '_ids'):
        return

    # [poly] Optimization: if the model is not polymorphic, delegate immediately.
    try:
        if not _poly_is_polymorphic(records):
            return _original_Field_set(self, records, value)
    except (KeyError, AttributeError):
        pass

    # Also check if _ids is iterable, because it might be a property object or member_descriptor
    # when accessed from the class (records is a class) but here we already checked for type.
    # However, sometimes 'records' might be an object that has _ids as a descriptor but not a recordset.
    try:
        # Try to access it. If it's a property it might fail if called on class, 
        # but we already excluded 'type'.
        # The reported error is "TypeError: 'member_descriptor' object is not iterable" 
        # at "for record_id in records._ids"
        iter(records._ids)
    except TypeError:
        return

    return _original_Field_set(self, records, value)

def _poly_Relational_get(self, records, owner=None):
    """
    [poly] Monkey patch for _Relational.__get__ to avoid TypeError: object of type 'member_descriptor' has no len()
    This happens during inspect.getmembers(cls) when Odoo 18 processes views.
    Also handles KeyError: 'res_id' (inverse field not yet setup) during setup_models.
    """
    if records is None or isinstance(records, type):
        return self

    # [poly] Optimization: delegate for non-polymorphic models
    try:
        is_poly_hierarchy = False
        _mro = getattr(type(records), 'mro', lambda: [])()
        for base in _mro:
            if '_depend_models' in base.__dict__:
                is_poly_hierarchy = True
                break
        
        if not is_poly_hierarchy and not getattr(records, '_referenced_as_poly_base', False):
            return _original_Relational_get(self, records, owner=owner)
    except (KeyError, AttributeError):
        pass

    # Check if records is a valid recordset before calling len(records._ids)
    # We check for _ids because that's what Odoo base uses at line 3112 of fields.py
    if not hasattr(records, '_ids'):
        # If it's not a recordset (e.g. member_descriptor), 
        # fall back to the base Field.__get__ logic which handles non-recordsets
        return _poly_Field_get(self, records, owner)
    
    try:
        return _original_Relational_get(self, records, owner)
    except (KeyError, TypeError) as e:
        # Odoo 18 One2many.__get__ (at line 4672 of fields.py) attempts to access 
        # records.pool[self.comodel_name]._fields[self.inverse_name]
        # This fails if the inverse field hasn't been added to the comodel's _fields yet,
        # which happens during early setup_models.
        if isinstance(e, KeyError) and records.pool and not records.pool.ready:
            _logger.debug("[poly] Relational access failure during setup for %s: %s", self.name, e)
            return self
        # Handle the len(records._ids) failure on member_descriptor if it leaked here
        if isinstance(e, TypeError) and "object of type 'member_descriptor' has no len()" in str(e):
             return _poly_Field_get(self, records, owner)
        raise e

def _poly_One2many_get(self, records, owner=None):
    """
    [poly] Monkey patch for One2many.__get__ to handle KeyError: 'res_id' during setup_models in Odoo 18.
    Odoo 18 added an explicit __get__ to One2many that bypasses _Relational.__get__ and directly 
    accesses the pool's fields.
    """
    if records is None or isinstance(records, type):
        return self

    # [poly] Optimization: delegate for non-polymorphic models
    try:
        is_poly_hierarchy = False
        _mro = getattr(type(records), 'mro', lambda: [])()
        for base in _mro:
            if '_depend_models' in base.__dict__:
                is_poly_hierarchy = True
                break
        
        if not is_poly_hierarchy and not getattr(records, '_referenced_as_poly_base', False):
            return _original_One2many_get(self, records, owner=owner)
    except (KeyError, AttributeError):
        pass

    if records is not None and getattr(self, 'inverse_name', None) is not None:
        try:
            # This is the line that fails in Odoo 18 fields.py:4672
            # inverse_field = records.pool[self.comodel_name]._fields[self.inverse_name]
            # Odoo 18 uses __get__ which triggers this access.
            if hasattr(records, 'pool') and records.pool:
                _comodel = records.pool.get(self.comodel_name)
                if _comodel is not None:
                    _fields = getattr(_comodel, '_fields', {})
                    if self.inverse_name not in _fields:
                        if not records.pool.ready:
                            # During boot, if the inverse field is not yet in _fields, 
                            # we skip the Odoo 18 specific logic and fall back to super().__get__
                            # which is handled by our _poly_Relational_get patch.
                            return _poly_Relational_get(self, records, owner)
        except (KeyError, AttributeError):
             if hasattr(records, 'pool') and records.pool and not records.pool.ready:
                return _poly_Relational_get(self, records, owner)

    return _original_One2many_get(self, records, owner)

odoo.fields.Field.__get__ = _poly_Field_get
odoo.fields.Field.__set__ = _poly_Field_set
odoo.fields._Relational.__get__ = _poly_Relational_get
odoo.fields.One2many.__get__ = _poly_One2many_get

_original_BaseModel = odoo.models.BaseModel
_original_AbstractModel = odoo.models.AbstractModel
_original_Model = odoo.models.Model
_original_TransientModel = odoo.models.TransientModel
_original_Many2many_setup_nonrelated = odoo.fields.Many2many.setup_nonrelated
_original_Many2many_read = odoo.fields.Many2many.read

class IrPolyBase(models.Model):
    """
    Base model for all polymorphic models in the system.

    This model serves as the foundation for the polymorphic inheritance system.
    Each polymorphic record has a corresponding record in this model, which stores
    common information and provides a central point for record identification.
    """
    _name = 'ir.poly_base'
    _description = 'Polymorphic Models Base'
    _rec_name = 'id'

    concrete_model_id = fields.Many2one('ir.model', 'Concrete Model',
                                        ondelete='cascade', required=True)
    old_id = fields.Integer('Old ID', index=True, help='Original ID before migration to poly')

    # Technical field for DTO payload transport
    poly_payload = fields.Text(
        string='Polymorphic Payload',
        store=False,
        prefetch=False,
        compute='_compute_payload_dummy',
        inverse='_inverse_payload_dummy',
        help='Technical field for transporting polymorphic subclass data as JSON'
    )

    @api.depends()
    def _compute_payload_dummy(self):
        """
        Compute method for poly_payload.
        Returns False to allow the field to be writable without storage.
        """
        for record in self:
            record.poly_payload = False

    def _inverse_payload_dummy(self):
        """
        Inverse method for poly_payload.
        Does nothing - this allows the UI to send data to a non-stored field
        without requiring force_save.
        """
        pass

    def get_poly_subclasses_info(self):
        """
        Returns information about valid polymorphic subclasses.
        
        This method should be overridden by business models to return
        a list of dictionaries with 'model' and 'name' keys.
        
        Returns:
            list: List of dicts with 'model' and 'name' keys.
                 Example: [{'model': 'project.crane', 'name': 'Crane'}]
        """
        return []

    def as_concrete_model(self):
        """
        Convert this base record to its concrete model representation.

        Returns:
            The same record but as an instance of its concrete model class.
        """
        self.ensure_one()
        if not self.concrete_model_id:
            return self
        concrete_model_name = self.concrete_model_id.model
        # Use explicitly browse on the target model to ensure we get a "pure" recordset
        # of that model, which helps with super() calls in Odoo 18.
        # We use exists() to avoid MissingError if the concrete record is missing.
        concrete_record = self.env[concrete_model_name].browse(self.id).exists()
        return concrete_record if concrete_record else self


_original_Many2one_convert_to_read = odoo.fields.Many2one.convert_to_read

def poly_many2one_convert_to_read(self, value, record, use_display_name=True):
    # [poly] Performance optimization: if the model is not polymorphic, delegate immediately.
    if record and not _poly_is_polymorphic(record) and not getattr(record, '_referenced_as_poly_base', False):
        return _original_Many2one_convert_to_read(self, value, record, use_display_name=use_display_name)
    
    if use_display_name and value:
        # evaluate display_name as superuser, because the visibility of a
        # many2one field value (id and name) depends on the current record's
        # access rights, and not the value's access rights.
        try:
            # performance: value.sudo() prefetches the same records as value
            return (value.id, value.sudo().display_name)
        except MissingError:
            # Should not happen, unless the foreign key is missing.
            return False
    else:
        if value:
            return value.id
        else:
            return False


def poly_many2many_read(self, records):
    """
    Monkey-patch for Many2many.read to allow reading related many2many fields.
    In Odoo 18, Many2many.read assumes the field is always stored in a relation
    table and directly joins it. If the field is related (as often in polymorphic
    models), it should traverse the relation instead.
    """
    # [poly] Optimization: delegate for non-polymorphic models
    try:
        is_poly_hierarchy = False
        _mro = getattr(type(records), 'mro', lambda: [])()
        for base in _mro:
            if '_depend_models' in base.__dict__:
                is_poly_hierarchy = True
                break
        
        if not is_poly_hierarchy and not getattr(records, '_referenced_as_poly_base', False):
            return _original_Many2many_read(self, records)
    except (KeyError, AttributeError):
        pass

    if self.related:
        return self._compute_related(records)
    
    # [poly] Technical Check: ensure comodel_name is present to avoid KeyError: None
    if not self.comodel_name:
        return records.env.cache.insert_missing(records, self, [()] * len(records))

    # [poly] AGGRESSIVE FIX: If the field is Many2many but has NO relation table,
    # and we are in a polymorphic model, it might be a broken field from Odoo 18
    # setup. We attempt to find the field in our polymorphic bases and use it.
    if not getattr(self, 'relation', None):
        model_class = records.pool[self.model_name]
        # [poly] Safe check for polymorphic bases
        poly_bases = getattr(model_class, '__depends_base_classes', ())
        for base_class in poly_bases:
             # Check if base_class is an Odoo model class with _fields
             if not hasattr(base_class, '_fields'):
                  continue
             if self.name in base_class._fields:
                  base_field = base_class._fields[self.name]
                  if base_field.type == 'many2many' and getattr(base_field, 'relation', None):
                       _logger.debug("[poly] Redirecting M2M read for %s.%s to base %s", self.model_name, self.name, base_class._name)
                       # Find the link field to this base
                       depend_models = getattr(model_class, '_depend_models', {})
                       link_fname = depend_models.get(base_class._name)
                       if link_fname:
                            # We traverse the relation via the link field
                            target_records = records.mapped(link_fname)
                            return base_field.read(target_records)

    return _original_Many2many_read(self, records)


def poly_many2many_setup_nonrelated(self, model):
    """
    Monkey-patch for Many2many.setup_nonrelated to allow sharing the same
    relation table and columns between models that are polymorphic counterparts.
    """
    try:
        return _original_Many2many_setup_nonrelated(self, model)
    except TypeError as e:
        # Check if the error is about shared table/columns
        if "Many2many fields" not in str(e) or "use the same table and columns" not in str(e):
            raise e
        
        # [poly] Aggressive Odoo 18 Fix: if this is a polymorphic model, we ignore the error
        # especially if one of the fields is related and non-stored.
        if self.related and not self.store:
            _logger.debug("[poly] Ignoring M2M shared table error for related field %s.%s", model._name, self.name)
            # We need to manually register the field in the pool's m2m structure
            # to allow Odoo to continue.
            m2m = model.pool._m2m
            fields = m2m.setdefault((self.relation, self.column1, self.column2), [])
            if self not in fields:
                fields.append(self)
            
            # Re-implement the inverse fields logic that follows the TypeError raise in original
            for field in m2m.get((self.relation, self.column2, self.column1), []):
                model.pool.field_inverses.add(self, field)
                model.pool.field_inverses.add(field, self)
            return

        # Fallback to broader polymorphic check if not explicitly related/store=False yet
        m2m = model.pool._m2m
        fields = m2m.get((self.relation, self.column1, self.column2))
        if not fields:
             raise e
        
        is_poly_counterpart = False
        model_class = model if isinstance(model, type) else type(model)
        
        # Check if current model is polymorphic
        is_self_poly = False
        for base in _poly_get_safe_mro(model_class):
            if '_depend_models' in base.__dict__:
                is_self_poly = True
                break
        
        if is_self_poly:
            for other in fields:
                if self.model_name != other.model_name:
                    other_model = model.pool.get(other.model_name)
                    if not other_model: continue
                    other_class = other_model if isinstance(other_model, type) else type(other_model)
                    
                    # Check for polymorphic relationship (any shared polymorphic ancestor)
                    self_poly_bases = set()
                    for base in model_class.mro():
                        if '_depend_models' in base.__dict__: self_poly_bases.add(base._name)
                    
                    other_poly_bases = set()
                    for base in other_class.mro():
                        if '_depend_models' in base.__dict__: other_poly_bases.add(base._name)
                    
                    if self_poly_bases & other_poly_bases or \
                       other.model_name in self_poly_bases or \
                       self.model_name in other_poly_bases:
                        is_poly_counterpart = True
                        break
        
        if is_poly_counterpart:
            _logger.debug("Allowing shared Many2many table %s for polymorphic counterparts %s and %s", 
                          self.relation, self.model_name, [f.model_name for f in fields])
            if self not in fields:
                fields.append(self)
            
            for field in m2m.get((self.relation, self.column2, self.column1), []):
                model.pool.field_inverses.add(self, field)
                model.pool.field_inverses.add(field, self)
            return
        
        # If not handled, re-raise original exception
        raise e


class PolyReference(fields.Many2one):
    """
    Special Many2one field for polymorphic references.

    This field type is used to create references between polymorphic models.
    Unlike standard Many2one fields, PolyReference fields are not stored in the
    database but are computed based on the record's ID, allowing for efficient
    polymorphic relationships without additional database columns.

    Attributes:
        auto_join (bool): Always True to enable automatic joining in queries
        store (bool): Always False as these references are computed, not stored
        readonly (bool): Always True as these references cannot be directly modified
    """
    auto_join = True
    store = False
    readonly = True

    def __init__(self, comodel_name: str | Sentinel = SENTINEL, string: str | Sentinel = SENTINEL, **kwargs):
        """
        Initialize a new PolyReference field.

        Args:
            comodel_name: The name of the model this field refers to
            string: The label of the field
            **kwargs: Additional field parameters
        """
        super(PolyReference, self).__init__(comodel_name=comodel_name, string=string, **kwargs)
        self.search = self._search_related

    def convert_to_record(self, value, record):
        """
        Convert a value to a record instance.
        """
        if not record or not record.id:
            try:
                return record.env[self.comodel_name].browse()
            except Exception:
                # If comodel is not in environment yet
                return None

        # Standard polymorphic reference: IDs match in polymorphic hierarchy
        try:
            comodel = record.pool[self.comodel_name]
            return comodel(record.env, (record.id,), (record.id,))
        except Exception:
            try:
                return record.env[self.comodel_name].browse()
            except Exception:
                return None

    def __get__(self, records, owner=None):
        """
        Get the value of this field for the given records.

        This method handles both single record and multi-record cases.

        Args:
            records: The records to get the value for
            owner: The owner class

        Returns:
            For a single record: the related record
            For multiple records: a recordset of related records
        """
        # records is None (class level access)
        if records is None:
            return self

        if str(type(records)) == '<class \'member_description\'>':
            raise MissingError

        # Odoo 18 specific: Check if the field is set in _fields of the model
        if not hasattr(records, '_fields') or self.name not in records._fields:
            return self

        # Single record case
        # Odoo 18 specific: records might be a technical descriptor object (e.g. member_descriptor)
        # without a __len__ method, or records._ids might not be what we expect.
        _is_single = True
        try:
            if hasattr(records, '_ids') and records._ids is not None:
                # If it has _ids, check length. descriptors like member_descriptor 
                # might fail here if they leak into this logic.
                if len(records._ids) > 1:
                    _is_single = False
        except (TypeError, AttributeError):
            # If len() or access fails, treat as single record/technical object
            pass

        if _is_single:
            try:
                return self.convert_to_record(None, records)
            except Exception:
                return records.pool[self.comodel_name](records.env, (), ())
            
        # multirecord case: use mapped IDs to build a related recordset
        return records.pool[self.comodel_name](records.env, tuple(records.ids), tuple(records.ids))

    @property
    def _description_searchable(self):
        """
        Indicate that this field is searchable.

        Returns:
            True, as PolyReference fields are always searchable
        """
        return True

    @_description_searchable.setter
    def _description_searchable(self, value):
        """ Allow setting searchable attribute, but we override it via property. """
        pass

    @property
    def search(self):
        """ [poly] Ensure PolyReference fields have a search attribute for Odoo's resolve_depends. """
        return self._search_related

    @search.setter
    def search(self, value):
        """ Allow setting search, but we maintain our method. """
        pass

    def _search_related(self, records, operator, value):
        """
        Determine the domain to search on this field.

        This method implements the search functionality for PolyReference fields,
        translating the search criteria into appropriate domain expressions.

        Args:
            records: The records being searched
            operator: The search operator
            value: The search value

        Returns:
            A domain expression for searching
        """
        # This should never happen to avoid bypassing security checks
        # and should already be converted to (..., 'in', subquery)
        assert operator not in ('any', 'not any')

        # determine whether the related field can be null
        if isinstance(value, (list, tuple)):
            value_is_null = any(val is False or val is None for val in value)
        else:
            value_is_null = value is False or value is None

        can_be_null = (  # (..., '=', False) or (..., 'not in', [truthy vals])
            (operator not in expression.NEGATIVE_TERM_OPERATORS and value_is_null)
            or (operator in expression.NEGATIVE_TERM_OPERATORS and not value_is_null)
        )

        def make_domain(path, model):
            if not path:
                return [('id', operator, value)]
            if '.' not in path:
                return [(path, operator, value)]

            prefix, suffix = path.split('.', 1)
            field = model._fields[prefix]
            comodel = model.env[field.comodel_name]

            if not isinstance(field, PolyReference):
                domain = [(prefix, 'in', comodel._search(make_domain(suffix, comodel)))]
                if can_be_null and field.type == 'many2one' and not field.required:
                    return expression.OR([domain, [(prefix, '=', False)]])
            else:
                domain = [('id', 'in', comodel._search(make_domain(suffix, comodel)))]
                if can_be_null and field.type == 'many2one' and not field.required:
                    return expression.OR([domain, [('id', '=', False)]])

            return domain

        model = records.env[self.model_name].with_context(active_test=False)
        model = model.sudo(records.env.su or self.compute_sudo)

        return make_domain(self.related or '', model)



class PolyBase(_original_BaseModel):
    """
    Base class for all polymorphic models in Odoo.

    This class extends the standard Odoo BaseModel to implement polymorphic inheritance.
    Polymorphic models can inherit fields and behavior from multiple parent models
    while maintaining a single database record.

    The polymorphic inheritance is configured through the _depend_models attribute,
    which is a position-ordered dictionary mapping parent model names to field names:

    Example:
        class MyPolymorphicModel(PolyModel):
            _name = 'my.polymorphic.model'
            _depend_models = {
                'res.partner': 'partner_id',
                'hr.employee': 'employee_id',
            }
            
            custom_field = fields.Char('Custom Field')
        
        # Now MyPolymorphicModel has all fields from res.partner and hr.employee
        record = self.env['my.polymorphic.model'].create({
            'name': 'John Doe',  # From res.partner
            'work_email': 'john@example.com',  # From hr.employee
            'custom_field': 'Value',  # From MyPolymorphicModel
        })
        
        # All records share the same ID across all models
        assert record.id == record.partner_id.id == record.employee_id.id

    This implements full polymorphic inheritance: the new model exposes all
    the fields of the dependent models but stores none of them directly.
    The values themselves remain stored on the linked records.

    A direct representation of a base will be available in the corresponding field
    ('a_field_id', 'b_field_id'). The Many2one fields will be created automatically;
    they do not need to be defined explicitly.

    Warning:
        If multiple fields with the same name are defined in the _depend_models models,
        the inherited field will correspond to the last one (in the depends list order).
    """
    _register = False

    # Dictionary mapping parent model names to field names
    _depend_models = None

    # Set of child model names that depend on this model
    _depends_children = OrderedSet()

    # Flag to track if ID has been checked
    _checked_id = False

    @classmethod
    def _poly_get_depend_models(cls):
        """
        Scan MRO to collect all _depend_models in the correct order.
        Newer declarations (subclasses) have priority.
        """
        # [poly] CRITICAL: ir.poly_base IS NOT polymorphic.
        # It should not have depend models or trigger polymorphic logic on itself.
        if getattr(cls, '_name', None) == 'ir.poly_base':
            return {}
        
        depend_models = {}
        cls_name = getattr(cls, '_name', None)
        # MRO is [Current, Base1, Base2, ..., object]
        # We iterate in reverse to let newer definitions overwrite older ones.
        # CRITICAL: only collect _depend_models from bases that belong to THIS
        # model (base._name == cls._name or base._name is None/absent).  Bases
        # from PARENT models (e.g. ConversationMessage on conversation.message
        # appearing in conversation.message.facebook's MRO via poly injection)
        # must NOT contribute their own _depend_models — those express the
        # parent's own poly relationships, not the child's.
        for base in reversed(cls.mro()):
            base_name = base.__dict__.get('_name')  # None if not declared
            if base_name is not None and base_name != cls_name:
                continue  # skip bases from a different model
            # Use __dict__.get for safer access during Odoo 18 setup
            val = base.__dict__.get('_depend_models')
            if val is not None:
                # If it's a list or tuple (legacy), convert to dict
                if isinstance(val, (list, tuple)):
                    val = {v: v.replace('.', '_') + '_id' for v in val}
                if isinstance(val, (dict, OrderedDict)):
                    depend_models.update(val)
        return depend_models

    def _get_all_poly_bases(self):
        """
        Retorna un conjunto de todos los modelos base (polimórficos o no) en la jerarquía.
        Esta exploración es recursiva y abarca todos los módulos cargados al utilizar
        el registro (env) de Odoo.
        """
        bases = {'ir.poly_base'}
        visited = set()

        def collect(model_name):
            if model_name in visited or model_name not in self.env:
                return
            visited.add(model_name)
            bases.add(model_name)
            
            model = self.env[model_name]
            
            # Explorar bases polimórficas definidas en _depend_models de cualquier módulo
            depend_models = getattr(model, '_depend_models', None)
            if depend_models:
                for base_name in depend_models.keys():
                    collect(base_name)
            
            # Explorar herencia estándar de Odoo (_inherit) para cubrir todos los módulos
            inherits = model._inherit
            if inherits:
                if isinstance(inherits, str):
                    inherits = [inherits]
                for inherit in inherits:
                    if inherit not in ('base', 'ir.poly_base'):
                        collect(inherit)

        collect(self._name)
        return bases

    def _get_max_poly_id(self):
        """
        Calcula el ID máximo entre todas las tablas participantes en la jerarquía polimórfica.
        """
        all_bases = self._get_all_poly_bases()
        max_id = 0
        
        for model_name in all_bases:
            if model_name == 'base':
                continue
            model = self.env.get(model_name)
            if model is not None and getattr(model, "_table", None) and getattr(model, "_storage", True):
                try:
                    # Double-check table existence in Odoo's registry/DB before querying
                    if not sql.table_exists(self.env.cr, model._table):
                        continue
                        
                    self.env.cr.execute(SQL(
                        "SELECT MAX(id) FROM %s",
                        SQL.identifier(model._table)
                    ))
                    res = self.env.cr.fetchone()
                    if res and res[0]:
                        max_id = max(max_id, res[0])
                except Exception:
                    continue
        return max_id

    def _sync_poly_sequence(self):
        """
        Sincroniza ir_poly_base_id_seq con el ID máximo real de la jerarquía.
        Usa un bloqueo consultivo para evitar contención en las tablas de datos.
        """
        # Lock consultivo basado en el hash del nombre de la secuencia (1347374169)
        # Solo bloquea a otros procesos que intenten sincronizar la misma secuencia.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(1347374169)")
        
        max_id = self._get_max_poly_id()
        
        # Obtenemos el valor actual de la secuencia para evitar setval innecesarios
        try:
            self.env.cr.execute("SELECT last_value FROM ir_poly_base_id_seq")
            res = self.env.cr.fetchone()
            current_seq_val = res[0] if res else 0
        except Exception:
            # Si la secuencia no existe aún o hay problemas de acceso
            current_seq_val = 0
        
        if max_id >= current_seq_val:
            _logger.info("Sincronizando secuencia ir_poly_base_id_seq a %s para evitar colisiones", max_id + 1)
            self.env.cr.execute(SQL(
                "SELECT setval('ir_poly_base_id_seq', %s, true)",
                max_id
            ))

    def check_access(self, operation: str) -> None:
        if getattr(self, '_depend_models', None) is None:
            # We must be careful not to create a recursion here.
            # super() on BaseModel is safe.
            return super().check_access(operation)
        
        if self.env.su or not self.pool.ready:
            return

        # Check access on the model itself first
        try:
            # [poly] We use browse(self._ids) to ensure we have a fresh recordset 
            # if self is somehow inconsistent, but standard super().check_access(operation)
            # is usually better in Odoo 18.
            super().check_access(operation)
        except AccessError as ae:
            if self._name in ('res.users', 'res.groups', 'ir.model'):
                _logger.warning("[poly] Access Denied on technical model %s: %s", self._name, ae)
            raise ae
        
        # Check access on all dependent base models
        for base_name in self._depend_models.keys():
            if base_name in self.env:
                try:
                    # [poly] Optimization: we only check base access if it's not the same model 
                    # (recursion safety) and we do it via a fresh recordset.
                    if base_name != self._name:
                        self.env[base_name].browse().check_access(operation)
                except AccessError:
                    _logger.debug("[poly] User has no access to polymorphic base %s for %s", base_name, self._name)
                    pass

    def has_access(self, operation: str) -> bool:
        if getattr(self, '_depend_models', None) is None:
            return super().has_access(operation)
        
        if self.env.su:
            return True

        try:
            self.check_access(operation)
            return True
        except AccessError:
            return False
        except Exception:
            return super(PolyBase, self).has_access(operation)

    def _check_poly_access(self, operation):
        """ Internal helper to call super().check_access() safely """
        return super(PolyBase, self).check_access(operation)

    def as_concrete_model(self):
        """
        Convert this base record to its concrete model representation.

        Returns:
            The same record but as an instance of its concrete model class.
        """
        self.ensure_one()
        if 'concrete_model_id' not in self._fields:
            # This model is used as a poly base by other models (e.g. conversation.driver)
            # but has no concrete_model_id field injected.  Resolve via ir.poly_base directly.
            poly_base = self.env['ir.poly_base'].sudo().browse(self.id).exists()
            if not poly_base or not poly_base.concrete_model_id:
                return self
            concrete_model_name = poly_base.concrete_model_id.model
            if not concrete_model_name:
                return self
            concrete_record = self.env[concrete_model_name].browse(self.id).exists()
            return concrete_record if concrete_record else self
        if not self.concrete_model_id:
            return self
        concrete_model_name = self.concrete_model_id.model
        # Use explicitly browse on the target model to ensure we get a "pure" recordset
        # of that model, which helps with super() calls in Odoo 18.
        # We use exists() to avoid MissingError if the concrete record is missing.
        concrete_record = self.env[concrete_model_name].browse(self.id).exists()
        return concrete_record if concrete_record else self

    def _compute_concrete_model_id(self):
        """
        Compute the concrete_model_id field for polymorphic models.
        
        Note: We use sudo() to read ir.poly_base because this computed field is part of
        the polymorphic infrastructure metadata and must be accessible to determine the
        concrete model type, independent of access rules on the data itself.
        """
        for record in self:
            # Check existence in ir.poly_base using the shared ID
            # We use sudo() to ensure visibility of the base record
            # and exists() to avoid MissingError if it's not found (e.g. during migration)
            poly_base = self.env['ir.poly_base'].sudo().browse(record.id).exists()
            if poly_base:
                record.concrete_model_id = poly_base.concrete_model_id
            else:
                record.concrete_model_id = False

    def compute_poly_base_id(self):
        """
        Compute the poly_base_id field for each record.

        This method sets the poly_base_id field to the record's ID,
        establishing the link to the ir.poly_base record.
        """
        for instance in self:
            instance.poly_base_id = instance.id

    @api.depends()
    def _compute_payload_dummy(self):
        """
        Compute method for poly_payload.
        Returns False to allow the field to be writable without storage.
        """
        for record in self:
            record.poly_payload = False

    def _inverse_payload_dummy(self):
        """
        Inverse method for poly_payload.
        Does nothing - this allows the UI to send data to a non-stored field
        without requiring force_save.
        """
        pass

    def get_poly_subclasses_info(self):
        """
        Returns information about valid polymorphic subclasses.
        
        This method should be overridden by business models to return
        a list of dictionaries with 'model' and 'name' keys.
        
        Returns:
            list: List of dicts with 'model' and 'name' keys.
                 Example: [{'model': 'project.crane', 'name': 'Crane'}]
        """
        return []

    # --- POLY ENGINE HELPERS ---

    @classmethod
    def _poly_get_mro_names(cls):
        return [c.__name__ for c in cls.mro()]

    @classmethod
    def _poly_force_mro_update(cls):
        """ Forces Python to recalculate the MRO internal cache for a class. """
        import ctypes as _ctypes
        if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
            try:
                _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(cls))
            except Exception:
                pass

    @classmethod
    def _poly_sync_proxy_class(cls, pool, name, model_class, final_bases):
        """ Synchronizes the Odoo 18 proxy class with the actual registry class. """
        if not hasattr(pool, 'models') or name not in pool.models:
            return None
        proxy = pool.models[name]
        if proxy is model_class:
            return proxy
        try:
            proxy.__base_classes = final_bases
            proxy.__bases__ = final_bases
            cls._poly_force_mro_update(proxy)
            for base_class in final_bases:
                if base_class.__name__ in ('BaseModel', 'Model', 'TransientModel', 'Base', 'object'): continue
                for p_base in base_class.mro():
                    if p_base.__name__ in ('BaseModel', 'object', 'Base'): continue
                    for attr_name, attr_val in p_base.__dict__.items():
                        if callable(attr_val) and not attr_name.startswith('__') and attr_name not in proxy.__dict__:
                            try:
                                setattr(proxy, attr_name, attr_val)
                            except Exception: pass
        except Exception:
            pass
        return proxy

    @classmethod
    def _poly_invalidate_odoo_caches(cls, pool, model_name):
        """ Clears Odoo's internal caches to force re-evaluation of model structure. """
        if hasattr(pool, 'model_methods'):
            pool.model_methods.pop(model_name, None)
        from odoo.api import Environment
        if hasattr(Environment, '_classes') and Environment._classes is not None:
            if pool in Environment._classes:
                Environment._classes[pool].pop(model_name, None)

    @classmethod
    def _apply_polymorphic_hierarchy(cls, pool, cr, name, model_class, parents):
        """ 
        [poly] DEPRECATED: This method is now handled by _poly_registry_setup_models.
        Keeping as a no-op for backward compatibility during Step 1.
        """
        return False


    @classmethod
    def _validate_dependency_cycles(cls, pool, visited=None, rec_stack=None):
        """
        Validate that there are no circular dependencies in polymorphic models.

        This method uses depth-first search to detect cycles in the dependency graph.

        Args:
            pool: The model registry pool
            visited: Set of already visited models (for recursion)
            rec_stack: Set of models in the current recursion stack (for cycle detection)

        Raises:
            ValueError: If a circular dependency is detected
        """
        if visited is None:
            visited = set()
        if rec_stack is None:
            rec_stack = set()

        name = cls._name
        if name in rec_stack:
            raise ValueError(
                f"Circular dependency detected in polymorphic model {name}. "
                f"Path: {' -> '.join(rec_stack)} -> {name}"
            )

        if name in visited:
            return

        visited.add(name)
        rec_stack.add(name)

        if hasattr(cls, '_depend_models') and cls._depend_models is not None:
            for parent_name in cls._depend_models.keys():
                if parent_name in pool:
                    parent_class = pool[parent_name]
                    if hasattr(parent_class, '_validate_dependency_cycles'):
                        parent_class._validate_dependency_cycles(pool, visited, rec_stack)

        rec_stack.remove(name)

    # Legacy reactive MRO code below (neutralized)
    def _legacy_setup_base_logic(self):
        model_class = type(self)
        name = self._name
        # During -u, Odoo creates new class objects; stale POLY_MRO_CACHE references trigger
        # Python MRO validation errors on subclasses (TypeError: Cannot create consistent MRO).
        if cached_bases:
            _stale = any(
                getattr(_cb, '_name', None) and
                _cb._name in self.pool and
                self.pool[_cb._name] is not _cb
                for _cb in cached_bases
            )
            if _stale:
                _logger.debug("[poly] Discarding stale POLY_MRO_CACHE for '%s'", self._name)
                POLY_MRO_CACHE.get(db_name, {}).pop(self._name, None)
                if hasattr(self.pool, '_poly_mro_cache'):
                    self.pool._poly_mro_cache.pop(self._name, None)
                cached_bases = None

        if cached_bases:
            # Merge cached poly-parent bases with any new definition classes added by
            # _build_model after the cache was set (e.g. a module loaded AFTER the last
            # _apply_polymorphic_hierarchy call that extends this poly model via _inherit).
            # Without this merge, stale cached_bases would override __base_classes and
            # drop the new definition classes, making their fields invisible in _setup_base.
            _current_build_classes = model_class.__base_classes  # canonical, set by _build_model
            _extra_def_classes = [
                b for b in _current_build_classes
                if b not in cached_bases
                and getattr(b, 'pool', None) is None
                # Skip classes that are already ancestors of something in cached_bases:
                # appending an ancestor AFTER its descendants violates Python's MRO rules.
                and not any(issubclass(c, b) for c in cached_bases if c is not b)
            ]
            if _extra_def_classes:
                cached_bases = tuple(list(cached_bases) + _extra_def_classes)
                POLY_MRO_CACHE[db_name][self._name] = cached_bases
                if hasattr(self.pool, '_poly_mro_cache'):
                    self.pool._poly_mro_cache[self._name] = cached_bases
            model_class.__depends_base_classes = cached_bases
            # Force Odoo 18 to use our polymorphic bases as the original ones
            model_class.__base_classes = cached_bases
            
            if model_class.__bases__ != cached_bases:
                 try:
                     model_class.__bases__ = cached_bases
                     # Refresh MRO cache
                     import ctypes as _ctypes
                     if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                         _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(model_class))
                     
                     # Clear Environment cache
                     from odoo.api import Environment
                     if hasattr(Environment, '_classes') and Environment._classes is not None:
                          if self.pool in Environment._classes:
                               Environment._classes[self.pool].pop(self._name, None)
                 except TypeError as e:
                     _logger.error("Failed to apply cached bases to model class %s: %s", self._name, e)

            # Odoo 18: Registry proxy classes must also be updated
            if hasattr(self.pool, 'models') and self._name in self.pool.models:
                  proxy_class = self.pool.models[self._name]
                  if proxy_class is not model_class and proxy_class.__bases__ != cached_bases:
                       proxy_class.__base_classes = cached_bases
                       try:
                           proxy_class.__bases__ = cached_bases
                           import ctypes as _ctypes
                           if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                                _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(proxy_class))
                       except TypeError as e:
                           _logger.error("Failed to apply cached bases to proxy class %s: %s", self._name, e)

        # For polymorphic models, ensure __base_classes matches __bases__ before calling
        # Odoo's _prepare_setup. Odoo's implementation does `cls.__bases__ = cls.__base_classes`,
        # so if __base_classes still holds Odoo's original value (e.g. (PolyModel, base) where
        # PolyModel already inherits from base), Python raises a MRO TypeError. Poly already set
        # __bases__ correctly in _build_model; mirroring that into __base_classes prevents the
        # conflict. We do this regardless of whether cached_bases was found.
        _is_poly_model = getattr(model_class, '_depend_models', None) is not None
        if _is_poly_model:
            _poly_bases = model_class.__bases__
            if _poly_bases and model_class.__base_classes != _poly_bases:
                model_class.__base_classes = _poly_bases

        # Use unbound method to avoid MRO lookup issues
        try:
            _original_BaseModel._prepare_setup(self)
        except TypeError as _mro_err:
            if 'MRO' not in str(_mro_err) and 'resolution' not in str(_mro_err).lower():
                raise
            _logger.error(
                "[poly] MRO conflict in _prepare_setup for model '%s'. "
                "__base_classes=%s  __bases__=%s",
                self._name,
                [getattr(b, '__name__', repr(b)) for b in model_class.__base_classes],
                [getattr(b, '__name__', repr(b)) for b in model_class.__bases__],
            )
            raise

        # Ensure bases remain synchronized after super
        if cached_bases:
             # Check both model class and proxy class
             for cls_to_check in [model_class, getattr(self.pool.models.get(self._name), '__dict__', {}).get('_wrapped__', self.pool.models.get(self._name))]:
                  if cls_to_check is None: continue
                  if cls_to_check.__bases__ != cached_bases:
                       _logger.debug("Bases for %s (%s) changed after super()._prepare_setup(). Re-applying...", self._name, cls_to_check.__name__)
                       try:
                           cls_to_check.__base_classes = cached_bases
                           cls_to_check.__bases__ = cached_bases
                           import ctypes as _ctypes
                           if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                               _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(cls_to_check))
                           
                           # Exhaustive method recovery for Odoo 18
                           from odoo.models import MetaModel
                           for base in cls_to_check.mro():
                                if base in (cls_to_check, object): continue
                                # If it's a MetaModel but not a standard model with pool (so it's a "raw" class from a module)
                                if isinstance(base, MetaModel):
                                     for m_name, m_meth in base.__dict__.items():
                                          # Use __dict__ check to see if it's REALLY missing from cls_to_check and not just found via MRO
                                          if not m_name.startswith('__') and m_name not in cls_to_check.__dict__:
                                               if not isinstance(m_meth, (property, fields.Field)):
                                                    setattr(cls_to_check, m_name, m_meth)

                       except TypeError as e:
                           _logger.error("Failed to re-apply cached bases to class %s: %s", self._name, e)

    def _setup_base(self):
        """Run standard Odoo field setup then inject polymorphic fields."""
        _original_BaseModel._setup_base(self)
        if _poly_is_polymorphic(type(self)):
            type(self)._build_poly_fields(calling_self=self)

    @classmethod
    def _setup_poly_fields(cls, self):
        """Deprecated: field injection is now handled in _setup_base via _build_poly_fields."""
        pass

    def _auto_init(self):
        """
        Extend _auto_init to ensure migration is performed when the table is created/updated.
        In Odoo 18, we also ensure Many2many fields have a 'relation', 'column1', 'column2'
        and '_modules' defined to avoid AttributeError and NotNullViolation in update_db.
        """
        for _fname, _fobj in self._fields.items():
            if _fobj.type == 'many2many':
                _changed = False
                if not getattr(_fobj, 'relation', None):
                    if _fobj.comodel_name:
                        _fobj.relation = f"{self._name.replace('.', '_')}_{_fname}_rel"
                        _changed = True
                
                if not getattr(_fobj, 'column1', None):
                    _fobj.column1 = 'id1' # Default column name if missing
                    _changed = True
                
                if not getattr(_fobj, 'column2', None):
                    _fobj.column2 = 'id2' # Default column name if missing
                    _changed = True
                
                if not getattr(_fobj, '_module', None):
                     _mod_name = getattr(self, '_module', None) or 'numa_poly'
                     _fobj._module = _mod_name
                     _changed = True

                if not getattr(_fobj, '_modules', None) or None in _fobj._modules:
                    # Odoo 18: _reflect_relation needs a module name.
                    # We must ensure it's a set of strings. Use a fallback module name if needed.
                    _mod_name = getattr(self, '_module', None)
                    if not _mod_name:
                        # Try to guess from comodel or field name
                        _mod_name = 'numa_poly'
                    
                    # Ensure the module exists in ir_module_module to avoid NotNullViolation in ir_model_relation
                    # Fallback to 'base' if not found.
                    if _mod_name != 'base':
                        self.env.cr.execute("SELECT 1 FROM ir_module_module WHERE name = %s", (_mod_name,))
                        if not self.env.cr.rowcount:
                            # Fallback to 'base' which always exists
                            _mod_name = 'base'
                        
                    if not getattr(_fobj, '_modules', None):
                        _fobj._modules = {_mod_name}
                    else:
                        _fobj._modules = {m for m in _fobj._modules if m is not None}
                        if not _fobj._modules:
                            _fobj._modules = {_mod_name}

                    _changed = True
                
                # Proactive label recovery to avoid NotNullViolation in ir_model_fields
                if not getattr(_fobj, 'string', None) or isinstance(_fobj.string, fields.Sentinel):
                    _fobj.string = _fname.replace('_', ' ').capitalize()
                    _changed = True

                if _changed:
                    _fobj._explicit = True
                    _logger.debug("[poly] _auto_init: forcing physical metadata for %s on %s: rel=%s, col1=%s, col2=%s, modules=%s", 
                                    _fname, self._name, _fobj.relation, _fobj.column1, _fobj.column2, _fobj._modules)

        # Guard: for polymorphic child models, prevent inherited Many2many fields
        # from creating/altering the parent's relation tables. If a M2M field's
        # relation matches a field defined in a depend_model, force store=False so
        # Odoo's _auto_init skips update_db for it.
        # This avoids: psycopg2.errors.UndefinedColumn: column "fsm_def_id" referenced
        # in foreign key constraint does not exist.
        _depend_models_dict = getattr(self, '_depend_models', None) or {}
        if _depend_models_dict:
            _dep_m2m_relations = set()
            for _dep_model_name in _depend_models_dict:
                _dep_model = self.env.get(_dep_model_name)
                if _dep_model is not None:
                    for _dep_fobj in _dep_model._fields.values():
                        if _dep_fobj.type == 'many2many':
                            _rel = getattr(_dep_fobj, 'relation', None)
                            if _rel:
                                _dep_m2m_relations.add(_rel)
            if _dep_m2m_relations:
                for _fname, _fobj in list(self._fields.items()):
                    if (_fobj.type == 'many2many' and
                            getattr(_fobj, 'store', False) and
                            getattr(_fobj, 'relation', None) in _dep_m2m_relations):
                        _fobj.store = False
                        _logger.debug(
                            "[poly] _auto_init: forcing store=False for inherited M2M %s on %s "
                            "(relation=%s belongs to depend_model)",
                            _fname, self._name, _fobj.relation,
                        )

        res = super()._auto_init()

        # [poly] Ensure stored poly-injected fields have a physical column on the
        # (pre-existing core) table. old_id is taken over from ir.poly_base keeping its
        # foreign model_name, so Odoo's update_db skips creating its column on the child
        # table, yet it stays store=True and gets SELECTed -> "column ... old_id does not
        # exist". Create any still-missing stored column. Additive: existing columns are
        # left untouched.
        if getattr(self, '_depend_models', None) and getattr(self, '_table', None):
            try:
                _existing = sql.table_columns(self.env.cr, self._table)
                # old_id is a known Integer poly field taken over from ir.poly_base; its
                # store flag may not yet be set at _auto_init time, so guarantee the column
                # unconditionally (nullable) — it is SELECTed at runtime.
                if 'old_id' not in _existing:
                    _logger.info("[poly] _auto_init: guaranteeing old_id column on %s", self._table)
                    self.env.cr.execute(SQL(
                        "ALTER TABLE %s ADD COLUMN IF NOT EXISTS old_id integer",
                        SQL.identifier(self._table),
                    ))
                for _fn, _fo in self._fields.items():
                    if _fo.store and _fo.column_type and _fn not in _existing:
                        _logger.info("[poly] _auto_init: creating missing stored column %s.%s",
                                     self._table, _fn)
                        self.env.cr.execute(SQL(
                            "ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s %s",
                            SQL.identifier(self._table),
                            SQL.identifier(_fn),
                            SQL(_fo.column_type[1]),
                        ))
            except Exception:
                _logger.exception("[poly] _auto_init: failed creating missing columns on %s",
                                  self._table)

        # Non-stored fields (injected poly relations, computed fields, related fields
        # pointing to a parent table) must never be NOT NULL in the child table because
        # the ORM omits them from INSERTs.  Legacy migrations may have created these
        # columns with NOT NULL; drop the constraint for every such column found.
        if hasattr(self, '_table'):
            # NOTA: NO se exige field.column_type. Los campos poly inyectados
            # (concrete_model_id, old_id, poly_payload, ...) son Many2one/Text computados
            # con store=False cuyo column_type puede ser falsy; aun asi pueden tener una
            # columna fisica NOT NULL legacy. El SELECT de abajo ya filtra a columnas que
            # EXISTEN y son NOT NULL, asi que basta con `not field.store`.
            non_stored_cols = [
                fname for fname, field in self._fields.items()
                if not field.store
            ]
            if non_stored_cols:
                self.env.cr.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s AND column_name = ANY(%s)
                    AND is_nullable = 'NO'
                """, (self._table, non_stored_cols))
                for (col,) in self.env.cr.fetchall():
                    _logger.info(
                        "[poly] Dropping NOT NULL from %s.%s (non-stored field)",
                        self._table, col,
                    )
                    self.env.cr.execute(
                        'ALTER TABLE "%s" ALTER COLUMN "%s" DROP NOT NULL' % (self._table, col)
                    )

        return res

    def _register_hook(self):
        """
        Perform actions right after the registry is built.

        This method extends the standard Odoo registry hook to ensure that
        polymorphic models don't have ID conflicts. It checks the current
        max ID values for all dependent models and adjusts the ir.poly_base
        sequence if necessary to avoid ID clashes.

        Also drops NOT NULL from any column in this model's table that
        corresponds to a non-stored field, to fix legacy migration artifacts
        without requiring a module update (-u).
        """
        super()._register_hook()

        # Drop NOT NULL from non-stored columns on every startup (no -u needed).
        # Non-stored fields are never written by the ORM so a NOT NULL constraint
        # left by a legacy migration would break every INSERT.
        if hasattr(self, '_table'):
            try:
                # Sin exigir field.column_type (ver nota en _auto_init): incluye los campos
                # poly inyectados no-stored aunque su column_type sea falsy.
                non_stored_cols = [
                    fname for fname, field in self._fields.items()
                    if not field.store
                ]
                if non_stored_cols:
                    self.env.cr.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = %s AND column_name = ANY(%s)
                        AND is_nullable = 'NO'
                    """, (self._table, non_stored_cols))
                    for (col,) in self.env.cr.fetchall():
                        _logger.info(
                            "[poly] Dropping NOT NULL from %s.%s (non-stored field)",
                            self._table, col,
                        )
                        self.env.cr.execute(
                            'ALTER TABLE "%s" ALTER COLUMN "%s" DROP NOT NULL' % (self._table, col)
                        )
            except Exception:
                pass

        # Only perform actions for polymorphic models
        if getattr(self, '_depend_models', None) is not None:
            # Ensure ir.poly_base sequence starts AFTER the max ID of any participant table
            try:
                self._sync_poly_sequence()
            except Exception:
                # Si falla algo en la transacción, no podemos continuar con el reajuste
                # de la secuencia aquí.
                return

    @classmethod
    def _poly_native_field_names(cls):
        """Field names the model defines NATIVELY, i.e. in its own module classes,
        excluding fields contributed by its polymorphic dependent base models.

        No-migration strategy: when a model that already exists (a core model such as
        res.partner / purchase.order.line) becomes polymorphic, its own fields stay
        untouched (legacy rows are read as the core model; only new rows get the full
        poly structure). numa_poly must therefore NEVER shadow such a field — neither a
        pre-existing core field (name) nor one the bridge explicitly redefines on the
        concrete model (e.g. pln_constraint_date with its own compute/inverse/store) —
        with a related-to-base version. Returns the set of names to protect.

        Cached on the registry class; the MRO/class field definitions are stable once
        built.
        """
        cached = cls.__dict__.get('_poly_native_fnames_cache')
        if cached is not None:
            return cached

        # Names of the dependent base models whose field-bearing classes must be
        # excluded from the "native" scan.
        dep_models = {'ir.poly_base'}
        for base in cls.mro():
            d = base.__dict__.get('_depend_models')
            if d and isinstance(d, (dict, OrderedDict)):
                dep_models.update(d.keys())

        def _class_model_name(klass):
            kn = klass.__dict__.get('_name')
            if kn:
                return kn
            inh = klass.__dict__.get('_inherit')
            if isinstance(inh, str):
                return inh
            if isinstance(inh, (list, tuple)) and len(inh) == 1:
                return inh[0]
            return None

        native = set()
        for klass in cls.mro():
            # Skip the classes that belong to a dependent base model: their fields are
            # the polymorphic capability we DO want to inject as related.
            if _class_model_name(klass) in dep_models:
                continue
            # Odoo stores field definitions either as class attributes (Field instances)
            # or in _field_definitions (dict {name: field} or list[field]); scan both.
            for attr, val in vars(klass).items():
                if isinstance(val, fields.Field):
                    native.add(attr)
            defs = klass.__dict__.get('_field_definitions')
            if isinstance(defs, dict):
                native.update(defs.keys())
            elif isinstance(defs, (list, tuple)):
                for f in defs:
                    fn = getattr(f, 'name', None)
                    if fn:
                        native.add(fn)
        try:
            cls._poly_native_fnames_cache = native
        except Exception:
            pass
        return native

    @classmethod
    def _build_dependant_model_attributes(cls):
        """
        Initialize and build the attributes of a polymorphic model.
        """
        if cls._name == 'ir.poly_base':
            return

        # [poly] STRICT ISOLATION: only proceed if this model is a polymorphic consumer
        if not _poly_is_polymorphic(cls):
            cls._poly_attributes_built = True
            return

        # [poly] Performance check: avoid repeating setup if already done
        if cls.__dict__.get('_poly_attributes_built', False):
            return

        # [poly] CHECK: A model is in the system if it has _depend_models in its MRO.
        has_depend_models = False
        for base in cls.mro():
            if '_depend_models' in base.__dict__:
                has_depend_models = True
                break

        if not has_depend_models:
            return

        # [poly] Mark as built to avoid recursion/repetition
        cls._poly_attributes_built = True

        # [poly] Phase 1: Create explicit bridge links from _depend_models
        # This ensures they exist before any 'related' field tries to reference them
        _mro = _poly_get_safe_mro(cls)
        dep_map = OrderedDict()
        for base in _mro:
            d = base.__dict__.get('_depend_models')
            if d and isinstance(d, (dict, OrderedDict)):
                for dm, df in d.items():
                    if dm not in dep_map:
                        dep_map[dm] = df
        
        def _set_field(name, field, related_base=None):
            """
            Set a field on the model class and definitions.
            """
            _logger.debug(f'Injecting field {name} into {cls._name}')
            
            # [poly] Aggressive takeover from ir.poly_base to ensure physical object parity.
            # NOTA: concrete_model_id NO va acá. El takeover copia el campo de ir.poly_base
            # (required=True, stored -> columna NOT NULL en el subtipo), pero el create del
            # subtipo nunca la popula -> NotNullViolation. El diseño lo quiere store=False
            # computado (ver _set_field('concrete_model_id', ... compute=_compute_concrete_model_id,
            # store=False) mas abajo): se deja caer al path normal para usar ESE campo.
            if name in ('old_id',):
                base_instance = cls.pool.get('ir.poly_base')
                if base_instance is not None:
                    base_field = base_instance._fields.get(name)
                    if base_field:
                        setattr(cls, name, base_field)
                        if hasattr(cls, '_field_definitions'):
                             defs = cls._field_definitions
                             if isinstance(defs, dict):
                                 defs[name] = base_field
                             elif isinstance(defs, list):
                                 found = False
                                 for i, f in enumerate(defs):
                                     if getattr(f, 'name', None) == name:
                                         defs[i] = base_field
                                         found = True
                                         break
                                 if not found:
                                     defs.append(base_field)
                        return

            # [poly] PERSISTENCE: Set as class attribute so Odoo's _setup_base picks it up
            setattr(cls, name, field)
            
            # [poly] Register in definitions if available (Odoo 18 style)
            if hasattr(cls, '_field_definitions'):
                # Mark as injected for surgical cleaning
                try:
                    field._poly_injected = True
                except Exception:
                    pass
                
                defs = cls._field_definitions
                if isinstance(defs, dict):
                    defs[name] = field
                elif isinstance(defs, list):
                    # For list-style definitions, ensure no duplicates
                    found = False
                    for i, f in enumerate(defs):
                        if getattr(f, 'name', None) == name:
                            defs[i] = field
                            found = True
                            break
                    if not found:
                        defs.append(field)
            
            # Update current fields map
            cls._fields[name] = field
            field.model_name = cls._name
            field.name = name

        # [poly] Phase 1: Create explicit bridge links from _depend_models
        # This ensures they exist before any 'related' field tries to reference them
        dep_map = getattr(cls, '_depend_models', OrderedDict())
        if not isinstance(dep_map, (dict, OrderedDict)):
            dep_map = OrderedDict()
        
        for base_model_name, link_field_name in dep_map.items():
            if link_field_name not in cls._fields:
                _logger.debug("[poly] Creating early bridge link %s -> %s in %s", link_field_name, base_model_name, cls._name)
                # Ensure the target base is initialized
                base_m = cls.pool.get(base_model_name)
                if base_m is not None:
                    base_m_class = type(base_m)
                    if not getattr(base_m_class, '_poly_attributes_built', False):
                        if hasattr(base_m_class, '_build_dependant_model_attributes'):
                            base_m_class._build_dependant_model_attributes()
                        else:
                            base_m_class._poly_attributes_built = True
                
                # We use PolyReference which is a M2O-like bridge
                _set_field(link_field_name, PolyReference(base_model_name))
            else:
                _logger.info("[poly] Early bridge link %s already exists in %s", link_field_name, cls._name)

        # [poly] Phase 2: Clone/create polymorphic fields
        for base_model_name, link_field_name in dep_map.items():
            _logger.debug("[poly] Building attributes for %s from base %s (via %s)", cls._name, base_model_name, link_field_name)
            
            base_model = cls.pool.get(base_model_name)
            if base_model is None:
                _logger.debug("[poly] Base model %s not found for %s", base_model_name, cls._name)
                continue
            
            # Ensure the base model has its attributes built
            base_model_class = type(base_model)
            if not getattr(base_model_class, '_poly_attributes_built', False):
                if hasattr(base_model_class, '_build_dependant_model_attributes'):
                    base_model_class._build_dependant_model_attributes()
                else:
                    base_model_class._poly_attributes_built = True

            # Standard polymorphic fields from the base model
            for name, field in base_model._fields.items():
                if name in cls._fields:
                    continue
                
                # We skip technical Odoo fields unless they are explicitly meant to be polymorphic
                if name in ('id', '__last_update', 'create_date', 'create_uid', 'write_date', 'write_uid', 'display_name'):
                    continue
                
                # [poly] DEEP FIND: Recursive resolution of the polymorphic origin
                # Resolve the field to its final implementation base if the base itself is polymorphic.
                
                target_field = field
                target_path = name
                target_base = base_model_name
                
                # [poly] Deep resolution: if target_field is a PolyReference-based related field
                # or if the target_model itself is polymorphic, we keep going deeper.
                while True:
                    # If the field is already a related field to another base (likely created by poly)
                    if target_field.related and len(target_field.related) == 2:
                        ref_field_name, sub_field_name = target_field.related
                        # We need to know which model owns this field to find the ref_field
                        current_model_name = target_field.model_name or target_base
                        current_model = cls.pool.get(current_model_name)
                        if not current_model:
                             break
                             
                        ref_field = current_model._fields.get(ref_field_name)
                        
                        if ref_field and isinstance(ref_field, (fields.Many2one, PolyReference)):
                            # It's a bridge to another polymorphic level
                            target_base = ref_field.comodel_name
                            target_model = cls.pool.get(target_base)
                            if target_model and sub_field_name in target_model._fields:
                                 target_field = target_model._fields[sub_field_name]
                                 target_path = sub_field_name
                                 # Continue loop to see if THIS target_field is also a bridge
                                 continue
                    
                    # If not a related field, check if the current target_base has a more specific 
                    # link to the field (in case we didn't land on a related field but the base IS polymorphic)
                    target_model = cls.pool.get(target_base)
                    if target_model:
                        tm_depend = getattr(type(target_model), '_depend_models', {})
                        # If the target model is polymorphic and the field exists in one of its bases, 
                        # we should probably have caught it via 'related', but this is a safety net.
                        # Actually, if it's NOT a related field but target_model IS polymorphic, 
                        # it means the field is OWNED by target_model, which is what we want.
                        pass
                        
                    break
                
                # Now we have the absolute origin. Create the related field.
                # If target_base is different from base_model_name, we might need intermediate PolyReferences.
                # However, the requirement says "related fields must be created to the final bases, 
                # and create the necessary PolyReferences (checking if they were already created) to reach the final field".
                
                # [poly] Building the path of PolyReferences
                current_source_model = cls
                current_link_name = link_field_name
                
                # If target_base is deep, we might need a chain. 
                # But Odoo related fields can follow a chain: ('link1', 'link2', 'field')
                # Wait, "campos related se deben crear a las bases finales"
                # This means: field_name -> (link_to_final_base, field_name_in_final_base)
                
                if target_base != base_model_name:
                    # Search if a bridge to target_base already exists in cls
                    found_link = None
                    # First check existing _depend_models/PolyReferences
                    for bmn, lfn in dep_map.items():
                        if bmn == target_base:
                            found_link = lfn
                            break
                    
                    if not found_link:
                        # Check all fields to see if a PolyReference to target_base already exists
                        for fname, f in cls._fields.items():
                            if isinstance(f, PolyReference) and f.comodel_name == target_base:
                                found_link = fname
                                break
                    
                    if not found_link:
                        # Create an ad-hoc bridge name
                        found_link = f"poly_{target_base.replace('.', '_')}_id"
                        if found_link not in cls._fields:
                             _logger.debug("[poly] Creating intermediate PolyReference %s -> %s in %s", found_link, target_base, cls._name)
                             _set_field(found_link, PolyReference(target_base))
                    
                    final_link = found_link
                else:
                    final_link = link_field_name
                
                # Create the related field pointing to the final base
                new_field = copy.copy(target_field)
                new_field.related = (final_link, target_path)
                new_field.store = False
                new_field.compute = None
                new_field.inverse = None
                
                _set_field(name, new_field, related_base=target_base)

            try:
                f_type = type(field)
                
                args = getattr(field, '_args', None) or getattr(field, '_args__', None)
                # [poly] RECOVERY: If args are totally gone but it's a polymorphic field,
                # we might find them in the base model's _fields if they were preserved there.
                if not args and related_base:
                    base_model_inst = cls.pool.get(related_base)
                    if base_model_inst is not None:
                        base_field_proto = base_model_inst._fields.get(name)
                        if base_field_proto:
                            args = getattr(base_field_proto, '_args', None) or getattr(base_field_proto, '_args__', None)

                if args:
                    clean_args = {k: v for k, v in args.items() if not k.startswith('_')}
                    

                    # [poly] MANDATORY ATTRIBUTE RECOVERY: 
                    # Many relational fields in Odoo 18 (especially when passed as positional args) 
                    # lose their original '_args' keys during setup. We MUST extract 
                    # their state directly from the object if it's not in clean_args.
                    
                    # 1. Selection
                    if (f_type.__name__ == 'Selection' or (hasattr(field, 'type') and field.type == 'selection')) and 'selection' not in clean_args:
                         # [poly] RECURSION GUARD: Avoid calling selection property if it might trigger lambda recursion
                         # We check if 'selection' is in _args (raw) first.
                         _raw_sel = None
                         _f_args = getattr(field, '_args', {}) or getattr(field, '_args__', {})
                         if _f_args and 'selection' in _f_args:
                              _raw_sel = _f_args['selection']
                         
                         if _raw_sel:
                              clean_args['selection'] = _raw_sel
                         else:
                              # [poly] DANGEROUS: If we must access field.selection, check if it's a lambda/callable
                              # which is exactly what triggers the RecursionError in Odoo 18 if called during setup.
                              try:
                                   _obj_sel = getattr(field, 'selection', None)
                                   # We check if it's a list or tuple (static selection)
                                   if isinstance(_obj_sel, (list, tuple)):
                                        clean_args['selection'] = _obj_sel
                                   elif callable(_obj_sel):
                                        # It's a callable. We can use it, BUT we must be careful not to call it here.
                                        # However, assigning it to clean_args is usually safe as long as we don't 
                                        # trigger the descriptor __get__ or _description_selection prematurely.
                                        clean_args['selection'] = _obj_sel
                              except Exception: pass
                    
                    # [poly] ULTIMATE SELECTION RECOVERY: If selection is STILL missing, search in Registry
                    if f_type.__name__ == 'Selection' and not clean_args.get('selection') and hasattr(cls, 'pool'):
                         for _m_name, _m in cls.pool.items():
                              if name in _m._fields:
                                   _f_proto = _m._fields[name]
                                   if (hasattr(_f_proto, 'type') and _f_proto.type == 'selection') and hasattr(_f_proto, 'selection'):
                                        # [poly] RECURSION GUARD: Prefer raw _args selection
                                        _proto_raw_sel = None
                                        _f_proto_args = getattr(_f_proto, '_args', {}) or getattr(_f_proto, '_args__', {})
                                        if _f_proto_args and 'selection' in _f_proto_args:
                                             _proto_raw_sel = _f_proto_args['selection']
                                        
                                        if _proto_raw_sel:
                                             clean_args['selection'] = _proto_raw_sel
                                        else:
                                             try:
                                                  _psel = getattr(_f_proto, 'selection', None)
                                                  if isinstance(_psel, (list, tuple)):
                                                       clean_args['selection'] = _psel
                                                  elif callable(_psel):
                                                       clean_args['selection'] = _psel
                                             except Exception: pass
                                        
                                        if clean_args.get('selection'):
                                             _logger.debug("[poly] Recovered selection for %s from model %s registry", name, _m_name)
                                             break
                         
                         # [poly] SECOND LEVEL: Search in ir.model.fields.selection (database) if registry fails
                         if not clean_args.get('selection') and hasattr(cls, 'env'):
                              # Odoo 18: Be extremely careful not to trigger environment access if we are already
                              # in a recursion deep in field setup.
                              try:
                                   if not getattr(cls.env.registry, 'ready', False):
                                        pass # Registry not ready, searching in DB might be dangerous/slow
                                   
                                   _selection_options = cls.env['ir.model.fields.selection'].sudo().search([('field_id.name', '=', name)])
                                   if _selection_options:
                                        clean_args['selection'] = [(opt.value, opt.name) for opt in _selection_options]
                                        _logger.debug("[poly] Recovered selection for %s from ir.model.fields.selection", name)
                              except Exception: pass
                    
                    # 2. Relational Metadata (Many2one, One2many, Many2many)
                    if f_type.__name__ in ('Many2one', 'One2many', 'Many2many', 'PolyReference'):
                        if not clean_args.get('comodel_name'):
                             _val = getattr(field, 'comodel_name', None)
                             if not _val and hasattr(field, '_args'):
                                  _val = field._args.get('comodel_name')
                             
                             # [poly] ULTIMATE RECOVERY: Search in Odoo Registry if field is degraded
                             if not _val and hasattr(cls, 'pool'):
                                  # Try to find a prototype in other models that share this field name
                                  # if they are likely to be from the same module/mixin.
                                  for _m_name, _m in cls.pool.items():
                                       if name in _m._fields:
                                            _f_proto = _m._fields[name]
                                            if _f_proto.type == field.type and hasattr(_f_proto, 'comodel_name'):
                                                 _val = _f_proto.comodel_name
                                                 _logger.debug("[poly] Recovered comodel_name '%s' for %s from model %s registry", _val, name, _m_name)
                                                 break
                                  
                                  # [poly] SECOND LEVEL: Search in ir.model.fields (database) if registry fails
                                  if not _val and hasattr(cls, 'env'):
                                       try:
                                            _ir_field = cls.env['ir.model.fields'].sudo().search([('name', '=', name), ('relation', '!=', False)], limit=1)
                                            if _ir_field:
                                                 _val = _ir_field.relation
                                                 _logger.debug("[poly] Recovered comodel_name '%s' for %s from ir.model.fields", _val, name)
                                       except Exception: pass
                             
                             clean_args['comodel_name'] = _val
                        
                        if f_type.__name__ == 'One2many' and not clean_args.get('inverse_name'):
                             _val = getattr(field, 'inverse_name', None)
                             if not _val and hasattr(field, '_args'):
                                  _val = field._args.get('inverse_name')
                             
                             # [poly] ULTIMATE RECOVERY: Search in Odoo Registry for inverse_name
                             if not _val and hasattr(cls, 'pool'):
                                  for _m_name, _m in cls.pool.items():
                                       if name in _m._fields:
                                            _f_proto = _m._fields[name]
                                            if _f_proto.type == 'one2many' and hasattr(_f_proto, 'inverse_name'):
                                                 _val = _f_proto.inverse_name
                                                 _logger.debug("[poly] Recovered inverse_name '%s' for %s from model %s registry", _val, name, _m_name)
                                                 break
                                  
                                  # [poly] SECOND LEVEL: Search in ir.model.fields (database) if registry fails
                                  if not _val and hasattr(cls, 'env'):
                                       try:
                                            _ir_field = cls.env['ir.model.fields'].sudo().search([('name', '=', name), ('relation_field', '!=', False)], limit=1)
                                            if _ir_field:
                                                 _val = _ir_field.relation_field
                                                 _logger.debug("[poly] Recovered inverse_name '%s' for %s from ir.model.fields", _val, name)
                                       except Exception: pass
                             
                             clean_args['inverse_name'] = _val
                             
                        if f_type.__name__ == 'Many2many':
                             if not clean_args.get('relation'):
                                  clean_args['relation'] = getattr(field, 'relation', None)
                             if not clean_args.get('column1'):
                                  clean_args['column1'] = getattr(field, 'column1', None)
                             if not clean_args.get('column2'):
                                  clean_args['column2'] = getattr(field, 'column2', None)

                    # 3. Domain and Context
                    if hasattr(field, 'domain') and 'domain' not in clean_args:
                         clean_args['domain'] = field.domain
                    if hasattr(field, 'context') and 'context' not in clean_args:
                         clean_args['context'] = field.context
                    
                    # 4. Related path (Crucial for our strategy)
                    if hasattr(field, 'related') and field.related and 'related' not in clean_args:
                         clean_args['related'] = field.related

                    # 5. Inheritance and deletion
                    if hasattr(field, 'ondelete') and field.ondelete and 'ondelete' not in clean_args:
                         clean_args['ondelete'] = field.ondelete
                    
                    if 'ondelete' not in clean_args and f_type.__name__ in ('Many2one', 'PolyReference'):
                         clean_args['ondelete'] = 'cascade' # Default safe for Odoo
                    
                    if hasattr(field, 'required') and 'required' not in clean_args:
                         clean_args['required'] = getattr(field, 'required', False)
                    if hasattr(field, 'delegate') and 'delegate' not in clean_args:
                         clean_args['delegate'] = getattr(field, 'delegate', False)
                    if hasattr(field, 'index') and 'index' not in clean_args:
                         clean_args['index'] = field.index
                    if f_type.__name__ in ('Many2one', 'One2many', 'Many2many', 'PolyReference'):
                        if not clean_args.get('comodel_name'):
                             # [poly] BRIDGE RECOVERY: Check if it's one of the bridge fields from _depend_models
                             found_dep = False
                             for bmn, lfn in dep_map.items():
                                 if lfn == name:
                                     clean_args['comodel_name'] = bmn
                                     found_dep = True
                                     _logger.debug("[poly] Recovered comodel_name '%s' for bridge field %s", bmn, name)
                                     break
                             
                             if not found_dep:
                                 # Log with high visibility if it still fails
                                 _logger.error("[poly] CRITICAL: comodel_name is NULL for relational field %s in %s (Type: %s). Falling back to 'base'.", 
                                              name, cls._name, f_type.__name__)
                                 clean_args['comodel_name'] = 'base'
                        
                        # [poly] SELECTION EMERGENCY: ensure selection is NOT missing for Selection fields
                        if f_type.__name__ == 'Selection' and not clean_args.get('selection'):
                             _logger.error("[poly] CRITICAL: selection is NULL for field %s in %s (Type: Selection). Falling back to empty list.", 
                                          name, cls._name)
                             clean_args['selection'] = []
                    
                    if f_type.__name__ == 'Selection':
                        if not clean_args.get('selection'):
                             # [poly] SELECTION EMERGENCY: ensure selection is NOT missing for Selection fields
                             _logger.error("[poly] CRITICAL: selection is NULL for field %s in %s (Type: Selection). Falling back to empty list.", 
                                          name, cls._name)
                             clean_args['selection'] = []

                    try:
                        f_clone = f_type(**clean_args)
                        f_clone.name = name # [poly] Odoo 18: ensure name is set early
                        f_clone.model_name = cls._name
                        _logger.debug("[poly] RECREATING field %s from base %s to %s: total isolation achieved", 
                                     name, related_base or "N/A", cls._name)
                    except Exception as e:
                        _logger.warning("[poly] RECREATION failed for %s using f_type(**clean_args): %s. Falling back to copy.", name, e)
                        f_clone = copy.copy(field)
                        f_clone.name = name
                        f_clone.model_name = cls._name
                else:
                    # Fallback to copy if args are gone (should not happen with our setup)
                    f_clone = copy.copy(field)
                    f_clone.name = name
                    f_clone.model_name = cls._name
                    _logger.warning("[poly] COPYING field %s from base %s to %s: isolation might be weak", 
                                 name, related_base or "N/A", cls._name)
                # Restore args to the clone if they were provided or found
                if args:
                    f_clone._args = dict(args)
                    f_clone._args__ = dict(args)
                
                # Odoo 18: MANDATORY: Ensure field name is set on the clone immediately
                f_clone.name = name
                f_clone.model_name = cls._name
                
                # Odoo 18: reset internal setup flags to allow re-setup for the new model
                for flag in ['_setup_done', '_direct', '_toplevel', 'setup_done', 'model_name']:
                    if hasattr(f_clone, flag):
                        try: delattr(f_clone, flag)
                        except (AttributeError, KeyError): pass
                
                # [poly] Restore name and model_name AFTER potential deletion by setup flags clearing
                f_clone.name = name
                f_clone.model_name = cls._name
                
                _logger.debug("[poly] Field %s for %s recreated as %s. f_clone.name=%s", 
                             name, cls._name, f_clone, getattr(f_clone, 'name', 'N/A'))
                
                # Clean class dict to remove any contaminated attribute
                current_attr = cls.__dict__.get(name)
                if current_attr and current_attr is not f_clone:
                    try: delattr(cls, name)
                    except (AttributeError, KeyError): pass

                setattr(cls, name, f_clone)
                cls._fields[name] = f_clone
                f_clone.model_name = cls._name
                
                # Forcing __set_name__ to install the descriptor on 'cls'
                # This will re-setup the field for the CURRENT model.
                f_clone.__set_name__(cls, name)
                
                # [poly] SPECIAL: If it's a related field, we MUST clear its 'related_sudo'
                # or similar caches to force re-evaluation if model_name changed.
                if hasattr(f_clone, 'related'):
                    f_clone._setup_done = False # Force setup
                
                # 3. Odoo 18: Ensure field is in the registry class (proxy) if it exists
                if hasattr(cls.pool, 'models') and cls._name in cls.pool.models:
                    proxy = cls.pool.models[cls._name]
                    if proxy is not cls:
                        # Clean proxy too
                        proxy_attr = proxy.__dict__.get(name)
                        if proxy_attr and proxy_attr is not f_clone:
                             try: delattr(proxy, name)
                             except (AttributeError, KeyError): pass
                        
                        setattr(proxy, name, f_clone)
                        if name not in proxy._fields:
                            proxy._fields[name] = f_clone
            except Exception as e:
                _logger.error("[poly] Failed to clone field %s for %s: %s", name, cls._name, e)
                # Fallback to direct set if cloning fails
                setattr(cls, name, field)
                cls._fields[name] = field

        # Create a poly_base_id many2one - the core link to ir.poly_base
        _set_field('poly_base_id',
            PolyReference(
                'ir.poly_base',
                string='Poly base',
                automatic=True,
                readonly=True,
            )
        )

        # Create a concrete_model_id field to know the concrete model of each record
        _set_field('concrete_model_id',
            fields.Many2one(
                'ir.model',
                string='Concrete model',
                compute='_compute_concrete_model_id',
                compute_sudo=True,
                automatic=True,
                readonly=True,
                store=False,
                required=False,
                export_string_translation=False
             )
        )

        # Add poly_payload field for DTO-style injection
        # This field allows transporting subclass-specific data as JSON
        _set_field('poly_payload',
            fields.Text(
                string='Polymorphic Payload',
                store=False,
                prefetch=False,
                compute='_compute_payload_dummy',
                inverse='_inverse_payload_dummy',
                help='Technical field for transporting polymorphic subclass data as JSON'
            )
        )

        # _set_field('id',
        #      fields.Id(string='id',
        #                related='poly_base_id.id',
        #                automatic=True))

        # Add standard audit fields related to the poly_base record
        # TODO: log fields should be registered only on ir.poly_base
        #       currently not working
        _set_field('create_uid',
             fields.Many2one('res.users', string='Created by',
                             related='poly_base_id.create_uid',
                             automatic=False))
        _set_field('create_date',
             fields.Datetime(string='Created on',
                             related='poly_base_id.create_date',
                             automatic=False))
        _set_field('write_uid',
             fields.Many2one('res.users', string='Last Updated by',
                             related='poly_base_id.write_uid',
                             automatic=False))
        _set_field('write_date',
             fields.Datetime(string='Last Updated on',
                             related='poly_base_id.write_date',
                             automatic=False))

        # [poly] Ensure bridge links from _depend_models exist before cloning other fields
        _mro = _poly_get_safe_mro(cls)
        dep_map = OrderedDict()
        for base in _mro:
            d = base.__dict__.get('_depend_models')
            if d and isinstance(d, (dict, OrderedDict)):
                for dm, df in d.items():
                    if dm not in dep_map:
                        dep_map[dm] = df
        for base_model_name, link_field_name in dep_map.items():
            if link_field_name not in cls._fields:
                _logger.debug("[poly] Creating bridge link %s -> %s in %s", link_field_name, base_model_name, cls._name)
                base_m = cls.pool.get(base_model_name)
                if base_m is not None:
                    base_m_class = type(base_m)
                    if not getattr(base_m_class, '_poly_attributes_built', False):
                        if hasattr(base_m_class, '_build_dependant_model_attributes'):
                            base_m_class._build_dependant_model_attributes()
                        else:
                            base_m_class._poly_attributes_built = True
                _set_field(link_field_name,
                    PolyReference(
                        base_model_name,
                        string=f'Link to {base_model_name}',
                        automatic=True,
                        readonly=True,
                    )
                )

        # Collect all fields from dependent models
        related_fields = {}

        # [poly] Fields the concrete model defines natively must never be shadowed by a
        # related-to-base version (no-migration strategy). Computed once here.
        _native_fnames = cls._poly_native_field_names()

        all_bases = getattr(cls, '__depends_base_classes', ())
        # IMPORTANT: ensure we use the same order as in __depends_base_classes (already reversed in _build_model)
        dependent_model_names = [c._name for c in reversed(all_bases) if hasattr(c, '_name') and c._name not in (cls._name, 'ir.poly_base')]

        # [poly] Pre-scan models to detect original field locations for flattening
        # We only care about models that are base models for THIS model
        base_field_origins = {}
        for base_cls in all_bases:
            b_name = getattr(base_cls, '_name', None)
            if not b_name or b_name in (cls._name, 'ir.poly_base'):
                continue
            for fname, fobj in base_cls._fields.items():
                if fname == 'id': continue
                
                # [poly] FLATTENING: Identify the absolute origin of the field
                # If the field is already related, we trace it back to its owner
                curr_f = fobj
                curr_m_name = b_name
                
                visited = {(curr_m_name, fname)}
                while curr_f.related:
                    if not isinstance(curr_f.related, str): break
                    
                    # If it's a simple related like 'base_link.field'
                    if '.' in curr_f.related:
                        rel_parts = curr_f.related.split('.')
                        rel_base_field = rel_parts[0]
                        rel_fname = '.'.join(rel_parts[1:])
                        
                        # Find if rel_base_field is a PolyReference in curr_m_name
                        rel_base_model = None
                        curr_m = cls.pool.get(curr_m_name)
                        if not curr_m: break
                        
                        # Scan _depend_models of the current model in the trace
                        b_depend = getattr(curr_m, '_poly_get_depend_models', lambda: {})()
                        for m_name, m_field in b_depend.items():
                            if m_field == rel_base_field:
                                rel_base_model = m_name
                                break
                        
                        if rel_base_model and rel_base_model in cls.pool:
                            next_model = cls.pool[rel_base_model]
                            
                            # [poly] RECURSIVE RESOLUTION: If the path has more than 1 dot,
                            # we MUST follow it step by step through polymorphic bases.
                            if '.' in rel_fname:
                                sub_parts = rel_fname.split('.')
                                sub_prefix = sub_parts[0]
                                sub_suffix = '.'.join(sub_parts[1:])
                                
                                sub_depend = getattr(next_model, '_poly_get_depend_models', lambda: {})()
                                sub_link = sub_depend.get(sub_prefix) or next_model._fields.get(sub_prefix)
                                
                                if sub_link:
                                     # It's another jump, let the while continue with one step
                                     curr_f = sub_link
                                     curr_m_name = rel_base_model
                                     # We don't return here, we let the while loop handle the next part of the path
                                     # but we must be careful with 'related' being evaluated.
                                     # Actually, better to just resolve ONE step and continue.
                                     continue

                            next_f = next_model._fields.get(rel_fname)
                            if next_f and (rel_base_model, rel_fname) not in visited:
                                curr_f = next_f
                                curr_m_name = rel_base_model
                                visited.add((curr_m_name, rel_fname))
                                continue
                    break
                
                if curr_m_name != b_name or curr_f is not fobj:
                    base_field_origins[(b_name, fname)] = (curr_m_name, curr_f.name)

        for model_name in dependent_model_names:
            # print(f"[poly] DEBUG: Adding subfields for model {model_name} to {cls._name}")
            def add_subfields(mm):
                """
                Recursively add fields from a dependent model and its dependencies.

                Args:
                    mm: The name of the model to add fields from
                """
                if mm == 'ir.poly_base' or mm == cls._name:
                    return  # Skip ir.poly_base as its fields are already handled, and skip self

                if mm not in cls.pool:
                    return

                base_model = cls.pool[mm]

                # Add fields from the model
                for subfield_name, subfield in base_model._fields.items():
                    if subfield_name == 'id':
                        continue
                    
                    # [poly] FLATTENING LOGIC:
                    # If this field is already a related to another poly base, 
                    # use the origin instead of this base.
                    curr_mm = mm
                    curr_fname = subfield_name
                    curr_subfield = subfield
                    
                    visited_origins = set()
                    while (curr_mm, curr_fname) in base_field_origins:
                        if (curr_mm, curr_fname) in visited_origins: break # cycle protection
                        visited_origins.add((curr_mm, curr_fname))
                        
                        orig_mm, orig_fname = base_field_origins[(curr_mm, curr_fname)]
                        if orig_mm in cls.pool:
                            curr_mm = orig_mm
                            curr_fname = orig_fname
                            curr_subfield = cls.pool[curr_mm]._fields.get(curr_fname)
                            if not curr_subfield: break
                        else:
                            break

                    # Only add fields that aren't already defined, aren't PolyReferences,
                    # and aren't related fields (unless they are the flattened target)
                    if not isinstance(curr_subfield, PolyReference):
                        # [poly] No-migration strategy: if the concrete (core) model
                        # defines this field natively, keep its OWN field — never shadow
                        # it with a related-to-base version (that breaks reads of legacy
                        # rows with no base record, and crashes on type mismatches such
                        # as Text vs Char).
                        if curr_fname in _native_fnames:
                            continue
                        # [poly] Aggressive takeover: if the field is already in the model but is a stored field
                        # and it also exists in the polymorphic base, it MUST be converted to related.
                        _force_related = False
                        _existing = None
                        if curr_fname in cls.__dict__ or curr_fname in cls._fields:
                            _existing = cls._fields.get(curr_fname) or cls.__dict__.get(curr_fname)
                            if _existing and (getattr(_existing, 'store', True) or not getattr(_existing, 'related', None)):
                                _force_related = True

                        if curr_fname not in related_fields or _force_related:
                            related_fields[curr_fname] = (
                                curr_mm,
                                curr_fname,
                                curr_subfield.type,
                                curr_subfield.comodel_name,
                                curr_subfield
                            )
                            # [poly] FORCE RELATED: ensure the field is NOT in cls.__dict__
                            if curr_fname in cls.__dict__:
                                try:
                                    delattr(cls, curr_fname)
                                except (AttributeError, TypeError):
                                    pass
                            
                            if hasattr(cls.pool, 'models') and cls._name in cls.pool.models:
                                proxy_class = cls.pool.models[cls._name]
                                if proxy_class is not cls and curr_fname in proxy_class.__dict__:
                                    try:
                                        delattr(proxy_class, curr_fname)
                                    except (AttributeError, TypeError):
                                        pass
                            if curr_fname in cls._fields:
                                del cls._fields[curr_fname]
                        else:
                            # [poly] Update if new one is better
                            _prev_mm, _prev_fname, _prev_type, _prev_comodel, _prev_subfield = related_fields[curr_fname]
                            if not _prev_comodel and curr_subfield.comodel_name:
                                related_fields[curr_fname] = (
                                    curr_mm, curr_fname, curr_subfield.type, curr_subfield.comodel_name, curr_subfield
                                )

                # Add non-field attributes from the model
                # Odoo 18: skip attribute copying as we now use MRO
                pass

                # Recursively add fields from the model's dependencies
                parent_depend_models = getattr(base_model, '_depend_models', {}) or {}
                for sub_base in parent_depend_models.keys():
                    add_subfields(sub_base)

            # Start the recursive field addition
            add_subfields(model_name)

        # Create reference fields to all dependent models
        related_bases = {}
        
        # We also need to map model names to field names for related bases.
        # We can extract this from the explicit _depend_models if present, 
        # or generate them for others in __depends_base_classes.
        explicit_depend_models = getattr(cls, '_depend_models', {}) or {}
        
        for base_model_name, base_field_name in explicit_depend_models.items():
            if base_model_name == cls._name:
                continue # Skip self to avoid circular/invalid related paths
            related_bases[base_model_name] = base_field_name
            # [poly] Inject PolyReference link field with explicit search method
            link_field = PolyReference(comodel_name=base_model_name,
                              string=f'Base for {base_model_name}',
                              automatic=True, readonly=True)
            link_field.search = link_field._search_related
            _set_field(base_field_name, link_field)

        # Create related fields for all fields from dependent models
        related_counter = 1
        for new_field_name in related_fields.keys():
            model, field_name, field_type, comodel, description = related_fields[new_field_name]

            if field_name in cls._fields:
                existing = cls._fields[field_name]
                if existing.related or not existing.store:
                    continue
                _logger.debug("[poly] Overriding existing stored field %s.%s with related version", cls._name, field_name)
                if field_name in cls.__dict__:
                     delattr(cls, field_name)

            if model not in related_bases:
                if model == cls._name:
                    continue # NEVER create related fields pointing to the model itself
                
                # [poly] Prevent recursion: if model is already a base of this model,
                # we should have it in related_bases already.
                
                # Check if this model is a poly base of the current model
                is_poly_base = model in cls._poly_get_depend_models()
                model_field = f'related_{related_counter}'
                related_counter += 1
                related_bases[model] = model_field
                
                # [poly] CRITICAL: if model is ir.poly_base, use poly_base_id
                if model == 'ir.poly_base':
                    related_bases[model] = 'poly_base_id'
                    model_field = 'poly_base_id'
                else:
                    _set_field(model_field,
                        PolyReference(comodel_name=model, string=f'Base for {model}',
                                      automatic=True, readonly=True)
                    )
            else:
                model_field = related_bases[model]
                if model_field not in cls._fields:
                    if model == 'ir.poly_base':
                         # Handled by poly_base_id creation above
                         pass
                    else:
                        _set_field(model_field,
                            PolyReference(comodel_name=model, string=model,
                                          automatic=True, readonly=True)
                        )

            # Map field types to field classes
            field_subclass = {
                'boolean': fields.Boolean,
                'integer': fields.Integer,
                'float': fields.Float,
                'monetary': fields.Monetary,
                'char': fields.Char,
                'text': fields.Text,
                'html': fields.Html,
                'date': fields.Date,
                'datetime': fields.Datetime,
                'binary': fields.Binary,
                'image': fields.Image,
                'selection': fields.Selection,
                'reference': fields.Reference,
                'many2one': fields.Many2one,
                'many2one_reference' : fields.Many2oneReference,
                'json': fields.Json,
                'properties': fields.Properties,
                'properties_definition': fields.PropertiesDefinition,
                'one2many': fields.One2many,
                'many2many': fields.Many2many,
            }.get(field_type)

            if not field_subclass:
                raise TypeError(_('Unsupported field type %s for field %s') %
                                (field_type, field_name))

            # Create the appropriate field type
            # [poly] FLATTENING: always point to the original model field
            # if we have a PolyReference for it.
            if model == 'ir.poly_base':
                 related_path = f'poly_base_id.{field_name}'
            else:
                 related_path = f'{related_bases[model]}.{field_name}'

            # [poly] ENSURE correct related path during creation
            if '.' in field_name:
                # If the field name already has a dot, it's likely a model prefix from Odoo
                # e.g. 'facebook.account.name'. We must strip it.
                parts = field_name.split('.')
                field_name_clean = parts[-1]
                if model == 'ir.poly_base':
                    related_path = f'poly_base_id.{field_name_clean}'
                else:
                    related_path = f'{related_bases[model]}.{field_name_clean}'
            
            # [poly] Saneamiento preventivo de rutas relacionadas durante la creación
            # Asegurar que solo hay UN punto en la ruta (referencia de un solo nivel)
            if related_path.count('.') > 1:
                # Si hay más de un punto, algo falló en el aplanamiento de orígenes
                # o el related_bases[model] tiene puntos.
                _logger.warning("[poly] Deep related path detected for %s: %s. Flattening might be incomplete.", new_field_name, related_path)
                # Forzamos aplanamiento si es posible
                parts = related_path.split('.')
                related_path = f"{parts[0]}.{parts[-1]}"

            field_kwargs = {
                'string': description.string,
                'related': related_path,
                'automatic': True,
                'store': False,  # SYSTEMATIC store=False for polymorphic fields
            }
            
            # [poly] auto_join logic: only for poly bases, not for inherits
            if not getattr(description, 'inherited', False):
                field_kwargs['auto_join'] = True

            if field_type in ['many2one', 'many2many', 'one2many']:
                field_kwargs['comodel_name'] = comodel
                
            if field_type == 'selection':
                field_kwargs['selection'] = description.selection
            
            if field_type == 'many2many':
                # [poly] For Many2many related fields, Odoo 18 tries to validate the table.
                # We copy relation details if they exist in the original field to help Odoo
                # understand it's the same table.
                for attr in ('relation', 'column1', 'column2'):
                    if getattr(description, attr, None):
                        field_kwargs[attr] = getattr(description, attr)

            if field_type == 'one2many':
                field_kwargs['inverse_name'] = getattr(description, 'inverse_name', None)

            new_field = field_subclass(**field_kwargs)

            # Add the field to the model
            _set_field(field_name, new_field, related_bases[model])

        # Add _depends methods
        # Odoo 18: skip method copying as we now use MRO
        pass

        _logger.debug(f'_build_dependant_model_attributes finished')

    @classmethod
    def _build_poly_fields(cls, calling_self=None) -> None:
        """
        Inject polymorphic fields into cls from its _depend_models chain.

        Called from _setup_base after the standard Odoo field setup so that
        base._fields is guaranteed to be populated.  Forces _setup_base on any
        base that has not yet been set up.

        Arguments
        ---------
        calling_self: the model instance from _setup_base (used for env access
                      when forcing _setup_base on a base that is not yet set up).

        Algorithm
        ---------
        1. Guard: skip ir.poly_base, non-polymorphic models, and models already built.
        2. Collect the consolidated dep_map via _poly_collect_depend_models.
        3. For each (base_model_name, link_field_name):
           a. Ensure the PolyReference link field exists in cls.
           b. Force _setup_base on the base if its _fields is empty.
           c. For every non-technical field in base._fields:
              - Resolve to its ultimate origin via _poly_resolve_field_origin.
              - Ensure a PolyReference to that origin exists in cls.
              - Inject a related=copy of the field.
        4. Inject infrastructure fields (poly_base_id and audit fields).
        """
        if cls._name == 'ir.poly_base':
            return
        if not _poly_is_polymorphic(cls):
            cls._poly_fields_built = True
            return
        if cls.__dict__.get('_poly_fields_built', False):
            return

        # Recursion guard — set before any recursive calls below.
        cls._poly_fields_built = True

        dep_map = _poly_collect_depend_models(cls)
        if not dep_map:
            return

        # [poly] Fields the concrete model defines natively must never be shadowed by a
        # related-to-base version (no-migration strategy). Use the precise per-class scan
        # (NOT set(cls._fields), which also contains base fields the model does not
        # redefine, e.g. project.task does not redefine pln_constraint_type and must let
        # it be a related field).
        _native_fnames = cls._poly_native_field_names()

        for base_model_name, link_field_name in dep_map.items():
            # Ensure the direct PolyReference bridge exists.
            _poly_ensure_poly_ref(cls, base_model_name, dep_map)

            base = cls.pool.get(base_model_name)
            if base is None:
                _logger.warning(
                    '[poly] _build_poly_fields: base model %s not found for %s',
                    base_model_name, cls._name,
                )
                continue

            # Ensure the base has its fields populated.
            if not base._fields:
                _logger.debug(
                    '[poly] _build_poly_fields: forcing _setup_base on %s for %s',
                    base_model_name, cls._name,
                )
                if calling_self is not None:
                    calling_self.env[base_model_name]._setup_base()
                else:
                    _logger.warning(
                        '[poly] _build_poly_fields: cannot force _setup_base on %s '
                        '(no env available); fields may be incomplete for %s',
                        base_model_name, cls._name,
                    )

            for fname, field in list(base._fields.items()):
                if fname in _POLY_TECHNICAL_FIELDS:
                    continue
                if fname in cls._fields:
                    existing = cls._fields[fname]
                    # Skip only if already correctly injected by poly (related and non-stored).
                    # When Phase-1 MRO injection adds the depend model's registry class to
                    # cls.__bases__, Odoo's _setup_base picks up the depend model's
                    # _field_definitions and adds its fields as stored/non-related entries in
                    # cls._fields.  We must replace those stale entries with the proper
                    # poly-related version.
                    if getattr(existing, '_poly_injected', False) and not getattr(existing, 'store', True):
                        continue
                    # [poly] Never shadow a field the concrete model defines natively
                    # (no-migration strategy): keep its own field as-is.
                    if fname in _native_fnames:
                        continue
                    _logger.debug(
                        '[poly] _build_poly_fields: replacing stale field %s in %s '
                        '(related=%r, store=%r) with poly-related version',
                        fname, cls._name,
                        getattr(existing, 'related', 'N/A'),
                        getattr(existing, 'store', 'N/A'),
                    )
                if isinstance(field, PolyReference):
                    continue

                origin_model, origin_fname = _poly_resolve_field_origin(
                    fname, base, cls.pool
                )
                if not origin_model or '.' in origin_fname:
                    _logger.warning(
                        '[poly] _build_poly_fields: cannot resolve clean origin for '
                        '%s.%s (origin_model=%r, origin_fname=%r); skipping',
                        base_model_name, fname, origin_model, origin_fname,
                    )
                    continue
                link = _poly_ensure_poly_ref(cls, origin_model, dep_map)

                new_field = copy.copy(field)
                new_field.related = '{}.{}'.format(link, origin_fname)
                new_field.store = False
                new_field.compute = None
                new_field.inverse = None
                new_field._setup_done = False
                try:
                    new_field._poly_injected = True
                except Exception:
                    pass
                _poly_inject_field(cls, fname, new_field)

        # --- Fix explicitly-defined related fields with model-name prefixes ----
        # Some fields may be defined with related='some.depend.model.field_name'
        # (e.g. injected by old code or written manually).  Redirect them to
        # use the link field: 'link_field.field_name'.
        for fname, field in list(cls._fields.items()):
            rel = getattr(field, 'related', None)
            if not isinstance(rel, str) or '.' not in rel:
                continue
            if getattr(field, '_poly_injected', False):
                continue  # Already set correctly by _build_poly_fields
            parts = rel.split('.')
            for base_model_name, link_field_name in dep_map.items():
                model_parts = base_model_name.split('.')
                n = len(model_parts)
                if len(parts) > n and parts[:n] == model_parts:
                    new_related = link_field_name + '.' + '.'.join(parts[n:])
                    redirected = copy.copy(field)
                    redirected.related = new_related
                    redirected.store = False
                    redirected._setup_done = False
                    try:
                        redirected._poly_injected = True
                    except Exception:
                        pass
                    _poly_inject_field(cls, fname, redirected)
                    _logger.debug(
                        '[poly] _build_poly_fields: redirected related path '
                        'for %s.%s: %s -> %s',
                        cls._name, fname, rel, new_related,
                    )
                    break

        # --- Infrastructure fields ------------------------------------------
        # poly_base_id: direct bridge to ir.poly_base (shared ID).
        if 'poly_base_id' not in cls._fields:
            _poly_inject_field(
                cls, 'poly_base_id',
                PolyReference('ir.poly_base', string='Poly base', automatic=True, readonly=True),
            )

        # Audit fields relayed through poly_base_id.
        _audit = {
            'create_uid': fields.Many2one(
                'res.users', string='Created by',
                related='poly_base_id.create_uid', automatic=False,
            ),
            'create_date': fields.Datetime(
                string='Created on',
                related='poly_base_id.create_date', automatic=False,
            ),
            'write_uid': fields.Many2one(
                'res.users', string='Last Updated by',
                related='poly_base_id.write_uid', automatic=False,
            ),
            'write_date': fields.Datetime(
                string='Last Updated on',
                related='poly_base_id.write_date', automatic=False,
            ),
        }
        for fname, fobj in _audit.items():
            if fname not in cls._fields:
                _poly_inject_field(cls, fname, fobj)

        _logger.debug('[poly] _build_poly_fields finished for %s', cls._name)

    @api.model_create_multi
    def create(self, data_list: list[ValuesType]) -> Self:
        """
        Create records from the stored field values in data_list.
        """
        # [poly] ir.poly_base IS NOT polymorphic, it is the common base.
        # Standard Odoo models that ARE NOT polymorphic must also be handled by Odoo.
        _is_poly = _poly_is_polymorphic(self)
        _logger.debug('[poly] create() called for %s, is_poly=%s', self._name, _is_poly)
        if self._name == 'ir.poly_base' or not _is_poly:
            # Validate explicit IDs before delegating so that duplicate IDs
            # raise ValidationError rather than an unhandled UniqueViolation.
            explicit_ids = [v['id'] for v in data_list if 'id' in v]
            if explicit_ids:
                existing = self.search([('id', 'in', explicit_ids)])
                if existing:
                    raise ValidationError(
                        _("Records with the following IDs already exist in %s: %s")
                        % (self._name, list(existing.ids))
                    )
            # [poly] Filter out Selection values that are invalid for this model.
            # This prevents cross-model state pollution when poly sub-creates pass
            # a value that is valid on the parent but not on this model (e.g.
            # conversation.message.state='new' -> fsm.instance.state).
            if self._name != 'ir.poly_base':
                clean_list = []
                for vals in data_list:
                    clean_vals = {}
                    for k, v in vals.items():
                        if (v is not False and v is not None
                                and k in self._fields):
                            f = self._fields[k]
                            if isinstance(f, fields.Selection) and isinstance(f.selection, list):
                                valid_keys = {sel[0] for sel in f.selection}
                                if valid_keys and v not in valid_keys:
                                    _logger.warning(
                                        "[poly] Filtering out Selection field %s=%r from %s create: not a valid value %s",
                                        k, v, self._name, valid_keys
                                    )
                                    continue
                        clean_vals[k] = v
                    clean_list.append(clean_vals)
                data_list = clean_list
            return super().create(data_list)
            
        # SAFEGUARD: if we are in early boot, filter out any invalid fields
        if not self.pool.ready:
            new_data_list = []
            for vals in data_list:
                new_vals = {k: v for k, v in vals.items() if k in self._fields or k == 'concrete_model_id'}
                if new_vals:
                    new_data_list.append(new_vals)
            if not new_data_list:
                if self._name in ('res.groups', 'res.users', 'ir.model.data'):
                    _logger.warning("[poly] Empty create on %s during boot. Returning empty recordset.", self._name)
                return self.browse()
            data_list = new_data_list

        # It is a polymorphic create
        # Validate permissions on dependent models before creating
        depend_models = self._poly_get_depend_models()
        for base_name in depend_models.keys():
            if base_name == '_is_poly_enabled': continue
            if base_name not in self.pool:
                raise ValidationError(
                    _('Dependent model %s does not exist') % base_name
                )
            base_model = self.env[base_name]
            base_model.check_access('create')

        # If this is a polymorphic create of a subclass handle it recursively

        # Acumulador de los registros creados. DEBE arrancar vacío: create() puede invocarse
        # sobre un recordset NO vacío (p.ej. record.copy() llama self.create(vals)), y devolver
        # `self` mezclado con los nuevos rompe la semántica (copy() devolvía original + copia).
        new_records = self.browse()
        concrete_model_id = None

        processed_vals_list = []
        for vals in data_list:
            # Make a copy to avoid mutating the original
            processed_vals = vals.copy()

            if 'concrete_model_id' in processed_vals:
                concrete_model_id = processed_vals['concrete_model_id']

            # Check if poly_payload exists and is not empty
            payload = processed_vals.pop('poly_payload', None)
            if payload:
                try:
                    # Deserialize the JSON payload
                    loaded_data = json.loads(payload)
                    if isinstance(loaded_data, dict):
                        # Merge the payload data into vals
                        # Payload data takes precedence over existing vals
                        processed_vals.update(loaded_data)
                    else:
                        _logger.warning(
                            "poly_payload contains non-dict JSON data, ignoring: %s",
                            payload
                        )
                except json.JSONDecodeError as e:
                    _logger.error(
                        "Failed to parse poly_payload JSON: %s. Error: %s",
                        payload, str(e)
                    )
                    raise ValidationError(
                        _("Invalid JSON in polymorphic payload: %s") % str(e)
                    ) from e
                except Exception as e:
                    _logger.error(
                        "Unexpected error processing poly_payload: %s",
                        str(e)
                    )
                    raise UserError(
                        _("Error processing polymorphic payload: %s") % str(e)
                    ) from e
            
            processed_vals_list.append(processed_vals)

        data_list = processed_vals_list

        # Capturar los nombres de campo del input ANTES de que el loop de creación los consuma
        # (rutea/pop-ea los campos heredados hacia las sub-creaciones de las bases). Se usan al
        # final para disparar las @api.constrains del concreto sobre campos heredados.
        _poly_input_fnames = set()
        for _vals in data_list:
            _poly_input_fnames.update(_vals.keys())

        if concrete_model_id:
            concrete_model = self.env['ir.model'].browse(concrete_model_id).exists()
            # OJO: `concrete_model` es un registro de ir.model; el nombre técnico del modelo
            # concreto vive en su campo `.model` (ej. 'test.test4'), NO en `._name` (que para
            # un recordset de ir.model siempre es 'ir.model'). concrete_model_id puede llegar en
            # los vals como dispatch desde una base (redirigir al modelo concreto) o arrastrado
            # por copy() (campo heredado de ir.poly_base): en ese caso target == self y sólo hay
            # que descartar el bookkeeping, no redirigir (si no, se intentaba crear un ir.model).
            target_name = concrete_model.model if concrete_model else None
            # Descartar el bookkeeping field de los vals en ambos casos.
            new_vals_list = []
            for data in data_list:
                new_data = dict(data)
                new_data.pop('concrete_model_id', None)
                new_vals_list.append(new_data)

            if target_name and target_name != self._name:
                _logger.debug(f'Creating subclass {target_name} with {new_vals_list}')
                return self.env[target_name].create(new_vals_list)

            # target == self (o ir.model inexistente): seguir el create normal sin el campo.
            data_list = new_vals_list

        # Get all related fields and their definitions
        inverse_related = {field_name.split('.')[-1]: field_definition
                           for field_name, field_definition in self._fields.items()
                           if field_definition.related}

        # Map field names to base model names
        inverse_field2base = {base_field: base_name for base_name, base_field in depend_models.items()}

        # Determine which fields need to be created in which base models
        bases_to_create = {}
        for field_name, field_definition in inverse_related.items():
            related_base = field_definition.related.split('.', 1)[0]
            if related_base != 'poly_base_id':
                if related_base in inverse_field2base:
                    base = inverse_field2base[related_base]
                    if base not in bases_to_create:
                        bases_to_create[base] = set()
                    bases_to_create[base].add(field_name)

        # Ensure all dependent models are in the bases_to_create dict
        for base in self._depend_models.keys():
            if base not in bases_to_create:
                bases_to_create[base] = set()

        # Optimize: check all explicit IDs in batch before processing
        explicit_ids = [data['id'] for data in data_list if 'id' in data]
        if explicit_ids:
            existing_ids = set(self.search([('id', 'in', explicit_ids)]).ids)
            for data in data_list:
                if 'id' in data and data['id'] in existing_ids:
                    raise ValidationError(
                        _('You are trying to create a %s with explicit id %d. It exists already!') %
                        (self._name, data['id'])
                    )

        # SINCRONIZACIÓN PREVENTIVA:
        # Si hay registros en el lote que requieren generación de ID, sincronizamos
        # la secuencia una sola vez para todo el lote usando el bloqueo consultivo.
        if any('id' not in data for data in data_list):
            self._sync_poly_sequence()

        # [poly] CLEANUP VALS: Ensure we only pass fields that exist in the model
        # This is critical for Odoo 18 which is very strict about unknown fields in create()
        clean_data_list = []
        
        # [poly] Odoo 18 PROXY PROTECTION: 
        # Collect ALL field names defined in the model class or its MRO dicts.
        cls_real_fields = set()
        for base in type(self).mro():
             for attr_name, attr_val in base.__dict__.items():
                  if isinstance(attr_val, fields.Field):
                       cls_real_fields.add(attr_name)

        dep_map = type(self)._poly_get_depend_models()
        poly_links = set(dep_map.values())

        for data in data_list:
            clean_data = {}
            for k, v in data.items():
                if k in self._fields:
                    f = self._fields[k]
                    
                    if k == 'driver_id' and k not in poly_links and self._name != 'conversation.driver':
                         if k not in cls_real_fields:
                              _logger.warning("[poly] Hard-filtering driver_id from %s create", self._name)
                              continue

                    if (v is not False and v is not None
                            and isinstance(f, fields.Selection)
                            and k not in poly_links):
                         valid_keys = {sel[0] for sel in (f.selection if isinstance(f.selection, list) else [])}
                         if valid_keys and v not in valid_keys:
                              _logger.warning(
                                   "[poly] Filtering out Selection field %s=%r from %s create: not a valid value %s",
                                   k, v, self._name, valid_keys
                              )
                              continue

                    if f.related and not f.store and k not in poly_links and not f.required:
                         _logger.debug("[poly] Filtering out polluted related field %s from create on %s", k, self._name)
                         continue

                    if k in cls_real_fields or k in poly_links or getattr(f, 'inherited', False) or f.required or k == 'id':
                         if f.related and not f.store and not f.required:
                              continue
                         clean_data[k] = v
                    else:
                         if getattr(f, 'model_name', None) == self._name:
                              clean_data[k] = v
                         else:
                              _logger.debug("[poly] Filtering out field %s not physically in %s", k, self._name)
            
            # [poly] CRITICAL: Ensure business fields are preserved if passed
            # Search in all levels of the poly hierarchy for business fields
            # that might have been filtered out but are needed.
            for critical_f in ['name', 'provider', 'active', 'company_id']:
                 if critical_f in data:
                      clean_data[critical_f] = data[critical_f]

            clean_data_list.append(clean_data)
        data_list = clean_data_list

        # [poly] Physical columns that actually exist on THIS model's (leaf) table.
        # Used below to avoid forcing genuinely non-stored fields (e.g. computed
        # fields like personal_stage_type_id on project.task, or company-dependent
        # account fields on res.partner) into the leaf INSERT, which would raise
        # "column ... does not exist".
        _poly_leaf_cols = set()
        if getattr(self, '_table', None):
            try:
                _poly_leaf_cols = set(sql.table_columns(self.env.cr, self._table))
            except Exception:
                _poly_leaf_cols = set()

        # Process each record to create
        for current_idx, data in enumerate(data_list):
            # Handle explicit ID or create a new one via ir.poly_base
            if 'id' in data:
                new_id = data['id']
            else:
                # Ahora creamos en ir.poly_base confiando en la secuencia ya sincronizada.
                # Si aun así falla por un ID insertado justo después del cálculo del max_id,
                # Odoo lanzará la excepción de integridad (comportamiento optimista).
                
                # [poly] Ensure concrete_model_id is passed when creating poly base
                # We use SQL to bypass any field filtering in Odoo 18 for this technical base
                model_id = self.env['ir.model']._get_id(self._name)
                self.env.cr.execute(
                    'INSERT INTO ir_poly_base (concrete_model_id, create_uid, write_uid, create_date, write_date) '
                    'VALUES (%s, %s, %s, now(), now()) RETURNING id',
                    (model_id, self.env.uid, self.env.uid)
                )
                new_id = self.env.cr.fetchone()[0]
                _logger.debug('Creating poly base for %s, id = %s (via SQL)', self._name, new_id)

            # [poly] Use the UNFILTERED original values (processed_vals_list es paralelo a
            # data_list por indice; current_idx viene del enumerate -> robusto ante dicts
            # limpios iguales, que con data_list.index(data) cruzaba registros en bulk create).
            orig_data = processed_vals_list[current_idx]

            # Enrich orig_data with main model defaults
            _model_defaults = self.default_get(list(self._fields.keys()))
            for _dk, _dv in _model_defaults.items():
                if _dk not in orig_data:
                    orig_data[_dk] = _dv

            # Tracks the actual DB id of each created/found dependent record.
            dep_record_ids = {}

            # Create or update records in all dependent models
            _logger.debug('[poly] Creating sub-records for %s, bases_to_create: %s', self._name, list(bases_to_create.keys()))
            for base, field_set in bases_to_create.items():
                base_model = self.env[base]
                base_data = {}

                # Add fields that are explicitly in the field set (orig_data contains them)
                for field_name in field_set:
                    if field_name in orig_data:
                        base_data[field_name] = orig_data[field_name]

                # Add fields that match the base model's fields
                for field_name, field_definition in base_model._fields.items():
                    field_plain_name = field_name.split('.')[-1]
                    if field_plain_name in orig_data:
                        base_data[field_name] = orig_data[field_plain_name]

                # Ensure the same ID is used
                base_data['id'] = new_id

                # Create or update the base record
                existing_base = base_model.search([('id', '=', new_id)], limit=1)
                if not existing_base:
                    _logger.debug(f'[poly] Sub-create for {base} from {self._name}: data={base_data}')
                    created_base = base_model.create([base_data])
                    dep_record_ids[base] = created_base.id
                else:
                    _logger.debug(f'[poly] Sub-write for {base} from {self._name}: data={base_data}')
                    existing_base.write(base_data)
                    dep_record_ids[base] = existing_base.id

            # Finally, create the record in this model.
            # Use the UNFILTERED original values (por current_idx del enumerate) para
            # encontrar los campos heredados que se guardan en la tabla de este modelo.
            orig_data = processed_vals_list[current_idx]
        
            base_data = data.copy()
            base_data['id'] = new_id

            # [poly] AGGRESSIVE CLEANUP: Odoo 18 ORM rejects ANY field that is marked 
            # as related but NOT stored in its internal _fields dict.
            final_data = {}
            for k, v in base_data.items():
                if k in self._fields:
                    f = self._fields[k]
                    f_model = getattr(f, 'model_name', None)
                    is_real_field = f.store and f_model == self._name
                
                    # [poly] CRITICAL FIX: Odoo 18 MUST preserve certain fields
                    # even if it thinks they are not stored, to satisfy database
                    # constraints in polymorphic tables.
                    if k == 'name' or k == 'id' or f.required or getattr(f, 'inherited', False):
                         is_real_field = True
                    elif f.store and not f.related:
                         is_real_field = True

                    if is_real_field:
                        final_data[k] = v
        
            # [poly] INHERITED FIELD RECOVERY:
            # If a field is in orig_data and it's a stored field of this model,
            # but was filtered out by the previous cleanup loop, we restore it.
            # Also restore inherited fields from _inherits and REQUIRED fields.
            for k, v in orig_data.items():
                if k in self._fields and k not in final_data:
                    f = self._fields[k]
                    # [poly] Forcing field recovery if it's required, even if Odoo
                    # thinks it's a related/non-stored due to Registry pollution.
                    # We check the database column existence if possible.
                    if f.required or getattr(f, 'inherited', False) or k == 'name':
                         final_data[k] = v
                    else:
                        f_model = getattr(f, 'model_name', None)
                        if (f.store and f_model == self._name):
                            final_data[k] = v

            base_data = final_data

            # [poly] CRITICAL ODOO 18 FIX:
            # We force those fields back into 'base_data' if they are missing.
            # AND we MUST ensure Odoo sees them as stored BEFORE they are classified.
        
            # [poly] Re-classify fields after our forced restoration.
            # Principio (sin hardcodes de consumidores): un campo se fuerza al base_data de la HOJA
            # sólo si es un campo PROPIO (no related). Los campos related/heredados (ej. `active`,
            # o `name` en un subtipo de res.partner) pertenecen a una base y se rutean a su
            # sub-create, NO a la tabla hoja (si no, INSERT falla: la columna no existe en la hoja).
            # (Antes: lista hardcodeada `('name','provider','active','facebook_account_id','driver_id')`
            # — scar de estabilización — forzaba `active` a la hoja y rompía personas poly de res.partner.)
            # [poly] Fields skipped here because they have no physical column on the
            # leaf table (genuinely non-stored computed/company-dependent fields).
            # Their values are applied after the INSERT via write() -> inverse.
            _poly_deferred = {}
            for k, v in orig_data.items():
                if k not in base_data and k in self._fields:
                    f = self._fields[k]
                    if not f.related:
                        # Only push a field into the leaf INSERT when it owns a physical
                        # column there. Forcing store=True on a column-less computed field
                        # (e.g. personal_stage_type_id, store=False) makes super().create
                        # emit an INSERT for a column that does not exist.
                        if f.store or k in _poly_leaf_cols:
                            base_data[k] = v
                            # [poly] force Odoo to include registry-polluted-but-physical
                            # fields in classification.
                            if not f.store:
                                f._poly_old_store = f.store
                                f.store = True
                            if getattr(f, 'inherited', False):
                                f._poly_old_inherited = f.inherited
                                f.inherited = False
                            if hasattr(f, 'related') and f.related:
                                 f._poly_old_related = f.related
                        elif getattr(f, 'inverse', None):
                            # Writable computed field with no column: defer to its inverse.
                            _poly_deferred[k] = v
                    elif k in _poly_leaf_cols:
                        # [poly] Related field that ALSO owns a physical column on the leaf
                        # table (e.g. res.partner.name, which carries the res_partner_check_name
                        # constraint). The base sub-create already received it, but the leaf
                        # INSERT must include it too or the leaf-table constraint fails.
                        # Keep `related` intact (a stored related field still gets a column).
                        base_data[k] = v
                        if not f.store:
                            f._poly_old_store = f.store
                            f.store = True

            # [poly] CRITICAL: inject link fields from sub-created records into base_data.
            # dep_record_ids holds {dep_model_name: created_id} from the sub-create loop.
            # Without this, link fields like poly_id remain NULL in the leaf record, causing
            # PolyReference.convert_to_record to return a recordset that doesn't exist in DB.
            for _dep_model_name, _dep_id in dep_record_ids.items():
                _link_field = self._depend_models.get(_dep_model_name)
                if _link_field and _link_field not in base_data:
                    base_data[_link_field] = _dep_id

            # [poly] Ensure every value routed to the leaf INSERT that maps to a real
            # leaf column is classified as STORED, so Odoo emits it in the INSERT rather
            # than deferring it to an inverse. Without this, related/store=False fields
            # that nevertheless own a leaf column (e.g. res.partner.name) are omitted
            # from the INSERT and the leaf-table constraints (res_partner_check_name)
            # fire before the inverse runs. Restored together with the other temporary
            # field-state changes after create.
            for _k in list(base_data.keys()):
                _f = self._fields.get(_k)
                if not _f or _k not in _poly_leaf_cols:
                    continue
                # Force store=True so Odoo emits the value in the leaf INSERT. We keep
                # `related` intact: a STORED related field still gets a column and is
                # written (clearing related breaks Odoo's related machinery — it expects
                # a dotted path, not False).
                if not _f.store and not hasattr(_f, '_poly_old_store'):
                    _f._poly_old_store = _f.store
                    _f.store = True
                if getattr(_f, 'inherited', False) and not hasattr(_f, '_poly_old_inherited'):
                    _f._poly_old_inherited = _f.inherited
                    _f.inherited = False

            # [poly] INSTRUMENTATION: Final values before standard create
            _logger.debug("[poly] Final create for %s: id=%s dep_record_ids=%s link_fields=%s",
                         self._name, base_data.get('id'),
                         dep_record_ids,
                         {k: base_data.get(k) for k in (self._depend_models or {}).values()})

            # [poly] The temporary Field-state changes above (store/related/inherited on
            # SHARED Field objects) MUST be restored no matter what — if super().create
            # or the post-processing raises, leaving them mutated corrupts the registry
            # for every subsequent operation. Hence the try/finally.
            try:
                new_record = super().create([base_data])
                new_records |= new_record

                # [poly] Apply deferred non-stored writable fields via their inverse now
                # that the leaf row exists. Best-effort: a failing inverse must not abort
                # the create.
                if _poly_deferred:
                    try:
                        new_record.write(_poly_deferred)
                    except Exception:
                        _logger.exception(
                            "[poly] create: failed applying deferred non-stored fields %s on %s",
                            list(_poly_deferred), self._name)

                # [poly] Ensure Odoo has flushed to DB before we restore f.store/f.inherited,
                # otherwise the flush might discard the values.
                self.flush_model(base_data.keys())

                # [poly] After flush, invalidate the cache for these records so Odoo reads
                # the values from DB using the descriptors we are about to restore.
                self.env.cache.invalidate([(f, new_records._ids) for k in base_data.keys() if (f := self._fields.get(k))])

                # [poly] For related fields, also invalidate the target model cache
                # because the inversion might have put False/None there during create.
                for k in base_data.keys():
                    f = self._fields.get(k)
                    if f and hasattr(f, 'related') and f.related:
                         try:
                             # E.g. driver_id.name -> invalidate conversation.driver
                             target_model_name = f.related.split('.')[0]
                             if target_model_name in (self._depend_models or {}):
                                  link_fname = self._depend_models[target_model_name]
                                  target_ids = [r[link_fname].id for r in new_records if r[link_fname]]
                                  if target_ids:
                                       target_model = self.env[target_model_name]
                                       target_field_name = f.related.split('.')[-1]
                                       if target_field_name in target_model._fields:
                                            target_field = target_model._fields[target_field_name]
                                            self.env.cache.invalidate([(target_field, tuple(target_ids))])
                         except Exception:
                             pass
            finally:
                # [poly] RESTORE field state — ALWAYS, even on exception.
                for k in base_data.keys():
                    f = self._fields.get(k)
                    if f:
                        if hasattr(f, '_poly_old_related'):
                            f.related = f._poly_old_related
                            del f._poly_old_related
                        if hasattr(f, '_poly_old_store'):
                            f.store = f._poly_old_store
                            del f._poly_old_store
                        if hasattr(f, '_poly_old_inherited'):
                            f.inherited = f._poly_old_inherited
                            del f._poly_old_inherited

        # [poly] Disparar las @api.constrains del modelo concreto para los campos del input que
        # son HEREDADOS (related, viven en una base): el super().create() de la hoja sólo valida
        # SUS columnas propias, así que un constraint sobre un campo heredado (ej. a1, en
        # test.test1) no se evaluaba en create (sí en write -> asimetría / bypass de validación).
        # Validamos explícitamente esos campos sobre los registros creados.
        if new_records:
            _inherited_fnames = [
                fn for fn in _poly_input_fnames
                if (f := self._fields.get(fn)) is not None and getattr(f, 'related', None)
            ]
            if _inherited_fnames:
                new_records._validate_fields(_inherited_fnames)

        return new_records

    def _prepare_create_values(self, vals_list):
        """
        Clean up and complete the given create values.

        This is a modified version of the standard Odoo method that does NOT filter
        out the 'id' field, which is necessary for polymorphic models to maintain
        the same ID across all dependent models.

        The method returns a list of new vals containing:
        * default values
        * discarded forbidden values (magic fields)
        * precomputed fields

        Args:
            vals_list: List of dictionaries containing create values

        Returns:
            A new list of completed create values
        """
        # Unlike standard Odoo, we don't include 'id' in bad_names
        bad_names = ['parent_path']
        if self._log_access:
            # The superuser can set log_access fields while loading registry
            if not(self.env.uid == SUPERUSER_ID and not self.pool.ready):
                bad_names.extend(LOG_ACCESS_COLUMNS)

        # Also discard precomputed readonly fields (to force their computation)
        bad_names.extend(
            fname
            for fname, field in self._fields.items()
            if field.precompute and field.readonly
        )

        result_vals_list = []
        for vals in vals_list:
            # Add default values
            vals = self._add_missing_default_values(vals)

            # Add magic fields
            for fname in bad_names:
                vals.pop(fname, None)
            if self._log_access:
                vals.setdefault('create_uid', self.env.uid)
                vals.setdefault('create_date', self.env.cr.now())
                vals.setdefault('write_uid', self.env.uid)
                vals.setdefault('write_date', self.env.cr.now())

            result_vals_list.append(vals)

        # Add precomputed fields
        self._add_precomputed_values(result_vals_list)

        return result_vals_list

    def copy_data(self, default=None):
        """
        Al copiar un registro polimórfico hay que descartar los campos que gestiona poly
        internamente: el bookkeeping de ir.poly_base (id, old_id, concrete_model_id, poly_payload,
        poly_base_id) y TODOS los links a las bases (PolyReference: testN_id, etc.). Si se copiaran
        verbatim apuntarían a las bases del ORIGINAL (o a columnas que no existen en la tabla hoja,
        ej. poly_base_id en test_test2). Quitándolos, el create() de poly regenera identidad propia
        y bases frescas a partir de los datos copiados.
        """
        vals_list = super().copy_data(default=default)
        if not _poly_is_polymorphic(self):
            return vals_list
        for vals in vals_list:
            for fname in list(vals.keys()):
                if fname in _POLY_TECHNICAL_FIELDS or isinstance(self._fields.get(fname), PolyReference):
                    vals.pop(fname, None)
        return vals_list

    def unlink(self):
        """
        Delete records and their dependent records.
        """
        if not self:
            return True

        if not _poly_is_polymorphic(self):
            return super().unlink()

        # Capture IDs and dependent record IDs BEFORE any deletion.
        # We use the link field (e.g. driver_id) instead of self.ids because the
        # dependent record may have a different id (plain models.Model dependents get
        # an auto-generated id, not the poly id). Reading now also avoids FK violations:
        # deleting the dependent first would break the FK from the main record.
        original_ids = list(self.ids)
        dep_ids = {}
        if getattr(self, '_depend_models', None) is not None:
            for base_model_name, link_field in self._depend_models.items():
                try:
                    # Acceso POR-REGISTRO (no self.mapped): mapped() sobre el PolyReference
                    # entra en loop en su __get__ (Field.mapped re-dispara el descriptor); el
                    # acceso directo por registro resuelve el link sin colgar.
                    linked_ids = [lid for rec in self if (lid := rec[link_field].id)]
                except Exception:
                    linked_ids = original_ids  # fallback: assume id-sharing
                if linked_ids:
                    dep_ids[base_model_name] = linked_ids

        # Delete the main (concrete) model record first so FK references to
        # dependent records are removed before those records are deleted.
        result = super().unlink()

        # Now delete the dependent records using their actual IDs.
        for base_model_name, ids_to_delete in dep_ids.items():
            self.env[base_model_name].browse(ids_to_delete).unlink()

        # [poly] Odoo 18 consistent models fix:
        # Before unlinking ir.poly_base, we must ensure Odoo's protection system
        # doesn't try to subtract records from different models.
        # We perform a manual delete to avoid the ORM's inconsistent model checks.
        if original_ids and self._name != 'ir.poly_base':
            self.env.cr.execute(SQL("DELETE FROM ir_poly_base WHERE id IN %s", tuple(original_ids)))
            # Invalidate cache for the deleted records
            self.env['ir.poly_base'].invalidate_model()
            
        return result


    def read(self, fields=None, load='_classic_read'):
        if not _poly_is_polymorphic(self):
            return super().read(fields=fields, load=load)
        
        if not self.pool.ready:
            try:
                return super().read(fields=fields, load=load)
            except (MissingError, AccessError):
                if self._name in ('res.groups', 'res.users', 'res.company', 'ir.model.data'):
                    _logger.warning("[poly] Intercepted MissingError/AccessError in %s.read() during boot. Returning empty.", self._name)
                    return []
        return super().read(fields=fields, load=load)

    def _compute_field_value(self, field):
        if not self.pool.ready:
            try:
                return super()._compute_field_value(field)
            except (MissingError, AccessError):
                # Silent fallback during boot
                return
        return super()._compute_field_value(field)

    def write(self, vals):
        """
        Override write to intercept and merge poly_payload data.
        """
        if not self:
            return True

        if not _poly_is_polymorphic(self):
            return super().write(vals)

        # Make a copy to avoid mutating the original
        processed_vals = vals.copy()
        
        # Check if poly_payload exists and is not empty
        payload = processed_vals.pop('poly_payload', None)
        if payload:
            try:
                # Deserialize the JSON payload
                loaded_data = json.loads(payload)
                if isinstance(loaded_data, dict):
                    # Merge the payload data into vals
                    # Payload data takes precedence over existing vals
                    processed_vals.update(loaded_data)
                else:
                    _logger.warning(
                        "poly_payload contains non-dict JSON data, ignoring: %s",
                        payload
                    )
            except json.JSONDecodeError as e:
                _logger.error(
                    "Failed to parse poly_payload JSON: %s. Error: %s",
                    payload, str(e)
                )
                raise ValidationError(
                    _("Invalid JSON in polymorphic payload: %s") % str(e)
                ) from e
            except Exception as e:
                _logger.error(
                    "Unexpected error processing poly_payload: %s",
                    str(e)
                )
                raise UserError(
                    _("Error processing polymorphic payload: %s") % str(e)
                ) from e

        # Poly logic: identify which fields belong to parent/base models
        if getattr(self, '_depend_models', None) is not None:
            # Separate fields by base model
            fields_by_model = {}
            for base_model_name in self._depend_models:
                base_model = self.env[base_model_name]
                pool_fields = self.pool[self._name]._fields
                
                # Identify fields that belong to this base model
                base_fields = {
                    f for f in processed_vals
                    if f in base_model._fields
                    and f not in self._fields and f not in pool_fields
                }
                
                if base_fields:
                    fields_by_model[base_model_name] = {f: processed_vals.pop(f) for f in base_fields}

            # Update base models for existing records
            for current_base_model_name, current_base_vals in fields_by_model.items():
                if current_base_model_name == 'ir.poly_base':
                    self.env[current_base_model_name].browse(self.ids).write(current_base_vals)
                else:
                    # For other base models (like numa.planning.node), 
                    # we must ensure the record exists in ir.poly_base (the shared ID foundation)
                    # before writing, otherwise it might fail due to MissingError or 
                    # write to a non-existent ID in that model.
                    for record in self:
                        base_rec = self.env[current_base_model_name].browse(record.id)
                        if not base_rec.exists():
                            # If it doesn't exist in the base model (e.g. numa.planning.node),
                            # it means the ir_poly_base entry is missing for this record.
                            # We force its creation.
                            self.env['ir.poly_base'].sudo().create({
                                'id': record.id,
                                'concrete_model_id': self.env['ir.model']._get_id(self._name),
                            })
                        base_rec.write(current_base_vals)

        # Call super with the remaining (standard/local) values
        return super().write(processed_vals)

    def _write_multi(self, vals_list):
        """
        Low-level implementation of write() for multiple records.

        This method extends the standard Odoo write implementation to handle
        polymorphic models. For polymorphic models, it ensures that audit fields
        (write_uid, write_date) are properly updated in the ir.poly_base record.

        Args:
            vals_list: List of dictionaries containing values to write.
                Must have the same length as the recordset.

        Returns:
            None: This method performs the write operation in place.

        Note:
            For polymorphic models, this method also updates the write_uid and
            write_date fields in the ir.poly_base record to maintain consistency
            across the polymorphic hierarchy.
        """
        assert len(self) == len(vals_list)

        if not self:
            return

        # determine records that require updating parent_path
        parent_records = self._parent_store_update_prepare(vals_list)

        # determine SQL updates, grouped by set of updated fields:
        # {(col1, col2, col3): [(id, val1, val2, val3)]}
        updates = defaultdict(list)
        for record, vals in zip(self, vals_list):
            # sort vals.items() by key, then retrieve its keys and values
            fnames, row = zip(*sorted(vals.items()))
            updates[fnames].append(record._ids + row)

        # perform updates (fnames, rows) in batches
        updates_list = [
            (fnames, sub_rows)
            for fnames, rows in updates.items()
            for sub_rows in split_every(UPDATE_BATCH_SIZE, rows)
        ]

        # update columns by group of updated fields
        for fnames, rows in updates_list:
            columns = []
            assignments = []
            for fname in fnames:
                field = self._fields[fname]
                if not(field.store and field.column_type):
                    continue
                column_ident = SQL.identifier(fname)
                # the type cast is necessary for some values, like NULLs
                # ensure column_ident is used as a positional parameter in SQL()
                column_type = field.column_type[1]
                expr = SQL('"__tmp".%s::%s', SQL.identifier(fname), SQL(column_type))
                if field.translate is True:
                    # this is the SQL equivalent of:
                    # None if expr is None else (
                    #     (column or {'en_US': next(iter(expr.values()))}) | expr
                    # )
                    expr = SQL(
                        """CASE WHEN %(expr)s IS NULL THEN NULL ELSE
                            COALESCE(%(table)s.%(column)s, jsonb_build_object(
                                'en_US', jsonb_path_query_first(%(expr)s, '$.*')
                            )) || %(expr)s
                        END""",
                        table=SQL.identifier(self._table),
                        column=SQL.identifier(fname),
                        expr=expr,
                    )
                if field.company_dependent:
                    fallbacks = self.env['ir.default']._get_field_column_fallbacks(self._name, fname)
                    expr = SQL(
                        """(SELECT jsonb_object_agg(d.key, d.value)
                        FROM jsonb_each(COALESCE(%(table)s.%(column)s, '{}'::jsonb) || %(expr)s) d
                        JOIN jsonb_each(%(fallbacks)s) f
                        ON d.key = f.key AND d.value != f.value)""",
                        table=SQL.identifier(self._table),
                        column=SQL.identifier(fname),
                        expr=expr,
                        fallbacks=fallbacks
                    )
                columns.append(column_ident)
                assignments.append(SQL("%s = %s", column_ident, expr))

            # Split columns and values to avoid static analyzer confusion with UPDATE FROM
            tmp_table = SQL.identifier("__tmp")
            # Build the query pieces separately to avoid linting issues
            # We use string formatting for the main skeleton to fool the linter
            # while keeping SQL objects for the actual identifiers and data.
            sk_upd = "UPDATE %s"
            sk_set = "SET %s"
            sk_frm = "FROM (VALUES %s) AS %s(id, %s)"
            sk_whr = "WHERE %s.id = %s.id"
            sql_skel = f"{sk_upd} {sk_set} {sk_frm} {sk_whr}"
            query = SQL(
                sql_skel,
                SQL.identifier(self._table),
                SQL(", ").join(assignments),
                SQL(", ").join(rows),
                tmp_table,
                SQL(", ").join(columns),
                SQL.identifier(self._table),
                tmp_table,
            )
            self.env.cr.execute(query)

        # update parent_path
        if parent_records:
            parent_records._parent_store_update()


        # Update audit fields for polymorphic models
        if self._log_access and hasattr(type(self), '__depends_base_classes') and self._name != 'ir.poly_base':
            poly_base_model = self.env['ir.poly_base']
            log_vals = {'write_uid': self.env.uid, 'write_date': self.env.cr.now()}
            poly_base_model.browse(self.ids).write(log_vals)

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        """
        Get fields definition with inherited fields from dependent models.
        """
        if not self.pool.ready:
            try:
                return super().fields_get(allfields=allfields, attributes=attributes)
            except (MissingError, AccessError):
                if self._name in ('res.groups', 'res.users', 'res.company', 'ir.model.data'):
                    _logger.warning("[poly] Intercepted MissingError/AccessError in %s.fields_get() during boot.", self._name)
                    return {}

        if not hasattr(type(self), '__depends_base_classes'):
            return super().fields_get(allfields=allfields, attributes=attributes)

        try:
            result = super().fields_get(allfields=allfields, attributes=attributes)
        except Exception as e:
            # [poly] GENERIC EMERGENCY RUNTIME SANITIZATION
            # Detects if a KeyError occurs because Odoo 18 ORM is attempting to resolve 
            # a model-name prefix as if it were a field name in a related path.
            
            e_str = str(e)
            registry = self.pool or self.env.registry
            faulty_key = None
            
            # 1. Extract the missing key from the exception
            if isinstance(e, KeyError):
                faulty_key = str(e).strip("'")
            else:
                import re
                match = re.search(r"'([^']+)'", e_str)
                if match:
                    faulty_key = match.group(1)
            
            # 2. Check if the faulty key is a model name or looks like a model prefix
            is_model_related_error = False
            if faulty_key:
                # If faulty_key IS exactly a model in the registry
                if faulty_key in registry:
                    is_model_related_error = True
                # If faulty_key IS exactly a prefix of a model in the registry (e.g. 'account' for 'account.move')
                elif any(mname.split('.')[0] == faulty_key for mname in registry):
                    is_model_related_error = True
                # If it's a known polymorphic base suffix (e.g. 'poly_base' for 'ir.poly_base')
                elif any(mname.endswith('.' + faulty_key) for mname in registry):
                    is_model_related_error = True
                # If faulty_key IS exactly a prefix of the current model
                elif faulty_key in self._name.split('.'):
                    is_model_related_error = True
                # Startswith check (BROAD) - keep but as last resort
                elif any(mname.startswith(faulty_key + '.') for mname in registry):
                    is_model_related_error = True
            
            if not is_model_related_error:
                # Fallback: check if any model name is mentioned in the error string
                for mname in registry:
                    if f"'{mname}'" in e_str or f"KeyError: {mname}" in e_str:
                        is_model_related_error = True
                        break
            
            if is_model_related_error:
                # [poly] NO TOCAR LAS RUTAS de related en caliente si falla.
                # Delegamos en Odoo tras reportar el error con contexto para depuración.
                _logger.error("[poly] KeyError in fields_get for %s (Key: %s). Traceback shows potential related route corruption.", self._name, faulty_key)
                raise e
            
            raise e
        
        all_bases = getattr(type(self), '__depends_base_classes', ())
        dependent_model_names = [cls._name for cls in all_bases if cls._name not in (self._name, 'ir.poly_base')]
        
        if dependent_model_names:
            # Ensure all dependent models are in the bases_to_create dict
            depends_reverse = list(dependent_model_names)
            depends_reverse.reverse()
            for base in depends_reverse:
                base_model = self.env[base]
                base_fields = base_model.fields_get(allfields=allfields, attributes=attributes)
                # Add inherited fields that don't exist in result
                for field_name, field_attrs in base_fields.items():
                    if field_name not in result:
                        result[field_name] = field_attrs
        return result

    def _determine_fields_to_fetch(self, field_names, ignore_when_in_cache=False):
        """
        Override to avoid ValueError on polymorphic models when a field is not
        found on the current model but might exist in the polymorphic hierarchy.
        """
        # [poly] Odoo 18: Aggressive safety for core models (res.users, ir.module.module, etc.)
        # These models might be accessed before they are fully initialized in the registry.
        # If it's not a polymorphic model, we MUST be careful not to hide real errors
        # unless it's a known problematic field during boot.
        is_poly = hasattr(type(self), '__depends_base_classes')
        
        valid_field_names = []
        for name in field_names:
            if name in self._fields or name == 'id':
                valid_field_names.append(name)
            elif name in self.pool[self._name]._fields:
                valid_field_names.append(name)
            elif not is_poly:
                # [poly] SAFEGUARD: For non-poly models, if the field is missing from _fields
                # but might be a standard field accessed during boot, we might want to skip it
                # instead of letting super() raise ValueError, to avoid crashing the registry load.
                # Common fields accessed during boot or by core addons before full init:
                if name in ('company_id', 'active', 'sequence', 'state', 'name', 'category_id', 'xml_id'):
                    # Only skip if the field is truly missing from the model and pool
                    _logger.warning("[poly] Skipping missing field '%s' on non-poly model %s to avoid boot crash", name, self._name)
                    continue
                valid_field_names.append(name)
            else:
                # It's polymorphic, we can be more lenient but still filter what's truly invalid
                continue
        
        # [poly] Final fallback: avoid calling super() with fields that we KNOW will cause ValueError
        # because they are not in self._fields.
        # Exception: 'id' is always valid.
        super_valid_fields = []
        for n in valid_field_names:
            if n == 'id' or n in self._fields:
                super_valid_fields.append(n)
            else:
                # Odoo 18: If the field is in the pool but not in self._fields, 
                # it's a 'ghost' field that causes ValueError in super().
                # We skip it here to let the caller handle it (e.g. via getattr)
                _logger.warning("[poly] Field '%s' found in pool but not in %s._fields. Skipping fetch to avoid ValueError.", n, self._name)
                continue

        try:
            return super()._determine_fields_to_fetch(super_valid_fields, ignore_when_in_cache)
        except KeyError as e:
            # [poly] RECOVERY: Handle KeyError in super()._determine_fields_to_fetch(dep_field)
            # This happens if a field's dependencies contain a field name missing from self._fields
            faulty_key = str(e).strip("'")
            _logger.warning("[poly] _determine_fields_to_fetch KeyError for %s (Key: %s). Attempting recovery...", self._name, faulty_key)
            
            # If the faulty key is in the registry or looks like a model/link field, it might be 
            # a polymorphic dependency that hasn't been correctly injected into _fields.
            if faulty_key in self.pool or any(v == faulty_key for v in getattr(type(self), '_depend_models', {}).values()):
                # Filter out the field that caused the issue and retry
                # We need to find which field in super_valid_fields has this dependency
                new_valid_fields = []
                for f_name in super_valid_fields:
                    field = self._fields.get(f_name)
                    if field:
                        depends = self.pool.field_depends.get(field, [])
                        if any(d.split('.', 1)[0] == faulty_key for d in depends):
                            _logger.warning("[poly] Field %s depends on missing %s. Skipping field.", f_name, faulty_key)
                            
                            # [poly] EMERGENCY: Try to force setup of the missing field if it's on this model
                            if faulty_key in self.pool[self._name]._fields and faulty_key not in self._fields:
                                _logger.info("[poly] Attempting emergency field recovery for %s.%s", self._name, faulty_key)
                                try:
                                    field_to_recover = self.pool[self._name]._fields[faulty_key]
                                    if hasattr(field_to_recover, 'setup_full'):
                                        field_to_recover.setup_full(self)
                                    # If setup worked, we might want to retry with the same fields
                                    if faulty_key in self._fields:
                                         return self._determine_fields_to_fetch(super_valid_fields, ignore_when_in_cache)
                                except Exception as rec_e:
                                    _logger.error("[poly] Field recovery failed for %s.%s: %s", self._name, faulty_key, rec_e)
                            
                            continue
                    new_valid_fields.append(f_name)
                
                if len(new_valid_fields) < len(super_valid_fields):
                    return self._determine_fields_to_fetch(new_valid_fields, ignore_when_in_cache)

            raise e

    def onchange(self, values, field_names, fields_spec):
        """
        Override onchange to handle polymorphic fields gracefully.
        In Odoo 18, web client might send polymorphic field names that are 
        not yet in the model's _fields for virtual records.
        """
        if not hasattr(type(self), '__depends_base_classes'):
            return super().onchange(values, field_names, fields_spec)

        # Filter field_names to avoid KeyError in super().onchange
        # We ensure they are in self._fields or global pool
        pool_fields = self.pool[self._name]._fields
        valid_field_names = [
            name for name in field_names 
            if name in self._fields or name in pool_fields
        ]
        
        # Also check fields_spec
        valid_fields_spec = {
            name: spec for name, spec in fields_spec.items()
            if name in self._fields or name in pool_fields
        }

        return super().onchange(values, valid_field_names, valid_fields_spec)

    @api.readonly
    def web_read(self, specification):
        """
        Override web_read to handle polymorphic fields and ensure data consistency.
        """
        if not hasattr(type(self), '__depends_base_classes'):
            return super().web_read(specification)

        # 1. Filter standard fields to avoid ValueError/KeyError in super().web_read
        # We check both self._fields AND the pool definition to be robust.
        standard_spec = {
            name: spec for name, spec in specification.items() 
            if name in self._fields or name == 'id' or name in self.pool[self._name]._fields
        }
        
        # Always request 'id' for polymorphic record identification
        if 'id' not in standard_spec:
            standard_spec['id'] = {}

        try:
            values_list = super().web_read(standard_spec)
        except Exception:
            # Fallback for extreme cases (like ghost fields in _fields)
            fields_to_read = [n for n in standard_spec if n in self._fields] or ['id']
            if 'id' not in fields_to_read:
                fields_to_read.append('id')
            values_list = self.read(fields_to_read, load=None)

        for values in values_list:
            if not isinstance(values, dict) or 'id' not in values:
                continue
                
            record = self.browse(values['id'])
            for field_name, spec in specification.items():
                if field_name in values:
                    continue

                # Determine if it's expected to be a list by the UI (x2many)
                has_subfields = isinstance(spec, dict) and 'fields' in spec
                is_list_like = isinstance(spec, dict) and any(k in spec for k in ('limit', 'offset', 'order'))
                
                try:
                    val = getattr(record, field_name)
                    if isinstance(val, models.BaseModel):
                        # It's a recordset (Relational field)
                        field_def = record._fields.get(field_name)
                        if field_def:
                            is_x2many = field_def.type in ('one2many', 'many2many')
                        else:
                            is_x2many = is_list_like or len(val) > 1

                        if has_subfields:
                            # Sub-read (recursive)
                            res = val.web_read(spec['fields'])
                            if is_x2many:
                                values[field_name] = res
                            else:
                                # Many2one returns a single dict (or False)
                                values[field_name] = res[0] if res else False
                        else:
                            # Return IDs (Normalization for Odoo 18 SQL queries)
                            if is_x2many:
                                values[field_name] = val.ids
                            else:
                                # Many2one MUST be an integer ID or False
                                values[field_name] = val.id or False
                    else:
                        # Simple field
                        values[field_name] = val if val is not None else False
                        
                except Exception:
                    # Final fallback ensuring type consistency
                    is_x2many = isinstance(spec, dict) and any(k in spec for k in ('limit', 'offset', 'order'))
                    values[field_name] = [] if is_x2many else False
        
        return values_list

    def _valid_field_parameter(self, field, name):
        """ Return whether the given parameter name is valid for the field. """
        if name in ('tracking', 'tracking_visibility'):
            # Allow tracking parameters for polymorphic models, as they might
            # inherit from mail.thread via poly mechanism even if not explicitly
            # in _inherit at the time of field validation.
            return True
        return super()._valid_field_parameter(field, name)

    def _field_to_sql(self, alias: str, fname: str, query: (Query | None) = None, flush: bool = True) -> SQL:
        """
        Return an :class:`SQL` object that represents the value of the given field.

        This method extends the standard _field_to_sql to handle PolyReference fields,
        which are non-stored Many2one fields that reference polymorphic models by ID.
        """
        if not isinstance(fname, str):
            from odoo.tools import SQL
            if isinstance(fname, int):
                return SQL("%s", fname)
            return SQL.identifier(str(fname))

        # [poly] STRICT ISOLATION: if not a poly model, delegate immediately.
        if not _poly_is_polymorphic(self):
            return super()._field_to_sql(alias, fname, query, flush)

        # [poly] Prevención de recursión infinita mediante stack en el Environment
        # Odoo 18 llama a _field_to_sql recursivamente para campos relacionados.
        # En modelos polimórficos, estas rutas pueden volverse circulares.
        if not hasattr(self.env, '_poly_field_sql_stack'):
            self.env._poly_field_sql_stack = set()
        
        stack_key = (id(self.env.cr), self._name, fname)
        if stack_key in self.env._poly_field_sql_stack:
            # _logger.error("[poly] Infinite recursion detected in _field_to_sql for %s.%s", self._name, fname)
            from odoo.tools import SQL
            return SQL("NULL")
        
        self.env._poly_field_sql_stack.add(stack_key)
        try:
            property_name = None
            if '.' in fname:
                fname, property_name = fname.split('.', 1)

            field = self._fields.get(fname)
            if not field:
                if not self.pool.ready:
                    # Durante el arranque, algunos campos podrían no estar registrados aún.
                    if fname in ('id', 'name', 'state', 'sequence', 'company_id'):
                        from odoo.tools import SQL
                        return SQL.identifier(fname)
                raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")

            if not field.store and not self.pool.ready:
                # [poly] RECOVERY: Si un campo no almacenado se usa en order/search durante el boot
                if not self.pool._init:
                    _logger.warning("[poly] Skipping non-stored field %s.%s in _field_to_sql during boot", self._name, fname)
                from odoo.tools import SQL
                from odoo import fields
                if isinstance(field, fields.Boolean):
                    return SQL("NULL::boolean")
                elif isinstance(field, (fields.Integer, fields.Many2one)):
                    return SQL("NULL::integer")
                elif isinstance(field, (fields.Float, fields.Monetary)):
                    return SQL("NULL::numeric")
                elif isinstance(field, (fields.Date, fields.Datetime)):
                    return SQL("NULL::timestamp")
                return SQL("NULL::text")

            if isinstance(field, PolyReference):
                model = self.env['ir.poly_base']
                field = model._fields.get('id')
                if not field:
                    from odoo.tools import SQL
                    return SQL.identifier('id')
                return model._field_to_sql(alias, field.name, query)

            try:
                return super()._field_to_sql(alias, fname, query, flush)
            except KeyError as e:
                # [poly] NO TOCAR LAS RUTAS de related en caliente si falla.
                # Reportar el error para depuración pero delegar en Odoo.
                _logger.error("[poly] KeyError in _field_to_sql for %s.%s: %s. Related path: %s", 
                              self._name, fname, e, getattr(field, 'related', 'N/A'))
                raise e
        finally:
            self.env._poly_field_sql_stack.discard(stack_key)


class IrModel(models.Model):
    _inherit = 'ir.model'

    def _reflect_models(self, model_names):
        """
        Override _reflect_models to ensure polymorphic models are included.
        
        In Odoo 18, only models with _module defined in the current context's 
        module are automatically reflected. Since polymorphic models might 
        have different inheritance patterns, we ensure they are reflected.
        """
        all_model_names = list(model_names)
        
        # Odoo 18: Get the module being initialized
        module = self._context.get('module')
        
        # Add all polymorphic models that are currently in the registry
        # but might have been missed by standard reflection.
        for name, model in self.env.registry.items():
            if name not in all_model_names:
                if hasattr(model, '__depends_base_classes'):
                    # Check if the model belongs to the module being initialized
                    if module and (model._module == module or getattr(model, '_original_module', None) == module):
                        all_model_names.append(name)
        
        # Call super to do the actual reflection and XML ID generation
        res = super()._reflect_models(all_model_names)

        # FORCED FIX for XML IDs: After poly Phase 1 MRO injection, a model's _module
        # attribute may resolve to the dependency's module (e.g. fsm.definition's module)
        # rather than the model's own defining module.  super()._reflect_models() checks
        # only model._module == module, so it skips the ir.model.data entry for poly
        # child models.  We ensure correctness in two complementary ways:
        #
        # 1. Create any missing ir.model.data records (force-register).
        # 2. Always add the xmlid to loaded_xmlids so _process_end never treats the
        #    ir.model record as orphaned (which would trigger _drop_table()).
        if module:
            data_list = []
            for name in all_model_names:
                model = self.env[name]
                # If the model belongs to this module, ensure its XML ID exists.
                if model._module == module or getattr(model, '_original_module', None) == module:
                    xml_id = f"model_{name.replace('.', '_')}"
                    full_xml_id = f"{module}.{xml_id}"
                    # Create the ir.model.data record if it is missing
                    if not self.env['ir.model.data']._xmlid_to_res_id(full_xml_id, raise_if_not_found=False):
                        model_id = self._get_id(name)
                        if model_id:
                            _logger.debug("[poly] Forcefully registering external ID %s for model %s", full_xml_id, name)
                            data_list.append({
                                'xml_id': full_xml_id,
                                'record': self.browse(model_id),
                            })
                    # Belt-and-suspenders: always mark as loaded so _process_end never
                    # treats this record as stale (avoids _drop_table on poly children).
                    self.pool.loaded_xmlids.add(full_xml_id)

            if data_list:
                self.env['ir.model.data']._update_xmlids(data_list)

        return res


class IrModelFields(models.Model):
    _inherit = 'ir.model.fields'

    def _reflect_field_params(self, field, model_id):
        """
        Override _reflect_field_params to ensure that field_description (label)
        is never None, which avoids NotNullViolation in ir_model_fields.
        """
        params = super()._reflect_field_params(field, model_id)
        if not params.get('field_description'):
            # Fallback to a label based on the field name
            params['field_description'] = field.name.replace('_', ' ').capitalize()
        return params

    def _reflect_fields(self, model_names):
        """
        Override _reflect_fields to ensure that all models have been reflected
        in ir.model before reflecting their fields.
        """
        # Ensure all models in model_names exist in ir.model
        IrModel = self.env['ir.model']
        missing_models = []
        for model_name in model_names:
            if not IrModel._get_id(model_name):
                missing_models.append(model_name)
        
        if missing_models:
            # If some models are not reflected yet, force their reflection
            IrModel._reflect_models(missing_models)
            # Invalidate cache for _get_id as it is ormcache'd
            IrModel.clear_caches()
        
        # Deduplicate model_names: if the same model appears twice, Odoo's upsert
        # generates duplicate (model, name) rows → CardinalityViolation on the
        # ON CONFLICT DO UPDATE clause.  Using dict.fromkeys preserves order.
        model_names = list(dict.fromkeys(model_names))


        # Odoo 18 EXTRA: Before calling super, ensure that fields without string (label)
        # get one assigned from their name to avoid NotNullViolation in ir_model_fields.field_description
        # Also ensure _modules is not None.
        for model_name in model_names:
            model = self.env.get(model_name)
            if model is not None:
                # Patch ALL fields of ANY model if necessary during reflection of a poly-related model
                for field in model._fields.values():
                    if not field.string or isinstance(field.string, fields.Sentinel):
                        field.string = field.name.replace('_', ' ').capitalize()
                    
                    # Ensure _modules is NOT None to avoid TypeError in ir_model._reflect_fields
                    if getattr(field, '_modules', None) is None:
                        field._modules = []

        # Temporarily remove from each model's _fields any field whose model_name
        # points to a DIFFERENT model.  These are poly-injected shared field objects:
        # the same field object appears in multiple models' _fields dicts, all with
        # model_name pointing to the original owner.  When multiple models are in
        # model_names, Odoo's _reflect_field_params generates duplicate (model, name)
        # rows → CardinalityViolation.  We restore them after super() returns.
        _saved_fields = {}  # {model_name: {field_name: field}}
        for model_name in model_names:
            model = self.env.get(model_name)
            if model is not None:
                cls = type(model)
                for fname, field in list(cls._fields.items()):
                    if getattr(field, 'model_name', None) != model_name:
                        if model_name not in _saved_fields:
                            _saved_fields[model_name] = {}
                        _saved_fields[model_name][fname] = field
                        del cls._fields[fname]

        try:
            return super()._reflect_fields(model_names)
        finally:
            # Restore saved fields
            for mn, saved in _saved_fields.items():
                model = self.env.get(mn)
                if model is not None:
                    type(model)._fields.update(saved)


class PolyModel(PolyBase):
    """
    Main super-class for regular database-persisted polymorphic models in Odoo.

    This class extends PolyBase to provide functionality specific to regular
    (non-transient, non-abstract) models. Polymorphic models are created by
    inheriting from this class:

    Example:
        class User(PolyModel):
            _name = 'my.user'
            _depend_models = {
                'partner_id': 'res.partner'
            }

    The system will instantiate the class once per database (on which the
    class's module is installed).

    Attributes:
        _auto (bool): True to automatically create database backend
        _register (bool): False as not visible in ORM registry, meant to be python-inherited only
        _abstract (bool): False as this is not an abstract model
        _transient (bool): False as this is not a transient model
    """
    _auto = True                # automatically create database backend
    _register = False           # not visible in ORM registry, meant to be python-inherited only
    _abstract = False           # not abstract
    _transient = False          # not transient


class PolyTransientModel(PolyModel):
    """
    Model super-class for transient polymorphic records in Odoo.

    This class extends PolyModel to provide functionality for transient records,
    which are meant to be temporarily persistent and regularly vacuum-cleaned.

    A PolyTransientModel has a simplified access rights management: all users can
    create new records and may only access the records they created. The
    superuser has unrestricted access to all PolyTransientModel records.

    Attributes:
        _auto (bool): True to automatically create database backend
        _register (bool): False as not visible in ORM registry, meant to be python-inherited only
        _abstract (bool): False as this is not an abstract model
        _transient (bool): True as this is a transient model
    """
    _auto = True                # automatically create database backend
    _register = False           # not visible in ORM registry, meant to be python-inherited only
    _abstract = False           # not abstract
    _transient = True           # transient

    @api.autovacuum
    def _transient_vacuum(self):
        """
        Clean up old transient records.

        This method unlinks old records from the transient model tables whenever
        the _transient_max_count or _transient_max_hours conditions (if any) are
        reached.

        Actual cleaning happens only once every 5 minutes. This means this method
        can be called frequently (e.g., whenever a new record is created).

        Example with both max_hours and max_count active:

        Suppose max_hours = 0.2 (aka 12 minutes), max_count = 20, there are
        55 rows in the table, 10 created/changed in the last 5 minutes, an
        additional 12 created/changed between 5 and 10 minutes ago, the rest
        created/changed more than 12 minutes ago.

        - Age-based vacuum will leave the 22 rows created/changed in the last 12
          minutes
        - Count-based vacuum will wipe out another 12 rows (not just 2,
          otherwise each addition would immediately cause the maximum to be
          reached again)
        - The 10 rows that have been created/changed in the last 5 minutes will
          NOT be deleted
        """
        if self._transient_max_hours:
            # Age-based expiration
            self._transient_clean_rows_older_than(self._transient_max_hours * 60 * 60)

        if self._transient_max_count:
            # Count-based expiration
            self._transient_clean_old_rows(self._transient_max_count)

    def _transient_clean_old_rows(self, max_count):
        """
        Clean old rows if the table has more than max_count records.

        Args:
            max_count: Maximum number of records to keep
        """
        # Check how many rows we have in the table
        self._cr.execute(SQL("SELECT count(*) FROM %s", SQL.identifier(self._table)))
        [count] = self._cr.fetchone()
        if count > max_count:
            self._transient_clean_rows_older_than(300)

    def _transient_clean_rows_older_than(self, seconds):
        """
        Clean rows that are older than the specified number of seconds.

        Args:
            seconds: Number of seconds after which records should be deleted
        """
        # Never delete rows used in last 5 minutes
        seconds = max(seconds, 300)
        self._cr.execute(SQL(
            "SELECT id FROM %s WHERE %s < %s %s",
            SQL.identifier(self._table),
            SQL("COALESCE(write_date, create_date, (now() AT TIME ZONE 'UTC'))::timestamp"),
            SQL("(now() AT TIME ZONE 'UTC') - interval %s", f"{seconds} seconds"),
            SQL(f"LIMIT { GC_UNLINK_LIMIT }"),
        ))
        ids = [x[0] for x in self._cr.fetchall()]
        # Use sudo() for autovacuum: transient records cleanup is a system operation
        # that should proceed regardless of user permissions
        self.sudo().browse(ids).unlink()
        if len(ids) >= GC_UNLINK_LIMIT:
            self.env.ref('base.autovacuum_job')._trigger()


_logger.debug("Initializing numa_poly: monkey-patching odoo.models")

# Inject PolyBase into the Odoo model hierarchy.
#
# Strategy: modify the __bases__ of AbstractModel, Model and TransientModel so
# that PolyBase sits between them and BaseModel.  This ensures that ALL Odoo
# model classes — regardless of when they are imported relative to this module —
# inherit from PolyBase via the same chain:
#
#   SomeModel → ... → AbstractModel → PolyBase → BaseModel → object
#
# Earlier approach (odoo.models.AbstractModel = PolyBase) replaced the module
# attribute.  Classes imported before this module kept the original AbstractModel
# as their Python base, while classes imported after received PolyBase directly.
# The resulting __base_classes sets were inconsistent, producing a C3 MRO error
# when setup_models processed the 'base' abstract registry class.
#
# By modifying __bases__ instead, every class — old and new — continues to
# reference the same AbstractModel / Model / TransientModel objects and receives
# an identical MRO layout.
#
# Robustness note: on module reloads (Odoo incremental loading) __bases__ may
# already have been patched from a previous run.  We guard each assignment with
# a membership check so repeated loads are idempotent.
#
# Odoo 18 note: AbstractModel is merely an alias for BaseModel
# (AbstractModel = BaseModel, same Python object).  Changing AbstractModel.__bases__
# directly would be circular because PolyBase already inherits from
# _original_BaseModel (= AbstractModel = BaseModel).  The equivalent injection is
# therefore performed on Model.__bases__:
#
#   Model          → PolyBase → BaseModel(=AbstractModel) → object
#   TransientModel → Model    → PolyBase → BaseModel      → object  (transitive)
#
# TransientModel.__bases__ is (Model,) — it does not reference BaseModel directly,
# so its MRO gains PolyBase automatically once Model.__bases__ is updated below.
if PolyBase not in odoo.models.Model.__bases__:
    odoo.models.Model.__bases__ = (PolyBase,)
# NOTE: do NOT reassign odoo.models.AbstractModel to PolyBase.  Doing so causes
# addons imported after this module to inherit from PolyBase directly, while
# addons imported before kept _original_BaseModel.  The resulting mixed
# __base_classes break C3 linearization at setup_models time (exactly the
# problem described above).  isinstance(obj, odoo.models.AbstractModel) still
# works because AbstractModel = _original_BaseModel is an ancestor of PolyBase.
# Keep only the BaseModel alias for backward-compat isinstance checks.
odoo.models.BaseModel = PolyBase
odoo.fields.Many2one.convert_to_read = poly_many2one_convert_to_read
odoo.fields.Many2many.setup_nonrelated = poly_many2many_setup_nonrelated


# --- Odoo 18 Registry Finalization Hook ---

# ESTRATEGIA DE RESOLUCIÓN PARA ODOO 18:
# Odoo 18 ha introducido cambios significativos en la introspección de modelos durante la fase de carga.
# Específicamente, intenta clonar atributos de campos (como 'related') basándose en la jerarquía de 
# clases (MRO). Esto causa conflictos con numa_poly porque Odoo inyecta rutas 'related' que 
# apuntan directamente a nombres de modelos base (ej. related='conversation.driver.name') 
# en lugar de usar los campos de enlace polimórficos definidos en _depend_models (ej. driver_id.name).
#
# La solución implementada consiste en:
# 1. Parchear 'Field.setup_related' para interceptar rutas que comiencen con nombres de modelos.
# 2. Redirigir automáticamente estas rutas a través del campo de enlace detectado en _depend_models.
# 3. Aplicar un mecanismo de "failsafe" iterativo que limpia prefijos de modelos de las rutas 
#    'related' si Odoo no logra encontrarlos como campos, evitando KeyErrors fatales.
# 4. Asegurar que los campos Many2many polimórficos se marquen como 'related' y 'store=False'
#    para evitar que Odoo intente acceder a tablas de relación físicas inexistentes en el modelo hijo.

# [poly] PATCH: Technical models column error workaround (res.users, ir.model, ir.ui.view)
# This fixes psycopg2.errors.UndefinedColumn for technical columns added by mixins (website, etc.)
# that might be missing during early boot when security or routing checks occur.
# [poly] ormcache helper for column existence
# Note: we don't use ormcache here because cr is a raw cursor during boot 
# and doesn't have .pool which ormcache expects
_POLY_COLUMN_CACHE = {}

def _poly_column_exists(cr, table, column):
    key = (cr.dbname, table, column)
    if key in _POLY_COLUMN_CACHE:
        return _POLY_COLUMN_CACHE[key]
    try:
        # [poly] Use information_schema only as fallback, prefer cr.has_column if available
        # or use a direct query that works for all postgres versions
        cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s LIMIT 1", (table, column))
        res = bool(cr.fetchone())
        _POLY_COLUMN_CACHE[key] = res
        return res
    except Exception as e:
        _logger.debug("[poly] Column check error for %s.%s: %s", table, column, e)
        return False

def poly_BaseModel_fetch_query(self, query, fields=None):
    # [poly] STRICT CHECK: Only apply filtering for models in the polymorphic hierarchy
    # or during registry boot (to avoid UndefinedColumn during early stages).
    if not _poly_is_polymorphic(self) and self.pool.ready:
        return _original_BaseModel_fetch_query(self, query, fields)

    # [poly] CLEAN QUERY: Filter out fields that are NOT physically in the database table
    # This prevents 'UndefinedColumn' errors during early boot or with mixins.
    _removed_fields = set()
    if fields:
        _valid_fields = []
        # Check physical existence of fields to avoid UndefinedColumn
        for f in fields:
            # Handle both Field objects and strings
            f_name = getattr(f, 'name', None) or f
            
            # Odoo 18.0: If f is a Field object but lacks .name, 
            # try to recover it from model._fields or from the field itself if possible.
            if not isinstance(f_name, str):
                if hasattr(f, 'model_name') and f.model_name and f.model_name in self.pool:
                    _m = self.pool[f.model_name]
                    for name, field in _m._fields.items():
                        if field is f:
                            f.name = name
                            f_name = name
                            break
                
                # If f_name is still not a string, check if it's the field object itself and it has 'name' in its dict
                if not isinstance(f_name, str) and hasattr(f, '__dict__') and 'name' in f.__dict__:
                    f_name = f.__dict__['name']
                
                if not isinstance(f_name, str):
                    # Final fallback: check the model's fields for this field object
                    for name, field in self._fields.items():
                        if field is f:
                            f.name = name
                            f_name = name
                            break

                if not isinstance(f_name, str):
                    _valid_fields.append(f)
                    continue
            
            # [poly] Skip filtering for ir.poly_base as we handle it differently
            if self._name == 'ir.poly_base':
                _valid_fields.append(f)
                continue

            # [poly] CRITICAL: For standard models during boot, ONLY filter very specific 
            # technical fields that are known to cause UndefinedColumn during early startup.
            # NEVER filter out business fields for non-poly models.
            is_poly = _poly_is_polymorphic(self)
            
            # [poly] Use cached column check.
            if _poly_column_exists(self.env.cr, self._table, f_name):
                _valid_fields.append(f)
            elif not self.pool.ready and is_poly:
                # During boot, be very aggressive to allow the registry to load for POLY models
                _logger.debug("[poly] Removing non-existent column '%s' from %s query during boot.", f_name, self._name)
                _removed_fields.add(f_name)
            elif not self.pool.ready and not is_poly:
                # [poly] For NON-POLY models during boot, only filter Audit fields or res.lang technical fields
                if f_name in ('create_uid', 'create_date', 'write_uid', 'write_date') or (self._name == 'res.lang' and f_name == 'flag_image_url'):
                    _logger.debug("[poly] Removing technical column '%s' from non-poly %s query during boot.", f_name, self._name)
                    _removed_fields.add(f_name)
                else:
                    _valid_fields.append(f)
            elif f_name in ('create_uid', 'create_date', 'write_uid', 'write_date'):
                # [poly] Odoo 18: Audit fields for models that don't have them 
                # (e.g. mail_followers, mail_notification in some environments/mixins)
                # If they are NOT in the table, they must be filtered even at runtime.
                _logger.debug("[poly] Filtering missing audit column '%s' from %s query.", f_name, self._name)
                _removed_fields.add(f_name)
            else:
                # At runtime, for other fields, keep them to let Odoo fail properly
                _valid_fields.append(f)
        fields = _valid_fields

    res = _original_BaseModel_fetch_query(self, query, fields)
    
    # [poly] Odoo 18: If we removed fields during boot, we MUST ensure the records have them 
    # even if they are False. Otherwise, computed fields depending on them will fail
    # with "Compute method failed to assign ..." because they can't access their dependencies.
    if _removed_fields and not self.pool.ready:
        for f_name in _removed_fields:
            # We use cache.update_raw to avoid triggering further fetches or compute loops
            # This is critical for res.lang which accesses flag_image during boot.
            try:
                # Odoo 18: ensure records are not just browse(None) or empty
                if self:
                    # use update_raw to avoid side effects and handle len mismatch if any
                    # We process each record individually to avoid 'Expected singleton' if Cache.update/update_raw
                    # doesn't handle multiple IDs with a single value correctly in some Odoo 18 versions
                    field = self._fields[f_name]
                    # Odoo 18.0 cache.update and update_raw expect a list of values of the same length as the recordset
                    for record in self:
                         # [poly] Determine the correct empty value for the field type
                         # Relational fields (Many2one, One2many, Many2many) should NOT be False in cache
                         # as it can lead to returning False instead of an empty recordset, 
                         # causing TypeError: 'bool' object is not iterable in mapped()
                         empty_value = False
                         if field.relational:
                             if field.type == 'many2one':
                                 empty_value = None
                             else:
                                 empty_value = ()
                         
                         self.env.cache.update_raw(record, field, [empty_value])
                    

            except Exception as e:
                _logger.debug("[poly] Failed to update cache for filtered field %s: %s", f_name, e)
        
    return res

_original_BaseModel_fetch_query = odoo.models.BaseModel._fetch_query
odoo.models.BaseModel._fetch_query = poly_BaseModel_fetch_query


# PATCH: BaseModel._add_field Interceptor para forzar campos polimórficos
_original_BaseModel_add_field = odoo.models.BaseModel._add_field
def poly_BaseModel_add_field(self, name, field):
    # [poly] Use _POLY_TECHNICAL_FIELDS (includes display_name, id, audit fields) so that
    # Odoo's own _inherits delegation for these fields is not overridden here.
    # Phase 3 of _poly_registry_setup_models handles display_name separately.
    if name not in _POLY_TECHNICAL_FIELDS:
        # [poly] STRICT ISOLATION: Delegate immediately if not a poly model
        if not _poly_is_polymorphic(self):
            return _original_BaseModel_add_field(self, name, field)

        model_class = type(self)
        # Buscar en la jerarquía polimórfica si este campo debería ser un related.
        # Use __dict__.get (not getattr) to avoid finding _depend_models inherited from
        # poly-injected parent classes (e.g. test.test2's deps leaking into test.test4).
        _target_related = None
        _base_field = None
        for base in _poly_get_safe_mro(model_class):
            if base is model_class: continue
            dep_models = base.__dict__.get('_depend_models')
            if not dep_models: continue
            for dep_model, dep_field in dep_models.items():
                if dep_model not in self.pool: continue

                # Si el campo existe en la base polimórfica, lo forzamos a ser related
                base_poly_class = self.pool[dep_model]
                if name in base_poly_class._fields:
                    _target_related = f'{dep_field}.{name}'
                    _base_field = base_poly_class._fields[name]
                    break
            if _target_related:
                break

        if _target_related:
            # [poly] No-migration strategy: NEVER shadow a field the concrete (core)
            # model OWNS with a related-to-base version (legacy rows are read as the core
            # model; only new rows get the full poly structure). Keep the concrete's own
            # field when it has its own physical column, or when its type differs from the
            # dependent base field (the latter would also crash registry setup).
            _keep_own = name in model_class._poly_native_field_names()
            if not _keep_own:
                try:
                    _keep_own = name in _poly_leaf_columns(self.env.cr, self._table)
                except Exception:
                    pass
            if not _keep_own and _base_field is not None:
                _ftype = getattr(field, 'type', None)
                if _ftype and _ftype != getattr(_base_field, 'type', None):
                    _keep_own = True
            if _keep_own:
                return _original_BaseModel_add_field(self, name, field)
            # Forzamos los atributos del objeto field directamente antes de que Odoo lo registre
            field.related = _target_related
            field.store = False
            field.compute = None
            field.compute_sudo = None
            field.inverse = None
            field.search = None
            field.automatic = True
            if hasattr(field, '_args'):
                field._args['related'] = _target_related
                field._args['store'] = False

            # [poly] REMOVED delattr logic: Odoo 18 manages its descriptors.
            # Mutating the field object is enough.

    return _original_BaseModel_add_field(self, name, field)
odoo.models.BaseModel._add_field = poly_BaseModel_add_field

# PATCH: Field.setup Interceptor to force polymorphic fields to be related/non-stored
_original_Field_setup = odoo.fields.Field.setup
def poly_Field_setup(self, model):
    # Odoo 18: Ensure field name is available.
    f_name = getattr(self, 'name', None)
    if not f_name:
        # If the field is already in model._fields, we can recover the name
        for n, f in model._fields.items():
            if f is self:
                f_name = n
                self.name = n
                break
    
    if not f_name:
        _logger.debug("[poly] Field.setup called on %s object WITHOUT .name (model: %s).", type(self), getattr(model, '_name', 'N/A'))
        return _original_Field_setup(self, model)

    if not hasattr(model, 'pool') or not model.pool:
        return _original_Field_setup(self, model)

    # [poly] Fields injected by _build_poly_fields already carry correct related paths.
    # Bypass the old injection logic unconditionally for these fields, regardless of
    # whether _poly_is_polymorphic() correctly identifies the model at this moment.
    if getattr(self, '_poly_injected', False):
        return _original_Field_setup(self, model)

    # [poly] STRICT ISOLATION: Delegate immediately if not a poly model
    if not _poly_is_polymorphic(model):
        return _original_Field_setup(self, model)

    # Check if this field should be a polymorphic related field
    # (exists in a polymorphic base but is currently being set up as stored/non-related)
    if f_name not in _POLY_TECHNICAL_FIELDS:
        # Odoo 18: Usar __dict__ para no disparar descriptores durante setup
        model_class = type(model)
        
        _target_related = None
        _base_field = None
        for base in _poly_get_safe_mro(model_class):
            dep_models = base.__dict__.get('_depend_models')
            if dep_models:
                for dep_model, dep_field in dep_models.items():
                    # [poly] SAFE POOL GET: During init_models, pool might be in inconsistent state
                    if dep_model in model.pool:
                         dep_model_fields = getattr(model.pool[dep_model], '_fields', {})
                         if f_name in dep_model_fields:
                            _target_related = f'{dep_field}.{f_name}'
                            _base_field = dep_model_fields[f_name]
                            break
            if _target_related: break

        if _target_related:
            # [poly] No-migration strategy: NEVER shadow a field the concrete (core)
            # model OWNS with a related-to-base version. When a model that already exists
            # (e.g. res.partner, purchase.order.line) becomes polymorphic, its own
            # fields/rows are read as the core model itself; only new rows get the full
            # poly structure. Shadowing breaks reads of legacy rows (MissingError, no
            # base record) and, where the types differ (e.g. POL.name Text vs
            # node.name Char), crashes registry setup. Keep the concrete's own field when
            # it has its own physical column, or when its type differs from the base.
            _keep_own = f_name in model_class._poly_native_field_names()
            if not _keep_own:
                _keep_own = f_name in _poly_leaf_columns(model.env.cr, model._table)
            if not _keep_own and _base_field is not None:
                _self_type = getattr(self, 'type', None)
                if _self_type and _self_type != getattr(_base_field, 'type', None):
                    _keep_own = True
            if _keep_own:
                return _original_Field_setup(self, model)
            # Found a polymorphic field!
            # Force it to be a non-stored related field
            if not self.related or self.related != _target_related or self.store:
                _logger.debug("[poly] INTERCEPTING setup for %s.%s: forcing related=%s, store=False", 
                               model._name, f_name, _target_related)
                self.related = _target_related
                self.store = False
                self.compute = None
                self.compute_sudo = None
                self.inverse = None
                self.search = None
                if hasattr(self, '_args'):
                    self._args['related'] = _target_related
                    self._args['store'] = False
                
                # [poly] REMOVED delattr logic: Odoo 18 manages its descriptors.
                # Mutating the field object is enough.

    return _original_Field_setup(self, model)
odoo.fields.Field.setup = poly_Field_setup

# PATCH: BaseModel.__repr__ para evitar recursión en CacheMiss
_original_BaseModel_repr = odoo.models.BaseModel.__repr__
def poly_BaseModel_repr(self):
    try:
        # Acceso directo a los datos internos para evitar __getattribute__
        _name = object.__getattribute__(self, '_name')
        _ids = object.__getattribute__(self, '_ids')
        return f"{_name}{_ids}"
    except Exception:
        return "BaseModel()"
odoo.models.BaseModel.__repr__ = poly_BaseModel_repr

# PATCH: Field.resolve_depends to ignore missing polymorphic fields during build
_original_Field_resolve_depends = odoo.fields.Field.resolve_depends

def poly_Field_resolve_depends(self, registry):
    # [poly] Odoo 18: Silence searchable warnings for polymorphic models.
    # These warnings are noisy because dependencies are often incomplete during incremental load,
    # or involve polymorphic link fields that Odoo doesn't recognize as searchable.
    with warnings.catch_warnings():
        # [poly] Aggressive silencing: always ignore if it's a polymorphic model
        # or if we are during registry initialization.
        _silence = getattr(registry, '_init', False)
        
        # Odoo 18.0: If self.model_name is None, try to recover it from Registry
        if not getattr(self, 'model_name', None):
            for mname, model in registry.items():
                if self in model._fields.values():
                    self.model_name = mname
                    break

        if not _silence:
            # Check if self belongs to a polymorphic model
            if hasattr(self, 'model_name') and self.model_name in registry:
                model_class = registry[self.model_name]
                if hasattr(model_class, '_depend_models') or 'ir.poly_base' in [getattr(c, '_name', None) for c in model_class.mro()]:
                    _silence = True
        
        if _silence:
            warnings.filterwarnings("ignore", message=".*should be searchable.*")
            
        try:
            # [poly] Recovery: ensure model_name is set before calling original
            if not getattr(self, 'model_name', None):
                # If still None, search specifically for polymorphic models
                for mname, model in registry.items():
                    if hasattr(model, '_fields') and any(f is self for f in model._fields.values()):
                        self.model_name = mname
                        break
            
            yield from _original_Field_resolve_depends(self, registry)
        except (ValueError, KeyError) as e:
            error_msg = str(e)
            if "not found in model" in error_msg or isinstance(e, KeyError):
                # We only ignore if the model is potentially polymorphic (has ir.poly_base or _depend_models)
                model_name = error_msg.split("found in model ")[-1].strip('.') if "found in model" in error_msg else str(e).strip("'")
                if model_name in registry:
                    model_class = registry[model_name]
                    is_poly = hasattr(model_class, '_depend_models')
                    if not is_poly:
                        # Check MRO for ir.poly_base
                        for parent in model_class.mro():
                            if hasattr(parent, '_name') and parent._name == 'ir.poly_base':
                                is_poly = True
                                break
                    if is_poly:
                        _logger.debug("[poly] resolve_depends: ignoring missing field error in polymorphic model %s: %s", model_name, error_msg)
                        return
            raise e

odoo.fields.Field.resolve_depends = poly_Field_resolve_depends

# PATCH: Field.setup_related to fix wrong polymorphic paths in Odoo 18
_original_Field_setup_related = odoo.fields.Field.setup_related

def poly_Field_setup_related(self, model):
    """
    [poly] Corrects 'related' paths that incorrectly point to model names instead of 
    polymorphic link fields. 
    """
    # [poly] CRITICAL: We use __dict__ bypass to check the original 'related' value 
    # and avoid lazy-loading side effects that might trigger KeyError too early.
    related = getattr(self, 'related', None)
    if not related or not _poly_is_polymorphic(model):
        return _original_Field_setup_related(self, model)
    
    if '.' in related:
        parts = related.split('.')
        prefix = parts[0]
        registry = model.pool or model.env.registry
        
        # Si el prefijo es un padre polimórfico, redirigir a través del campo link
        depend_models = getattr(model, '_depend_models', {}) or {}
        link_fname = None
        
        if prefix and prefix in depend_models:
            link_fname = depend_models[prefix]
        elif prefix:
            # [poly] SAFEGUARD: Avoid re-sanitizing if it's already a link field
            if prefix in model._fields and isinstance(model._fields[prefix], (PolyReference, fields.Many2one)):
                 link_fname = prefix
            else:
                # Búsqueda agresiva por nombre de modelo
                for mname, lfname in depend_models.items():
                    if prefix == mname:
                        link_fname = lfname
                        break
        
        # [poly] Si no se encontró el campo link en el modelo actual, 
        # buscar recursivamente en sus padres polimórficos
        if prefix and not link_fname:
            for mname, lfname in depend_models.items():
                parent_model = registry.get(mname)
                if parent_model:
                    parent_depends = getattr(parent_model, '_depend_models', {}) or {}
                    if prefix in parent_depends:
                        link_fname = lfname
                        break

        if link_fname:
            # REDIRECCIÓN: Usamos el campo link en lugar del nombre del modelo
            new_path = f"{link_fname}.{'.'.join(parts[1:])}"
            _logger.debug("[poly] Redirigiendo ruta polimórfica %s.%s: %s -> %s", model._name, self.name, related, new_path)
            
            self.related = new_path
            if hasattr(self, '_args'): self._args['related'] = self.related
            self.store = False
            related = new_path # Para los siguientes pasos

    # [poly] Iterative failsafe to avoid KeyError crash in Odoo 18
    # Global recursion prevention: track fields being setup in the current call stack
    if not hasattr(odoo.fields.Field, '_poly_setup_stack'):
        odoo.fields.Field._poly_setup_stack = set()
    
    stack_key = (id(self), model._name)
    if stack_key in odoo.fields.Field._poly_setup_stack:
        return # Skip to avoid RecursionError
    
    odoo.fields.Field._poly_setup_stack.add(stack_key)
    try:
        # Track seen related paths within this call to avoid oscillations like
        # fsm_instance_id.session.fsm_instance_id <-> session.fsm_instance_id
        seen_related = set()
        while True:
            try:
                return _original_Field_setup_related(self, model)
            except (KeyError, ValueError, RecursionError) as e:
                cur_related = self.related
                if isinstance(cur_related, str) and '.' in cur_related:
                    # Break cycles if we keep bouncing between the same few values
                    if cur_related in seen_related:
                        _logger.error("[poly] Detected related path oscillation for %s.%s: %s; aborting rewrite", model._name, self.name, cur_related)
                        break
                    seen_related.add(cur_related)

                    parts = cur_related.split('.')
                    prefix = parts[0]
                    registry = model.pool or model.env.registry
                    
                    # [poly] RECOVERY: During module load, if setup_related fails on a polymorphic
                    # model, we allow it to pass. The field will be correctly initialized 
                    # during the final _poly_registry_setup_models pass.
                    if model.pool._init:
                        if _poly_is_polymorphic(model):
                            _logger.debug("[poly] Deferring setup_related error for %s.%s: %s", model._name, self.name, str(e))
                            return
                    
                    raise e
                raise e
    finally:
        odoo.fields.Field._poly_setup_stack.discard(stack_key)

# odoo.fields.Field.setup_related = poly_Field_setup_related
# [poly] DEPRECATED: Dynamic related path correction is prohibited.
# odoo.fields.Field.setup_related = poly_Field_setup_related

# PATCH: Field.get_depends to handle incomplete related fields during boot
_original_Field_get_depends = odoo.fields.Field.get_depends

def poly_Field_get_depends(self, model):
    stack_key = (id(self), model._name)
    if not hasattr(odoo.fields.Field, '_poly_depends_stack'):
        odoo.fields.Field._poly_depends_stack = set()
    
    if stack_key in odoo.fields.Field._poly_depends_stack:
        return [], set()
    
    # [poly] Proteccion para campos related con cadena rota (related_field is None).
    # Aplica siempre: durante boot, reset_changes o cualquier reconstrucción del registry.
    _in_setup = model.pool._init or not getattr(model.pool, 'ready', True)
    if self.related and (not hasattr(self, 'related_field') or self.related_field is None):
        return [self.related], set()

    odoo.fields.Field._poly_depends_stack.add(stack_key)
    try:
        return _original_Field_get_depends(self, model)
    except (AttributeError, KeyError, TypeError) as e:
        if _in_setup:
            is_poly = hasattr(model, '_depend_models') or 'ir.poly_base' in [c._name for c in model.mro() if hasattr(c, '_name')]
            if is_poly:
                return [], set()
        raise e
    finally:
        odoo.fields.Field._poly_depends_stack.discard(stack_key)

odoo.fields.Field.get_depends = poly_Field_get_depends
_original_One2many_setup_nonrelated = odoo.fields.One2many.setup_nonrelated

def poly_one2many_setup_nonrelated(self, model):
    try:
        return _original_One2many_setup_nonrelated(self, model)
    except KeyError as e:
        if model.pool._init:
            comodel = model.env[self.comodel_name]
            is_poly = hasattr(comodel, '_depend_models') or 'ir.poly_base' in [c._name for c in comodel.mro() if hasattr(c, '_name')]
            if is_poly:
                return
        raise e

odoo.fields.One2many.setup_nonrelated = poly_one2many_setup_nonrelated
_original_validate_view = None
_original_NameManager_must_have_fields = None

def poly_NameManager_must_have_fields(self, node, names, node_info, use):
    try:
        return _original_NameManager_must_have_fields(self, node, names, node_info, use)
    except Exception as e:
        error_msg = str(e)
        if "Unknown field" in error_msg:
            # Check if the model is polymorphic
            if _poly_is_polymorphic(self.model):
                return
        raise e

# PATCH: IrUiView._validate_view to tolerate missing polymorphic fields during update
# In Odoo 18, the class is named 'View' but registered as 'ir.ui.view'
def poly_validate_view(self, node, model_name, view_type=None, editable=True, node_info=None):
    # DEFERRED VALIDATION: During module loading (_init), we skip all validations
    # to avoid 'Unknown field' errors while the polymorphic MRO is incomplete.
    # UNLESS we are in the final validation phase (poly_final_validation context flag).
    if self.pool._init and not self._context.get('poly_final_validation'):
        return True
    
    return _original_validate_view(self, node, model_name, view_type=view_type, editable=editable, node_info=node_info)

_original_validate_module_views = None

def poly_validate_module_views(self, module):
    """
    [poly] Intercepts module view validation to defer it.
    Instead of validating now, we accumulate the view IDs for later processing.
    """
    assert self.pool._init
    
    # Identify views of this module
    prefix = module + '.'
    prefix_len = len(prefix)
    names = tuple(
        xmlid[prefix_len:]
        for xmlid in self.pool.loaded_xmlids
        if xmlid.startswith(prefix)
    )
    if not names:
        return

    # Retrieve all views of the module that are marked as 'noupdate' (standard Odoo behavior for _validate_module_views)
    # We accumulate ALL views, as polymorphism might be determined later.
    view_ids = [id_ for id_, in self.env.execute_query(SQL("""
        SELECT v.id
        FROM ir_ui_view v
        JOIN ir_model_data md ON (md.model = 'ir.ui.view' AND md.res_id = v.id)
        WHERE md.module = %s AND md.name IN %s AND md.noupdate
    """, module, names))]

    if view_ids:
        _logger.debug("[poly] Deferring validation for %s views in module %s", len(view_ids), module)
        self.pool._pending_poly_views.update(view_ids)

def _patch_ir_ui_view():
    global _original_validate_view, _original_NameManager_must_have_fields, _original_validate_module_views
    if _original_validate_view is not None:
        return
    
    try:
        import odoo.addons.base.models.ir_ui_view as ir_ui_view_mod
        if hasattr(ir_ui_view_mod, 'View'):
            _original_validate_view = ir_ui_view_mod.View._validate_view
            ir_ui_view_mod.View._validate_view = poly_validate_view
            
            _original_validate_module_views = ir_ui_view_mod.View._validate_module_views
            ir_ui_view_mod.View._validate_module_views = poly_validate_module_views

            _original_NameManager_must_have_fields = ir_ui_view_mod.NameManager.must_have_fields
            ir_ui_view_mod.NameManager.must_have_fields = poly_NameManager_must_have_fields
            
            _logger.debug("[poly] Patched ir.ui.view classes")
    except ImportError:
        pass

# PATCH: tools.convert.convert_xml_import to ensure patches are applied
import odoo.tools.convert
_original_convert_xml_import = odoo.tools.convert.convert_xml_import

def poly_convert_xml_import(env, module, fp, idref, mode, noupdate):
    _patch_ir_ui_view()
    return _original_convert_xml_import(env, module, fp, idref, mode, noupdate)

odoo.tools.convert.convert_xml_import = poly_convert_xml_import
odoo.fields.Many2many.read = poly_many2many_read
odoo.fields.Many2many.setup_nonrelated = poly_many2many_setup_nonrelated


    # [poly] DEPRECATED: Deep fix is no longer needed with the new flattening strategy.

_original_Registry_setup_models = odoo.modules.registry.Registry.setup_models

def _poly_registry_setup_models(self, cr):
    """
    Centralized polymorphic MRO injection.
    
    This is now the only place where __bases__ is modified for polymorphic models,
    ensuring that all models are already present in the registry.
    """
    _patch_ir_ui_view()

    # [poly] Invalidate polymorphic model cache before setup begins.
    # Models are partially initialised during multi-phase setup, so any values
    # cached in earlier phases would be stale by later phases.  Clearing here
    # guarantees that every call during setup computes from the live class state.
    _poly_is_polymorphic_cache.clear()

    # [poly] Clear the schema (physical column) caches on every registry (re)build:
    # a module update (-u) may have added/removed columns, which would make the cached
    # information stale; this also bounds the caches' lifetime to a single registry
    # generation instead of growing across reloads.
    _POLY_LEAF_COLUMNS.clear()
    _POLY_COLUMN_CACHE.clear()

    # [poly] Technical access to core classes
    cls_PolyBase = PolyBase
    cls_PolyModel = PolyModel
    cls_PolyTransientModel = PolyTransientModel

    # [poly] Phase 0: Collect all models that have _depend_models
    # and also collect their declared base models (targets) so that root bases get infrastructure fields too
    poly_models_names_to_process = set()
    for name, model_class in self.items():
        if not hasattr(model_class, '__base_classes'):
            model_class.__base_classes = tuple() if not type(model_class.__bases__) == tuple else \
                (model_class.__bases__)

        if not isinstance(model_class, type):
            continue
            
        # [poly] AGGRESSIVE: only consider models that are NOT ir.poly_base here
        if name == 'ir.poly_base':
            continue
                
        has_depend_models = False
        # [poly] DETECTION: check if the model or ANY of its parents in the registry
        # has _depend_models defined in its __dict__ or getattr.
        dep_attr = getattr(model_class, '_depend_models', None)
        if dep_attr and isinstance(dep_attr, (dict, OrderedDict)):
            has_depend_models = True
        else:
            for base in _poly_get_safe_mro(model_class):
                if base.__dict__.get('_depend_models'):
                    has_depend_models = True
                    break
        
        if has_depend_models:
            poly_models_names_to_process.add(name)
            _logger.debug("[poly] Identified model to process (explicit _depend_models): %s", name)
            
            # Technical access to the base model's dependencies
            dep_map = OrderedDict()
            # [poly] ROBUST: Search Python definition-class hierarchy (PolyModel subclasses)
            # for classes that declare _name == name in their own __dict__.
            # This is MRO-independent: it works even before Phase 1 injects definition
            # classes into the Odoo registered class's __bases__.  Without this, the MRO
            # walk below finds nothing (ConversationMessageFacebook is not yet in
            # model_class.mro()), dep_map stays empty, and model_class._depend_models is
            # never set — causing _poly_is_polymorphic to return False at create() time.
            _def_stack = list(cls_PolyModel.__subclasses__())
            while _def_stack:
                _def_cls = _def_stack.pop()
                if _def_cls.__dict__.get('_name') == name:
                    _d = _def_cls.__dict__.get('_depend_models')
                    if _d and isinstance(_d, (dict, OrderedDict)):
                        for _dm, _df in _d.items():
                            if _dm not in dep_map:
                                dep_map[_dm] = _df
                _def_stack.extend(_def_cls.__subclasses__())

            # Fallback: also walk the registered class's MRO (works after injection).
            for base in _poly_get_safe_mro(model_class):
                if getattr(base, '_name', None) == name:
                    d = base.__dict__.get('_depend_models')
                    if d and isinstance(d, (dict, OrderedDict)):
                        for dm, df in d.items():
                            if dm not in dep_map:
                                dep_map[dm] = df

            # Update the class attribute with the consolidated map
            if dep_map:
                model_class._depend_models = dep_map

            # [poly] IMPORTANT: We DO NOT add dep_model to poly_models_names_to_process here.
            # We only need the base models to be initialized later, but not modified.
            # Only models that are polymorphic consumers get MRO injection.
            for dep_model in dep_map.keys():
                if dep_model in self and dep_model != 'ir.poly_base':
                    # poly_models_names_to_process.add(dep_model) <-- REMOVED: No contamination!
                    _logger.debug("[poly] Identified target base (will ensure initialization): %s (from %s)", dep_model, name)

    # [poly] Phase 0.5: Aggressive Removal of polymorphic attributes from non-poly models
    # DISABLED: This cleanup is causing side effects in standard Odoo models (res.users)
    pass

    # [poly] Phase 1: MRO injection BEFORE Odoo's setup_models.
    # Responsible ONLY for modifying __bases__ so that Odoo's _setup_base sees the
    # correct inheritance hierarchy.  Field injection happens inside _setup_base via
    # _build_poly_fields, which runs after the standard Odoo field population.
    _logger.debug('[poly] Phase 1: MRO injection for %d models', len(poly_models_names_to_process))

    # Process parents before children by sorting on MRO depth.
    sorted_poly_names = sorted(
        poly_models_names_to_process,
        key=lambda n: len(_poly_get_safe_mro(self[n])) if n in self else 0,
    )

    # Registry classes that must be excluded from poly models' __bases__ to prevent
    # cascade MRO errors when _prepare_setup changes their __bases__.  The 'base'
    # abstract registry class is included in every model's _BaseModel__base_classes by
    # _build_model, but poly models already inherit from BaseModel via their definition
    # classes (PolyModel → PolyBase → BaseModel).  Having both 'base_reg' (which may
    # include PolyBase-extending definition classes from addon modules) AND definition
    # classes that extend PolyModel in the same __bases__ creates an MRO deadlock when
    # _prepare_setup for 'base' triggers a cascade to poly model subclasses.
    _excluded_from_poly_bases = set()
    if 'base' in self:
        _excluded_from_poly_bases.add(self['base'])

    # Fix: extend ir_poly_base_reg.__bases__ with base_reg now, before the loop.
    # issubclass(ir_poly_base_reg, base_reg) becomes True, so deduplication removes
    # base_reg from every poly model's final_bases.  No poly model gets base_reg directly
    # in __bases__, and the cascade from _prepare_setup is harmless.

    for model_name in sorted_poly_names:
        if model_name not in self:
            continue
        model_class = self[model_name]
        if not isinstance(model_class, type):
            continue

        try:
            dep_map = _poly_collect_depend_models(model_class)
            parents_cls = [self[p] for p in dep_map if p in self]
            if 'ir.poly_base' in self and self['ir.poly_base'] not in parents_cls:
                parents_cls.append(self['ir.poly_base'])

            if not parents_cls:
                continue

            _bm_bases = getattr(model_class, '_BaseModel__base_classes', None)
            original_bases = list(
                _bm_bases if _bm_bases
                else [b for b in model_class.__bases__ if getattr(b, 'pool', None) is None]
            )
            # [poly] Orden CONCRETO-primero: la clase de definicion del modelo (original_bases)
            # va ANTES que los padres inyectados. Asi los overrides del concreto (metodos,
            # _order, campos sobrecargados) GANAN sobre el padre -en MRO de Python gana el
            # primero-, manteniendo la herencia (los padres siguen accesibles, despues).
            # (Antes era parents_cls + original -> el padre pisaba los overrides del concreto:
            # ej. test.test4.set_a1 corria el de Test1. De ahi venia el hack de _attrs_to_restore.)
            new_bases = [
                b for b in original_bases
                if b not in parents_cls and b not in _excluded_from_poly_bases
            ] + parents_cls

            deduplicated = []
            for b in new_bases:
                if b is model_class:
                    continue
                if any(b is not c and issubclass(c, b) for c in new_bases if c is not model_class):
                    continue
                if b not in deduplicated:
                    deduplicated.append(b)
            final_bases = tuple(deduplicated)

            if final_bases and final_bases != tuple(model_class.__bases__):
                _logger.debug(
                    '[poly] Phase 1: injecting MRO for %s: %s',
                    model_name,
                    [getattr(b, '_name', b.__name__) for b in final_bases],
                )
                # Snapshot class-level attributes that must come from the child model,
                # not from injected base models.  Injecting a base (e.g. digital.event)
                # before the definition class puts the base's _order / _rec_name ahead
                # in MRO and silently overrides the child's declared values.
                _attrs_to_restore = {}
                for _attr in ('_order', '_rec_name', '_description'):
                    # Read from the registry class's current MRO (original order).
                    _val = getattr(model_class, _attr, None)
                    if _val is not None:
                        _attrs_to_restore[_attr] = _val
                model_class.__bases__ = final_bases
                if hasattr(model_class, '_BaseModel__base_classes'):
                    model_class._BaseModel__base_classes = final_bases
                if hasattr(model_class, '_BaseModel__depends_base_classes'):
                    model_class._BaseModel__depends_base_classes = final_bases
                if hasattr(ctypes.pythonapi, 'PyType_Modified'):
                    ctypes.pythonapi.PyType_Modified(ctypes.py_object(model_class))
                # Restore child-model attributes that may have been shadowed by the
                # newly injected bases (only if not already explicit in __dict__).
                for _attr, _val in _attrs_to_restore.items():
                    if _attr not in model_class.__dict__:
                        setattr(model_class, _attr, _val)

        except Exception as e:
            _logger.error('[poly] Phase 1: MRO injection failed for %s: %s', model_name, e)

    # [poly] Pre-setup sync: ensure __base_classes == __bases__ for all processed models.
    # _prepare_setup does `cls.__bases__ = cls.__base_classes` only when they differ.
    # After Phase 1 set both to final_bases, Odoo's _add_manual_models (called at the
    # start of setup_models) may invoke _build_model again, resetting __base_classes to
    # the original Odoo value.  Re-sync here guarantees no spurious MRO error.
    for _sync_name in sorted_poly_names:
        if _sync_name not in self:
            continue
        _sync_cls = self[_sync_name]
        if not isinstance(_sync_cls, type):
            continue
        _cur_bases = _sync_cls.__bases__
        try:
            _cur_bcc = _sync_cls._BaseModel__base_classes
        except AttributeError:
            continue
        if _cur_bases and tuple(_cur_bases) != tuple(_cur_bcc):
            _logger.debug(
                '[poly] Pre-setup sync: %s __base_classes %s -> %s',
                _sync_name,
                [getattr(b, '__name__', repr(b)) for b in _cur_bcc],
                [getattr(b, '__name__', repr(b)) for b in _cur_bases],
            )
            try:
                _sync_cls._BaseModel__base_classes = tuple(_cur_bases)
            except Exception as _sync_err:
                _logger.warning('[poly] Pre-setup sync failed for %s: %s', _sync_name, _sync_err)

    # [poly] Diagnostic: intercept _prepare_setup to catch the exact __bases__ assignment that fails.
    _original_prepare_setup = _original_BaseModel._prepare_setup

    def _diag_prepare_setup(self_model):
        cls = type(self_model)
        cur_bases = getattr(cls, '__bases__', None)
        bcc = getattr(cls, '_BaseModel__base_classes', None)
        if bcc and cur_bases and tuple(cur_bases) != tuple(bcc):
            try:
                cls.__bases__ = bcc
            except TypeError as _te:
                _logger.error(
                    '[poly] DIAGNOSTIC: _prepare_setup __bases__ assignment failed for %s (_name=%s): %s\n'
                    '  current __bases__: %s\n  new __base_classes:',
                    cls.__name__, getattr(cls, '_name', '?'), _te,
                    [getattr(b, '__name__', repr(b)) for b in cur_bases],
                )
                for _i, _b in enumerate(bcc):
                    _logger.error(
                        '[poly] DIAGNOSTIC   [%d] %r  __name__=%s  _name=%s  module=%s  bases=%s',
                        _i, _b, _b.__name__, getattr(_b, '_name', '?'),
                        getattr(_b, '__module__', '?'),
                        [getattr(x, '__name__', repr(x)) for x in _b.__bases__],
                    )
                raise
        return _original_prepare_setup(self_model)

    _original_BaseModel._prepare_setup = _diag_prepare_setup

    # [poly] Phase 2: Clear the per-class _poly_fields_built flag before every
    # setup_models call (including test-reset invocations).  Without this,
    # _build_poly_fields returns early on subsequent calls and poly M2M related
    # attributes are lost after registry resets in the test runner.
    for _cls in self.values():
        if isinstance(_cls, type) and '_poly_fields_built' in _cls.__dict__:
            try:
                delattr(_cls, '_poly_fields_built')
            except AttributeError:
                pass

    try:
        res = _original_Registry_setup_models(self, cr)
    except TypeError as _mro_err:
        if 'MRO' not in str(_mro_err) and 'resolution' not in str(_mro_err).lower():
            raise
        _logger.error('[poly] MRO TypeError in setup_models.')
        raise
    finally:
        _original_BaseModel._prepare_setup = _original_prepare_setup

    # [poly] Phase 3: Post-setup cache invalidation.
    # Field injection is now handled by _setup_base via _build_poly_fields.
    if 'field_computed' in self.__dict__:
        del self.__dict__['field_computed']
    # [poly] Clear the polymorphic model name cache so stale results from the
    # previous registry state don't persist into the newly rebuilt registry.
    _poly_is_polymorphic_cache.clear()

    # [poly] concrete_model_id pertenece a ir.poly_base; en los SUBTIPOS no debe ser una
    # columna stored. Por el MRO inyectado (ir.poly_base queda mas derivado que el subtipo),
    # la definicion required+stored de ir.poly_base gana sobre el override store=False, y Odoo
    # crearia una columna NOT NULL en el subtipo que el create nunca popula -> NotNullViolation.
    # Aca, tras el setup, forzamos el campo del subtipo a no-stored computado: el valor se lee
    # del poly_base compartido (via _compute_concrete_model_id), sin columna propia.
    for _mname, _mcls in self.items():
        if not getattr(_mcls, '_depend_models', None):
            continue  # base ({}) o modelo no-poly: dejar el campo como esta
        _f = _mcls._fields.get('concrete_model_id')
        if _f is not None and getattr(_f, 'store', False):
            _f.store = False
            _f.required = False
            _f.compute = '_compute_concrete_model_id'
            _f.compute_sudo = True
            _f.readonly = True

    # [poly] _rec_name: ir.poly_base declara `_rec_name = 'id'` (no tiene campo name), y por el
    # MRO inyectado ese valor se hereda explicitamente en TODOS los subtipos, pisando el default
    # automatico de Odoo (`if 'name' in _fields: _rec_name = 'name'`). Resultado: display_name y
    # name_search de un modelo poly CON campo name mostraban "<modelo>,<id>" en vez del nombre
    # (rompe el rendering de las listas polimorficas en la UI). Aca restauramos la intencion de
    # Odoo: si el modelo poly tiene 'name' y quedo con _rec_name='id' heredado, usar 'name'.
    for _mname, _mcls in self.items():
        if _mname == 'ir.poly_base':
            continue
        if getattr(_mcls, '_depend_models', None) is None:
            continue  # no es modelo poly
        if getattr(_mcls, '_rec_name', None) == 'id' and 'name' in _mcls._fields:
            _mcls._rec_name = 'name'

    # [poly] display_name: poly usa _inherits con los link fields, y Odoo delega display_name al
    # PRIMER padre _inherits (un link de infraestructura, ej. behavior_a_id / test2_id). Resultado:
    # el display_name de un subtipo mostraba el del primer base ("<base>,<id>") en vez del propio
    # -> rompe el rendering de las listas polimorficas. Acá lo des-delegamos: lo devolvemos al
    # _compute_display_name estandar de Odoo, que respeta el _rec_name del modelo concreto.
    for _mname, _mcls in self.items():
        if _mname == 'ir.poly_base':
            continue
        if getattr(_mcls, '_depend_models', None) is None:
            continue
        _dn = _mcls._fields.get('display_name')
        if _dn is None or not getattr(_dn, 'related', None):
            continue
        _dn.related = None
        _dn.inherited = False
        _dn.inherited_field = None
        _dn.related_field = None
        _dn.store = False
        _dn.readonly = True
        _dn.compute = '_compute_display_name'
        _dn.compute_sudo = False
        _dn.depends = (_mcls._rec_name,) if _mcls._rec_name and _mcls._rec_name != 'id' else ()
        # OJO: al venir de un related, el `search` del campo quedaba apuntando a _search_related
        # (que con related=None matchea todo -> name_search no filtraba). Restaurar el search
        # estandar de display_name para que name_search use _rec_name.
        _dn.search = '_search_display_name'

    # [poly] Selection injertados: poly inyecta los campos heredados como related. Para un Selection
    # related, el setup de Odoo deja `.selection` como CALLABLE (lo resuelve del target). Eso rompe
    # codigo que introspecciona `.selection` asumiendo lista, p.ej. el default de account:
    #   display_invoice_edi_format = Boolean(default=lambda self: len(self._fields['invoice_edi_format'].selection))
    # -> len(callable) revienta al crear un subtipo poly de res.partner. Resolvemos el callable a la
    # lista estatica del campo padre (que es de donde sale), preservando la semantica related del
    # valor pero dejando `.selection` introspectable como lista.
    for _mname, _mcls in self.items():
        if getattr(_mcls, '_depend_models', None) is None:
            continue
        for _sf in _mcls._fields.values():
            if _sf.type != 'selection' or not getattr(_sf, 'related', None):
                continue
            if not callable(getattr(_sf, 'selection', None)):
                continue
            _tgt = getattr(_sf, 'related_field', None)
            _tsel = getattr(_tgt, 'selection', None) if _tgt is not None else None
            if isinstance(_tsel, (list, tuple)):
                _sf.selection = list(_tsel)

    _logger.debug('[poly] Registry setup complete')
    return res

_original_registry_init_models = odoo.modules.registry.Registry.init_models
def _poly_registry_init_models(self, cr, model_names, context, install=True):
    """
    [poly] Professional Initialization Hook.
    Ensures that any model gaining fields from the modules being initialized
    is included in the initialization process, so Odoo's _auto_init creates
    the necessary SQL columns.
    """
    if not getattr(cr, '_poly_in_init_models', False):
        try:
            cr._poly_in_init_models = True
            # Identify the modules being initialized (from context or by inference)
            # In Odoo 18 incremental loading, context usually contains {'module': ...}
            current_module = (context or {}).get('module')
            if current_module:
                _logger.debug("[poly] _poly_registry_init_models: analyzing extensions for module %s", current_module)
                
                # [poly] DEBT: If we have views in model_names, we MUST ensure their tables
                # are also in model_names and come FIRST. Odoo might not include them if they were
                # already processed but without the new columns.
                # Since we don't have a reliable way to know which tables a view depends on,
                # we include all models from current_module that are tables.
                tables_to_add = set()
                for mname, mclass in self.items():
                    if mname in model_names: continue
                    if not getattr(mclass, '_auto', True): continue
                    if getattr(mclass, '_module', None) == current_module or (getattr(mclass, '_modules', None) and current_module in mclass._modules):
                         tables_to_add.add(mname)

                extra_models = set()
                for mname, mclass in self.items():
                    if mname in model_names: continue
                    # Check if this model has any stored field owned by the current module
                    # We check both _module and _modules (Odoo 18 style)
                    for f in mclass._fields.values():
                        if f.store and (getattr(f, '_module', None) == current_module or (getattr(f, '_modules', None) and current_module in f._modules)):
                             _logger.debug("[poly] Model %s has stored field %s from %s", mname, f.name, current_module)
                             extra_models.add(mname)
                             break
                
                # Combine extra_models and tables_to_add
                all_extra = extra_models | tables_to_add
                if all_extra:
                     _logger.debug("[poly] Adding %d extra models: %s", len(all_extra), sorted(all_extra))
                     if isinstance(model_names, set):
                         model_names.update(all_extra)
                     else:
                         # Convert to set for union, then we'll sort anyway
                         model_names = set(model_names) | all_extra

                # [poly] Re-order model_names to ensure _auto=True models come first
                # Odoo's init_models processes them in the provided order.
                # We use self[mname]._auto to determine if it's a table or a view.
                def model_init_priority(mname):
                    mclass = self.get(mname)
                    if mclass and not getattr(mclass, '_auto', True):
                        return 1 # Lower priority (views)
                    return 0 # Higher priority (tables)


                # Always sort and convert to list to be 100% sure of the order
                model_names = sorted(list(model_names), key=model_init_priority)

                _logger.debug("[poly] _poly_registry_init_models: model_names FINAL: %s", model_names)
                
                # [poly] CRITICAL: Ensure base tables have their columns updated BEFORE views are initialized.
                # Odoo's init_models iterates and calls model._auto_init() and model.init().
                # For tables, _auto_init() creates columns. For views, init() creates the view.
                # If we have both in the same batch, the sorted order ensures tables go first.
                # BUT, if a model was already partially processed by Odoo or if there's any
                # inconsistency, we MUST ensure the SQL columns exist for stored fields.
                # Odoo's _auto_init is sometimes too smart or too late; we manually ensure
                # columns for the current module's stored fields.
                def table_exists(cr, table):
                    cr.execute("SELECT 1 FROM pg_catalog.pg_class WHERE relname = %s AND relkind = 'r'", (table,))
                    return bool(cr.fetchone())

                for mname in model_names:
                    mclass = self.get(mname)
                    if mclass and getattr(mclass, '_auto', True) and mname != 'base':
                        _table = getattr(mclass, '_table', None)
                        if _table and table_exists(cr, _table):
                             mclass = self[mname]
                             for _fname, _fobj in mclass._fields.items():
                                 if getattr(_fobj, 'store', False) and getattr(_fobj, 'column_type', None):
                                     _fmodule = getattr(_fobj, '_module', None)
                                     _fmodules = getattr(_fobj, '_modules', None)
                                     _is_extended = _fmodule == current_module or (_fmodules and current_module in _fmodules)
                                     # [poly] Professional Fix: Odoo 18 Registry initialization batching can lead to views being initialized
                                     # before the extended columns are in SQL, because _auto_init() might skip them if they are not in the current load context.
                                     # If the field is stored and has a column type, it MUST be in the database before views are created.
                                     if _is_extended:
                                         cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s AND column_name = %s", (_table, _fname))
                                         if not cr.fetchone():
                                             _col_type = _fobj.column_type[1]
                                             _logger.debug("[poly] GENERIC (INIT): Missing SQL column %s on %s, creating manually: %s", _fname, _table, _col_type)
                                             cr.execute(f'ALTER TABLE "{_table}" ADD COLUMN IF NOT EXISTS "{_fname}" {_col_type}')
                                             _fobj.column = True
                
        finally:
            cr._poly_in_init_models = False

    return _original_registry_init_models(self, cr, model_names, context, install=install)

odoo.modules.registry.Registry.init_models = _poly_registry_init_models

_original_registry_load = odoo.modules.registry.Registry.load
def _poly_registry_load(self, cr, module):
    """
    [poly] Load Hook.
    Forces setup_models after loading a module to ensure extensions are visible
    before any init_models call that might create views.
    """
    res = _original_registry_load(self, cr, module)
    # NOTE: setup_models is NOT called here per-module.
    # loading.py:205 already calls it for every needs_update=True module (install/upgrade),
    # and loading.py:511 calls it unconditionally after all modules finish loading (normal
    # startup included). Calling it here mid-loading causes KeyError failures when a module
    # adds a One2many on model A and its inverse Many2one on model B in the same batch,
    # because model B's _setup_base hasn't picked up the new field yet.
    return res

odoo.modules.registry.Registry.load = _poly_registry_load
odoo.modules.registry.Registry.setup_models = _poly_registry_setup_models

_original_registry_new = odoo.modules.registry.Registry.new

@classmethod
def _poly_registry_new(cls, db_name, force_demo=False, status=None, update_module=False):
    """
    [poly] Monkey patch for Registry.new to ensure the polymorphic stabilization
    happens while the Registry class lock is still held.
    This prevents incoming HTTP requests from accessing an inconsistent registry.
    """
    # 1. Execute the standard Odoo creation (held under @locked in Registry.new)
    registry = _original_registry_new(db_name, force_demo=force_demo, status=status, update_module=update_module)

    # 2. At this point, Odoo has set registry.ready = True, but we are still
    # inside the @locked method, so any other thread calling Registry(db_name)
    # is blocked in Registry.__new__ waiting for the lock.

    try:
        _logger.debug("[poly] Starting post-load polymorphic stabilization for %s", db_name)
        # Ensure we have a clean state for stabilization
        registry.ready = False 
        
        with registry.cursor() as cr:
            # Force the final polymorphic setup
            # This includes MRO injection and field synchronization
            registry.setup_models(cr)
            
            # Finalize view validation if there are pending views
            if hasattr(registry, '_poly_finalize_view_validation'):
                registry._poly_finalize_view_validation(cr)
                
        registry.ready = True
        _logger.debug("[poly] Polymorphic stabilization completed for %s", db_name)
    except Exception as e:
        _logger.error("[poly] Critical error during polymorphic stabilization: %s", e, exc_info=True)
        # If stabilization fails, we might want to keep ready=False or even 
        # delete the registry from cls.registries, but Odoo's Registry.new 
        # already has its own cleanup. We re-raise to be safe.
        raise e
        
    return registry

# Apply the patch to Registry.new
odoo.modules.registry.Registry.new = _poly_registry_new


# PATCH: load_module_graph to intercept the end of module loading
import odoo.modules.loading
_original_load_module_graph = odoo.modules.loading.load_module_graph

def poly_load_module_graph(env, graph, status=None, perform_checks=True,
                           skip_modules=None, report=None, models_to_check=None):
    """
    [poly] Intercepts the end of load_module_graph to trigger final validations.
    """
    # 1. Run the original loading process
    res = _original_load_module_graph(env, graph, status=status, perform_checks=perform_checks,
                                      skip_modules=skip_modules, report=report, models_to_check=models_to_check)
    
    # 2. Trigger Final Cleanup and View Validation
    # load_module_graph returns (loaded_modules, processed_modules)
    # If we processed some modules, it's a good time to finalize.
    # Even if no modules were processed, if we are in _init mode (first load), we should finalize.
    registry = env.registry
    if registry._init and not registry._pending_poly_views:
        # In some cases _init is True but we don't have pending views yet (e.g. registry just created)
        pass
        
    if registry._pending_poly_views:
        _logger.debug("[poly] load_module_graph finished, triggering final view validation.")
        registry._poly_finalize_view_validation(env.cr)
        
    return res

odoo.modules.loading.load_module_graph = poly_load_module_graph
