# -*- coding: utf-8 -*-

from odoo import models


class PhysicalMagnitudes(models.AbstractModel):
    """Derivation of the magnitudes implied by a product's dimensions.

    Surface, volume and weight follow from length, width and height. They used
    to be produced by ``@api.onchange`` alone, so anything created or written
    through the ORM — an import, a data file, a configured variant — kept a
    surface of zero and was then costed at zero per square metre. The
    derivation now runs on every write path and the onchange delegates to it,
    so the form and the ORM cannot disagree.

    Two rules hold everywhere:

    - **A stated value is never overruled by a derived one.** The derivation
      fills in what the caller left out; it does not correct what the caller
      said. Passing ``surface`` explicitly keeps that surface.
    - **Nothing is derived unless something it depends on was written.** A
      write that touches no dimension leaves the magnitudes alone, so a
      hand-entered surface survives an unrelated edit.
    """

    _name = 'numa.physical.magnitudes'
    _description = 'Derived Physical Magnitudes'

    def _physical_triggers(self):
        """Field names whose write can change a derived magnitude."""
        raise NotImplementedError

    def _physical_derived_vals(self, stated=()):
        """The magnitudes implied by this record, as values to write.

        ``stated`` names the fields the caller wrote itself.
        """
        raise NotImplementedError

    def _physical_weight(self, surface, volume):
        """The weight implied by ``weight_kind``.

        Returns ``None`` when the weight is not derived at all, which is what
        ``weight_kind == 'normal'`` means: the weight was entered by hand and
        is nobody else's business.
        """
        self.ensure_one()
        magnitude = {
            'length': self.product_length,
            'width': self.product_width,
            'height': self.product_height,
            'surface': surface,
            'volume': volume,
        }.get(self.weight_kind)
        if not magnitude:
            # No magnitude, nothing to derive. A weight of zero obtained from a
            # dimension of zero states nothing, and writing it is not
            # harmless: on a single-variant template core keeps the two
            # weights in sync, so a zero derived from the template's empty
            # dimensions would travel down and erase the weight the variant
            # derived from its own.
            return None
        return self.weight_factor * magnitude

    def _apply_physical_derivation(self, stated=()):
        """Write the derived magnitudes that differ from what is stored."""
        for record in self:
            derived = {
                name: value
                for name, value in record._physical_derived_vals(stated).items()
                if record[name] != value
            }
            if derived:
                record.with_context(
                    numa_skip_physical_derivation=True).write(derived)

    def _physical_derivation_needed(self, vals):
        return (not self.env.context.get('numa_skip_physical_derivation')
                and any(name in vals for name in self._physical_triggers()))
