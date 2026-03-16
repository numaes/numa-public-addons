"""
Finite State Machine (FSM) Module for Odoo
"""
from collections import OrderedDict
import logging
import uuid
from datetime import date, datetime, timedelta
from markupsafe import Markup
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import base64
from jinja2 import Environment
from werkzeug.datastructures import FileStorage
import odoo
from odoo import api, _, exceptions
from odoo.tools.safe_eval import safe_eval, wrap_module
from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.modules.registry import Registry
from odoo.tools.config import config
from . import miniqweb
import pprint

_logger = logging.getLogger(__name__)

DEFAULT_FSM_WORKERS = 2

class FSMDefinition(models.Model):
    _name = 'fsm.definition'
    _description = 'FSM Definition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _depend_models = OrderedDict()

    name = fields.Char('Name', required=True)
    text_definition = fields.Text('Definition (Legacy)')
    json_compiled_definition = fields.Text('JSON Compiled Definition', readonly=True)
    json_ui_schema = fields.Json(string='UI Schema (JSON)')
    website_form_id = fields.Many2one('ir.model', string='Website Form')
    
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('test', 'Test'), ('production', 'Production')],
        default='draft',
        string='State',
        tracking=True
    )
    is_verified = fields.Boolean('Is Verified', default=False, tracking=True)
    
    execution_policy = fields.Selection(
        selection=[('run', 'Normal Run'), ('pause_all', 'Pause All Instances')],
        default='run',
        string='Execution Policy'
    )
    parent_id = fields.Many2one('fsm.definition', 'Parent FSM')
    children_ids = fields.One2many('fsm.definition', 'parent_id', 'Children FSMs')
    pages = fields.Many2many(
        'fsm.wf.page_template', 
        'wf_page_templates_rel', 
        column1='fsm_definition_id', 
        string='Pages'
    )
    mail_templates = fields.Many2many(
        'fsm.wf.mail_template', 
        'wf_mail_templates_rel', 
        column1='fsm_definition_id', 
        string='Mail templates'
    )
    type = fields.Char('Type')

    def compile_ui_schema_to_definition(self):
        for record in self:
            ui_schema = record.json_ui_schema
            if not ui_schema:
                record.json_compiled_definition = '{}'
                continue
            
            try:
                ui_data = ui_schema
                if isinstance(ui_data, str):
                    ui_data = json.loads(ui_data or '{}')
                
                nodes = ui_data.get('nodes', [])
                connections = ui_data.get('connections', [])
            except (json.JSONDecodeError, TypeError) as e:
                continue

            compiled_nodes = {}
            start_node_id = None
            global_state_id = None
            
            for node in nodes:
                node_id = node.get('id')
                if not node_id: continue
                
                # Check if node is a global state (special state with events available in any state)
                is_global = node.get('is_global', False) or node.get('type') == 'global_state'
                
                compiled_nodes[node_id] = {
                    'id': node_id,
                    'type': node.get('type'),
                    'label': node.get('label'),
                    'code': node.get('code', ''),
                    'events': node.get('events', []),
                    'outcomes': node.get('outcomes', {}),
                    'is_breakpoint': node.get('is_breakpoint', False),
                    'is_global': is_global,
                }
                
                if node.get('type') == 'start':
                    start_node_id = node_id
                elif is_global and node.get('type') == 'state':
                    # Store the global state ID (only one allowed per FSM)
                    if global_state_id:
                        _logger.warning("Multiple global states found in FSM definition '%s'. Using first: %s", 
                                      record.name, global_state_id)
                    else:
                        global_state_id = node_id

            for conn in connections:
                from_node = compiled_nodes.get(conn.get('fromNodeId'))
                if not from_node: continue
                
                if from_node['type'] in ['start', 'transition']:
                    if 'outcomes' not in from_node:
                        from_node['outcomes'] = {}
                    from_node['outcomes'][conn.get('fromPortName')] = conn.get('toNodeId')
                
                elif from_node['type'] == 'state':
                    if 'events' not in from_node:
                        from_node['events'] = []
                    event = next((e for e in from_node['events'] if e.get('name') == conn.get('fromPortName')), None)
                    if event:
                        event['target_transition_id'] = conn.get('toNodeId')

            compiled_definition = {
                'start_node_id': start_node_id,
                'nodes': compiled_nodes,
                'all_state_events': {},
                'global_state_id': global_state_id,  # State with events available in any state
            }
            
            record.json_compiled_definition = json.dumps(compiled_definition, indent=2)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.json_ui_schema:
                record.compile_ui_schema_to_definition()
        return records

    def write(self, vals):
        # Reset verification if diagram fields change
        if 'json_ui_schema' in vals or 'json_compiled_definition' in vals or 'text_definition' in vals:
            vals['is_verified'] = False
            
        res = super().write(vals)
        if 'json_ui_schema' in vals:
            self.compile_ui_schema_to_definition()
        return res

    def action_validate(self):
        """
        Integrity check for the FSM diagram.
        Marks the diagram as verified if all nodes (except start/end) have inputs and outputs.
        """
        for record in self:
            ui_data = record.json_ui_schema
            if not ui_data:
                raise exceptions.UserError(_("No hay un diagrama para validar."))
            
            if isinstance(ui_data, str):
                ui_data = json.loads(ui_data)
            
            nodes = ui_data.get('nodes', [])
            conns = ui_data.get('connections', [])
            errors = []

            # Basic logic verification
            has_start = any(n.get('type') == 'start' for n in nodes)
            if not has_start:
                errors.append(_("El diagrama debe tener un nodo de Inicio."))

            for node in nodes:
                node_id = node.get('id')
                node_label = node.get('label', node_id)
                if node.get('type') == 'start':
                    if not any(c.get('fromNodeId') == node_id for c in conns):
                        errors.append(_("El nodo de Inicio debe estar conectado."))
                elif node.get('type') == 'state':
                    if not any(c.get('toNodeId') == node_id for c in conns):
                        errors.append(_("El estado '%s' no tiene entradas.") % node_label)
                    events = node.get('events', [])
                    for evt in events:
                        if not any(c.get('fromNodeId') == node_id and c.get('fromPortName') == evt.get('name') for c in conns):
                            errors.append(_("El evento '%s' del estado '%s' no está conectado.") % (evt.get('name'), node_label))
                elif node.get('type') == 'transition':
                    if not any(c.get('toNodeId') == node_id for c in conns):
                        errors.append(_("La transición '%s' no tiene entradas.") % node_label)
                    outcomes = node.get('outcomes', {})
                    for out in outcomes:
                        if not any(c.get('fromNodeId') == node_id and c.get('fromPortName') == out for c in conns):
                            errors.append(_("El resultado '%s' de la transición '%s' no está conectado.") % (out, node_label))

            if errors:
                raise exceptions.ValidationError("\n".join(errors))
            
            record.is_verified = True
            record.message_post(body=_("Diagrama verificado exitosamente."))

    def action_set_production(self):
        for record in self:
            if not record.is_verified:
                # We log a warning as requested, or we could raise a confirm dialog in a real UI context.
                # For now, following instructions: force production but warn.
                _logger.warning("Pasando a producción un FSM no verificado: %s", record.name)
                record.message_post(body=_("Advertencia: El diagrama se pasó a producción sin verificación previa."), 
                                  message_type='notification')
            record.state = 'production'

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_set_test(self):
        self.write({'state': 'test'})

    def _generate_visual_from_logic(self):
        """
        Generates a basic grid layout for the UI schema if only logical definition exists.
        """
        for record in self:
            if record.json_ui_schema or not record.json_compiled_definition:
                continue
            
            try:
                logic = json.loads(record.json_compiled_definition)
                nodes_logic = logic.get('nodes', {})
                
                ui_nodes = []
                ui_conns = []
                
                x, y = 100, 100
                col_count = 0
                
                # Logic to distribute nodes in a simple grid
                for node_id, node_data in nodes_logic.items():
                    ui_nodes.append({
                        'id': node_id,
                        'type': node_data.get('type', 'state'),
                        'label': node_data.get('label', node_id),
                        'x': x,
                        'y': y,
                        'code': node_data.get('code', ''),
                        'events': node_data.get('events', []),
                        'outcomes': node_data.get('outcomes', {}),
                        'height': 100 if node_data.get('type') == 'start' else (80 if node_data.get('type') == 'end' else 50)
                    })
                    
                    # Basic grid logic
                    x += 250
                    col_count += 1
                    if col_count >= 4:
                        x = 100
                        y += 200
                        col_count = 0

                # Reconstruct connections from outcomes and events
                for node_id, node_data in nodes_logic.items():
                    if node_data.get('type') in ['start', 'transition']:
                        outcomes = node_data.get('outcomes', {})
                        for port, target_id in outcomes.items():
                            if target_id:
                                ui_conns.append({
                                    'id': f'conn_{node_id}_{port}_{target_id}',
                                    'fromNodeId': node_id,
                                    'fromPortName': port,
                                    'toNodeId': target_id
                                })
                    elif node_data.get('type') == 'state':
                        events = node_data.get('events', [])
                        for evt in events:
                            target_id = evt.get('target_transition_id')
                            port = evt.get('name')
                            if target_id:
                                ui_conns.append({
                                    'id': f'conn_{node_id}_{port}_{target_id}',
                                    'fromNodeId': node_id,
                                    'fromPortName': port,
                                    'toNodeId': target_id
                                })

                record.json_ui_schema = {
                    'nodes': ui_nodes,
                    'connections': ui_conns
                }
            except Exception as e:
                _logger.error("Error generating visual layout: %s", str(e))

