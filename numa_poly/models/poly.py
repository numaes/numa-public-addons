import logging
from collections import OrderedDict

from docutils.nodes import field_name

import odoo
from odoo import api, _, exceptions
from odoo import models, fields
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

import typing
if typing.TYPE_CHECKING:
    from collections.abc import Reversible
    from odoo.modules.registry import Registry
    from odoo.api import Self, ValuesType, IdType


_logger = logging.getLogger(__name__)


class PolyBase(models.Model):
    _name = 'ir.poly_base'
    _description = 'Polymorphic Models Base'
    _rec_name = 'id'

    concrete_model_id = fields.Many2one('res.models', 'Concrete Model', required=True)


class Base(models.AbstractModel):
    _inherit = 'base'

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

    _checked_id = False

    def __init__(self, name, bases, attrs):
        super().__init__(name, bases, attrs)

        if not self._abstract and self._depend_models and self._name not in self._depend_models.keys():
            # this class defines a model: add magic fields
            def set(name, field):
                setattr(self, name, field)
                field.__set_name__(self, name)

            # Create a poly_base_id many2one
            set(
                'poly_base_id',
                fields.Many2one(
                    'ir.poly_base',
                    string='Poly base',
                    compute='compute_poly_base_id()',
                    automatic=True,
                    readonly=True
                )
            )

            # Create a concrete_model_id poly_base_id many2one
            set(
                'concrete_model_id',
                fields.Many2one(
                    'ir.model',
                    string='Concrete model',
                    related='poly_base_id.concrete_model_id',
                    automatic=True,
                    readonly=True
                )
            )

            if attrs.get('_log_access', self._auto):
                # Redefine log access on ir.poly_bas
                set('create_uid',
                    fields.Many2one('res.users', string='Created by',
                                    related='poly_base_id.create_uid',
                                    automatic=True, readonly=True))
                set('create_date',
                    fields.Datetime(string='Created on',
                                    related='poly_base_id.create_date',
                                    automatic=True, readonly=True))
                set('write_uid',
                    fields.Many2one('res.users', string='Last Updated by',
                                    related='poly_base_id.write_uid',
                                    automatic=True, readonly=True))
                set('write_date',
                    fields.Datetime(string='Last Updated on',
                                    related='poly_base_id.write_uid',
                                    automatic=True, readonly=True))

    def compute_poly_base_id(self):
        for instance in self:
            instance.poly_base_id = instance.id

    def _get_depends_list(self):
        """
        Build a dependant list, ordered by inheritance order
        :return: a List of model names, ordered by precedence, last is the first to consider
        """
        self.ensure_one()

        if self._name != 'base':
            return super()._get_depends_list() + self._depend_models.keys()
        else:
            return []

    def _get_depends_fields(self):
        """
        Build a dependant mapping dictionary to get the Many2one field names of the bases
        :return: a dict of field names, to be accesed by model name
        """
        self.ensure_one()

        if self._name != 'base':
            return super()._get_depends_fields().update(self._depend_models)
        else:
            return {}

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
        model_class_without_depends = super()._build_model(cls, pool, cr)

        model_class_without_depends._depends_module = {}
        model_class_without_depends._depends_children = OrderedSet()
        check_parent = model_class_without_depends._build_model_check_parent

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
                for base in parent_class.__depends_base_classes:
                    bases.add(base)
            else:
                if parent_class._name != 'ir.poly_base' and not parent_class._depend_models:
                    raise TypeError("Model %r depends from non-polymorphic model %r. Only polymorphic is allowed" %
                                    (name, parent))
                bases.add(parent_class)
                model_class_without_depends._depends_module[parent] = cls._module
                parent_class._depends_children.add(name)

        model_class_without_depends.__depends_base_classes = tuple(bases)

        # determine the attributes of the model's class
        model_class_without_depends._build_dependant_model_attributes(pool)

        pool[name] = model_class_without_depends

        return model_class_without_depends

    @api.model
    def _setup_base(self):
        super()._setup_base()

        def get_next_id(base_name) -> int:
            base_model = self.env[base_name]
            if base_model._table:
                self.env.cr.execute(f'''SELECT currval(pg_get_serial_sequence('{base_name}', 'id'))''')[0]
                next_id = self.env.cr.fetchall()[0][0]
                return next_id
            else:
                return 1

        if self._depend_models:
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
    def _build_dependant_model_attributes(cls, pool):
        """ Initialize base model attributes. """

        super()._build_model_attributes(pool)

        def set(name, field):
            setattr(cls, name, field)
            field.__set_name__(cls, name)

        for model_name, model_field in reversed(cls._depend_models.items()):
            set(model_field,
                fields.Many2one(model_name, string=model_name,
                                compute=f'compute_{model_field}',
                                automatic=True, readonly=True)
            )
            def compute_method(self):
                for instance in self:
                    instance[model_field] = instance.id

            set(f'compute_{model_field}', compute_method)

            for subfield_name, subfield_definition in pool[model_name]._fields:
                if subfield_name not in ['id', 'create_uid', 'create_date', 'write_uid', 'write_date'] and \
                   not hasattr(cls, subfield_name):
                    subfield_type = subfield_definition['type']
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
                    }.get(subfield_type)
                    if field_subclass:
                        new_field = field_subclass(
                            string=subfield_definition['string'],
                            related=f'{model_field}.{subfield_name}'
                        )
                    else:
                        raise TypeError(_('Unsupported field type %s for field %s') %
                                        (subfield_type, field_name))

                    set(subfield_name, new_field)

    @api.model
    def _create(self, data_list):
        """ Create records from the stored field values in ``data_list``. """
        """ TODO Investigate if access rules shold be applied base by base also """

        if not self._depend_models:
            # Normal Odoo ORM model, just process it the normal way
            return super()._create(data_list)
        else:
            # It is a polymorphic create.
            related2base = {}
            for base_name, base_many2one in self._depend_models.items():
                related2base[base_many2one] = base_name

            new_records = self

            new_poly = self.env['ir.poly_base'].create(dict(
                concrete_model_id=self.env['ir.model']._get(self._name).id
            ))

            for data in data_list:
                # First ensure all base records will be created
                base_data = {}
                for base in self._depend_models:
                    base_data.setdefault(base, {})
                    for field_name in data.keys():
                        field_description = self._fields[field_name]
                        if field_description['related']:
                            related_field = field_description['related'].split('.')[0]
                            if related_field in related2base:
                                base_data[base][field_name] = data[field_name]
                                del data[field_name]
                    base_model = self.env[base]
                    base_values = base_model._prepare_create_values(base_data[base])
                    base_values['id'] = new_poly.id
                    base_model._create(base_values)

                # Lastly create the new records, all bases already created
                new_records |= super()._create([data])[0]

            return new_records

    def unlink(self):
        """ Unlink records """

        super().unlink()

        if self._depend_models:
            # Ensure all bases will be unlinked also
            for base in self._depend_models:
                base_model = self.env[base]
                base_model.browse(self.ids).unlink()

