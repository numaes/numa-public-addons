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

3. Deferred View Validation:
   Odoo 18 validates views (`_validate_view`) immediately after XML record loading,
   often before the final MRO has been synchronized across all models. This leads
   to "Unknown field" or "Method not found" errors for buttons or actions referencing
   polymorphic logic.
   To survive the `-u` (update) process, validation is deferred, never skipped:
   - While modules load, every view that reaches `_validate_view` is recorded and passes.
   - Once every module is loaded (`ir.poly_base._register_hook`, which Odoo calls exactly once
     per model at the end of loading), every recorded view is validated against the complete
     registry (`_poly_finalize_view_validation`) and all failures are reported.
   - A failure aborts loading when `poly_strict_view_validation` is on (the default under
     `--test-enable`); otherwise it is logged as an error.
   Until 2026-09 no deferred view was ever validated: only `noupdate` views were recorded, and
   even those were lost. The pending set was a lazy_property, first stored under a name other than
   the one read and then wiped by every Registry.setup_models (lazy_property.reset_all); and the
   final validation hung from a load_module_graph wrapper that never applies to the load in
   progress.
   See doc/TRANSPARENCY.md, which also covers which patches reach models outside every
   polymorphic hierarchy.

4. Cache and Proxy Synchronization:
   Modern Odoo uses internal caches (like `Environment._classes` and Proxy classes)
   that may hold stale versions of model definitions. `numa_poly` forcefully clears
   these caches and synchronizes Proxy `__bases__` to ensure that Python's attribute
   lookup reflects the injected polymorphic hierarchy.
"""

import copy
import functools
import logging
import ctypes
import warnings
from collections import OrderedDict, defaultdict
import typing
import json
import time

import psycopg2
from psycopg2.extras import Json as PsycopgJson

# Odoo imports
import odoo
# [poly][20.0] `odoo` is a namespace package: importing it no longer pulls in the
# submodules, so the ones used by full path are declared here.
import odoo.fields
import odoo.models
import odoo.modules.loading
import odoo.modules.registry
from odoo import api, models, fields, _, Command
from odoo import SUPERUSER_ID
from odoo.models import BaseModel, LOG_ACCESS_COLUMNS
from odoo.orm.models import INSERT_BATCH_SIZE, UPDATE_BATCH_SIZE
from odoo.orm import model_classes as _poly_model_classes
from odoo.orm.fields_relational import _Relational
from odoo.orm.query import Query
from odoo.tools.constants import GC_UNLINK_LIMIT
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
from odoo.fields import Domain
from odoo.tools import OrderedSet, split_every, SQL, sql
from odoo.tools.misc import LastOrderedSet, Sentinel, SENTINEL
from typing import Self

from odoo.api import ValuesType, IdType
from collections import deque

# Local imports
# Type checking imports
if typing.TYPE_CHECKING:
    from collections.abc import Reversible
    from odoo.modules.registry import Registry


_logger = logging.getLogger(__name__)


# Context marker for the creates that poly ITSELF makes on another model of the hierarchy
# (dispatch to the concrete model, sub-create of the bases). Only those vals can carry a value that
# was valid on the source model and is not on the target -the case that motivated the Selection
# filtering-, and only there is discarding it the right thing. A create asked directly by a caller
# has to fail as in standard Odoo: discarding the value silently loses the data and hides the bug.
POLY_PROPAGATED = 'poly_propagated_vals'


def poly_vals_propagados(env):
    """Were these vals propagated by poly from another model, instead of asked by the caller?"""
    return bool(env.context.get(POLY_PROPAGATED))


def poly_selection_value_is_valid(field, value):
    """
    Whether `value` is acceptable for a Selection-like field on this model.

    `fields.Reference` subclasses `fields.Selection`, but its stored value is
    ``"model,id"`` while its selection keys are bare model names. Comparing the two
    directly rejects every well-formed reference, so a Reference is validated on its
    model part alone. A selection that is built at runtime -a callable, or the name
    of a method- is let through: there is nothing to compare it against.

    [poly][20.0] This used to demand ``isinstance(selection, list)``, and in Odoo 20
    ``field.selection`` is a TUPLE of tuples. With that condition the filter took
    every value of every Selection field as valid and never filtered: exactly the
    silent failure this function exists to prevent.
    """
    selection = field.selection
    if callable(selection) or isinstance(selection, str):
        return True
    try:
        valid_keys = {entry[0] for entry in selection}
    except TypeError:
        return True
    if not valid_keys:
        return True
    if isinstance(field, fields.Reference):
        if not isinstance(value, str) or ',' not in value:
            return False
        return value.split(',', 1)[0] in valid_keys
    return value in valid_keys


class _PolyRelatedFieldNoiseFilter(logging.Filter):
    """Silences BENIGN warnings that numa_poly's related-field injection produces inherently and
    massively, cluttering the log.

    A poly subtype inherits its base's field definitions through the MRO (Selection with
    `selection`, fields with `default`), and numa_poly overlays a `related` version. Odoo then warns
    that selection/selection_add/default are ignored on the related field - correct and expected
    (the value comes from the source), but emitted once per field/model (dozens of lines). It cannot
    be avoided at the source without breaking poly inheritance (the warning looks at `_base_fields`,
    the base's definition in the MRO). ONLY these 3 `odoo.fields` messages are filtered."""

    _NOISE = (
        'selection attribute will be ignored as the field is related',
        'selection_add attribute will be ignored as the field is related',
        'Redundant default on',
    )

    def filter(self, record):  # noqa: A003
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        return not any(n in msg for n in self._NOISE)


# Installed once at import level (active during setup_models, which is when they are emitted).
logging.getLogger('odoo.fields').addFilter(_PolyRelatedFieldNoiseFilter())

# Sequence synchronisation cache, per registry instance.
# id(registry) changes on every reload, so the cache is invalidated
# automatically when installing/updating modules or restarting the server.
_poly_sequence_synced_registries: set = set()
_poly_table_sequence_synced: set = set()


# [poly] Per-table physical-column cache (no-migration strategy): used to decide
# whether a field is the concrete model's OWN column and must therefore never be
# shadowed by a related-to-base version. Stable within a process after install.
_POLY_LEAF_COLUMNS = {}

# Native-field-names cache keyed by model name (NOT stored as a class attribute, which
# Odoo's test framework flags as an "unexpected attribute" leak). Cleared on every
# registry rebuild together with the schema caches.
_POLY_NATIVE_FNAMES = {}

# Models whose reconstruction is over, keyed by (registry id, model name). From then on
# `create` keeps every record complete, so the safety net that materialises missing base
# rows on write has nothing to do and must cost nothing to skip. Answered from the
# backfill pairs the first time and remembered for the life of the registry.
_POLY_TRANSITION_FINISHED: set = set()

# Which concrete models sit on a given base, and which many2one fields of a model point
# at such a base. Both derive from the schema alone, so they are computed once per
# registry; they exist so that a model with no such field pays a dict lookup and nothing
# more on every create and write.
_POLY_SUBTYPES: dict = {}
_POLY_BASE_REFERENCE_FIELDS: dict = {}

# How costly it is to renumber a model, so that when two legacy tables hold the same id
# the one half the database points at is not the one that moves. See
# PolyBase._poly_renumber_rank.
_POLY_RENUMBER_RANK: dict = {}

# The polymorphic chain above a model, and the concrete models whose base rows a model
# may use. Both walk the dependency graph, both are asked on the write path by the
# ownership probe, and both are fixed once the registry is built.
_POLY_ANCESTORS: dict = {}
_POLY_ACCEPTABLE_OWNERS: dict = {}

# (registry, model, field) triples whose base collision has already been reported.
_POLY_REPORTED_COLLISIONS: set = set()
_POLY_REPORTED_UNOWNED_STAMPS: set = set()


def _poly_subtype_names(base_model_name, pool):
    """The polymorphic models whose chain includes ``base_model_name``.

    Empty for a model nothing sits on — which is the answer for almost every comodel,
    and the reason the reference check costs nothing in general.
    """
    if not base_model_name or base_model_name == 'ir.poly_base':
        return ()
    key = (id(pool), base_model_name)
    cached = _POLY_SUBTYPES.get(key)
    if cached is not None:
        return cached
    names = []
    for name in pool.models:
        if name == base_model_name:
            continue
        try:
            if base_model_name in _poly_ancestor_names(name, pool):
                names.append(name)
        except Exception:  # noqa: BLE001 — an unbuilt class must not break the scan
            continue
    cached = tuple(sorted(names))
    _POLY_SUBTYPES[key] = cached
    return cached


def _poly_sql_param(value):
    """
    Make `value` something psycopg2 can send as an INSERT parameter.

    A jsonb column reads back as a plain ``dict``/``list``, and psycopg2 has no adapter
    for either on the way in: copying such a column straight from a concrete row to its
    base row fails with "can't adapt type 'dict'". Values already converted by the ORM
    (``convert_to_column_insert`` hands back a ``Json`` wrapper) pass through untouched.
    """
    if isinstance(value, (dict, list)):
        return PsycopgJson(value)
    return value


def _poly_force_related(field, related_path):
    """
    Make `field` a non-stored related field, and make it stay one.

    Odoo rebuilds every field attribute from the declaration dict (`_args__`)
    each time it sets a field up, so assigning `store`/`compute` on the object
    holds only until the next `_setup_attrs`. It held for a base field declared
    plainly -- nothing in its declaration mentions `store`, and `_get_attrs`
    defaults a related field to `store=False` -- and did not hold for one
    declared `compute=..., store=True`, whose values came straight back. The
    concrete model then kept a physical column for a value that lives on the
    base, with the base's compute method attached to it, and which answer you
    got depended on whether that pass happened to re-run: it does during an
    upgrade and does not on a cold registry load.

    Saying it in the declaration is what makes the result the same however many
    times Odoo sets the field up. The dict is replaced rather than mutated:
    `copy.copy` on a field shares it with the original, and a field reached
    through the MRO *is* the base model's own, which must not be rewritten.
    """
    args = getattr(field, '_args__', None)
    if args:
        # Odoo frees `_args__` once a top-level field is set up, and a field whose
        # declaration is gone is never rebuilt from it -- that is why assigning
        # `store` on the object was enough for the fields copied out of an
        # already-set-up base. Where the declaration is still live, which is the
        # case for the fields Odoo builds for the concrete class through the MRO,
        # it has the last word and has to be told.
        #
        # `store` and `precompute`, and nothing else. `related` itself must stay
        # out: declaring it switches on `_get_attrs`'s related branch, which forces
        # `readonly=True`, and a readonly related field gets no `_inverse_related`
        # -- writes to it are then accepted and discarded, which is the failure this
        # whole module exists to prevent. `compute`, `inverse` and `search` stay out
        # for the same reason: they belong to `setup_related`, which installs them
        # every time it runs, and a later `_setup_attrs` would null them again.
        #
        # `precompute` rides along because it only ever means something on a stored
        # field, and the declaration we are copying may well carry it: the field
        # this runs on is frequently a stored compute -- `res.partner.user_id` is
        # declared `compute=..., store=True, precompute=True`. Turning `store` off
        # while leaving `precompute` on leaves a combination Odoo does not accept,
        # and it says so with a `UserWarning` for every concrete model in the
        # hierarchy on every registry load. It is only noise, but it is noise that
        # scrolls a real problem off the screen. Unlike the attributes above, this
        # one has no behaviour attached to it once `store` is False, so declaring
        # it costs nothing.
        args = dict(args)
        args['store'] = False
        args['precompute'] = False
        field._args__ = args
        field.args = args  # Odoo keeps `args` as an alias of `_args__`
    field.related = related_path
    field.store = False
    field.precompute = False
    field.compute = None
    field.compute_sudo = None
    field.inverse = None
    field.search = None
    return field


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
# [poly][20.0] _inherits_check stopped being a method of BaseModel: it is now the
# function _check_inherits(model_cls) of odoo.orm.model_classes, which moreover only
# validates and no longer repairs (model_classes.py:497-510). The body below still
# repairs, and writes into cls._fields, which in 20.0 is a read-only MappingProxyType
# (model_classes.py:204). Phase 3 of the redesign replaces it; see
# doc/plan-2026-09-20-odoo-20-redesign.md section 2.1.
_original_inherits_check = _poly_model_classes._check_inherits
def poly_inherits_check(cls):
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
            elif _poly_hierarchy_names(cls):
                # Polymorphic model without the link yet: _build_poly_fields injects it later.
                del cls._inherits[parent_model]
            else:
                # Common model with the link field undeclared. Odoo 18 does not create it by
                # itself: its _add_field rejects fields absent from the Python class, and the
                # startup would fall over. The delegation is dropped so that it loads, but it is
                # reported: the model is left without the parent's fields. It used to happen in
                # silence (that is how alfy.reuters.chat broke).
                _logger.warning(
                    "[poly] %s: dropping the _inherits towards %s because the link field '%s' is "
                    "not declared in the class (Odoo 18 requires declaring it); the model is left "
                    "without the fields of %s.", cls._name, parent_model, field_name, parent_model)
                del cls._inherits[parent_model]
                
    return _original_inherits_check(cls)
_poly_model_classes._check_inherits = poly_inherits_check

# [poly] Views recorded during the load, to validate them when it finishes.
def _pending_poly_views(self):
    """Ids of the views whose validation was deferred during the registry load.

    It is a plain registry attribute and, on purpose, NOT a lazy_property. With lazy_property there
    were two defects: the function was named differently from the attribute (lazy_property stores
    the value under fget.__name__), so every read created a new set; and even with the right name,
    Registry.setup_models calls lazy_property.reset_all(), which wipes every lazy_property, and
    during a -u there is one setup_models per updated module. Only what was recorded after the
    last one survived: 1 view out of hundreds in an update of 36 modules.
    """
    pending = self.__dict__.get('_poly_pending_view_ids')
    if pending is None:
        pending = self.__dict__['_poly_pending_view_ids'] = set()
    return pending

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


# Keys the polymorphic create handles itself, which are not fields of the model.
_POLY_CREATE_TECHNICAL_KEYS = frozenset({'id', 'concrete_model_id', 'poly_payload'})


def _poly_is_polymorphic(model):
    """
    Determine whether a model is polymorphic by analysing its MRO chain and the presence of _depend_models.
    A model is polymorphic if it, or any of its bases (WITH THE SAME _name), has _depend_models.
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


def _poly_registry_hierarchy_models(registry):
    """Models that take part in some polymorphic hierarchy: those that declare
    ``_depend_models`` (``{}`` a base, a dict of parents a subtype) and every model named as a
    parent in any of those declarations.

    The criterion is the VALUE, never the presence of the attribute: ``PolyBase`` declares
    ``_depend_models = None`` and is in the MRO of every model, so
    ``'_depend_models' in base.__dict__`` is true for the 839 models of a real installation,
    not for the ~40 polymorphic ones.
    """
    names = set()
    for name in list(registry):
        try:
            cls = registry[name]
        except KeyError:
            continue
        for base in _poly_get_safe_mro(cls):
            declared = base.__dict__.get('_depend_models')
            if declared is None:
                continue
            names.add(name)
            if isinstance(declared, dict):
                names.update(declared)
    return frozenset(names)


def _poly_is_outside_hierarchy(records):
    """True only when it is CERTAIN that ``records`` belongs to a model outside every poly
    hierarchy, and can therefore be served by Odoo's original path.

    The certainty demands a registry that finished loading (``ready``) and the hierarchy map built
    at the end of the last ``setup_models``. While the registry is being assembled, poly rewrites
    bases and fields of many classes and the tolerant path is needed by all of them: during the
    setup this answers False and nothing changes with respect to before.
    """
    pool = getattr(records, 'pool', None)
    if pool is None or not getattr(pool, 'ready', False):
        return False
    names = getattr(pool, '_poly_hierarchy_model_names', None)
    if names is None:
        return False
    return getattr(records, '_name', None) not in names


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
    """Register *field* as *fname* on the model class *cls*.

    It goes through ``add_field`` instead of writing ``cls._fields``, which in
    Odoo 20 is a read-only ``MappingProxyType`` over ``_fields__``
    (``model_classes.py:204``). ``add_field`` also runs ``__set_name__``, which
    is what resolves ``comodel_name`` and the rest of ``_args__``; before, a
    loose call to ``_setup_attrs`` did that, wrapped in an ``except`` that
    swallowed the failure.

    It is registered with ``shareable=False``: the field belongs to this registry
    and to nobody else, so it does not enter ``SHARED_FIELD_CACHE`` and mutating
    it does not touch the other databases served by the same worker
    (``model_classes.py:34``).
    """
    # The add_field of odoo.orm.model_classes is intercepted by this very module
    # further down; this is poly's own injection and must not re-enter that
    # logic, so it goes straight to the original.
    _original_BaseModel_add_field(cls, fname, field, shareable=False)


# [poly] Track processed models for incremental Deep Fix
@functools.cached_property
def _poly_processed_models(self):
    """ {model_name: set(module_names)} """
    return defaultdict(set)

# [poly] Track injected MRO for incremental Phase 1
@functools.cached_property
def _poly_injected_mro(self):
    """ {model_name: tuple(base_classes)} """
    return {}

def _poly_strict_view_validation():
    """Does an invalid view detected at the end of the load abort the load, or is it only reported?

    The ``poly_strict_view_validation`` option of the configuration file decides. Without the
    option it is strict when tests are run (``--test-enable``) and it is not on a normal server: a
    ``-u`` on an installation with latent broken views -which used to pass unvalidated- must not
    stop starting from one day to the next, but it does have to say so; and a test run does have
    to fail.
    """
    value = odoo.tools.config.get('poly_strict_view_validation')
    if value is None or value == '':
        return bool(odoo.tools.config.get('test_enable'))
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _poly_finalize_view_validation(self, cr):
    """
    [poly] Validate, once the load is over, the views whose validation was deferred.

    While modules are being loaded the polymorphic MRO can be incomplete, so
    ``poly_validate_view`` does not validate: it records the view. Here they are all validated with
    the registry complete; a view that fails here is really broken. All are reported, not just the
    first.
    """
    if not self._pending_poly_views:
        return

    _logger.info("[poly] Validating %d deferred view(s) at the end of the load", len(self._pending_poly_views))
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    View = env['ir.ui.view']
    view_ids = sorted(self._pending_poly_views)
    # It is emptied before validating: if the validation aborts, what is pending must not
    # survive and reappear in the next load as if it were new.
    self._pending_poly_views.clear()

    failures = []
    for view_id in view_ids:
        view = View.browse(view_id).with_context(poly_final_validation=True)
        try:
            with cr.savepoint(flush=False):
                if not view.exists():
                    continue
                view._check_xml()
        except Exception as e:  # noqa: BLE001
            cr.execute("SELECT module, name FROM ir_model_data WHERE model='ir.ui.view' AND res_id=%s",
                       (view_id,))
            row = cr.fetchone()
            label = '%s.%s' % row if row else 'id %s' % view_id
            text = str(e).strip()
            reason = text.splitlines()[-1] if text else repr(e)
            failures.append((label, reason))
            _logger.error("[poly] Validation failed for view %s: %s", label, e)

    # [poly][20.0] Neither Registry.clear_caches() nor Registry.clear_cache() exists any more.
    # The ormcache is invalidated per transaction (environments.py:833), which is
    # how the core addons do it.
    env.transaction.invalidate_ormcache()

    if not failures:
        _logger.info("[poly] The %d deferred views validate.", len(view_ids))
        return

    summary = "[poly] %d invalid view(s) at the end of the load:\n%s" % (
        len(failures), '\n'.join('  - %s: %s' % f for f in failures))
    if _poly_strict_view_validation():
        raise ValidationError(summary)
    _logger.warning("%s\n(the load is not aborted: poly_strict_view_validation is off)", summary)


odoo.modules.registry.Registry._pending_poly_views = property(_pending_poly_views)
odoo.modules.registry.Registry._poly_finalize_view_validation = _poly_finalize_view_validation
# Map of the models in poly hierarchies; rebuilt at the end of every setup_models.
odoo.modules.registry.Registry._poly_hierarchy_model_names = None

# Save the original Odoo methods to avoid cyclic inheritance
_original_Field_get = odoo.fields.Field.__get__
_original_Field_set = odoo.fields.Field.__set__
_original_Relational_get = _Relational.__get__
_original_One2many_get = odoo.fields.One2many.__get__

_POLY_MISSING_BASE_WARNED = set()

# Above this many missing rows the backfill is not run during the upgrade. A table with
# millions of rows must not hold a deployment open; the work is left to the cron, which
# is batched and can be interrupted.
POLY_BACKFILL_INLINE_LIMIT = 50000
POLY_BACKFILL_LIMIT_PARAM = 'numa_poly.backfill_inline_limit'
POLY_BACKFILL_DEFERRED_PARAM = 'numa_poly.backfill_deferred_models'
POLY_RENUMBER_COLLISIONS_PARAM = 'numa_poly.renumber_collisions'

# The single id allocator of the shared space. See _poly_claim_shared_id_space.
POLY_ID_SEQUENCE = 'ir_poly_base_id_seq'


def _poly_missing_base_is_tolerable(field, record):
    """Whether a MissingError here is the absent-base-row case rather than a real one."""
    try:
        if not record._ids or len(record._ids) != 1:
            return False
        return _poly_is_polymorphic(record) or bool(record._poly_get_depend_models())
    except Exception:
        return False


def _poly_warn_missing_base_once(field, record):
    """One warning per model and field, not one per record read."""
    key = (getattr(field, 'model_name', None), getattr(field, 'name', None))
    if key in _POLY_MISSING_BASE_WARNED:
        return
    _POLY_MISSING_BASE_WARNED.add(key)
    _logger.warning(
        "[poly] %s.%s read on a record whose polymorphic base row is missing; "
        "answering with the field default. Run _poly_backfill_base_rows() on %s to "
        "give these records their rows.", key[0], key[1], key[0])


def _poly_field_default_value(field, record):
    """The field's declared default, in record form."""
    try:
        default = field.default
        value = default(record) if callable(default) else default
        return field.convert_to_record(field.convert_to_cache(value, record), record)
    except Exception:
        try:
            return field.convert_to_record(False, record)
        except Exception:
            return False


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
    except MissingError:
        # The concrete row exists but its polymorphic base row does not: a record that
        # predates the module and has not been backfilled, or one inserted by raw SQL.
        # Raising here turns every read of an untouched legacy record into a crash, so
        # answer with the field's default — and say so once, because a default that
        # nobody chose should not pass for data.
        if _poly_missing_base_is_tolerable(self, record):
            _poly_warn_missing_base_once(self, record)
            return _poly_field_default_value(self, record)
        raise
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

    # [poly] Outside every poly hierarchy and with the registry ready: Odoo's original path.
    # (The previous check looked for `_depend_models` in each base's __dict__; PolyBase declares
    # it as None and is in everyone's MRO, so it never delegated.)
    if _poly_is_outside_hierarchy(records):
        return _original_Relational_get(self, records, owner=owner)

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

    # [poly] Outside every poly hierarchy and with the registry ready: Odoo's original path.
    # (The previous check looked for `_depend_models` in each base's __dict__; PolyBase declares
    # it as None and is in everyone's MRO, so it never delegated.)
    if _poly_is_outside_hierarchy(records):
        return _original_One2many_get(self, records, owner=owner)

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
_Relational.__get__ = _poly_Relational_get
odoo.fields.One2many.__get__ = _poly_One2many_get

_original_BaseModel = odoo.models.BaseModel
_original_AbstractModel = odoo.models.AbstractModel
_original_Model = odoo.models.Model
_original_TransientModel = odoo.models.TransientModel
_original_Many2many_setup_nonrelated = odoo.fields.Many2many.setup_nonrelated
_original_Many2many_read = odoo.fields.Many2many.read

class PolyBackfillPair(models.Model):
    """
    Which (concrete model, base model) pairs have already been reconstructed.

    Reconstruction is a one-off event with a precise trigger: a module adds a base to a
    model that already holds records. That happens at the start of a project, or when a
    feature is bolted onto something already running — but for a given pair it happens
    exactly once. Every later upgrade finds those records complete, because from then on
    ``create`` maintains them.

    Recording the pair is what turns that fact into behaviour. Without it the migration
    re-scans every concrete table against every base on every upgrade, forever, paying
    the full cost of a one-off event each time. Adding a *new* base later reconstructs
    only that pair; the ones already done are not touched.
    """
    _name = 'numa.poly.backfill.pair'
    _description = 'Polymorphic Backfill State'
    _order = 'concrete_model, base_model'
    _rec_name = 'concrete_model'

    concrete_model = fields.Char('Concrete Model', required=True, index=True)
    base_model = fields.Char('Base Model', required=True, index=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('blocked', 'Blocked by ID Collisions'),
        ('done', 'Done'),
    ], string='State', default='pending', required=True, index=True)
    records_created = fields.Integer('Rows Created', default=0)
    collisions = fields.Integer(
        'ID Collisions', default=0,
        help="Rows whose id already belongs to a different concrete model. Their base "
             "row cannot be built while they keep that id; see _poly_renumber_colliding.")
    completed_on = fields.Datetime('Completed On')

    _numa_poly_backfill_pair_unique = models.Constraint(
        'unique(concrete_model, base_model)',
        "A concrete model and base pair is reconstructed once.",
    )


