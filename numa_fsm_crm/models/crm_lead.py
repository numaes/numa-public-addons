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
    
    El lead NO es la instancia: la tiene. Hasta Odoo 18 heredaba ``fsm.instance``
    con ``_inherit``, y el lead pasaba a ser la instancia sin campo aparte. Eso
    dejó de linealizar en Odoo 20: ``fsm.instance`` hereda ``mail.thread`` y
    ``mail.activity.mixin``, que ``crm.lead`` ya hereda por su cuenta, y C3 pide
    que lo más derivado vaya primero mientras la construcción de bases las deja
    antes. En 18.0 no se notaba porque numa_poly rearmaba ``__bases__`` a mano y
    de paso deshacía el conflicto; desde que las bases se declaran, el orden lo
    calcula Odoo y el choque sale a la luz.

    El vínculo explícito dice lo mismo sin pelearse con el MRO, y además separa
    dos ciclos de vida que nunca fueron uno: un lead puede existir sin workflow,
    y su instancia puede reiniciarse sin tocar el lead.
    """
    _name = 'crm.lead'
    _inherit = ['crm.lead']

    fsm_instance_id = fields.Many2one(
        'fsm.instance',
        string='FSM Instance',
        copy=False,
        ondelete='set null',
        help="The FSM instance that runs this lead's workflow, created when a definition "
             "is assigned.",
    )

    # Lo que el formulario y los filtros leían del lead cuando era la instancia.
    # Siguen llamándose igual, así que las vistas no cambian.
    fsm_state = fields.Selection(
        related='fsm_instance_id.fsm_state', string='Execution State', readonly=True)
    current_state_id = fields.Char(
        related='fsm_instance_id.current_state_id', string='Current State Node ID', readonly=True)
    instance_variables = fields.Json(
        related='fsm_instance_id.instance_variables', string='Instance Variables', readonly=True)
    debug_mode = fields.Selection(
        related='fsm_instance_id.debug_mode', string='Debug Mode', readonly=False)
    next_node_id = fields.Char(
        related='fsm_instance_id.next_node_id', string='Next Node to Execute', readonly=True)
    # El diagrama se puede dibujar aunque todavía no haya instancia, así que
    # sale de la definición y no del vínculo.
    json_ui_schema = fields.Json(
        related='definition_id.json_ui_schema', string='UI Schema (JSON)', readonly=True)

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
        search='_search_has_fsm',
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

    @api.depends('fsm_instance_id.current_state_id')
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

    @api.depends('fsm_instance_id.fsm_state', 'definition_id')
    def _compute_has_fsm(self):
        """Compute if lead has an active FSM instance."""
        for lead in self:
            lead.has_fsm = bool(
                lead.definition_id and 
                lead.fsm_state in ['running', 'paused']
            )

    def _search_has_fsm(self, operator, value):
        """Make ``has_fsm`` searchable.

        The "With Active FSM" search filter uses it; a computed field without ``search`` makes the
        whole search view invalid, including the standard views that inherit from it.
        """
        if operator not in ('=', '!='):
            raise UserError(_('Unsupported operator for has_fsm: %s') % operator)
        # El dominio negativo es la negación literal del positivo, no su espejo
        # escrito a mano: un lead con definición pero todavía sin instancia tiene
        # ``fsm_state`` vacío, y un ``not in`` sobre la travesía no lo alcanzaría.
        activo = ['&', ('definition_id', '!=', False),
                  ('fsm_instance_id.fsm_state', 'in', ['running', 'paused'])]
        if (operator == '=') == bool(value):
            return activo
        return ['!'] + activo

    def _ensure_fsm_instance(self):
        """Devolver la instancia de este lead, creándola si todavía no tiene.

        Cuando el lead ERA la instancia esto no hacía falta. Ahora es el único
        lugar donde se crea, para que el resto del módulo no tenga que saber si
        ya existía.
        """
        self.ensure_one()
        if not self.fsm_instance_id:
            if not self.definition_id:
                raise UserError(_("No FSM definition assigned to this lead."))
            self.fsm_instance_id = self.env['fsm.instance'].create({
                'definition_id': self.definition_id.id,
            })
        return self.fsm_instance_id

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
                    if lead.fsm_state in (False, 'init'):
                        lead._ensure_fsm_instance().start()
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
                if lead.definition_id and lead.fsm_state in (False, 'init'):
                    try:
                        lead._ensure_fsm_instance().start()
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
            'view_mode': 'list,form',
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
        
        if self.fsm_state not in (False, 'init'):
            raise UserError(_("FSM is already running or has ended. Current state: %s") % self.fsm_state)
        
        try:
            self._ensure_fsm_instance().start()
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
        
        if self.fsm_state != 'running':
            raise UserError(_("FSM is not running. Current state: %s") % self.fsm_state)
        
        # Set debug mode to pause on next breakpoint
        self.fsm_instance_id.debug_mode = 'step_by_step'
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
        
        if self.fsm_state != 'paused':
            raise UserError(_("FSM is not paused. Current state: %s") % self.fsm_state)
        
        self.fsm_instance_id.action_debug_continue()
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
        
        if self.fsm_state != 'paused':
            raise UserError(_("FSM is not paused. Current state: %s") % self.fsm_state)
        
        self.fsm_instance_id.action_debug_next_step()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
