# Typed Attribute Values and Record References — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `product.attribute` declare the type of its values (text, number, date, or a reference to a record) and accept values outside its predefined list, materialising them on demand so Odoo's variant machinery keeps working unchanged.

**Architecture:** Type declaration on `product.attribute`; reference payload on an abstract mixin applied to both `product.attribute.value` and `product.template.attribute.value` (the latter overriding the former); a single deterministic `_get_or_create_value` entry point guarded by a partial unique index; a `resolve_value` controller route returning a `ptav_id` so the existing OWL configurator flow is untouched.

**Tech Stack:** Odoo 18, Python 3, OWL 2, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-08-12-product-attribute-typed-values-design.md`

## Global Constraints

- All documentation, code comments and user-facing messages in professional English.
- Backward compatibility: with `value_type='char'`, a populated value list and `allow_additional_values=False`, behaviour must be identical to today. No data migration.
- `build_default_code` on `product.template` must not change its output for existing list attributes.
- All validation server-side. The OWL dialog is not the only entry path (`_onchange_product_template_id`, imports, direct `create()`).
- `website_sale` and Point of Sale configurators are out of scope.
- Test command, run from `/home/gamarino/odoo/cm-18.0`:
  ```bash
  .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin -c odoo.config \
    -d cm-test-18.0 -u numa_product_variant --test-enable \
    --test-tags /numa_product_variant --stop-after-init --log-level=test
  ```
  Baseline before any change: `0 failed, 0 error(s) of 19 tests` (25 test methods).

## Spec corrections locked in here

1. **`canonical_key` replaces `name` as the deduplication key.** `product.attribute.value.name` is `translate=True`, therefore a jsonb column: it cannot carry a unique index nor an exact-match search. A dedicated non-translatable `canonical_key` Char is added instead.
2. **The mixin carries only the reference payload.** `is_materialized`, `free_number`, `free_date` and `canonical_key` live on `product.attribute.value` only. Overriding a free value per template is meaningless — only references are overridable — and the mixin name then matches its contents.

## File Structure

`numa_product_variant/models/product.py` currently holds six model classes in 203 lines. This change adds roughly 500 lines of attribute logic, so the attribute-related models move to their own files (Odoo's own convention, one file per model). `product.py` keeps the category/template/variant models.

**Create:**
- `models/product_attribute_reference_mixin.py` — abstract reference payload
- `models/product_attribute.py` — `product.attribute` type declaration + `_get_or_create_value` + `_build_code_value`
- `models/product_attribute_value.py` — `product.attribute.value` payload, `canonical_key`, lifecycle
- `models/product_template_attribute_value.py` — PTAV override + `_get_effective_reference`
- `models/product_template_attribute_line.py` — `_get_or_create_ptav`
- `data/ir_cron.xml` — garbage-collection cron
- `static/src/js/product_template_attribute_line_patch.js`
- `static/src/xml/product_template_attribute_line_patch.xml`
- `tests/test_attribute_typing.py`
- `tests/test_materialization.py`
- `tests/test_codes.py`
- `tests/test_lifecycle.py`
- `tests/test_resolution_api.py`
- `tests/test_resolve_value_controllers.py`

**Modify:**
- `models/__init__.py` — import order (mixin first)
- `models/product.py` — remove the three attribute classes, add the resolution API to `product.product`
- `views/product_views.xml` — new attribute and value fields
- `controllers/product_configurator.py` — `resolve_value` routes
- `tests/common.py` — joinery fixture
- `__manifest__.py` — new data files and assets, version bump
- `README.md` — extensive documentation

---

### Task 1: Split the attribute models into their own files

Pure refactor. No behaviour change, no new field. Its only job is to give the following tasks a clean place to write in, and to prove the split broke nothing.

**Files:**
- Create: `models/product_attribute.py`, `models/product_attribute_value.py`, `models/product_template_attribute_value.py`
- Modify: `models/product.py`, `models/__init__.py`

**Interfaces:**
- Produces: modules `product_attribute`, `product_attribute_value`, `product_template_attribute_value` importable from `models/__init__.py`. Model behaviour identical.

- [ ] **Step 1: Run the existing suite to confirm the baseline**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant --stop-after-init --log-level=test 2>&1 | grep odoo.tests.result
```
Expected: `0 failed, 0 error(s) of 19 tests`

- [ ] **Step 2: Move `ProductAttribute` verbatim**

Create `models/product_attribute.py` with the imports and the class exactly as it stands in `product.py` lines 9-18. Delete it from `product.py`.

```python
import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    code_identifier = fields.Char('Code Identifier')
    default_value = fields.Many2one('product.attribute.value',
                                    domain="[('id', 'in', value_ids)]")
    change_on_create = fields.Selection(
        [('length', 'Length'), ('width', 'Width'), ('height', 'Height')],
        'Set on variant creation',
    )
```

- [ ] **Step 3: Move `ProductAttributeValue` and `ProductTemplateAttributeValue` verbatim**

`models/product_attribute_value.py`:

```python
from odoo import models, fields


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    code_value = fields.Char('Code Value', required=True)
    value_on_create = fields.Float('Value to set on variant creation')
    weight_factor = fields.Float('Weight factor', default=1.0)
```

`models/product_template_attribute_value.py`:

```python
from odoo import models, fields


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    code_value = fields.Char('Code Value',
                             related='product_attribute_value_id.code_value')
```

- [ ] **Step 4: Update `models/__init__.py`**

```python
from . import product_attribute
from . import product_attribute_value
from . import product_template_attribute_value
from . import product
from . import purchase_order_line
```

- [ ] **Step 5: Run the suite — must still be green**

Same command as Step 1. Expected: `0 failed, 0 error(s) of 19 tests`

- [ ] **Step 6: Commit**

```bash
git add numa_product_variant/models/
git commit -m "refactor(numa_product_variant): split attribute models into their own files"
```

---

### Task 2: Attribute type declaration

**Files:**
- Modify: `models/product_attribute.py`
- Test: `tests/test_attribute_typing.py` (create)

**Interfaces:**
- Produces: on `product.attribute` — `value_type` (`char`/`number`/`date`/`reference`), `reference_model`, `reference_domain`, `allow_additional_values`, `number_min`, `number_max`, `number_rounding`, `code_format`. Constant `REFERENCE_MODELS` in `models/product_attribute_reference_mixin.py`.

- [ ] **Step 1: Create the mixin module holding the shared selection**

`models/product_attribute_reference_mixin.py`:

```python
from odoo import models, fields

REFERENCE_MODELS = [
    ('product.template', 'Product Template'),
    ('product.product', 'Product Variant'),
    ('product.attribute.value', 'Attribute Value'),
]


class ProductAttributeReferenceMixin(models.AbstractModel):
    """Reference payload shared by attribute values and template attribute values.

    Concrete ``Many2one`` columns rather than a bare ``fields.Reference``: the
    latter stores ``'product.product,42'`` as text, with no foreign key, no
    ``ondelete`` and no way to filter or join. ``reference_record`` gives the
    uniform generic API on top of them.

    Another module extends this by adding its own ``Many2one``, extending
    ``reference_model`` with ``selection_add`` and overriding
    ``_reference_field_map``.
    """
    _name = 'product.attribute.reference.mixin'
    _description = 'Product Attribute Reference Payload'

    reference_model = fields.Selection(
        REFERENCE_MODELS, string='Referenced Model',
        help="Which kind of record this value points at.")
    reference_template_id = fields.Many2one(
        'product.template', string='Referenced Template',
        ondelete='restrict', index='btree_not_null')
    reference_variant_id = fields.Many2one(
        'product.product', string='Referenced Variant',
        ondelete='restrict', index='btree_not_null')
    reference_value_id = fields.Many2one(
        'product.attribute.value', string='Referenced Value',
        ondelete='restrict', index='btree_not_null')

    def _reference_field_map(self):
        """Model name -> name of the column holding its foreign key."""
        return {
            'product.template': 'reference_template_id',
            'product.product': 'reference_variant_id',
            'product.attribute.value': 'reference_value_id',
        }
```