class PolyBackfill(models.Model):
    """
    What the migration filled in, and what it still owes.

    Deliberately a table of its own rather than flags on ``ir.poly_base``: a field there
    is injected into every concrete model of the chain, and a technical marker has no
    business appearing on ``project.task``. Keyed by (model, id) it also gives the sweep
    exactly the scope it needs — a polymorphic record has a row in every table of its
    chain, and only the concrete model knows how to finish the job.

    It doubles as the review list the migration owes a user: these records hold defaults
    derived from pre-existing data, not values anybody entered.
    """
    _name = 'numa.poly.backfill'
    _description = 'Polymorphic Backfill Ledger'
    _order = 'backfilled_on desc, id desc'
    _rec_name = 'res_model'

    res_model = fields.Char('Model', required=True, index=True)
    res_id = fields.Integer('Record ID', required=True, index=True)
    backfilled_on = fields.Datetime('Backfilled On', required=True, index=True)
    post_pending = fields.Boolean(
        'Post-Processing Pending', index=True,
        help="The rows exist but the work that needs a fully loaded registry — "
             "rebuilding links, recomputing groupings — has not run yet.")
    reviewed = fields.Boolean(
        'Reviewed',
        help="Tick once a person has confirmed the values the migration guessed.")

    _numa_poly_backfill_unique = models.Constraint(
        'unique(res_model, res_id)',
        "A record can only be backfilled once.",
    )

    def action_open_record(self):
        """Jump to the record this entry is about, to correct what was guessed."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
        }


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

    def _register_hook(self):
        """Validate the views whose validation was deferred during the load.

        Odoo calls ``_register_hook`` exactly once per model, with every module already loaded
        (loading.py, STEP 9). It is the first guaranteed point after the load. The
        ``load_module_graph`` wrapper is no good for that: numa_poly is imported INSIDE that call,
        so the invocation in progress is the original one and, in a startup or a ``-u``, the final
        validation never ran.
        """
        super()._register_hook()
        self.pool._poly_finalize_view_validation(self.env.cr)

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

    @api.model
    def _poly_collision_census(self, sample=1000):
        """
        Every polymorphic model holding records whose ids are not theirs, and what has
        them.

        The first thing to run on an unfamiliar database that behaves as though half its
        polymorphic records were not there. Each entry is
        ``{concrete_model, count, ids, claimed_by}``; ``ids`` is capped at ``sample`` so
        the report stays readable on a large table, ``count`` is not.
        """
        census = []
        for model_name in sorted(self.env.registry.models):
            model = self.env.get(model_name)
            if model is None or model_name == 'ir.poly_base':
                continue
            try:
                if not _poly_is_polymorphic(model) or not model._auto or not model._table:
                    continue
                ids = model._poly_colliding_ids()
            except Exception:  # noqa: BLE001 — one broken model must not hide the rest
                _logger.exception("[poly] collision census failed for %s", model_name)
                continue
            if not ids:
                continue
            shown = ids[:sample]
            census.append({
                'concrete_model': model_name,
                'count': len(ids),
                'ids': shown,
                'claimed_by': model._poly_id_conflicts(shown),
            })
        return census

    @api.model
    def _poly_log_collision_census(self):
        """Write the census to the log, for a deployment with no shell to hand."""
        census = self._poly_collision_census(sample=5)
        if not census:
            _logger.info("[poly] collision census: every polymorphic record owns its id.")
            return census
        for entry in census:
            examples = ', '.join(
                '%s->%s' % (i, entry['claimed_by'].get(i, '?')) for i in entry['ids'])
            _logger.warning("[poly] %s: %s record(s) cannot claim their id (%s)",
                            entry['concrete_model'], entry['count'], examples)
        return census

    @api.model
    def _poly_dependent_pairs(self):
        """Every ``(base model, dependent model)`` pair the registry declares."""
        pairs = set()
        for model_name in list(self.env.registry.models):
            model = self.env.get(model_name)
            getter = getattr(model, '_poly_get_depend_models', None)
            if model is None or not getter:
                continue
            try:
                bases = getter() or {}
            except Exception:  # noqa: BLE001 — a broken model must not stop the sweep
                _logger.exception("[poly] could not read _depend_models of %s",
                                  model_name)
                continue
            for base_name in bases:
                if base_name != model_name and base_name in self.env:
                    pairs.add((base_name, model_name))
        return sorted(pairs)

    @api.model
    def _poly_sync_dependent_field_labels(self, max_passes=5):
        """Give a dependent's cloned fields the translations of the base's.

        A dependent model gets an ``ir.model.fields`` row of its own for every
        propagated field, and a ``.po`` names only the base model's row — the
        clone is never named anywhere, so it keeps the source language for
        ever. The symptom is a form where every propagated field reads in
        English while the very same field on the base model reads in the
        user's language: it looks like a translation that will not load, and
        it is really a translation with nowhere to land.

        Only a clone still carrying the base's own source label is touched, so
        a dependent that deliberately renames or re-documents a field keeps
        what it said.

        Two shapes in the graph need care. A **diamond** — a dependent with two
        bases, as ``conversation.message`` has — would be claimed by both in
        turn, and the two would overwrite each other on every pass; the first
        base in a stable order therefore owns a name and the others skip it. A
        **chain** — a dependent that is itself a base — needs the sweep run
        again, because a pass may reach the far end before the near one; it
        converges in as many passes as the chain is deep, and stops early when
        a pass writes nothing.

        Runs from the backfill cron for the reason that cron exists: a
        registry that is finished and usable, and a mechanism that repairs
        itself without anybody remembering to run it.
        """
        bases_by_dependent = {}
        for base_name, dep_name in self._poly_dependent_pairs():
            bases_by_dependent.setdefault(dep_name, []).append(base_name)

        total = 0
        for _pass in range(max_passes):
            written = 0
            for dep_name in sorted(bases_by_dependent):
                bases = sorted(bases_by_dependent[dep_name])
                for position, base_name in enumerate(bases):
                    # Names an earlier base already owns are not this one's to
                    # give: that is what stops a diamond oscillating.
                    earlier = bases[:position]
                    written += self._poly_adopt_labels(
                        base_name, dep_name, earlier)
            total += written
            if not written:
                break
        else:
            _logger.warning(
                "[poly] field labels still changing after %s passes; the "
                "dependency graph may hold a cycle.", max_passes)

        if total:
            self.env.registry.clear_cache()
            _logger.info("[poly] adopted %s label(s) onto dependent models.",
                         total)
        return total

    @api.model
    def _poly_adopt_labels(self, base_name, dep_name, earlier_bases):
        """Copy one base's field and selection labels onto one dependent."""
        earlier = list(earlier_bases)
        written = 0

        self.env.cr.execute("""
            UPDATE ir_model_fields d
               SET field_description = b.field_description,
                   help = CASE
                       WHEN b.help IS NOT NULL
                        AND (d.help IS NULL
                             OR d.help->>'en_US' = b.help->>'en_US')
                       THEN b.help ELSE d.help END
              FROM ir_model_fields b
             WHERE b.model = %s
               AND d.model = %s
               AND d.name = b.name
               AND d.field_description->>'en_US'
                   IS NOT DISTINCT FROM b.field_description->>'en_US'
               AND d.field_description IS DISTINCT FROM b.field_description
               AND NOT EXISTS (SELECT 1 FROM ir_model_fields e
                                WHERE e.model = ANY(%s) AND e.name = d.name)
        """, (base_name, dep_name, earlier))
        written += self.env.cr.rowcount

        # A selection's option labels live in their own table and have exactly
        # the same problem: the dropdown reads in English while the base
        # model's reads in the user's language.
        self.env.cr.execute("""
            UPDATE ir_model_fields_selection ds
               SET name = bs.name
              FROM ir_model_fields_selection bs
              JOIN ir_model_fields bf ON bf.id = bs.field_id,
                   ir_model_fields df
             WHERE df.id = ds.field_id
               AND bf.model = %s
               AND df.model = %s
               AND df.name = bf.name
               AND ds.value = bs.value
               AND ds.name->>'en_US' IS NOT DISTINCT FROM bs.name->>'en_US'
               AND ds.name IS DISTINCT FROM bs.name
               AND NOT EXISTS (SELECT 1 FROM ir_model_fields e
                                WHERE e.model = ANY(%s) AND e.name = df.name)
        """, (base_name, dep_name, earlier))
        written += self.env.cr.rowcount

        return written

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


def _poly_hierarchy_names(model):
    """Names of the poly hierarchy of ``model``: the ``_name`` of its poly bases (the ones that
    declare ``_depend_models``) plus the keys of those ``_depend_models`` (the ancestors with a
    shared PK). E.g.: persona.fisica -> {'persona.fisica', 'res.partner'}."""
    names = set()
    for base in _poly_get_safe_mro(model if isinstance(model, type) else type(model)):
        if '_depend_models' in base.__dict__:
            bname = getattr(base, '_name', None)
            if bname:
                names.add(bname)
            for k in (base.__dict__.get('_depend_models') or {}):
                names.add(k)
    return names


def _poly_value_is_subtype_of_comodel(value_name, comodel_name, pool):
    """True if ``value_name`` is a poly subtype whose hierarchy includes ``comodel_name`` as an
    ancestor base (shared PK). In that case ``value.id`` is a valid id of the comodel, so assigning
    the subtype to a Many2one that points at the base is correct (same record)."""
    if value_name == comodel_name:
        return True
    model = pool.get(value_name)
    if model is None:
        return False
    return comodel_name in _poly_hierarchy_names(model)


def _poly_same_hierarchy(name_a, name_b, pool):
    """True if ``name_a`` and ``name_b`` belong to the SAME poly hierarchy (they share the PK /
    same id): one is an ancestor base of the other, or they share a common poly base. Symmetric.
    Since the id is unique across the whole hierarchy (same ir_poly_base sequence), comparing by
    id between its members is safe."""
    if name_a == name_b:
        return True
    a = pool.get(name_a)
    b = pool.get(name_b)
    if a is None or b is None:
        return False
    na = _poly_hierarchy_names(a)
    nb = _poly_hierarchy_names(b)
    return (name_b in na) or (name_a in nb) or bool(na & nb)


def _poly_ancestor_names(model_name, pool):
    """``model_name`` and every polymorphic base above it, transitively.

    A polymorphic record has one row per table of its chain, all under the same primary
    key, so its id is a valid id of every model in this set — and a base row carrying
    that id is that record's own row.

    Cached per registry: this is on the write path, through the ownership probe, and
    walking the dependency graph on every write of every polymorphic model is not
    something the answer's stability justifies.
    """
    key = (id(pool), model_name)
    cached = _POLY_ANCESTORS.get(key)
    if cached is not None:
        return cached
    seen, stack = set(), [model_name]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        cls = pool.get(name)
        if cls is None:
            continue
        try:
            stack.extend(_poly_collect_depend_models(cls).keys())
        except Exception:  # noqa: BLE001 — an unbuilt class must not break a scan
            continue
    seen.add('ir.poly_base')
    _POLY_ANCESTORS[key] = seen
    return seen


def _poly_base_row_is_usable(owner_name, model_name, pool):
    """
    True when a base row recorded as belonging to ``owner_name`` is ``model_name``'s row.

    Ownership is not equality. The leaf of a chain owns the rows of all its bases, and a
    row still labelled with one of those bases is the same record seen less specifically.
    What is *not* the same record is a second model that merely holds the same id:
    ``project.task`` and ``purchase.order.line`` both sit on ``numa.planning.node``, but
    task 5 and line 5 are two records, and reading that as ownership is the mistake that
    left 37 of 210 records without a base row on the first customer database.
    """
    if not owner_name or owner_name == model_name:
        return True
    return (model_name in _poly_ancestor_names(owner_name, pool)
            or owner_name in _poly_ancestor_names(model_name, pool))


def _poly_drop_base_declarations(field, model_class):
    """Remove the polymorphic bases' declarations from a field the concrete model owns.

    ``_base_fields`` is every declaration of the name in the MRO, and Odoo merges their
    attributes. For a field numa_poly deliberately did *not* inject — one the concrete
    model declares itself — the bases are in that MRO only because numa_poly put them
    there, so anything they contribute is an accident of the injection rather than
    something either model asked for.

    Declarations from other extensions of the *same* model are left alone: that is
    ordinary Odoo inheritance and the whole point of `_inherit`.
    """
    args = getattr(field, '_args__', None)
    if not args:
        return
    base_fields = args.get('_base_fields')
    if not base_fields or len(base_fields) < 2:
        return
    try:
        dep_names = set(_poly_collect_depend_models(model_class).keys())
    except Exception:  # noqa: BLE001 — a half-built class keeps the merge it had
        return
    if not dep_names:
        return
    own_name = getattr(model_class, '_name', None)
    kept = tuple(bf for bf in base_fields
                 if getattr(bf, 'model_name', None) not in dep_names
                 or getattr(bf, 'model_name', None) == own_name)
    if kept and len(kept) != len(base_fields):
        dropped = sorted({getattr(bf, 'model_name', '?') for bf in base_fields
                          if bf not in kept})
        _logger.debug(
            "[poly] %s.%s is declared by the model itself; not merging the declarations "
            "from %s.", own_name, getattr(field, 'name', '?'), ', '.join(dropped))
        args['_base_fields'] = kept
        field.__dict__['_base_fields'] = kept


def _poly_report_base_field_collisions(pool):
    """Log the field names that more than one base of a polymorphic model provides.

    Reported once per (registry, model, field): a registry rebuild is frequent and this
    is a modelling problem, not an event.
    """
    for model_name, model_cls in pool.items():
        try:
            dep_map = _poly_collect_depend_models(model_cls)
        except Exception:  # noqa: BLE001 — a half-built class must not break the report
            continue
        if not dep_map or len(dep_map) < 2:
            continue
        providers = {}
        for base_name in dep_map:
            base_cls = pool.get(base_name)
            if base_cls is None:
                continue
            for fname, field in getattr(base_cls, '_fields', {}).items():
                if fname in _POLY_TECHNICAL_FIELDS:
                    continue
                if getattr(field, 'related', None) or getattr(field, 'inherited', False):
                    continue
                providers.setdefault(fname, []).append(base_name)
        for fname, owners in providers.items():
            if len(owners) < 2:
                continue
            key = (id(pool), model_name, fname)
            if key in _POLY_REPORTED_COLLISIONS:
                continue
            _POLY_REPORTED_COLLISIONS.add(key)
            _logger.warning(
                "[poly] %s.%s is provided by %s bases: %s. %s wins; the others are not "
                "reachable under that name. Rename the field on the base that has no "
                "claim to it -- a model meant to be a polymorphic base should not "
                "occupy a name as common as 'state'.",
                model_name, fname, len(owners), ', '.join(owners), owners[0])


def _poly_id_owners(cr, ids):
    """``{id: concrete model name}`` for the ids that ``ir.poly_base`` already knows."""
    if not ids:
        return {}
    cr.execute(
        "SELECT b.id, m.model FROM ir_poly_base b "
        "JOIN ir_model m ON m.id = b.concrete_model_id WHERE b.id IN %s",
        (tuple(ids),))
    return dict(cr.fetchall())


_original_Many2one_convert_to_cache = odoo.fields.Many2one.convert_to_cache

def poly_many2one_convert_to_cache(self, value, record, validate=True):
    """[poly] Allows assigning to a Many2one a record of a poly SUBTYPE when the comodel is its
    ancestor base (same id through the shared PK). The core rejects ``value._name != comodel_name``
    with "Wrong value for ...", but the legitimate case is a self-referencing field of the base
    (e.g. ``res.partner.commercial_partner_id`` / ``parent_id``) that Odoo computes on a subtype
    (persona.fisica) doing ``rec.field = rec``: ``rec`` is the subtype but its id is a valid id of
    the base. We re-express the value as a recordset of the comodel and delegate to the core (which
    keeps the ``delegate``/NewId logic). The normal path (same model) is untouched."""
    if (validate and self.comodel_name and isinstance(value, BaseModel)
            and value._name != self.comodel_name and len(value) <= 1):
        try:
            if _poly_value_is_subtype_of_comodel(value._name, self.comodel_name, record.pool):
                value = record.env[self.comodel_name].browse(value._ids)
        except Exception:  # noqa: BLE001 — on any doubt, delegate to the core (which will validate)
            pass
    return _original_Many2one_convert_to_cache(self, value, record, validate=validate)


