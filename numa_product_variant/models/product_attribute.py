import logging
import math
import unicodedata

import psycopg2

from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from odoo.tools import float_round, float_repr

from .product_attribute_reference_mixin import REFERENCE_MODELS

_logger = logging.getLogger(__name__)

#: Factor turning a value of each unit into metres, the unit dimensions
#: are stored in.
NUMBER_UNIT_FACTORS = {'m': 1.0, 'cm': 0.01, 'mm': 0.001}


class ProductAttribute(models.Model):
    """Attribute declaring what kind of data its values carry.

    ``value_type`` is orthogonal to Odoo's two existing axes:

    - ``create_variant`` decides whether a value materialises a variant. It is
      the counterpart of SAP's configurable material versus material variant
      decision, and is reused unchanged.
    - ``display_type`` decides how the predefined list is rendered.

    The predefined values remain an *optional list*, not a mode: an attribute
    may have a list and still accept values outside it, which is what SAP calls
    "additional values" and what D365 models as "Text with or without a fixed
    list".
    """
    _inherit = "product.attribute"

    code_identifier = fields.Char('Code Identifier')
    default_value = fields.Many2one('product.attribute.value',
                                    domain="[('id', 'in', value_ids)]")
    change_on_create = fields.Selection(
        [('length', 'Length'), ('width', 'Width'), ('height', 'Height')],
        'Set on variant creation',
    )

    value_type = fields.Selection(
        [
            ('char', 'Text'),
            ('number', 'Number'),
            ('date', 'Date'),
            ('reference', 'Reference to a record'),
        ],
        string='Value Type', default='char', required=True,
        help="Data type of this attribute's values. Orthogonal to the display "
             "type and to variant creation.")
    reference_model = fields.Selection(
        REFERENCE_MODELS, string='Referenced Model',
        help="Model whose records this attribute's values point at.")
    reference_domain = fields.Char(
        string='Reference Domain',
        help="Optional domain restricting which records may be referenced.")
    allow_additional_values = fields.Boolean(
        string='Allow Additional Values',
        help="Allow values outside the predefined list. The list then acts as "
             "a set of suggestions rather than a closed set.")
    number_min = fields.Float(string='Minimum Value')
    number_max = fields.Float(string='Maximum Value')
    number_uom = fields.Selection(
        selection=[('m', 'Metres'), ('cm', 'Centimetres'),
                   ('mm', 'Millimetres')],
        string='Unit of the Value',
        help="Unit the values of this attribute are entered in. Physical "
             "dimensions are stored in metres, so a value entered in "
             "millimetres is converted once, where it is materialised. "
             "Bounds and rounding are expressed in this unit, which is the "
             "unit the user types in.\n\n"
             "Only meaningful for a value that feeds a dimension: a count of "
             "modules is a number, not a length, and offering it metres would "
             "be an invitation to answer the wrong question.")
    number_rounding = fields.Float(
        string='Rounding', default=0.001,
        help="Numeric values are rounded to this precision before being "
             "compared, so that 1250.0 and 1250.0000001 are the same value "
             "and therefore the same product.")
    code_format = fields.Char(
        string='Code Format', default='%(value)s',
        help="Python format string used to build the code of materialised "
             "values, e.g. '%(value)04.0f'.")

    @api.constrains('value_type', 'reference_model')
    def _check_reference_model(self):
        for attribute in self:
            if attribute.value_type == 'reference' and not attribute.reference_model:
                raise ValidationError(_(
                    "Attribute %(name)s references records, so it must declare "
                    "a referenced model.", name=attribute.display_name))

    @api.constrains('number_min', 'number_max')
    def _check_number_bounds(self):
        for attribute in self:
            if attribute.number_min and attribute.number_max and \
                    attribute.number_min > attribute.number_max:
                raise ValidationError(_(
                    "Attribute %(name)s has a minimum greater than its maximum.",
                    name=attribute.display_name))

    def _number_unit_factor(self):
        """Factor converting a value of this attribute into the model's unit.

        Physical dimensions are stored in metres. A family asking for
        millimetres — which is how anybody configuring a roof or a window
        thinks — would otherwise write 1200 metres into ``variant_length``.
        The conversion happens once, here, so nothing downstream learns about
        units: the value keeps its entered form in ``free_number``, its label
        and its code, and only the dimension it feeds is converted.
        """
        self.ensure_one()
        return NUMBER_UNIT_FACTORS.get(self.number_uom or 'm', 1.0)

    @api.constrains('value_type', 'change_on_create', 'number_uom')
    def _check_number_uom(self):
        """Un numero que alimenta una dimension tiene que decir en que unidad esta.

        Sin unidad se asume metros, y asumir es justamente lo que hizo que una
        familia que pide milimetros escribiera 1200 metros de largo en la
        variante. Donde el valor no alimenta ninguna dimension la unidad no
        significa nada y se deja vacia.
        """
        for attribute in self:
            if (attribute.value_type == 'number'
                    and attribute.change_on_create
                    and not attribute.number_uom):
                raise ValidationError(_(
                    "%(name)s writes the %(dimension)s of the variant, so it "
                    "has to say which unit its values are in.",
                    name=attribute.display_name,
                    dimension=attribute.change_on_create))

    @api.constrains('value_type', 'number_rounding')
    def _check_number_rounding(self):
        for attribute in self:
            if attribute.value_type == 'number' and attribute.number_rounding <= 0.0:
                raise ValidationError(_(
                    "Attribute %(name)s must have a strictly positive rounding.",
                    name=attribute.display_name))

    # === MATERIALISATION === #

    def _normalize_payload(self, payload):
        """Validate a payload against the declared type and normalise it.

        Returns a dict with four keys:

        - ``key``: the deterministic deduplication key
        - ``target``: the referenced record, or ``None``
        - ``values``: the columns to write on a materialised value
        - ``label``: the human-readable text stored in ``name``

        A payload is a dict carrying exactly one of ``reference``, ``number``,
        ``char`` or ``date``.
        """
        self.ensure_one()

        if self.value_type == 'reference':
            target = payload.get('reference')
            if not target:
                raise ValidationError(_(
                    "Attribute %(name)s expects a record reference.",
                    name=self.display_name))
            if isinstance(target, (tuple, list)):
                target = self.env[target[0]].browse(target[1])
            if not target or target._name != self.reference_model:
                raise ValidationError(_(
                    "Attribute %(name)s expects a %(model)s record.",
                    name=self.display_name, model=self.reference_model))
            field_map = self.env['product.attribute.value']._reference_field_map()
            return {
                'key': '%s,%s' % (target._name, target.id),
                'target': target,
                'values': {
                    'reference_model': target._name,
                    field_map[target._name]: target.id,
                },
                'label': target.display_name,
            }

        if self.value_type == 'number':
            raw = payload.get('number')
            if raw is None:
                raise ValidationError(_(
                    "Attribute %(name)s expects a number.",
                    name=self.display_name))
            try:
                raw = float(raw)
            except (TypeError, ValueError):
                raise ValidationError(_(
                    "Attribute %(name)s expects a number.",
                    name=self.display_name))
            rounded = float_round(raw, precision_rounding=self.number_rounding)
            if self.number_min and rounded < self.number_min:
                raise ValidationError(_(
                    "%(value)s is below the minimum of attribute %(name)s.",
                    value=rounded, name=self.display_name))
            if self.number_max and rounded > self.number_max:
                raise ValidationError(_(
                    "%(value)s is above the maximum of attribute %(name)s.",
                    value=rounded, name=self.display_name))
            digits = max(0, -int(round(math.log10(self.number_rounding))))
            label = float_repr(rounded, digits)
            return {
                'key': label,
                'target': None,
                # value_on_create feeds the change_on_create machinery this
                # module already had, so a free numeric attribute drives the
                # variant dimension without any extra code.
                'values': {
                    'free_number': rounded,
                    'value_on_create': rounded * self._number_unit_factor(),
                },
                'label': label,
            }

        if self.value_type == 'date':
            raw = payload.get('date')
            if not raw:
                raise ValidationError(_(
                    "Attribute %(name)s expects a date.", name=self.display_name))
            raw = fields.Date.to_date(raw)
            label = fields.Date.to_string(raw)
            return {
                'key': label,
                'target': None,
                'values': {'free_date': raw},
                'label': label,
            }

        raw = payload.get('char')
        if raw is None:
            raise ValidationError(_(
                "Attribute %(name)s expects a text value.",
                name=self.display_name))
        label = str(raw).strip()
        if not label:
            raise ValidationError(_(
                "Attribute %(name)s does not accept an empty value.",
                name=self.display_name))
        return {'key': label, 'target': None, 'values': {}, 'label': label}

    def _canonical_key(self, payload):
        """Deterministic deduplication key for a payload."""
        return self._normalize_payload(payload)['key']

    def _find_value(self, normalized):
        """Look up an existing value matching a normalised payload."""
        self.ensure_one()
        Value = self.env['product.attribute.value'].with_context(active_test=False)
        target = normalized['target']
        if target is not None:
            field_name = Value._reference_field_map()[target._name]
            return Value.search([
                ('attribute_id', '=', self.id),
                ('reference_model', '=', target._name),
                (field_name, '=', target.id),
            ], limit=1)
        found = Value.search([
            ('attribute_id', '=', self.id),
            ('canonical_key', '=', normalized['key']),
        ], limit=1)
        if found:
            return found

        # A value that was never materialised carries no canonical key: every
        # value of a closed attribute is like that, because it was loaded from
        # a data file or typed into the attribute form. Without this fallback
        # `configure` cannot address any of them, and says so with the one
        # message that is certainly wrong -- "Red is not an allowed value of
        # Color" about the Red that the attribute itself lists.
        #
        # So the natural field is searched too. It is a weaker key on purpose:
        # deduplication still belongs to the canonical one, which is unique by
        # index; this only finds what somebody else already declared.
        natural = {
            'number': 'free_number',
            'date': 'free_date',
        }.get(self.value_type)
        if natural:
            value = normalized['values'].get(natural)
            if value is None:
                return Value.browse()
            return Value.search([
                ('attribute_id', '=', self.id),
                ('canonical_key', '=', False),
                (natural, '=', value),
            ], limit=1)
        return Value.search([
            ('attribute_id', '=', self.id),
            ('canonical_key', '=', False),
            ('name', '=', normalized['label']),
        ], limit=1)

    def _get_or_create_value(self, payload):
        """Return the attribute value for a payload, creating it if allowed.

        Single entry point for materialisation: the configurator dialog is not
        the only caller, so this lives on the model rather than in a
        controller.

        Deterministic — the same payload always yields the same value.
        Concurrent callers race on the partial unique index; the loser re-reads
        the winner's row rather than creating a duplicate.
        """
        self.ensure_one()
        normalized = self._normalize_payload(payload)

        existing = self._find_value(normalized)
        if existing:
            # The garbage collector may have archived it after a previous use.
            # Re-entering the same value must revive it rather than leave the
            # attribute line pointing at an archived record.
            if not existing.active:
                existing.write({'active': True})
            return existing

        if not self.allow_additional_values:
            raise ValidationError(_(
                "%(value)s is not an allowed value of attribute %(name)s.",
                value=normalized['label'], name=self.display_name))

        values = dict(normalized['values'])
        values.update({
            'attribute_id': self.id,
            'name': normalized['label'],
            'canonical_key': normalized['key'],
            'is_materialized': True,
            'code_value': self._build_code_value(normalized),
        })
        try:
            with self.env.cr.savepoint():
                return self.env['product.attribute.value'].create(values)
        except psycopg2.errors.UniqueViolation:
            concurrent = self._find_value(normalized)
            if not concurrent:
                raise
            return concurrent

    # === CODE GENERATION === #

    def _build_code_value(self, normalized):
        """Build the ``code_value`` of a materialised value.

        References borrow the referenced record's own code so the generated
        ``default_code`` stays readable — the same composition Infor LN uses
        for generated custom item codes: fixed elements plus option values.
        """
        self.ensure_one()
        target = normalized['target']
        if target is not None:
            code = getattr(target, 'base_code', False) or \
                getattr(target, 'default_code', False)
            if code:
                return code
            return self._slugify_code(target.display_name)

        if self.value_type == 'number':
            return (self.code_format or '%(value)s') % {
                'value': normalized['values']['free_number']}

        return self._slugify_code(normalized['label'])

    @api.model
    def _slugify_code(self, text):
        """Uppercase alphanumeric slug, accents folded, truncated to 32 chars."""
        folded = unicodedata.normalize('NFKD', text or '')
        stripped = ''.join(c for c in folded if not unicodedata.combining(c))
        return ''.join(c for c in stripped if c.isalnum()).upper()[:32]