- [ ] **Step 2: Write the failing test**

`tests/test_attribute_typing.py`:

```python
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestAttributeTyping(NumaVariantCommon):

    def test_default_value_type_is_char(self):
        """Existing attributes keep behaving as plain text attributes."""
        self.assertEqual(self.attr_color.value_type, 'char')
        self.assertFalse(self.attr_color.allow_additional_values)

    def test_reference_attribute_declares_a_model(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type',
            'create_variant': 'dynamic',
            'code_identifier': 'P',
            'value_type': 'reference',
            'reference_model': 'product.template',
        })
        self.assertEqual(attr.reference_model, 'product.template')

    def test_reference_attribute_requires_a_model(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken reference',
                'value_type': 'reference',
            })

    def test_number_bounds_must_be_ordered(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken bounds',
                'value_type': 'number',
                'number_min': 100.0,
                'number_max': 10.0,
            })

    def test_number_rounding_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.env['product.attribute'].create({
                'name': 'Broken rounding',
                'value_type': 'number',
                'number_rounding': 0.0,
            })
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant:TestAttributeTyping --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|Invalid field"
```
Expected: failures on `Invalid field 'value_type'`.

- [ ] **Step 4: Implement the fields and constraints**

Append to `models/product_attribute.py`:

```python
from odoo import api, _
from odoo.exceptions import ValidationError

from .product_attribute_reference_mixin import REFERENCE_MODELS


# inside class ProductAttribute
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
    number_rounding = fields.Float(
        string='Rounding', default=0.001,
        help="Numeric values are rounded to this precision before being "
             "compared, so that 1250.0 and 1250.0000001 are the same value.")
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

    @api.constrains('value_type', 'number_rounding')
    def _check_number_rounding(self):
        for attribute in self:
            if attribute.value_type == 'number' and attribute.number_rounding <= 0.0:
                raise ValidationError(_(
                    "Attribute %(name)s must have a strictly positive rounding.",
                    name=attribute.display_name))
```

Add `from . import product_attribute_reference_mixin` as the **first** import in `models/__init__.py`.

- [ ] **Step 5: Run it and watch it pass**

Same command as Step 3. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 6: Commit**

```bash
git add numa_product_variant/models/ numa_product_variant/tests/test_attribute_typing.py
git commit -m "feat(numa_product_variant): declare attribute value type on product.attribute"
```

---

### Task 3: Reference payload and effective-reference resolution

**Files:**
- Modify: `models/product_attribute_value.py`, `models/product_template_attribute_value.py`
- Test: `tests/test_attribute_typing.py` (extend)

**Interfaces:**
- Consumes: `ProductAttributeReferenceMixin`, `REFERENCE_MODELS` (Task 2).
- Produces: `_get_reference_record()` on both value models; `_get_effective_reference()` on `product.template.attribute.value`; `canonical_key`, `is_materialized`, `free_number`, `free_date` on `product.attribute.value`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_attribute_typing.py`:

```python
    def test_value_reference_round_trip(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type', 'create_variant': 'dynamic',
            'value_type': 'reference', 'reference_model': 'product.template',
        })
        base = self._make_template(name='Profile L 40x40', base_code='L4040')
        value = self.env['product.attribute.value'].create({
            'name': 'L 40x40', 'attribute_id': attr.id, 'code_value': 'L4040',
            'reference_model': 'product.template',
            'reference_template_id': base.id,
        })
        self.assertEqual(value._get_reference_record(), base)
        self.assertEqual(value.reference_record, base)

    def test_ptav_overrides_the_value_reference(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type', 'create_variant': 'always',
            'value_type': 'reference', 'reference_model': 'product.template',
        })
        base = self._make_template(name='Profile A', base_code='A')
        override = self._make_template(name='Profile B', base_code='B')
        value = self.env['product.attribute.value'].create({
            'name': 'A', 'attribute_id': attr.id, 'code_value': 'A',
            'reference_model': 'product.template',
            'reference_template_id': base.id,
        })
        tmpl = self._make_template(name='Cut piece', base_code='CUT')
        self.env['product.template.attribute.line'].create({
            'product_tmpl_id': tmpl.id, 'attribute_id': attr.id,
            'value_ids': [(6, 0, value.ids)],
        })
        ptav = tmpl.attribute_line_ids.product_template_value_ids
        self.assertEqual(ptav._get_effective_reference(), base)

        ptav.write({
            'reference_model': 'product.template',
            'reference_template_id': override.id,
        })
        self.assertEqual(ptav._get_effective_reference(), override)

    def test_reference_cycle_is_rejected(self):
        attr = self.env['product.attribute'].create({
            'name': 'Alias', 'value_type': 'reference',
            'reference_model': 'product.attribute.value',
        })
        first = self.env['product.attribute.value'].create({
            'name': 'first', 'attribute_id': attr.id, 'code_value': 'F',
        })
        second = self.env['product.attribute.value'].create({
            'name': 'second', 'attribute_id': attr.id, 'code_value': 'S',
            'reference_model': 'product.attribute.value',
            'reference_value_id': first.id,
        })
        with self.assertRaises(ValidationError):
            first.write({
                'reference_model': 'product.attribute.value',
                'reference_value_id': second.id,
            })

    def test_reference_domain_is_enforced(self):
        attr = self.env['product.attribute'].create({
            'name': 'Profile type', 'value_type': 'reference',
            'reference_model': 'product.template',
            'reference_domain': "[('base_code', '=like', 'L%')]",
        })
        outside = self._make_template(name='Not a profile', base_code='X1')
        with self.assertRaises(ValidationError):
            self.env['product.attribute.value'].create({
                'name': 'X1', 'attribute_id': attr.id, 'code_value': 'X1',
                'reference_model': 'product.template',
                'reference_template_id': outside.id,
            })
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant:TestAttributeTyping --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|Invalid field"
```
Expected: failures on `Invalid field 'reference_model'` on `product.attribute.value`.

- [ ] **Step 3: Add the shared helpers to the mixin**

Append inside `ProductAttributeReferenceMixin` in `models/product_attribute_reference_mixin.py`:

```python
    reference_record = fields.Reference(
        REFERENCE_MODELS, string='Referenced Record',
        compute='_compute_reference_record', inverse='_inverse_reference_record',
        help="Uniform read/write access to the referenced record.")

    @api.depends(lambda self: list(self._reference_field_map().values()) + ['reference_model'])
    def _compute_reference_record(self):
        for record in self:
            record.reference_record = record._get_reference_record() or False

    def _inverse_reference_record(self):
        for record in self:
            target = record.reference_record
            values = {field: False for field in record._reference_field_map().values()}
            values['reference_model'] = target._name if target else False
            if target:
                values[record._reference_field_map()[target._name]] = target.id
            record.write(values)

    def _get_reference_record(self):
        """Return the referenced record, or an empty recordset."""
        self.ensure_one()
        if not self.reference_model:
            return self.env['product.template'].browse()
        field_name = self._reference_field_map().get(self.reference_model)
        if not field_name:
            return self.env[self.reference_model].browse()
        return self[field_name]