def poly_many2many_read(self, records):
    """
    Monkey-patch for Many2many.read to allow reading related many2many fields.
    In Odoo 18, Many2many.read assumes the field is always stored in a relation
    table and directly joins it. If the field is related (as often in polymorphic
    models), it should traverse the relation instead.
    """
    # [poly] Outside every poly hierarchy and with the registry ready: Odoo's original path.
    # (The previous check looked for `_depend_models` in each base's __dict__; PolyBase declares
    # it as None and is in everyone's MRO, so it never delegated.)
    if _poly_is_outside_hierarchy(records):
        return _original_Many2many_read(self, records)

    if self.related:
        return self._compute_related(records)
    
    # [poly] Technical Check: ensure comodel_name is present to avoid KeyError: None
    if not self.comodel_name:
        # [poly][20.0] It used to be `env.cache.insert_missing(records, self, ...)`. That
        # method does not exist in Odoo 20 -- the cache is manipulated from the field
        # (fields.py:1769) -- so this line would have raised AttributeError.
        return self._insert_cache(records, [()] * len(records))

    # [poly] AGGRESSIVE FIX: If the field is Many2many but has NO relation table,
    # and we are in a polymorphic model, it might be a broken field from Odoo 18
    # setup. We attempt to find the field in our polymorphic bases and use it.
    if not getattr(self, 'relation', None):
        model_class = records.pool[self.model_name]
        # The bases come from the model's own declaration. This used to read
        # `__depends_base_classes`, an attribute that is on no model in the registry --
        # its only writer sits in _legacy_setup_base_logic, which is neutralized and
        # would raise NameError if called -- so the loop never ran a single iteration.
        depend_models = model_class._poly_get_depend_models() \
            if hasattr(model_class, '_poly_get_depend_models') else {}
        for base_name, link_fname in depend_models.items():
             base_class = records.pool.get(base_name)
             if base_class is None or self.name not in getattr(base_class, '_fields', {}):
                  continue
             base_field = base_class._fields[self.name]
             if base_field.type == 'many2many' and getattr(base_field, 'relation', None):
                  _logger.debug("[poly] Redirecting M2M read for %s.%s to base %s",
                                self.model_name, self.name, base_name)
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
        
        # Only a counterpart of the SAME poly hierarchy can share the table. The previous check
        # used the presence of `_depend_models` (true for everyone because of PolyBase) and added
        # PolyBase's `base._name`, which is None, to both sets: the intersection {None} was never
        # empty and any collision was tolerated, poly or not.
        self_poly_bases = _poly_hierarchy_names(model_class)
        if self_poly_bases:
            for other in fields:
                if self.model_name != other.model_name:
                    other_model = model.pool.get(other.model_name)
                    if not other_model: continue
                    other_class = other_model if isinstance(other_model, type) else type(other_model)
                    other_poly_bases = _poly_hierarchy_names(other_class)
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
        store (bool): Always False as these references are computed, not stored
        readonly (bool): Always True as these references cannot be directly modified

    [poly][20.0] ``auto_join`` is gone: the attribute exists nowhere in the Odoo 20
    source. What decided between JOIN and subquery is now
    ``bypass_search_access`` (``fields_relational.py:38``), read by
    ``Many2one.condition_to_sql`` (``:492-509``).
    """
    store = False
    readonly = True
    compute_sudo = True

    @staticmethod
    def _poly_compute_sql(field, table):
        """The SQL expression of a PolyReference is the ``id`` column.

        Base and derived share the id, so the "foreign key" towards the base is
        the id of the record itself. Without this, Odoo rejects the field as soon
        as it appears in a domain: ``domains.py:1021`` demands ``store`` or
        ``compute_sql`` and otherwise raises "Cannot convert ... to SQL because it
        is not stored".

        With this in place, ``Many2one.condition_to_sql``
        (``fields_relational.py:484-544``) generates both forms -JOIN and
        subquery- on its own, and ``Many2one.property_to_sql`` (``:477``) makes
        the dotted paths work.
        """
        return table['id']

    @staticmethod
    def _poly_compute_reference(records):
        """The value of a PolyReference is the record itself, read by its id.

        It is the Python counterpart of ``_poly_compute_sql``, and Odoo wants both
        of them: ``compute_sql`` without ``compute`` warns "makes sense only if ...
        is a computed field" (``fields.py:471-473``). Until now the value was
        derived in the descriptor and the field declared no compute, so the SQL
        expression had nothing to be the translation of.

        Odoo calls a callable compute with the recordset and nothing else
        (``fields.py:67-85``): it does not tell it which field it is computing.
        That is why every PolyReference of the model is assigned, which is also
        what Odoo expects, because it groups fields by compute method
        (``pool.field_computed``) and the ones in a group are assigned together.
        It costs nothing: they are all worth the same.
        """
        for record in records:
            for nombre, campo in record._fields.items():
                if isinstance(campo, PolyReference):
                    record[nombre] = record.id or False

    def __init__(self, comodel_name: str | Sentinel = SENTINEL, string: str | Sentinel = SENTINEL, **kwargs):
        """
        Initialize a new PolyReference field.

        Args:
            comodel_name: The name of the model this field refers to
            string: The label of the field
            **kwargs: Additional field parameters
        """
        kwargs.setdefault('compute', PolyReference._poly_compute_reference)
        kwargs.setdefault('compute_sql', PolyReference._poly_compute_sql)
        kwargs.setdefault('compute_sudo', True)
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
            # [poly][20.0] The prefetch that travels is the SOURCE's, not the bare id.
            # _compute_related walks record by record (fields.py:760), so if every
            # target comes out with a prefetch of one id, reading an inherited
            # field over N records costs N queries: the N+1 that the test
            # test_11_performance_n_plus_one watches for. Base and derived share
            # the id space, so the source's ids are valid ids in the base and the
            # N targets are read in one go.
            return comodel(record.env, (record.id,), record._prefetch_ids or (record.id,))
        except Exception:
            try:
                return record.env[self.comodel_name].browse()
            except Exception:
                return None

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
        # [poly][20.0] In 18.0 this was an assert: the 'any' operators did not
        # reach here. In 20.0 they do (``domains.py:1052, 1070``), with the value
        # already converted into a Query (``:1064-1065``). And they are easy to
        # answer: base and derived share the id, so "the ones that satisfy X in
        # the base" are "the ones whose id is in that query".
        if operator in ('any', 'not any', 'any!', 'not any!'):
            dentro = 'not in' if operator.startswith('not') else 'in'
            return [('id', dentro, value)]

        # determine whether the related field can be null
        if isinstance(value, (list, tuple)):
            value_is_null = any(val is False or val is None for val in value)
        else:
            value_is_null = value is False or value is None

        can_be_null = (  # (..., '=', False) or (..., 'not in', [truthy vals])
            (operator not in Domain.NEGATIVE_OPERATORS and value_is_null)
            or (operator in Domain.NEGATIVE_OPERATORS and not value_is_null)
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
                    return Domain.OR([domain, [(prefix, '=', False)]])
            else:
                domain = [('id', 'in', comodel._search(make_domain(suffix, comodel)))]
                if can_be_null and field.type == 'many2one' and not field.required:
                    return Domain.OR([domain, [('id', '=', False)]])

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
        Return a set of every base model (polymorphic or not) in the hierarchy.
        This exploration is recursive and covers every loaded module, because it
        uses Odoo's registry (env).
        """
        bases = {'ir.poly_base'}
        visited = set()

        def collect(model_name):
            if model_name in visited or model_name not in self.env:
                return
            visited.add(model_name)
            bases.add(model_name)
            
            model = self.env[model_name]
            
            # Explore the polymorphic bases declared in _depend_models of any module
            depend_models = getattr(model, '_depend_models', None)
            if depend_models:
                for base_name in depend_models.keys():
                    collect(base_name)
            
            # Explore Odoo's standard inheritance (_inherit) to cover every module
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
        Compute the global maximum ID of the WHOLE polymorphic universe.

        It must not be limited to the hierarchy of ``self._name``, because the hook
        can fire from any polymorphic model and, if a subset is used, the sequence
        can fall behind other tables (e.g. ``res_partner``).
        """
        max_id = 0

        # 1) Canonical reference: ir_poly_base
        try:
            self.env.cr.execute("SELECT COALESCE(MAX(id), 0) FROM ir_poly_base")
            res = self.env.cr.fetchone()
            max_id = max(max_id, (res and res[0]) or 0)
        except Exception:
            pass

        # 2) Defence for migrations: walk every table of the polymorphic models
        # registered in the current instance, PLUS those of their bases.
        #
        # A base takes part in the hierarchy but is also a model in its own right:
        # it can have non-polymorphic records created directly, which consume ids from
        # its own sequence. Those ids become unusable for the hierarchy, so the id of a
        # polymorphic record must sit above the maximum of ALL the tables involved, not
        # only of those of the polymorphic models.
        candidate_models = {'ir.poly_base'}
        for model_name, model in self.env.registry.models.items():
            try:
                if model_name != 'ir.poly_base' and _poly_is_polymorphic(model):
                    candidate_models.add(model_name)
                    candidate_models.update(_poly_ancestor_names(model_name, self.pool))
            except Exception:
                continue

        for model_name in candidate_models:
            model = self.env.registry.models.get(model_name)
            if model is None:
                continue
            table = getattr(model, '_table', None)
            if not table or not getattr(model, '_storage', True):
                continue
            try:
                if not sql.table_exists(self.env.cr, table):
                    continue
                self.env.cr.execute(SQL(
                    "SELECT COALESCE(MAX(id), 0) FROM %s",
                    SQL.identifier(table)
                ))
                res = self.env.cr.fetchone()
                max_id = max(max_id, (res and res[0]) or 0)
            except Exception:
                continue

        return max_id

    def _sync_poly_sequence(self):
        """
        Synchronise ir_poly_base_id_seq with the real maximum ID of the hierarchy.
        It runs only once per registry instance, to avoid the contention of the
        advisory lock and the cost of scanning every table on each create().
        """
        registry_id = id(self.pool)
        if registry_id in _poly_sequence_synced_registries:
            return

        # Advisory lock based on the hash of the sequence name (1347374169).
        # It only blocks other processes trying to synchronise the same sequence.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(1347374169)")

        max_id = self._get_max_poly_id()

        # Read the current value of the sequence to avoid unnecessary setvals
        try:
            self.env.cr.execute("SELECT last_value FROM ir_poly_base_id_seq")
            res = self.env.cr.fetchone()
            current_seq_val = res[0] if res else 0
        except Exception:
            # The sequence does not exist yet, or there are access problems
            current_seq_val = 0

        if max_id > current_seq_val:
            _logger.debug("Synchronising sequence ir_poly_base_id_seq to %s to avoid collisions", max_id + 1)
            self.env.cr.execute(SQL(
                "SELECT setval('ir_poly_base_id_seq', %s, true)",
                max_id
            ))

        _poly_sequence_synced_registries.add(registry_id)

    def _sync_table_id_sequence_once(self):
        """
        Synchronise, once per registry+table, the physical ``id`` sequence of the
        current model, to avoid collisions caused by lagging sequences in
        restored/migrated databases.
        """
        table = getattr(self, '_table', None)
        if not table:
            return

        registry_key = (id(self.pool), table)
        if registry_key in _poly_table_sequence_synced:
            return

        # Per-table advisory lock, to avoid concurrent setvals.
        # hashtext() is stable within the database and enough for this use.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f'poly_table_seq:{table}'])

        if not sql.table_exists(self.env.cr, table):
            _poly_table_sequence_synced.add(registry_key)
            return

        self.env.cr.execute("SELECT pg_get_serial_sequence(%s, 'id')", [table])
        row = self.env.cr.fetchone()
        seq_name = row and row[0]
        if not seq_name:
            _poly_table_sequence_synced.add(registry_key)
            return

        if '.' in seq_name:
            seq_schema, seq_rel = seq_name.split('.', 1)
        else:
            seq_schema, seq_rel = 'public', seq_name

        self.env.cr.execute(SQL(
            "SELECT COALESCE(MAX(id), 0) FROM %s",
            SQL.identifier(table)
        ))
        res = self.env.cr.fetchone()
        max_id = (res and res[0]) or 0

        self.env.cr.execute(SQL(
            "SELECT last_value FROM %s",
            SQL.identifier(seq_schema, seq_rel)
        ))
        seq_res = self.env.cr.fetchone()
        current_seq_val = (seq_res and seq_res[0]) or 0

        if max_id > current_seq_val:
            self.env.cr.execute("SELECT setval(%s, %s, true)", [seq_name, max_id])

        _poly_table_sequence_synced.add(registry_key)

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

    # _legacy_setup_base_logic lived here: 127 lines marked "neutralized", called by
    # nothing, and broken besides -- it read a free variable `cached_bases` that the
    # function never binds, so entering it would have raised NameError. It was also
    # the only writer of __depends_base_classes and the only writer of POLY_MRO_CACHE,
    # which it wrote exclusively from inside `if cached_bases:` -- a cache that could
    # never be primed.

    def _setup_base(self):
        """Run standard Odoo field setup then inject polymorphic fields."""
        _original_BaseModel._setup_base(self)
        if _poly_is_polymorphic(type(self)):
            type(self)._build_poly_fields(calling_self=self)

    @classmethod
    def _setup_poly_fields(cls, self):
        """Deprecated: field injection is now handled in _setup_base via _build_poly_fields."""
        pass

    # ------------------------------------------------------------------
    # Backfill of pre-existing rows
    # ------------------------------------------------------------------
    def _poly_backfill_values(self, base_model_name, concrete_ids):
        """
        Extra column values for the base rows about to be created for `concrete_ids`.

        Override in a module that knows what the legacy data means. The generic
        migration can only fill declared defaults and copy same-named columns, which
        keeps a record readable but says nothing about it; a bridge knows that a task's
        ``allocated_hours`` is the planning effort and that its deadline is a scheduling
        constraint, and can carry that across instead of leaving a zero for somebody to
        find later.

        :return: ``{concrete_id: {column_name: value}}``. Columns that do not exist on
            the base table are ignored, so an override is safe across versions.
        """
        return {}

    def _poly_backfill_post(self, base_model_name, concrete_ids):
        """
        Run after the base rows for `concrete_ids` exist.

        Some of what a record gains on create is not a column: links between records,
        a computed grouping, a ledger entry. Override this to reproduce it. The base
        rows are already committed to the cursor by the time it runs, so the ORM can be
        used normally.
        """
        return None

    @api.model
    def _poly_backfill_required_fields(self, base_model_name):
        """
        ``{column: field}`` for the base columns Postgres will not accept as NULL.

        A legacy row often cannot answer one of these: the column is NOT NULL, the model
        declares no default, and the concrete row's own copy of it is empty — which is
        how a set of conversation drivers whose ``name`` had never been filled in stopped
        the reconstruction of their whole model. There is no honest value to write there,
        but the alternative to a placeholder is not a cleaner row: it is no row at all,
        and a record that stays half built for good.
        """
        base = self.env.get(base_model_name)
        if base is None or not base._table:
            return {}
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND is_nullable = 'NO'", (base._table,))
        names = {row[0] for row in self.env.cr.fetchall()}
        names -= {'id'} | set(LOG_ACCESS_COLUMNS)
        return {name: base._fields[name] for name in sorted(names)
                if name in base._fields and base._fields[name].store}

    @api.model
    def _poly_backfill_fallback_value(self, field, concrete_id):
        """A value a NOT NULL column will take when the record has none to give.

        Deliberately recognisable rather than plausible — a placeholder that reads like
        real data is worse than one that says where it came from. ``None`` for anything
        relational: a required many2one cannot be guessed, and stopping is the right
        answer there.
        """
        if field.type in ('char', 'text', 'html'):
            value = '%s,%s' % (self._name, concrete_id)
        elif field.type == 'selection':
            selection = field.selection
            if not isinstance(selection, list):
                try:
                    selection = field._description_selection(self.env)
                except Exception:  # noqa: BLE001 — an unresolvable selection has no value
                    return None
            value = selection[0][0] if selection else None
        elif field.type in ('integer', 'float', 'monetary'):
            value = 0
        elif field.type == 'boolean':
            value = False
        elif field.type == 'date':
            value = fields.Date.today()
        elif field.type == 'datetime':
            value = fields.Datetime.now()
        else:
            return None
        if value is None:
            return None
        return field.convert_to_column_insert(value, self.env[field.model_name])

    @api.model
    def _poly_backfill_columns(self, base_model_name):
        """
        Column values shared by every base row this model backfills.

        Two sources, in order: the static default declared on each stored base field,
        and — for a column the concrete table also has — the concrete row itself. The
        second is what keeps a NOT NULL column like ``name`` satisfied without inventing
        a placeholder, and it means the base row starts out agreeing with the record it
        belongs to.
        """
        base = self.env[base_model_name]
        base_columns = _poly_leaf_columns(self.env.cr, base._table)
        concrete_columns = _poly_leaf_columns(self.env.cr, self._table)

        candidates, copied = [], {}
        for fname, field in base._fields.items():
            if fname not in base_columns or fname == 'id':
                continue
            if fname in concrete_columns and fname in self._fields:
                # The concrete row already answers this one; copying it keeps a NOT NULL
                # column like `name` satisfied and starts the base row agreeing with the
                # record it belongs to.
                copied[fname] = fname
                # Fall through: still collect its default. On a legacy row the concrete
                # column is usually empty, and copying that NULL would drop the default
                # the model declares — observed on a real customer database, where every
                # migrated task ended up with no scheduling constraint instead of ASAP.
            if getattr(field, 'default', None) is not None:
                candidates.append(fname)

        # Ask the ORM for the defaults rather than reading Field.default: Odoo wraps a
        # declared default in a callable, so poking at the attribute silently produced
        # empty columns where the model says 'asap' or True.
        statics = {}
        if candidates:
            for fname, value in base.default_get(candidates).items():
                if fname not in base_columns:
                    continue
                field = base._fields.get(fname)
                if field is None or field.type in ('one2many', 'many2many'):
                    continue
                # default_get answers in the *write* format, which is not what a column
                # takes. The two differ for every field that stores something other than
                # a scalar, and a Json field is the loud case: its empty default comes
                # back as False, and Postgres refuses a boolean for a jsonb column. Use
                # the conversion create() itself uses, so translated Char (jsonb),
                # company-dependent columns and Monetary rounding are right too.
                value = field.convert_to_column_insert(value, base)
                if value is None:
                    continue
                statics[fname] = value
        return statics, copied

    @api.model
    def _poly_backfill_base_rows(self, batch_size=1000, limit=None, only_ids=None):
        """
        Give every pre-existing row of this model the polymorphic rows it is missing.

        Installing a polymorphic module on a database that already holds records leaves
        those records without their base rows. The symptom people notice is a
        MissingError on read, but the two quiet failures matter more: a search on a base
        field silently returns nothing, and a write to one is accepted and discarded.
        Neither announces itself, so the only safe transition is to make the missing rows
        exist.

        Idempotent by construction — it only ever inserts ids the base table does not
        have — so it is safe to re-run, and safe to interrupt.

        A row whose id already belongs to a *different* concrete model is left alone and
        counted instead: its base row cannot be built while it keeps that id, and
        overwriting the row that is there would take the other record's identity away.
        The pair then stays open, so the next run tries again — after
        ``_poly_renumber_colliding`` has moved those rows out of the way.

        :return: ``{base_model_name: rows_created}``
        """
        created = {}
        if not self._auto or not self._table:
            return created

        chain = self._poly_chain_bases()

        # A record whose id belongs to somebody else cannot be reconstructed in place.
        # Move it out of the way first, so the pass below has nothing left to skip.
        # Only during a migration: renumbering a record while a caller is holding it
        # would pull the id out from under them, which is why a targeted repair raises
        # instead (see _poly_ensure_base_rows).
        if only_ids is None and self._poly_renumber_enabled():
            colliding = self._poly_colliding_ids(limit=limit)
            if colliding:
                self._poly_renumber_colliding(colliding)

        # A targeted repair (a write onto a record whose base row is missing) is not a
        # migration: it must run whatever the pair's state says, and must not declare it
        # finished on the strength of one record.
        targeted = only_ids is not None

        for base_model_name in chain:
            if base_model_name == self._name or base_model_name not in self.env:
                continue
            if not targeted and self._poly_backfill_pair_state(base_model_name) == 'done':
                continue
            count, blocked = self._poly_backfill_one_base(
                base_model_name, batch_size=batch_size, limit=limit, only_ids=only_ids)
            created[base_model_name] = count
            if targeted:
                continue
            if blocked:
                self._poly_backfill_mark_pair_blocked(base_model_name, count, blocked)
            elif not self._poly_backfill_count_missing(base_model_name):
                self._poly_backfill_mark_pair_done(base_model_name, count)
        if created:
            self._poly_forget_transition_state()
        return created

    @api.model
    def _poly_backfill_pair_state(self, base_model_name):
        """'done' once this model's records have all been given their `base` rows."""
        pair = self.env['numa.poly.backfill.pair'].sudo().search([
            ('concrete_model', '=', self._name),
            ('base_model', '=', base_model_name),
        ], limit=1)
        return pair.state if pair else False

    @api.model
    def _poly_backfill_mark_pair_blocked(self, base_model_name, records_created,
                                         blocked_ids):
        """
        Record that a pair cannot finish, and why.

        Deliberately not ``done``. A closed pair is never scanned again, and closing one
        over records that still have no base row is how a broken transition came to look
        like a finished one: the pairs all said done while a third of the records had
        lost their identity to somebody else's id.
        """
        Pair = self.env['numa.poly.backfill.pair'].sudo()
        values = {'state': 'blocked', 'collisions': len(blocked_ids)}
        pair = Pair.search([
            ('concrete_model', '=', self._name),
            ('base_model', '=', base_model_name),
        ], limit=1)
        if pair:
            values['records_created'] = pair.records_created + records_created
            pair.write(values)
        else:
            values.update({
                'concrete_model': self._name,
                'base_model': base_model_name,
                'records_created': records_created,
            })
            Pair.create(values)
        _logger.warning(
            "[poly] %s -> %s: %s record(s) cannot be reconstructed, their ids belong to "
            "another model. The pair stays open; run _poly_renumber_colliding().",
            self._name, base_model_name, len(blocked_ids))

    @api.model
    def _poly_backfill_mark_pair_done(self, base_model_name, records_created=0):
        """Close a pair, so no later upgrade pays for it again."""
        Pair = self.env['numa.poly.backfill.pair'].sudo()
        values = {
            'state': 'done',
            'collisions': 0,
            'completed_on': fields.Datetime.now(),
        }
        pair = Pair.search([
            ('concrete_model', '=', self._name),
            ('base_model', '=', base_model_name),
        ], limit=1)
        if pair:
            values['records_created'] = pair.records_created + records_created
            pair.write(values)
        else:
            values.update({
                'concrete_model': self._name,
                'base_model': base_model_name,
                'records_created': records_created,
            })
            Pair.create(values)

    @api.model
    def _poly_chain_bases(self):
        """Every base of this model, deepest first, with ``ir.poly_base`` at the front.

        The order is the order the rows have to be built in: a base row cannot reference
        a base that is not there yet, and ``ir.poly_base`` is where the id is claimed, so
        nothing above it can be settled before it.
        """
        chain = [name for name in reversed(list(self._poly_get_depend_models().keys()))
                 if name != 'ir.poly_base']
        return ['ir.poly_base'] + chain

    @api.model
    def _poly_id_conflicts(self, ids):
        """
        ``{id: what already holds it}`` for the ids this model cannot claim.

        There are two ways an id is taken. A *different concrete model* may own it in
        ``ir.poly_base`` — two legacy tables both numbering from 1 produce that by the
        thousand. Or a *base* may hold a standalone row under it: a base of a polymorphic
        model is a model in its own right, its own records come from its own sequence,
        and an id it has already spent is not available to the hierarchy above it.

        Either way the row cannot be built without taking an existing record's identity
        away, which is why these ids are reported rather than overwritten.
        """
        if not ids:
            return {}
        cr, pool = self.env.cr, self.pool
        ids = list(ids)
        conflicts = {}
        owners = _poly_id_owners(cr, ids)
        for record_id, owner in owners.items():
            if not _poly_base_row_is_usable(owner, self._name, pool):
                conflicts[record_id] = owner

        # An id with no polymorphic owner belongs to no record of this hierarchy, so a
        # row already sitting on it in one of the bases is somebody else's.
        unowned = [i for i in ids if i not in owners and i not in conflicts]
        if unowned:
            for base_model_name in self._poly_chain_bases():
                if base_model_name in ('ir.poly_base', self._name) or base_model_name not in self.env:
                    continue
                base_table = self.env[base_model_name]._table
                if not base_table or not _poly_leaf_columns(cr, base_table):
                    continue
                cr.execute(SQL("SELECT id FROM %s WHERE id IN %s",
                               SQL.identifier(base_table), tuple(unowned)))
                for (taken,) in cr.fetchall():
                    conflicts.setdefault(taken, base_model_name)
        return conflicts

    @api.model
    def _poly_backfill_one_base(self, base_model_name, batch_size=1000, limit=None,
                                only_ids=None):
        """
        Insert the rows missing from one base table. See _poly_backfill_base_rows.

        :return: ``(rows_created, ids_that_could_not_be_claimed)``
        """
        cr = self.env.cr
        base = self.env[base_model_name]
        base_table, concrete_table = base._table, self._table
        base_columns = _poly_leaf_columns(cr, base_table)
        if not base_columns:
            return 0, set()

        statics, copied = self._poly_backfill_columns(base_model_name)
        required = self._poly_backfill_required_fields(base_model_name)
        stamp = fields.Datetime.now()
        model_id = None
        if 'concrete_model_id' in base_columns:
            model_id = self.env['ir.model']._get_id(self._name)

        acceptable = self._poly_acceptable_owner_ids()
        total = 0
        blocked = set()
        # Paginate on the id rather than on "what is still missing": a blocked row never
        # leaves the result set, and re-reading the same page would spin forever.
        after_id = 0
        while True:
            scope = SQL("")
            if only_ids is not None:
                if not only_ids:
                    break
                scope = SQL("AND c.id IN %s", tuple(only_ids))
            # "Missing" is not the only thing that needs looking at. A row whose base
            # row is *present but somebody else's* is the failure this pass exists to
            # catch, and asking only `b.id IS NULL` walks straight past it — which is how
            # the ir.poly_base pair kept closing itself as done over records that had
            # never owned their id.
            cr.execute(SQL(
                """
                SELECT c.id FROM %s c
                LEFT JOIN %s b ON b.id = c.id
                LEFT JOIN ir_poly_base p ON p.id = c.id
                WHERE c.id > %s %s
                  AND (b.id IS NULL OR p.id IS NULL OR p.concrete_model_id NOT IN %s)
                ORDER BY c.id
                LIMIT %s
                """,
                SQL.identifier(concrete_table), SQL.identifier(base_table), after_id,
                scope, tuple(acceptable) or (0,),
                batch_size if not limit else min(batch_size, limit - total),
            ))
            candidates = [row[0] for row in cr.fetchall()]
            if not candidates:
                break
            after_id = candidates[-1]

            conflicts = self._poly_id_conflicts(candidates)
            if conflicts:
                blocked.update(conflicts)
                for record_id, holder in sorted(conflicts.items())[:5]:
                    _logger.warning(
                        "[poly] %s id %s cannot be reconstructed: %s already holds that "
                        "id. Run _poly_renumber_colliding() to move it.",
                        self._name, record_id, holder)
            missing = [i for i in candidates if i not in conflicts]
            if not missing:
                continue

            overrides = self._poly_backfill_values(base_model_name, missing) or {}
            rows = self._poly_backfill_read_source(missing, copied)

            for concrete_id in missing:
                values = {'id': concrete_id}
                values.update(statics)
                # A copied NULL means the legacy row never answered this question, so
                # the declared default stands; anything else overrides it.
                values.update({k: v for k, v in rows.get(concrete_id, {}).items()
                               if v is not None})
                for column, value in (overrides.get(concrete_id) or {}).items():
                    if column in base_columns:
                        values[column] = value
                if model_id and 'concrete_model_id' in base_columns:
                    values.setdefault('concrete_model_id', model_id)
                for column in ('create_uid', 'write_uid'):
                    if column in base_columns:
                        values.setdefault(column, SUPERUSER_ID)
                for column in ('create_date', 'write_date'):
                    if column in base_columns:
                        values.setdefault(column, stamp)
                # Last: a NOT NULL column nothing above could answer. Without this the
                # INSERT is rejected and the record is never reconstructed at all.
                for column, field in required.items():
                    if values.get(column) is not None or column not in base_columns:
                        continue
                    fallback = self._poly_backfill_fallback_value(field, concrete_id)
                    if fallback is None:
                        continue
                    _logger.warning(
                        "[poly] %s %s: %s.%s is required and the record has no value "
                        "for it; wrote a placeholder. See the backfill ledger.",
                        self._name, concrete_id, base_model_name, column)
                    values[column] = fallback

                usable = {k: _poly_sql_param(v) for k, v in values.items()
                          if k in base_columns or k == 'id'}
                cr.execute(SQL(
                    "INSERT INTO %s (%s) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    SQL.identifier(base_table),
                    SQL(', ').join(SQL.identifier(c) for c in usable),
                    SQL(', ').join(SQL('%s', v) for v in usable.values()),
                ))
            self._poly_backfill_ledger(missing, stamp)
            total += len(missing)
            _logger.info("[poly] backfill %s -> %s: %s row(s)",
                         self._name, base_model_name, total)
            if limit and total >= limit:
                break

        if total:
            self.env.invalidate_all()
            self._sync_poly_sequence()
        return total, blocked

    @api.model
    def _poly_backfill_read_source(self, concrete_ids, copied):
        """Read the same-named columns off the concrete rows, keyed by id."""
        if not copied or not concrete_ids:
            return {}
        columns = sorted(set(copied.values()))
        self.env.cr.execute(SQL(
            "SELECT id, %s FROM %s WHERE id IN %s",
            SQL(', ').join(SQL.identifier(c) for c in columns),
            SQL.identifier(self._table),
            tuple(concrete_ids),
        ))
        result = {}
        for row in self.env.cr.fetchall():
            result[row[0]] = {
                base_column: row[1 + columns.index(source_column)]
                for base_column, source_column in copied.items()
            }
        return result

    @api.model
    def _poly_backfill_ledger(self, concrete_ids, stamp):
        """Record what was backfilled, and that it still owes post-processing."""
        Ledger = self.env['numa.poly.backfill'].sudo()
        known = set(Ledger.search([
            ('res_model', '=', self._name), ('res_id', 'in', concrete_ids),
        ]).mapped('res_id'))
        fresh = [cid for cid in concrete_ids if cid not in known]
        if fresh:
            Ledger.create([{
                'res_model': self._name,
                'res_id': cid,
                'backfilled_on': stamp,
                'post_pending': True,
            } for cid in fresh])

    @api.model
    def _cron_poly_backfill_pending(self, batch_size=500):
        """
        Finish the post-processing the backfill deferred, for every model that has any.

        Driven by a cron rather than by a registry hook on purpose. ``init`` runs while
        the schema is still being built, and the hooks that fire during registry load are
        no better: reading a many2many there returns nothing instead of failing, which
        produced base rows with no dependency links and no error to show for it. A cron
        runs against a registry that is finished and usable, can be batched, and picks up
        where it left off if it is interrupted.
        """
        # Models whose backfill was too big to run during the upgrade: do a batch of
        # inserts per tick, so a very large table is migrated over several runs instead
        # of holding a deployment open.
        Param = self.env['ir.config_parameter'].sudo()
        deferred = [n for n in (Param.get_str(POLY_BACKFILL_DEFERRED_PARAM)).split(',') if n]
        for model_name in deferred:
            if model_name not in self.env:
                continue
            model = self.env[model_name].sudo()
            try:
                # Same reason as in init(): without the savepoint one bad model aborts
                # the transaction, and the models after it -- and the post-processing
                # sweep below -- fail on a cursor that can no longer run anything.
                with self.env.cr.savepoint():
                    model._poly_backfill_base_rows(
                        batch_size=batch_size, limit=batch_size * 10)
                if not (model._poly_backfill_count_missing()
                        or model._poly_backfill_count_colliding()):
                    model._poly_backfill_undefer()
            except Exception:
                _logger.exception(
                    "[poly] deferred backfill failed for %s; it stays on the list.",
                    model_name)

        # A deployment that never opens a shell still has to hear about a model whose
        # records cannot claim their ids: the pair stays open, and nothing else says so.
        try:
            self.env['ir.poly_base']._poly_log_collision_census()
        except Exception:  # noqa: BLE001 — a report must not stop the work it reports on
            _logger.exception("[poly] collision census failed")

        # Propagated fields land in ir.model.fields rows nobody translates.
        # Cheap, idempotent, and it only writes what is still in the source
        # language, so it costs nothing on a tick with nothing to do.
        try:
            self.env['ir.poly_base']._poly_sync_dependent_field_labels()
        except Exception:  # noqa: BLE001
            _logger.exception("[poly] field label sync failed")

        self.env.cr.execute(
            "SELECT DISTINCT res_model FROM numa_poly_backfill WHERE post_pending = true")
        model_names = [row[0] for row in self.env.cr.fetchall()]
        if not model_names:
            return 0

        processed = 0
        for model_name in model_names:
            if model_name not in self.env:
                continue
            try:
                processed += self.env[model_name].sudo()._poly_backfill_run_pending(
                    batch_size=batch_size)
            except Exception:
                # One model's mapping must not strand every other model's records; the
                # flag stays set and the next run retries this one.
                _logger.exception(
                    "[poly] backfill post-processing failed for %s; its records stay "
                    "flagged for the next run.", model_name)
        return processed

    @api.model
    def _poly_backfill_run_pending(self, batch_size=500):
        """
        Run the post-processing the backfill deferred, and clear the flag.

        ``init`` cannot do it: it runs while the registry is still loading, and reading a
        many2many there returns nothing instead of failing — which is how a first attempt
        produced base rows with no dependency links and no error to show for it. The flag
        set during the insert is what makes the work recoverable rather than lost when
        that boot ends.
        """
        Ledger = self.env['numa.poly.backfill'].sudo()
        processed = 0
        while True:
            entries = Ledger.search(
                [('res_model', '=', self._name), ('post_pending', '=', True)],
                order='res_id', limit=batch_size)
            if not entries:
                break
            pending = entries.mapped('res_id')
            records = self.browse(pending).exists()
            for base_model_name in self._poly_get_depend_models().keys():
                if base_model_name in self.env:
                    records._poly_backfill_post(base_model_name, records.ids)
            entries.write({'post_pending': False})
            processed += len(pending)
        if processed:
            _logger.info("[poly] %s: post-processed %s backfilled record(s)",
                         self._name, processed)
        return processed

    @api.model
    def _poly_backfill_defer(self):
        """Note that this model still owes a backfill, so the cron can pick it up."""
        Param = self.env['ir.config_parameter'].sudo()
        deferred = {n for n in (Param.get_str(POLY_BACKFILL_DEFERRED_PARAM)).split(',') if n}
        if self._name not in deferred:
            deferred.add(self._name)
            Param.set_str(POLY_BACKFILL_DEFERRED_PARAM, ','.join(sorted(deferred)))

    @api.model
    def _poly_backfill_undefer(self):
        """Drop this model from the deferred list once it has nothing left to fill."""
        Param = self.env['ir.config_parameter'].sudo()
        deferred = {n for n in (Param.get_str(POLY_BACKFILL_DEFERRED_PARAM)).split(',') if n}
        if self._name in deferred:
            deferred.discard(self._name)
            Param.set_str(POLY_BACKFILL_DEFERRED_PARAM, ','.join(sorted(deferred)))

    @api.model
    def _poly_backfill_inline_limit(self):
        """How many missing rows this model will backfill during an upgrade."""
        # get_int returns the default when the parameter is absent or is not an
        # integer, so the try/except that used to be here is no longer needed.
        param = self.env['ir.config_parameter'].sudo().get_int(
            POLY_BACKFILL_LIMIT_PARAM, POLY_BACKFILL_INLINE_LIMIT)
        try:
            return param or POLY_BACKFILL_INLINE_LIMIT
        except (TypeError, ValueError):
            return POLY_BACKFILL_INLINE_LIMIT

    @api.model
    def _poly_backfill_count_missing(self, base_model_name=None):
        """
        How many rows of this model still lack their base row.

        With no base given, only the pairs that have not been closed are counted: once a
        pair is done, `create` maintains it, and re-counting it on every upgrade is the
        cost this whole mechanism exists to pay only once.
        """
        if base_model_name is not None:
            bases = [base_model_name]
        else:
            bases = [name for name in self._poly_get_depend_models().keys()
                     if name != self._name and name in self.env
                     and self._poly_backfill_pair_state(name) != 'done']
        total = 0
        for name in bases:
            base = self.env[name] if name in self.env else None
            if base is None or not base._table:
                continue
            self.env.cr.execute(SQL(
                "SELECT count(*) FROM %s c LEFT JOIN %s b ON b.id = c.id "
                "WHERE b.id IS NULL",
                SQL.identifier(self._table), SQL.identifier(base._table),
            ))
            total += self.env.cr.fetchone()[0]
        return total

    @api.model
    def _poly_acceptable_owner_ids(self):
        """``ir.model`` ids of the concrete models whose base rows are also this one's.

        The model itself, the bases above it — a record's row in a base is its own row —
        and every model below it, since a leaf owns the whole chain it sits on.
        """
        key = (id(self.pool), self._name)
        cached = _POLY_ACCEPTABLE_OWNERS.get(key)
        if cached is not None:
            return cached
        names = set(_poly_ancestor_names(self._name, self.pool))
        for model_name in self.env.registry.models:
            try:
                if self._name in _poly_ancestor_names(model_name, self.pool):
                    names.add(model_name)
            except Exception:  # noqa: BLE001 — an unbuilt class must not break a scan
                continue
        IrModel = self.env['ir.model'].sudo()
        model_ids = []
        for name in sorted(names):
            if name in self.env:
                model_ids.append(IrModel._get_id(name))
        _POLY_ACCEPTABLE_OWNERS[key] = model_ids
        return model_ids

    @api.model
    def _poly_colliding_ids(self, base_model_name=None, limit=None):
        """
        Rows of this model whose id is not theirs to claim.

        Split from "missing" on purpose: a missing row is inserted and the record is
        whole again, while a colliding row cannot be inserted at all — the id belongs to
        another record, and the only way out is to renumber.
        """
        cr = self.env.cr
        if not self._table or not _poly_leaf_columns(cr, self._table):
            return []
        acceptable = self._poly_acceptable_owner_ids()
        found = []

        # Owned by a concrete model that is not in this record's chain.
        cr.execute(SQL(
            "SELECT c.id FROM %s c JOIN ir_poly_base p ON p.id = c.id "
            "WHERE p.concrete_model_id NOT IN %s ORDER BY c.id %s",
            SQL.identifier(self._table), tuple(acceptable) or (0,),
            SQL("LIMIT %s", limit) if limit else SQL(""),
        ))
        found.extend(row[0] for row in cr.fetchall())

        # Held by a standalone record of a base: no polymorphic owner, but the row is
        # already there, so the id was spent outside the hierarchy.
        bases = [base_model_name] if base_model_name else self._poly_chain_bases()
        for name in bases:
            if name in ('ir.poly_base', self._name) or name not in self.env:
                continue
            base_table = self.env[name]._table
            if not base_table or not _poly_leaf_columns(cr, base_table):
                continue
            cr.execute(SQL(
                "SELECT c.id FROM %s c JOIN %s b ON b.id = c.id "
                "LEFT JOIN ir_poly_base p ON p.id = c.id "
                "WHERE p.id IS NULL ORDER BY c.id %s",
                SQL.identifier(self._table), SQL.identifier(base_table),
                SQL("LIMIT %s", limit) if limit else SQL(""),
            ))
            found.extend(row[0] for row in cr.fetchall())

        ordered = sorted(set(found))
        return ordered[:limit] if limit else ordered

    @api.model
    def _poly_backfill_count_colliding(self, base_model_name=None):
        """How many rows of this model hold an id that is already somebody else's."""
        return len(self._poly_colliding_ids(base_model_name))

    @api.model
    def _poly_renumber_enabled(self):
        """Whether the migration may move a colliding record onto a free id.

        On by default: a record that cannot be reconstructed is a record whose
        polymorphic fields silently do nothing, and leaving it that way is the failure
        this whole mechanism exists to prevent. Set ``numa_poly.renumber_collisions`` to
        ``0`` to have the backfill report the collisions and stop instead — worth doing
        on a first pass, together with ``_poly_collision_census()``.
        """
        param = self.env['ir.config_parameter'].sudo().get_str(
            POLY_RENUMBER_COLLISIONS_PARAM)
        if not param:
            return True
        return param.strip().lower() not in ('0', 'false', 'no')

    @api.model
    def _poly_table_fk_dependents(self, table):
        """``(table, column)`` for every foreign key that points at ``table``'s id.

        Read from ``pg_constraint`` rather than from the ORM: what has to move with a
        renumbered row is what the *database* will refuse to leave behind, which includes
        the many2many relation tables and every column a custom module added.
        """
        self.env.cr.execute("""
            SELECT c.conrelid::regclass::text, a.attname
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            JOIN pg_attribute r ON r.attrelid = c.confrelid AND r.attnum = c.confkey[1]
            WHERE c.contype = 'f'
              AND c.confrelid = to_regclass(%s)
              AND array_length(c.conkey, 1) = 1
              AND r.attname = 'id'
        """, (table,))
        return sorted(set(self.env.cr.fetchall()))

    @api.model
    def _poly_fk_dependents(self):
        """``(table, column)`` for every foreign key that points at this model's id."""
        return self._poly_table_fk_dependents(self._table)

    @api.model
    def _poly_reference_dependents(self):
        """``(table, id column, model column)`` for references that carry no foreign key.

        Odoo points at a record by ``(model name, id)`` in several places — attachments,
        messages, followers, external ids, the backfill ledger. Postgres knows nothing
        about those, so a renumbering that only follows real foreign keys leaves every
        one of them pointing at a record that has moved.
        """
        cr = self.env.cr
        found = set()
        for model_name in self.env.registry.models:
            model = self.env.get(model_name)
            if model is None or not model._auto or not model._table:
                continue
            for fname, field in model._fields.items():
                model_field = getattr(field, 'model_field', None)
                if field.type == 'many2one_reference' and field.store and model_field:
                    found.add((model._table, fname, model_field))
        # Two tables that predate Many2oneReference and still key records this way.
        found.add(('ir_model_data', 'res_id', 'model'))
        found.add(('numa_poly_backfill', 'res_id', 'res_model'))
        # The companion field naming the model is not always a column of its own:
        # base_automation.trg_field_ref_model_name is a related, computed on the fly.
        # Nothing is stored there to match against, so there is nothing to renumber.
        return sorted(
            (table, id_column, model_column) for table, id_column, model_column in found
            if {id_column, model_column} <= _poly_leaf_columns(cr, table)
        )

    @api.model
    @api.model
    def _poly_renumber_rank(self):
        """
        How much it costs to move this model's rows. The higher rank keeps its ids.

        When two legacy tables hold the same id, one of them has to move, and *which* is
        the whole decision. Row count is the tempting answer and the wrong one: the first
        run of this migration picked ``mrp.workcenter`` over ``res.partner`` and set out
        to renumber partner 1 — the company's own partner, named by an external id and
        pointed at from several hundred tables — in order to spare three work centres.

        So the first criterion is how widely the model is referenced, counted from
        ``pg_constraint``. Row count breaks the tie, the name breaks what is left, so the
        order is total and the same on every run.
        """
        key = (id(self.pool), self._name)
        cached = _POLY_RENUMBER_RANK.get(key)
        if cached is None:
            rows = 0
            try:
                self.env.cr.execute(SQL("SELECT count(*) FROM %s",
                                        SQL.identifier(self._table)))
                rows = self.env.cr.fetchone()[0]
            except Exception:  # noqa: BLE001 — a missing table simply ranks lowest
                pass
            cached = (len(self._poly_fk_dependents()), rows, self._name)
            _POLY_RENUMBER_RANK[key] = cached
        return cached

    @api.model
    def _poly_renumber_chain_tables(self, record_id):
        """The tables holding this record's own rows, the concrete one first.

        A record that owns its ``ir.poly_base`` row owns the rest of its chain, and all
        of it has to travel together — leaving the base row behind would keep the id
        occupied and block whoever is waiting for it.
        """
        tables = [self._table]
        owner = _poly_id_owners(self.env.cr, [record_id]).get(record_id)
        ours = _poly_base_row_is_usable(owner, self._name, self.pool) if owner else False
        for base_model_name in self._poly_chain_bases():
            base = self.env.get(base_model_name)
            if base is None or base_model_name == self._name or not base._table:
                continue
            if base._table in tables:
                continue
            if base_model_name == 'ir.poly_base':
                # The claim itself. Only ours to move if it names us.
                if ours:
                    tables.append(base._table)
                continue
            # A row in an intermediate base is ours unless it can belong to whoever holds
            # the id. It usually cannot: `res.partner` is no kind of `numa.planning.node`,
            # so a node row under a partner-owned id is the wreckage of the backfill that
            # could not tell the two apart — and leaving it behind is how 44 orphan rows
            # survived a renumbering that was otherwise correct.
            if ours or (owner and base_model_name not in _poly_ancestor_names(
                    owner, self.pool)):
                tables.append(base._table)
        return tables

    @api.model
    def _poly_renumber_colliding(self, ids=None, dry_run=False):
        """
        Free this model's records from ids that are already somebody else's.

        The last resort, and the only real fix. Polymorphic models share one id space; a
        record whose id another model holds cannot be given its base rows while it keeps
        that id, so one of the two has to move. Which one is decided by
        ``_poly_renumber_rank`` — and when the *other* model is the one that should move,
        this asks it to, rather than moving a record that half the database points at.

        Everything that points at a moved row moves with it: real foreign keys, taken
        from ``pg_constraint`` rather than from a list somebody has to maintain, and the
        ``(model, id)`` references Postgres knows nothing about. A row and its foreign
        keys move in a single statement, because a foreign key declared ``NO ACTION`` is
        checked at the end of the statement and not before — updating the row on its own
        is rejected outright.

        This rewrites primary keys of real business data. Take a backup, and run
        ``dry_run=True`` first to see what would move.

        :return: ``{old_id: new_id}`` for the rows of *this* model that moved.
        """
        ids = list(ids) if ids is not None else self._poly_colliding_ids()
        if not ids:
            return {}
        cr = self.env.cr
        self.env.flush_all()

        # Hand back the ids whose current holder is the one that should give way.
        mine, delegated = [], defaultdict(list)
        conflicts = self._poly_id_conflicts(ids)
        for record_id in ids:
            holder = conflicts.get(record_id)
            other = self.env.get(holder) if holder else None
            if other is not None and self._poly_renumber_rank() > other._poly_renumber_rank():
                delegated[holder].append(record_id)
            else:
                mine.append(record_id)
        for holder, held_ids in delegated.items():
            _logger.info("[poly] %s outranks %s: moving %s of its row(s) instead.",
                         self._name, holder, len(held_ids))
            self.env[holder]._poly_renumber_colliding(held_ids, dry_run=dry_run)
        if not mine:
            return {}

        self._sync_poly_sequence()
        plan = {}
        for old_id in mine:
            cr.execute("SELECT nextval('ir_poly_base_id_seq')")
            plan[old_id] = cr.fetchone()[0]
        if dry_run:
            _logger.info("[poly] renumber (dry run) %s: %s row(s) would move, e.g. %s",
                         self._name, len(plan), dict(list(plan.items())[:5]))
            return plan

        reference_dependents = self._poly_reference_dependents()
        # Odoo 18 dropped ir_property in favour of company-dependent jsonb columns, but
        # a database upgraded from an older version can still have the table.
        cr.execute("SELECT to_regclass('ir_property')")
        has_ir_property = bool(cr.fetchone()[0])
        fk_cache = {}

        for index, (old_id, new_id) in enumerate(plan.items(), start=1):
            # One statement per record, and — this is the part that is not optional —
            # one UPDATE per *table* within it, rewriting all of that table's columns at
            # once.
            #
            # Postgres applies at most one of a statement's data-modifying CTEs to any
            # given row, silently. A table with two columns pointing at the record
            # (`conversation_message` has parent_id, reference_id and root_id, and a
            # planning node is its own root) therefore had one of them updated and the
            # rest quietly left behind, and the statement died on the foreign key it had
            # just been told to fix.
            columns_by_table = defaultdict(set)
            for table in self._poly_renumber_chain_tables(old_id):
                if table not in fk_cache:
                    fk_cache[table] = self._poly_table_fk_dependents(table)
                for child_table, column in fk_cache[table]:
                    columns_by_table[child_table].add(column)
                columns_by_table[table].add('id')

            parts = []
            for position, (table, columns) in enumerate(sorted(columns_by_table.items())):
                ordered = sorted(columns)
                parts.append(SQL(
                    "%s AS (UPDATE %s SET %s WHERE %s RETURNING 1)",
                    SQL.identifier('poly_move_%s' % position), SQL.identifier(table),
                    SQL(', ').join(
                        SQL("%s = CASE WHEN %s = %s THEN %s ELSE %s END",
                            SQL.identifier(c), SQL.identifier(c), old_id, new_id,
                            SQL.identifier(c))
                        for c in ordered),
                    SQL(' OR ').join(
                        SQL("%s = %s", SQL.identifier(c), old_id) for c in ordered),
                ))
            cr.execute(SQL("WITH %s SELECT 1", SQL(', ').join(parts)))

            for table, id_column, model_column in reference_dependents:
                cr.execute(SQL(
                    "UPDATE %s SET %s = %s WHERE %s = %s AND %s = %s",
                    SQL.identifier(table), SQL.identifier(id_column), new_id,
                    SQL.identifier(id_column), old_id,
                    SQL.identifier(model_column), self._name))
            if has_ir_property:
                cr.execute(
                    "UPDATE ir_property SET res_id = %s WHERE res_id = %s",
                    ('%s,%s' % (self._name, new_id), '%s,%s' % (self._name, old_id)))

            if index % 500 == 0:
                _logger.info("[poly] renumber %s: %s/%s", self._name, index, len(plan))

        # Claim the new ids. Without this the record lands on an id nothing owns, while
        # the base rows that travelled with it sit there under it — which is exactly what
        # a standalone base record looks like, so the very next scan reads the record as
        # colliding with its own rows and refuses to reconstruct it.
        if _poly_is_polymorphic(self):
            model_id = self.env['ir.model']._get_id(self._name)
            cr.execute(
                "INSERT INTO ir_poly_base (id, concrete_model_id, create_uid, write_uid, "
                "create_date, write_date) SELECT unnest(%s), %s, %s, %s, now(), now() "
                "ON CONFLICT (id) DO NOTHING",
                (list(plan.values()), model_id, SUPERUSER_ID, SUPERUSER_ID))

        self.env.invalidate_all()
        self._poly_forget_transition_state()
        _logger.warning("[poly] renumbered %s row(s) of %s onto free ids; the records "
                        "can now be reconstructed.", len(plan), self._name)
        return plan

    @api.model
    def _poly_backfill_pending_pairs(self):
        """Bases of this model that have not been reconstructed yet."""
        return [name for name in self._poly_chain_bases()
                if name != self._name and name in self.env
                and self._poly_backfill_pair_state(name) != 'done']

    def init(self):
        """
        Fill in the polymorphic rows that pre-existing records are missing.

        Odoo calls this after the table has been created or updated, which is the first
        moment the base tables and their columns are all in place. Installing a
        polymorphic module on a populated database is otherwise a silent data hazard:
        searches on base fields return nothing and writes to them are discarded, neither
        with an error.
        """
        super().init()
        if getattr(self, '_name', None) == 'ir.poly_base':
            return
        if not _poly_is_polymorphic(self):
            return

        # A single allocator for the whole shared id space. It is re-applied on every
        # update, without asking whether it is needed: the statement is idempotent and
        # cheap, and asking first is exactly the kind of cleverness that left the problem
        # open for a year.
        self._poly_claim_shared_id_space()
        try:
            if not self._poly_backfill_pending_pairs():
                # Every base of this model has already been reconstructed; from here on
                # create() keeps them complete. This is the common path on every upgrade
                # after the first, and it must cost nothing.
                return
            pending = self._poly_backfill_count_missing()
            if pending > self._poly_backfill_inline_limit():
                # Deliberately not done here: this runs inside the upgrade, and a table
                # this size would hold the deployment open for as long as it takes. The
                # cron picks it up in batches; until it does, reads answer defaults and
                # writes materialise their own row, so nothing is lost in the meantime.
                _logger.warning(
                    "[poly] %s has %s record(s) without their polymorphic rows, above "
                    "the %s inline limit. The '%s' cron will work through them in "
                    "batches; until it does, reads answer defaults and any write "
                    "materialises the record's rows first, so nothing waits on it. "
                    "_poly_backfill_base_rows() finishes it now if you would rather "
                    "not wait.",
                    self._name, pending, self._poly_backfill_inline_limit(),
                    'Polymorphic: finish backfilled records')
                self._poly_backfill_defer()
                return
            # The savepoint is what lets the `except` below keep its promise. A
            # statement that fails aborts the whole transaction, so without it every
            # query after this point -- the rest of the upgrade -- dies with
            # InFailedSqlTransaction and the registry never loads. Rolling back to the
            # savepoint also clears what the attempt left in the cache.
            with self.env.cr.savepoint():
                created = self._poly_backfill_base_rows()
        except Exception:
            # A failed backfill must not take the whole upgrade down: the records stay
            # readable through the concrete model, and the cron keeps trying. Leaving it
            # to a person to re-run by hand is not a mechanism — nobody can foresee which
            # module will make which model polymorphic on which database.
            _logger.exception(
                "[poly] backfill failed for %s; handed to the '%s' cron, which will "
                "retry it.", self._name, 'Polymorphic: finish backfilled records')
            self._poly_backfill_defer()
            return
        if any(created.values()):
            _logger.info("[poly] %s: backfilled %s", self._name, created)
        if self._poly_backfill_pending_pairs():
            # Something is still open — a batch limit, a collision that could not be
            # resolved, a base that was not ready. The cron owns it from here.
            self._poly_backfill_defer()

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
                if not getattr(_fobj, 'string', None) or isinstance(_fobj.string, Sentinel):
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
            # NOTE: field.column_type is NOT demanded. The injected poly fields
            # (concrete_model_id, old_id, poly_payload, ...) are computed Many2one/Text
            # with store=False whose column_type can be falsy; even so they may have a
            # legacy physical NOT NULL column. The SELECT below already filters to columns
            # that EXIST and are NOT NULL, so `not field.store` is enough.
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
                # Without demanding field.column_type (see the note in _auto_init): it
                # includes the injected non-stored poly fields even if column_type is falsy.
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

        # Run only once, from the base model, to avoid synchronising with subsets of
        # the hierarchy depending on the order of the hooks.
        if self._name == 'ir.poly_base':
            # Ensure ir.poly_base sequence starts AFTER the max ID of any participant table
            try:
                self._sync_poly_sequence()
            except Exception:
                # If something fails in the transaction, we cannot go on readjusting
                # the sequence here.
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
        cached = _POLY_NATIVE_FNAMES.get(cls._name)
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

        # Only the classes a MODULE declared count. `cls.mro()` also contains the
        # registry's own aggregate class -- which by construction holds EVERY field of
        # the model, including the ones poly injected -- and the contribution class poly
        # generates. Counting those made "native" mean "any field at all": `project.task`
        # reported the whole `pln_*` set as its own although its bridge only declares
        # `_depend_models`, so a field that belongs to `numa.planning.node` resolved to
        # the leftover column on `project_task` instead of to the base.
        declaradas = set()
        for _defs in odoo.models.MetaModel._module_to_models__.values():
            declaradas.update(_defs)

        native = set()
        for klass in cls.mro():
            if klass not in declaradas:
                continue
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
        _POLY_NATIVE_FNAMES[cls._name] = native
        return native

    # _build_dependant_model_attributes lived here: 1016 lines that could never run.
    # Every reference to it in this file was a recursive call from inside its own body,
    # so nothing could enter it, and a boot with a probe on its first statement never
    # hit it once. The field injection it duplicated is done by _build_poly_fields
    # below, which is what the registry actually calls.


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
                excluded_related = getattr(cls, '_poly_exclude_related_fields', None) or set()
                if fname in excluded_related:
                    continue
                # Respect fields declared explicitly on the target class, so that
                # poly injection does not overwrite local overrides.
                local_decl = cls.__dict__.get(fname)
                if isinstance(local_decl, fields.Field):
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

                new_field = _poly_force_related(
                    copy.copy(field), '{}.{}'.format(link, origin_fname))
                if getattr(new_field, 'type', None) == 'selection':
                    # Rebuild the related Selection without an explicit `selection`
                    # to avoid ignored-attribute warnings.
                    new_field = fields.Selection(
                        string=getattr(field, 'string', None),
                        related='{}.{}'.format(link, origin_fname),
                        readonly=getattr(field, 'readonly', True),
                        store=False,
                        help=getattr(field, 'help', None),
                    )
                # Avoid ignored-attribute warnings on related fields.
                for _attr in ('selection', 'selection_add', 'default'):
                    try:
                        if hasattr(new_field, _attr):
                            setattr(new_field, _attr, None)
                    except Exception:
                        pass
                try:
                    attrs = getattr(new_field, '_attrs', None)
                    if isinstance(attrs, dict):
                        attrs.pop('selection', None)
                        attrs.pop('selection_add', None)
                        attrs.pop('default', None)
                except Exception:
                    pass
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
                    if getattr(redirected, 'type', None) == 'selection':
                        redirected = fields.Selection(
                            string=getattr(field, 'string', None),
                            related=new_related,
                            readonly=getattr(field, 'readonly', True),
                            store=False,
                            help=getattr(field, 'help', None),
                        )
                    for _attr in ('selection', 'selection_add', 'default'):
                        try:
                            if hasattr(redirected, _attr):
                                setattr(redirected, _attr, None)
                        except Exception:
                            pass
                    try:
                        attrs = getattr(redirected, '_attrs', None)
                        if isinstance(attrs, dict):
                            attrs.pop('selection', None)
                            attrs.pop('selection_add', None)
                            attrs.pop('default', None)
                    except Exception:
                        pass
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
        # A many2one in the values may point at a record whose base row was never built;
        # without it the insert fails on a foreign key naming a table the caller never
        # mentioned. True of non-polymorphic models too — numa.planning.allocation is one.
        self._poly_repair_base_references(data_list)

        # [poly] ir.poly_base IS NOT polymorphic, it is the common base.
        # Standard Odoo models that ARE NOT polymorphic must also be handled by Odoo.
        _is_poly = _poly_is_polymorphic(self)
        _logger.debug('[poly] create() called for %s, is_poly=%s', self._name, _is_poly)
        if self._name == 'ir.poly_base' or not _is_poly:
            # Global defence: on non-polymorphic models (or before the poly
            # wiring is active), make sure the physical sequence of the table is
            # not behind MAX(id). It is done once per table/registry so as not
            # to hurt performance.
            if self._name != 'ir.poly_base':
                # A database error (transaction already aborted, concurrency conflict) is not
                # hidden: hiding it only moves it to the next query, far from the cause, and
                # takes away Odoo's chance to retry the request.
                try:
                    self._sync_table_id_sequence_once()
                except psycopg2.Error:
                    raise
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._poly_reserve_base_ids(data_list)
                except psycopg2.Error:
                    raise
                except Exception:
                    _logger.exception(
                        "[poly] could not reserve a shared id for a new %s; it may "
                        "land on an id the hierarchy above it already holds.",
                        self._name)

            # Reject explicit IDs that already exist in the table.  Creating a row with an
            # already-taken primary key is an error (same contract as the polymorphic branch
            # below, which raises).  copy() must NOT leak the source id here: that is handled at
            # the source by the copy_data override that drops technical/bookkeeping fields, so a
            # well-behaved copy never reaches this branch with a colliding id.
            explicit_ids = [v['id'] for v in data_list if 'id' in v]
            if explicit_ids:
                existing_ids = set(self.search([('id', 'in', explicit_ids)]).ids)
                for v in data_list:
                    if v.get('id') in existing_ids:
                        raise ValidationError(
                            _('You are trying to create a %s with explicit id %d. It exists already!')
                            % (self._name, v['id'])
                        )
            # [poly] Filter out Selection values that are invalid for this model.
            # This prevents cross-model state pollution when poly sub-creates pass
            # a value that is valid on the parent but not on this model (e.g.
            # conversation.message.state='new' -> fsm.instance.state).
            #
            # ONLY on vals PROPAGATED by poly: in a create asked directly by a caller, an
            # invalid value is an error and it is Odoo's job to reject it. Filtering it silently
            # left the record created without that data and with nobody the wiser — that is how
            # the type of 73 imported documents was lost, with only a WARNING in the log left.
            if self._name != 'ir.poly_base' and poly_vals_propagados(self.env):
                clean_list = []
                for vals in data_list:
                    clean_vals = {}
                    for k, v in vals.items():
                        if (v is not False and v is not None
                                and k in self._fields):
                            f = self._fields[k]
                            if isinstance(f, fields.Selection) and not poly_selection_value_is_valid(f, v):
                                _logger.warning(
                                    "[poly] Filtering out Selection field %s=%r from %s create: not a valid value %s",
                                    k, v, self._name, {sel[0] for sel in f.selection}
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

        # A key nobody recognises is an ERROR, not something to drop.
        #
        # The polymorphic create below distributes the values between this model, its
        # bases and the link fields, and every one of those branches is written as
        # `if k in <some>._fields`. A key that matches none of them falls through all of
        # them and is silently lost: the record is created without it and nothing is
        # logged. Odoo itself raises ValueError for an unknown field, but that check
        # lives in `BaseModel.create`, which this branch never calls.
        #
        # Measured on Odoo 20: `res.partner.create({'mobile': '+54 9 11 6123 4567'})`
        # returned a partner and threw the number away. `mobile` was removed in Odoo 20,
        # so every caller still writing it lost the phone with no error --
        # while `search([('mobile', '=', ...)])` raised, as it should.
        #
        # Skipped for values propagated by poly itself: those are filtered on purpose a
        # few lines above, where a parent's value may legitimately not exist on a child.
        if not poly_vals_propagados(self.env):
            conocidos = set(self._fields)
            for base_name in depend_models:
                if base_name == '_is_poly_enabled' or base_name not in self.pool:
                    continue
                conocidos.update(self.env[base_name]._fields)
            conocidos.update(_POLY_CREATE_TECHNICAL_KEYS)
            for vals in data_list:
                for k in vals:
                    if k not in conocidos:
                        raise ValueError(f"Invalid field {k!r} in {self._name!r}")

        # If this is a polymorphic create of a subclass handle it recursively

        # Accumulator of the created records. It MUST start empty: create() can be invoked
        # on a NON-empty recordset (e.g. record.copy() calls self.create(vals)), and returning
        # `self` mixed with the new ones breaks the semantics (copy() returned original + copy).
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

        # Capture the field names of the input BEFORE the creation loop consumes them
        # (it routes/pops the inherited fields towards the sub-creates of the bases). They are
        # used at the end to fire the concrete model's @api.constrains on inherited fields.
        _poly_input_fnames = set()
        for _vals in data_list:
            _poly_input_fnames.update(_vals.keys())

        if concrete_model_id:
            concrete_model = self.env['ir.model'].browse(concrete_model_id).exists()
            # CAREFUL: `concrete_model` is an ir.model record; the technical name of the
            # concrete model lives in its `.model` field (e.g. 'test.test4'), NOT in `._name`
            # (which for an ir.model recordset is always 'ir.model'). concrete_model_id can
            # arrive in the vals as a dispatch from a base (redirect to the concrete model) or
            # dragged along by copy() (field inherited from ir.poly_base): in that case
            # target == self and the bookkeeping must only be dropped, not redirected (otherwise
            # it tried to create an ir.model).
            target_name = concrete_model.model if concrete_model else None
            # Drop the bookkeeping field from the vals in both cases.
            new_vals_list = []
            for data in data_list:
                new_data = dict(data)
                new_data.pop('concrete_model_id', None)
                new_vals_list.append(new_data)

            if target_name and target_name != self._name:
                _logger.debug(f'Creating subclass {target_name} with {new_vals_list}')
                return self.env[target_name].with_context(
                    **{POLY_PROPAGATED: True}).create(new_vals_list)

            # target == self (or a non-existent ir.model): go on with the normal create
            # without the field.
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
                            and k not in poly_links
                            and poly_vals_propagados(self.env)
                            and not poly_selection_value_is_valid(f, v)):
                         _logger.warning(
                              "[poly] Filtering out Selection field %s=%r from %s create: not a valid value %s",
                              k, v, self._name,
                              {sel[0] for sel in (f.selection if isinstance(f.selection, list) else [])}
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
        # _poly_leaf_columns caches per table; sql.table_columns queries
        # information_schema.columns every time. Measured on res.partner: 5.64 ms out of the
        # 13.7 ms of SQL of a create -- 41%, and the largest single cost of the insert, for
        # reading a catalogue that does not change at runtime.
        _poly_leaf_cols = set()
        if getattr(self, '_table', None):
            _poly_leaf_cols = _poly_leaf_columns(self.env.cr, self._table)

        # On polymorphic models, if there are inserts without an explicit id, make sure
        # once per registry that the global ir.poly_base sequence is aligned.
        # It avoids PK collisions when the process enters directly through the
        # polymorphic branch (e.g. creating a res.partner from res.users).
        if any('id' not in data for data in data_list):
            self._sync_poly_sequence()

        # Process each record to create
        for current_idx, data in enumerate(data_list):
            # Handle explicit ID or create a new one via ir.poly_base
            linked_id = self._poly_identity_from_link_fields(data)
            if 'id' in data:
                new_id = data['id']
                if linked_id and linked_id != new_id:
                    raise ValueError(
                        "%s: create was given id=%s and a link field pointing at %s. A "
                        "link field is the record's own id, so the two cannot differ."
                        % (self._name, new_id, linked_id))
            elif linked_id:
                new_id = linked_id
                data['id'] = new_id
            else:
                # Now we create in ir.poly_base trusting the already synchronised sequence.
                # If it still fails because of an ID inserted right after the max_id was
                # computed, Odoo will raise the integrity exception (optimistic behaviour).
                
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

            # [poly] Use the UNFILTERED original values (processed_vals_list is parallel to
            # data_list by index; current_idx comes from the enumerate -> robust against equal
            # clean dicts, which with data_list.index(data) crossed records in a bulk create).
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
                    created_base = base_model.with_context(
                        **{POLY_PROPAGATED: True}).create([base_data])
                    dep_record_ids[base] = created_base.id
                else:
                    _logger.debug(f'[poly] Sub-write for {base} from {self._name}: data={base_data}')
                    existing_base.write(base_data)
                    dep_record_ids[base] = existing_base.id

            # Finally, create the record in this model.
            # Use the UNFILTERED original values (by current_idx from the enumerate) to
            # find the inherited fields that are stored in this model's table.
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
            # Principle (no hardcoded consumer names): a field is forced into the LEAF base_data
            # only if it is an OWN field (not related). Related/inherited fields (e.g. `active`,
            # or `name` on a subtype of res.partner) belong to a base and are routed to its
            # sub-create, NOT to the leaf table (otherwise the INSERT fails: the column does not
            # exist on the leaf). (Before: the hardcoded list
            # `('name','provider','active','facebook_account_id','driver_id')` — a stabilization
            # scar — forced `active` onto the leaf and broke poly persons of res.partner.)
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
                # [poly][20.0] `env.cache.invalidate` is deprecated (environments.py:655);
                # the 20.0 idiom is to ask the field for it.
                for k in base_data.keys():
                    if (f := self._fields.get(k)) is not None:
                        f._invalidate_cache(self.env, new_records._ids)

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
                                            target_field._invalidate_cache(self.env, tuple(target_ids))
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

        # [poly] Fire the concrete model's @api.constrains for the input fields that are
        # INHERITED (related, they live on a base): the leaf's super().create() only validates
        # ITS own columns, so a constraint on an inherited field (e.g. a1, in test.test1) was
        # not evaluated on create (it was on write -> asymmetry / validation bypass).
        # We validate those fields explicitly on the created records.
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
        When copying a polymorphic record the fields poly manages internally must be dropped:
        the ir.poly_base bookkeeping (id, old_id, concrete_model_id, poly_payload, poly_base_id)
        and ALL the links to the bases (PolyReference: testN_id, etc.). Copied verbatim they
        would point at the ORIGINAL's bases (or at columns that do not exist on the leaf table,
        e.g. poly_base_id in test_test2). With them removed, poly's create() regenerates an
        identity of its own and fresh bases out of the copied data.
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
                    # PER-RECORD access (not self.mapped): mapped() over the PolyReference
                    # loops in its __get__ (Field.mapped re-fires the descriptor); direct
                    # per-record access resolves the link without hanging.
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

    @api.model
    def _poly_transition_finished(self):
        """
        True once every base of this model has been reconstructed.

        Reports on the migration; deliberately *not* what decides whether the safety net
        below runs. A finished migration says the records that existed at the time were
        completed, not that no incomplete record can appear afterwards — a restored
        partial dump, a row inserted outside the ORM and a create that failed halfway all
        produce one, and a safeguard switched off by a flag is not a safeguard.
        """
        key = (id(self.pool), self._name)
        if key in _POLY_TRANSITION_FINISHED:
            return True
        bases = [name for name in self._poly_chain_bases()
                 if name != self._name and name in self.env]
        if not bases:
            _POLY_TRANSITION_FINISHED.add(key)
            return True
        try:
            done = set(self.env['numa.poly.backfill.pair'].sudo().search([
                ('concrete_model', '=', self._name),
                ('base_model', 'in', bases),
                ('state', '=', 'done'),
            ]).mapped('base_model'))
        except Exception:  # noqa: BLE001 — before the table exists, assume unfinished
            return False
        if all(name in done for name in bases):
            _POLY_TRANSITION_FINISHED.add(key)
            return True
        return False

    @api.model
    def _poly_forget_transition_state(self):
        """Ask again — a pair was reopened, or the backfill just moved rows."""
        _POLY_TRANSITION_FINISHED.discard((id(self.pool), self._name))

    @api.model
    def _poly_reserve_base_ids(self, data_list):
        """Give a standalone record of a polymorphic base an id from the shared allocator.

        A base is a model in its own right, and its own ``create`` drew from its own
        sequence — starting at 1, straight into the ids the hierarchy above it already
        held. That is how a demo ``numa.planning.resource`` came to share a row with
        ``res.partner`` 1: the two are one primary key, so writing the partner's name
        renamed the resource, and the resource's availability periods belonged to the
        partner. The scheduling problem built from it asked a resource with no
        availability to do 112 hours of work, and CP-SAT correctly called it infeasible.

        The other half of the same rule is already in ``_get_max_poly_id``, which makes a
        polymorphic record skip the ids a base has spent. This is the direction that was
        missing: one ``nextval`` makes the collision impossible instead of merely
        detectable afterwards.
        """
        if not _poly_subtype_names(self._name, self.pool):
            return
        missing = [vals for vals in data_list if not vals.get('id')]
        if not missing:
            return
        self._sync_poly_sequence()
        cr = self.env.cr
        for vals in missing:
            cr.execute("SELECT nextval('ir_poly_base_id_seq')")
            vals['id'] = cr.fetchone()[0]

    @api.model
    def _poly_identity_from_link_fields(self, data):
        """The id a caller asked this record to take, said with a link field.

        ``_depend_models`` maps each base to the name of the field that links to it, and
        that field is a :class:`PolyReference`: unstored, read-only, and by construction
        equal to the record's own id -- ``convert_to_record`` returns
        ``comodel(env, (record.id,), (record.id,))``. So ``{'poly_id': driver.id}`` and
        ``{'id': driver.id}`` are the same sentence, and the bridges say it the first way:

            driver = self.env['conversation.driver'].create({'name': ..., ...})
            self.env['conversation.driver.instagram'].create({'poly_id': driver.id, ...})

        ``create`` used to read only ``id``, which made the link field silently inert. The
        value was dropped as unstored, a fresh id was drawn from the sequence, and the base
        was created a *second* time -- this time from a dict that never carried the
        caller's business values, because the caller had already put them in the first one.
        On ``conversation.driver``, whose ``name`` is NOT NULL, that second insert failed
        outright and took 42 tests across five bridges with it.

        Returns ``None`` when no link field was supplied, which is the ordinary case: the
        record is new and draws its own identity.
        """
        candidates = {}
        for link_name in (self._poly_get_depend_models() or {}).values():
            value = data.get(link_name)
            if isinstance(value, BaseModel):
                value = value.id
            if isinstance(value, int) and value > 0:
                candidates[link_name] = value
        if not candidates:
            return None
        distinct = set(candidates.values())
        if len(distinct) > 1:
            raise ValueError(
                "%s: create was given several identities -- %s. A link field is the "
                "record's own id, so they all have to agree."
                % (self._name, ', '.join('%s=%s' % kv for kv in sorted(candidates.items()))))
        return distinct.pop()

    @api.model
    def _poly_base_rows_present(self, ids):
        """One indexed lookup: do these records have an ``ir.poly_base`` row of their own?

        That row is where the id is claimed, and ``create`` never makes one without the
        rest of the chain — so a row that belongs to *this* record is a sound proxy for
        "this record is whole", and the cheapest question that can be asked on the write
        path. Ownership is half the question, not a refinement of it: a colliding record
        has a row under its id too, somebody else's, and answering on presence alone
        would wave it through exactly as the old backfill did.

        The alternative — trusting the migration to have finished — costs nothing and
        answers the wrong question: it stays true of a database that acquired an
        incomplete record yesterday.
        """
        ids = set(ids)
        if not ids:
            return True
        return len(self._poly_owned_base_ids(ids)) >= len(ids)

    def _poly_claim_shared_id_space(self):
        """Make this model's table, and those of its bases, take their id from the one allocator.

        A polymorphic record and its components share an id, so all of those tables live
        in one and the same space. But each one was born with its own ``SERIAL`` and
        therefore with its own sequence: thirty independent allocators handing out over
        the same space. That they did not collide depended on absolutely every insert
        going through poly's ``create()``, which supplies the explicit id and never uses
        the column default. Any insert outside of that -- direct SQL, a data load, an ORM
        path that inserts without an id -- fired a sequence that knows nothing about the
        shared space.

        What is insidious is that the symptom depends on the table. ``res_partner_id_seq``
        was at 119 with ``MAX(id) = 14763``: there an insert by default blows up loudly with
        a duplicate key. ``conversation_bot_id_seq`` was at 0 with the table empty: it hands
        out 1, 2, 3 -- free in *that* table and taken in the shared space. That does not
        fail, it corrupts. It is the mechanism behind the 560 collisions that showed up in
        production.

        Periodic reconciliation (``_get_max_poly_id`` scanning 26 tables and
        ``_sync_poly_sequence`` doing a ``setval`` under an advisory lock) cannot close that:
        it synchronises allocators that drift apart again as soon as it finishes. With a
        single allocator the requirement "the id must be greater than that of every base"
        disappears. "Greater than" is not what is needed; "never handed out before" is, and
        that is what a sequence gives for free, atomically and without blocking: 8
        concurrent sessions generated 2000 ids without a single duplicate in 121 ms.

        It is re-applied on every update on purpose. The ``ALTER`` touches the catalogue, it
        does not rewrite the table, and it is idempotent; and doing it incrementally -- each
        model claims its own chain -- avoids depending on the order in which modules load.
        """
        cr = self.env.cr
        tablas = []
        if getattr(self, '_table', None):
            tablas.append(self._table)
        for base_name in (self._poly_get_depend_models() or {}):
            base = self.env.get(base_name) if base_name in self.env else None
            if base is not None and getattr(base, '_table', None):
                tablas.append(base._table)

        for table in dict.fromkeys(tablas):
            try:
                if not sql.table_exists(cr, table):
                    continue
                cr.execute("""SELECT column_default FROM information_schema.columns
                               WHERE table_schema = current_schema()
                                 AND table_name = %s AND column_name = 'id'""", (table,))
                row = cr.fetchone()
                ya_estaba = bool(row and row[0] and POLY_ID_SEQUENCE in row[0])

                # The sequence only moves forward. Raising it above this table's maximum
                # before claiming it closes the invariant without global coordination:
                # after walking them all, it sits above the maximum of all of them.
                cr.execute(SQL("SELECT COALESCE(MAX(id), 0) FROM %s", SQL.identifier(table)))
                max_id = (cr.fetchone() or [0])[0] or 0
                cr.execute("SELECT last_value, is_called FROM %s" % POLY_ID_SEQUENCE)
                last, called = cr.fetchone()
                actual = last if called else last - 1
                if max_id > actual:
                    cr.execute("SELECT setval(%s, %s, true)", (POLY_ID_SEQUENCE, max_id))
                    _logger.info("[poly] %s advanced to %s because of %s", POLY_ID_SEQUENCE, max_id, table)

                cr.execute(SQL(
                    "ALTER TABLE %s ALTER COLUMN id SET DEFAULT nextval(%s)",
                    SQL.identifier(table), SQL(repr(POLY_ID_SEQUENCE)),
                ))
                if not ya_estaba:
                    _logger.info("[poly] %s: its id column now draws from the one allocator %s",
                                 table, POLY_ID_SEQUENCE)
            except Exception:  # noqa: BLE001
                # A table that cannot be claimed must not prevent claiming the others;
                # the next update retries it.
                _logger.warning("[poly] could not point %s at the one allocator", table,
                                exc_info=True)

    @api.model
    def _poly_owned_base_ids(self, ids):
        """The subset of ``ids`` whose ``ir.poly_base`` row is this model's to write.

        The same question :meth:`_poly_base_rows_present` asks, answered by name instead
        of by count, for the callers that must act on each id rather than on the batch.
        """
        ids = [i for i in set(ids or ()) if isinstance(i, int) and i > 0]
        if not ids:
            return []
        acceptable = self._poly_acceptable_owner_ids()
        if not acceptable:
            return []
        self.env.cr.execute(
            "SELECT id FROM ir_poly_base WHERE id IN %s AND concrete_model_id IN %s",
            (tuple(ids), tuple(acceptable)))
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def _poly_ensure_base_rows(self, ids, force=False):
        """
        Build the polymorphic rows ``ids`` are missing, now, before they are needed.

        The safety net for a transition that is not over: a table still being migrated by
        the cron, a backfill that failed halfway, a row inserted outside the ORM. What
        decides whether it runs is the state of the *record*, never which fields a caller
        happens to be touching — the write that took production down set only
        ``date_planned``, a field of the concrete model, and then created an allocation
        pointing at the base row that was not there:

            ForeignKeyViolation: numa_planning_allocation_node_id_fkey
            Key (node_id)=(14764) is not present in table "numa_planning_node"

        A record whose id belongs to somebody else cannot be completed here — the id has
        to be given up first, and taking it out from under a caller mid-transaction is
        not something this may do. It is reported and skipped, never raised: refusing the
        write would mean a purchase order that cannot be saved because one of its lines
        is waiting for a migration, and a system that stops is worse than one whose
        planning fields on that one line are still empty. The cron resolves it, usually
        within the hour.
        """
        ids = [i for i in (ids or []) if isinstance(i, int) and i > 0]
        if not ids or not self._poly_get_depend_models():
            return
        if not force and self._poly_base_rows_present(ids):
            return
        conflicts = self._poly_id_conflicts(ids)
        if conflicts:
            record_id, holder = sorted(conflicts.items())[0]
            _logger.warning(
                "[poly] %s %s cannot be given its polymorphic rows yet: the id belongs "
                "to %s (%s record(s) of this write). Values aimed at a base model are "
                "not stored for %s. The backfill cron moves it to a free id; "
                "_poly_renumber_colliding() does it now.",
                self._name, record_id, holder, len(conflicts),
                'them' if len(conflicts) > 1 else 'it')
            ids = [i for i in ids if i not in conflicts]
            if not ids:
                return
        self._poly_backfill_base_rows(only_ids=ids)

    def _poly_ensure_base_rows_for_write(self, vals):
        """Kept for callers outside this module; the values no longer decide anything."""
        self._poly_ensure_base_rows(list(self._ids))

    @api.model
    def _poly_base_reference_fields(self):
        """``(field name, base model)`` for the many2ones of this model that point into
        a polymorphic hierarchy.

        Almost every model has none, and answering that is a dict lookup — which is the
        whole point, because the check below runs on every create and write.
        """
        key = (id(self.pool), self._name)
        cached = _POLY_BASE_REFERENCE_FIELDS.get(key)
        if cached is None:
            cached = tuple(
                (fname, field.comodel_name)
                for fname, field in self._fields.items()
                if field.type == 'many2one' and field.store and field.comodel_name
                and _poly_subtype_names(field.comodel_name, self.pool)
            )
            _POLY_BASE_REFERENCE_FIELDS[key] = cached
        return cached

    @api.model
    def _poly_repair_base_references(self, vals_list):
        """
        Complete the records this write is about to point at.

        A foreign key does not care who forgot to build the row. ``numa.planning.node``
        is a base of ``purchase.order.line``, so an allocation created against a line
        that never got its node row fails inside *the allocation's* create, with a
        ForeignKeyViolation naming a table the caller never mentioned. The record being
        referenced is the incomplete one, so that is where the repair belongs.
        """
        references = self._poly_base_reference_fields()
        if not references:
            return
        wanted = defaultdict(set)
        for fname, base_model_name in references:
            for vals in vals_list:
                value = vals.get(fname)
                if isinstance(value, BaseModel):
                    value = value.id
                if isinstance(value, int) and value > 0:
                    wanted[base_model_name].add(value)
        for base_model_name, ids in wanted.items():
            try:
                self._poly_complete_base_targets(base_model_name, ids)
            except Exception:  # noqa: BLE001 — the caller's own error is the useful one
                _logger.exception(
                    "[poly] could not complete the %s records referenced from %s",
                    base_model_name, self._name)

    @api.model
    def _poly_complete_base_targets(self, base_model_name, ids):
        """Build the missing rows of `base_model_name` for `ids`, via their own model."""
        cr = self.env.cr
        base = self.env.get(base_model_name)
        if base is None or not base._table or not _poly_leaf_columns(cr, base._table):
            return
        cr.execute(SQL("SELECT id FROM %s WHERE id IN %s",
                       SQL.identifier(base._table), tuple(ids)))
        missing = set(ids) - {row[0] for row in cr.fetchall()}
        if not missing:
            return
        for subtype in _poly_subtype_names(base_model_name, self.pool):
            if not missing:
                break
            model = self.env.get(subtype)
            if model is None or not model._auto or not model._table:
                continue
            if not _poly_leaf_columns(cr, model._table):
                continue
            cr.execute(SQL("SELECT id FROM %s WHERE id IN %s",
                           SQL.identifier(model._table), tuple(missing)))
            owned = [row[0] for row in cr.fetchall()]
            if not owned:
                continue
            # The base row is already known to be absent, so there is nothing left for
            # the cheap probe to establish: go straight to the repair.
            model._poly_ensure_base_rows(owned, force=True)
            missing.difference_update(owned)

    def write(self, vals):
        """
        Override write to intercept and merge poly_payload data.
        """
        if not self:
            return True

        # Before anything else, and whether or not THIS model is polymorphic: a many2one
        # in `vals` may be about to point at a record that never got its base row.
        self._poly_repair_base_references([vals])

        if not _poly_is_polymorphic(self):
            return super().write(vals)

        # A write to a field that lives on a base row is discarded when that row does not
        # exist — silently, returning True. And a write that touches nothing but the
        # model's own fields is no safer: what runs after it reaches for the base row.
        # Give the records their rows first, either way.
        try:
            self._poly_ensure_base_rows(list(self._ids))
        except Exception:
            # This must not cost the user their write: the record stays as readable as it
            # was, and the log carries the reason.
            _logger.exception(
                "[poly] could not create the missing base rows for a write on %s; "
                "values aimed at a base model may be lost.", self._name)

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

    def _poly_stamp_base_audit_fields(self):
        """Keep the shared identity's ``write_uid``/``write_date`` current, and only its own.

        A polymorphic record has two audit trails. The concrete table keeps its own
        ``write_date``/``write_uid`` columns, which standard Odoo maintains correctly and
        this method does not touch. ``ir_poly_base`` keeps a second pair, for the identity
        the whole chain shares -- the answer to "when was this record, in any of its
        components, last touched?", which no single component's column can give.

        That second pair was written once at insert and never again: its caller tested for
        an attribute that name-mangling put out of reach, so it never ran and every base
        row still carries its creation timestamp. Making the caller ask the right question
        is what brings this code to life, and bringing it to life is what makes the filter
        below load-bearing rather than decorative.

        Because the row is addressed by the record's own id, and that is right exactly as
        long as the id is the record's to claim. When it is not -- a colliding id left over
        from the pre-transition id space, the state :meth:`_poly_colliding_ids` reports --
        the row under that id is another model's record, and stamping it there would not
        add a wrong second trail: it would overwrite the only shared-identity trail that
        record has, with this user and this moment. Silent, and in the one field an auditor
        is entitled to trust. Production carried 560 such ids on ``purchase.order.line``
        alone, and printing a quotation writes every line
        (``purchase.order.line.state`` is a stored related over the order), so an ordinary
        print would have been enough to do it.

        The rows are therefore filtered by ownership. A colliding record keeps no shared
        trail until it is renumbered -- the honest outcome, and the one the renumbering
        pass exists to end -- and each such id is reported once rather than dropped
        quietly.
        """
        ids = [i for i in self._ids if isinstance(i, int) and i > 0]
        if not ids:
            return
        owned = self._poly_owned_base_ids(ids)
        if owned:
            self.env['ir.poly_base'].browse(owned).write({
                'write_uid': self.env.uid,
                'write_date': self.env.cr.now(),
            })
        skipped = set(ids) - set(owned)
        if not skipped:
            return
        owners = _poly_id_owners(self.env.cr, sorted(skipped))
        for record_id in sorted(skipped):
            key = (id(self.pool), self._name, record_id)
            if key in _POLY_REPORTED_UNOWNED_STAMPS:
                continue
            _POLY_REPORTED_UNOWNED_STAMPS.add(key)
            holder = owners.get(record_id)
            _logger.warning(
                "[poly] %s %s gets no shared audit stamp: its ir_poly_base row is %s. "
                "Stamping it would rewrite that record's trail instead. The renumbering "
                "pass has to move this record before it can have one of its own.",
                self._name, record_id,
                "held by %s" % holder if holder else "claimed by no model")
    def _write_multi(self, vals_list):
        """Write, and stamp the shared audit trail of a polymorphic record.

        [20.0] This used to be a full copy of core's `_write_multi`, and the copy had
        fallen a version behind on the one piece of SQL that is not obvious: the
        expression that merges a translated column. Odoo 20 passes such a column the
        pair `(is_partial, translations)` and reads `expr -> 0` and `expr -> 1` out of
        it; the copy still treated `expr` as the bare translation dict, so what went
        into the column was

            COALESCE(col, jsonb_build_object('en_US', <the pair's first element>))
            || '[false, {"en_US": "..."}]'

        -- an object concatenated with an array, which Postgres answers with an array.
        Every translated field written through a polymorphic model was stored as
        `[{...}, false, {...}]` instead of `{"en_US": "..."}`, and the next read of it
        died in `StoredTranslations(val)` with "dictionary update sequence element #0
        has length 1; 2 is required". Installing `website` alongside `numa_poly` hit
        this in `website`'s own post-init hook, which is why the two could not be
        installed in the same run.

        The copy had also quietly dropped `transaction._wrote__` and the `_log_access`
        magic fields, and swapped core's assertion on non-column fields for a silent
        `continue`. None of that was the point of the override: the point is the two
        lines at the end.
        """
        super()._write_multi(vals_list)

        # Update audit fields for polymorphic models.
        # The predicate is the model's own declaration, not the `__depends_base_classes`
        # attribute this used to test for: that name is written inside the body of
        # `PolyBase`, so Python mangles it to `_PolyBase__depends_base_classes`, while
        # every `hasattr`/`getattr` reading it passes an unmangled string literal. The
        # attribute is on no model in the registry -- `dir()` finds neither spelling --
        # so the test was constant False and the stamp below has never run.
        if self._log_access and self._name != 'ir.poly_base' and self._poly_get_depend_models():
            self._poly_stamp_base_audit_fields()



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

        # Whether this model is polymorphic is its own declaration. This used to test for
        # `__depends_base_classes`, which no model carries, so the sanitisation below and
        # the base merge at the end have never run: every call took this line out.
        if not self._poly_get_depend_models():
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
                # [poly] DO NOT TOUCH the related PATHS at runtime if it fails.
                # We delegate to Odoo after reporting the error with context for debugging.
                _logger.error("[poly] KeyError in fields_get for %s (Key: %s). Traceback shows potential related route corruption.", self._name, faulty_key)
                raise e
            
            raise e
        
        # A merge of each base's fields_get() into this one used to sit here, reading the
        # bases from `__depends_base_classes` and therefore never running. Giving it a
        # working source made it advertise `event_id` on the six conversation.message.*
        # models -- a field poly deliberately does not inject into them, and which is not
        # in their _fields. The web client would then request a field the ORM cannot read.
        #
        # The base fields a concrete model really has are injected into _fields by
        # _build_poly_fields, so super().fields_get() already reports them. Anything this
        # merge would add on top is, by construction, something the model does not have.
        return result

    def _determine_fields_to_fetch(self, field_names=None, ignore_when_in_cache=False):
        """
        Override to avoid ValueError on polymorphic models when a field is not
        found on the current model but might exist in the polymorphic hierarchy.
        """
        # [poly][20.0] field_names=None means "every prefetchable field"
        # (models.py:3180-3182), and there is no list to filter. That is how it arrives from
        # search_fetch (models.py:1485), which in 18.0 did not exercise this path.
        if field_names is None:
            return super()._determine_fields_to_fetch(None, ignore_when_in_cache)
        # [poly] Odoo 18: Aggressive safety for core models (res.users, ir.module.module, etc.)
        # These models might be accessed before they are fully initialized in the registry.
        # If it's not a polymorphic model, we MUST be careful not to hide real errors
        # unless it's a known problematic field during boot.
        # _poly_is_polymorphic is the cached, canonical predicate. The attribute this
        # used to test for is on no model, so every model took the non-poly branch
        # below and poly models were reported as 'non-poly' in the warning it logs.
        is_poly = _poly_is_polymorphic(self)
        
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
        # The attribute this used to test for is on no model, so every call returned here
        # and the filtering below never ran. It only drops names that are in neither
        # self._fields nor the pool's -- exactly the ones super() raises KeyError on.
        if not _poly_is_polymorphic(self):
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
        # The attribute this used to test for is on no model, so every web_read went
        # straight to super() and the polymorphic completion below never ran.
        if not _poly_is_polymorphic(self):
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

        # [poly] Infinite-recursion prevention by means of a stack on the Environment.
        # Odoo 18 calls _field_to_sql recursively for related fields.
        # On polymorphic models, those paths can become circular.
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
                    # During startup, some fields may not be registered yet.
                    if fname in ('id', 'name', 'state', 'sequence', 'company_id'):
                        from odoo.tools import SQL
                        return SQL.identifier(fname)
                raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")

            if not field.store and not self.pool.ready:
                # [poly] RECOVERY: a non-stored field used in order/search during the boot
                if self.pool.loaded:
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
                # [poly] DO NOT TOUCH the related PATHS at runtime if it fails.
                # Report the error for debugging but delegate to Odoo.
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
        module = self.env.context.get("module")
        
        # Add all polymorphic models that are currently in the registry
        # but might have been missed by standard reflection.
        for name, model in self.env.registry.items():
            if name not in all_model_names:
                # The attribute this used to test for is on no model, so this safety net
                # never added anything to the reflection list.
                if _poly_is_polymorphic(model):
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
            # _get_id sits under @api.ormcache(cache='stable') (ir_model.py:338), so THAT
            # subset has to be invalidated and not the 'default' one
            IrModel.env.transaction.invalidate_ormcache('stable')
        
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
                    if not field.string or isinstance(field.string, Sentinel):
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
odoo.fields.Many2one.convert_to_cache = poly_many2one_convert_to_cache
odoo.fields.Many2many.setup_nonrelated = poly_many2many_setup_nonrelated


