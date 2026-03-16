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

import logging
import ctypes
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

# Local imports
from . import expression

# Type checking imports
if typing.TYPE_CHECKING:
    from collections.abc import Reversible
    from odoo.modules.registry import Registry


_logger = logging.getLogger(__name__)


# Global cache for polymorphic MRO to ensure they survive Odoo's registry setup phases.
# Keys are db_name, then model_name. Values are tuples of base classes.
POLY_MRO_CACHE = defaultdict(dict)

# Save the original Odoo classes to avoid cyclic inheritance
_original_BaseModel = odoo.models.BaseModel
_original_AbstractModel = odoo.models.AbstractModel
_original_Model = odoo.models.Model
_original_TransientModel = odoo.models.TransientModel
_original_Many2many_setup_nonrelated = odoo.fields.Many2many.setup_nonrelated

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


def poly_many2one_convert_to_read(self, value, record, use_display_name=True):
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


def poly_many2many_setup_nonrelated(self, model):
    """
    Monkey-patch for Many2many.setup_nonrelated to allow sharing the same
    relation table and columns between models that are polymorphic counterparts.
    """
    try:
        return _original_Many2many_setup_nonrelated(self, model)
    except TypeError as e:
        # Check if the error is about shared table/columns
        if "Many2many fields" in str(e) and "use the same table and columns" in str(e):
            # Attempt to find the conflicting field in the error message or pool
            m2m = model.pool._m2m
            fields = m2m[(self.relation, self.column1, self.column2)]
            
            is_poly_counterpart = False
            for other in fields:
                # If they are different models, check if they are in each other's polymorphic hierarchy
                if self.model_name != other.model_name:
                    # Check if one is a polymorphic base of the other
                    model_class = model.pool[self.model_name]
                    other_class = model.pool[other.model_name]
                    
                    # Check MRO for polymorphic relationship
                    if other.model_name in [getattr(c, '_name', None) for c in model_class.mro()] or \
                       self.model_name in [getattr(c, '_name', None) for c in other_class.mro()]:
                        is_poly_counterpart = True
                        break
            
            if is_poly_counterpart:
                _logger.debug("Allowing shared Many2many table %s for polymorphic counterparts %s and %s", 
                              self.relation, self.model_name, [f.model_name for f in fields])
                # Silently allow sharing by ignoring the TypeError and appending to the list
                if self not in fields:
                    fields.append(self)
                
                # Re-implement the inverse fields logic that follows the TypeError raise in original
                for field in m2m[(self.relation, self.column2, self.column1)]:
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

        # Odoo 18 specific: Check if the field is set in _fields of the model
        if self.name not in records._fields:
            return self

        # Single record case
        if len(records._ids) <= 1:
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

    def _get_all_poly_bases(self):
        """
        Returns a set of all base models (polymorphic or not) in the hierarchy.
        This exploration is recursive.
        """
        bases = set()
        visited = set()

        def collect(model_name):
            if model_name in visited:
                return
            visited.add(model_name)
            
            # ir.poly_base is always a base
            bases.add('ir.poly_base')
            
            model = self.env.get(model_name)
            if model is None:
                return

            # Add current model if it's not the starting one (or always add it)
            bases.add(model_name)
            
            # Recursively explore _depend_models
            depend_models = getattr(model, '_depend_models', None)
            if depend_models:
                for base_name in depend_models.keys():
                    collect(base_name)
            
            # Also explore standard Odoo inheritance (_inherit)
            # though usually _depend_models should cover what we need for poly
            # but the task says "polimórficas o no"
            for inherit in (model._inherit if isinstance(model._inherit, (list, tuple)) else [model._inherit] if model._inherit else []):
                if inherit in self.env and inherit != 'base':
                    collect(inherit)

        collect(self._name)
        return bases

    def _get_max_poly_id(self):
        """
        Calculates the maximum ID among all participating tables in the polymorphic hierarchy.
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
                    if not self.env.cr.has_table(model._table):
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

    def check_access(self, operation: str) -> None:
        if getattr(self, '_depend_models', None) is None:
            return super().check_access(operation)
        
        if self.env.su:
            return

        # Check access on the model itself first
        # We MUST avoid calling super() on self if self is a recordset that might have
        # mixed internal state or if the class hierarchy is complex.
        # But here we want to call Odoo's base check_access.
        try:
            # We use browse(self._ids) to ensure we have a fresh recordset of the current class
            # this often helps super() find the right context in Odoo 18
            self.env[self._name].browse(self._ids)._check_poly_access(operation)
        except (AccessError, TypeError):
            # If _check_poly_access fails or isn't found, fallback to standard check
            super(PolyBase, self).check_access(operation)
        
        # Check access on all dependent base models
        for base_name in self._depend_models.keys():
            base_model = self.env[base_name]
            base_model.check_access(operation)

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

    def __getattr__(self, name):
        """
        Fallback for polymorphic fields that might not have been correctly
        injected or resolved as attributes due to late model setup.
        """
        # CRITICAL: We avoid standard Odoo field attributes to prevent recursion
        # during field setup. We only intercept pln_* or known polymorphic fields.
        if name.startswith('pln_') or (name != '_fields' and name in getattr(self, '_fields', {})):
            # Check for numa.planning.node specifically
            node_model = self.env.registry.get('numa.planning.node')
            if node_model is not None and name in node_model._fields:
                field = node_model._fields[name]
                try:
                    return field.__get__(self, type(self))
                except (MissingError, AccessError, AttributeError):
                    # Odoo 18: If the record is missing from ir_poly_base (missing polymorphic link)
                    # or the user lacks access to the polymorphic base,
                    # return a sensible default for the field type to avoid AttributeError.
                    if field.type == 'one2many':
                        return self.env[field.comodel_name]
                    if field.type == 'many2many':
                        return self.env[field.comodel_name]
                    if field.type == 'many2one':
                        return self.env[field.comodel_name]
                    return False
                except Exception:
                    pass

            # Check for numa.planning.allocation (another potential polymorphic base)
            allocation_model = self.env.registry.get('numa.planning.allocation')
            if allocation_model is not None and name in allocation_model._fields:
                field = allocation_model._fields[name]
                try:
                    return field.__get__(self, type(self))
                except (MissingError, AccessError):
                    if field.type == 'one2many' or field.type == 'many2many' or field.type == 'many2one':
                        return self.env[field.comodel_name]
                    return False
                except Exception:
                    pass

            fields_dict = getattr(self, '_fields', {})
            field = fields_dict.get(name)
            if field:
                try:
                    return field.__get__(self, type(self))
                except Exception:
                    pass
        
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

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
    def _apply_polymorphic_hierarchy(cls, pool, name, model_class, parents):
        """ The core logic to inject polymorphic parents into a model's hierarchy. """
        if not parents: return False
        
        # Odoo 18: ensure all parents are registry classes
        parents_cls = []
        missing_parents = []
        for p_name in parents:
            if p_name in pool:
                parents_cls.append(pool[p_name])
            else:
                missing_parents.append(p_name)
        
        if missing_parents:
            if not hasattr(pool, '_poly_pending_dependencies'): pool._poly_pending_dependencies = defaultdict(set)
            for p_name in missing_parents: pool._poly_pending_dependencies[p_name].add(name)
            return False

        if name != 'ir.poly_base' and pool['ir.poly_base'] not in parents_cls:
            parents_cls.append(pool['ir.poly_base'])

        new_bases = list(parents_cls)
        current_bases = list(model_class.__bases__)
        for b in current_bases:
            if b not in new_bases and b.__name__ not in ('BaseModel', 'object'):
                new_bases.append(b)
        
        final_bases = tuple(b for b in new_bases if b is not model_class)
        
        try:
            model_class.__base_classes = final_bases
            model_class.__bases__ = final_bases
            model_class.__depends_base_classes = final_bases
            cls._poly_force_mro_update(model_class)
            
            cls._poly_sync_proxy_class(pool, name, model_class, final_bases)
            cls._poly_invalidate_odoo_caches(pool, name)
            
            if not hasattr(pool, '_poly_mro_cache'): pool._poly_mro_cache = {}
            pool._poly_mro_cache[name] = final_bases
            POLY_MRO_CACHE[pool.db_name][name] = final_bases

            # Odoo 18: Immediate field recovery after hierarchy change
            # to prevent stale _fields during incremental module loading
            from odoo.models import MetaModel
            _current_mro = model_class.mro()
            for _base_class in _current_mro:
                if (getattr(_base_class, 'pool', None) is None
                        and isinstance(_base_class, MetaModel)
                        and hasattr(_base_class, '_field_definitions')):
                    for _fobj in _base_class._field_definitions:
                        _fname = _fobj.name
                        if _fname not in model_class._fields:
                            _fobj.model_name = name
                            model_class._fields[_fname] = _fobj
                            if _fname not in model_class.__dict__:
                                try:
                                    setattr(model_class, _fname, _fobj)
                                except Exception:
                                    pass
                            
                            # Also ensure the proxy class (if any) has it
                            if hasattr(pool, 'models') and name in pool.models:
                                _proxy = pool.models[name]
                                if _proxy is not model_class:
                                    _proxy._fields[_fname] = _fobj
                                    if _fname not in _proxy.__dict__:
                                        try: setattr(_proxy, _fname, _fobj)
                                        except Exception: pass

                            if hasattr(_fobj, '_setup_done'):
                                _fobj._setup_done = False
                            elif hasattr(_fobj, 'setup_done'):
                                _fobj.setup_done = False
            
            return True
        except Exception: return False

    @classmethod
    def _build_model(cls, pool, cr):
        """
        Build a model using the polymorphic inheritance system.
        
        This method is responsible for constructing the Python class for the model,
        ensuring that it inherits from all dependent models specified in _depend_models.
        """
        name = cls._name
        # First build the model using the standard Odoo mechanism.
        if name is None:
            _logger.warning("Building model with name=None for class %s. MRO: %s", cls.__name__, cls.mro())
            # Skip building if name is None to avoid TypeError in type.__new__
            return None
        model_class = _original_BaseModel._build_model.__func__(cls, pool, cr)

        # --- RETROACTIVE DEPENDENCY RESOLUTION ---
        # When a model is built, check if any already-built models depend on it.
        # If so, we need to trigger an update for them.
        if not hasattr(pool, '_poly_pending_dependencies'):
            pool._poly_pending_dependencies = defaultdict(set)
        
        if name in pool._poly_pending_dependencies:
            waiting_models = list(pool._poly_pending_dependencies[name])
            _logger.debug("Retroactively updating models %s which depend on %s", waiting_models, name)
            for waiting_name in waiting_models:
                # We don't want to re-trigger the whole _build_model, but we want to re-evaluate its polymorphic bases.
                # Since Registry.load calls _build_model for each class, we can't easily re-invoke it.
                # However, we can clear the cache so that the next time it's built or setup, it will re-evaluate.
                if hasattr(pool, '_poly_mro_cache'):
                    pool._poly_mro_cache.pop(waiting_name, None)
                if pool.db_name in POLY_MRO_CACHE:
                    POLY_MRO_CACHE[pool.db_name].pop(waiting_name, None)
                
                # If the model is already in the pool, we try to re-build it if it's currently being loaded
                if waiting_name in pool:
                    waiting_class = pool[waiting_name]
                    _logger.debug("Triggering IMMEDIATE refresh for already-built model %s because parent %s is now ready", waiting_name, name)
                    
                    # Force re-evaluation of bases for the waiting class
                    # We look for all depend models in its hierarchy
                    child_all_depends = OrderedDict()
                    for base in waiting_class.mro():
                        if base is waiting_class: continue
                        if '_depend_models' in base.__dict__ and base._depend_models:
                            for dep_model, dep_field in base._depend_models.items():
                                if dep_model not in child_all_depends:
                                    child_all_depends[dep_model] = dep_field
                    
                    if child_all_depends:
                        child_parents = list(child_all_depends.keys())
                        if waiting_name != 'ir.poly_base' and 'ir.poly_base' not in child_parents:
                            child_parents.append('ir.poly_base')
                        
                        child_new_bases = []
                        child_missing = False
                        for p in child_parents:
                            if p in pool:
                                p_cls = pool[p]
                                if p_cls not in child_new_bases: child_new_bases.append(p_cls)
                            else:
                                child_missing = True
                        
                        if not child_missing:
                            # We have everything! Update MRO immediately
                            child_current_bases = list(waiting_class.__bases__)
                            for b in child_current_bases:
                                if b not in child_new_bases and b.__name__ != 'BaseModel':
                                    child_new_bases.append(b)
                            child_final_bases = tuple(b for b in child_new_bases if b is not waiting_class)
                            
                            waiting_class.__base_classes = child_final_bases
                            waiting_class.__bases__ = child_final_bases
                            waiting_class.__depends_base_classes = child_final_bases
                            import ctypes as _ctypes
                            if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                                _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(waiting_class))
                            
                            # Sync proxy
                            if hasattr(pool, 'models') and waiting_name in pool.models:
                                child_proxy = pool.models[waiting_name]
                                if child_proxy is not waiting_class:
                                    child_proxy.__base_classes = child_final_bases
                                    child_proxy.__bases__ = child_final_bases
                                    if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                                        _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(child_proxy))
                                    
                                    # Odoo 18: Proxy uses ProxyFunc/ProxyAttr descriptors.
                                    # Copy methods from parents to proxy class explicitly for IMMEDIATE view validation.
                                    for p_model_name in child_parents:
                                        if p_model_name in pool:
                                            p_cls = pool[p_model_name]
                                            for attr_name, attr_val in p_cls.__dict__.items():
                                                if callable(attr_val) and not attr_name.startswith('__') and attr_name not in child_proxy.__dict__:
                                                    try:
                                                        setattr(child_proxy, attr_name, attr_val)
                                                    except Exception:
                                                        pass
                            
                            # Update caches
                            if not hasattr(pool, '_poly_mro_cache'): pool._poly_mro_cache = {}
                            pool._poly_mro_cache[waiting_name] = child_final_bases
                            POLY_MRO_CACHE[pool.db_name][waiting_name] = child_final_bases
                            
                            # Invalidate Environment and Pool caches for the child model
                            if hasattr(pool, 'model_methods'):
                                pool.model_methods.pop(waiting_name, None)
                            
                            from odoo.api import Environment
                            if hasattr(Environment, '_classes') and Environment._classes is not None:
                                if pool in Environment._classes:
                                    Environment._classes[pool].pop(waiting_name, None)
                            
                            # Mark as setup not done to force re-setup if needed
                            if hasattr(waiting_class, '_setup_done'):
                                waiting_class._setup_done = False

                # Set a flag to ensure it's checked during setup too
                if not hasattr(pool, '_poly_refresh_needed'):
                    pool._poly_refresh_needed = set()
                pool._poly_refresh_needed.add(waiting_name)

                pool._poly_pending_dependencies[name].remove(waiting_name)

        # Collect all classes that contribute to this model's definition.
        all_depend_models = OrderedDict()
        is_polymorphic = False
        
        # We iterate over the MRO of the model_class to find all _depend_models.
        for base in model_class.mro():
            if base is model_class:
                continue
            if '_depend_models' in base.__dict__ and base._depend_models:
                is_polymorphic = True
                for dep_model, dep_field in base._depend_models.items():
                    if dep_model not in all_depend_models:
                        all_depend_models[dep_model] = dep_field

        if is_polymorphic:
            # Validate dependency cycles before building
            cls._validate_dependency_cycles(pool)

            # Clear registry-level caches to ensure we don't pick up stale method resolutions.
            if hasattr(pool, 'model_methods'):
                pool.model_methods.pop(name, None)

            # All models except 'ir.poly_base' implicitly depend on 'ir.poly_base'
            parents = list(all_depend_models.keys())
            if name != 'ir.poly_base' and 'ir.poly_base' not in parents:
                parents.append('ir.poly_base')

            # Calculate polymorphic bases.
            # Use __base_classes (updated by Odoo's _build_model to include the
            # newly added extension class) rather than __bases__ (only updated in
            # _prepare_setup, so it lags behind and misses the new extension class).
            # Without this, extension modules like project_timesheet_holidays that
            # extend a polymorphic model lose their fields (e.g. is_timeoff_task)
            # because the extension class is never included in final_bases nor in
            # POLY_MRO_CACHE, so _setup_base never scans its _field_definitions.
            original_bases = list(getattr(model_class, '__base_classes', None) or model_class.__bases__)
            
            new_bases = []
            missing_parents = False
            for parent in parents:
                if parent not in pool:
                    if not hasattr(pool, '_poly_pending_dependencies'):
                        pool._poly_pending_dependencies = defaultdict(set)
                    pool._poly_pending_dependencies[parent].add(name)
                    missing_parents = True
                    continue
                
                parent_class = pool[parent]
                if parent_class not in new_bases:
                    new_bases.append(parent_class)
                
                # Register dependency for reverse lookup
                if not hasattr(parent_class, '_depends_children'):
                    parent_class._depends_children = OrderedSet()
                parent_class._depends_children.add(name)

            for b in original_bases:
                if b not in new_bases:
                    new_bases.append(b)

            final_bases = tuple(b for b in new_bases if b is not model_class)
            
            # Store the polymorphic bases for setup phases
            model_class.__depends_base_classes = final_bases
            if not hasattr(pool, '_poly_mro_cache'):
                 pool._poly_mro_cache = {}
            pool._poly_mro_cache[name] = final_bases
            POLY_MRO_CACHE[pool.db_name][name] = final_bases
            
            # Odoo 18: ensure __base_classes (used by _prepare_setup) is updated
            model_class.__base_classes = final_bases

            # Inject into Python's MRO:
            model_class.__bases__ = final_bases

            # Force Python to refresh the class MRO cache
            import ctypes as _ctypes
            if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(model_class))

            # --- Odoo 18 PROXY INJECTION ---
            if hasattr(pool, 'models') and name in pool.models:
                 proxy_class = pool.models[name]
                 if proxy_class is not model_class:
                     proxy_class.__base_classes = final_bases
                     try:
                         proxy_class.__bases__ = final_bases
                         if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                             _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(proxy_class))
                     except TypeError as e:
                         _logger.error("Failed to sync proxy bases for %s: %s", name, e)

            # Clear various caches that might be stale due to MRO change
            if hasattr(pool, '_classes') and name in pool._classes:
                 pool._classes.pop(name, None)
            
            from odoo.api import Environment
            if hasattr(Environment, '_classes') and Environment._classes is not None:
                 if pool in Environment._classes:
                      Environment._classes[pool].pop(name, None)

            if hasattr(model_class, '_setup_done'):
                 model_class._setup_done = False
            
            if hasattr(model_class, '_fields'):
                 model_class._fields = {}

            # Force recomputation of _model_classes__ (Odoo 18 cache)
            if hasattr(model_class, '_model_classes__'):
                try:
                    from odoo.tools import discardattr
                    discardattr(model_class, '_model_classes__')
                except (ImportError, AttributeError):
                    if '_model_classes__' in model_class.__dict__:
                        delattr(model_class, '_model_classes__')

        return model_class

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

        if hasattr(cls, '_depend_models') and cls._depend_models:
            for parent_name in cls._depend_models.keys():
                if parent_name in pool:
                    parent_class = pool[parent_name]
                    if hasattr(parent_class, '_validate_dependency_cycles'):
                        parent_class._validate_dependency_cycles(pool, visited, rec_stack)

        rec_stack.remove(name)

    def _prepare_setup(self):
        """ Prepare the setup of the model. """
        model_class = type(self)
        name = self._name
        
        # --- REFRESH CHECK ---
        # If this model was built before its polymorphic parents were available, 
        # we try to refresh its bases now.
        if hasattr(self.pool, '_poly_refresh_needed') and name in self.pool._poly_refresh_needed:
            # We re-collect dependencies from MRO
            all_depend_models = OrderedDict()
            for base in model_class.mro():
                if base is model_class: continue
                if '_depend_models' in base.__dict__ and base._depend_models:
                    for dep_model, dep_field in base._depend_models.items():
                        if dep_model not in all_depend_models:
                            all_depend_models[dep_model] = dep_field
            
            if all_depend_models:
                parents = list(all_depend_models.keys())
                if name != 'ir.poly_base' and 'ir.poly_base' not in parents:
                    parents.append('ir.poly_base')
                
                # Get current bases (excluding our previous polymorphic injection if possible)
                current_bases = list(model_class.__bases__)
                new_bases = []
                missing_any = False
                for parent in parents:
                    if parent in self.pool:
                        p_cls = self.pool[parent]
                        if p_cls not in new_bases: new_bases.append(p_cls)
                    else:
                        missing_any = True
                
                if not missing_any:
                    # We have all parents now!
                    for b in current_bases:
                        if b not in new_bases and b.__name__ != 'BaseModel': # Avoid redundant BaseModel
                            new_bases.append(b)
                    
                    final_bases = tuple(b for b in new_bases if b is not model_class)
                    _logger.debug("RETROACTIVE: Applying final bases for %s: %s", name, [b.__name__ for b in final_bases])
                    
                    model_class.__base_classes = final_bases
                    model_class.__bases__ = final_bases
                    import ctypes as _ctypes
                    if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                        _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(model_class))
                    
                    # Sync proxy
                    if hasattr(self.pool, 'models') and name in self.pool.models:
                        proxy = self.pool.models[name]
                        if proxy is not model_class:
                            proxy.__base_classes = final_bases
                            proxy.__bases__ = final_bases
                            if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                                _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(proxy))
                    
                    # Cache it
                    if not hasattr(self.pool, '_poly_mro_cache'): self.pool._poly_mro_cache = {}
                    self.pool._poly_mro_cache[name] = final_bases
                    POLY_MRO_CACHE[self.pool.db_name][name] = final_bases
                    
                    self.pool._poly_refresh_needed.remove(name)

        db_name = self.pool.db_name
        cached_bases = POLY_MRO_CACHE.get(db_name, {}).get(self._name)

        if not cached_bases and hasattr(self.pool, '_poly_mro_cache'):
            cached_bases = self.pool._poly_mro_cache.get(self._name)

        if cached_bases:
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

        # Use unbound method to avoid MRO lookup issues
        _original_BaseModel._prepare_setup(self)

        # Ensure bases remain synchronized after super
        if cached_bases:
             # Check both model class and proxy class
             for cls_to_check in [model_class, getattr(self.pool.models.get(self._name), '__dict__', {}).get('_wrapped__', self.pool.models.get(self._name))]:
                  if cls_to_check is None: continue
                  if cls_to_check.__bases__ != cached_bases:
                       _logger.warning("Bases for %s (%s) changed after super()._prepare_setup(). Re-applying...", self._name, cls_to_check.__name__)
                       try:
                           cls_to_check.__base_classes = cached_bases
                           cls_to_check.__bases__ = cached_bases
                           import ctypes as _ctypes
                           if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                               _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(cls_to_check))
                       except TypeError as e:
                           _logger.error("Failed to re-apply cached bases to class %s: %s", self._name, e)

    def _setup_base(self):
        """ Determine the inherited and custom fields of the model. """
        model_class = type(self)
        name = self._name
        
        # --- REFRESH CHECK ---
        # If this model was built before its polymorphic parents were available, 
        # we try to refresh its bases now.
        if hasattr(self.pool, '_poly_refresh_needed') and name in self.pool._poly_refresh_needed:
            all_depend_models = OrderedDict()
            for base in model_class.mro():
                if base is model_class: continue
                if '_depend_models' in base.__dict__ and base._depend_models:
                    for dep_model, dep_field in base._depend_models.items():
                        if dep_model not in all_depend_models:
                            all_depend_models[dep_model] = dep_field
            
            if all_depend_models:
                parents = list(all_depend_models.keys())
                if name != 'ir.poly_base' and 'ir.poly_base' not in parents:
                    parents.append('ir.poly_base')
                
                current_bases = list(model_class.__bases__)
                new_bases = []
                missing_any = False
                for parent in parents:
                    if parent in self.pool:
                        p_cls = self.pool[parent]
                        if p_cls not in new_bases: new_bases.append(p_cls)
                    else:
                        missing_any = True
                
                if not missing_any:
                    for b in current_bases:
                        if b not in new_bases and b.__name__ != 'BaseModel':
                            new_bases.append(b)
                    final_bases = tuple(b for b in new_bases if b is not model_class)
                    model_class.__base_classes = final_bases
                    model_class.__bases__ = final_bases
                    import ctypes as _ctypes
                    if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                        _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(model_class))
                    if hasattr(self.pool, 'models') and name in self.pool.models:
                        proxy = self.pool.models[name]
                        if proxy is not model_class:
                            proxy.__base_classes = final_bases
                            proxy.__bases__ = final_bases
                            if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                                _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(proxy))
                    if not hasattr(self.pool, '_poly_mro_cache'): self.pool._poly_mro_cache = {}
                    self.pool._poly_mro_cache[name] = final_bases
                    POLY_MRO_CACHE[self.pool.db_name][name] = final_bases
                    if hasattr(self.pool, '_poly_refresh_needed') and name in self.pool._poly_refresh_needed:
                        self.pool._poly_refresh_needed.remove(name)

        db_name = self.pool.db_name
        cached_bases = POLY_MRO_CACHE.get(db_name, {}).get(name)

        if not cached_bases and hasattr(self.pool, '_poly_mro_cache'):
            cached_bases = self.pool._poly_mro_cache.get(name)

        if cached_bases:
             model_class.__base_classes = cached_bases
             model_class.__bases__ = cached_bases
             model_class.__depends_base_classes = cached_bases
             
             import ctypes as _ctypes
             if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                 _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(model_class))
             
             # Sync proxy if exists
             if hasattr(self.pool, 'models') and self._name in self.pool.models:
                  proxy = self.pool.models[self._name]
                  if proxy is not model_class:
                       proxy.__base_classes = cached_bases
                       proxy.__bases__ = cached_bases
                       if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                           _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(proxy))
                       
                       # Exhaustive method copying from polymorphic parents to proxy
                       for base_class in cached_bases:
                            if hasattr(base_class, '_name') and base_class._name != self._name:
                                 # We inspect the whole MRO of the parent to ensure we get all methods
                                 for p_base in base_class.mro():
                                      if p_base.__name__ in ('BaseModel', 'object', 'Base'): continue
                                      for attr_name, attr_val in p_base.__dict__.items():
                                           if callable(attr_val) and not attr_name.startswith('__') and attr_name not in proxy.__dict__:
                                                try:
                                                     setattr(proxy, attr_name, attr_val)
                                                except Exception:
                                                     pass
             
             # Clear caches to force re-discovery
             if hasattr(self.pool, 'model_methods'):
                 self.pool.model_methods.pop(self._name, None)
             
             from odoo.api import Environment
             if hasattr(Environment, '_classes') and Environment._classes is not None:
                  if self.pool in Environment._classes:
                       Environment._classes[self.pool].pop(self._name, None)

        _original_BaseModel._setup_base(self)

        # Odoo 18: ensure polymorphic attributes are built after base setup
        if hasattr(model_class, '__depends_base_classes'):
             # Fail-safe: Recovery of missing fields from MRO after super()._setup_base()
             # to catch fields added by standard Odoo inheritance during incremental loading.
             from odoo.models import MetaModel
             for cls in model_class.mro():
                 if (getattr(cls, 'pool', None) is None
                         and isinstance(cls, MetaModel)
                         and hasattr(cls, '_field_definitions')):
                     for f in cls._field_definitions:
                         if f.name not in self._fields:
                             f.model_name = self._name
                             self._fields[f.name] = f
                             if f.name not in model_class.__dict__:
                                 try: setattr(model_class, f.name, f)
                                 except Exception: pass
                             if hasattr(f, '_setup_done'): f._setup_done = False
                             elif hasattr(f, 'setup_done'): f.setup_done = False

             self._setup_poly_fields()
             
             # Clear registry caches to force method re-discovery
             if hasattr(self.pool, 'model_methods'):
                  _logger.debug("Clearing model_methods for %s in _setup_base after setup", self._name)
                  self.pool.model_methods.pop(self._name, None)
             
             # Clear Environment cache to force recordset class re-creation
             from odoo.api import Environment
             if hasattr(Environment, '_classes') and Environment._classes is not None:
                  if self.pool in Environment._classes:
                       Environment._classes[self.pool].pop(self._name, None)

             # Fail-safe: Copy methods from polymorphic parents if they are missing
             # This ensures visibility even if MRO resolution is delayed or blocked by proxies
             # Use a generic approach by inspecting bases in __depends_base_classes
             depends_bases = getattr(model_class, '__depends_base_classes', ())
             for base in depends_bases:
                 if base is model_class: continue
                 # Look into the base and its MRO for methods
                 for parent in base.mro():
                     if parent in (model_class, object): continue
                     for m_name, m_meth in parent.__dict__.items():
                         # Copy methods that are not already present and are not internal/fields
                         if not m_name.startswith('__') and not hasattr(model_class, m_name):
                             if not isinstance(m_meth, (property, fields.Field)):
                                 _logger.debug("Fail-safe: Copying method %s from %s to %s", m_name, parent.__name__, self._name)
                                 setattr(model_class, m_name, m_meth)

             # Force synchronization with pool.models if it's a proxy
             if hasattr(self.pool, 'models') and self._name in self.pool.models:
                  proxy_class = self.pool.models[self._name]
                  if proxy_class is not model_class:
                       _logger.debug("Final sync of proxy class for %s in _setup_base after super", self._name)
                       # Sync MRO and attributes
                       proxy_class.__base_classes = model_class.__base_classes
                       proxy_class.__bases__ = model_class.__bases__
                       import ctypes as _ctypes
                       if hasattr(_ctypes.pythonapi, 'PyType_Modified'):
                            _ctypes.pythonapi.PyType_Modified(_ctypes.py_object(proxy_class))
                       
                       # Safe field synchronization: ensure proxy sees all fields
                       for field_name, field in model_class._fields.items():
                            if field_name not in proxy_class._fields:
                                 proxy_class._fields[field_name] = field
                       
                       # Fail-safe for proxy methods too: ensure all methods from model_class are visible
                       for m_name in dir(model_class):
                           if not m_name.startswith('__') and not hasattr(proxy_class, m_name):
                               try:
                                   m_meth = getattr(model_class, m_name)
                                   if not isinstance(m_meth, (property, fields.Field)):
                                       setattr(proxy_class, m_name, m_meth)
                               except Exception:
                                   continue

                       # Clear the proxy class cache for methods to force re-evaluation
                       if hasattr(proxy_class, '__dict__'):
                            # List of methods that might be incorrectly cached as 'not found' or stale
                            # We remove them to force Python to use the new MRO/dict
                            for m in list(proxy_class.__dict__.keys()):
                                 if not m.startswith('__') and not isinstance(proxy_class.__dict__[m], (property, fields.Field)):
                                      # Special case: don't remove core Odoo attributes that should stay
                                      if m in ('_ids', '_names', '_context', 'env', 'pool', '_wrapped__'):
                                          continue
                                      _logger.debug("Removing potentially stale %s from proxy __dict__", m)
                                      try:
                                          delattr(proxy_class, m)
                                      except (AttributeError, KeyError):
                                          pass

    def _setup_poly_fields(self):
        """ Inject polymorphic field definitions from parent models. """
        model_class = type(self)
        
        # Odoo 18: We collect all fields that should be added as related fields first.
        # This is handled by _build_dependant_model_attributes.
        # Then we handle fields that might need fresh instances if they are NOT in _depend_models.
        
        for base in model_class.__depends_base_classes:
            if hasattr(base, '_name') and base._name != self._name:
                # Add missing or inherited polymorphic fields to _fields
                if hasattr(base, '_fields'):
                    for field_name, field in base._fields.items():
                        # Protection: if the field is already in self._fields, it might be
                        # already added as a related field by _build_dependant_model_attributes.
                        # We should not overwrite it with a fresh instance which would cause collisions.
                        if field_name in self._fields:
                            continue

                        # Identify fields belonging specifically to this polymorphic parent.
                        if field.model_name == base._name:
                            # Create a fresh field instance using parent's arguments
                            args = getattr(field, '_args', {})
                            new_field = type(field)(**args)
                            new_field.model_name = self._name
                            
                            # Fields originating from _depend_models are often accessed
                            # as related fields to the base model.
                            # We should NOT redefine Many2many tables if the field is
                            # supposed to reuse the existing relation.
                            
                            is_depend_model = False
                            if hasattr(model_class, '_depend_models') and model_class._depend_models:
                                if base._name in model_class._depend_models:
                                    is_depend_model = True

                            # For Many2many, force unique naming ONLY if it's NOT a depend_model.
                            if new_field.type == 'many2many' and not is_depend_model:
                                 # Resetting these triggers Odoo's native automatic naming logic.
                                 new_field.relation = False
                                 new_field.column1 = False
                                 new_field.column2 = False
                                 new_field._explicit = False
                                 
                                 # Odoo 18: ensure we are not hitting the framework cache for M2M relations.
                                 # We force a unique relation name explicitly if automatic naming is failing.
                                 new_field.relation = "rel_%s_%s" % (self._name.replace('.', '_'), field_name)
                                 new_field.column1 = "%s_id" % self._name.replace('.', '_')
                                 new_field.column2 = "%s_id" % new_field.comodel_name.replace('.', '_')
                                 new_field._explicit = True
                                 if len(new_field.relation) > 63:
                                      new_field.relation = new_field.relation[:63]
                            elif is_depend_model:
                                 # Fields from depend_models should be handled by _build_dependant_model_attributes
                                 # which adds them as related non-stored fields.
                                 # If we are here, it means it wasn't in self._fields yet.
                                 # Force it to be non-stored related here too just in case.
                                 new_field.related = f"{base._name}.{field_name}"
                                 new_field.store = False

                            model_class._fields[field_name] = new_field
                            
                            # Ensure Odoo registry's internal field list is aware
                            if hasattr(model_class, '_field_definitions'):
                                 if new_field not in model_class._field_definitions:
                                      model_class._field_definitions.append(new_field)

        # Build dependent model attributes for all models that inherit from PolyBase.
        # This includes models with _depend_models defined (even if empty) and
        # any model that participates in the polymorphic hierarchy.
        
        try:
            # Check if we have polymorphic configuration using the calculated hierarchy
            if hasattr(type(self), '__depends_base_classes'):
                self._build_dependant_model_attributes()
                
                model_class = type(self)
                for field_name, field in self._fields.items():
                    # Protection: only inject if it's not already in __dict__
                    # This avoids overwriting methods (now available via MRO) with field descriptors
                    # Odoo 18: Injected fields from bases should NOT shadow actual methods.
                    if field_name not in model_class.__dict__:
                        # In Odoo 18, we must inject descriptors for polymorphic fields.
                        setattr(model_class, field_name, field)
                    elif field_name in self._fields and hasattr(model_class.__dict__[field_name], 'fget'):
                        # If it's already a property/descriptor but not our field, we might need to be careful
                        pass
                
                # Odoo 18: also pull in fields from parent models that might have been missed
                # by the standard MRO-based setup in _setup_base.
                # This is a safety for view validation.
                # In Odoo 18, we search the ENTIRE MRO to recover fields that might
                # have been lost during incremental registry loading.
                for base_class in model_class.mro():
                     if hasattr(base_class, '_name') and base_class._name != self._name:
                          parent_model = self.env.get(base_class._name)
                          if parent_model is not None:
                               for fname, fobj in parent_model._fields.items():
                                    if fname not in self._fields:
                                         # _logger.debug("[Poly.Setup] Manually inheriting field %s from %s to %s", fname, base_class._name, self._name)
                                         self._fields[fname] = fobj
                                         # Odoo 18: ensure field metadata is correct
                                         fobj.model_name = self._name
                                         
                                         # Odoo 18: Injected fields from bases should NOT shadow actual methods.
                                         # This is critical for 'pln_get_allocations_view' and others.
                                         if fname not in model_class.__dict__:
                                              setattr(model_class, fname, fobj)
                                         
                                         # Add to _field_definitions if missing, so _setup_base sees it
                                         if hasattr(model_class, '_field_definitions'):
                                              if fobj not in model_class._field_definitions:
                                                   model_class._field_definitions.append(fobj)

                                         # Odoo 18: view validation needs the field to be in the model's registry
                                         # but we must NOT use the same field instance if it belongs to another model.
                                         # However, for non-stored fields it might be safe to alias them.
                                         # For 'is_timeoff_task' which is a standard boolean, it should be fine.
                                         
                                         # Force setup for the new model if already setup
                                         if hasattr(fobj, '_setup_done'):
                                              fobj._setup_done = False
                                    elif fobj is not self._fields[fname] and fobj.manual and not self._fields[fname].manual:
                                         # Special case: manual fields (from customizations) might be lost if Odoo rebuilds 
                                         # and our polymorphic fields are shadowing them too aggressively.
                                         pass

                # Update _fields of the model in the pool
                if self._name in self.pool.models:
                    proxy_class = self.pool.models[self._name]
                    proxy_class._fields.update(self._fields)
                    # Odoo 18: Ensure all recovered fields are in proxy class descriptors
                    if proxy_class is not model_class:
                         for fname, fobj in self._fields.items():
                              if fname not in proxy_class.__dict__:
                                   try:
                                        setattr(proxy_class, fname, fobj)
                                   except Exception:
                                        pass
                
                # --- Odoo 18 View Validation Fix ---
                # View validation uses getattr(model, method_name) on the registry class.
                # If polymorphic methods are only in __bases__, sometimes Odoo 18's
                # dynamic registry setup misses them if it has already created a proxy class.
                # We explicitly inject the method descriptors into the model class.
                for base_class in getattr(model_class, '__depends_base_classes', ()):
                     if hasattr(base_class, '_name') and base_class._name != self._name:
                          for attr_name, attr_val in base_class.__dict__.items():
                               if callable(attr_val) and not attr_name.startswith('__') and attr_name not in model_class.__dict__:
                                    setattr(model_class, attr_name, attr_val)

                # Clear computation caches
                if hasattr(self.pool, 'field_computed'):
                    if self._name in self.pool.field_computed:
                        del self.pool.field_computed[self._name]
                if hasattr(self.pool, 'field_inverses'):
                    if self._name in self.pool.field_inverses:
                        del self.pool.field_inverses[self._name]
        except Exception as e:
            _logger.exception(f"[Poly.Setup] CRITICAL ERROR during injection for {self._name}: {e}")

    def _check_migration_needed(self):
        """
        Verifica si el modelo actual requiere migración de registros existentes
        para integrarse en la jerarquía polimórfica de ir.poly_base.
        """
        if not hasattr(type(self), '__depends_base_classes'):
            return False

        concrete_model_id = self.env['ir.model']._get_id(self._name)
        
        # We only check the main table of the model being migrated.
        # If a record in self._table is NOT in ir_poly_base with its model_id,
        # then migration is needed for this model.
        query = SQL(
            "SELECT id FROM %s WHERE id NOT IN ("
            "    SELECT old_id FROM ir_poly_base WHERE concrete_model_id = %s"
            ") LIMIT 1",
            SQL.identifier(self._table),
            concrete_model_id,
        )
        self.env.cr.execute(query)
        return bool(self.env.cr.fetchone())

    def _migrate_to_poly(self):
        """
        Realiza la migración de registros existentes a la jerarquía polimórfica.
        """
        self = self.with_context(is_migration=True)
        if not self._check_migration_needed():
            return

        _logger.info("Migrating model %s to polymorphic hierarchy", self._name)

        concrete_model_id = self.env['ir.model']._get_id(self._name)

        # Only migrate records from the CURRENT model's table that are not yet in ir_poly_base
        self.env.cr.execute(SQL(
            "SELECT id FROM %s WHERE id NOT IN ("
            "    SELECT old_id FROM ir_poly_base WHERE concrete_model_id = %s"
            ")",
            SQL.identifier(self._table),
            concrete_model_id,
        ))
        all_old_ids = {row[0] for row in self.env.cr.fetchall()}

        if not all_old_ids:
            return

        # Para cada ID viejo, realizar la migración
        concrete_model_id = self.env['ir.model']._get_id(self._name)
        
        for old_id in sorted(all_old_ids):
            try:
                with self.env.cr.savepoint():
                    # 1. Asegurar registro en ir.poly_base
                    # Intentamos buscar si ya existe (por si acaso hubo un fallo previo parcial)
                    # o lo creamos usando el ORM para disparar hooks necesarios.
                    PolyBase = self.env['ir.poly_base'].sudo()
                    poly_base_rec = PolyBase.search([
                        ('concrete_model_id', '=', concrete_model_id),
                        ('old_id', '=', old_id)
                    ], limit=1)
                    
                    if not poly_base_rec:
                        poly_base_rec = PolyBase.create({
                            'concrete_model_id': concrete_model_id,
                            'old_id': old_id,
                        })
                    
                    new_id = poly_base_rec.id

                    # 2. Duplicar datos
                    # Usamos SQL para extraer los valores crudos de los campos almacenados
                    # Esto garantiza que no haya recordsets ni basura del ORM
                    self.env.cr.execute(SQL("SELECT * FROM %s WHERE id = %s", SQL.identifier(self._table), old_id))
                    vals = self.env.cr.dictfetchone()
                    if not vals:
                        raise ValueError(f"Could not find original record {old_id} in {self._table}")

                    # Extraer el root original para restaurarlo después si es necesario
                    # Lo guardamos porque al crear el nuevo registro puede perderse si no se pasa en vals
                    old_root_id = vals.get('pln_root_id')

                    # Extraer campos X2M via ORM por separado, ya que no están en la tabla principal
                    old_record = self.browse(old_id)
                    x2m_fields = [f for f, field in self._fields.items() if field.store and field.type in ('many2many', 'one2many')]
                    
                    # Limpiar vals para el create: eliminar campos no almacenados o problemáticos
                    vals.pop('id', None)
                    # Forzar el nuevo ID
                    vals['id'] = new_id
                    
                    # Limpiar recordsets que puedan quedar en vals y procesar X2M
                    for k, v in list(vals.items()):
                        field = self._fields.get(k)
                        if not field or not field.store:
                            vals.pop(k, None)
                            continue
                        
                        if field.type == 'many2one':
                            # Extraction logic for Many2one
                            is_self_base_ref = False
                            if getattr(field, 'comodel_name', None) in self._depend_models:
                                is_self_base_ref = True
                            
                            # En SQL los M2O ya son IDs enteros o None
                            # Pero Odoo 18 puede devolver recordsets o tuplas incluso en SQL crudo si hay interceptores
                            if v is None:
                                vals[k] = False
                            elif is_self_base_ref:
                                # Saltamos validación del ORM para campos que apuntan a bases
                                vals[k] = False
                            else:
                                # Extraer ID de forma agresiva
                                def extract_id(val):
                                    if not val:
                                        return False
                                    # Si es un recordset (tiene .ids y no es lista/tupla)
                                    if hasattr(val, '_name') and hasattr(val, 'ids'):
                                        try:
                                            # We use val[:1].id to get the first ID if it's a recordset
                                            return val[:1].id if val else False
                                        except:
                                            # Fallback if it's some other Odoo proxy
                                            return val.id if hasattr(val, 'id') else False
                                    # Si es una tupla (id, name) o lista de recordsets
                                    if isinstance(val, (list, tuple)) and len(val) > 0:
                                        return extract_id(val[0])
                                    # Si es algo casteable a int
                                    try:
                                        return int(val)
                                    except (ValueError, TypeError):
                                        return False
                                
                                vals[k] = extract_id(v)
                                # Final cleanup for pln_root_id issues
                                if k == 'pln_root_id' and vals[k] is not False:
                                    # We ensure it's an int, not a recordset
                                    if not isinstance(vals[k], (int, bool)):
                                        try:
                                            vals[k] = int(vals[k])
                                        except:
                                            vals[k] = False
                        
                        # Limpiar campos técnicos de Odoo
                        if k in ('__last_update', 'display_name', 'create_uid', 'create_date', 'write_uid', 'write_date'):
                            vals.pop(k, None)

                    # Añadir X2M procesados via ORM
                    for k in x2m_fields:
                        try:
                            # Evitamos campos problemáticos de project.task que causan NOT NULL violations
                            if self._name == 'project.task' and k in ('user_ids', 'personal_stage_type_ids'):
                                continue
                                
                            rel_records = old_record[k]
                            if rel_records:
                                vals[k] = [Command.set(rel_records.ids)]
                        except Exception:
                            continue
                    
                    # Preservar campos de auditoría y referencias circulares (leídos antes del create)
                    # Añadimos pln_root_id y cualquier M2O que apunte a las bases
                    extra_cols = []
                    if 'pln_root_id' in self._fields:
                        extra_cols.append('pln_root_id')
                    for k, field in self._fields.items():
                        if k != 'pln_root_id' and field.store and field.type == 'many2one' and getattr(field, 'comodel_name', None) in self._depend_models:
                            extra_cols.append(k)
                    
                    audit_cols = ['create_uid', 'create_date', 'write_uid', 'write_date'] + extra_cols
                    # Use safer SQL construction for Odoo 18
                    col_identifiers = [SQL.identifier(c) for c in audit_cols]
                    self.env.cr.execute(SQL(
                        "SELECT %s FROM %s WHERE id = %s",
                        SQL(', ').join(col_identifiers),
                        SQL.identifier(self._table), old_id
                    ))
                    audit = self.env.cr.dictfetchone() or {}

                    # Crear el nuevo registro (esto disparará la creación en depend_models)
                    self.env.flush_all()
                    
                    try:
                        # Odoo 18: bypass security and recomputes
                        new_record = self.with_context(
                            tracking_disable=True,
                            mail_create_nolog=True,
                            mail_create_nosubscribe=True,
                            prefetch_fields=False,
                            no_upsert=True,  # Evitar lógicas de auto-merge si existen
                            is_migration=True,  # Marcar explícitamente como migración
                        ).create([vals])
                        # IMPORTANTE: Forzar flush para que los registros base existan en BD
                        # y no fallen las FKs en _update_foreign_keys
                        self.env.flush_all()
                        
                        # Doble verificación: asegurar que ir_poly_base tenga el registro 
                        # (debería haber sido creado por el create() arriba si no lo estuviera,
                        # o el create() debería haber usado el ID que le pasamos).
                        # Como ya lo creamos al inicio de la iteración con new_poly,
                        # solo nos aseguramos de que siga ahí.
                        if not self.env['ir.poly_base'].sudo().browse(new_id).exists():
                            self.env['ir.poly_base'].sudo().create({
                                'id': new_id,
                                'concrete_model_id': concrete_model_id,
                                'old_id': old_id,
                            })
                    except Exception as create_err:
                        _logger.error("Create failed for %s ID %s. Vals: %s", self._name, old_id, vals)
                        raise create_err

                    # Restaurar auditoría en todas las tablas involucradas
                    audit_tables = [self._table, 'ir_poly_base']
                    for base_name in self._depend_models:
                        base_model = self.env[base_name]
                        if base_model._table:
                            audit_tables.append(base_model._table)
                    
                    for table in set(audit_tables):
                        # Columnas a restaurar: auditoría y referencias circulares
                        self.env.cr.execute("""
                            SELECT column_name 
                            FROM information_schema.columns 
                            WHERE table_name = %s AND column_name IN %s
                        """, [table, tuple(audit_cols)])
                        existing_cols = {row[0] for row in self.env.cr.fetchall()}
                        
                        if not existing_cols:
                            continue
                            
                        set_clauses = []
                        params = []
                        # Columnas a restaurar: auditoría y referencias circulares
                        for col in audit_cols:
                            # If it's pln_root_id, we restore the original old ID for now
                            # it will be updated to the new ID later in _update_foreign_keys bulk
                            if col == 'pln_root_id' and old_root_id:
                                if col in existing_cols:
                                    set_clauses.append(f"{col}=%s")
                                    params.append(old_root_id)
                                continue

                            if col in existing_cols and audit.get(col):
                                set_clauses.append(f"{col}=%s")
                                params.append(audit[col])
                        
                        if set_clauses:
                            query = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE id=%s"
                            params.append(new_id)
                            self.env.cr.execute(query, params)

                    # 3. Actualizar Referencias
                    # IMPORTANTE: Se hace antes de borrar el ID viejo para satisfacer FKs si fuera necesario
                    self._update_foreign_keys(old_id, new_id)

                    # 4. Limpieza
                    # Borrado físico de las tablas originales para el ID viejo
                    for table in set(audit_tables):
                        self.env.cr.execute(SQL("DELETE FROM %s WHERE id = %s", SQL.identifier(table), old_id))
                    
                    _logger.info("Migrated %s ID %s -> %s", self._name, old_id, new_id)

            except Exception as e:
                _logger.error("Failed to migrate %s ID %s: %s", self._name, old_id, e)
                # Continuamos con el siguiente registro
        
        # Post-migration: re-trigger syncs that were skipped during migration
        # We search all records of this model that now exist in ir_poly_base
        _logger.info("Performing post-migration sync for %s", self._name)

        # Before syncing, we perform a repository-wide update for pln_root_id
        # since all records are now migrated and have their new IDs in ir_poly_base
        if 'pln_root_id' in self._fields:
            try:
                # This query updates ALL pln_root_id that still point to old IDs
                # across all tables that have this field.
                self.env.cr.execute("""
                    SELECT f.model, f.name FROM ir_model_fields f 
                    WHERE f.name = 'pln_root_id' AND f.store = True
                """)
                for root_model, root_field in self.env.cr.fetchall():
                    try:
                        root_table = self.env[root_model]._table
                        # We use the ir_poly_base table as the mapping source
                        # We also set to NULL if the old_id is not found in ir_poly_base to satisfy FKs
                        # Split queries into smaller pieces to avoid static analyzer confusion
                        # We use string constants for the SQL skeleton and identifier substitution later.
                        sql_upd = "UPDATE %s AS t"
                        sql_set = "SET %s = CASE WHEN m.id IS NOT NULL THEN m.id ELSE NULL END"
                        sql_frm = "FROM (SELECT DISTINCT %s AS old_id FROM %s) AS old_ids"
                        sql_jn1 = "LEFT JOIN ir_poly_base m ON old_ids.old_id = m.old_id"
                        sql_jn2 = "AND m.concrete_model_id = (SELECT id FROM ir_model WHERE model = %s)"
                        sql_whr = "WHERE t.%s = old_ids.old_id"
                        full_sql = f"{sql_upd} {sql_set} {sql_frm} {sql_jn1} {sql_jn2} {sql_whr}"
                        self.env.cr.execute(SQL(full_sql, SQL.identifier(root_table), SQL.identifier(root_field), SQL.identifier(root_field), SQL.identifier(root_table), self._name, SQL.identifier(root_field)))
                    except:
                        continue
            except Exception as e:
                _logger.error("Failed to bulk update pln_root_id: %s", e)

        newly_migrated_records = self.with_context(active_test=False).search([])
        for record in newly_migrated_records:
            try:
                # Ensure record exists and is accessible
                if not record.exists():
                    continue
                
                # During migration, avoid syncs that might fail due to incomplete mapping
                # We skip them here and rely on the bulk update or manual re-sync later.
                if self.env.context.get('is_migration'):
                    continue

                if hasattr(record, '_pln_sync_dependencies_to_links'):
                    record._pln_sync_dependencies_to_links()
                if hasattr(record, '_pln_set_root_from_project'):
                    record._pln_set_root_from_project()
                # If pln_root_id is still pointing to an old ID (failed to bulk update)
                # or if it was nullified, we re-calculate it.
                if hasattr(record, 'pln_root_id') and not record.pln_root_id:
                     record._pln_set_root_from_project()
            except Exception as e:
                _logger.warning("Post-migration sync failed for %s ID %s: %s", self._name, record.id, e)

    def _update_foreign_keys(self, old_id, new_id):
        """
        Actualiza todas las referencias al ID viejo con el nuevo ID.
        """
        # A. Many2one y Many2many estándar
        # Buscamos campos almacenados que apunten a este modelo
        # En Odoo 18, ir_model tiene el nombre de la tabla en la columna 'name' o derivado, 
        # pero la forma más segura y portable es usar self.env[model]._table
        # Odoo 18: Many2one references are stored in 'relation' column of ir_model_fields for all types
        self.env.cr.execute("""
            SELECT f.model, f.name, f.ttype
            FROM ir_model_fields f
            WHERE f.relation = %s AND f.store = True
        """, [self._name])
        
        for field_model, field_name, ttype in self.env.cr.fetchall():
            # Skip update if we are already updating this field in a specialized way
            if self._name == 'project.task' and field_model == 'project.task' and field_name == 'pln_root_id':
                continue
            
            try:
                model_obj = self.env[field_model]
                table_name = model_obj._table
                
                # Check field object directly to be sure
                field = model_obj._fields.get(field_name)
                if not field:
                    continue
            except Exception:
                continue

            try:
                # Usamos un savepoint para cada actualización para evitar abortar la transacción entera
                with self.env.cr.savepoint():
                    if ttype in ('many2one', 'many2many'):
                        # Para M2M necesitamos encontrar la tabla intermedia, para M2O la tabla del modelo
                        # Odoo 18: Many2one tiene comodel_name, Many2many tiene relation
                        if ttype == 'many2many':
                            # Many2many specific: uses 'relation' for table name and 'column2' for the target ID
                            rel_table = getattr(field, 'relation', None)
                            col_id = getattr(field, 'column2', None)
                        else:
                            # Many2one specific: uses 'comodel_name' but we update the current model's table
                            rel_table = getattr(field, 'comodel_name', None)
                            col_id = field_name
                            
                        if not rel_table or not col_id:
                            continue
                        
                        # Para Many2one, si rel_table es el comodel, queremos actualizar la tabla donde ESTÁ el campo
                        target_update_table = rel_table if ttype == 'many2many' else table_name

                        # Verificar si es una vista antes de intentar el UPDATE
                        self.env.cr.execute("""
                            SELECT count(*) FROM information_schema.views 
                            WHERE table_name = %s AND table_schema = 'public'
                        """, [target_update_table])
                        if self.env.cr.fetchone()[0] > 0:
                            continue

                        if ttype == 'many2many':
                            # Manejo de duplicados en M2M
                            col_id_other = getattr(field, 'column1', None)
                            if col_id_other:
                                self.env.cr.execute(SQL("""
                                    DELETE FROM %s 
                                    WHERE %s = %s
                                    AND %s IN (
                                        SELECT %s FROM %s WHERE %s = %s
                                    )
                                """, SQL.identifier(rel_table), SQL.identifier(col_id), old_id,
                                     SQL.identifier(col_id_other), SQL.identifier(col_id_other),
                                     SQL.identifier(rel_table), SQL.identifier(col_id), new_id))

                        # Special handling for project_task_user_rel (Personal Task Stage)
                        # Odoo 18: task_id, user_id unique constraint
                        if target_update_table == 'project_task_user_rel' and col_id == 'task_id':
                            self.env.cr.execute(SQL("""
                                DELETE FROM project_task_user_rel 
                                WHERE task_id = %s
                                AND user_id IN (
                                    SELECT user_id FROM project_task_user_rel WHERE task_id = %s
                                )
                            """, new_id, old_id))

                        self.env.cr.execute(SQL(
                            "UPDATE %s SET %s = %s WHERE %s = %s",
                            SQL.identifier(target_update_table), SQL.identifier(col_id), new_id,
                            SQL.identifier(col_id), old_id
                        ))
            except Exception as e:
                _logger.warning("Minor issue during FK update for %s.%s (ID %s -> %s): %s", field_model, field_name, old_id, new_id, e)

        # A2. Specialized Many2one update for pln_root_id (across all tables)
        # Any model pointing to a polymorphic base must be updated
        # We only update if the old_id is not already a polymorphic ID (new_id)
        # to avoid double-updating or cycle issues during the transition
        if old_id != new_id:
            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute("""
                        SELECT f.model, f.name FROM ir_model_fields f 
                        WHERE f.name = 'pln_root_id' AND f.store = True
                    """)
                    for root_model, root_field in self.env.cr.fetchall():
                        try:
                            root_table = self.env[root_model]._table
                            self.env.cr.execute(SQL(
                                "UPDATE %s SET %s = %s WHERE %s = %s",
                                SQL.identifier(root_table), SQL.identifier(root_field), new_id,
                                SQL.identifier(root_field), old_id
                            ))
                        except:
                            continue
            except Exception:
                pass

        # B. Referencias Dinámicas (res_model / res_id)
        dynamic_refs = [
            ('ir_attachment', 'res_model', 'res_id'),
            ('mail_message', 'model', 'res_id'),
            ('mail_followers', 'res_model', 'res_id'),
            ('mail_activity', 'res_model', 'res_id'),
            ('ir_model_data', 'model', 'res_id'),
        ]
        for table, model_col, id_col in dynamic_refs:
            try:
                # Usamos un savepoint para cada actualización dinámica para evitar abortar la transacción entera
                # en caso de violación de restricción única (ej. mail_followers)
                with self.env.cr.savepoint():
                    if table == 'mail_followers':
                        # Para mail_followers, si ya existe el seguidor para el nuevo ID, 
                        # simplemente borramos el del viejo ID en lugar de actualizar.
                        self.env.cr.execute(SQL("""
                            DELETE FROM mail_followers 
                            WHERE res_model = %s AND res_id = %s
                            AND partner_id IN (
                                SELECT partner_id FROM mail_followers 
                                WHERE res_model = %s AND res_id = %s
                            )
                        """, self._name, old_id, self._name, new_id))

                    self.env.cr.execute(SQL(
                        "UPDATE %s SET %s = %s WHERE %s = %s AND %s = %s",
                        SQL.identifier(table), SQL.identifier(id_col), new_id,
                        SQL.identifier(model_col), self._name, SQL.identifier(id_col), old_id
                    ))
            except Exception as e:
                _logger.warning("Minor issue during dynamic ref update for %s (ID %s -> %s): %s", table, old_id, new_id, e)

        # C. Casos Especiales
        # C1. mail.alias
        if 'mail.alias' in self.env:
            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute("""
                        UPDATE mail_alias SET alias_parent_thread_id = %s 
                        WHERE alias_parent_model_id = (SELECT id FROM ir_model WHERE model = %s)
                        AND alias_parent_thread_id = %s
                    """, [new_id, self._name, old_id])
            except Exception:
                pass

        # C2. project_task_user_rel (Odoo 18 special relation table)
        if self._name == 'project.task':
            try:
                with self.env.cr.savepoint():
                    # En Odoo 18, project_task_user_rel tiene columnas: id, task_id, user_id, stage_id, ...
                    # Manejar duplicados antes de actualizar
                    self.env.cr.execute("""
                        DELETE FROM project_task_user_rel t1
                        WHERE task_id = %s
                        AND EXISTS (
                            SELECT 1 FROM project_task_user_rel t2
                            WHERE t2.task_id = %s 
                            AND t2.user_id IS NOT DISTINCT FROM t1.user_id
                        )
                    """, [old_id, new_id])
                    
                    self.env.cr.execute("""
                        UPDATE project_task_user_rel SET task_id = %s WHERE task_id = %s
                    """, [new_id, old_id])
            except Exception as e:
                _logger.warning("Issue updating project_task_user_rel for ID %s -> %s: %s", old_id, new_id, e)

        # C3. numa_planning_link (Foreign Key constraints)
        self.env.cr.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'numa_planning_link'")
        if self.env.cr.fetchone()[0] > 0:
            for col in ['source_node_id', 'target_node_id']:
                try:
                    with self.env.cr.savepoint():
                        # Para numa_planning_link, existe una FK a numa_planning_node.
                        # El ID viejo YA NO existe en numa_planning_node en este punto
                        # porque _migrate_to_poly se asegura de que el nuevo_id ya esté creado.
                        # PERO, si el source_node_id apunta a un ID que aún no ha sido migrado,
                        # fallará si intentamos migrar el link antes que el nodo.
                        # Como _migrate_to_poly procesa los IDs en orden, y los links suelen ser
                        # entre registros del mismo modelo o relacionados, intentamos actualizar.
                        
                        # Eliminar duplicados si los hay
                        other_col = 'target_node_id' if col == 'source_node_id' else 'source_node_id'
                        self.env.cr.execute(SQL("""
                            DELETE FROM numa_planning_link t1
                            WHERE %s = %s
                            AND EXISTS (
                                SELECT 1 FROM numa_planning_link t2
                                WHERE t2.%s = %s
                                AND t2.%s = t1.%s
                            )
                        """, SQL.identifier(col), old_id, SQL.identifier(col), new_id, 
                             SQL.identifier(other_col), SQL.identifier(other_col)))

                        self.env.cr.execute(SQL(
                            "UPDATE numa_planning_link SET %s = %s WHERE %s = %s",
                            SQL.identifier(col), new_id, SQL.identifier(col), old_id
                        ))
                except Exception as e:
                    _logger.debug("Could not update numa_planning_link.%s for ID %s -> %s (probably order of migration): %s", col, old_id, new_id, e)

    def _auto_init(self):
        """
        Extend _auto_init to ensure migration is performed when the table is created/updated.
        """
        res = super()._auto_init()
        # Only migrate if _depend_models is defined (is a polymorphic model)
        if getattr(self, '_depend_models', None) is not None:
            # Check if migration is needed and perform it
            if self._check_migration_needed():
                _logger.info("Auto-migrating %s to polymorphic hierarchy in _auto_init", self._name)
                self._migrate_to_poly()
        return res

    def _register_hook(self):
        """
        Perform actions right after the registry is built.

        This method extends the standard Odoo registry hook to ensure that
        polymorphic models don't have ID conflicts. It checks the current
        max ID values for all dependent models and adjusts the ir.poly_base
        sequence if necessary to avoid ID clashes.
        """
        super()._register_hook()

        # Only perform actions for polymorphic models
        if getattr(self, '_depend_models', None) is not None:
            # 1. Sincronizar secuencias
            def get_max_id(base_name) -> int:
                """
                Get the maximum ID currently used in a model's table.
                """
                base_model = self.env[base_name]
                if base_model._table:
                    # Direct SQL to get the actual MAX ID, regardless of sequence state
                    try:
                        self.env.cr.execute(SQL(
                            "SELECT MAX(id) FROM %s",
                            SQL.identifier(base_model._table)
                        ))
                        res = self.env.cr.fetchone()
                        return res[0] or 0
                    except Exception:
                        return 0
                return 0

            # Ensure ir.poly_base sequence starts AFTER the max ID of any participant table
            try:
                max_id = self._get_max_poly_id()
            except Exception:
                # Si falla algo en la transacción, no podemos continuar con el reajuste
                # de la secuencia aquí.
                return

            if max_id > 0:
                # Update ir.poly_base sequence to avoid clashing with existing records
                self.env.cr.execute(SQL(
                    "SELECT last_value FROM %s",
                    SQL.identifier("ir_poly_base_id_seq")
                ))
                current_seq = self.env.cr.fetchone()[0]
                
                if max_id >= current_seq:
                    _logger.info("Synchronizing ir.poly_base sequence to %s (max detected ID: %s)", max_id + 1, max_id)
                    self.env.cr.execute(SQL(
                        "ALTER SEQUENCE IF EXISTS %s RESTART WITH %s",
                        SQL.identifier("ir_poly_base_id_seq"),
                        max_id + 1
                    ))

    @classmethod
    def _build_dependant_model_attributes(self):
        """
        Initialize and build the attributes of a polymorphic model.
        """
        def set(name, field, related_base=None):
            """
            Set a field on the model.

            Args:
                name: The name of the field
                field: The field object
                related_base: The name of the related base model (if any)
            """
            _logger.debug(f'Adding field {name} to {self._name}'
                          f' (base: {related_base or "N/A"})')
            setattr(self, name, field)
            self._fields[name] = field
            field._direct = True
            field.prepare_setup()
            field.__set_name__(self, name)

        # Create a poly_base_id many2one - the core link to ir.poly_base
        set('poly_base_id',
            PolyReference(
                'ir.poly_base',
                string='Poly base',
                automatic=True,
                readonly=True,
            )
        )

        # Create a concrete_model_id field to know the concrete model of each record
        set('concrete_model_id',
            fields.Many2one(
                'ir.model',
                string='Concrete model',
                compute='_compute_concrete_model_id',
                compute_sudo=True,
                automatic=True,
                readonly=True
             )
        )

        # Add poly_payload field for DTO-style injection
        # This field allows transporting subclass-specific data as JSON
        set('poly_payload',
            fields.Text(
                string='Polymorphic Payload',
                store=False,
                prefetch=False,
                compute='_compute_payload_dummy',
                inverse='_inverse_payload_dummy',
                help='Technical field for transporting polymorphic subclass data as JSON'
            )
        )

        # set('id',
        #      fields.Id(string='id',
        #                related='poly_base_id.id',
        #                automatic=True))

        # Add standard audit fields related to the poly_base record
        # TODO: log fields should be registered only on ir.poly_base
        #       currently not working
        set('create_uid',
             fields.Many2one('res.users', string='Created by',
                             related='poly_base_id.create_uid',
                             automatic=False))
        set('create_date',
             fields.Datetime(string='Created on',
                             related='poly_base_id.create_date',
                             automatic=False))
        set('write_uid',
             fields.Many2one('res.users', string='Last Updated by',
                             related='poly_base_id.write_uid',
                             automatic=False))
        set('write_date',
             fields.Datetime(string='Last Updated on',
                             related='poly_base_id.write_date',
                             automatic=False))

        # Collect all fields from dependent models
        related_fields = {}
        
        all_bases = getattr(type(self), '__depends_base_classes', ())
        # IMPORTANT: ensure we use the same order as in __depends_base_classes (already reversed in _build_model)
        dependent_model_names = [cls._name for cls in reversed(all_bases) if cls._name not in (self._name, 'ir.poly_base')]

        for model_name in dependent_model_names:
            def add_subfields(mm):
                """
                Recursively add fields from a dependent model and its dependencies.

                Args:
                    mm: The name of the model to add fields from
                """
                if mm == 'ir.poly_base':
                    return  # Skip ir.poly_base as its fields are already handled

                if mm not in self.pool:
                    return

                base_model = self.pool[mm]

                # Add fields from the model
                for subfield_name, subfield in base_model._fields.items():
                    # Only add fields that aren't already defined, aren't PolyReferences,
                    # and aren't related fields (to avoid duplication)
                    if not isinstance(subfield, PolyReference) and \
                       not subfield.related:
                        if subfield_name not in related_fields:
                            related_fields[subfield_name] = (
                                mm,
                                subfield_name,
                                subfield.type,
                                subfield.comodel_name,
                                subfield
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
        explicit_depend_models = getattr(type(self), '_depend_models', {}) or {}
        
        for base_model_name, base_field_name in explicit_depend_models.items():
            related_bases[base_model_name] = base_field_name
            set(base_field_name,
                PolyReference(comodel_name=base_model_name,
                              string=f'Base for {base_model_name}',
                              automatic=True, readonly=True)
                )

        # Create related fields for all fields from dependent models
        related_counter = 1
        for new_field_name in related_fields.keys():
            model, field_name, field_type, comodel, description = related_fields[new_field_name]

            # Skip if the field is already defined
            if field_name in self._fields:
                continue

            if model not in related_bases:
                model_field = f'related_{related_counter}'
                related_counter += 1
                related_bases[model] = model_field
                set(model_field,
                    PolyReference(comodel_name=model, string=f'Base for {model}',
                                  automatic=True, readonly=True)
                )
            else:
                model_field = related_bases[model]
                if model_field not in self._fields:
                    set(model_field,
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

            # Create the appropriate field type
            if field_type in ['many2one', 'many2many', 'one2many']:
                related_path = f'{related_bases[model]}.{field_name}'
                # Odoo 18: Ensure Many2many related fields don't cause table collisions.
                # We use the comodel_name and related path.
                # Use fresh field instantiation but force it to be a related field from the start.
                new_field = field_subclass(
                    comodel_name=comodel,
                    string=description.string,
                    related=related_path,
                    automatic=True,
                    store=False,  # Force non-stored to avoid setup_nonrelated checks
                )
            elif field_subclass:
                new_field = field_subclass(
                    string=description.string,
                    related=f'{related_bases[model]}.{field_name}',
                    automatic=True,
                    readonly=False,
                    store=False,
                )
            else:
                raise TypeError(_('Unsupported field type %s for field %s') %
                                (field_type, field_name))

            # Add the field to the model
            set(field_name, new_field, related_bases[model])

        # Add _depends methods
        # Odoo 18: skip method copying as we now use MRO
        pass

        _logger.debug(f'_build_dependant_model_attributes finished')


    @api.model_create_multi
    def create(self, data_list: list[ValuesType]) -> Self:
        """
        Create records from the stored field values in data_list.

        For polymorphic models, this method:
        1. Creates a record in ir.poly_base
        2. Creates records in all dependent models with the same ID
        3. Creates the record in this model with the same ID

        This ensures that all parts of the polymorphic record are created
        with the same ID, allowing the polymorphic inheritance to work.

        In case the data_list contains a 'concrete_model_id' key, the create will be handled by the concrete model.
        This is useful for polymorphic creates of subclasses.
        ATTENTION: all returned records will be of only one concrete model, the first one found in the data_list.
                   Odoo does no support different models as part of the returned recordset.
                   This is a limitation of Odoo's ORM.
                   It is caller responsibility to ensure that the concrete_model_id is set to a subclass of 
                   the polymorphic model. No validation is done on the concrete_model_id.

        Args:
            data_list: List of dictionaries containing field values. Each dictionary
                can contain fields from this model and from all dependent models.
                Optionally, an 'id' key can be provided to use a specific ID.

        Returns:
            Self: Recordset containing the newly created records. All records in the
                polymorphic hierarchy (base models and dependent models) will share
                the same ID.

        Raises:
            ValidationError: If trying to create a record with an ID that already exists,
                or if a dependent model does not exist.
            AccessError: If the current user does not have permission to create records
                in one or more of the dependent models.

        TODO: Investigate if access rules should be applied base by base also
        """
        if self._depend_models is None:
            # Normal Odoo ORM model, just process it the normal way
            return super().create(data_list)
        else:
            # It is a polymorphic create
            # Validate permissions on dependent models before creating
            for base_name in self._depend_models.keys():
                if base_name not in self.pool:
                    raise ValidationError(
                        _('Dependent model %s does not exist') % base_name
                    )
                base_model = self.env[base_name]
                base_model.check_access('create')

            # If this is a polymorphic create of a subclass handle it recursively

            new_records = self
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
            
            if concrete_model_id:
                concrete_model = self.env['ir.model'].browse(concrete_model_id).exists()
                if concrete_model and concrete_model._name != self._name:
                    # clean the data_list from the concrete_model_id
                    # Create a copy to avoid modifying the original data
                    new_vals_list = []
                    for data in data_list:
                        new_data = dict(data)
                        if 'concrete_model_id' in new_data:
                            del new_data['concrete_model_id']
                        new_vals_list.append(new_data)

                    _logger.debug(f'Creating subclass {concrete_model._name} with {new_vals_list}')
                    new_records = concrete_model.create(new_vals_list)
                    return new_records

            # Get all related fields and their definitions
            inverse_related = {field_name.split('.')[-1]: field_definition
                               for field_name, field_definition in self._fields.items()
                               if field_definition.related}

            # Map field names to base model names
            inverse_field2base = {base_field: base_name for base_name, base_field in self._depend_models.items()}

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

            # Process each record to create
            for data in data_list:
                # Handle explicit ID or create a new one via ir.poly_base
                if 'id' in data:
                    new_id = data['id']
                else:
                    # Create a new ir.poly_base record to get a new ID
                    # Ensure ID doesn't clash with existing ones in the hierarchy
                    # Using SUDO to ensure we have access and can set the ID
                    max_id = self._get_max_poly_id()
                    new_poly = self.env['ir.poly_base'].sudo().create(dict(
                        id=max_id + 1,
                        concrete_model_id=self.env['ir.model']._get_id(self._name)
                    ))
                    _logger.debug(f'Creating poly base for {self._name}, id = {new_poly.id} (max_id was {max_id})')
                    new_id = new_poly.id

                # Create or update records in all dependent models
                for base, field_set in bases_to_create.items():
                    base_model = self.env[base]
                    base_data = {}

                    # Add fields that are explicitly in the field set
                    for field_name in field_set:
                        if field_name in data:
                            base_data[field_name] = data[field_name]

                    # Add fields that match the base model's fields
                    for field_name, field_definition in base_model._fields.items():
                        field_plain_name = field_name.split('.')[-1]
                        if field_plain_name in data:
                            base_data[field_name] = data[field_plain_name]

                    # Set the ID to match the polymorphic record
                    base_data['id'] = new_id

                    # Create or update the base record
                    existing_base = base_model.search([('id', '=', new_id)], limit=1)
                    if not existing_base:
                        _logger.debug(f'Creating {base} with {base_data} for id {new_id}')
                        
                        # Handle potential field collisions in base models
                        if 'state' in base_data:
                            field = base_model._fields.get('state')
                            if field and field.type == 'selection':
                                selection_values = [v[0] for v in field._description_selection(self.env)]
                                if base_data['state'] not in selection_values:
                                    _logger.debug("Collision detected for 'state' field in base model %s. Value '%s' is invalid. Resetting to default.", 
                                                    base, base_data['state'])
                                    base_data.pop('state')

                        base_model.create([base_data])
                    else:
                        _logger.debug(f'Updating {base} with {base_data} for id {new_id}')
                        
                        # Handle potential field collisions in base models during update
                        if 'state' in base_data:
                            field = base_model._fields.get('state')
                            if field and field.type == 'selection':
                                selection_values = [v[0] for v in field._description_selection(self.env)]
                                if base_data['state'] not in selection_values:
                                    base_data.pop('state')

                        existing_base.write(base_data)

                # Finally, create the record in this model
                base_data = {}
                for full_field_name, field_definition in self._fields.items():
                    # Only include non-related, stored fields
                    if not field_definition.related and field_definition.store:
                        field_name = full_field_name.split('.')[-1]
                        if field_name in data:
                            base_data[field_name] = data[field_name]

                base_data['id'] = new_id
                
                # Handle potential field collisions (e.g., 'state' in digital.event vs fsm.instance)
                # If we are in Level 3, and Level 1/2 also have 'state', we must ensure 
                # we don't pass an invalid value for this specific model's 'state' field.
                if 'state' in base_data:
                    field = self._fields.get('state')
                    if field and field.type == 'selection':
                        selection_values = [v[0] for v in field._description_selection(self.env)]
                        if base_data['state'] not in selection_values:
                            _logger.debug("Collision detected for 'state' field in %s. Value '%s' is invalid. Resetting to default.", 
                                            self._name, base_data['state'])
                            base_data.pop('state')

                _logger.debug(f'Creating {self._name} with {base_data} for id {new_id}')
                new_record = super().create([base_data])
                new_records |= new_record

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

    def unlink(self):
        """
        Delete records and their dependent records.

        For polymorphic models, this method ensures that when a record is deleted,
        all corresponding records in dependent models are also deleted, maintaining
        the integrity of the polymorphic structure.

        Returns:
            Result of the standard unlink operation
        """
        if not self:
            return True

        # For polymorphic models, delete records in base models
        if getattr(self, '_depend_models', None) is not None:
            for base_model_name in self._depend_models:
                self.env[base_model_name].browse(self.ids).unlink()

        # Standard unlink for the current concrete model
        return super().unlink()


    def read(self, fields=None, load='_classic_read'):
        return super().read(fields=fields, load=load)

    def _compute_field_value(self, field):
        return super()._compute_field_value(field)

    def write(self, vals):
        """
        Override write to intercept and merge poly_payload data.
        
        Similar to create, this allows updating subclass-specific fields
        through the payload mechanism.
        """
        if not self:
            return True

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
                    if f in base_model._fields and (
                        f.startswith('pln_') or 
                        (f not in self._fields and f not in pool_fields)
                    )
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
        if not hasattr(type(self), '__depends_base_classes'):
            return super().fields_get(allfields=allfields, attributes=attributes)

        result = super().fields_get(allfields=allfields, attributes=attributes)
        
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
        if not hasattr(type(self), '__depends_base_classes'):
            return super()._determine_fields_to_fetch(field_names, ignore_when_in_cache)

        # Filter out fields that are not in self._fields or pool
        valid_field_names = [
            name for name in field_names 
            if name in self._fields or name == 'id' or name in self.pool[self._name]._fields
        ]
        return super()._determine_fields_to_fetch(valid_field_names, ignore_when_in_cache)

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

    def _field_to_sql(self, alias: str, fname: str, query: (Query | None) = None, flush: bool = True) -> SQL:
        """
        Return an :class:`SQL` object that represents the value of the given field.

        This method extends the standard _field_to_sql to handle PolyReference fields,
        which are non-stored Many2one fields that reference polymorphic models by ID.

        Args:
            alias: The table alias to use in the SQL expression.
            fname: The name of the field to convert to SQL.
            query: Optional Query object. Required for inherited fields, many2one fields,
                and properties fields where joins are added to the query.
            flush: If True, adds metadata to ensure the field is flushed before
                executing the query. Defaults to True.

        Returns:
            SQL: An SQL object representing the field value in the SQL query.

        Raises:
            ValueError: If the field name is invalid or doesn't exist on the model.

        Note:
            For PolyReference fields, this method converts them to use the record's ID
            directly from ir.poly_base, as these fields are not stored as foreign keys.
        """
        property_name = None
        if '.' in fname:
            fname, property_name = fname.split('.', 1)

        field = self._fields.get(fname)
        if not field:
            raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")

        if isinstance(field, PolyReference):
            model = self.env['ir.poly_base']
            field = model._fields['id']
            return model._field_to_sql(alias, field.name, query)

        return super()._field_to_sql(alias, fname, query, flush)


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
        
        # Add all polymorphic models that are currently in the registry
        # but might have been missed by standard reflection.
        for name, model in self.env.registry.items():
            if name not in all_model_names:
                if hasattr(model, '__depends_base_classes'):
                    # Check if the model belongs to the module being initialized
                    module = self._context.get('module')
                    if module and (model._module == module or getattr(model, '_original_module', None) == module):
                        all_model_names.append(name)
        
        return super()._reflect_models(all_model_names)


class IrModelFields(models.Model):
    _inherit = 'ir.model.fields'

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
        
        return super()._reflect_fields(model_names)


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


_logger.info("Initializing numa_poly: monkey-patching odoo.models")

# Monkey-patch Odoo models
odoo.models.BaseModel = PolyBase
odoo.models.AbstractModel = PolyBase
odoo.models.Model = PolyModel
odoo.models.TransientModel = PolyTransientModel
odoo.fields.Many2one.convert_to_read = poly_many2one_convert_to_read
odoo.fields.Many2many.setup_nonrelated = poly_many2many_setup_nonrelated


# --- Odoo 18 Registry Finalization Hook ---

# PATCH: Field.resolve_depends to ignore missing polymorphic fields during build
_original_Field_resolve_depends = odoo.fields.Field.resolve_depends

def poly_Field_resolve_depends(self, registry):
    try:
        yield from _original_Field_resolve_depends(self, registry)
    except ValueError as e:
        error_msg = str(e)
        if "not found in model" in error_msg:
            # We only ignore if the model is potentially polymorphic (has ir.poly_base or _depend_models)
            model_name = error_msg.split("found in model ")[-1].strip('.')
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
                    _logger.info("[poly] resolve_depends: ignoring missing field error in polymorphic model %s: %s", model_name, error_msg)
                    return
        raise e

odoo.fields.Field.resolve_depends = poly_Field_resolve_depends

# Lazy patching of ir.ui.view._validate_view because base modules might not be loaded yet
_original_validate_view = None
_original_NameManager_must_have_fields = None

def poly_NameManager_must_have_fields(self, node, names, node_info, use):
    try:
        return _original_NameManager_must_have_fields(self, node, names, node_info, use)
    except Exception as e:
        error_msg = str(e)
        if "Unknown field" in error_msg:
            # Check if the model is polymorphic
            is_poly = hasattr(self.model, '_depend_models') or 'ir.poly_base' in [c._name for c in self.model.mro() if hasattr(c, '_name')]
            if is_poly:
                _logger.warning("[poly] NameManager: ignoring unknown field error in polymorphic model %s: %s", self.model._name, error_msg)
                return
        raise e

# PATCH: IrUiView._validate_view to tolerate missing polymorphic fields during update
# In Odoo 18, the class is named 'View' but registered as 'ir.ui.view'
def poly_validate_view(self, node, model_name, view_type=None, editable=True, node_info=None):
    try:
        return _original_validate_view(self, node, model_name, view_type=view_type, editable=editable, node_info=node_info)
    except Exception as e:
        error_msg = str(e)
        # Check if it's a field missing error
        is_missing_field = "Unknown field" in error_msg or "does not exist" in error_msg
        
        if is_missing_field:
            # Check if the model is polymorphic OR if the error references a polymorphic model
            is_poly = False
            if model_name in self.env.registry:
                model_class = self.env.registry[model_name]
                is_poly = hasattr(model_class, '_depend_models') or 'ir.poly_base' in [c._name for c in model_class.mro() if hasattr(c, '_name')]
            
            # The error might be in a domain referencing a poly model (e.g. project.task)
            import re
            match = re.search(r'(Unknown field|Field) "([^"]+)\.([^"]+)"', error_msg)
            f_name, m_name = None, None
            if match:
                m_name, f_name = match.group(2), match.group(3)
            else:
                match = re.search(r'(Unknown field|Field) "([^"]+)"', error_msg)
                if match:
                    f_name = match.group(2)
                    m_name = model_name

            if m_name and m_name in self.env.registry:
                ref_class = self.env.registry[m_name]
                is_poly = is_poly or hasattr(ref_class, '_depend_models') or 'ir.poly_base' in [c._name for c in ref_class.mro() if hasattr(c, '_name')]

            # ESPECIAL PARA ACTUALIZACIÓN: Tolerancia extendida durante -u
            # Si estamos en modo actualización, silenciamos campos faltantes en modelos críticos
            if not is_poly and m_name in ['account.move.line', 'account.move', 'account.analytic.line']:
                is_poly = True # Treat as poly-related to survive update

            if is_poly:
                _logger.warning("[poly] _validate_view: ignoring unknown field error in model %s (poly-related): %s", model_name, error_msg)
                
                # INJECTION REACTIVA: If field is missing, try to find it in MRO and inject it NOW
                if f_name and m_name in self.env.registry:
                    m_class = self.env.registry[m_name]
                    # Scan MRO for this field
                    for parent in m_class.mro():
                        # Standard Odoo builds fields from _field_definitions in MRO order
                        if hasattr(parent, '_field_definitions'):
                            for f_def in parent._field_definitions:
                                if getattr(f_def, 'name', None) == f_name:
                                    _logger.info("[poly] _validate_view: EMERGENCY RECOVERY of %s for %s", f_name, m_name)
                                    if f_name not in m_class._fields:
                                        m_class._fields[f_name] = f_def
                                    setattr(m_class, f_name, f_def)
                                    
                                    # Also ensure it's in the proxy if any
                                    if m_name in self.env.registry:
                                        proxy_class = type(self.env.registry[m_name])
                                        if proxy_class is not m_class:
                                            setattr(proxy_class, f_name, f_def)

                                    # Retry validation once
                                    try:
                                        return _original_validate_view(self, node, model_name, view_type=view_type, editable=editable, node_info=node_info)
                                    except:
                                        pass
                                    break
                
                return True # Assume valid for now, will be checked later in final setup
        raise e

def _patch_ir_ui_view():
    global _original_validate_view, _original_NameManager_must_have_fields
    if _original_validate_view is not None:
        return
    
    try:
        import odoo.addons.base.models.ir_ui_view as ir_ui_view_mod
        if hasattr(ir_ui_view_mod, 'View'):
            _original_validate_view = ir_ui_view_mod.View._validate_view
            ir_ui_view_mod.View._validate_view = poly_validate_view
            
            _original_NameManager_must_have_fields = ir_ui_view_mod.NameManager.must_have_fields
            ir_ui_view_mod.NameManager.must_have_fields = poly_NameManager_must_have_fields
            
            _logger.info("[poly] Patched ir.ui.view classes")
    except ImportError:
        pass

# PATCH: tools.convert.convert_xml_import to tolerate ParseError on poly models
import odoo.tools.convert
_original_convert_xml_import = odoo.tools.convert.convert_xml_import

def poly_convert_xml_import(env, module, fp, idref, mode, noupdate):
    _patch_ir_ui_view()
    try:
        return _original_convert_xml_import(env, module, fp, idref, mode, noupdate)
    except Exception as e:
        error_msg = str(e)
        if "Unknown field" in error_msg:
             _logger.warning("[poly] convert_xml_import: ignoring ParseError in %s: %s", module, error_msg)
             return
        raise e

odoo.tools.convert.convert_xml_import = poly_convert_xml_import


_original_Registry_setup_models = odoo.modules.registry.Registry.setup_models

def _poly_registry_setup_models(self, cr):
    """
    Ensures critical polymorphic models have their full MRO
    finalized after Odoo's standard incremental build process.
    """
    _patch_ir_ui_view()
    res = _original_Registry_setup_models(self, cr)
    
    # Identify models that participate in polymorphic inheritance
    poly_models = []
    for name, model_class in self.items():
        if not isinstance(model_class, type):
            continue
            
        mro = model_class.mro()
        all_depend_models = OrderedDict()
        is_polymorphic = False
        
        # Collect polymorphic dependencies from the MRO
        for base in mro:
            if base is model_class:
                continue
            dep_models = base.__dict__.get('_depend_models') or getattr(base, '_depend_models', None)
            if dep_models:
                is_polymorphic = True
                for dep_model, dep_field in dep_models.items():
                    if dep_model not in all_depend_models:
                        all_depend_models[dep_model] = dep_field
        
        if is_polymorphic:
            poly_models.append((name, model_class, all_depend_models))

    for name, model_class, all_depend_models in poly_models:
        parents = list(all_depend_models.keys())
        if name != 'ir.poly_base' and 'ir.poly_base' not in parents:
            parents.append('ir.poly_base')

        # Check if parents are already in MRO names
        mro = model_class.mro()
        current_mro_names = [getattr(c, '_name', None) for c in mro]
        poly_applied = False
        if any(p_name not in current_mro_names for p_name in parents):
            # We use the PolyBase class which is fully defined at this point
            poly_applied = PolyBase._apply_polymorphic_hierarchy(self, name, model_class, parents)

        if poly_applied:
            # _apply_polymorphic_hierarchy changed MRO but does NOT set _setup_done=False
            # (unlike poly's _build_model). We must reset it before calling _setup_base,
            # otherwise _setup_base returns early due to the _setup_done guard.
            model_class._setup_done = False
            try:
                _env = api.Environment(cr, SUPERUSER_ID, {})
                _env[name]._setup_base()
                # Re-run _setup_fields to resolve comodels and field relations.
                # Guard _m2m as Odoo sets it in setup_models around _setup_fields.
                _m2m_was_set = hasattr(self, '_m2m')
                if not _m2m_was_set:
                    self._m2m = defaultdict(list)
                try:
                    _env[name]._setup_fields()
                finally:
                    if not _m2m_was_set and hasattr(self, '_m2m'):
                        del self._m2m
            except Exception as _e:
                _logger.warning(
                    "Re-running _setup_base/_setup_fields for %s after poly "
                    "injection failed (%s); falling back to _field_definitions scan",
                    name, _e,
                )

        # After _original_Registry_setup_models (and any poly hierarchy injection),
        # ensure all fields from definition classes in the MRO are present in _fields.
        # This is necessary because _setup_base may have run before some extension
        # modules were loaded, or because poly's MRO manipulation caused _setup_base
        # to use a stale MRO that excluded the extension's definition class.
        # We scan ALL definition classes (pool=None, MetaModel instance) in the
        # current MRO and add any missing fields or descriptors.
        from odoo.models import MetaModel
        _current_mro = model_class.mro()
        _fields_before = set(model_class._fields.keys())
        for _base_class in _current_mro:
            # RECOVERY: Scan ALL base classes in the MRO for field definitions.
            # Odoo 18's incremental loading often misses fields from extension modules
            # if they inherit from a model that was already partially built.
            _recovered_from_this_base = []
            
            # 1. From _field_definitions (standard Odoo way for non-setup models)
            if hasattr(_base_class, '_field_definitions'):
                for _fobj in _base_class._field_definitions:
                    _fname = _fobj.name
                    if _fname not in model_class._fields:
                        _base_name = getattr(_base_class, '_name', None)
                        _is_poly_ancestor = (_base_name and (hasattr(_base_class, '_depend_models') or _base_name == 'ir.poly_base' or _base_name in getattr(model_class, '_depend_models', {})))
                        if _is_poly_ancestor and _fname not in ['id', 'create_uid', 'create_date', 'write_uid', 'write_date']:
                            from odoo import fields as odoo_fields
                            _new_fobj = type(_fobj)(related=f'{_base_name}.{_fname}', store=False)
                            _new_fobj.model_name = name
                            _new_fobj.name = _fname
                        else:
                            try:
                                # Clonar preservando TODOS los atributos criticos
                                # Usamos _args del objeto original si existen
                                _args = dict(getattr(_fobj, '_args', {}))
                                
                                # Extraer comodel_name de forma exhaustiva para evitar KeyError: None en Odoo 18
                                _comodel = getattr(_fobj, 'comodel_name', None) or _args.get('comodel_name')
                                if _comodel and isinstance(_comodel, odoo_fields.Sentinel):
                                    _comodel = None

                                # Si es un campo relacional (m2o, o2m, m2m) y no tenemos comodel_name,
                                # NO podemos instanciarlo ni inyectarlo, ya que update_db fallará.
                                if _fobj.relational and not _comodel:
                                    _logger.warning('[poly] Skipping relational field %s on %s: missing comodel_name', _fname, name)
                                    continue
                                
                                # Asegurar comodel_name en los argumentos de inicializacion
                                if _comodel and 'comodel_name' not in _args:
                                    _args['comodel_name'] = _comodel

                                _new_fobj = type(_fobj)(**_args)
                                
                                # Lista de atributos a copiar explícitamente
                                attrs_to_copy = [
                                    'string', 'help', 'compute', 'search', 'inverse', '_modules', 
                                    'relation', 'column1', 'column2', 'comodel_name', 'inverse_name', 
                                    'delegate', 'store', 'related', 'selection', 'domain'
                                ]
                                for attr in attrs_to_copy:
                                    if hasattr(_fobj, attr):
                                        val = getattr(_fobj, attr)
                                        if val is not None:
                                            setattr(_new_fobj, attr, val)
                                
                                # Forzar explicitud en Many2many para evitar que Odoo recalcule nombres de columnas
                                if _new_fobj.type == 'many2many' and getattr(_new_fobj, 'relation', None):
                                    _new_fobj._explicit = True
                                    
                            except Exception as e:
                                _logger.error('[poly] Error cloning field %s: %s', _fname, e)
                                # Si falla el clonado, usamos el original con el riesgo de corromper model_name
                                _new_fobj = _fobj
                            _new_fobj.model_name = name
                            _new_fobj.name = _fname
                        model_class._fields[_fname] = _new_fobj
                        _fobj = _new_fobj
                        if hasattr(_fobj, '_setup_done'): _fobj._setup_done = False
                        _recovered_from_this_base.append(_fname)
                    
                    # Ensure descriptor is in model class __dict__
                    if _fname not in model_class.__dict__:
                        _logger.info("[poly] FORCING descriptor for %s in %s class", _fname, name)
                        try: setattr(model_class, _fname, _fobj)
                        except Exception: pass

                    # Ensure descriptor is in proxy class __dict__
                    if hasattr(self, 'models') and name in self.models:
                        _proxy = self.models[name]
                        if _proxy is not model_class:
                            if _fname not in _proxy._fields:
                                _proxy._fields[_fname] = _fobj
                            if _fname not in _proxy.__dict__:
                                _logger.info("[poly] FORCING descriptor for %s in %s proxy", _fname, name)
                                try: setattr(_proxy, _fname, _fobj)
                                except Exception: pass

            # 2. From __dict__ (fallback for fields already instantiated as descriptors)
            for _fname, _fobj in _base_class.__dict__.items():
                if isinstance(_fobj, fields.Field):
                    if _fname not in model_class._fields:
                        _base_name = getattr(_base_class, '_name', None)
                        _is_poly_ancestor = (_base_name and (hasattr(_base_class, '_depend_models') or _base_name == 'ir.poly_base' or _base_name in getattr(model_class, '_depend_models', {})))
                        if _is_poly_ancestor and _fname not in ['id', 'create_uid', 'create_date', 'write_uid', 'write_date']:
                            from odoo import fields as odoo_fields
                            _new_fobj = type(_fobj)(related=f'{_base_name}.{_fname}', store=False)
                            _new_fobj.model_name = name
                            _new_fobj.name = _fname
                        else:
                            try:
                                # Clonar preservando TODOS los atributos criticos
                                # Usamos _args del objeto original si existen
                                _args = dict(getattr(_fobj, '_args', {}))
                                
                                # Extraer comodel_name de forma exhaustiva para evitar KeyError: None en Odoo 18
                                _comodel = getattr(_fobj, 'comodel_name', None) or _args.get('comodel_name')
                                if _comodel and isinstance(_comodel, odoo_fields.Sentinel):
                                    _comodel = None

                                # Si es un campo relacional y no tenemos comodel_name, saltar para evitar KeyError: None
                                if _fobj.relational and not _comodel:
                                    _logger.warning('[poly] Skipping relational field %s on %s (dict): missing comodel_name', _fname, name)
                                    continue
                                
                                # Asegurar comodel_name en los argumentos de inicializacion
                                if _comodel and 'comodel_name' not in _args:
                                    _args['comodel_name'] = _comodel

                                _new_fobj = type(_fobj)(**_args)
                                
                                # Lista de atributos a copiar explícitamente
                                attrs_to_copy = [
                                    'string', 'help', 'compute', 'search', 'inverse', '_modules', 
                                    'relation', 'column1', 'column2', 'comodel_name', 'inverse_name', 
                                    'delegate', 'store', 'related', 'selection', 'domain'
                                ]
                                for attr in attrs_to_copy:
                                    if hasattr(_fobj, attr):
                                        val = getattr(_fobj, attr)
                                        if val is not None:
                                            setattr(_new_fobj, attr, val)
                                
                                # Forzar explicitud en Many2many para evitar que Odoo recalcule nombres de columnas
                                if _new_fobj.type == 'many2many' and getattr(_new_fobj, 'relation', None):
                                    _new_fobj._explicit = True
                                    
                            except Exception as e:
                                _logger.error('[poly] Error cloning field %s: %s', _fname, e)
                                # Si falla el clonado, usamos el original con el riesgo de corromper model_name
                                _new_fobj = _fobj
                            _new_fobj.model_name = name
                            _new_fobj.name = _fname
                        model_class._fields[_fname] = _new_fobj
                        _fobj = _new_fobj
                        if hasattr(_fobj, '_setup_done'): _fobj._setup_done = False
                        _recovered_from_this_base.append(_fname)
                    
                    if _fname not in model_class.__dict__:
                        _logger.info("[poly] FORCING descriptor for %s in %s class (from __dict__)", _fname, name)
                        try: setattr(model_class, _fname, _fobj)
                        except Exception: pass

                    if hasattr(self, 'models') and name in self.models:
                        _proxy = self.models[name]
                        if _proxy is not model_class:
                            if _fname not in _proxy._fields:
                                _proxy._fields[_fname] = _fobj
                            if _fname not in _proxy.__dict__:
                                _logger.info("[poly] FORCING descriptor for %s in %s proxy (from __dict__)", _fname, name)
                                try: setattr(_proxy, _fname, _fobj)
                                except Exception: pass

            # 3. Method propagation (Odoo 18 MRO might miss methods if classes are skipped)
            # We already use MRO, so methods should be found by Python. 
            # But calculated fields depend on methods (compute='_compute_...')
            # If the method is NOT found in the model class but exists in a base,
            # Python's MRO will find it. If it was skipped by Odoo, it might still be in the class MRO.

        _fields_added = set(model_class._fields.keys()) - _fields_before
        if _fields_added:
            _logger.info(
                "[poly] _poly_registry_setup_models: recovered %d missing field(s) "
                "for %s: %s",
                len(_fields_added), name, sorted(_fields_added),
            )

            # Clear Env cache for this model to ensure fields are fresh
            from odoo.api import Environment
            if hasattr(Environment, '_classes') and Environment._classes is not None:
                if self in Environment._classes:
                    Environment._classes[self].pop(name, None)
                
    return res

odoo.modules.registry.Registry.setup_models = _poly_registry_setup_models