```

Add `api` to the imports.

- [ ] **Step 4: Apply the mixin to `product.attribute.value` and add its own columns**

`models/product_attribute_value.py` becomes:

```python
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class ProductAttributeValue(models.Model):
    _name = 'product.attribute.value'
    _inherit = ['product.attribute.value', 'product.attribute.reference.mixin']

    code_value = fields.Char('Code Value', required=True)
    value_on_create = fields.Float('Value to set on variant creation')
    weight_factor = fields.Float('Weight factor', default=1.0)

    canonical_key = fields.Char(
        string='Canonical Key', index=True, copy=False,
        help="Deterministic deduplication key. `name` cannot be used: it is "
             "translatable, therefore a jsonb column that can neither carry a "
             "unique index nor be matched exactly.")
    is_materialized = fields.Boolean(
        string='Materialised', copy=False,
        help="Created on demand by the configurator rather than curated by "
             "hand. Only these are subject to automatic archiving.")
    free_number = fields.Float(string='Numeric Value')
    free_date = fields.Date(string='Date Value')

    @api.constrains('reference_model', 'reference_template_id',
                    'reference_variant_id', 'reference_value_id')
    def _check_reference_domain(self):
        for value in self:
            target = value._get_reference_record()
            if not target:
                continue
            domain = value.attribute_id.reference_domain
            if not domain:
                continue
            if not target.filtered_domain(safe_eval(domain)):
                raise ValidationError(_(
                    "%(record)s is not allowed for attribute %(attribute)s.",
                    record=target.display_name,
                    attribute=value.attribute_id.display_name))

    @api.constrains('reference_value_id')
    def _check_no_reference_cycle(self):
        for value in self:
            seen = set()
            current = value
            while current:
                if current.id in seen:
                    raise ValidationError(_(
                        "Attribute value %(name)s is part of a reference cycle.",
                        name=value.display_name))
                seen.add(current.id)
                current = current.reference_value_id
```

- [ ] **Step 5: Apply the mixin to `product.template.attribute.value`**

`models/product_template_attribute_value.py`:

```python
from odoo import models, fields


class ProductTemplateAttributeValue(models.Model):
    _name = 'product.template.attribute.value'
    _inherit = ['product.template.attribute.value',
                'product.attribute.reference.mixin']

    code_value = fields.Char('Code Value',
                             related='product_attribute_value_id.code_value')

    def _get_effective_reference(self):
        """Referenced record for this template value.

        The template value overrides the attribute value when it sets one.
        This is the only place the precedence rule lives; consumers must go
        through it rather than reading the columns directly.
        """
        self.ensure_one()
        return self._get_reference_record() or \
            self.product_attribute_value_id._get_reference_record()

    def _get_effective_value(self):
        """Typed Python value carried by this template value."""
        self.ensure_one()
        value = self.product_attribute_value_id
        value_type = self.attribute_id.value_type
        if value_type == 'reference':
            return self._get_effective_reference()
        if value_type == 'number':
            return value.free_number
        if value_type == 'date':
            return value.free_date
        return value.name
```

- [ ] **Step 6: Run it and watch it pass**

Same command as Step 2. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 7: Commit**

```bash
git add numa_product_variant/models/ numa_product_variant/tests/test_attribute_typing.py
git commit -m "feat(numa_product_variant): record reference payload on attribute values"
```

---

### Task 4: Deterministic materialisation

**Files:**
- Modify: `models/product_attribute.py`, `models/product_attribute_value.py`
- Test: `tests/test_materialization.py` (create)

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: `product.attribute._canonical_key(payload)`, `product.attribute._get_or_create_value(payload)`. Payload is a dict with exactly one of the keys `reference` (a `(model, id)` tuple or a recordset), `char`, `number`, `date`.

- [ ] **Step 1: Write the failing test**

`tests/test_materialization.py`:

```python
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestMaterialization(NumaVariantCommon):

    def test_same_reference_returns_the_same_value(self):
        first = self.attr_profile._get_or_create_value(
            {'reference': self.profile_l4040})
        second = self.attr_profile._get_or_create_value(
            {'reference': self.profile_l4040})
        self.assertEqual(first, second)
        self.assertTrue(first.is_materialized)

    def test_numbers_are_rounded_before_comparison(self):
        self.attr_length.number_rounding = 1.0
        first = self.attr_length._get_or_create_value({'number': 1250.0})
        second = self.attr_length._get_or_create_value({'number': 1250.4})
        self.assertEqual(first, second)
        self.assertEqual(first.free_number, 1250.0)

    def test_numbers_beyond_rounding_are_distinct(self):
        self.attr_length.number_rounding = 1.0
        first = self.attr_length._get_or_create_value({'number': 1250.0})
        second = self.attr_length._get_or_create_value({'number': 1252.0})
        self.assertNotEqual(first, second)

    def test_text_is_case_sensitive(self):
        first = self.attr_legend._get_or_create_value({'char': 'Juan'})
        second = self.attr_legend._get_or_create_value({'char': 'JUAN'})
        self.assertNotEqual(first, second)

    def test_text_is_stripped(self):
        first = self.attr_legend._get_or_create_value({'char': 'Juan'})
        second = self.attr_legend._get_or_create_value({'char': '  Juan  '})
        self.assertEqual(first, second)

    def test_existing_curated_value_is_reused_not_duplicated(self):
        curated = self.env['product.attribute.value'].create({
            'name': 'Standard', 'attribute_id': self.attr_legend.id,
            'code_value': 'STD',
        })
        curated.canonical_key = 'Standard'
        found = self.attr_legend._get_or_create_value({'char': 'Standard'})
        self.assertEqual(found, curated)
        self.assertFalse(found.is_materialized)

    def test_closed_attribute_rejects_unknown_values(self):
        self.attr_legend.allow_additional_values = False
        with self.assertRaises(ValidationError):
            self.attr_legend._get_or_create_value({'char': 'Anything'})

    def test_number_out_of_bounds_is_rejected(self):
        self.attr_length.number_min = 100.0
        self.attr_length.number_max = 6000.0
        with self.assertRaises(ValidationError):
            self.attr_length._get_or_create_value({'number': 7000.0})

    def test_payload_must_match_the_declared_type(self):
        with self.assertRaises(ValidationError):
            self.attr_length._get_or_create_value({'char': 'not a number'})
```

- [ ] **Step 2: Extend the fixture**

Append to `tests/common.py`, inside `setUpClass`, after the existing fixtures:

```python
        # Joinery fixture: an extruded profile template varying by colour,
        # alloy and strip length, and the attributes a cut piece uses.
        cls.attr_alloy = Attribute.create({
            'name': 'Alloy', 'create_variant': 'always', 'code_identifier': 'A',
        })
        cls.alloy_6063 = Value.create({
            'name': '6063', 'attribute_id': cls.attr_alloy.id, 'code_value': '63',
        })
        cls.attr_strip_length = Attribute.create({
            'name': 'Strip length', 'create_variant': 'always', 'code_identifier': 'T',
        })
        cls.strip_6m = Value.create({
            'name': '6 m', 'attribute_id': cls.attr_strip_length.id, 'code_value': '6',
        })
        cls.strip_45m = Value.create({
            'name': '4.5 m', 'attribute_id': cls.attr_strip_length.id, 'code_value': '45',
        })

        cls.attr_profile = Attribute.create({
            'name': 'Profile type', 'create_variant': 'dynamic',
            'code_identifier': 'P', 'value_type': 'reference',
            'reference_model': 'product.template',
            'allow_additional_values': True,
        })
        cls.attr_length = Attribute.create({
            'name': 'Segment length', 'create_variant': 'dynamic',
            'code_identifier': 'L', 'value_type': 'number',
            'allow_additional_values': True, 'number_rounding': 1.0,
            'code_format': '%(value)04.0f',
            'change_on_create': 'length',
        })
        cls.attr_legend = Attribute.create({
            'name': 'Engraved legend', 'create_variant': 'no_variant',
            'code_identifier': 'G', 'value_type': 'char',
            'allow_additional_values': True,
        })
