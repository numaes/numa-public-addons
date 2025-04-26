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

# If not specifically configured in config file, number of workers
# used to process FSM events
DEFAULT_FSM_WORKERS = 2


def compile_definition(source):
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
                event_body = get_unindented_body()
                for event in current_events:
                    for cstate in current_states:
                        states[cstate][event]['code'] = event_body
                        states[cstate][event]['pospone'] = pospone
                state = 'state_definition'
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
                        else:
                            raise exceptions.UserError(_('Non valid parameter %s in line %d') %
                                                       (tokenized_line[2], line_number))
                    body = []
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
                    for state in current_states:
                        states[state] = {}
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
                    raise exceptions.UserError(_('Invalid meta command %s in line %d') %
                                               (cleaned_line.strip(), line_number))
            else:
                body.append(line)

    if state == 'collecting_start_body':
        start_body = get_unindented_body()
    elif state == 'collecting_event_body':
        event_body = get_unindented_body()
        for event in current_events:
            for cstate in current_states:
                states[cstate][event]['code'] = event_body
                states[cstate][event]['pospone'] = pospone

    return dict(
        start_code=start_body,
        states=states,
        extends=extended_fsmd,
    )


class FSMDefinition(models.Model):
    _name = 'fsm.definition'
    _description = 'FSM Definition'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name', required=True)
    text_definition = fields.Text('Definition')
    json_compiled_definition = fields.Text('JSON Compiled definition')

    parent_id = fields.Many2one('fsm.definition', 'Parent FSM')
    children_ids = fields.One2many('fsm.definition', 'parent_id', 'Children FSMs')

    pages = fields.Many2many('fsm.wf.page_template', 'wf_page_templates_rel', string='Pages')
    mail_templates = fields.Many2many('fsm.wf.mail_template', 'wf_mail_templates_rel', string='Mail templates')

    # For subclasses, used to filter per usage
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
                    raise exceptions.UserError(_(
                        'Extended FSM %s not found!'
                    ) % cd['extends'])
            for child in fsm.children_ids:
                child.onchange_text_definition()


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
    body_html = fields.Html(
        string='Body converted to be sent by mail', sanitize='email_outgoing',
        render_engine='qweb', render_options={'post_process': True})
    is_body_empty = fields.Boolean(compute="_compute_is_body_empty")

    render_model = fields.Char('Render model', default='fsm.instance')

    attachment_ids = fields.Many2many(
        'ir.attachment', 'wfmt_ir_attachments_rel',
        'wfmt_id', 'attachment_id',
        string='Attachments'
    )

    def open_mail_template(self):
        self.ensure_one()

        compose_form = self.env.ref('numa_fsm.mail_template_html_edit')

        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'view_mode': 'form',
            'res_model': 'fsm.wf.mail_template',
            'views': [(compose_form.id, 'form')],
            'view_id': compose_form.id,
            'res_id': self.id,
        }


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

        return {
            "type": "ir.actions.act_url",
            "url": '/fsm_page_template/%d' % self.id,
            "target": "new"
        }


class FSMFormInput(models.TransientModel):
    _name = 'fsm.form_input'
    _description = 'FSM Form input'

    website_form_access = fields.Boolean('Allowed to use in forms', help='Enable the form builder feature for this model.')

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
            new_record = super().create(dict(
                instance_id=instance.id if instance else False,
                unrelated_identifier=vals['unrelated_identifier'],
                json_data=json_data,
            ))

            file_vals = {}
            for name, content in vals.items():
                if isinstance(content, FileStorage):
                    field_name = name.split('[', 1)[0]
                    attachment = attachment_model.create({
                        'name': content.filename,
                        'res_model': self._name,
                        'res_id': new_record.id,
                        'type': 'binary',
                        'datas': base64.b64encode(content.read()),
                        'description': content.filename,
                    })
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
                        raise exceptions.UserError(
                            _('Field %s does not exists in model %s') % (field_name, instance._name)
                        )
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


