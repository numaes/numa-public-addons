# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FSMDebugEvent(models.Model):
    _name = 'fsm.debug.event'
    _description = 'FSM Debug Event (paused/intercepted)'
    _order = 'id desc'

    instance_id = fields.Many2one('fsm.instance', string='Instance', required=True, index=True, ondelete='cascade')
    event_payload = fields.Text(string='Event Payload (JSON)')
    trigger_env = fields.Text(string='Trigger Env (JSON)')
    state = fields.Selection(
        selection=[('pending', 'Pending'), ('processed', 'Processed'), ('discarded', 'Discarded')],
        default='pending',
        required=True,
        index=True,
    )
