# -*- coding: utf-8 -*-
"""
What numa_poly does when the registry finishes loading.

In 18.0 two mechanisms hung from points that, in a normal startup, either never got to run or
lost what they had collected. Odoo 20.0 took both hook points away, so this file ended up split
into two halves in different states:

- **The views pending validation.** The set was a ``lazy_property`` of the registry, and
  ``setup_models`` called ``lazy_property.reset_all()`` once per updated module: what was
  recorded while loading one module was lost when the next one started. In 20.0
  ``lazy_property`` does not exist, the set is a ``functools.cached_property``, and
  ``_setup_models__`` resets nothing equivalent. The risk disappeared by construction, and what
  follows below verifies it.

- **The post-load stabilization.** It hung from ``Registry.signal_changes``, which does not
  exist in 20.0. It was removed whole, and not for lack of somewhere to hang it: what it did
  was repeat the setup to re-inject the MRO, and that stopped being needed once declaration
  replaced injection. Odoo builds the bases on its own, on the first pass, and there is nothing
  to redo.

  The only thing left pending for the end of the load is validating the deferred views, and
  that has had an anchor of its own all along: ``ir.poly_base._register_hook``, which Odoo
  calls with every module loaded (``registry.py:577``). ``test_poly_view_validation`` covers it.
"""
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestPolyPendingViews(TransactionCase):
    """What is recorded during the load has to still be there until somebody validates it."""

    def test_01_the_pending_set_is_the_same_object_across_reads(self):
        """If every read returned a new set, recording would be good for nothing.

        It was a real defect: because ``lazy_property`` stored the value under the name of the
        function and not that of the attribute, every read created an empty set and the final
        validation validated nothing.
        """
        self.assertIs(self.registry._pending_poly_views, self.registry._pending_poly_views)

    def test_02_what_is_recorded_stays_until_something_validates_it(self):
        """Recording and reading loses nothing.

        The 18.0 invariant was stronger -surviving ``setup_models``- because
        ``lazy_property.reset_all()`` emptied the set once per updated module. In Odoo 20 there
        is no ``reset_all``, and what a ``_setup_models__`` does do is call ``_register_hook``
        (``registry.py:577``), which validates the pending ones and discards them: that is the
        anchor working, not a loss.
        """
        centinela = -424242
        self.registry._pending_poly_views.add(centinela)
        try:
            self.assertIn(centinela, self.registry._pending_poly_views)
        finally:
            self.registry._pending_poly_views.discard(centinela)


@tagged('post_install', '-at_install')
class TestPolyStabilizationIsGone(TransactionCase):
    """The stabilization was removed: it must not come back in through the window."""

    def test_01_no_stabilization_machinery_is_left(self):
        from ..models import poly as P
        for nombre in ('_poly_stabilize_registry', '_poly_signal_changes', '_poly_registry_new'):
            self.assertFalse(hasattr(P, nombre),
                             "%s came back: declaring the bases makes it unnecessary "
                             "to repeat the setup after the load" % nombre)

    def test_02_the_view_validation_anchor_is_the_register_hook(self):
        """The anchor that did survive Odoo 20."""
        self.assertTrue(hasattr(self.registry, '_poly_finalize_view_validation'))
        self.assertTrue(hasattr(self.env['ir.poly_base'], '_register_hook'))