def fsm_consume_event(db_name: str, _context: dict, instance_id: int, event: dict):
    instance = None
    try:
        db = odoo.sql_db.db_connect(db_name)
        threading.current_thread().dbname = db_name
        with db.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, _context)
            instance = env['fsm.instance'].browse(instance_id).exists()
            if instance:
                instance_env = instance.prepare_env()
                instance.process_event(event, instance_env)
    except Exception as e:
        _logger.exception('Exception in FSM instance %s:' %
                          (instance.display_name if instance else 'N/A'),
                          exc_info=True,
                          stack_info=True)
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

    concrete_model = fields.Char('Concrete model', default='fsm.instance')
    concrete_id = fields.Integer('Concrete ID')
    current_page = fields.Many2one('fsm.wf.page_template', 'Current page')

    name = fields.Char('Instance ID', default=lambda s: uuid.uuid4())
    definition_id = fields.Many2one('fsm.definition', 'Definition', required=True)
    type = fields.Char(string='Type', related='definition_id.type', readonly=True)
    current_state = fields.Char('Current state', copy=False)
    events_queue = fields.One2many('fsm.event_entry', 'instance_id', 'Events queue')
    retained_events = fields.One2many('fsm.event_entry', 'retained_instance_id', 'Posponed Events queue')

    json_instance_values = fields.Text('JSON Instance Values')

    state = fields.Selection(
        [('init', 'For Init'), ('running', 'Running'), ('stopped', 'Stopped'), ('ended', 'Ended')],
        string='State',
        required=True,
        default='init',
        copy=False,
    )

    logging = fields.Boolean('Logging?')

    def set_page(self, page_name):
        self.ensure_one()
        current_page = self.definition_id.pages.filtered(lambda s: s.name == page_name)
        if len(current_page) >= 1:
            self.current_page = current_page[0]
        else:
            raise exceptions.UserError(
                _('Page %s not found!') % page_name
            )

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

        concrete_instance = self.env[self.concrete_model].browse(self.concrete_id).exists()

        return dict(
            datetime=wrap_module(
                __import__('datetime'),
                ['date', 'datetime', 'time', 'timedelta', 'timezone', 'tzinfo', 'MAXYEAR', 'MINYEAR']
            ),
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

        # Wait til lock is released
        self._cr.execute(
            f"SELECT id FROM fsm_instance "
            f"WHERE id = '{self.id}' FOR UPDATE")

        instance_id = self.env.cr.fetchall()[0][0]

        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']

        if fsm_instance.state == 'running':
            try:
                if fsm_instance.logging:
                    fsm_instance.message_post(
                        subject=f"Processing event",
                        body=Markup(
                            f"<i>Processing <pre>{event}</pre> "
                            f"for instance {fsm_instance.display_name} "
                            f"in state {fsm_instance.current_state}</i>"
                        )
                    )

                for target_state in [fsm_instance.current_state, 'all']:
                    current_fsmd = fsm_instance.definition_id
                    while current_fsmd:
                        compiled_definition = json.loads(current_fsmd.json_compiled_definition)
                        env = fsm_instance.prepare_env()
                        if target_state in compiled_definition['states']:
                            state_definition = compiled_definition['states'][target_state]
                            if event['name'] in state_definition:
                                event_definition = state_definition[event['name']]
                                if event_definition.get('pospone', False):
                                    fsm_instance.retain_event(event)
                                else:
                                    fsm_instance.before_event_process(event, env)
                                    env['event'] = event
                                    code_definition = event_definition['code']
                                    exec(code_definition, global_objects, env)
                                    fsm_instance.after_event_process(event, env)
                                break
                        current_fsmd = current_fsmd.parent_id

                return env

            except Exception as e:
                _logger.exception(e, exc_info=True)
                fsm_instance.message_post(
                    subject=f"Exception processing event",
                    body=Markup(
                        f"<i>Processing {event['name']} "
                        f"for instance {fsm_instance.display_name}"
                        f"unexpected exception <pre>{pprint.pformat(e)}</pre></i>"
                    )
                )
                raise exceptions.UserError(
                    f"Processing event {event['name']}, "
                    f"instance {fsm_instance.display_name}, "
                    f"on state {fsm_instance.current_state}\n"
                    f"Unexpected exception {e}"
                )

    def send_event(self, event):
        # Send an event to eventually multiple receivers
        # Events only be sent if the transaction commits

        event_model = self.env['fsm.event_entry']

        for fsm_instance in self:
            fsm_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()

            def register_event():
                # In case of several event receivers, prepare one task trigger per receiver
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

    def start(self):
        self.ensure_one()

        global_objects = self.get_globals()

        fsm_instance = global_objects['fsm_instance']
        if fsm_instance.state != 'init':
            _logger.info(f'You cannot not start a not initialized FSM Instance! ({fsm_instance.display_name}')
            return

        if fsm_instance.logging:
            fsm_instance.message_post(
                subject=f"Starting instance",
                body=Markup(
                    f"<i>Starting instance {fsm_instance.display_name}</i>"
                )
            )

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
                fsm_instance.message_post(
                    subject=f"Unexpected exception starting instance",
                    body=Markup(
                        f"<i>Starting instance {fsm_instance.display_name}"
                        f"exception {e}</i>"
                    )
                )

            raise exceptions.UserError(
                f'''Starting FSM {fsmd.display_name}, on instance {fsm_instance.display_name}\n
                Unexpected exception {e}'''
            )

    def end(self):
        for fsm_instance in self:
            if fsm_instance.state != 'running':
                raise exceptions.UserError(
                    f'You cannot not end a non running FSM Instance! ({fsm_instance.display_name}'
                )

            fsm_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
            if fsm_instance.logging:
                fsm_instance.message_post(
                    subject=f"Ending instance",
                    body=Markup(
                        f"<i>Instance {fsm_instance.display_name}</i>"
                    )
                )

            fsm_instance.stop_all_timers()
            fsm_instance.state = 'ended'
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(
                    subject=f"Ending FSM",
                    body=Markup(f'<i>Ending FSM instance {fsm_instance.display_name}</i>)')
                )
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
            concrete_instance.message_post(
                subject=f"Changing state",
                body=Markup(
                    f"<i>Changing state from {fsm_instance.current_state} "
                    f"to: {new_state} for instance {fsm_instance.display_name}</i>"
                )
            )
            _logger.info(f"Changing state {'from ' + fsm_instance.current_state if fsm_instance.current_state else ''} "
                         f"to: {new_state} for instance {fsm_instance.display_name}")

        fsm_instance.current_state = new_state

    def start_timer(self, event, delay=None, at=None):
        timer_model = self.env['fsm.timer']

        if not at:
            at = fields.Datetime.now() + (timedelta(seconds=delay) if delay else timedelta(seconds=0))

        for fsm_instance in self:
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(
                    subject=f"Starting timer",
                    body=Markup(
                        f"<i>Starting timer with event <pre>{event}</pre> "
                        f"for: {delay} seconds, trigger at: {at} for instance {fsm_instance.display_name}</i>"
                    )
                )
                _logger.info(f"Sending timer {event} "
                             f"for: {delay}, trigger at: {at} for instance {fsm_instance.display_name}")

            def register_event():
                # In case of several event receivers, prepare one task trigger per receiver
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

            timer_model.create(dict(
                name=event['name'],
                json_event=json.dumps(event),
                fsm_instance_id=self.id,
                trigger_at=at,
                database_name=self.env.cr.dbname,
            ))

    def stop_timer(self, event_name):
        timer_model = self.env['fsm.timer']

        timers = timer_model.search([('name', '=', event_name), ('fsm_instance_id', '=', self.id)])
        if timers:
            timers.unlink()

        for fsm_instance in self:
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(
                    subject=f"Stopping timer",
                    body=Markup(
                        f"<i>Stopping timer {event_name} "
                        f"for instance {fsm_instance.display_name}</i>"
                    )
                )
                _logger.info(f"Stopping timer {event_name} "
                             f"for instance {fsm_instance.display_name}")

    def stop_all_timers(self):
        timer_model = self.env['fsm.timer']

        self.ensure_one()
        timers = timer_model.search([('fsm_instance_id', '=', self.id)])
        if timers:
            timers.unlink()

        for fsm_instance in self:
            if fsm_instance.logging:
                concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
                concrete_instance.message_post(
                    subject=f"Stopping all timers",
                    body=Markup(
                        f"<i>Stopping all timers "
                        f"for instance {fsm_instance.display_name}</i>"
                    )
                )
                _logger.info(f"Stopping all timers "
                             f"for instance {fsm_instance.display_name}")

    def render_dynamic_html(self, template, **params):
        templater = Environment(
            variable_start_string="{{",
            variable_end_string="}}",
        )

        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']
        processed_body = template
        while processed_body.find("{{") >= 0:
            # Inject data into the view and replace our template tags with the data
            jinja_template = templater.from_string(template)
            processed_body = jinja_template.render(
                instance=fsm_instance,
                **params
            )

        return miniqweb.render(processed_body, **dict(instance=fsm_instance, **params))

    def render_page(self, page_name, **params):
        self.ensure_one()

        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']
        page = self.definition_id.pages.filtered(lambda s: s.name == page_name)
        if not page:
            raise exceptions.UserError(
                _('Page %s not found for definition %s') %
                (page_name, self.definition_id.name)
            )

        page = page[0]
        templater = Environment(
            variable_start_string="{{",
            variable_end_string="}}",
        )
        jinja_template = templater.from_string(page.body_html)

        # Inject data into the view and replace our template tags with the data
        processed_body = jinja_template.render(
            instance=fsm_instance,
            **params
        )

        return miniqweb.render(processed_body, **dict(instance=fsm_instance, **params))

    def action_send_template_mail(self, fsm_instance, target_object, mail_template_name, subject=None):
        self.ensure_one()

        mail_template = self.definition_id.mail_templates.filtered(lambda s: s.name == mail_template_name)
        if not mail_template:
            raise exceptions.UserError(
                _('Mail template %s not found for definition %s') %
                (mail_template_name, self.definition_id.name)
            )
        if len(mail_template) > 1:
            concrete_instance = self.env[fsm_instance.concrete_model].browse(fsm_instance.concrete_id).exists()
            concrete_instance.message_post(
                subject='Execution error',
                body=Markup(
                    _("<span>Error trying to send mail template with ambiguous name %s</span>") % mail_template_name
                ),
            )

        templater = Environment(
            variable_start_string="{{",
            variable_end_string="}}",
        )
        jinja_template = templater.from_string(mail_template.body_html)

        # Inject data into the view and replace our template tags with the data
        processed_body = jinja_template.render(instance=fsm_instance)

        concrete_body = miniqweb.render(processed_body, **dict(instance=fsm_instance))

        # Inject data into the view and replace our template tags with the data
        jinja_template = templater.from_string(subject or mail_template.subject or _('Workflow message'))

        concrete_subject = jinja_template.render(instance=fsm_instance)

        target_object.message_notify(
            subject=concrete_subject,
            body=Markup(concrete_body),
            attachment_ids=mail_template.attachment_ids.ids,
            partner_ids=[fsm_instance.partner_id.id] if fsm_instance.partner_id else False,
        )

