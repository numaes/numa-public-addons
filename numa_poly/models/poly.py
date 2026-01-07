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
"""

import logging
import pprint
from collections import OrderedDict, defaultdict, deque
import inspect

from operator import attrgetter, itemgetter

from attr import attributes
from docutils.nodes import field_name

import odoo
from odoo import api, _, exceptions
from odoo import models, fields
from odoo.models import BaseModel, MetaModel
import odoo
from odoo import SUPERUSER_ID
from odoo import api
from odoo import tools
from odoo.api import ContextType, DomainType, IdType, NewId, M, T
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
from odoo.tools import (
    clean_context, config, date_utils, discardattr,
    DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, format_list,
    frozendict, get_lang, lazy_classproperty, OrderedSet,
    ormcache, partition, Query, split_every, unique,
    SQL, sql,
)
from odoo.tools.misc import LastOrderedSet, ReversedIterable, unquote, Sentinel, SENTINEL

from odoo.models import LOG_ACCESS_COLUMNS, INSERT_BATCH_SIZE, UPDATE_BATCH_SIZE, SQL_DEFAULT, GC_UNLINK_LIMIT

from . import expression

from odoo.fields import first, MetaField, T


import typing
if typing.TYPE_CHECKING:
    from collections.abc import Reversible
    from odoo.modules.registry import Registry

from odoo.api import Self, ValuesType, IdType


_logger = logging.getLogger(__name__)


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

    def as_concrete_model(self):
        """
        Convert this base record to its concrete model representation.
        If no concrete model is defined (legacy records), returns self.

        Returns:
            The same record but as an instance of its concrete model class.
        """
        self.ensure_one()
        if not self.concrete_model_id:
            return self
        concrete_model = self.env[self.concrete_model_id.model]
        return concrete_model.browse(self.id).exists() or self


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

        Args:
            value: The value to convert
            record: The record containing this field

        Returns:
            A record instance of the comodel with the same ID as the current record
        """
        return record.pool[self.comodel_name](record.env, (record.id,), (record.id,))

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
        # base case: do the regular access
        if records is None or len(records._ids) <= 1:
            return super().__get__(records, owner)
        # multirecord case: use mapped
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



