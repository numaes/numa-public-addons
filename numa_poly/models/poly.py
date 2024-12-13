import logging
from collections import OrderedDict, defaultdict, deque

from operator import attrgetter, itemgetter

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
    _name = 'ir.poly_base'
    _description = 'Polymorphic Models Base'
    _rec_name = 'id'

    concrete_model_id = fields.Many2one('ir.model', 'Concrete Model',
                                        ondelete='cascade', required=True)

    def as_concrete_model(self):
        self.ensure_one()

        concrete_model = self.env[self.concrete_model_id.model]
        return concrete_model.browse(self.id).exists()


class PolyReference(fields.Many2one):
    auto_join = True
    store = False
    readonly = True

    def __init__(self, comodel_name: str | Sentinel = SENTINEL, string: str | Sentinel = SENTINEL, **kwargs):
        super(PolyReference, self).__init__(comodel_name=comodel_name, string=string, **kwargs)
        self.search = self._search_related

    def convert_to_record(self, value, record):
        return record.pool[self.comodel_name](record.env, (record.id,), (record.id,))

    def __get__(self, records, owner=None):
        # base case: do the regular access
        if records is None or len(records._ids) <= 1:
            return super().__get__(records, owner)
        # multirecord case: use mapped
        return records.pool[self.comodel_name](records.env, tuple(records.ids), tuple(records.ids))

    @property
    def _description_searchable(self):
        return True

    def _search_related(self, records, operator, value):
        """ Determine the domain to search on field ``self``. """

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

            if field.store:
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
    _register = False


    """Position ordered dictionary {'parent_model': 'm2o_field'} mapping the _name of the parent business
    objects to the names of the corresponding foreign key fields to use::

      _depend_models = {
          'a.model': 'a_field_id',
          'b.model': 'b_field_id'
      }

    implements full polymorphic inheritance: the new model exposes all
    the fields of the dependant models but stores none of them:
    the values themselves remain stored on the linked record.

    A direct representation of a base will be available in the corresponding field ('a_field_id', 'b_field_id')
    The Many2one field will be created automatically, it is no needed to define it explicitly

    .. warning::

      if multiple fields with the same name are defined in the
      :attr:`~odoo.models.Model._depend_models` models, the inherited field will
      correspond to the last one (in the depends list order).
    """

    _depend_models = None
    _depends_children = OrderedSet()


    _checked_id = False

    def compute_poly_base_id(self):
        for instance in self:
            instance.poly_base_id = instance.id

    #
    # Goal: try to apply inheritance at the instantiation level and
    #       put objects in the pool var
    #
    @classmethod
    def _build_model(cls, pool, cr):
        """ Instantiate a given model in the registry.

        This method creates or extends a "registry" class for the given model.
        This "registry" class carries inferred model metadata, and inherits (in
        the Python sense) from all classes that define the model, and possibly
        other registry classes.
        """

        model_class_without_depends = super(PolyBase, cls)._build_model(pool, cr)

        if hasattr(cls, '_depend_models') and cls._depend_models != None:

            # all models except 'base' implicitly depend from 'ir.poly_base'
            name = cls._name
            parents = list(cls._depend_models.keys())
            if name != 'ir.poly_base':
                parents.append('ir.poly_base')

            # determine all the classes the model should inherit from
            bases = LastOrderedSet([cls])
            for parent in parents:
                if parent not in pool:
                    raise TypeError("Model %r depends from non-existing model %r." % (name, parent))
                parent_class = pool[parent]
                if parent == name:
                    if not hasattr(parent_class, '__depends_base_classes'):
                        parent_class.__depends_base_classes = OrderedSet()
                    for base in parent_class.__depends_base_classes:
                        bases.add(base)
                else:
                    if parent_class._name != 'ir.poly_base' and parent_class._depend_models == None:
                        raise TypeError("Model %r depends from non-polymorphic model %r. Only polymorphic is allowed" %
                                        (name, parent))
                    bases.add(parent_class)
                    if not hasattr(parent_class, '_depends_children'):
                        parent_class._depends_children = OrderedSet()
                    parent_class._depends_children.add(name)

            model_class_without_depends.__depends_base_classes = tuple(bases)

            # determine the attributes of the model's class
            pool[name] = model_class_without_depends

        return model_class_without_depends

    def _setup_base(self):
        super()._setup_base()

        if self._depend_models != None:
            self._build_dependant_model_attributes()

    def _register_hook(self):
        """ stuff to do right after the registry is built """
        super()._register_hook()

        def get_next_id(base_name) -> int:
            base_model = self.env[base_name]
            if base_model._table:
                self.env.cr.execute(f'''
                    SELECT pg_sequence_last_value('{base_model._table}_id_seq')
                ''')
                next_id = self.env.cr.fetchall()[0][0]
                return next_id
            else:
                return 1

        if self._depend_models != None:
            # Ensure no polymorphic models has existing records
            # with IDs clashing with newly created polymorphic records
            poly_base_id = get_next_id('ir.poly_base')
            for base_name in self._depend_models.keys():
                current_id = get_next_id(base_name)
                if current_id and current_id > poly_base_id:
                    poly_base_id = current_id
                    self.env.cr.execute(f'''
                        ALTER SEQUENCE 'ir_poly_base_id_seq' RESTART WITH {current_id + 1};
                    ''')

    @classmethod
    def _build_dependant_model_attributes(self):
        """ Initialize base model attributes. """
        def set(name, field, related_base=None):
            _logger.debug(f'Agregando campo {name} a {self._name}'
                          f' (base: {related_base or "N/A"})')
            setattr(self, name, field)
            self._fields[name] = field
            field._direct = True
            field.prepare_setup()
            field.__set_name__(self, name)

        # Create a poly_base_id many2one
        set('poly_base_id',
            PolyReference(
                'ir.poly_base',
                string='Poly base',
                automatic=True,
                readonly=True
             )
        )

        # Create a concrete_model_id poly_base_id many2one
        set('concrete_model_id',
            fields.Many2one(
                'ir.model',
                string='Concrete model',
                related='poly_base_id.concrete_model_id',
                automatic=True,
                readonly=True
             )
        )

        # TODO log fields should be registered only on ir.poly_base
        #      currently not working
        #
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


        related_fields = {}
        for model_name, model_field in reversed(self._depend_models.items()):
            def add_subfields(mm):
                if mm == 'ir.poly_base':
                    return

                base_model = self.pool[mm]
                for subfield_name, subfield in base_model._fields.items():
                    if subfield_name not in self._fields and \
                       not subfield.related:
                        if subfield_name not in related_fields:
                            related_fields[subfield_name] = (
                                mm,
                                subfield_name,
                                subfield.type,
                                subfield.comodel_name,
                                subfield
                            )

                for sub_base in base_model._depend_models.keys():
                    add_subfields(sub_base)

            add_subfields(model_name)

        related_bases = {base_model: base_field for base_model, base_field in self._depend_models.items()}
        for base_model, base_field in related_bases.items():
            related_bases[base_model] = base_field
            set(base_field,
                PolyReference(comodel_name=base_model, string=base_model,
                              automatic=True, readonly=True)
                )

        related_counter = 1
        for new_field_name in related_fields.keys():
            model, field_name, field_type, comodel, description = related_fields[new_field_name]

            if field_name in self._fields:
                continue

            if model not in related_bases:
                if model in self._depend_models:
                    model_field = self._depend_models[model]
                else:
                    model_field = f'related_{related_counter}'
                    related_counter += 1
                related_bases[model] = model_field
                set(model_field,
                    PolyReference(comodel_name=model, string=model,
                                  automatic=True, readonly=True)
                )
            else:
                model_field = related_bases[model]
                if model_field not in self._fields:
                    set(model_field,
                        PolyReference(comodel_name=model, string=model,
                                      automatic=True, readonly=True)
                    )

            field_subclass = {
                'char': fields.Char,
                'integer': fields.Integer,
                'float': fields.Float,
                'monetary': fields.Monetary,
                'date': fields.Date,
                'datetime': fields.Datetime,
                'selection': fields.Selection,
                'many2one': fields.Many2one,
                'one2many': fields.One2many,
                'many2many': fields.Many2many,
                'text': fields.Text,
                'html': fields.Html,
                'binary': fields.Binary,
                'boolean': fields.Boolean,
            }.get(field_type)

            if isinstance(description, PolyReference):
                field_subclass = PolyReference

            if field_type in ['many2one', 'many2many', 'one2many']:
                new_field = field_subclass(
                    comodel_name=comodel,
                    string=description.string,
                    related=f'{related_bases[model]}.{field_name}',
                    automatic=True,
                    recursive=True,
                )
            elif field_subclass:
                new_field = field_subclass(
                    string=description.string,
                    related=f'{related_bases[model]}.{field_name}',
                    automatic=True,
                )
            else:
                raise TypeError(_('Unsupported field type %s for field %s') %
                                (field_type, field_name))

            set(field_name, new_field, related_bases[model])

        _logger.debug(f'_build_dependant_model_attributes finished')


    @api.model_create_multi
    def create(self, data_list: list[ValuesType]) -> Self:
        """ Create records from the stored field values in ``data_list``. """
        """ TODO Investigate if access rules should be applied base by base also """

        if self._depend_models == None:
            # Normal Odoo ORM model, just process it the normal way
            return super().create(data_list)
        else:
            # It is a polymorphic create.

            new_records = self

            inverse_related = {field_name.split('.')[-1]: field_definition
                               for field_name, field_definition in self._fields.items()
                               if field_definition.related}

            inverse_field2base = {base_field: base_name for base_name, base_field in self._depend_models.items()}

            bases_to_create = {}

            for field_name, field_definition in inverse_related.items():
                related_base = field_definition.related.split('.', 1)[0]
                if related_base != 'poly_base_id':
                    if related_base in inverse_field2base:
                        base = inverse_field2base[related_base]
                        if base not in bases_to_create:
                            bases_to_create[base] = set()
                        bases_to_create[base].add(field_name)

            for base in self._depend_models.keys():
                if base not in bases_to_create:
                    bases_to_create[base] = set()

            for data in data_list:
                if 'id' in data:
                    existing_record = self.search([('id', '=', data['id'])], limit=1)
                    if existing_record:
                        raise ValidationError(
                            _('Your are trying to create an %s with explicit id %d. It exists already!') %
                            (self._name, data['id'])
                        )
                    new_id = data['id']
                else:
                    new_poly = self.env['ir.poly_base'].create(dict(
                        concrete_model_id=self.env['ir.model']._get_id(self._name)
                    ))
                    _logger.debug(f'Creando poly base para {self._name}, id = {new_poly.id}')
                    new_id = new_poly.id

                for base, field_set in bases_to_create.items():
                    base_model = self.env[base]
                    base_data = {}
                    for field_name in field_set:
                        if field_name in data:
                            base_data[field_name] = data[field_name]
                    for field_name, field_definition in base_model._fields.items():
                        field_plain_name = field_name.split('.')[-1]
                        if field_plain_name in data:
                            base_data[field_name] = data[field_plain_name]

                    base_data['id'] = new_id
                    existing_base = base_model.search([('id', '=', new_id)], limit=1)
                    if not existing_base:
                        _logger.debug(f'Creando {base} con {base_data} para id {new_id}')
                        base_model.create(base_data)
                    else:
                        _logger.debug(f'Actualizando {base} con {base_data} para id {new_id}')
                        existing_base.write(base_data)


                # Lastly create the new records, all bases already created
                base_data = {}
                for full_field_name, field_definition in self._fields.items():
                    if not field_definition.related and field_definition.store:
                        field_name = full_field_name.split('.')[-1]
                        if field_name in data:
                            base_data[field_name] = data[field_name]

                base_data['id'] = new_id
                _logger.debug(f'Creando {self._name} con {base_data} para id {new_id}')
                new_record = super().create(base_data)
                new_records |= new_record

            return new_records

    def _prepare_create_values(self, vals_list):
        """ Modified version from Odoo. Do NOT FILTER OUT id!"""
        """ Clean up and complete the given create values, and return a list of
        new vals containing:

        * default values,
        * discarded forbidden values (magic fields),
        * precomputed fields.

        :param list vals_list: List of create values
        :returns: new list of completed create values
        :rtype: dict
        """
        #bad_names = ['id', 'parent_path']
        bad_names = ['parent_path']
        if self._log_access:
            # the superuser can set log_access fields while loading registry
            if not(self.env.uid == SUPERUSER_ID and not self.pool.ready):
                bad_names.extend(LOG_ACCESS_COLUMNS)

        # also discard precomputed readonly fields (to force their computation)
        bad_names.extend(
            fname
            for fname, field in self._fields.items()
            if field.precompute and field.readonly
        )

        result_vals_list = []
        for vals in vals_list:
            # add default values
            vals = self._add_missing_default_values(vals)

            # add magic fields
            for fname in bad_names:
                vals.pop(fname, None)
            if self._log_access:
                vals.setdefault('create_uid', self.env.uid)
                vals.setdefault('create_date', self.env.cr.now())
                vals.setdefault('write_uid', self.env.uid)
                vals.setdefault('write_date', self.env.cr.now())

            result_vals_list.append(vals)

        # add precomputed fields
        self._add_precomputed_values(result_vals_list)

        return result_vals_list

    def unlink(self):
        """ Unlink records """

        super().unlink()

        if self._depend_models != None:
            # Ensure all bases will be unlinked also
            for base in self._depend_models:
                base_model = self.env[base]
                base_model.browse(self.ids).unlink()

    def _write_multi(self, vals_list):
        """ Low-level implementation of write() """
        assert len(self) == len(vals_list)

        if not self:
            return

        # determine records that require updating parent_path
        parent_records = self._parent_store_update_prepare(vals_list)

        if self._log_access and self._name != 'ir.poly_base' and self._depend_models == None:
            # set magic fields (already done by write(), but not for computed fields)
            log_vals = {'write_uid': self.env.uid, 'write_date': self.env.cr.now()}
            vals_list = [(log_vals | vals) for vals in vals_list]

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
                assert field.store and field.column_type
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

            self.env.execute_query(SQL(
                """ UPDATE %(table)s
                    SET %(assignments)s
                    FROM (VALUES %(values)s) AS "__tmp"("id", %(columns)s)
                    WHERE %(table)s."id" = "__tmp"."id"
                """,
                table=SQL.identifier(self._table),
                assignments=SQL(", ").join(assignments),
                values=SQL(", ").join(rows),
                columns=SQL(", ").join(columns),
            ))

        # update parent_path
        if parent_records:
            parent_records._parent_store_update()

        # update log fields for polymorphic models
        if self._log_access and self._depend_models != None and self._name != 'ir.poly_base':
            poly_base_model = self.env['ir.poly_base']
            log_vals = {'write_uid': self.env.uid, 'write_date': self.env.cr.now()}
            poly_base_model.browse(self.ids).write(log_vals)


