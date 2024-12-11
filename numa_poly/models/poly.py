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
from odoo.api import NewId, model
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
from odoo.tools import (
    clean_context, config, date_utils, discardattr,
    DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, format_list,
    frozendict, get_lang, lazy_classproperty, OrderedSet,
    ormcache, partition, Query, split_every, unique,
    SQL, sql,
)
from odoo.tools.misc import LastOrderedSet, ReversedIterable, unquote

from odoo.models import LOG_ACCESS_COLUMNS, INSERT_BATCH_SIZE, UPDATE_BATCH_SIZE, SQL_DEFAULT, GC_UNLINK_LIMIT


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

    _depend_models = OrderedDict()
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

        if hasattr(cls, '_depend_models') and cls._depend_models:

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
                    if parent_class._name != 'ir.poly_base' and not parent_class._depend_models:
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

    @api.model
    def _setup_base(self):
        super()._setup_base()

        if self._depend_models:
            self._build_dependant_model_attributes()

        def get_next_id(base_name) -> int:
            base_model = self.env[base_name]
            if base_model._table:
                self.env.cr.execute(f'''
                    SELECT currval(pg_get_serial_sequence('{base_model._table}', 'id'))
                ''')
                next_id = self.env.cr.fetchall()[0][0]
                return next_id
            else:
                return 1

        # if self._depend_models:
        if False:
            # Ensure no polymorphic models has existing records
            # with IDs clashing with newly created polymorphic records
            poly_base_id = get_next_id('ir.poly_base')
            for base_name in self._depend_models.keys:
                base = self.pool[base_name]
                if not base._id_checked:
                    base._id_checked = True
                    current_id = get_next_id(base._name)
                    if current_id > poly_base_id:
                        poly_base_id = current_id
                        self.env.cr.execute(f'''
                            ALTER SEQUENCE pg_get_serial_sequence('ir_poly_base', 'id') MINVALUE {poly_base_id};
                        ''')

    @classmethod
    def _build_dependant_model_attributes(self):
        """ Initialize base model attributes. """
        def set(name, field, related_base=None):
            _logger.info(f'Agregando campo {name} a {self._name}'
                         f' (base: {related_base or "N/A"})')
            setattr(self, name, field)
            self._fields[name] = field
            field._direct = True
            field.prepare_setup()
            field.__set_name__(self, name)

        # Create a poly_base_id many2one
        set('poly_base_id',
            fields.Many2one(
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

        # set('create_uid',
        #      fields.Many2one('res.users', string='Created by',
        #                      related='poly_base_id.create_uid',
        #                      automatic=False, readonly=True))
        # set('create_date',
        #      fields.Datetime(string='Created on',
        #                      related='poly_base_id.create_date',
        #                      automatic=False, readonly=True))
        # set('write_uid',
        #      fields.Many2one('res.users', string='Last Updated by',
        #                      related='poly_base_id.write_uid',
        #                      automatic=False, readonly=True))
        # set('write_date',
        #      fields.Datetime(string='Last Updated on',
        #                      related='poly_base_id.write_uid',
        #                      automatic=False, readonly=True))

        related_fields = {}
        for model_name, model_field in reversed(self._depend_models.items()):
            def add_subfields(mm):
                if mm == 'ir.poly_base':
                    return

                base_model = self.pool[mm]
                for subfield_name, subfield in base_model._fields.items():
                    subfield_plain_name = subfield_name.split('.')[-1]
                    if subfield_plain_name not in self._fields and \
                       subfield_plain_name not in related_fields and \
                       not subfield.related:
                        related_fields[subfield_plain_name] = (
                            mm, subfield_plain_name,
                            subfield.type, subfield.comodel_name, subfield.string
                        )

                for sub_base in base_model._depend_models.keys():
                    add_subfields(sub_base)

            add_subfields(model_name)

        related_bases = {}
        related_counter = 1
        for new_field_name in related_fields.keys():
            model, field_name, field_type, comodel, description = related_fields[new_field_name]
            if model not in related_bases:
                if model in self._depend_models:
                    model_field = self._depend_models[model]
                else:
                    model_field = f'related_{related_counter}'
                    related_counter += 1
                related_bases[model] = model_field
                set(model_field,
                    fields.Many2one(comodel_name=model, string=model,
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

            if field_type in ['many2one', 'many2many', 'one2many']:
                new_field = field_subclass(
                    comodel_name=comodel,
                    string=description,
                    related=f'{related_bases[model]}.{field_name}',
                    automatic=True,
                    recursive=True,
                )
            elif field_subclass:
                new_field = field_subclass(
                    string=description,
                    related=f'{related_bases[model]}.{field_name}',
                    automatic=True,
                )
            else:
                raise TypeError(_('Unsupported field type %s for field %s') %
                                (field_type, field_name))

            set(field_name, new_field, related_bases[model])

        for model, model_field in self._depend_models.items():
            if model not in related_bases:
                set(model_field,
                    fields.Many2one(comodel_name=model, string=model,
                                    automatic=True, readonly=True)
                )

    @api.model_create_multi
    def create(self, data_list: list[ValuesType]) -> Self:
        """ Create records from the stored field values in ``data_list``. """
        """ TODO Investigate if access rules should be applied base by base also """

        if not self._depend_models:
            # Normal Odoo ORM model, just process it the normal way
            return super().create(data_list)
        else:
            # It is a polymorphic create.
            related2base = {}
            for base_name, base_many2one in self._depend_models.items():
                related2base[base_many2one] = base_name

            new_records = self

            depend_fields = [base_field for base_field in self._depend_models.values()]
            all_created = OrderedSet()

            for data in data_list:
                outer_data = data.copy()

                if 'id' in data:
                    new_id = data['id']
                else:
                    new_poly = self.env['ir.poly_base'].create(dict(
                        concrete_model_id=self.env['ir.model']._get_id(self._name)
                    ))
                    _logger.info(f'Creando poly base para {self._name} con {data}, id = {new_poly.id}')
                    all_created.add(new_poly)
                    new_id = new_poly.id

                # First ensure all base records will be created
                created_models = OrderedSet()
                created_models.add('ir.poly_base')
                base_data = {}
                for base, base_field in self._depend_models.items():
                    if base not in created_models:
                        created_models.add(base)

                        base_data.setdefault(base, {})
                        for field_name in data.keys():
                            field_definition = self._fields[field_name]
                            if field_definition.args.get('related'):
                                related_root = field_definition.args['related'].split('.')[0]
                                if related_root in related2base and related2base[related_root] == base:
                                    base_data[base][field_name] = data[field_name]
                                    del outer_data[field_name]

                        base_model = self.env[base]
                        if base_model.search([('id', '=', new_id)], limit=1):
                            # Already created by other base
                            continue

                        base_data[base]['id'] = new_id
                        _logger.info(f'Creando {base_model._name} con {base_data[base]} para id {new_id}')
                        all_created.add(base_model.create(base_data[base]))

                # Lastly create the new records, all bases already created
                outer_data['id'] = new_id
                outer_data['poly_base_id'] = new_id

                for base_field in depend_fields:
                    outer_data[base_field] = new_id

                _logger.info(f'Creando {self._name} con {outer_data} para id {new_id}')
                new_record = super().create([outer_data])
                all_created.add(new_record)
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

        if self._depend_models:
            # Ensure all bases will be unlinked also
            for base in self._depend_models:
                base_model = self.env[base]
                base_model.browse(self.ids).unlink()


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