```

And after the existing `_make_template` helper, add a builder for the base profile:

```python
    @classmethod
    def _make_profile_template(cls, name, base_code):
        """An extruded profile: colour + alloy + strip length, all 'always'."""
        template = cls.env['product.template'].create({
            'name': name, 'type': 'consu', 'purchase_ok': True,
            'weight_kind': 'normal', 'price_base': 'normal',
            'base_code': base_code,
            'categ_id': cls.env.ref('product.product_category_all').id,
        })
        Line = cls.env['product.template.attribute.line']
        Line.create([
            {'product_tmpl_id': template.id, 'attribute_id': cls.attr_color.id,
             'value_ids': [(6, 0, (cls.color_red + cls.color_blue).ids)]},
            {'product_tmpl_id': template.id, 'attribute_id': cls.attr_alloy.id,
             'value_ids': [(6, 0, cls.alloy_6063.ids)]},
            {'product_tmpl_id': template.id, 'attribute_id': cls.attr_strip_length.id,
             'value_ids': [(6, 0, (cls.strip_6m + cls.strip_45m).ids)]},
        ])
        return template
```

Then, at the end of `setUpClass`:

```python
        cls.profile_l4040 = cls._make_profile_template('Profile L 40x40', 'L4040')
```

Note: `_make_template` sets `categ_id` implicitly through the default category; the profile builder sets it explicitly to the base category so the fixture's `cls.category` default attributes are not injected.

- [ ] **Step 3: Run it and watch it fail**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant:TestMaterialization --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|AttributeError"
```
Expected: `_get_or_create_value` does not exist.

- [ ] **Step 4: Implement canonical keys and the entry point**

Append to `models/product_attribute.py`:

```python
import psycopg2

from odoo.tools import float_round, float_repr


# inside class ProductAttribute
    def _normalize_payload(self, payload):
        """Validate a payload against the declared type and normalise it.

        Returns a dict with the canonical key, the values to write, and the
        record referenced (if any).
        """
        self.ensure_one()
        if self.value_type == 'reference':
            target = payload.get('reference')
            if target is None:
                raise ValidationError(_(
                    "Attribute %(name)s expects a record reference.",
                    name=self.display_name))
            if isinstance(target, tuple):
                target = self.env[target[0]].browse(target[1])
            if not target or target._name != self.reference_model:
                raise ValidationError(_(
                    "Attribute %(name)s expects a %(model)s record.",
                    name=self.display_name, model=self.reference_model))
            field_name = self.env['product.attribute.value']._reference_field_map()[target._name]
            return {
                'key': '%s,%s' % (target._name, target.id),
                'target': target,
                'values': {'reference_model': target._name, field_name: target.id},
                'label': target.display_name,
            }

        if self.value_type == 'number':
            raw = payload.get('number')
            if raw is None:
                raise ValidationError(_(
                    "Attribute %(name)s expects a number.", name=self.display_name))
            try:
                raw = float(raw)
            except (TypeError, ValueError):
                raise ValidationError(_(
                    "Attribute %(name)s expects a number.", name=self.display_name))
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
                'key': label, 'target': None,
                'values': {'free_number': rounded}, 'label': label,
            }

        if self.value_type == 'date':
            raw = payload.get('date')
            if raw is None:
                raise ValidationError(_(
                    "Attribute %(name)s expects a date.", name=self.display_name))
            raw = fields.Date.to_date(raw)
            label = fields.Date.to_string(raw)
            return {
                'key': label, 'target': None,
                'values': {'free_date': raw}, 'label': label,
            }

        raw = payload.get('char')
        if raw is None:
            raise ValidationError(_(
                "Attribute %(name)s expects a text value.", name=self.display_name))
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
        """Look up an existing value for a normalised payload."""
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
        return Value.search([
            ('attribute_id', '=', self.id),
            ('canonical_key', '=', normalized['key']),
        ], limit=1)

    def _get_or_create_value(self, payload):
        """Return the attribute value for a payload, creating it if allowed.

        Single entry point for materialisation. Deterministic: the same payload
        always yields the same value. Concurrent callers race on the partial
        unique index; the loser re-reads the winner's row.
        """
        self.ensure_one()
        normalized = self._normalize_payload(payload)

        existing = self._find_value(normalized)
        if existing:
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
            self.env.cr.flush()
            concurrent = self._find_value(normalized)
            if not concurrent:
                raise
            return concurrent
```

Add `import math` and `from odoo import api, fields, models, _` to the module imports.

Also add the partial unique indexes. Append to `models/product_attribute_value.py`:

```python
    def init(self):
        super_init = getattr(super(), 'init', None)
        if super_init:
            super_init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS product_attribute_value_canonical_key_uniq
            ON product_attribute_value (attribute_id, canonical_key)
            WHERE canonical_key IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS product_attribute_value_reference_uniq
            ON product_attribute_value (attribute_id, reference_model,
                                        COALESCE(reference_template_id, 0),
                                        COALESCE(reference_variant_id, 0),
                                        COALESCE(reference_value_id, 0))
            WHERE reference_model IS NOT NULL;
        """)
```

- [ ] **Step 5: Run it and watch it pass**

Same command as Step 3. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 6: Commit**

```bash
git add numa_product_variant/models/ numa_product_variant/tests/
git commit -m "feat(numa_product_variant): deterministic on-demand value materialisation"
```

---

### Task 5: Code generation and PTAV materialisation

**Files:**
- Modify: `models/product_attribute.py`, `models/product_template_attribute_line.py` (create)
- Test: `tests/test_codes.py` (create)

**Interfaces:**
- Consumes: `_normalize_payload`, `_get_or_create_value` (Task 4).
- Produces: `product.attribute._build_code_value(normalized)`; `product.template.attribute.line._get_or_create_ptav(payload)` returning a `product.template.attribute.value`.

- [ ] **Step 1: Write the failing test**

`tests/test_codes.py`:

```python
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestCodes(NumaVariantCommon):

    def test_reference_code_comes_from_the_referenced_base_code(self):
        value = self.attr_profile._get_or_create_value(
            {'reference': self.profile_l4040})
        self.assertEqual(value.code_value, 'L4040')

    def test_number_code_uses_the_attribute_format(self):
        value = self.attr_length._get_or_create_value({'number': 1250.0})
        self.assertEqual(value.code_value, '1250')

    def test_text_code_is_an_uppercase_slug(self):
        value = self.attr_legend._get_or_create_value({'char': 'Feliz día 2026'})
        self.assertEqual(value.code_value, 'FELIZDIA2026')

    def test_build_default_code_is_unchanged_for_list_attributes(self):
        """Regression: existing behaviour must not shift."""
        template = self._make_template(base_code='WIDGET')
        line = self.env['product.template.attribute.line'].create({
            'product_tmpl_id': template.id, 'attribute_id': self.attr_color.id,
            'value_ids': [(6, 0, self.color_blue.ids)],
        })
        ptav = line.product_template_value_ids
        self.assertEqual(template.build_default_code(ptav.ids), 'WIDGET.CB')

    def test_get_or_create_ptav_adds_the_value_to_the_line(self):
        template = self._make_template(base_code='CUT')
        line = self.env['product.template.attribute.line'].create({
            'product_tmpl_id': template.id, 'attribute_id': self.attr_profile.id,
            'value_ids': [(6, 0, [])],
        })
        ptav = line._get_or_create_ptav({'reference': self.profile_l4040})
        self.assertEqual(ptav.attribute_line_id, line)
        self.assertIn(ptav.product_attribute_value_id, line.value_ids)
        self.assertEqual(ptav._get_effective_reference(), self.profile_l4040)

    def test_get_or_create_ptav_is_idempotent(self):
        template = self._make_template(base_code='CUT')
        line = self.env['product.template.attribute.line'].create({
            'product_tmpl_id': template.id, 'attribute_id': self.attr_length.id,
            'value_ids': [(6, 0, [])],
        })
        first = line._get_or_create_ptav({'number': 800.0})
        second = line._get_or_create_ptav({'number': 800.0})
        self.assertEqual(first, second)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant:TestCodes --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|AttributeError"
```
Expected: `_build_code_value` / `_get_or_create_ptav` missing.

- [ ] **Step 3: Implement code generation**

Append to `models/product_attribute.py`:

```python
    def _build_code_value(self, normalized):
        """Build the `code_value` of a materialised value.

        Overridable per attribute type. References borrow the referenced
        record's own code so the generated `default_code` stays readable,
        which is the same composition Infor LN uses for generated item codes.
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
```

Add `import unicodedata` to the module imports.

- [ ] **Step 4: Implement PTAV materialisation**

Create `models/product_template_attribute_line.py`:

```python
from odoo import models


class ProductTemplateAttributeLine(models.Model):
    _inherit = 'product.template.attribute.line'

    def _get_or_create_ptav(self, payload):
        """Return the template attribute value for a payload.

        Materialises the attribute value if needed and adds it to this line,
        which is the precondition for Odoo to build the dynamic variant.
        """
        self.ensure_one()
        value = self.attribute_id._get_or_create_value(payload)
        if value not in self.value_ids:
            self.write({'value_ids': [(4, value.id)]})
        ptav = self.product_template_value_ids.filtered(
            lambda p: p.product_attribute_value_id == value)
        if not ptav:
            self._update_product_template_attribute_values()
            ptav = self.product_template_value_ids.filtered(
                lambda p: p.product_attribute_value_id == value)
        if ptav and not ptav.ptav_active:
            ptav.write({'ptav_active': True})
        return ptav
```

Add `from . import product_template_attribute_line` to `models/__init__.py`, after `product_template_attribute_value`.

- [ ] **Step 5: Run it and watch it pass**

Same command as Step 2. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 6: Commit**

```bash
git add numa_product_variant/models/ numa_product_variant/tests/test_codes.py
git commit -m "feat(numa_product_variant): code generation and template value materialisation"
```

---

### Task 6: Lifecycle — archiving and referential integrity

**Files:**
- Modify: `models/product_attribute_value.py`
- Create: `data/ir_cron.xml`, `tests/test_lifecycle.py`
- Modify: `__manifest__.py`

**Interfaces:**
- Consumes: `is_materialized` (Task 3), materialisation (Task 4).
- Produces: `product.attribute.value._gc_materialized_values()`.

- [ ] **Step 1: Write the failing test**

`tests/test_lifecycle.py`:

```python
import psycopg2

from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestLifecycle(NumaVariantCommon):

    def test_gc_archives_unused_materialized_values(self):
        value = self.attr_legend._get_or_create_value({'char': 'Orphan'})
        self.env['product.attribute.value']._gc_materialized_values()
        self.assertFalse(value.active)

    def test_gc_never_touches_curated_values(self):
        self.env['product.attribute.value']._gc_materialized_values()
        self.assertTrue(self.color_red.active)

    def test_gc_keeps_values_used_by_a_template(self):
        template = self._make_template(base_code='CUT')
        line = self.env['product.template.attribute.line'].create({
            'product_tmpl_id': template.id, 'attribute_id': self.attr_profile.id,
            'value_ids': [(6, 0, [])],
        })
        ptav = line._get_or_create_ptav({'reference': self.profile_l4040})
        self.env['product.attribute.value']._gc_materialized_values()
        self.assertTrue(ptav.product_attribute_value_id.active)

    @mute_logger('odoo.sql_db')
    def test_referenced_template_cannot_be_deleted(self):
        self.attr_profile._get_or_create_value({'reference': self.profile_l4040})
        with self.assertRaises(psycopg2.errors.ForeignKeyViolation):
            with self.env.cr.savepoint():
                self.profile_l4040.unlink()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant:TestLifecycle --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|AttributeError"
```
Expected: `_gc_materialized_values` missing.

- [ ] **Step 3: Implement the garbage collector**

Append to `models/product_attribute_value.py`:

```python
    @api.model
    def _gc_materialized_values(self, limit=1000):
        """Archive materialised values that ended up unused.

        Materialising a master record per free value is something the
        industrial configurators deliberately avoid; Odoo forces it because
        variant identity is the set of template attribute values. Archiving
        keeps the master data from growing without bound.

        Never deletes, never touches hand-curated values, never touches a
        value still used by a product.
        """
        candidates = self.with_context(active_test=False).search([
            ('is_materialized', '=', True),
            ('active', '=', True),
            ('pav_attribute_line_ids', '=', False),
        ], limit=limit)
        stale = candidates.filtered(lambda value: not value.is_used_on_products)
        if stale:
            stale.write({'active': False})
        return len(stale)
```

- [ ] **Step 4: Register the cron**

Create `data/ir_cron.xml`:

```xml
<?xml version="1.0"?>
<odoo>
    <data noupdate="1">
        <record id="ir_cron_gc_materialized_values" model="ir.cron">
            <field name="name">Product Variant: archive unused materialised attribute values</field>
            <field name="model_id" ref="product.model_product_attribute_value"/>
            <field name="state">code</field>
            <field name="code">model._gc_materialized_values()</field>
            <field name="interval_number">1</field>
            <field name="interval_type">days</field>
            <field name="numbercall">-1</field>
            <field name="active" eval="True"/>
        </record>
    </data>
</odoo>
```

Add `'data/ir_cron.xml'` to the `data` list in `__manifest__.py`, before the views.

- [ ] **Step 5: Run it and watch it pass**

Same command as Step 2. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 6: Commit**

```bash
git add numa_product_variant/models/ numa_product_variant/data/ numa_product_variant/tests/test_lifecycle.py numa_product_variant/__manifest__.py
git commit -m "feat(numa_product_variant): archive unused materialised attribute values"
```

---

### Task 7: Public resolution API

**Files:**
- Modify: `models/product.py`
- Test: `tests/test_resolution_api.py` (create)

**Interfaces:**
- Consumes: `_get_effective_reference` (Task 3).
- Produces: on `product.product` — `get_attribute_reference(attribute)`, `get_attribute_references(model=None)`, `find_matching_variants(base_template)`.

- [ ] **Step 1: Write the failing test**

`tests/test_resolution_api.py`:

```python
from odoo.tests import tagged

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestResolutionApi(NumaVariantCommon):

    def setUp(self):
        super().setUp()
        self.cut = self._make_cut_piece_template()

    def test_get_attribute_reference_returns_the_base_template(self):
        variant = self._configure_cut_piece(
            profile=self.profile_l4040, colour=self.color_red, length=800.0)
        self.assertEqual(
            variant.get_attribute_reference(self.attr_profile),
            self.profile_l4040)

    def test_get_attribute_reference_is_false_without_one(self):
        variant = self._configure_cut_piece(
            profile=self.profile_l4040, colour=self.color_red, length=800.0)
        self.assertFalse(variant.get_attribute_reference(self.attr_color))

    def test_get_attribute_references_filters_by_model(self):
        variant = self._configure_cut_piece(
            profile=self.profile_l4040, colour=self.color_red, length=800.0)
        found = variant.get_attribute_references(model='product.template')
        self.assertEqual(list(found.values()), [self.profile_l4040])

    def test_find_matching_variants_leaves_free_attributes_unconstrained(self):
        """Strip length exists on the base but not on the cut piece, so both
        strip lengths must come back as candidates."""
        variant = self._configure_cut_piece(
            profile=self.profile_l4040, colour=self.color_red, length=800.0)
        candidates = variant.find_matching_variants(self.profile_l4040)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            set(candidates.mapped('product_template_attribute_value_ids.product_attribute_value_id')
                & (self.strip_6m + self.strip_45m)),
            set(self.strip_6m + self.strip_45m))

    def test_find_matching_variants_respects_shared_values(self):
        """A red cut piece must not match blue strips."""
        variant = self._configure_cut_piece(
            profile=self.profile_l4040, colour=self.color_red, length=800.0)
        candidates = variant.find_matching_variants(self.profile_l4040)
        blue_values = candidates.mapped(
            'product_template_attribute_value_ids.product_attribute_value_id')
        self.assertNotIn(self.color_blue, blue_values)
```

Add the two helpers to `tests/common.py`:

```python
    def _make_cut_piece_template(self):
        """A cut piece: profile reference + colour (shared with the base) +
        free segment length. Deliberately has no strip-length attribute."""
        template = self.env['product.template'].create({
            'name': 'Aluminium cut piece', 'type': 'consu',
            'purchase_ok': True, 'weight_kind': 'normal',
            'price_base': 'normal', 'base_code': 'CUT',
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        Line = self.env['product.template.attribute.line']
        Line.create([
            {'product_tmpl_id': template.id, 'attribute_id': self.attr_profile.id,
             'value_ids': [(6, 0, [])]},
            {'product_tmpl_id': template.id, 'attribute_id': self.attr_color.id,
             'value_ids': [(6, 0, (self.color_red + self.color_blue).ids)]},
            {'product_tmpl_id': template.id, 'attribute_id': self.attr_length.id,
             'value_ids': [(6, 0, [])]},
        ])
        return template

    def _configure_cut_piece(self, profile, colour, length):
        """Materialise the open values and build the variant."""
        lines = {line.attribute_id: line for line in self.cut.attribute_line_ids}
        ptavs = (
            lines[self.attr_profile]._get_or_create_ptav({'reference': profile})
            + lines[self.attr_color].product_template_value_ids.filtered(
                lambda p: p.product_attribute_value_id == colour)
            + lines[self.attr_length]._get_or_create_ptav({'number': length})
        )
        return self.cut._create_product_variant(ptavs)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant:TestResolutionApi --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|AttributeError"
```
Expected: `get_attribute_reference` missing.

- [ ] **Step 3: Implement the API**

Append to `class ProductProduct` in `models/product.py`:

```python
    def get_attribute_reference(self, attribute):
        """Record referenced by this variant's value of `attribute`.

        Returns an empty recordset when the attribute is not a reference
        attribute or carries no reference.
        """
        self.ensure_one()
        ptav = self.product_template_attribute_value_ids.filtered(
            lambda value: value.attribute_id == attribute)
        if not ptav:
            return self.env['product.template'].browse()
        return ptav[0]._get_effective_reference()

    def get_attribute_references(self, model=None):
        """Every reference carried by this variant, keyed by attribute.

        `model` restricts the result to references of that model.
        """
        self.ensure_one()
        result = {}
        for ptav in self.product_template_attribute_value_ids:
            if ptav.attribute_id.value_type != 'reference':
                continue
            target = ptav._get_effective_reference()
            if not target:
                continue
            if model and target._name != model:
                continue
            result[ptav.attribute_id] = target
        return result

    def find_matching_variants(self, base_template):
        """Variants of `base_template` sharing this variant's attribute values.

        Attributes present on the base template but absent here — strip length,
        sheet size — are left unconstrained, so this returns a candidate set
        rather than a single variant. Pure mechanism: it does not choose.
        """
        self.ensure_one()
        own_values = self.product_template_attribute_value_ids.mapped(
            'product_attribute_value_id')
        shared_attributes = base_template.attribute_line_ids.attribute_id & \
            self.product_template_attribute_value_ids.attribute_id

        candidates = base_template.product_variant_ids
        for attribute in shared_attributes:
            expected = own_values.filtered(
                lambda value: value.attribute_id == attribute)
            if not expected:
                continue
            candidates = candidates.filtered(
                lambda variant: expected <= variant.product_template_attribute_value_ids
                .mapped('product_attribute_value_id'))
        return candidates
```

- [ ] **Step 4: Run it and watch it pass**

Same command as Step 2. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 5: Commit**

```bash
git add numa_product_variant/models/product.py numa_product_variant/tests/
git commit -m "feat(numa_product_variant): public attribute reference resolution API"
```

---

### Task 8: Views and Phase 1 documentation

**Files:**
- Modify: `views/product_views.xml`, `README.md`, `__manifest__.py`

**Interfaces:**
- Consumes: every field from Tasks 2 and 3.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the attribute fields to the form**

In `views/product_views.xml`, inside the existing `product_attribute_form_view`, replace the `group[@name='sale_main_fields']` block with:

```xml
                <group name="sale_main_fields" position="inside">
                    <field name="code_identifier" />
                    <field name="default_value" />
                    <field name="change_on_create" />
                    <field name="value_type" />
                    <field name="reference_model"
                           invisible="value_type != 'reference'"
                           required="value_type == 'reference'" />
                    <field name="reference_domain"
                           invisible="value_type != 'reference'" />
                    <field name="allow_additional_values" />
                    <field name="number_min" invisible="value_type != 'number'" />
                    <field name="number_max" invisible="value_type != 'number'" />
                    <field name="number_rounding" invisible="value_type != 'number'" />
                    <field name="code_format" />
                </group>
```

And extend the value list inside the same view:

```xml
                <xpath expr="//page/field[@name='value_ids']/list/field[@name='name']" position="before">
                    <field name="code_value"/>
                    <field name="value_on_create"/>
                    <field name="weight_factor"/>
                    <field name="reference_record"
                           invisible="parent.value_type != 'reference'"/>
                    <field name="is_materialized" optional="hide"/>
                </xpath>
```

- [ ] **Step 2: Add the override field to the template value form**

In the existing `product_template_attribute_value_view_form` record:

```xml
                <field name="name" position="after">
                    <field name="code_value" />
                    <field name="reference_record"
                           string="Reference override"
                           help="Overrides the attribute value's own reference for this template only."/>
                </field>
```

- [ ] **Step 3: Bump the version**

In `__manifest__.py`, set `'version': '18.0.0.3'`.

- [ ] **Step 4: Document Phase 1 in the README**

Add a `## Typed attribute values` section to `README.md` covering: the two orthogonal axes (`value_type` versus `create_variant` versus `display_type`), the five configuration cases from the spec table, the materialisation contract (`_get_or_create_value` payload shapes), the `canonical_key` rationale, the lifecycle policy, and the public API with the joinery worked example. Include the prior-art table from the spec so the reasoning survives.

