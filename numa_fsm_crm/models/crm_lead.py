# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class CrmLead(models.Model):
    """
    Extension of crm.lead to add FSM capabilities.
    
    Each lead can be converted into a Finite State Machine instance,
    allowing automated workflows and bot-driven lead processing.
    
    Note: When a lead inherits from fsm.instance via numa_poly, the lead
    itself BECOMES the FSM instance. There's no separate fsm_instance_id field.
    """
    _name = 'crm.lead'
    _inherit = ['crm.lead', 'fsm.instance']
    _depend_models = {}

    # Bot assignment field (similar to conversation.session)
    bot_id = fields.Many2one(
        'crm.bot',
        string='CRM Bot',
        tracking=True,
        help="The bot/FSM definition assigned to this lead for automated processing."
    )

    # FSM Definition field (computed from bot_id, but can be set directly)
    definition_id = fields.Many2one(
        'fsm.definition',
        string='FSM Definition',
        compute='_compute_fsm_definition_from_bot',
        store=True,
        readonly=False,
        help="The FSM definition that controls this lead's workflow."
    )

    # Current bot state (computed from FSM instance)
    bot_state = fields.Char(
        string="Bot State",
        compute='_compute_bot_state',
        store=True,
        help="Current state of the bot/FSM workflow."
    )

    # Flag to indicate if lead has active FSM
    has_fsm = fields.Boolean(
        string="Has Active FSM",
        compute='_compute_has_fsm',
        help="True if this lead has an active FSM instance."
    )

    @api.depends('bot_id')
    def _compute_fsm_definition_from_bot(self):
        """Compute definition_id from bot_id."""
        for lead in self:
            if lead.bot_id:
                lead.definition_id = lead.bot_id.fsm_definition_id
            elif not lead.definition_id:
                # Don't clear if manually set
                pass

    @api.depends('current_state_id')
    def _compute_bot_state(self):
        """Compute bot_state from FSM instance current state."""
        for lead in self:
            if lead.current_state_id:
                # Get the state label from the definition
                definition = lead.definition_id
                if definition and definition.json_ui_schema:
                    try:
                        import json
                        schema = definition.json_ui_schema
                        if isinstance(schema, str):
                            schema = json.loads(schema)
                        nodes = schema.get('nodes', [])
                        for node in nodes:
                            if node.get('id') == lead.current_state_id:
                                lead.bot_state = node.get('label', lead.current_state_id)
                                break
                        else:
                            lead.bot_state = lead.current_state_id
                    except Exception as e:
                        _logger.warning(f"Error computing bot_state for lead {lead.id}: {e}")
                        lead.bot_state = lead.current_state_id
                else:
                    lead.bot_state = lead.current_state_id
            else:
                lead.bot_state = False

    @api.depends('state', 'definition_id')
    def _compute_has_fsm(self):
        """Compute if lead has an active FSM instance."""
        for lead in self:
            lead.has_fsm = bool(
                lead.definition_id and 
                lead.state in ['running', 'paused']
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Handle FSM creation when lead is created with bot."""
        leads = super().create(vals_list)
        for lead in leads:
            # If bot is assigned, ensure definition is set
            if lead.bot_id and not lead.definition_id:
                lead.definition_id = lead.bot_id.fsm_definition_id
            
            # Start FSM if definition is set and lead should start automatically
            if lead.definition_id and lead.definition_id.state == 'production':
                # Auto-start FSM for new leads with bots
                try:
                    if lead.state == 'init':
                        lead.start()
                except Exception as e:
                    _logger.warning(f"Failed to auto-start FSM for lead {lead.id}: {e}")
        
        return leads

    def write(self, vals):
        """Handle bot assignment and FSM lifecycle."""
        # Handle bot_id changes
        if 'bot_id' in vals:
            bot = self.env['crm.bot'].browse(vals['bot_id']) if vals['bot_id'] else None
            vals['definition_id'] = bot.fsm_definition_id.id if bot else False
        
        res = super().write(vals)

        # After write, handle FSM lifecycle
        if 'bot_id' in vals or 'definition_id' in vals:
            for lead in self:
                # Start FSM if definition is set and instance is in init state
                if lead.definition_id and lead.state == 'init':
                    try:
                        lead.start()
                    except Exception as e:
                        _logger.warning(f"Failed to start FSM for lead {lead.id}: {e}")
        
        return res

    def action_assign_bot(self):
        """Action to assign a bot to the lead."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assign CRM Bot'),
            'res_model': 'crm.bot',
            'view_mode': 'tree,form',
            'target': 'new',
            'domain': [('state', '=', 'production')],
            'context': {
                'default_lead_id': self.id,
                'select_bot': True,
            },
        }

    def action_start_fsm(self):
        """Manually start the FSM for this lead."""
        self.ensure_one()
        if not self.definition_id:
            raise UserError(_("No FSM definition assigned to this lead. Please assign a bot first."))
        
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
