# -*- coding: utf-8 -*-
from odoo import api, fields, models


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
