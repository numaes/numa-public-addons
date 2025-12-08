# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models, exceptions, _


class FSMExecutionLog(models.Model):
    _name = 'fsm.execution.log'
    _description = 'FSM Execution Log (structured)'
    _order = 'timestamp desc, id desc'

    instance_id = fields.Many2one('fsm.instance', string='Instance', required=True, index=True, ondelete='cascade')
    timestamp = fields.Datetime(string='Timestamp', default=lambda self: fields.Datetime.now(), required=True, index=True)
    event_name = fields.Char(string='Event')
    from_state = fields.Char(string='From State')
    to_state = fields.Char(string='To State')
    input_snapshot = fields.Text(string='Input Snapshot (JSON)')
    output_snapshot = fields.Text(string='Output Snapshot (JSON)')
    status = fields.Selection(
        selection=[('success', 'Success'), ('error', 'Error'), ('intercepted', 'Intercepted')],
        string='Status',
        default='success',
        required=True,
        index=True,
    )
    log_type = fields.Selection(
        selection=[('info', 'Info'), ('warning', 'Warning'), ('error', 'Error')],
        string='Type',
        default='info',
        required=True,
    )
    error_msg = fields.Text(string='Error Message / Traceback')

    # ------------------------------------------------------------------
    # Simulation / Replay
    # ------------------------------------------------------------------
    def action_replay_simulation(self):
        """Replay this log entry by creating a simulation clone of the instance.

        Steps:
        - Clone the base instance (name, definition, etc.), mark as is_simulation=True
        - Restore current_state and env prior to the event (from input_snapshot/from_state)
        - Re-trigger the event once with a debug bypass context
        - Return an action opening the new instance
        """
        self.ensure_one()

        # Resolve prior env and event from snapshot
        prior_env = {}
        event_payload = None
        if self.input_snapshot:
            try:
                snap = json.loads(self.input_snapshot)
                if isinstance(snap, dict):
                    prior_env = snap.get('env') or {}
                    event_payload = snap.get('event')
            except Exception:
                prior_env = {}

        # Build event dict fallback
        if not event_payload:
            event_payload = {'name': self.event_name} if self.event_name else {}

        base_instance = self.instance_id.sudo()
        Instance = self.env['fsm.instance'].sudo()

        # Prepare name
        base_name = base_instance.display_name or base_instance.name or _('FSM Instance')
        sim_name = f"{base_name} (Simulation Replay ID: {self.id})"

        # Create the simulation instance
        new_instance = Instance.create({
            'definition_id': base_instance.definition_id.id,
            'name': sim_name,
            'state': 'running',  # ensure it can process events
            'is_simulation': True,
        })

        # Restore state and env BEFORE the event was processed originally
        try:
            new_instance.write({
                'current_state': self.from_state or base_instance.current_state,
                'json_instance_values': json.dumps(prior_env or {}),
            })
        except Exception:
            # fallback to minimal env
            new_instance.write({
                'current_state': self.from_state or base_instance.current_state,
                'json_instance_values': json.dumps({}),
            })

        # Trigger the event once, bypassing interceptors
        try:
            env_dict = new_instance.prepare_env()
            new_instance.with_context(debug_step_bypass=True).process_event(event_payload, env_dict)
            new_instance.flush_env(env_dict)
        except Exception as e:
            # Do not block opening the simulation; developer can inspect logs
            # Optionally post a message
            try:
                new_instance.message_post(
                    subject=_('Simulation replay error'),
                    body=_('An error occurred while replaying the event: %s') % str(e),
                )
            except Exception:
                pass

        # Return action to open the new instance form
        try:
            view = self.env.ref('numa_fsm.instance_form_view')
            views = [(view.id, 'form')]
        except Exception:
            view = False
            views = False

        return {
            'type': 'ir.actions.act_window',
            'name': _('Simulation Replay') + f" #{self.id}",
            'res_model': 'fsm.instance',
            'res_id': new_instance.id,
            'view_mode': 'form',
            'views': views or [],
            'target': 'current',
        }
