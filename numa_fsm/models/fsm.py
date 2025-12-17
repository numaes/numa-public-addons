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

def compile_definition(source):
    """
    Compile an FSM definition from source text into a structured representation.
    Supports @outcome directive for mapping logical results to target states.
    """
    def tokenize(meta_line):
        tokens = []
        token = ''
        for c in meta_line:
            if c in [' ', '\n']:
                if token:
                    tokens.append(token)
                token = ''
            elif c != ' ':
                token += c
        if token:
            tokens.append(token)
        return tokens

    def is_meta(raw_line):
        if len(raw_line) > 0 and raw_line[0] == '@':
            return True
        return False

    body = []

    def get_unindented_body():
        indentation = 0
        indentation_found = False
        for line in body:
            for c in line:
                if c in [' ']:
                    indentation += 1
                elif c in ['\n', '#']:
                    indentation = 0
                    break
                else:
                    indentation_found = True
                    break
            if indentation_found:
                break

        if indentation > 0:
            unindented_code = []
            for line in body:
                all_spaces = True
                cleaned_line = ''
                first_char_position = -1
                position = -1
                for c in line:
                    position += 1
                    if c == '#':
                        break
                    elif c != ' ':
                        all_spaces = False
                        if first_char_position < 0:
                            first_char_position = position
                        cleaned_line += c
                if not all_spaces and first_char_position < indentation:
                    raise exceptions.UserError('Line indentation is not following the first line')
                if len(line) > indentation:
                    unindented_code.append(line[indentation:])
                else:
                    unindented_code.append('')
            code_definition = '\n'.join(unindented_code)
        else:
            code_definition = '\n'.join(body)
        return code_definition

    start_body = None
    current_states = None
    current_events = None
    pospone = False
    extended_fsmd = False
    states = {}
    line_number = 0
    state = 'outer_level'
    
    # Temporary storage for outcomes of the current event being parsed
    current_outcomes = {} 

    for line in (source or '').split('\n'):
        line_number += 1
        cleaned_line = line.lstrip() + '\n'

        if state == 'collecting_start_body':
            if is_meta(cleaned_line):
                start_body = get_unindented_body()
                state = 'outer_level'
            else:
                body.append(line)

        if state == 'collecting_event_body':
            if is_meta(cleaned_line):
                # Check for @outcome directive inside event body
                if cleaned_line.startswith('@outcome'):
                    # Syntax: @outcome name -> target_state
                    parts = cleaned_line.split('->')
                    if len(parts) != 2:
                         raise exceptions.UserError(_('Invalid outcome syntax in line %d. Use: @outcome name -> state') % line_number)
                    
                    outcome_name = parts[0].replace('@outcome', '').strip()
                    target_state = parts[1].strip()
                    current_outcomes[outcome_name] = target_state
                    # Do not change state, continue collecting body or other outcomes
                else:
                    # End of event body, save it
                    event_body = get_unindented_body()
                    for event in current_events:
                        for cstate in current_states:
                            states[cstate][event]['code'] = event_body
                            states[cstate][event]['pospone'] = pospone
                            states[cstate][event]['outcomes'] = current_outcomes.copy()
                    
                    # Reset for next block
                    current_outcomes = {}
                    
                    # Process the meta line that ended the block
                    if cleaned_line.startswith('@event'):
                        # ... (same logic as below) ...
                        tokenized_line = tokenize(cleaned_line)
                        if len(tokenized_line) < 2:
                            raise exceptions.UserError(_('No event name defined in line %d') % line_number)
                        current_events = [e.strip() for e in tokenized_line[1].split(',')]
                        for cstate in current_states:
                            for event in current_events:
                                states[cstate][event] = {}
                        pospone = False
                        if len(tokenized_line) >= 3:
                            if tokenized_line[2] == 'pospone':
                                pospone = True
                        body = []
                        state = 'collecting_event_body'
                    elif cleaned_line.startswith('@state'):
                        state = 'states_definition'
                        # Re-process this line in the new state context? 
                        # Easier to just duplicate the logic or use a 'reprocess' flag, 
                        # but here we just jump to state_definition logic
                        tokenized_line = tokenize(cleaned_line)
                        if len(tokenized_line) < 2:
                            raise exceptions.UserError(_('No state name defined in line %d') % line_number)
                        current_states = [s.strip() for s in tokenized_line[1].split(',')]
                        for state_name in current_states:
                            states[state_name] = {}
                        body = []
                        state = 'state_definition'
                    else:
                        state = 'state_definition' # Fallback
            else:
                body.append(line)

        if state == 'state_definition':
            if is_meta(cleaned_line):
                if cleaned_line.startswith('@event'):
                    tokenized_line = tokenize(cleaned_line)
                    if len(tokenized_line) < 2:
                        raise exceptions.UserError(_('No event name defined in line %d') % line_number)
                    current_events = [e.strip() for e in tokenized_line[1].split(',')]
                    for cstate in current_states:
                        for event in current_events:
                            states[cstate][event] = {}
                    pospone = False
                    if len(tokenized_line) >= 3:
                        if tokenized_line[2] == 'pospone':
                            pospone = True
                    body = []
                    current_outcomes = {} # Reset outcomes
                    state = 'collecting_event_body'
                else:
                    state = 'states_definition'

        if state == 'states_definition':
            if is_meta(cleaned_line):
                if cleaned_line.startswith('@state'):
                    tokenized_line = tokenize(cleaned_line)
                    if len(tokenized_line) < 2:
                        raise exceptions.UserError(_('No state name defined in line %d') % line_number)
                    current_states = [s.strip() for s in tokenized_line[1].split(',')]
                    for state_name in current_states:
                        states[state_name] = {}
                    body = []
                    state = 'state_definition'
                else:
                    state = 'outer_level'

        if state == 'outer_level':
            if is_meta(cleaned_line):
                if cleaned_line.startswith('@start'):
                    body = []
                    state = 'collecting_start_body'
                elif cleaned_line.startswith('@states'):
                    state = 'states_definition'
                elif cleaned_line.startswith('@extends'):
                    tokenized_line = tokenize(cleaned_line)
                    if len(tokenized_line) < 2:
                        raise exceptions.UserError(_('No extended FSM name in line %d') % line_number)
                    extended_fsmd = tokenized_line[1]
                else:
                    # Ignore unknown meta lines at outer level or raise error
                    pass
            else:
                body.append(line)

    # Handle end of file
    if state == 'collecting_start_body':
        start_body = get_unindented_body()
    elif state == 'collecting_event_body':
        event_body = get_unindented_body()
        for event in current_events:
            for cstate in current_states:
                states[cstate][event]['code'] = event_body
                states[cstate][event]['pospone'] = pospone
                states[cstate][event]['outcomes'] = current_outcomes.copy()

    return dict(
        start_code=start_body,
        states=states,
        extends=extended_fsmd,
    )


