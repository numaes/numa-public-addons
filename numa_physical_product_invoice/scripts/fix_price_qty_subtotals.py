# Server Action: Fix price_qty and recompute subtotals
# Model: account.move.line  (or run from base model with no record binding)
# Type: Python code
#
# Replicates compute_price() logic to set price_qty correctly on all posted
# invoice/refund lines, then recomputes price_subtotal via _compute_amount().
#
# Run in Odoo shell:
#   exec(open('scripts/fix_price_qty_subtotals.py').read())
# Or paste into a Server Action (Settings > Technical > Server Actions).

import logging
_logger = logging.getLogger(__name__)

PRICE_BASE_FIELD = {
    'length':  'product_length',
    'width':   'product_width',
    'height':  'product_height',
    'surface': 'surface',
    'weight':  'weight',
    'volume':  'volume',
}

INVOICE_TYPES = ['out_invoice', 'in_invoice', 'out_refund', 'in_refund']

# ── 1. Fetch all invoice lines that have price_qty set ──────────────────────

lines = env['account.move.line'].sudo().search([
    ('move_id.move_type', 'in', INVOICE_TYPES),
    ('price_qty', '!=', False),
    ('product_id', '!=', False),
])

_logger.info("[fix_price_qty] Checking %d invoice lines", len(lines))

updated    = env['account.move.line']
skipped    = 0

for line in lines:
    product    = line.product_id
    price_base = product.price_base or 'normal'

    # Quantity normalised to the product's internal UoM
    if line.product_uom_id and product.uom_id:
        norm_qty = line.product_uom_id._compute_quantity(
            line.quantity, product.uom_id
        )
    else:
        norm_qty = line.quantity

    # Compute expected price_qty
    if price_base == 'normal':
        expected_qty = norm_qty
    elif price_base in ('length', 'width', 'height'):
        unit_val = getattr(product, PRICE_BASE_FIELD[price_base], 0.0)
        expected_qty = unit_val * norm_qty
    elif price_base == 'surface':
        expected_qty = norm_qty * (product.surface or 0.0)
    elif price_base == 'weight':
        expected_qty = norm_qty * (product.weight or 0.0)
    elif price_base == 'volume':
        expected_qty = norm_qty * (product.volume or 0.0)
    else:
        expected_qty = norm_qty

    if abs((line.price_qty or 0.0) - expected_qty) < 0.0001:
        skipped += 1
        continue

    _logger.info(
        "[fix_price_qty] line %d | product=%s | price_base=%s | "
        "price_qty: %.4f → %.4f | quantity=%.4f",
        line.id, product.display_name, price_base,
        line.price_qty, expected_qty, line.quantity,
    )
    line.with_context(check_move_validity=False).price_qty = expected_qty
    updated |= line

# ── 2. Recompute subtotals for changed lines ────────────────────────────────

if updated:
    updated.with_context(check_move_validity=False)._compute_totals()
    _logger.info("[fix_price_qty] Recomputed subtotals for %d lines", len(updated))

# ── 3. Summary ──────────────────────────────────────────────────────────────

summary = (
    f"fix_price_qty finished.\n"
    f"  Lines checked : {len(lines)}\n"
    f"  Lines updated : {len(updated)}\n"
    f"  Lines OK      : {skipped}\n"
)
_logger.info(summary)
raise UserError(summary)