# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class HrEmployee(models.Model):
    """
    Extension of hr.employee to add FSM capabilities.
    
    Each employee can be converted into a Finite State Machine instance,
    allowing automated workflows and bot-driven employee processing.
    """
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'fsm.instance']
    _depend_models = {}

    # Bot assignment field (similar to conversation.session and crm.lead)
    bot_id = fields.Many2one(
        'hr.bot',
        string='HR Bot',
        tracking=True,
        help="The bot/FSM definition assigned to this employee for automated processing."
    )

    # FSM Definition field (computed from bot_id, but can be set directly)
    definition_id = fields.Many2one(
        'fsm.definition',
        string='FSM Definition',
        compute='_compute_fsm_definition_from_bot',
        store=True,
        readonly=False,
        help="The FSM definition that controls this employee's workflow."
    )

    # Current bot state (computed from FSM instance)
    bot_state = fields.Char(
        string="Bot State",
        compute='_compute_bot_state',
        store=True,
        help="Current state of the bot/FSM workflow."
    )

    # Flag to indicate if employee has active FSM
    has_fsm = fields.Boolean(
        string="Has Active FSM",
        compute='_compute_has_fsm',
        help="True if this employee has an active FSM instance."
    )

    @api.depends('bot_id')
    def _compute_fsm_definition_from_bot(self):
        """Compute definition_id from bot_id."""
        for employee in self:
            if employee.bot_id:
                employee.definition_id = employee.bot_id.fsm_definition_id
            elif not employee.definition_id:
                # Don't clear if manually set
                pass

    @api.depends('current_state_id')
    def _compute_bot_state(self):
        """Compute bot_state from FSM instance current state."""
        for employee in self:
            if employee.current_state_id:
                # Get the state label from the definition
                definition = employee.definition_id
                if definition and definition.json_ui_schema:
                    try:
                        import json
                        schema = definition.json_ui_schema
                        if isinstance(schema, str):
                            schema = json.loads(schema)
                        nodes = schema.get('nodes', [])
                        for node in nodes:
                            if node.get('id') == employee.current_state_id:
                                employee.bot_state = node.get('label', employee.current_state_id)
                                break
                        else:
                            employee.bot_state = employee.current_state_id
                    except Exception as e:
                        _logger.warning(f"Error computing bot_state for employee {employee.id}: {e}")
                        employee.bot_state = employee.current_state_id
                else:
                    employee.bot_state = employee.current_state_id
            else:
                employee.bot_state = False

    @api.depends('state', 'definition_id')
    def _compute_has_fsm(self):
        """Compute if employee has an active FSM instance."""
        for employee in self:
            employee.has_fsm = bool(
                employee.definition_id and 
                employee.state in ['running', 'paused']
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Handle FSM creation when employee is created with bot."""
        employees = super().create(vals_list)
        for employee in employees:
            # If bot is assigned, ensure definition is set
            if employee.bot_id and not employee.definition_id:
                employee.definition_id = employee.bot_id.fsm_definition_id
            
            # Start FSM if definition is set and employee should start automatically
            if employee.definition_id and employee.definition_id.state == 'production':
                # Auto-start FSM for new employees with bots
                try:
                    if employee.state == 'init':
                        employee.start()
                except Exception as e:
                    _logger.warning(f"Failed to auto-start FSM for employee {employee.id}: {e}")
        
        return employees

    def write(self, vals):
        """Handle bot assignment and FSM lifecycle."""
        # Handle bot_id changes
        if 'bot_id' in vals:
            bot = self.env['hr.bot'].browse(vals['bot_id']) if vals['bot_id'] else None
            vals['definition_id'] = bot.fsm_definition_id.id if bot else False
        
        res = super().write(vals)

        # After write, handle FSM lifecycle
        if 'bot_id' in vals or 'definition_id' in vals:
            for employee in self:
                # Start FSM if definition is set and instance is in init state
                if employee.definition_id and employee.state == 'init':
                    try:
                        employee.start()
                    except Exception as e:
                        _logger.warning(f"Failed to start FSM for employee {employee.id}: {e}")
        
        return res

    def action_assign_bot(self):
        """Action to assign a bot to the employee."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assign HR Bot'),
            'res_model': 'hr.bot',
            'view_mode': 'tree,form',
            'target': 'new',
            'domain': [('state', '=', 'production')],
            'context': {
                'default_employee_id': self.id,
                'select_bot': True,
            },
        }

    def action_start_fsm(self):
        """Manually start the FSM for this employee."""
        self.ensure_one()
        if not self.definition_id:
            raise UserError(_("No FSM definition assigned to this employee. Please assign a bot first."))
        
        if self.state != 'init':
            raise UserError(_("FSM is already running or has ended. Current state: %s") % self.state)
        
        try:
            self.start()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('FSM started successfully.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_("Failed to start FSM: %s") % str(e))

    def action_pause_fsm(self):
        """Pause the FSM execution (if in debug mode)."""
        self.ensure_one()
        if not self.definition_id:
            raise UserError(_("No FSM definition assigned."))
        
        if self.state != 'running':
            raise UserError(_("FSM is not running. Current state: %s") % self.state)
        
        # Set debug mode to pause on next breakpoint
        self.write({'debug_mode': 'step_by_step'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('FSM Paused'),
                'message': _('FSM will pause at the next breakpoint.'),
                'type': 'info',
                'sticky': False,
            }
        }

    def action_resume_fsm(self):
        """Resume FSM execution."""
        self.ensure_one()
        if not self.definition_id:
            raise UserError(_("No FSM definition assigned."))
        
        if self.state != 'paused':
            raise UserError(_("FSM is not paused. Current state: %s") % self.state)
        
        self.action_debug_continue()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('FSM Resumed'),
                'message': _('FSM execution resumed.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_next_step_fsm(self):
        """Execute next step in FSM (step-by-step debugging)."""
        self.ensure_one()
        if not self.definition_id:
            raise UserError(_("No FSM definition assigned."))
        
        if self.state != 'paused':
            raise UserError(_("FSM is not paused. Current state: %s") % self.state)
        
        self.action_debug_next_step()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
