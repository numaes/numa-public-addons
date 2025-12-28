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
    
    execution_policy = fields.Selection(
        selection=[('run', 'Normal Run'), ('pause_all', 'Pause All Instances')],
        default='run',
        string='Execution Policy'
    )
    parent_id = fields.Many2one('fsm.definition', 'Parent FSM')
    children_ids = fields.One2many('fsm.definition', 'parent_id', 'Children FSMs')
    pages = fields.Many2many('fsm.wf.page_template', 'wf_page_templates_rel', string='Pages')
    mail_templates = fields.Many2many('fsm.wf.mail_template', 'wf_mail_templates_rel', string='Mail templates')
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
            except (json.JSONDecodeError, TypeError):
                continue

            compiled_nodes = {}
            start_node_id = None
            
            for node in nodes:
                node_id = node.get('id')
                if not node_id: continue
                
                compiled_nodes[node_id] = {
                    'id': node_id,
                    'type': node.get('type'),
                    'label': node.get('label'),
                    'code': node.get('code', ''),
                    'events': node.get('events', []),
                    'outcomes': node.get('outcomes', {}),
                    'is_breakpoint': node.get('is_breakpoint', False),
                }
                if node.get('type') == 'start':
                    start_node_id = node_id

            for conn in connections:
                from_node = compiled_nodes.get(conn.get('fromNodeId'))
                if not from_node: continue
                
                if from_node['type'] in ['start', 'transition']:
                    # Outcomes initialization for safety
                    if 'outcomes' not in from_node:
                        from_node['outcomes'] = {}
                    
                    from_node['outcomes'][conn.get('fromPortName')] = conn.get('toNodeId')
                
                elif from_node['type'] == 'state':
                    # Events initialization for safety
                    if 'events' not in from_node:
                        from_node['events'] = []
                        
                    event = next((e for e in from_node['events'] if e.get('name') == conn.get('fromPortName')), None)
                    if event:
                        event['target_transition_id'] = conn.get('toNodeId')

            compiled_definition = {
                'start_node_id': start_node_id,
                'nodes': compiled_nodes,
                'all_state_events': {},
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
        res = super().write(vals)
        if 'json_ui_schema' in vals:
            self.compile_ui_schema_to_definition()
        return res

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
    def schedule_timers(self):
        """
        Process timers that have reached their trigger time.

        This method is called by a scheduled action to check for timers that have
        reached their trigger time. For each such timer, it sends the associated
        event to the target FSM instance and then deletes the timer.

        The event processing is done asynchronously using the FSM executor thread pool
        to avoid blocking the scheduler.

        Returns:
            None
        """
        now = fields.Datetime.now()

        triggered_timers = self.search([('trigger_at', '<', now)])
        dbname = self.env.cr.dbname
        _context = self.env.context

        for timer in triggered_timers:
            def trigger():
                instance_id = timer.fsm_instance_id.id
                event = json.loads(timer.json_event)
                event['name'] = timer.name

                last_event = timer.fsm_instance_id.events_queue[-1] if timer.fsm_instance_id.events_queue else None

                timer.fsm_instance_id.events_queue = [(0, 0, {
                    'name': event['name'],
                    'json_definition': json.dumps(event),
                    'sequence': last_event.sequence + 1 if last_event else 1,
                })]

                @self.env.cr.postcommit.add
                def trigger_timer():
                    db_registry = Registry(dbname)
                    with db_registry.cursor() as cr:
                        env = api.Environment(cr, SUPERUSER_ID, _context)
                        fsm_instance = env['fsm.instance'].browse(instance_id).exists()
                        fsm_executor.submit(fsm_consume_event, dbname, _context, fsm_instance.id, event)
                        fsm_instance.on_send_event(event)

            trigger()

        if triggered_timers:
            triggered_timers.unlink()


class FSMInstance(models.Model):
    _name = 'fsm.instance'
    _description = 'FSM Instance'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _depend_models = OrderedDict()

    name = fields.Char('Instance ID', default=lambda s: uuid.uuid4(), copy=False)
    definition_id = fields.Many2one('fsm.definition', 'Definition', required=True)
    
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
        self.ensure_one()
        if self.state != 'running' or not self.current_state_id:
            self.log(f"Event '{event.get('name')}' ignored: FSM not in a running state.")
            return

        compiled_def = json.loads(self.definition_id.json_compiled_definition or '{}')
        nodes = compiled_def.get('nodes', {})
        current_state_node = nodes.get(self.current_state_id)
        
        if not current_state_node:
            raise exceptions.UserError(f"Current state '{self.current_state_id}' not found in definition.")

        event_name = event.get('name')
        handler = next((e for e in current_state_node.get('events', []) if e.get('name') == event_name), None)
        
        if not handler:
            self.log(f"Event '{event_name}' has no handler in state '{current_state_node.get('label')}'.")
            return

        target_transition_id = handler.get('target_transition_id')
        if not target_transition_id:
            self.log(f"Event handler for '{event_name}' in state '{current_state_node.get('label')}' has no target transition.")
            return

        intermediate_vars = dict(self.instance_variables or {})
        intermediate_vars['event'] = event
        
        self.write({
            'next_node_id': target_transition_id,
            'intermediate_variables': intermediate_vars,
        })
        
        self._execute_chain()

    def send_event(self, event):
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
