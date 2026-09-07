# -*- coding: utf-8 -*-
"""
Rename fsm.instance.state to fsm_state.

``state`` is too common a name for a model whose whole purpose is to be mixed into
others. ``fsm.instance`` is a polymorphic base: ``conversation.message`` sits on it *and*
on ``digital.event``, which also declares ``state`` — with a different set of values. Two
bases contributing the same field name meant one silently won (``digital.event``), so
every ``message.state == 'init'`` in numa_conversation_fsm compared an event's processing
status against an FSM state and was quietly dead code. Odoo said so on every upgrade,
once per model of the hierarchy:

    conversation.message.state: selection=[...] overrides existing selection;
    use selection_add instead

Renaming here rather than on ``digital.event`` because the FSM side is the one that has
no claim to a generic name: an execution state belongs to the state machine, and saying
so in the field name is what keeps it from colliding with the next model it is mixed
into.

Done in pre-migration so the column arrives renamed and Odoo does not create an empty
``fsm_state`` beside a populated ``state``.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT to_regclass('fsm_instance')")
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        SELECT count(*) FROM information_schema.columns
         WHERE table_name = 'fsm_instance' AND column_name = 'state'
    """)
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        SELECT count(*) FROM information_schema.columns
         WHERE table_name = 'fsm_instance' AND column_name = 'fsm_state'
    """)
    if cr.fetchone()[0]:
        # A previous partial run already created it; carry over anything still only in
        # the old column rather than leaving two half-filled ones behind.
        cr.execute("UPDATE fsm_instance SET fsm_state = state WHERE fsm_state IS NULL")
        cr.execute("ALTER TABLE fsm_instance DROP COLUMN state")
        _logger.info("[numa_fsm] fsm_instance.state merged into fsm_state")
        return
    cr.execute("ALTER TABLE fsm_instance RENAME COLUMN state TO fsm_state")
    _logger.info("[numa_fsm] fsm_instance.state renamed to fsm_state")

    # The field's own ir.model.fields row, and anything keyed on the old name.
    cr.execute("""
        UPDATE ir_model_fields SET name = 'fsm_state'
         WHERE name = 'state'
           AND model = 'fsm.instance'
    """)