# --- Odoo 18 Registry Finalization Hook ---

# RESOLUTION STRATEGY FOR ODOO 18:
# Odoo 18 introduced significant changes in model introspection during the loading phase.
# Specifically, it tries to clone field attributes (such as 'related') based on the class
# hierarchy (MRO). That conflicts with numa_poly because Odoo injects 'related' paths that
# point directly at base model names (e.g. related='conversation.driver.name')
# instead of using the polymorphic link fields declared in _depend_models (e.g. driver_id.name).
#
# The solution implemented consists of:
# 1. Patching 'Field.setup_related' to intercept paths that start with model names.
# 2. Automatically redirecting those paths through the link field detected in _depend_models.
# 3. Applying an iterative "failsafe" mechanism that strips model prefixes from the 'related'
#    paths when Odoo cannot find them as fields, avoiding fatal KeyErrors.
# 4. Making sure polymorphic Many2many fields are marked as 'related' and 'store=False'
#    to prevent Odoo from accessing physical relation tables that do not exist on the child model.

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
            # The empty value is written straight into the cache so as not to trigger
            # another read nor a compute loop. It is critical for res.lang, which accesses
            # flag_image during the startup.
            try:
                if not self:
                    continue
                field = self._fields[f_name]
                # [poly] The empty value depends on the type: a relational one can NOT be
                # False in the cache, because it then returns False instead of an empty
                # recordset and any mapped() blows up with "'bool' object is not iterable".
                empty_value = False
                if field.relational:
                    empty_value = None if field.type == 'many2one' else ()

                # [poly][20.0] It used to be `env.cache.update_raw(record, field,
                # [empty_value])`, record by record because in 18.0 it was doubted that
                # Cache.update handled a single value for several ids. `Field._update_cache`
                # (fields.py:1783) writes THE SAME value for the whole recordset, which is
                # exactly what is needed here, so the loop is redundant. The only thing
                # `update_raw` added over `update` was the context for translated fields
                # (environments.py:1264); that is kept.
                destino = self.with_context(prefetch_langs=True) if field.translate else self
                field._update_cache(destino, empty_value)
            except Exception:
                # It cannot abort the startup, but it cannot be invisible either: until
                # now this was a _logger.debug and a failure here was nowhere to be seen.
                _logger.warning(
                    "[poly] could not write the empty value into the cache of %s.%s; the "
                    "computes that depend on that field will fail for not finding it",
                    self._name, f_name, exc_info=True)
        
    return res