class WorkFlowMailTemplate(models.Model):
    _name = 'fsm.wf.mail_template'
    _description = 'FSM WorkFlow Mail template'
    _inherit = ['mail.render.mixin']
    name = fields.Char('Name', required=True)
    subject = fields.Char('Subject')
    body_html = fields.Html(string='Body', sanitize=False)
    render_model = fields.Char('Render model', default='fsm.instance')
    attachment_ids = fields.Many2many('ir.attachment', 'wfmt_ir_attachments_rel', 'wfmt_id', 'attachment_id', string='Attachments')
    
    def open_mail_template(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.name, 'view_mode': 'form', 'res_model': self._name, 'res_id': self.id}

class WorkFlowPageTemplate(models.Model):
    _name = 'fsm.wf.page_template'
    _description = 'FSM WorkFlow Page template'
    _inherit = ['mail.render.mixin']
    name = fields.Char('Name', required=True)
    body = fields.Html('Body', sanitize=False)
    
    def open_page_template(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": f'/fsm_page_template/{self.id}', "target": "new"}

class FSMFormInput(models.TransientModel):
    _name = 'fsm.form_input'
    _description = 'FSM Form input'
    # ... (code remains unchanged)

fsm_executor = ThreadPoolExecutor(max_workers=DEFAULT_FSM_WORKERS)
background_service_executor = ThreadPoolExecutor(max_workers=DEFAULT_FSM_WORKERS)

class FSMTimer(models.Model):
    """
     Timer Model for FSM Workflows

     This model stores timer-based events that need to be triggered at specific times
     for FSM instances. Timers are used to implement delayed actions, timeouts, and
     scheduled events within FSM workflows.

     Timers are processed by a scheduled action that checks for timers that have
     reached their trigger time and sends the associated events to the target
     FSM instances.
     """
    _name = 'fsm.timer'
    _description = 'FSM Timer'
    _order = 'trigger_at desc'
    _rec_name = 'name'

    name = fields.Char('Event name', required=True)
    json_event = fields.Text('JSON Event')

    fsm_instance_id = fields.Many2one('fsm.instance', 'Target FSM instance')
    trigger_at = fields.Datetime('Trigger at')
    database_name = fields.Char('Database name')

    @api.model
    def _process_timers(self):
        """
        Process timers that have reached their trigger time.
        
        This method processes all timers that have reached their trigger time,
        sends the associated events to the target FSM instances, and then
        deletes the processed timers. After processing, it auto-schedules the
        next execution in 1 second using numa_asynch_exec with retry_count = -1
        (infinite retries for continuous execution).
        
        This method is designed to be called continuously via numa_asynch_exec
        with retry_count = -1 and retry_delay = 1000 (1 second).
        
        Returns:
            None
        """
        now = fields.Datetime.now()
        triggered_timers = self.search([('trigger_at', '<=', now)])
        
        for timer in triggered_timers:
            fsm_instance = timer.fsm_instance_id
            if not fsm_instance.exists():
                # Skip if instance no longer exists
                continue
            
            try:
                # Parse event from JSON
                event_data = json.loads(timer.json_event) if timer.json_event else {}
                event_data['name'] = timer.name
                
                # Send event to FSM instance (will be processed asynchronously via process_event)
                fsm_instance.send_event(event_data)
                
            except Exception as e:
                _logger.error("Error processing timer %s for FSM instance %s: %s", 
                            timer.name, fsm_instance.id, e)
                # Continue with other timers even if one fails
        
        # Delete processed timers
        if triggered_timers:
            triggered_timers.unlink()
        
        # Auto-schedule next execution in 1 second using infinite retries
        # This ensures the timer processor runs continuously
        # Use self.env to get the model recordset for asynch_exec
        self.env['fsm.timer'].asynch_exec(retry=-1, retry_delay=1000)._process_timers()

    @api.model
    def schedule_timers(self):
        """
        Legacy method kept for backward compatibility with cron.
        
        This method is deprecated in favor of _process_timers() which uses
        numa_asynch_exec for continuous execution. This method now simply
        calls _process_timers() for compatibility with existing cron jobs.
        
        Note: The cron should be disabled once _schedule_timer_task() is
        initialized via post_init_hook.
        
        Returns:
            None
        """
        self._process_timers()

    @api.model
    def _schedule_timer_task(self):
        """
        Initialize the continuous timer processing task.
        
        This method should be called from post_init_hook to start the
        timer processing task that runs continuously with retry_count = -1.
        It checks if there's already a pending job running to avoid duplicates.
        
        Returns:
            None
        """
        # Check if there's already a pending/running job for timer processing
        existing_jobs = self.env['numa.asynch.job'].search([
            ('model_name', '=', 'fsm.timer'),
            ('method_name', '=', '_process_timers'),
            ('state', 'in', ['pending', 'running']),
        ])
        
        if not existing_jobs:
            # Start the continuous timer processing task
            _logger.info("Initializing FSM timer processing task with infinite retries")
            self.asynch_exec(retry=-1, retry_delay=1000)._process_timers()
        else:
            _logger.debug("FSM timer processing task already running (found %d existing jobs)", 
                         len(existing_jobs))


class FSMInstance(models.Model):
    _name = 'fsm.instance'
    _description = 'FSM Instance'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _depend_models = OrderedDict()

    name = fields.Char('Instance ID', default=lambda s: uuid.uuid4(), copy=False)
    definition_id = fields.Many2one('fsm.definition', 'Definition')
    
    state = fields.Selection(
        [('init', 'Not Started'), ('running', 'Running'), ('paused', 'Paused'), ('ended', 'Ended'), ('error', 'Error')],
        string='Execution State', required=True, default='init', copy=False, tracking=True
    )
    current_state_id = fields.Char('Current State Node ID', copy=False, readonly=True, help="ID of the state node where the FSM is currently waiting.")
    next_node_id = fields.Char('Next Node to Execute', copy=False, readonly=True, help="ID of the next transition to execute when resuming.")
    
    instance_variables = fields.Json('Instance Variables', default={}, readonly=True)
    intermediate_variables = fields.Json('Intermediate Variables (Debug)', copy=False, readonly=True)

    debug_mode = fields.Selection(
        selection=[('off', 'Off'), ('step_by_step', 'Step-by-Step')],
        string='Debug Mode', default='off', tracking=True
    )
    is_simulation = fields.Boolean(string='Is Simulation', default=False, readonly=True)
    json_ui_schema = fields.Json(related='definition_id.json_ui_schema', readonly=True)

    def log(self, message):
        self.ensure_one()
        self.message_post(body=Markup(f"<pre>{message}</pre>"))

    def start(self):
        self.ensure_one()
        if self.state != 'init':
            raise exceptions.UserError("Only instances in 'Not Started' state can be started.")
        
        compiled_def = json.loads(self.definition_id.json_compiled_definition or '{}')
        start_node_id = compiled_def.get('start_node_id')
        
        if not start_node_id:
            raise exceptions.UserError("Cannot start FSM: No 'start' node defined in the diagram.")
            
        self.write({
            'state': 'running',
            'next_node_id': start_node_id,
            'instance_variables': {},
            'intermediate_variables': {},
        })
        
        self.action_debug_continue()

    def action_debug_next_step(self):
        self.ensure_one()
        if self.state not in ['paused', 'running'] or not self.next_node_id:
            return
        self.with_context(fsm_single_step=True)._execute_chain()

    def action_debug_continue(self):
        self.ensure_one()
        if self.state not in ['paused', 'running'] or not self.next_node_id:
            return
        self.with_context(fsm_single_step=False)._execute_chain()

    def _execute_chain(self):
        self.ensure_one()
        try:
            compiled_def = json.loads(self.definition_id.json_compiled_definition or '{}')
            nodes = compiled_def.get('nodes', {})
            intermediate_vars = dict(self.intermediate_variables or self.instance_variables or {})
            current_node_id = self.next_node_id
            
            while current_node_id:
                node = nodes.get(current_node_id)
                if not node:
                    raise exceptions.UserError(f"Node '{current_node_id}' not found in compiled definition.")

                if node['type'] in ['start', 'transition']:
                    self.log(f"Executing transition: {node.get('label', node_id)}")
                    global_objects = self._get_execution_globals(intermediate_vars)
                    exec(node.get('code', ''), global_objects, intermediate_vars)
                    
                    outcome = intermediate_vars.get('outcome', '__default__')
                    next_node_id = node.get('outcomes', {}).get(outcome)
                    
                    if not next_node_id:
                        raise exceptions.UserError(f"Outcome '{outcome}' from transition '{node_id}' does not lead anywhere.")
                    
                    current_node_id = next_node_id
                    
                    next_node_def = nodes.get(current_node_id)
                    is_breakpoint = next_node_def and next_node_def.get('is_breakpoint', False)
                    is_single_step = self.env.context.get('fsm_single_step') or self.debug_mode == 'step_by_step'

                    if is_breakpoint or is_single_step:
                        self.write({
                            'state': 'paused',
                            'intermediate_variables': intermediate_vars,
                            'next_node_id': current_node_id,
                        })
                        self.log(f"Execution paused. Next up: {nodes.get(current_node_id, {}).get('label', current_node_id)}")
                        return

                elif node['type'] == 'state':
                    self.log(f"Reached state: {node.get('label', node_id)}")
                    self.write({
                        'state': 'running',
                        'current_state_id': node_id,
                        'instance_variables': intermediate_vars,
                        'intermediate_variables': {},
                        'next_node_id': False,
                    })
                    return

                elif node['type'] == 'end':
                    self.log(f"Reached end: {node.get('label', node_id)}")
                    self.write({
                        'state': 'ended',
                        'current_state_id': node_id,
                        'instance_variables': intermediate_vars,
                        'intermediate_variables': {},
                        'next_node_id': False,
                    })
                    return
                
                else:
                    raise exceptions.UserError(f"Unknown node type '{node['type']}' for node '{node_id}'.")

        except Exception as e:
            _logger.exception("FSM Execution Error", exc_info=True)
            self.log(f"ERROR: {e}")
            self.write({'state': 'error', 'intermediate_variables': {}})

    def _get_execution_globals(self, variables):
        self.ensure_one()
        def set_outcome(name):
            variables['outcome'] = name
        def log_message(message):
            self.log(message)
        return {
            'variables': variables,
            'set_outcome': set_outcome,
            'log': log_message,
            'env': self.env,
            'model': self,
            'datetime': odoo.fields.datetime,
            'date': odoo.fields.date,
            'timedelta': timedelta,
            'user': self.env.user,
            'company': self.env.company,
        }

    def process_event(self, event):
        """
        Queue an event for asynchronous processing using numa_asynch_exec.
        
        This method schedules the event processing to run asynchronously,
        ensuring persistence and retry capability. The actual processing
        is done by _process_event_sync().
        
        :param event: Dictionary containing event data with at least a 'name' key
        """
        for fsm_instance in self:
            # Use asynch_exec to process the event asynchronously
            fsm_instance.asynch_exec()._process_event_sync(event)

    def _process_event_sync(self, event):
        """
        Synchronous event processing logic.
        
        This method contains the actual event processing logic that was
        previously in process_event(). It is called asynchronously via
        numa_asynch_exec to ensure persistence and error handling.
        
        :param event: Dictionary containing event data with at least a 'name' key
        """
        self.ensure_one()
        if self.state != 'running' or not self.current_state_id:
            self.log(f"Event '{event.get('name')}' ignored: FSM not in a running state.")
            return

        compiled_def = json.loads(self.definition_id.json_compiled_definition or '{}')
        nodes = compiled_def.get('nodes', {})
        current_state_node = nodes.get(self.current_state_id)
        global_state_id = compiled_def.get('global_state_id')
        
        if not current_state_node:
            raise exceptions.UserError(f"Current state '{self.current_state_id}' not found in definition.")

        event_name = event.get('name')
        
        # Priority 1: Look for handler in current state
        handler = next((e for e in current_state_node.get('events', []) if e.get('name') == event_name), None)
        handler_source = 'current_state'
        
        # Priority 2: If no handler in current state, check global state
        if not handler and global_state_id:
            global_state_node = nodes.get(global_state_id)
            if global_state_node:
                handler = next((e for e in global_state_node.get('events', []) if e.get('name') == event_name), None)
                if handler:
                    handler_source = 'global_state'
        
        if not handler:
            handler_info = f"state '{current_state_node.get('label')}'"
            if global_state_id:
                handler_info += f" or global state"
            self.log(f"Event '{event_name}' has no handler in {handler_info}.")
            return

        target_transition_id = handler.get('target_transition_id')
        if not target_transition_id:
            handler_label = current_state_node.get('label') if handler_source == 'current_state' else nodes.get(global_state_id, {}).get('label')
            self.log(f"Event handler for '{event_name}' in {handler_source} '{handler_label}' has no target transition.")
            return

        intermediate_vars = dict(self.instance_variables or {})
        intermediate_vars['event'] = event
        
        self.write({
            'next_node_id': target_transition_id,
            'intermediate_variables': intermediate_vars,
        })
        
        self._execute_chain()

    def send_event(self, event):
        """
        Send an event to one or more FSM instances.
        
        Events are processed asynchronously via numa_asynch_exec.
        
        :param event: Dictionary containing event data with at least a 'name' key
        """
        for fsm_instance in self:
            fsm_instance.process_event(event)

    # --- Existing Methods (Preserved) ---
    @api.model
    def _cron_cleanup_simulations(self, batch_size=500):
        now = fields.Datetime.now()
        threshold = now - timedelta(hours=24)
        domain = [('is_simulation', '=', True), ('create_date', '<', threshold)]
        Instance = self.sudo().with_context(active_test=False)
        while True:
            sims = Instance.search(domain, limit=batch_size)
            if not sims:
                break
            try:
                sims.unlink()
            except Exception as e:
                _logger.warning('Error cleaning up simulation instances: %s', e)
                break

    def set_page(self, page_name):
        self.ensure_one()
        current_page = self.definition_id.pages.filtered(lambda s: s.name == page_name)
        if len(current_page) >= 1:
            self.current_page = current_page[0]
        else:
            raise exceptions.UserError(_('Page %s not found!') % page_name)

    def end(self):
        self.write({'state': 'ended'})
    
    def start_timer(self, event, delay=None, at=None):
        timer_model = self.env['fsm.timer']
        if not at:
            at = fields.Datetime.now() + (timedelta(seconds=delay) if delay else timedelta(seconds=0))
        for fsm_instance in self:
            self.log(f"Starting timer with event {event} for: {delay} seconds, trigger at: {at}")
            timer_model.create(dict(name=event['name'], json_event=json.dumps(event), fsm_instance_id=self.id, trigger_at=at, database_name=self.env.cr.dbname,))

    def stop_timer(self, event_name):
        timer_model = self.env['fsm.timer']
        timers = timer_model.search([('name', '=', event_name), ('fsm_instance_id', '=', self.id)])
        if timers:
            timers.unlink()
        for fsm_instance in self:
            self.log(f"Stopping timer {event_name}")

    def stop_all_timers(self):
        timer_model = self.env['fsm.timer']
        self.ensure_one()
        timers = timer_model.search([('fsm_instance_id', '=', self.id)])
        if timers:
            timers.unlink()
        for fsm_instance in self:
            self.log(f"Stopping all timers")

    def render_dynamic_html(self, template, **params):
        templater = Environment(variable_start_string="{{", variable_end_string="}}",)
        global_objects = self._get_execution_globals(params)
        fsm_instance = global_objects['model']
        processed_body = template
        while "{{" in processed_body:
            jinja_template = templater.from_string(processed_body)
            processed_body = jinja_template.render(instance=fsm_instance, **params)
        return miniqweb.render(processed_body, **dict(instance=fsm_instance, **params))

    def render_page(self, page_name, **params):
        self.ensure_one()
        page = self.definition_id.pages.filtered(lambda s: s.name == page_name)
        if not page:
            raise exceptions.UserError(_('Page %s not found for definition %s') % (page_name, self.definition_id.name))
        return self.render_dynamic_html(page[0].body_html, **params)

    def action_send_template_mail(self, target_object, mail_template_name, subject=None):
        self.ensure_one()
        mail_template = self.definition_id.mail_templates.filtered(lambda s: s.name == mail_template_name)
        if not mail_template:
            raise exceptions.UserError(_('Mail template %s not found for definition %s') % (mail_template_name, self.definition_id.name))
        
        concrete_body = self.render_dynamic_html(mail_template.body_html)
        concrete_subject = self.render_dynamic_html(subject or mail_template.subject or _('Workflow message'))
        
        target_object.message_notify(
            subject=concrete_subject,
            body=Markup(concrete_body),
            attachment_ids=mail_template.attachment_ids.ids,
            partner_ids=[self.partner_id.id] if hasattr(self, 'partner_id') and self.partner_id else False,
        )