class PolyModel(PolyBase):
    """ Main super-class for regular database-persisted Odoo models.

    Odoo models are created by inheriting from this class::

        class user(Model):
            ...

    The system will later instantiate the class once per database (on
    which the class' module is installed).
    """
    _auto = True                # automatically create database backend
    _register = False           # not visible in ORM registry, meant to be python-inherited only
    _abstract = False           # not abstract
    _transient = False          # not transient


class PolyTransientModel(PolyModel):
    """ Model super-class for transient records, meant to be temporarily
    persistent, and regularly vacuum-cleaned.

    A TransientModel has a simplified access rights management, all users can
    create new records, and may only access the records they created. The
    superuser has unrestricted access to all TransientModel records.
    """
    _auto = True                # automatically create database backend
    _register = False           # not visible in ORM registry, meant to be python-inherited only
    _abstract = False           # not abstract
    _transient = True           # transient

    @api.autovacuum
    def _transient_vacuum(self):
        """Clean the transient records.

        This unlinks old records from the transient model tables whenever the
        :attr:`_transient_max_count` or :attr:`_transient_max_hours` conditions
        (if any) are reached.

        Actual cleaning will happen only once every 5 minutes. This means this
        method can be called frequently (e.g. whenever a new record is created).

        Example with both max_hours and max_count active:

        Suppose max_hours = 0.2 (aka 12 minutes), max_count = 20, there are
        55 rows in the table, 10 created/changed in the last 5 minutes, an
        additional 12 created/changed between 5 and 10 minutes ago, the rest
        created/changed more than 12 minutes ago.

        - age based vacuum will leave the 22 rows created/changed in the last 12
          minutes
        - count based vacuum will wipe out another 12 rows. Not just 2,
          otherwise each addition would immediately cause the maximum to be
          reached again.
        - the 10 rows that have been created/changed the last 5 minutes will NOT
          be deleted
        """
        if self._transient_max_hours:
            # Age-based expiration
            self._transient_clean_rows_older_than(self._transient_max_hours * 60 * 60)

        if self._transient_max_count:
            # Count-based expiration
            self._transient_clean_old_rows(self._transient_max_count)

    def _transient_clean_old_rows(self, max_count):
        # Check how many rows we have in the table
        self._cr.execute(SQL("SELECT count(*) FROM %s", SQL.identifier(self._table)))
        [count] = self._cr.fetchone()
        if count > max_count:
            self._transient_clean_rows_older_than(300)

    def _transient_clean_rows_older_than(self, seconds):
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