_original_BaseModel_fetch_query = odoo.models.BaseModel._fetch_query
odoo.models.BaseModel._fetch_query = poly_BaseModel_fetch_query


# PATCH: BaseModel._add_field interceptor, to force polymorphic fields
# [poly][20.0] _add_field stopped being a method of BaseModel: it is now the function
# add_field(model_cls, name, field, shareable) of odoo.orm.model_classes, which
# moreover rejects with a ValidationError every name that no Python class of the MRO
# declares and that does not start with 'x_' (model_classes.py:632-639). The body below
# assumes the opposite. Phase 3/4 of the redesign replaces it; see
# doc/plan-2026-09-20-odoo-20-redesign.md sections 2.1 and 2.2.
_original_BaseModel_add_field = _poly_model_classes.add_field
def poly_BaseModel_add_field(self, name, field, shareable=False):
    # [poly] Use _POLY_TECHNICAL_FIELDS (includes display_name, id, audit fields) so that
    # Odoo's own _inherits delegation for these fields is not overridden here.
    # Phase 3 of _poly_registry_setup_models handles display_name separately.
    if name not in _POLY_TECHNICAL_FIELDS:
        # [poly] STRICT ISOLATION: Delegate immediately if not a poly model
        if not _poly_is_polymorphic(self):
            return _original_BaseModel_add_field(self, name, field, shareable)

        model_class = type(self)
        # Look in the polymorphic hierarchy for whether this field should be a related.
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

                # If the field exists on the polymorphic base, we force it to be related
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
            # model; only new rows get the full poly structure). Ownership is what the
            # model DECLARES, not what its table happens to still have: a column left
            # behind by an earlier version of a bridge -- project_task.pln_constraint_type,
            # from before the planning fields moved to numa.planning.node -- is not owned
            # by anybody, and reading it gives an answer the base disagrees with.
            # Keep the concrete's own field when it declares it, or when its type differs
            # from the dependent base field (the latter would also crash registry setup).
            _keep_own = name in model_class._poly_native_field_names()
            if not _keep_own and _base_field is not None:
                _ftype = getattr(field, 'type', None)
                if _ftype and _ftype != getattr(_base_field, 'type', None):
                    _keep_own = True
            if _keep_own:
                # The concrete model's own declaration is the authority for this field.
                # Odoo merges attributes across every declaration in the MRO, and the
                # bases are in that MRO because numa_poly put them there — so an
                # attribute the concrete model does not mention is silently taken from a
                # base that has nothing to do with it.
                #
                # It broke creating a company. `res.partner` sits on
                # `numa.planning.resource`, whose `company_id` declares
                # `default=lambda self: self.env.company`; res.partner's own declares no
                # default. During a module update the merge gave every new partner the
                # current company, including the one `res.company.create` makes for a new
                # company — which then failed its own check_company. On a plain boot the
                # field is set up from its definition class alone and the leak does not
                # happen, which is why it only ever showed up under `-u`.
                _poly_drop_base_declarations(field, model_class)
                return _original_BaseModel_add_field(self, name, field)
            # Force the attributes of the field object directly, before Odoo registers it
            _poly_force_related(field, _target_related)
            field.automatic = True

            # [poly] REMOVED delattr logic: Odoo 18 manages its descriptors.
            # Mutating the field object is enough.

    return _original_BaseModel_add_field(self, name, field, shareable)