- [ ] **Step 5: Run the whole suite**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant --stop-after-init --log-level=test 2>&1 | grep odoo.tests.result
```
Expected: `0 failed, 0 error(s)`.

- [ ] **Step 6: Commit**

```bash
git add numa_product_variant/
git commit -m "feat(numa_product_variant): expose typed attribute fields in views, document phase 1"
```

---

### Task 9: `resolve_value` controller routes

**Files:**
- Modify: `controllers/product_configurator.py`
- Test: `tests/test_resolve_value_controllers.py` (create)

**Interfaces:**
- Consumes: `_get_or_create_ptav` (Task 5).
- Produces: routes `/sale/product_configurator/resolve_value` and `/purchase/product_configurator/resolve_value`, both returning `{'ptav_id': int, 'name': str, 'code_value': str}`.

- [ ] **Step 1: Write the failing test**

`tests/test_resolve_value_controllers.py`, following the existing `tests/test_purchase_configurator_controllers.py`:

```python
import json

from odoo.tests import tagged, HttpCase

from .common import NumaVariantCommon


@tagged('post_install', '-at_install')
class TestResolveValueControllers(HttpCase, NumaVariantCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref('base.user_admin').write({'password': 'admin'})

    def setUp(self):
        super().setUp()
        self.cut = self._make_cut_piece_template()
        self.authenticate('admin', 'admin')

    def _resolve(self, route, line, payload):
        response = self.url_open(
            route,
            data=json.dumps({'params': {
                'product_template_id': self.cut.id,
                'ptal_id': line.id,
                'payload': payload,
            }}),
            headers={'Content-Type': 'application/json'},
        )
        return response.json()['result']

    def test_sale_route_materializes_a_reference(self):
        line = self.cut.attribute_line_ids.filtered(
            lambda l: l.attribute_id == self.attr_profile)
        result = self._resolve('/sale/product_configurator/resolve_value',
                               line, {'reference': ['product.template',
                                                    self.profile_l4040.id]})
        ptav = self.env['product.template.attribute.value'].browse(result['ptav_id'])
        self.assertEqual(ptav._get_effective_reference(), self.profile_l4040)
        self.assertEqual(result['code_value'], 'L4040')

    def test_purchase_route_materializes_a_number(self):
        line = self.cut.attribute_line_ids.filtered(
            lambda l: l.attribute_id == self.attr_length)
        result = self._resolve('/purchase/product_configurator/resolve_value',
                               line, {'number': 800.0})
        ptav = self.env['product.template.attribute.value'].browse(result['ptav_id'])
        self.assertEqual(ptav.product_attribute_value_id.free_number, 800.0)

    def test_route_is_idempotent(self):
        line = self.cut.attribute_line_ids.filtered(
            lambda l: l.attribute_id == self.attr_length)
        first = self._resolve('/purchase/product_configurator/resolve_value',
                              line, {'number': 800.0})
        second = self._resolve('/purchase/product_configurator/resolve_value',
                               line, {'number': 800.0})
        self.assertEqual(first['ptav_id'], second['ptav_id'])

    def test_line_must_belong_to_the_template(self):
        other = self._make_template(base_code='OTHER')
        line = self.env['product.template.attribute.line'].create({
            'product_tmpl_id': other.id, 'attribute_id': self.attr_color.id,
            'value_ids': [(6, 0, self.color_red.ids)],
        })
        response = self.url_open(
            '/sale/product_configurator/resolve_value',
            data=json.dumps({'params': {
                'product_template_id': self.cut.id,
                'ptal_id': line.id,
                'payload': {'char': 'x'},
            }}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertIn('error', response.json())
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant:TestResolveValueControllers --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|404"
```
Expected: 404 on both routes.

- [ ] **Step 3: Implement the routes**

Append to `controllers/product_configurator.py`:

```python
class ProductConfiguratorValueResolver(SaleProductConfiguratorController):
    """Translate an open attribute value into a template attribute value.

    The whole configurator speaks in PTAV ids, so materialising an open value
    into one keeps the rest of the flow — combination update, exclusions,
    pricing, variant creation — completely untouched.
    """

    def _resolve_value(self, product_template_id, ptal_id, payload):
        line = request.env['product.template.attribute.line'].browse(ptal_id)
        line.check_access('read')
        if line.product_tmpl_id.id != product_template_id:
            raise UserError(_(
                "Attribute line %(line)s does not belong to this product.",
                line=ptal_id))
        normalized = dict(payload)
        reference = normalized.get('reference')
        if isinstance(reference, list):
            normalized['reference'] = (reference[0], reference[1])
        ptav = line.sudo()._get_or_create_ptav(normalized)
        return {
            'ptav_id': ptav.id,
            'name': ptav.name,
            'code_value': ptav.code_value,
        }

    @route(route='/sale/product_configurator/resolve_value',
           type='json', auth='user', methods=['POST'])
    def sale_product_configurator_resolve_value(
            self, product_template_id, ptal_id, payload, **kwargs):
        return self._resolve_value(product_template_id, ptal_id, payload)

    @route(route='/purchase/product_configurator/resolve_value',
           type='json', auth='user', methods=['POST'])
    def purchase_product_configurator_resolve_value(
            self, product_template_id, ptal_id, payload, **kwargs):
        return self._resolve_value(product_template_id, ptal_id, payload)
```

Add `from odoo import _` and `from odoo.exceptions import UserError` to the module imports.

- [ ] **Step 4: Run it and watch it pass**

Same command as Step 2. Expected: `0 failed, 0 error(s)`.

- [ ] **Step 5: Commit**

```bash
git add numa_product_variant/controllers/ numa_product_variant/tests/test_resolve_value_controllers.py
git commit -m "feat(numa_product_variant): resolve_value routes for sale and purchase configurators"
```

---

### Task 10: OWL component support for open values

**Files:**
- Create: `static/src/js/product_template_attribute_line_patch.js`, `static/src/xml/product_template_attribute_line_patch.xml`
- Modify: `controllers/product_configurator.py` (extend `get_values` payload), `__manifest__.py`

**Interfaces:**
- Consumes: the `resolve_value` routes (Task 9).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Extend the configurator payload with the typing metadata**

The OWL component cannot render the extra control without knowing the attribute's type. Override `_get_product_information` in `controllers/product_configurator.py` to enrich each attribute line:

```python
    def _get_product_information(self, *args, **kwargs):
        result = super()._get_product_information(*args, **kwargs)
        lines = result.get('attribute_lines') or []
        line_ids = [line['id'] for line in lines]
        records = request.env['product.template.attribute.line'].browse(line_ids)
        by_id = {record.id: record for record in records}
        for line in lines:
            attribute = by_id[line['id']].attribute_id
            line['attribute'].update({
                'value_type': attribute.value_type,
                'allow_additional_values': attribute.allow_additional_values,
                'reference_model': attribute.reference_model or False,
                'reference_domain': attribute.reference_domain or '[]',
                'number_min': attribute.number_min,
                'number_max': attribute.number_max,
                'number_rounding': attribute.number_rounding,
            })
        return result
```

- [ ] **Step 2: Patch the OWL component**

`static/src/js/product_template_attribute_line_patch.js`:

```javascript
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { ProductTemplateAttributeLine } from "@sale/js/product_template_attribute_line/product_template_attribute_line";

/**
 * Support attributes whose value is not confined to the predefined list:
 * a reference to a record, a free number, a free text or a free date.
 *
 * The predefined list keeps rendering through its own display_type. The extra
 * control appears beside it, never instead of it, so a list of suggestions and
 * free entry can coexist — the behaviour SAP calls "additional values".
 */
patch(ProductTemplateAttributeLine.prototype, {

    get acceptsOpenValue() {
        const attribute = this.props.attribute;
        return attribute.allow_additional_values
            || this.props.attribute_values.length === 0;
    },

    get openValueType() {
        return this.props.attribute.value_type;
    },

    /**
     * Materialise the typed value server-side and select the resulting PTAV.
     */
    async submitOpenValue(payload) {
        const result = await rpc(this.env.resolveValueUrl, {
            product_template_id: this.props.productTmplId,
            ptal_id: this.props.id,
            payload: payload,
        });
        this.props.attribute_values.push({
            id: result.ptav_id,
            name: result.name,
            html_color: false,
            image: false,
            is_custom: false,
            price_extra: 0,
        });
        this.env.updateProductTemplateSelectedPTAV(
            this.props.productTmplId, this.props.id, result.ptav_id, false
        );
    },

    onOpenReferenceSelected(record) {
        return this.submitOpenValue({
            reference: [this.props.attribute.reference_model, record.id],
        });
    },

    onOpenNumberConfirmed(event) {
        return this.submitOpenValue({ number: parseFloat(event.target.value) });
    },

    onOpenTextConfirmed(event) {
        return this.submitOpenValue({ char: event.target.value });
    },

    onOpenDateConfirmed(event) {
        return this.submitOpenValue({ date: event.target.value });
    },
});

ProductTemplateAttributeLine.props.attribute.shape.value_type = {
    type: String, optional: true,
};
ProductTemplateAttributeLine.props.attribute.shape.allow_additional_values = {
    type: Boolean, optional: true,
};
ProductTemplateAttributeLine.props.attribute.shape.reference_model = {
    type: [Boolean, String], optional: true,
};
ProductTemplateAttributeLine.props.attribute.shape.reference_domain = {
    type: String, optional: true,
};
ProductTemplateAttributeLine.props.attribute.shape.number_min = {
    type: Number, optional: true,
};
ProductTemplateAttributeLine.props.attribute.shape.number_max = {
    type: Number, optional: true,
};
ProductTemplateAttributeLine.props.attribute.shape.number_rounding = {
    type: Number, optional: true,
};
```

- [ ] **Step 3: Extend the template**

`static/src/xml/product_template_attribute_line_patch.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

    <t t-name="numa_product_variant.OpenValueControl"
       t-inherit="sale.ProductTemplateAttributeLine"
       t-inherit-mode="extension">
        <xpath expr="//div[hasclass('o_ptal_values')]" position="after">
            <div class="o_ptal_open_value mt-2" t-if="acceptsOpenValue">
                <input t-if="openValueType === 'number'"
                       type="number" class="form-control"
                       t-att-min="props.attribute.number_min or undefined"
                       t-att-max="props.attribute.number_max or undefined"
                       t-att-step="props.attribute.number_rounding"
                       t-on-change="onOpenNumberConfirmed"
                       placeholder="Enter a value"/>
                <input t-elif="openValueType === 'date'"
                       type="date" class="form-control"
                       t-on-change="onOpenDateConfirmed"/>
                <input t-elif="openValueType === 'char'"
                       type="text" class="form-control"
                       t-on-change="onOpenTextConfirmed"
                       placeholder="Enter a value"/>
                <Many2XAutocomplete t-elif="openValueType === 'reference'"
                       resModel="props.attribute.reference_model"
                       getDomain="() => JSON.parse(props.attribute.reference_domain)"
                       update="(records) => this.onOpenReferenceSelected(records[0])"
                       quickCreate="null"
                       value="''"/>
            </div>
        </xpath>
    </t>

</templates>
```

Import `Many2XAutocomplete` from `@web/views/fields/relational_utils` and register it in `ProductTemplateAttributeLine.components` inside the patch file.

- [ ] **Step 4: Provide the endpoint through the environment**

The sales dialog and the purchase dialog hit different URLs. In `static/src/js/purchase_product_configurator_dialog.js`, add `resolveValueUrl` to the sub-environment alongside the existing overridden URLs, using `/purchase/product_configurator/resolve_value`; add the sales default `/sale/product_configurator/resolve_value` in the patch file's `setup`.

- [ ] **Step 5: Register the assets**

In `__manifest__.py`:

```python
    'assets': {
        'web.assets_backend': [
            'numa_product_variant/static/src/js/purchase_product_configurator_dialog.js',
            'numa_product_variant/static/src/js/purchase_product_field.js',
            'numa_product_variant/static/src/js/product_template_attribute_line_patch.js',
            'numa_product_variant/static/src/xml/product_template_attribute_line_patch.xml',
        ],
    },
```

- [ ] **Step 6: Run the whole suite**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant --stop-after-init --log-level=test 2>&1 | grep odoo.tests.result
```
Expected: `0 failed, 0 error(s)`.

- [ ] **Step 7: Commit**

```bash
git add numa_product_variant/static/ numa_product_variant/controllers/ numa_product_variant/__manifest__.py
git commit -m "feat(numa_product_variant): open value controls in the product configurator"
```

---

### Task 11: Final documentation and full verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Complete the README**

Extend the `## Typed attribute values` section with the configurator behaviour, the `resolve_value` contract, the OWL extension points, the explicit `website_sale` / POS exclusion and why server-side validation covers them, and a troubleshooting subsection covering: duplicate values appearing (rounding too fine), `ValidationError` on a closed attribute, and referenced records that cannot be deleted.

- [ ] **Step 2: Run the full suite one last time**

```bash
cd /home/gamarino/odoo/cm-18.0 && .venv/bin/python3 ../numa-public-odoo-18.0-numa/odoo-bin \
  -c odoo.config -d cm-test-18.0 -u numa_product_variant --test-enable \
  --test-tags /numa_product_variant --stop-after-init --log-level=test 2>&1 | grep -E "odoo.tests.result|odoo.tests.stats"
```
Expected: `0 failed, 0 error(s)`, test count well above the 19 baseline.

- [ ] **Step 3: Commit**

```bash
git add numa_product_variant/README.md
git commit -m "docs(numa_product_variant): document typed attribute values and record references"
```

---

## Self-Review

**Spec coverage:** attribute type declaration → Task 2. Reference payload and PTAV override → Task 3. Uniqueness and determinism → Task 4. Concurrency → Task 4. Code generation → Task 5. `_get_or_create_ptav` → Task 5. Lifecycle and GC → Task 6. Public API → Task 7. Validation table → Tasks 2, 3, 4. Views → Task 8. `resolve_value` → Task 9. OWL component → Task 10. Backward compatibility → Task 1 baseline plus the Task 5 `build_default_code` regression test. Documentation → Tasks 8 and 11.

**Deviations from the spec, both justified above:** `canonical_key` replaces `name` as the deduplication key; the mixin carries only the reference payload.

**Type consistency:** `_normalize_payload` returns `{'key', 'target', 'values', 'label'}` and is consumed by `_find_value`, `_get_or_create_value` and `_build_code_value` with those exact keys. `_get_or_create_value(payload)` returns `product.attribute.value`; `_get_or_create_ptav(payload)` returns `product.template.attribute.value`. `_get_effective_reference()` exists only on `product.template.attribute.value`; `_get_reference_record()` exists on both value models via the mixin.
