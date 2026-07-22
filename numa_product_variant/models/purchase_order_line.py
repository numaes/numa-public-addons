from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    """Add product-template selection and the product configurator to PO lines.

    Entering a ``product_template_id`` triggers the same detection/trigger logic
    used by Sales (see the ``pol_product_many2one`` widget and the
    ``/purchase/product_configurator/*`` controllers): a non-configurable template
    auto-assigns its single variant, while a configurable one opens the reused
    Sales OWL configurator so the user picks or creates a variant. The persisted
    ``product_id`` remains the source of truth; pricing/name/UoM are recomputed by
    the standard purchase onchanges once it is set.
    """

    _inherit = 'purchase.order.line'

    # Mirrors sale.order.line: a non-stored computed template, editable so the
    # user can pick a template that drives the product configurator, while the
    # persisted product_id remains the source of truth.
    product_template_id = fields.Many2one(
        string="Product Template",
        comodel_name='product.template',
        compute='_compute_product_template_id',
        readonly=False,
        search='_search_product_template_id',
        domain=[('purchase_ok', '=', True)],
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related='product_template_id.has_configurable_attributes',
        depends=['product_template_id'],
    )

    @api.depends('product_id')
    def _compute_product_template_id(self):
        for line in self:
            line.product_template_id = line.product_id.product_tmpl_id

    def _search_product_template_id(self, operator, value):
        return [('product_id.product_tmpl_id', operator, value)]

    @api.onchange('product_template_id')
    def _onchange_product_template_id(self):
        """Auto-assign the single variant of a non-configurable template.

        Reuses product.template.get_single_product_variant(): it returns a
        product_id only when the template has exactly one, non-configurable
        variant. Configurable templates return {} and are handled by the OWL
        configurator dialog on the client side. Keeps the interface frictionless
        and also covers API/import flows where the JS widget does not run.
        """
        for line in self:
            template = line.product_template_id
            if not template:
                line.product_id = False
                continue
            result = template.get_single_product_variant()
            product_id = result.get('product_id')
            if product_id and line.product_id.id != product_id:
                line.product_id = product_id
            # Configurable template (empty result): leave product_id untouched.