class FSMDefinition(models.Model):
    _name = 'fsm.definition'
    _description = 'FSM Definition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _depend_models = OrderedDict()

    name = fields.Char('Name', required=True)
    text_definition = fields.Text('Definition')
    json_compiled_definition = fields.Text('JSON Compiled definition')
    json_ui_schema = fields.Text(string='UI Schema (JSON)')
    json_logic_schema = fields.Text(string='Logic Schema (JSON)')
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

    @api.onchange('text_definition')
    def onchange_text_definition(self):
        for fsm in self:
            cd = compile_definition(fsm.text_definition)
            fsm.json_compiled_definition = json.dumps(cd)
            if cd['extends']:
                extended_fsmd = self.search([('name', '=', cd['extends'])], limit=1)
                if extended_fsmd:
                    fsm.parent_id = extended_fsmd
                else:
                    raise exceptions.UserError(_('Extended FSM %s not found!') % cd['extends'])
            for child in fsm.children_ids:
                child.onchange_text_definition()

# ... (WorkFlowMailTemplate, WorkFlowPageTemplate, FSMFormInput classes remain unchanged) ...
class WorkFlowMailTemplate(models.Model):
    _name = 'fsm.wf.mail_template'
    _description = 'FSM WorkFlow Mail template'
    _inherit = ['mail.render.mixin']
    @api.model
    def default_body_view_id(self):
        view_model = self.env['ir.ui.view']
        return view_model.create(dict(
                type='qweb',
                name='Mail Template - ' + str(uuid.uuid4()),
                arch='<template>\n</template>',
        ))
    name = fields.Char('Name', required=True)
    subject = fields.Char('Subject')
    body_html = fields.Html(string='Body converted to be sent by mail', sanitize='email_outgoing', render_engine='qweb', render_options={'post_process': True})
    is_body_empty = fields.Boolean(compute="_compute_is_body_empty")
    render_model = fields.Char('Render model', default='fsm.instance')
    attachment_ids = fields.Many2many('ir.attachment', 'wfmt_ir_attachments_rel', 'wfmt_id', 'attachment_id', string='Attachments')
    def open_mail_template(self):
        self.ensure_one()
        compose_form = self.env.ref('numa_fsm.mail_template_html_edit')
        return {'type': 'ir.actions.act_window', 'name': self.name, 'view_mode': 'form', 'res_model': 'fsm.wf.mail_template', 'views': [(compose_form.id, 'form')], 'view_id': compose_form.id, 'res_id': self.id}

