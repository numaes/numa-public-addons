# -*- coding: utf-8 -*-
"""
Re-open the backfill pairs that were closed on a wrong answer.

Until this version the migration asked only whether *a* row with the record's id existed
in the base table. ``ir.poly_base`` is one id space for the whole polymorphic universe,
but pre-existing records come from per-table sequences, so a base row belonging to a
different concrete model read as "already reconstructed": the insert was a no-op, the
pair was closed as done, and the records were left without an identity of their own.

A closed pair is never scanned again, so every database upgraded before this fix carries
that verdict. Clearing the pairs here — in *pre*-migration, so it lands before ``init()``
runs in this same upgrade — is what makes the corrected scan look at them again.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT to_regclass('numa_poly_backfill_pair')")
    if not cr.fetchone()[0]:
        return
    cr.execute("UPDATE numa_poly_backfill_pair SET state = 'pending' "
               "WHERE state = 'done' RETURNING id")
    _logger.info("[poly] %s backfill pair(s) re-opened: they were closed by a test that "
                 "could not tell a record's own base row from another model's.",
                 cr.rowcount)