class PolyBase(BaseModel):
    """
    Base class for all polymorphic models in Odoo.

    This class extends the standard Odoo BaseModel to implement polymorphic inheritance.
    Polymorphic models can inherit fields and behavior from multiple parent models
    while maintaining a single database record.

    The polymorphic inheritance is configured through the _depend_models attribute,
    which is a position-ordered dictionary mapping parent model names to field names:

    Example:
        _depend_models = {
            'a.model': 'a_field_id',
            'b.model': 'b_field_id'
        }

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

    def as_concrete_model(self):
        """
        Convert this record to its most concrete model representation.
        If no concrete model is defined (legacy records), returns self.
        """
        self.ensure_one()
        # If the field is not even defined on this model, we are the concrete representation
        if self._depend_models == None:
            return self
        poly_base = self.env['ir.poly_base'].sudo().browse(self.id)
        if poly_base.concrete_model_id.model == self._name:
            return self
        concrete_model = self.env[poly_base.concrete_model_id.model]
        return concrete_model.browse(self.id).exists() or self

    def _compute_concrete_model_id(self):
        """
        Compute the concrete_model_id field for polymorphic models.
        Handles fallback to current model for legacy records (no ir.poly_base entry).
        """
        for record in self:
            # Check existence in ir.poly_base using the shared ID
            poly_base = self.env['ir.poly_base'].sudo().browse(record.id)
            if poly_base.exists():
                record.concrete_model_id = poly_base.concrete_model_id
            else:
                # Legacy record: assume current model is the concrete one
                record.concrete_model_id = self.env['ir.model']._get_id(record._name)

    def compute_poly_base_id(self):
        """
        Compute the poly_base_id field for each record.

        This method sets the poly_base_id field to the record's ID,
        establishing the link to the ir.poly_base record.
        """
        for instance in self:
            instance.poly_base_id = instance.id

    @classmethod
    def _build_model(cls, pool, cr):
        """
        Instantiate a given model in the registry.

        This method extends the standard Odoo model building process to implement
        polymorphic inheritance. It creates or extends a "registry" class for the
        given model that inherits from all the dependent models specified in
        _depend_models.

        The registry class carries inferred model metadata and inherits (in the
        Python sense) from all classes that define the model and its dependencies,
        and possibly other registry classes.

        Args:
            pool: The model registry pool
            cr: Database cursor

        Returns:
            The built model class

        Raises:
            TypeError: If a dependent model doesn't exist or is not polymorphic
        """
        # First build the model using the standard Odoo mechanism
        model_class_without_depends = super(PolyBase, cls)._build_model(pool, cr)

        # Only apply polymorphic inheritance if _depend_models is defined
        if hasattr(cls, '_depend_models') and cls._depend_models != None:

            # All models except 'ir.poly_base' implicitly depend on 'ir.poly_base'
            name = cls._name
            parents = list(cls._depend_models.keys())
            if name != 'ir.poly_base':
                parents.append('ir.poly_base')

            # Determine all the classes the model should inherit from
            bases = LastOrderedSet([cls])
            for parent in parents:
                # Check that the parent model exists
                if parent not in pool:
                    raise TypeError("Model %r depends from non-existing model %r." % (name, parent))

                parent_class = pool[parent]
                if parent == name:
                    # Self-reference: add all the bases of the parent
                    if not hasattr(parent_class, '__depends_base_classes'):
                        parent_class.__depends_base_classes = OrderedSet()
                    for base in parent_class.__depends_base_classes:
                        bases.add(base)
                else:
                    # Check that the parent is polymorphic (except for ir.poly_base)
                    if parent_class._name != 'ir.poly_base' and parent_class._depend_models == None:
                        raise TypeError("Model %r depends from non-polymorphic model %r. Only polymorphic is allowed" %
                                        (name, parent))

                    # Add the parent class to the bases
                    bases.add(parent_class)

                    # Register this model as a child of the parent
                    if not hasattr(parent_class, '_depends_children'):
                        parent_class._depends_children = OrderedSet()
                    parent_class._depends_children.add(name)

            # Store the base classes for later use
            model_class_without_depends.__depends_base_classes = tuple(bases)

            # Add the model to the registry
            pool[name] = model_class_without_depends

        return model_class_without_depends

    def _setup_base(self):
        """
        Set up the model's base attributes.

        This method extends the standard Odoo setup process to build the dependent
        model attributes for polymorphic models.
        """
        super()._setup_base()

        # Only build dependent model attributes if this is a polymorphic model
        if self._depend_models:
            self._build_dependant_model_attributes()

    def _register_hook(self):
        """
        Perform actions right after the registry is built.

        This method extends the standard Odoo registry hook to ensure that
        polymorphic models don't have ID conflicts. It checks the current
        sequence values for all dependent models and adjusts the ir.poly_base
        sequence if necessary to avoid ID clashes.
        """
        super()._register_hook()

        def get_next_id(base_name) -> int:
            """
            Get the next ID that would be assigned for a model.

            Args:
                base_name: The name of the model

            Returns:
                The next ID value that would be assigned
            """
            base_model = self.env[base_name]
            if base_model._table:
                self.env.cr.execute(f'''
                    SELECT pg_sequence_last_value('{base_model._table}_id_seq')
                ''')
                next_id = self.env.cr.fetchall()[0][0]
                return next_id
            else:
                return 1

        # Only perform ID conflict resolution for polymorphic models
        if self._depend_models != None:
            # Ensure no polymorphic models have existing records
            # with IDs clashing with newly created polymorphic records
            poly_base_id = get_next_id('ir.poly_base')
            for base_name in self._depend_models.keys():
                current_id = get_next_id(base_name)
                if current_id and current_id > (poly_base_id or 0):
                    poly_base_id = current_id
                    self.env.cr.execute(f'''
                        ALTER SEQUENCE IF EXISTS ir_poly_base_id_seq RESTART WITH {current_id + 1};
                    ''')

    @classmethod
    def _build_dependant_model_attributes(self):
        """
        Initialize and build the attributes of a polymorphic model.

        This method is responsible for:
        1. Creating the basic polymorphic fields (poly_base_id, concrete_model_id)
        2. Setting up audit fields (create_uid, create_date, etc.)
        3. Creating reference fields to all dependent models
        4. Inheriting all fields from dependent models as related fields
        5. Inheriting non-field attributes from dependent models

        This is the core of the polymorphic inheritance mechanism, as it makes
        all fields from dependent models available on the polymorphic model.
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
        for model_name in reversed(self._depend_models.keys()):
            def add_subfields(mm):
                """
                Recursively add fields from a dependent model and its dependencies.

                Args:
                    mm: The name of the model to add fields from
                """
                if mm == 'ir.poly_base':
                    return  # Skip ir.poly_base as its fields are already handled

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
                for attribute_name in base_model.mro()[1].__class__.__dir__(base_model):
                    if attribute_name.startswith('__'):
                        continue
                    attribute = getattr(base_model, attribute_name)
                    if not isinstance(attribute, fields.Field) and \
                       not hasattr(self, attribute_name):
                        setattr(self, attribute_name, attribute)

                # Recursively add fields from the model's dependencies
                for sub_base in base_model._depend_models.keys():
                    add_subfields(sub_base)

            # Start the recursive field addition
            add_subfields(model_name)

        # Create reference fields to all dependent models
        related_bases = {}
        for base_model, base_field in reversed(self._depend_models.items()):
            related_bases[base_model] = base_field
            set(base_field,
                PolyReference(comodel_name=base_model,
                              string=f'Base for {base_model}',
                              automatic=True, readonly=True)
                )

        # Create related fields for all fields from dependent models
        related_counter = 1
        for new_field_name in related_fields.keys():
            model, field_name, field_type, comodel, description = related_fields[new_field_name]

            # Skip if the field is already defined
            if field_name in self._fields:
                continue

            # If the model isn't directly in related_bases, create a new reference field
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
                new_field = field_subclass(
                    comodel_name=comodel,
                    string=description.string,
                    related=f'{related_bases[model]}.{field_name}',
                    automatic=True,
                )
            elif field_subclass:
                new_field = field_subclass(
                    string=description.string,
                    related=f'{related_bases[model]}.{field_name}',
                    automatic=True,
                    readonly=False,
                )
            else:
                raise TypeError(_('Unsupported field type %s for field %s') %
                                (field_type, field_name))

            # Add the field to the model
            set(field_name, new_field, related_bases[model])

        # Add _depends methods
        #  (not fields, only if not already overloaded, in inverted _depends order, recursively)

        for base in reversed(list(self._depend_models.keys())):
            attributes = vars(self.pool[base])
            for attribute_name, attribute_value in attributes.items():
                if not isinstance(attribute_value, fields.Field) and \
                   attribute_name not in vars(self):
                    setattr(self, attribute_name, attribute_value)

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

        Args:
            data_list: List of dictionaries containing field values

        Returns:
            The newly created records

        Raises:
            ValidationError: If trying to create a record with an ID that already exists

        TODO: Investigate if access rules should be applied base by base also
        """
        if self._depend_models == None:
            # Normal Odoo ORM model, just process it the normal way
            return super().create(data_list)
        else:
            # It is a polymorphic create
            new_records = self

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

            # Process each record to create
            for data in data_list:
                # Handle explicit ID or create a new one via ir.poly_base
                if 'id' in data:
                    # Check if record with this ID already exists
                    existing_record = self.search([('id', '=', data['id'])], limit=1)
                    if existing_record:
                        raise ValidationError(
                            _('You are trying to create a %s with explicit id %d. It exists already!') %
                            (self._name, data['id'])
                        )
                    new_id = data['id']
                else:
                    # Create a new ir.poly_base record to get a new ID
                    new_poly = self.env['ir.poly_base'].create(dict(
                        concrete_model_id=self.env['ir.model']._get_id(self._name)
                    ))
                    _logger.debug(f'Creating poly base for {self._name}, id = {new_poly.id}')
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
                        base_model.create([base_data])
                    else:
                        _logger.debug(f'Updating {base} with {base_data} for id {new_id}')
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
        result = super().unlink()

        # For polymorphic models, also delete records in dependent models
        if self._depend_models != None:
            for base in self._depend_models:
                base_model = self.env[base]
                base_model.browse(self.ids).unlink()

        return result

    def _write_multi(self, vals_list):

        """
        Low-level implementation of write() for multiple records.

        This method extends the standard Odoo write implementation to handle
        polymorphic models. For polymorphic models, it ensures that audit fields
        (write_uid, write_date) are properly updated in the ir.poly_base record.

        Args:
            vals_list: List of dictionaries containing values to write
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
                column = SQL.identifier(fname)
                # the type cast is necessary for some values, like NULLs
                expr = SQL('"__tmp".%s::%s', column, SQL(field.column_type[1]))
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
                        column=column,
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
                        column=column,
                        expr=expr,
                        fallbacks=fallbacks
                    )
                columns.append(column)
                assignments.append(SQL("%s = %s", column, expr))

            #self.env.execute_query(SQL(
                #""" UPDATE %(table)s
                #    SET %(assignments)s
                #    FROM (VALUES %(values)s) AS "__tmp"("id", %(columns)s)
                #    WHERE %(table)s."id" = "__tmp"."id"
                #""",
                #table=SQL.identifier(self._table),
                #assignments=SQL(", ").join(assignments),
                #values=SQL(", ").join(rows),
                #columns=SQL(", ").join(columns),
            #))

        # update parent_path
        if parent_records:
            parent_records._parent_store_update()


        # Update audit fields for polymorphic models
        if self._log_access and self._depend_models != None and self._name != 'ir.poly_base':
            poly_base_model = self.env['ir.poly_base']
            log_vals = {'write_uid': self.env.uid, 'write_date': self.env.cr.now()}
            poly_base_model.browse(self.ids).write(log_vals)

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        fields = super().fields_get(allfields=allfields, attributes=attributes)
        if self._depends != None and list(self._depends.keys()):
            # Ensure all dependent models are in the bases_to_create dict
            depends_reverse = list(self._depends.keys())
            depends_reverse.reverse()
            for base in depends_reverse:
                base_model = self.env[base]
                for inherited_field in base_model.fields_get(allfields=allfields, attributes=attributes):
                    if inherited_field not in fields:
                        fields[inherited_field] = inherited_field
        return fields

    def _field_to_sql(self, alias: str, fname: str, query: (Query | None) = None, flush: bool = True) -> SQL:
        """ Return an :class:`SQL` object that represents the value of the given
        field from the given table alias, in the context of the given query.
        The method also checks that the field is accessible for reading.

        The query object is necessary for inherited fields, many2one fields and
        properties fields, where joins are added to the query.

        When parameter ``flush`` is true, the method adds some metadata in the
        result to make method :meth:`~odoo.api.Environment.execute_query` flush
        the field before executing the query.
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
                'res.partner': 'partner_id'
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
        self.sudo().browse(ids).unlink()
        if len(ids) >= GC_UNLINK_LIMIT:
            self.env.ref('base.autovacuum_job')._trigger()


odoo.models.BaseModel = PolyBase
odoo.models.AbstractModel = PolyBase
odoo.models.Model = PolyModel
odoo.models.TransientModel = PolyTransientModel
odoo.fields.Many2one.convert_to_read = poly_many2one_convert_to_read