class WorkFlowPageTemplate(models.Model):
    _name = 'fsm.wf.page_template'
    _description = 'FSM WorkFlow Page template'
    _inherit = ['mail.render.mixin']
    name = fields.Char('Name', required=True)
    body = fields.Html('Body', sanitize=False)
    def plain_body(self, target_object, vals=None):
        self.ensure_one()
        context = dict(vals or {}, object=target_object)
        return self.body_view_id._render(context)
    def open_page_template(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": '/fsm_page_template/%d' % self.id, "target": "new"}

class FSMFormInput(models.TransientModel):
    _name = 'fsm.form_input'
    _description = 'FSM Form input'
    website_form_access = fields.Boolean('Allowed to use in forms')
    instance_id = fields.Many2one('fsm.instance', 'Target instance')
    unrelated_identifier = fields.Char('Unrelated identifier')
    json_data = fields.Char('JSON Data')
    json_files = fields.Char('JSON Files')
    @api.model_create_multi
    def create(self, vals_list):
        fsm_instance_model = self.env['fsm.instance']
        attachment_model = self.env['ir.attachment']
        result = self.env['fsm.form_input']
        for vals in vals_list:
            plain_vals = {}
            for name, content in vals.items():
                if not isinstance(content, FileStorage):
                    plain_vals[name] = content
            instance_name = vals.get('instance_id', False)
            if instance_name:
                instance = fsm_instance_model.search([('name', '=', instance_name)], limit=1)
            else:
                instance = False
            json_data = json.dumps(plain_vals)
            new_record = super().create(dict(instance_id=instance.id if instance else False, unrelated_identifier=vals['unrelated_identifier'], json_data=json_data))
            file_vals = {}
            for name, content in vals.items():
                if isinstance(content, FileStorage):
                    field_name = name.split('[', 1)[0]
                    attachment = attachment_model.create({'name': content.filename, 'res_model': self._name, 'res_id': new_record.id, 'type': 'binary', 'datas': base64.b64encode(content.read()), 'description': content.filename})
                    file_vals[field_name] = attachment.id
            new_record.json_files = json.dumps(file_vals)
            result |= new_record
        return result
    def get_file(self, name: str):
        attachment_model = self.env['ir.attachment']
        self.ensure_one()
        if self.json_files:
            files = json.loads(self.json_files)
            if name in files:
                attachment_id = files[name]
                attachment = attachment_model.browse(attachment_id).exists()
                if attachment:
                    return attachment.datas
        return None
    def move_file(self, instance, name: str, field_name):
        attachment_model = self.env['ir.attachment']
        self.ensure_one()
        if self.json_files:
            files = json.loads(self.json_files)
            if name in files:
                attachment_id = files[name]
                attachment = attachment_model.browse(attachment_id).exists()
                if attachment:
                    if not instance.fields_get([field_name]):
                        raise exceptions.UserError(_('Field %s does not exists in model %s') % (field_name, instance._name))
                    attachment.res_model = instance._name
                    attachment.res_id = instance.id
                    attachment.res_field = field_name
                    instance[field_name + '_filename'] = attachment.name
    def debug_hook(self):
        _logger.info('Debug hook')

fsm_workers_config = config.get('fsm_workers')
if not fsm_workers_config:
    fsm_workers = DEFAULT_FSM_WORKERS
else:
    fsm_workers = int(fsm_workers_config)
fsm_executor = ThreadPoolExecutor(max_workers=fsm_workers)
fsm_service_workers_config = config.get('fsm_service_workers')
if not fsm_service_workers_config:
    fsm_service_workers = DEFAULT_FSM_WORKERS
else:
    fsm_service_workers = int(fsm_workers_config)
background_service_executor = ThreadPoolExecutor(max_workers=fsm_service_workers)

def fsm_consume_event(db_name: str, _context: dict, instance_id: int, event: dict):
    instance = None
    db = odoo.sql_db.db_connect(db_name)
    threading.current_thread().dbname = db_name
    with db.cursor() as cr:
        try:
            env = api.Environment(cr, SUPERUSER_ID, _context)
            instance = env['fsm.instance'].browse(instance_id).exists()
            if instance:
                instance_env = instance.prepare_env()
                instance.process_event(event, instance_env)
        except Exception as e:
            _logger.exception('Exception in FSM instance %s:' % (instance.display_name if instance else 'N/A'), exc_info=True, stack_info=True)
            cr.rollback()
            instance.message_post(subject=f"Exception processing event", body=Markup(f"<i>On event {event.get('name', 'N/D')} for instance {instance.display_name} unexpected exception <pre>{pprint.pformat(e)}</pre></i>"))
        finally:
            if hasattr(threading.current_thread(), 'dbname'):
                del threading.current_thread().dbname

class FSMTimer(models.Model):
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
                timer.fsm_instance_id.events_queue = [(0, 0, {'name': event['name'], 'json_definition': json.dumps(event), 'sequence': last_event.sequence + 1 if last_event else 1,})]
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

    current_page = fields.Many2one('fsm.wf.page_template', 'Current page')
    name = fields.Char('Instance ID', default=lambda s: uuid.uuid4())
    definition_id = fields.Many2one('fsm.definition', 'Definition', required=True)
    type = fields.Char(string='Type', related='definition_id.type', readonly=True)
    current_state = fields.Char('Current state', copy=False)
    json_instance_values = fields.Text('JSON Instance Values')
    state = fields.Selection([('init', 'For Init'), ('running', 'Running'), ('stopped', 'Stopped'), ('ended', 'Ended')], string='State', required=True, default='init', copy=False)
    logging = fields.Boolean('Logging?')
    debug_mode = fields.Selection(selection=[('off', 'Off'), ('trace', 'Trace Only'), ('step', 'Step-by-Step / Pause')], string='Debug Mode', default='off', tracking=True)
    execution_log_ids = fields.One2many('fsm.execution.log', 'instance_id', string='Execution Logs')
    pending_debug_event_ids = fields.One2many('fsm.debug.event', 'instance_id', string='Pending Debug Events', domain=[('state', '=', 'pending')])
    is_simulation = fields.Boolean(string='Is Simulation', default=False, readonly=True, help='Marks this instance as a simulation clone created by a replay operation.')

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

    def prepare_env(self):
        self.ensure_one()
        env = json.loads(self.json_instance_values or '{}')
        return env or {}

    def flush_env(self, env):
        self.ensure_one()
        env2store = {}
        if env:
            for name, value in env.items():
                if not isinstance(value, models.BaseModel):
                    env2store[name] = value
            self.json_instance_values = json.dumps(env2store) if env2store else '{}'
        else:
            self.json_instance_values = {}

    def get_globals(self):
        self.ensure_one()
        concrete_instance = self
        return dict(
            datetime=wrap_module(__import__('datetime'), ['date', 'datetime', 'time', 'timedelta', 'timezone', 'tzinfo', 'MAXYEAR', 'MINYEAR']),
            logger=_logger,
            pprint=pprint.pformat,
            exceptions=wrap_module(odoo.exceptions, ['UserError']),
            json=wrap_module(json, ['loads', 'dumps']),
            base64=wrap_module(base64, ['b64encode', 'b64decode']),
            fsm_instance=concrete_instance,
            fsm_definition=concrete_instance.definition_id,
            user=self.env.user,
            company=self.env.company,
        )

    def consume_event(self, event):
        self.ensure_one()
        env = self.prepare_env()
        self.process_event(event, env)
        self.flush_env(env)

    def process_event(self, event, env):
        self.ensure_one()
        self._cr.execute(f"SELECT id FROM fsm_instance WHERE id = '{self.id}' FOR UPDATE")
        instance_id = self.env.cr.fetchall()[0][0]
        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']

        try:
            definition_policy = fsm_instance.definition_id.execution_policy or 'run'
        except Exception:
            definition_policy = 'run'

        if definition_policy == 'pause_all' and not self.env.context.get('debug_step_bypass'):
            try:
                input_snapshot = json.dumps({'event': event, 'env': env, 'current_state': fsm_instance.current_state})
            except Exception:
                input_snapshot = '{}'
            self.env['fsm.debug.event'].create({'instance_id': fsm_instance.id, 'event_payload': json.dumps(event or {}), 'trigger_env': json.dumps(env or {}), 'state': 'pending'})
            self.env['fsm.execution.log'].create({'instance_id': fsm_instance.id, 'event_name': event.get('name') if isinstance(event, dict) else str(event), 'from_state': fsm_instance.current_state, 'to_state': fsm_instance.current_state, 'input_snapshot': input_snapshot, 'output_snapshot': json.dumps({'intercepted': True, 'reason': 'pause_all'}), 'status': 'intercepted', 'log_type': 'warning'})
            return env

        if fsm_instance.state == 'running':
            try:
                before_state = fsm_instance.current_state
                try:
                    debug_mode = fsm_instance.debug_mode or 'off'
                except Exception:
                    debug_mode = 'off'
                try:
                    input_snapshot = json.dumps({'event': event, 'env': env, 'current_state': fsm_instance.current_state})
                except Exception:
                    input_snapshot = '{}'
                if debug_mode == 'step' and not self.env.context.get('debug_step_bypass'):
                    self.env['fsm.debug.event'].create({'instance_id': fsm_instance.id, 'event_payload': json.dumps(event or {}), 'trigger_env': json.dumps(env or {}), 'state': 'pending'})
                    self.env['fsm.execution.log'].create({'instance_id': fsm_instance.id, 'event_name': event.get('name') if isinstance(event, dict) else str(event), 'from_state': fsm_instance.current_state, 'to_state': fsm_instance.current_state, 'input_snapshot': input_snapshot, 'output_snapshot': json.dumps({'intercepted': True}), 'status': 'intercepted', 'log_type': 'info'})
                    return env

                if fsm_instance.logging:
                    fsm_instance.message_post(subject=f"Processing event", body=Markup(f"<i>Processing <pre>{event}</pre> for instance {fsm_instance.display_name} in state {fsm_instance.current_state}</i>"))

                for target_state in [fsm_instance.current_state, 'all']:
                    current_fsmd = fsm_instance.definition_id
                    while current_fsmd:
                        compiled_definition = json.loads(current_fsmd.json_compiled_definition)
                        if target_state in compiled_definition['states']:
                            state_definition = compiled_definition['states'][target_state]
                            if event['name'] in state_definition:
                                event_definition = state_definition[event['name']]
                                if event_definition.get('pospone', False):
                                    fsm_instance.retain_event(event)
                                else:
                                    fsm_instance.before_event_process(event, env)
                                    env['event'] = event
                                    
                                    # --- Outcome Logic ---
                                    # Provide helper to set outcome from code
                                    def _set_outcome(name):
                                        env['outcome'] = name
                                    env['set_outcome'] = _set_outcome
                                    
                                    code_definition = event_definition['code']
                                    exec(code_definition, global_objects, env)
                                    
                                    # Check for outcome
                                    outcome = env.get('outcome')
                                    outcomes_map = event_definition.get('outcomes', {})
                                    
                                    if outcome:
                                        if outcome in outcomes_map:
                                            new_state = outcomes_map[outcome]
                                            fsm_instance.change_state(new_state)
                                        else:
                                            # Fallback or error? For now, log warning
                                            _logger.warning(f"Outcome '{outcome}' not found in map {outcomes_map} for event {event['name']}")
                                    
                                    fsm_instance.after_event_process(event, env)
                                break
                        current_fsmd = current_fsmd.parent_id

                if (fsm_instance.debug_mode or 'off') == 'trace':
                    try:
                        output_snapshot = json.dumps({'event': event, 'env': env, 'current_state': fsm_instance.current_state})
                    except Exception:
                        output_snapshot = '{}'
                    self.env['fsm.execution.log'].create({'instance_id': fsm_instance.id, 'event_name': event.get('name') if isinstance(event, dict) else str(event), 'from_state': before_state, 'to_state': fsm_instance.current_state, 'input_snapshot': input_snapshot, 'output_snapshot': output_snapshot, 'status': 'success', 'log_type': 'info'})

                return env

            except Exception as e:
                _logger.exception(e, exc_info=True)
                try:
                    self.env['fsm.execution.log'].create({'instance_id': fsm_instance.id, 'event_name': event.get('name') if isinstance(event, dict) else str(event), 'from_state': fsm_instance.current_state, 'to_state': fsm_instance.current_state, 'input_snapshot': input_snapshot if 'input_snapshot' in locals() else '{}', 'output_snapshot': json.dumps({'error': True}), 'status': 'error', 'log_type': 'error', 'error_msg': str(e)})
                except Exception:
                    pass
                fsm_instance.message_post(subject=f"Exception processing event", body=Markup(f"<i>Processing {event['name']} for instance {fsm_instance.display_name} unexpected exception <pre>{pprint.pformat(e)}</pre></i>"))

    def send_event(self, event):
        for fsm_instance in self:
            def register_event():
                dbname = self.env.cr.dbname
                _context = self.env.context
                instance_id = fsm_instance.id
                @self.env.cr.postcommit.add
                def trigger():
                    db_registry = Registry(dbname)
                    with db_registry.cursor() as cr:
                        env = api.Environment(cr, SUPERUSER_ID, _context)
                        fsm_instance = env['fsm.instance'].browse(instance_id).exists()
                        fsm_executor.submit(fsm_consume_event, dbname, _context, fsm_instance.id, event)
                        fsm_instance.on_send_event(event)
            register_event()

    def start_background_service(self, service: callable):
        dbname = self.env.cr.dbname
        _context = self.env.context
        for instance in self:
            def exec_service(instance_id):
                db_registry = Registry(dbname)
                with db_registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, _context)
                    fsm_instance = env['fsm.instance'].browse(instance_id).exists()
                    if fsm_instance:
                        try:
                            fsm_instance.__func__(fsm_instance)
                        except Exception as e:
                            _logger.exception(e, exc_info=True)
                            cr.rollback()
                            fsm_instance.message_post(subject=f"Exception processing service", body=Markup(f"<i>For instance {fsm_instance.display_name} unexpected exception <pre>{pprint.pformat(e)}</pre></i>"))
            instance_id = instance.id
            @api.cr.postcommit.add
            def trigger_service():
                background_service_executor.submit(exec_service, instance_id)

    def start(self):
        self.ensure_one()
        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']
        if fsm_instance.state != 'init':
            _logger.info(f'You cannot not start a not initialized FSM Instance! ({fsm_instance.display_name}')
            return
        if fsm_instance.logging:
            fsm_instance.message_post(subject=f"Starting instance", body=Markup(f"<i>Starting instance {fsm_instance.display_name}</i>"))
        env = {}
        fsmd = fsm_instance.definition_id
        try:
            fsm_stack = []
            while fsmd:
                fsm_stack.append(fsmd)
                fsmd = fsmd.parent_id
            for fsmd in reversed(fsm_stack):
                compiled_definition = json.loads(fsmd.json_compiled_definition)
                if 'start_code' in compiled_definition:
                    code_definition = compiled_definition['start_code']
                    exec(code_definition, global_objects, env)
            fsm_instance.json_instance_values = json.dumps(env)
            fsm_instance.state = 'running'
        except Exception as e:
            _logger.exception(e, exc_info=True)
            if fsm_instance.logging:
                fsm_instance.message_post(subject=f"Unexpected exception starting instance", body=Markup(f"<i>Starting instance {fsm_instance.display_name} exception {e}</i>"))
            raise exceptions.UserError(f'''Starting FSM {fsmd.display_name}, on instance {fsm_instance.display_name}\n Unexpected exception {e}''')

    def end(self):
        for fsm_instance in self:
            if fsm_instance.state != 'running':
                raise exceptions.UserError(f'You cannot not end a non running FSM Instance! ({fsm_instance.display_name}')
            fsm_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
            if fsm_instance.logging:
                fsm_instance.message_post(subject=f"Ending instance", body=Markup(f"<i>Instance {fsm_instance.display_name}</i>"))
            fsm_instance.stop_all_timers()
            fsm_instance.state = 'ended'
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(subject=f"Ending FSM", body=Markup(f'<i>Ending FSM instance {fsm_instance.display_name}</i>)'))
                _logger.info(f"Ending FSM instance {fsm_instance.display_name}")

    def start_logging(self):
        for instance in self:
            instance.logging = True

    def stop_logging(self):
        for instance in self:
            instance.logging = False

    def on_send_event(self, event):
        pass

    def before_event_process(self, event, env):
        pass

    def after_event_process(self, event, env):
        pass

    def change_state(self, new_state):
        self.ensure_one()
        fsm_instance = self
        if fsm_instance.logging:
            concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
            concrete_instance.message_post(subject=f"Changing state", body=Markup(f"<i>Changing state from {fsm_instance.current_state} to: {new_state} for instance {fsm_instance.display_name}</i>"))
            _logger.info(f"Changing state {'from ' + fsm_instance.current_state if fsm_instance.current_state else ''} to: {new_state} for instance {fsm_instance.display_name}")
        fsm_instance.current_state = new_state

    def start_timer(self, event, delay=None, at=None):
        timer_model = self.env['fsm.timer']
        if not at:
            at = fields.Datetime.now() + (timedelta(seconds=delay) if delay else timedelta(seconds=0))
        for fsm_instance in self:
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(subject=f"Starting timer", body=Markup(f"<i>Starting timer with event <pre>{event}</pre> for: {delay} seconds, trigger at: {at} for instance {fsm_instance.display_name}</i>"))
                _logger.info(f"Sending timer {event} for: {delay}, trigger at: {at} for instance {fsm_instance.display_name}")
            def register_event():
                dbname = self.env.cr.dbname
                _context = self.env.context
                instance_id = fsm_instance.id
                @self.env.cr.postcommit.add
                def trigger():
                    db_registry = Registry(dbname)
                    with db_registry.cursor() as cr:
                        env = api.Environment(cr, SUPERUSER_ID, _context)
                        fsm_instance = env['fsm.instance'].browse(instance_id).exists()
                        fsm_executor.submit(fsm_consume_event, dbname, _context, fsm_instance.id, event)
                        fsm_instance.on_send_event(event)
            register_event()
            timer_model.create(dict(name=event['name'], json_event=json.dumps(event), fsm_instance_id=self.id, trigger_at=at, database_name=self.env.cr.dbname,))

    def stop_timer(self, event_name):
        timer_model = self.env['fsm.timer']
        timers = timer_model.search([('name', '=', event_name), ('fsm_instance_id', '=', self.id)])
        if timers:
            timers.unlink()
        for fsm_instance in self:
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(subject=f"Stopping timer", body=Markup(f"<i>Stopping timer {event_name} for instance {fsm_instance.display_name}</i>"))
                _logger.info(f"Stopping timer {event_name} for instance {fsm_instance.display_name}")

    def stop_all_timers(self):
        timer_model = self.env['fsm.timer']
        self.ensure_one()
        timers = timer_model.search([('fsm_instance_id', '=', self.id)])
        if timers:
            timers.unlink()
        for fsm_instance in self:
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(subject=f"Stopping all timers", body=Markup(f"<i>Stopping all timers for instance {fsm_instance.display_name}</i>"))
                _logger.info(f"Stopping all timers for instance {fsm_instance.display_name}")

    def render_dynamic_html(self, template, **params):
        templater = Environment(variable_start_string="{{", variable_end_string="}}",)
        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']
        processed_body = template
        while processed_body.find("{{") >= 0:
            jinja_template = templater.from_string(template)
            processed_body = jinja_template.render(instance=fsm_instance, **params)
        return miniqweb.render(processed_body, **dict(instance=fsm_instance, **params))

    def render_page(self, page_name, **params):
        self.ensure_one()
        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']
        page = self.definition_id.pages.filtered(lambda s: s.name == page_name)
        if not page:
            raise exceptions.UserError(_('Page %s not found for definition %s') % (page_name, self.definition_id.name))
        page = page[0]
        templater = Environment(variable_start_string="{{", variable_end_string="}}",)
        jinja_template = templater.from_string(page.body_html)
        processed_body = jinja_template.render(instance=fsm_instance, **params)
        return miniqweb.render(processed_body, **dict(instance=fsm_instance, **params))

    def action_send_template_mail(self, fsm_instance, target_object, mail_template_name, subject=None):
        self.ensure_one()
        mail_template = self.definition_id.mail_templates.filtered(lambda s: s.name == mail_template_name)
        if not mail_template:
            raise exceptions.UserError(_('Mail template %s not found for definition %s') % (mail_template_name, self.definition_id.name))
        if len(mail_template) > 1:
            concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
            concrete_instance.message_post(subject='Execution error', body=Markup(_("<span>Error trying to send mail template with ambiguous name %s</span>") % mail_template_name),)
        templater = Environment(variable_start_string="{{", variable_end_string="}}",)
        jinja_template = templater.from_string(mail_template.body_html)
        processed_body = jinja_template.render(instance=fsm_instance)
        concrete_body = miniqweb.render(processed_body, **dict(instance=fsm_instance))
        jinja_template = templater.from_string(subject or mail_template.subject or _('Workflow message'))
        concrete_subject = jinja_template.render(instance=fsm_instance)
        target_model = target_object._name
        target_id = target_object.id
        @self.env.cr.postcommit.add
        def send_mail_after_commit():
            env = api.Environment(self.env.cr, self.env.uid, self.env.context)
            target_object = env[target_model].browse(target_id).exists()
            if target_object:
                target_object.message_notify(subject=concrete_subject, body=Markup(concrete_body), attachment_ids=mail_template.attachment_ids.ids, partner_ids=[fsm_instance.partner_id.id] if fsm_instance.partner_id else False,)

    def action_debug_step_over(self):
        self.ensure_one()
        pending = self.env['fsm.debug.event'].search([('instance_id', '=', self.id), ('state', '=', 'pending'),], order='id asc', limit=1)
        if not pending:
            return
        try:
            payload = json.loads(pending.event_payload or '{}')
        except Exception:
            payload = {}
        env = self.prepare_env()
        self.with_context(debug_step_bypass=True).process_event(payload, env)
        self.flush_env(env)
        pending.state = 'processed'

    def action_debug_resume(self):
        self.ensure_one()
        self.debug_mode = 'trace'
        pendings = self.env['fsm.debug.event'].search([('instance_id', '=', self.id), ('state', '=', 'pending'),], order='id asc')
        for p in pendings:
            try:
                payload = json.loads(p.event_payload or '{}')
            except Exception:
                payload = {}
            env = self.prepare_env()
            self.with_context(debug_step_bypass=True).process_event(payload, env)
            self.flush_env(env)
            p.state = 'processed'

    def action_debug_discard(self):
        self.ensure_one()
        pending = self.env['fsm.debug.event'].search([('instance_id', '=', self.id), ('state', '=', 'pending'),], order='id asc', limit=1)
        if not pending:
            return
        pending.state = 'discarded'
        self.env['fsm.execution.log'].create({'instance_id': self.id, 'event_name': (json.loads(pending.event_payload or '{}') or {}).get('name', 'N/A'), 'from_state': self.current_state, 'to_state': self.current_state, 'input_snapshot': pending.event_payload or '{}', 'output_snapshot': json.dumps({'discarded': True}), 'status': 'intercepted', 'log_type': 'warning',})