_poly_model_classes.add_field = poly_BaseModel_add_field

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
            # it DECLARES it, or when its type differs from the base -- not merely because
            # the table still carries a column, which a bridge's earlier version can leave
            # behind long after the data moved to the base.
            _keep_own = f_name in model_class._poly_native_field_names()
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
                _poly_force_related(self, _target_related)
                
                # [poly] REMOVED delattr logic: Odoo 18 manages its descriptors.
                # Mutating the field object is enough.

    return _original_Field_setup(self, model)
odoo.fields.Field.setup = poly_Field_setup

# PATCH: BaseModel.__repr__, to avoid recursion on CacheMiss
_original_BaseModel_repr = odoo.models.BaseModel.__repr__
def poly_BaseModel_repr(self):
    try:
        # Direct access to the internal data, to avoid __getattribute__
        _name = object.__getattribute__(self, '_name')
        _ids = object.__getattribute__(self, '_ids')
        return f"{_name}{_ids}"
    except Exception:
        return "BaseModel()"
odoo.models.BaseModel.__repr__ = poly_BaseModel_repr

# PATCH: poly-aware BaseModel.__contains__ — allows ``record in recordset`` between poly-sibling
# models (they share the PK / the same id in the hierarchy). The core demands ``self._name ==
# item._name`` and otherwise raises 'inconsistent models'; but a subtype (persona.fisica) and its
# base (res.partner) are the SAME record by id. Real case: account_peppol._compute_peppol_endpoint
# does ``persona.fisica._origin in res.partner(...)`` when computing on the subtype. It compares by
# id only if they are of the same poly hierarchy; the normal path (same model or str) is untouched.
_original_BaseModel_contains = odoo.models.BaseModel.__contains__

def poly_BaseModel_contains(self, item):
    item_name = getattr(item, '_name', None)
    if item_name is not None and item_name != self._name:
        try:
            if _poly_same_hierarchy(item_name, self._name, self.pool):
                return len(item) == 1 and item.id in self._ids
        except Exception:  # noqa: BLE001 — on any doubt, delegate to the core (which will validate)
            pass
    return _original_BaseModel_contains(self, item)
odoo.models.BaseModel.__contains__ = poly_BaseModel_contains


def _poly_coerce_operand(self, other):
    """If ``other`` is a recordset of a poly-sibling model of ``self`` (same hierarchy / shared
    PK), re-expresses it as a recordset of ``self``'s model (same id) so that the core's set
    operations do not reject it with 'inconsistent models'. If it does not apply (a foreign model
    or a non-recordset), returns ``other`` untouched and the core validates/rejects as always."""
    other_name = getattr(other, '_name', None)
    if other_name is not None and other_name != self._name:
        try:
            if _poly_same_hierarchy(other_name, self._name, self.pool):
                return self.browse(other._ids)
        except Exception:  # noqa: BLE001
            pass
    return other

# PATCH: poly-aware set operators. self - other (__sub__) and self & other (__and__)
# ALWAYS return a subset of self (the ids of other are only used as a membership test),
# so re-expressing other to self's model (same id through the shared PK) is safe and gives
# the correct result. Real case: the chatter's followers/recipients logic, which subtracts
# a res.partner from a recordset of the poly subtype. union/concat/__eq__ are not touched.
_original_BaseModel_sub = odoo.models.BaseModel.__sub__
def poly_BaseModel_sub(self, other):
    return _original_BaseModel_sub(self, _poly_coerce_operand(self, other))
odoo.models.BaseModel.__sub__ = poly_BaseModel_sub

_original_BaseModel_and = odoo.models.BaseModel.__and__
def poly_BaseModel_and(self, other):
    return _original_BaseModel_and(self, _poly_coerce_operand(self, other))
odoo.models.BaseModel.__and__ = poly_BaseModel_and

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
        
        # If the prefix is a polymorphic parent, redirect through the link field
        depend_models = getattr(model, '_depend_models', {}) or {}
        link_fname = None
        
        if prefix and prefix in depend_models:
            link_fname = depend_models[prefix]
        elif prefix:
            # [poly] SAFEGUARD: Avoid re-sanitizing if it's already a link field
            if prefix in model._fields and isinstance(model._fields[prefix], (PolyReference, fields.Many2one)):
                 link_fname = prefix
            else:
                # Aggressive search by model name
                for mname, lfname in depend_models.items():
                    if prefix == mname:
                        link_fname = lfname
                        break
        
        # [poly] If the link field was not found on the current model,
        # search recursively in its polymorphic parents
        if prefix and not link_fname:
            for mname, lfname in depend_models.items():
                parent_model = registry.get(mname)
                if parent_model:
                    parent_depends = getattr(parent_model, '_depend_models', {}) or {}
                    if prefix in parent_depends:
                        link_fname = lfname
                        break

        if link_fname:
            # REDIRECTION: we use the link field instead of the model name
            new_path = f"{link_fname}.{'.'.join(parts[1:])}"
            _logger.debug("[poly] Redirecting polymorphic path %s.%s: %s -> %s", model._name, self.name, related, new_path)
            
            self.related = new_path
            if hasattr(self, '_args'): self._args['related'] = self.related
            self.store = False
            related = new_path # For the following steps

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
                    if not model.pool.loaded:
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
    
    # [poly] Protection for related fields with a broken chain (related_field is None).
    # It always applies: during boot, reset_changes or any rebuild of the registry.
    _in_setup = not model.pool.loaded or not getattr(model.pool, 'ready', True)
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
        if not model.pool.loaded:
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
    if not self.pool.loaded and not self.env.context.get("poly_final_validation"):
        # It is RECORDED for the final validation. Before, only the `noupdate` ones were
        # recorded (through _validate_module_views); the rest were skipped without being
        # recorded and were never validated.
        if self.ids:
            self.pool._pending_poly_views.update(self.ids)
        return True
    
    return _original_validate_view(self, node, model_name, view_type=view_type, editable=editable, node_info=node_info)

_original_validate_module_views = None

def poly_validate_module_views(self, module):
    """
    [poly] Intercepts module view validation to defer it.
    Instead of validating now, we accumulate the view IDs for later processing.
    """
    assert not self.pool.loaded
    
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

_original_check_xml = None

def poly_check_xml(self):
    """[poly] Defer the whole validation, not half of it.

    ``poly_validate_view`` defers ``_validate_view`` while modules are loading,
    but ``_check_xml`` then runs the RelaxNG over THE SAME tree and counts on
    ``_validate_view`` having normalized it already: ``_validate_tag_search`` takes
    the ``<searchpanel>`` out of the ``<search>`` precisely because the RNG does not
    know how to validate its fields (``icon``, ``icon_class`` and ``enable_counters``
    are not in common.rng). With half of it deferred the panel was still there and
    the RNG rejected a view that Odoo considers valid: no module could extend a
    search view with a searchpanel —``hr.view_employee_filter``, for instance— while
    numa_poly was installed.

    What IS done now is resolving the inheritance. It does not depend on the MRO, and
    its error ("such element cannot be located in parent view") points at the file and
    the line, which is where it helps; deferring it would leave it without context.
    """
    if self.pool.loaded or self.env.context.get('poly_final_validation'):
        return _original_check_xml(self)

    if self.ids:
        self.pool._pending_poly_views.update(self.ids)

    from lxml import etree as _etree
    for view in self:
        if not view.arch:
            continue
        try:
            if view.inherit_id:
                view._valid_inheritance(_etree.fromstring(view.arch))
            view._get_combined_arch()
        except (_etree.ParseError, ValueError, TypeError) as e:
            err = ValidationError(
                _("Error while parsing or validating view:\n\n%(error)s", error=e)
            ).with_traceback(e.__traceback__)
            err.context = getattr(e, 'context', None)
            raise err from None
    return True

def _patch_ir_ui_view():
    global _original_validate_view, _original_NameManager_must_have_fields, _original_validate_module_views
    if _original_validate_view is not None:
        return
    
    import odoo.addons.base.models.ir_ui_view as ir_ui_view_mod

    # [poly][20.0] The class was renamed to IrUiView (ir_ui_view.py:146); in 18.0
    # it was View. This used to be `if hasattr(mod, 'View')`, so when the name
    # changed the patch stopped being installed IN SILENCE: views were no longer
    # deferred and validation during the load went back to failing on polymorphic
    # fields that were still incomplete. If it changes again tomorrow, let it show.
    View = getattr(ir_ui_view_mod, 'IrUiView', None) or getattr(ir_ui_view_mod, 'View', None)
    if View is None:
        raise ImportError(
            "[poly] the ir.ui.view class was not found in %s: numa_poly cannot defer "
            "view validation during the load" % ir_ui_view_mod.__name__)

    _original_validate_view = View._validate_view
    View._validate_view = poly_validate_view

    global _original_check_xml
    _original_check_xml = View._check_xml
    View._check_xml = poly_check_xml

    _original_validate_module_views = View._validate_module_views
    View._validate_module_views = poly_validate_module_views

    _original_NameManager_must_have_fields = ir_ui_view_mod.NameManager.must_have_fields
    ir_ui_view_mod.NameManager.must_have_fields = poly_NameManager_must_have_fields

    _logger.debug("[poly] the ir.ui.view class has been patched (%s)", View.__name__)

# PATCH: tools.convert.convert_xml_import to ensure patches are applied
_original_convert_xml_import = odoo.tools.convert.convert_xml_import

def poly_convert_xml_import(env, module, fp, idref, mode, noupdate):
    _patch_ir_ui_view()
    return _original_convert_xml_import(env, module, fp, idref, mode, noupdate)

odoo.tools.convert.convert_xml_import = poly_convert_xml_import
odoo.fields.Many2many.read = poly_many2many_read
odoo.fields.Many2many.setup_nonrelated = poly_many2many_setup_nonrelated


    # [poly] DEPRECATED: Deep fix is no longer needed with the new flattening strategy.

# [poly][20.0] Contributing twice to the same model would reorder _base_classes__,
# because LastOrderedSet keeps the last appearance. The mark goes on the registry
# itself and not in a dictionary keyed by id(): object ids are recycled, and a new
# registry inherited the mark of an old one already freed, so that its models were
# never declared.
_POLY_CONTRIBUTED_ATTR = '_poly_contributed__' 


def _poly_declared_fields(cls, propios_de=None):
    """[poly][20.0] Fields declared in the DEFINITION classes of *cls*.

    ``_fields`` is only populated during ``_setup`` (``model_classes.py:391``
    empties it at the start of each pass), and the contribution runs before that:
    reading it there returns empty. The definitions, on the other hand, exist from
    the moment the module was imported, because ``Field.__set_name__`` stacks them
    up in ``_field_definitions`` as the class is created.

    :param propios_de: if a model name is given, only the fields declared BY that
        model are returned -- the ones coming from a mixin the model inherits with
        ``_inherit`` are left out. See ``_poly_base_field_names`` for the why.
    :return: ``{name: field_definition}``
    """
    declarados = {}
    for klass in cls.mro():
        if getattr(klass, 'pool', None) is not None:
            continue                       # registry class, not a definition class
        if propios_de is not None and not _poly_class_declares_model(klass, propios_de):
            continue
        for field in getattr(klass, '_field_definitions', ()):
            declarados.setdefault(field.name, field)
    return declarados


def _poly_class_declares_model(klass, model_name):
    """True if *klass* is a definition class OF the model *model_name*.

    The one that declares it (``_name == model_name``) is, and so is the one that
    extends it from another module (``_name`` absent or equal, with ``model_name``
    in ``_inherit``). A mixin is not: ``MailThread`` has ``_name = 'mail.thread'``,
    and its fields belong to mail.thread, not to whoever inherits it.
    """
    nombre = getattr(klass, '_name', None)
    if nombre in (None, model_name):
        return True
    heredados = getattr(klass, '_inherit', None) or ()
    if isinstance(heredados, str):
        heredados = (heredados,)
    return model_name in heredados


def _poly_base_field_names(registry, base_name, _vistos=None):
    """OWN fields of a polymorphic base, transitively through ``_depend_models``.

    It walks ``_depend_models`` upwards because, at contribution time, the base has
    not received anything from its own bases yet: that only happens when
    ``_setup_models__`` rebuilds everything.

    "Own" excludes what the base inherits from a mixin, and that is not a matter of
    style: without that filter, the set depended on whether the base's registry
    class was already built when the contribution ran. On a clean startup
    ``registry[base]`` is the raw class and ``fsm.definition`` gave 14 fields; on a
    later rebuild it already carries ``mail.thread`` and ``mail.activity.mixin`` in
    the MRO and gave 42. **The same code and the same base produced a different
    polymorphic model depending on the build order**: in the fat variant,
    ``message_ids`` came to be read from the base's row instead of its own, and 17
    computed fields ended up declared ``compute`` and ``related`` at the same time
    (Odoo warned and discarded the compute).

    The filter is also the right one on the merits: the contribution declares
    ``_inherit = [model] + bases``, so everything the base inherits from a mixin
    reaches the concrete model by that same path. Redirecting it with a ``related``
    adds nothing; only what is the base's data has to be redirected.
    """
    if _vistos is None:
        _vistos = set()
    if base_name in _vistos or base_name not in registry:
        return {}
    _vistos.add(base_name)
    base_cls = registry[base_name]
    declarados = dict(_poly_declared_fields(base_cls, propios_de=base_name))
    for abuelo in _poly_collect_depend_models(base_cls):
        for nombre, campo in _poly_base_field_names(registry, abuelo, _vistos).items():
            declarados.setdefault(nombre, campo)
    return declarados


def _poly_contribute_definitions(registry, model_names, declared_inherits=None):
    """[poly][20.0] Declare the polymorphic bases as model definitions.

    For each polymorphic model it builds a synthetic definition whose ``_inherit``
    names the model itself and its bases (those of ``_depend_models``, plus
    ``ir.poly_base``), and contributes it with ``add_to_registry``. It is the same
    mechanism Odoo's own suite uses to add definitions at runtime
    (``odoo/addons/test_base/tests/test_orm/test_fields.py:4694``).

    From there Odoo computes ``_base_classes__`` by itself: it puts in the registry
    classes of the bases, which is exactly what the MRO injection did by hand, and
    leaves the model's own definition in front, which is the order the injection
    wanted so that the concrete model's overrides would win.

    :param registry: the registry being built
    :param model_names: names of the polymorphic models detected
    :return: the names a definition was contributed for in this pass
    """
    from odoo.orm.model_classes import add_to_registry

    # [20.0] What has been contributed is remembered WITH ITS BASES, not by name
    # alone. A later module can add a base to a model that was already contributed --
    # `numa_conversation_fsm` adds `fsm.instance` to `conversation.message`, which
    # `numa_conversation_engine` had already declared over `digital.event` -- and a
    # name-only mark meant that model was never contributed again, so it never got the
    # fields of the base it had just gained.
    #
    # Its children did, though: they are contributed later, they walk `_depend_models`
    # transitively, and they redirect what they find through their own link. So
    # `conversation.message.email` asked for `name` (which `fsm.instance` declares) as
    # `related='poly_id.name'`, and `conversation.message` -- never re-contributed --
    # had no `name` for it to point at:
    #
    #     KeyError: Field name referenced in related field definition
    #               conversation.message.email.name does not exist.
    #
    # It only showed on a CLEAN database. Installing the same modules one at a time on
    # an accumulating one worked, because each run rebuilt the registry from scratch
    # with every `_depend_models` already in place -- which is exactly the kind of
    # false green this module's own docstrings warn about.
    done = registry.__dict__.get(_POLY_CONTRIBUTED_ATTR)
    if done is None:
        done = {}
        setattr(registry, _POLY_CONTRIBUTED_ATTR, done)
    elif isinstance(done, set):
        # A registry carried over from before this was a mapping.
        done = {name: None for name in done}
        setattr(registry, _POLY_CONTRIBUTED_ATTR, done)
    contributed = []
    for model_name in sorted(model_names):
        if model_name == 'ir.poly_base' or model_name not in registry:
            continue
        model_class = registry[model_name]
        if not isinstance(model_class, type):
            continue

        dep_map = _poly_collect_depend_models(model_class)
        parents = [name for name in dep_map if name in registry]
        # The signature is taken BEFORE `ir.poly_base` is appended below, so that it
        # describes what the model declares rather than what the mechanism adds.
        firma = tuple(parents)
        if done.get(model_name) == firma:
            continue
        if 'ir.poly_base' in registry and 'ir.poly_base' not in parents:
            parents.append('ir.poly_base')
        if not parents:
            continue

        # The link fields are DECLARED together with the bases, for the same reason:
        # a field added to the registry class after the setup does not survive the
        # next one, because _setup() rebuilds _fields__ from the definitions
        # (model_classes.py:373). Declared here it is an attribute of a real Python
        # class, so it rebuilds itself on every pass.
        #
        # A PolyReference is not shareable by construction -it is non-stored and
        # belongs to this registry-, so it is declared with _shareable=False so that
        # it does not enter SHARED_FIELD_CACHE (fields.py:422).
        # [20.0] The parents are followed by every mixin they themselves provide and
        # the concrete model already inherits directly. Without that, the order is
        # impossible for C3: `conversation.session` declares `mail.thread`, and
        # `fsm.instance` -- the base being added -- has `mail.thread` in its own MRO,
        # so the base list asked for `mail.thread` BEFORE `fsm.instance` while
        # `fsm.instance`'s own linearisation puts it after. The registry refused the
        # whole model with "Cannot create a consistent method resolution order".
        #
        # Naming those mixins again after the parents is enough, because the `bases`
        # accumulator in `add_to_registry` (model_classes.py:207) is a
        # `LastOrderedSet`: re-adding a class moves it behind what came before.
        #
        # [20.0] BOTH sides of this are read from the DECLARATIONS, not from a class's
        # `__mro__`. Reading the MRO worked on a clean install and not on an update: on
        # a `-u` pass the parent's registry class is not set up yet either, so
        # `fsm.instance.__mro__` did not mention `mail.thread`, `compartidos` came out
        # empty, and the MRO conflict came straight back -- `conversation.session`
        # could not be built at all. What a model declares does not depend on when the
        # pass runs.
        declared_inherits = declared_inherits or {}

        def _ancestros_declarados(nombre, vistos=None):
            if vistos is None:
                vistos = set()
            for padre in declared_inherits.get(nombre, ()):
                if padre in vistos:
                    continue
                vistos.add(padre)
                _ancestros_declarados(padre, vistos)
            return vistos

        # Only what the model inherits DIRECTLY, and IN ITS ORIGINAL ORDER.
        #
        # Direct, because C3 constrains the order of the direct bases; re-listing a
        # transitive ancestor adds an order nobody asked for, and doing that produced a
        # conflict of its own.
        #
        # In order, because re-listing moves these to the end and whatever order they
        # are given becomes their new relative order. Taking them from a set reversed
        # `mail.thread` and `mail.activity.mixin`, which is an order the model never
        # declared, and C3 refused that too.
        directos = []
        for b in getattr(model_class, '_base_classes__', ()):
            nombre = getattr(b, '_name', None)
            if nombre and nombre not in directos:
                directos.append(nombre)
        for nombre in declared_inherits.get(model_name, ()):
            if nombre not in directos:
                directos.append(nombre)

        compartidos = []
        for nombre in directos:
            if nombre in (model_name, 'base') or nombre in parents:
                continue
            if any(nombre in _ancestros_declarados(p) for p in parents):
                compartidos.append(nombre)

        atributos = {
            '__module__': __name__,
            '_module': None,
            '_name': model_name,
            '_inherit': [model_name] + parents + compartidos,
        }
        # What the model declares on its own is its own and is not replaced by a
        # version related to the base: that is the no-shadow rule.
        nativos = set(_poly_declared_fields(model_class))

        for base_name, link_name in dep_map.items():
            if base_name not in registry or not link_name:
                continue
            if link_name not in nativos:
                atributos[link_name] = PolyReference(base_name, _shareable=False)

            # The fields that only exist on the base are declared RELATED through
            # the link field: writing one writes the base's row, which is what in
            # 18.0 was achieved by flipping store/related on the shared Field.
            # readonly=False is what makes it writable: the related branch of
            # _get_attrs sets readonly=True by default (fields.py:484), and a
            # read-only related accepts the write and discards it, which is exactly
            # the failure this module exists to prevent. A related is already
            # non-shareable by construction (fields.py:422), so it does not enter
            # SHARED_FIELD_CACHE.
            for fname, campo_base in _poly_base_field_names(registry, base_name).items():
                if fname in nativos or fname in atributos or fname in _POLY_TECHNICAL_FIELDS:
                    continue
                # The related branch sets copy=False by default (fields.py:483), and
                # an inherited field is copied like any other of the record: without
                # this, duplicating a concrete model lost everything that lives on
                # the base. What the base said explicitly is respected.
                args_base = getattr(campo_base, '_args__', None) or {}
                atributos[fname] = type(campo_base)(
                    related='%s.%s' % (link_name, fname),
                    readonly=False,
                    copy=args_base.get('copy', True),
                    _shareable=False,
                )

        definition = odoo.models.MetaModel(
            'PolyContribution_%s' % model_name.replace('.', '_'),
            (odoo.models.Model,),
            atributos,
        )
        try:
            add_to_registry(registry, definition)
        except Exception:
            _logger.error("[poly] could not declare the polymorphic base of %s (bases: %s)",
                          model_name, parents, exc_info=True)
            continue
        done[model_name] = firma
        contributed.append(model_name)
        _logger.debug("[poly] %s declares its bases: %s", model_name, parents)

    if contributed:
        _logger.info("[poly] %d polymorphic model(s) declared their bases", len(contributed))
    return contributed


_original_Registry_setup_models = odoo.modules.registry.Registry._setup_models__

def _poly_registry_setup_models(self, cr, model_names=None):
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
    # The hierarchy map is not valid while the setup lasts: until it is rebuilt at the end,
    # _poly_is_outside_hierarchy answers False and everyone takes the tolerant path.
    self._poly_hierarchy_model_names = None

    # [poly] Clear the schema (physical column) caches on every registry (re)build:
    # a module update (-u) may have added/removed columns, which would make the cached
    # information stale; this also bounds the caches' lifetime to a single registry
    # generation instead of growing across reloads.
    _POLY_LEAF_COLUMNS.clear()
    _POLY_COLUMN_CACHE.clear()
    _POLY_NATIVE_FNAMES.clear()

    # [poly] Same reasoning for the graph caches the ownership probe reads on every
    # write: a module update can add a base to a model, which changes what its records
    # may own, and a stale answer there is the difference between a record being
    # completed and being reported as somebody else's.
    _POLY_ANCESTORS.clear()
    _POLY_ACCEPTABLE_OWNERS.clear()
    _POLY_REPORTED_COLLISIONS.clear()
    _POLY_REPORTED_UNOWNED_STAMPS.clear()
    _POLY_SUBTYPES.clear()
    _POLY_BASE_REFERENCE_FIELDS.clear()
    _POLY_RENUMBER_RANK.clear()
    _POLY_TRANSITION_FINISHED.clear()

    # [poly] Technical access to core classes
    cls_PolyBase = PolyBase
    cls_PolyModel = PolyModel
    cls_PolyTransientModel = PolyTransientModel

    # [poly][20.0] The declarations are indexed ONCE, here, not searched per model.
    #
    # `_depend_models` is authoritative on the DEFINITION classes, and on the first
    # pass of a clean install they are not in the registry class's MRO yet -- so the
    # two checks below cannot see them. `MetaModel._module_to_models__` holds every
    # definition class Odoo has imported, whatever its Python base, which is the set
    # actually meant.
    #
    # It is indexed once because the obvious way is quadratic: asking that question
    # per model is O(models x definitions), and `_setup_models__` runs once per module
    # loaded, so it becomes O(modules x models x definitions) and the load crawls to a
    # halt. One pass over the definitions, keyed by model name, costs nothing.
    _poly_declared_depends = {}
    _poly_declared_inherits = {}
    for _defs in odoo.models.MetaModel._module_to_models__.values():
        for _def_cls in _defs:
            _nombre = _def_cls.__dict__.get('_name')
            if not _nombre:
                continue
            _d = _def_cls.__dict__.get('_depend_models')
            if _d and isinstance(_d, (dict, OrderedDict)):
                _acumulado = _poly_declared_depends.setdefault(_nombre, OrderedDict())
                for _dm, _df in _d.items():
                    _acumulado.setdefault(_dm, _df)
            # `MetaModel` moves `_inherit` to `_inherit__` as the class is created
            # (models.py:276); read both so it does not matter which we see.
            _her = _def_cls.__dict__.get('_inherit__')
            if _her is None:
                _her = _def_cls.__dict__.get('_inherit')
            if isinstance(_her, str):
                _her = [_her]
            if _her:
                _poly_declared_inherits.setdefault(_nombre, set()).update(
                    h for h in _her if h != _nombre)

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
        if not has_depend_models and name in _poly_declared_depends:
            # The definition classes are the authority, and on a clean install they are
            # the only place the answer exists yet.
            has_depend_models = True
        
        if has_depend_models:
            poly_models_names_to_process.add(name)
            _logger.debug("[poly] Identified model to process (explicit _depend_models): %s", name)
            
            # Technical access to the base model's dependencies
            dep_map = OrderedDict()
            # The definition classes first: they are authoritative and, on a clean
            # install, the only place the answer exists before the MRO is built.
            for _dm, _df in _poly_declared_depends.get(name, {}).items():
                if _dm not in dep_map:
                    dep_map[_dm] = _df

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

    # [poly][20.0] Phase 1: declare the bases, do not inject them.
    #
    # Up to 18.0 this assigned model_class.__bases__ by hand to put in the registry
    # classes of the polymorphic bases, and dragged along everything that illegality
    # cost: re-synchronising __base_classes because _add_manual_models overwrote it,
    # excluding 'base' to avoid cascading MRO deadlocks, forcing PyType_Modified,
    # restoring the _order/_rec_name that the injected bases covered up, and an
    # interceptor of _prepare_setup to diagnose the assignment that would fail.
    #
    # Odoo 20 computes __bases__ from the model definitions and asserts that nobody
    # touched it afterwards (model_classes.py:353-360). So now it is asked instead of
    # fought: one synthetic definition per polymorphic model whose _inherit names its
    # bases. Odoo puts the registry classes of those bases in _base_classes__ on its
    # own, in the same order the injection wanted (the model's own definition first,
    # the bases after), so that the concrete model's overrides still win and there is
    # nothing to restore.
    #
    # See doc/plan-2026-09-20-odoo-20-redesign.md, section 2.1.
    _poly_contribute_definitions(self, poly_models_names_to_process,
                                 _poly_declared_inherits)

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

    res = _original_Registry_setup_models(self, cr, model_names)

    # [poly] Phase 3: Post-setup cache invalidation.
    # Field injection is now handled by _setup_base via _build_poly_fields.
    if 'field_computed' in self.__dict__:
        del self.__dict__['field_computed']

    # [poly] Report a field name that two bases of the same model both provide.
    #
    # Only one of them can be `model.<name>`, and which one is decided here (the first in
    # `_depend_models`); the other becomes unreachable under that name. Odoo notices when
    # the two are Selections with different values and says so once per model of the
    # hierarchy -- 219 lines on a real installation, none of which name the two bases.
    # This says it once, and says which one won.
    #
    # It cost a real bug before it existed: `conversation.message` sits on `digital.event`
    # (state = new/pending/processed/error) and on `fsm.instance` (state = init/running/
    # paused/ended/error). digital.event won, so every `message.state == 'init'` in
    # numa_conversation_fsm compared an event's processing status against an FSM state and
    # was dead code that nothing reported.
    _poly_report_base_field_collisions(self)
    # [poly] Clear the polymorphic model name cache so stale results from the
    # previous registry state don't persist into the newly rebuilt registry.
    _poly_is_polymorphic_cache.clear()

    # [poly] concrete_model_id belongs to ir.poly_base; on the SUBTYPES it must not be a
    # stored column. Because of the injected MRO (ir.poly_base ends up more derived than the
    # subtype), ir.poly_base's required+stored definition wins over the store=False override,
    # and Odoo would create a NOT NULL column on the subtype that the create never populates
    # -> NotNullViolation. Here, after the setup, we force the subtype's field to non-stored
    # computed: the value is read from the shared poly_base (through
    # _compute_concrete_model_id), with no column of its own.
    for _mname, _mcls in self.items():
        if not getattr(_mcls, '_depend_models', None):
            continue  # a base ({}) or a non-poly model: leave the field as it is
        _f = _mcls._fields.get('concrete_model_id')
        if _f is not None and getattr(_f, 'store', False):
            _f.store = False
            _f.required = False
            _f.compute = '_compute_concrete_model_id'
            _f.compute_sudo = True
            _f.readonly = True

    # [poly] _rec_name: ir.poly_base declares `_rec_name = 'id'` (it has no name field), and
    # through the injected MRO that value is explicitly inherited by ALL the subtypes, overriding
    # Odoo's automatic default (`if 'name' in _fields: _rec_name = 'name'`). Result: display_name
    # and name_search of a poly model WITH a name field showed "<model>,<id>" instead of the name
    # (it breaks the rendering of the polymorphic lists in the UI). Here we restore Odoo's
    # intention: if the poly model has 'name' and was left with an inherited _rec_name='id',
    # use 'name'.
    for _mname, _mcls in self.items():
        if _mname == 'ir.poly_base':
            continue
        if getattr(_mcls, '_depend_models', None) is None:
            continue  # not a poly model
        if getattr(_mcls, '_rec_name', None) == 'id' and 'name' in _mcls._fields:
            _mcls._rec_name = 'name'

    # [poly] display_name: poly uses _inherits with the link fields, and Odoo delegates
    # display_name to the FIRST _inherits parent (an infrastructure link, e.g. behavior_a_id /
    # test2_id). Result:
    # the display_name of a subtype showed that of the first base ("<base>,<id>") instead of its
    # own -> it breaks the rendering of the polymorphic lists. Here we un-delegate it: we hand it
    # back to Odoo's standard _compute_display_name, which respects the concrete model's
    # _rec_name.
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
        # CAREFUL: coming from a related, the field's `search` was left pointing at
        # _search_related (which with related=None matches everything -> name_search did not
        # filter). Restore display_name's standard search so that name_search uses _rec_name.
        _dn.search = '_search_display_name'

    # [poly] Grafted Selections: poly injects the inherited fields as related. For a related
    # Selection, Odoo's setup leaves `.selection` as a CALLABLE (it resolves it from the target).
    # That breaks code introspecting `.selection` assuming a list, e.g. account's default:
    #   display_invoice_edi_format = Boolean(default=lambda self: len(self._fields['invoice_edi_format'].selection))
    # -> len(callable) blows up when creating a poly subtype of res.partner. We resolve the
    # callable to the static list of the parent field (which is where it comes from), preserving
    # the related semantics of the value but leaving `.selection` introspectable as a list.
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

    # Models that take part in poly hierarchies: the rest go back to Odoo's original path
    # at runtime (see _poly_is_outside_hierarchy).
    self._poly_hierarchy_model_names = _poly_registry_hierarchy_models(self)

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

odoo.modules.registry.Registry._setup_models__ = _poly_registry_setup_models

# [poly][20.0] Here lived the post-load stabilization, hanging from
# Registry.signal_changes. That hook point does not exist in Odoo 20, and what the
# stabilization did -repeat the setup to re-inject the MRO- stopped being needed
# when phase 3 swapped injection for declaration: Odoo builds the bases on its own,
# on the first pass, and there is nothing to redo afterwards.
#
# The only thing left pending for the end of the load is validating the views that
# were deferred, and that has had an anchor of its own all along:
# ir.poly_base._register_hook, which Odoo calls with every module loaded
# (registry.py:577). It is moreover the only one that works on a cold startup, because
# numa_poly is imported INSIDE load_module_graph and a wrapper of that function
# does not get to apply the first time.


# PATCH: load_module_graph to intercept the end of module loading
_original_load_module_graph = odoo.modules.loading.load_module_graph

def poly_load_module_graph(env, graph, update_module=False, report=None, install_demo=True):
    """[poly] Validate, at the end of the load, the views that were left pending.

    The signature is Odoo 20's (``modules/loading.py:114-120``); in 18.0 it was
    ``(env, graph, status, perform_checks, skip_modules, report, models_to_check)``.
    """
    res = _original_load_module_graph(env, graph, update_module=update_module,
                                      report=report, install_demo=install_demo)
    registry = env.registry
    if registry._pending_poly_views:
        _logger.debug("[poly] module loading is over: the pending views are validated")
        registry._poly_finalize_view_validation(env.cr)
    return res

odoo.modules.loading.load_module_graph = poly_load_module_graph
