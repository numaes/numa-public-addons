"""
Finite State Machine (FSM) Module for Odoo

This module implements a comprehensive Finite State Machine system for Odoo,
allowing the definition and execution of complex workflows. It provides:

- FSM definition parsing and compilation
- Workflow state management
- Event processing and transitions
- Timer-based events
- Email template integration
- Dynamic page rendering
- Form input handling

The module is designed to be flexible and extensible, supporting various
business process automation needs within the Odoo ecosystem.
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

# If not specifically configured in config file, number of workers
# used to process FSM events
DEFAULT_FSM_WORKERS = 2


def compile_definition(source):
    """
    Compile an FSM definition from source text into a structured representation.

    This function parses a text-based FSM definition with special syntax and converts
    it into a Python dictionary that represents the FSM structure, including states,
    events, transitions, and actions.

    The FSM definition uses a custom syntax with meta-lines starting with '@' that
    define states, events, and transitions, followed by Python code blocks that
    define the actions to be executed.

    Args:
        source (str): The source text containing the FSM definition

    Returns:
        dict: A dictionary containing the compiled FSM definition with the following keys:
            - 'states': Dictionary of states and their properties
            - 'events': Dictionary of events and their properties
            - 'transitions': List of transitions between states
            - 'code': The Python code associated with the FSM
            - 'extended': Boolean indicating if this is an extended FSM
            - 'postpone': Boolean indicating if event processing should be postponed

    Raises:
        odoo.exceptions.UserError: If there are syntax errors in the FSM definition
    """
    def tokenize(meta_line):
        """
        Split a meta-line into tokens.

        Args:
            meta_line (str): A line from the FSM definition starting with '@'

        Returns:
            list: A list of tokens extracted from the meta-line
        """
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
        """
        Check if a line is a meta-line (starts with '@').

        Args:
            raw_line (str): A line from the FSM definition

        Returns:
            bool: True if the line is a meta-line, False otherwise
        """
        if len(raw_line) > 0 and raw_line[0] == '@':
            return True
        return False

    body = []  # Collects the code body of the FSM definition

    def get_unindented_body():
        """
        Process the collected code body and normalize indentation.

        This function detects the indentation level of the first non-empty line
        and removes that amount of leading whitespace from all lines. It also
        checks for consistent indentation across the code body.

        Returns:
            str: The normalized code with consistent indentation

        Raises:
            odoo.exceptions.UserError: If inconsistent indentation is detected
        """
        indentation = 0
        indentation_found = False
        # Find the indentation level of the first non-empty line
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
                # Process each character in the line
                for c in line:
                    position += 1
                    if c == '#':
                        break  # Stop at comments
                    elif c != ' ':
                        all_spaces = False
                        if first_char_position < 0:
                            first_char_position = position
                        cleaned_line += c
                # Check for consistent indentation
                if not all_spaces and first_char_position < indentation:
                    raise exceptions.UserError('Line indentation is not following the first line')
                # Remove the leading indentation
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
    """
    Finite State Machine Definition Model

    This model stores the definitions of finite state machines (FSMs) used in the system.
    Each FSM definition includes a text-based definition that is compiled into a structured
    JSON representation. FSM definitions can extend other definitions, creating a hierarchy.

    The text definition uses a custom syntax with meta-lines starting with '@' that define
    states, events, and transitions, followed by Python code blocks that define the actions
    to be executed.
    """
    _name = 'fsm.definition'
    _description = 'FSM Definition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _depend_models = OrderedDict()

    name = fields.Char('Name', required=True)
    text_definition = fields.Text('Definition')
    json_compiled_definition = fields.Text('JSON Compiled definition')

    # Visual Designer Schema (positions, zoom, topology)
    # Stored as JSON text to avoid dependency on DB json column capabilities
    json_ui_schema = fields.Text(
        string='UI Schema (JSON)',
        help='Visual layout schema for the FSM designer: nodes, connections, positions, zoom, etc.'
    )

    # Executable Logic Schema (Black Box with Outcomes)
    # Defines transitions with code and named outcomes mapping to target states
    json_logic_schema = fields.Text(
        string='Logic Schema (JSON)',
        help='Logic schema used by the FSM engine. Contains transitions with Python code and outcome-to-state mappings.'
    )

    parent_id = fields.Many2one('fsm.definition', 'Parent FSM')
    children_ids = fields.One2many('fsm.definition', 'parent_id', 'Children FSMs')

    pages = fields.Many2many('fsm.wf.page_template', 'wf_page_templates_rel', string='Pages')
    mail_templates = fields.Many2many('fsm.wf.mail_template', 'wf_mail_templates_rel', string='Mail templates')

    # For subclasses, used to filter per usage
    type = fields.Char('Type')

    @api.onchange('text_definition')
    def onchange_text_definition(self):
        """
        Compile the text definition into a JSON representation when it changes.

        This method is triggered when the text_definition field changes. It compiles
        the text definition into a structured representation, updates the JSON field,
        and handles parent-child relationships based on the 'extends' directive in
        the definition.

        If the FSM extends another FSM, it sets the parent_id field accordingly.
        It also propagates changes to child FSMs by triggering their onchange methods.

        Raises:
            odoo.exceptions.UserError: If an extended FSM referenced in the definition
                                       cannot be found in the system.
        """
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
    """
    Email Template Model for FSM Workflows

    This model defines email templates that can be used within FSM workflows.
    These templates can be referenced in FSM definitions and used to send
    emails at specific points in the workflow process.

    The templates use QWeb for rendering and can access FSM instance data
    during the rendering process.
    """
    _name = 'fsm.wf.mail_template'
    _description = 'FSM WorkFlow Mail template'

    _inherit = ['mail.render.mixin']

    @api.model
    def default_body_view_id(self):
        """
        Create a default QWeb view for new mail templates.

        Returns:
            ir.ui.view: A newly created empty QWeb view for the template body
        """
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
        """
        Open the mail template in a form view for editing.

        Returns:
            dict: Action dictionary for opening the template form
        """
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
    """
    Page Template Model for FSM Workflows

    This model defines HTML page templates that can be used within FSM workflows.
    These templates can be referenced in FSM definitions and used to render
    dynamic HTML pages at specific points in the workflow process.

    The templates can access FSM instance data during the rendering process,
    allowing for dynamic content generation based on workflow state.
    """
    _name = 'fsm.wf.page_template'
    _description = 'FSM WorkFlow Page template'

    _inherit = ['mail.render.mixin']

    name = fields.Char('Name', required=True)
    body = fields.Html('Body', sanitize=False)

    def plain_body(self, target_object, vals=None):
        """
        Render the template body with the given target object and values.

        Args:
            target_object: The object to use for rendering (typically an FSM instance)
            vals (dict, optional): Additional values to include in the rendering context

        Returns:
            str: The rendered HTML content
        """
        self.ensure_one()

        context = dict(vals or {}, object=target_object)

        return self.body_view_id._render(context)

    def open_page_template(self):
        """
        Open the page template in a web browser for preview.

        Returns:
            dict: Action dictionary for opening the template in a browser
        """
        self.ensure_one()

        return {
            "type": "ir.actions.act_url",
            "url": '/fsm_page_template/%d' % self.id,
            "target": "new"
        }


class FSMFormInput(models.TransientModel):
    """
    Form Input Model for FSM Workflows

    This transient model handles form submissions from web interfaces to FSM instances.
    It processes both regular form data and file uploads, storing the data in a structured
    format and associating it with the appropriate FSM instance.

    The model is designed to be used with the website form builder and provides methods
    for retrieving and processing uploaded files.
    """
    _name = 'fsm.form_input'
    _description = 'FSM Form input'

    website_form_access = fields.Boolean('Allowed to use in forms', help='Enable the form builder feature for this model.')

    instance_id = fields.Many2one('fsm.instance', 'Target instance')
    unrelated_identifier = fields.Char('Unrelated identifier')
    json_data = fields.Char('JSON Data')
    json_files = fields.Char('JSON Files')

    @api.model_create_multi
    def create(self, vals_list):
        """
        Create form input records from submitted form data.

        This method processes form submissions, handling both regular form fields
        and file uploads. It creates a form input record with the form data stored
        as JSON and associates it with the appropriate FSM instance.

        Args:
            vals_list (list): List of dictionaries containing form field values

        Returns:
            fsm.form_input: The created form input records
        """
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
        """
        Retrieve a file uploaded through the form.

        Args:
            name (str): The name of the file field in the form

        Returns:
            bytes or None: The base64-encoded file data if found, None otherwise
        """
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
        """
        Move an uploaded file to a binary field in the target instance.

        This method transfers ownership of an uploaded file attachment to the
        specified instance and field, allowing the file to be permanently stored
        in the database associated with the appropriate record.

        Args:
            instance (Model): The target instance to associate the file with
            name (str): The name of the file field in the form
            field_name (str): The name of the binary field in the target instance

        Raises:
            odoo.exceptions.UserError: If the specified field does not exist in the target instance
        """
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
        """
        Hook method for debugging purposes during development and testing.

        This method can be called from form submissions to log debugging information.
        """
        _logger.info('Debug hook')

# Worker pool configuration

fsm_workers_config = config.get('fsm_workers')

# Configure the thread pool size for FSM event processing
if not fsm_workers_config:
    fsm_workers = DEFAULT_FSM_WORKERS
else:
    fsm_workers = int(fsm_workers_config)

# Create a thread pool executor for processing FSM events asynchronously
fsm_executor = ThreadPoolExecutor(max_workers=fsm_workers)

# Configure the thread pool size for FSM background services

fsm_service_workers_config = config.get('fsm_service_workers')

if not fsm_service_workers_config:
    fsm_service_workers = DEFAULT_FSM_WORKERS
else:
    fsm_service_workers = int(fsm_workers_config)

background_service_executor = ThreadPoolExecutor(max_workers=fsm_service_workers)


def fsm_consume_event(db_name: str, _context: dict, instance_id: int, event: dict):
    """
    Process an FSM event in a separate database connection.

    This function is designed to be called from a separate thread or process to handle
    FSM events asynchronously. It connects to the specified database, retrieves the
    FSM instance, and processes the event.

    Args:
        db_name (str): The name of the database to connect to
        _context (dict): The Odoo environment context
        instance_id (int): The ID of the FSM instance to process the event for
        event (dict): The event data to process

    Note:
        This function handles exceptions internally and logs them, so it's safe
        to call from a thread pool without additional exception handling.
    """
    instance = None
    # Connect to the database
    db = odoo.sql_db.db_connect(db_name)
    threading.current_thread().dbname = db_name
    with db.cursor() as cr:
        try:
            # Create a new environment with the cursor
            env = api.Environment(cr, SUPERUSER_ID, _context)
            # Get the FSM instance
            instance = env['fsm.instance'].browse(instance_id).exists()
            if instance:
                # Prepare the environment and process the event
                instance_env = instance.prepare_env()
                instance.process_event(event, instance_env)

        except Exception as e:
            _logger.exception('Exception in FSM instance %s:' %
                              (instance.display_name if instance else 'N/A'),
                              exc_info=True,
                              stack_info=True)
            cr.rollback()
            instance.message_post(
                subject=f"Exception processing event",
                body=Markup(
                    f"<i>On event {event.get('name', 'N/D')}"
                    f"for instance {instance.display_name}"
                    f"unexpected exception <pre>{pprint.pformat(e)}</pre></i>"
                )
            )

        finally:
            if hasattr(threading.current_thread(), 'dbname'):
                del threading.current_thread().dbname


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
    """
    Finite State Machine Instance Model

    This model represents an active instance of a finite state machine (FSM) in the system.
    Each instance is associated with a specific FSM definition and maintains its own state,
    event queue, and instance-specific data.

    FSM instances can be standalone or associated with other models through the concrete_model
    and concrete_id fields. They process events according to the rules defined in their
    associated FSM definition, transitioning between states and executing actions as needed.

    The instance maintains a queue of events to be processed and can also retain events
    for later processing. It provides methods for starting, stopping, and ending the FSM,
    as well as for processing events, changing states, and managing timers.
    """
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

    state = fields.Selection(
        [('init', 'For Init'), ('running', 'Running'), ('stopped', 'Stopped'), ('ended', 'Ended')],
        string='State',
        required=True,
        default='init',
        copy=False,
    )

    logging = fields.Boolean('Logging?')

    # Debugging Suite
    debug_mode = fields.Selection(
        selection=[('off', 'Off'), ('trace', 'Trace Only'), ('step', 'Step-by-Step / Pause')],
        string='Debug Mode',
        default='off',
        tracking=True,
    )
    execution_log_ids = fields.One2many(
        'fsm.execution.log', 'instance_id', string='Execution Logs'
    )
    pending_debug_event_ids = fields.One2many(
        'fsm.debug.event', 'instance_id',
        string='Pending Debug Events',
        domain=[('state', '=', 'pending')]
    )

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

        concrete_instance = self

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
        """
        Process an event immediately in the current transaction.

        This method prepares the environment, processes the event, and then
        flushes the environment back to the instance. It's used for synchronous
        event processing within the current transaction.

        Args:
            event (dict): The event to process

        Returns:
            None
        """
        self.ensure_one()

        env = self.prepare_env()
        self.process_event(event, env)
        self.flush_env(env)

    def process_event(self, event, env):
        """
        Process an event according to the FSM definition.

        This is the core method for event processing in the FSM. It looks up the
        appropriate event handler in the FSM definition based on the current state
        and event name, and executes the associated code.

        The method acquires a lock on the FSM instance to ensure that only one
        process can modify the instance at a time. It also handles event postponing
        and error reporting.

        Args:
            event (dict): The event to process, containing at least a 'name' key
            env (dict): The environment dictionary for the event processing

        Returns:
            dict: The updated environment after event processing

        Raises:
            odoo.exceptions.UserError: If an error occurs during event processing
        """
        self.ensure_one()

        # Wait until lock is released
        self._cr.execute(
            f"SELECT id FROM fsm_instance "
            f"WHERE id = '{self.id}' FOR UPDATE")

        instance_id = self.env.cr.fetchall()[0][0]

        global_objects = self.get_globals()
        fsm_instance = global_objects['fsm_instance']

        if fsm_instance.state == 'running':
            try:
                before_state = fsm_instance.current_state
                # Debug interception (step mode) — do not execute, enqueue debug event and log
                try:
                    debug_mode = fsm_instance.debug_mode or 'off'
                except Exception:
                    debug_mode = 'off'

                # Prepare input snapshot
                try:
                    input_snapshot = json.dumps({
                        'event': event,
                        'env': env,
                        'current_state': fsm_instance.current_state,
                    })
                except Exception:
                    input_snapshot = '{}'

                # In step mode, intercept unless bypass flag is present in context
                if debug_mode == 'step' and not self.env.context.get('debug_step_bypass'):
                    self.env['fsm.debug.event'].create({
                        'instance_id': fsm_instance.id,
                        'event_payload': json.dumps(event or {}),
                        'trigger_env': json.dumps(env or {}),
                        'state': 'pending',
                    })
                    self.env['fsm.execution.log'].create({
                        'instance_id': fsm_instance.id,
                        'event_name': event.get('name') if isinstance(event, dict) else str(event),
                        'from_state': fsm_instance.current_state,
                        'to_state': fsm_instance.current_state,
                        'input_snapshot': input_snapshot,
                        'output_snapshot': json.dumps({'intercepted': True}),
                        'status': 'intercepted',
                        'log_type': 'info',
                    })
                    return env

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
                        # 1) Try outcome-based logic schema if present
                        logic_schema = None
                        if current_fsmd.json_logic_schema:
                            try:
                                logic_schema = json.loads(current_fsmd.json_logic_schema)
                            except Exception:
                                logic_schema = None

                        handled = False
                        if logic_schema and isinstance(logic_schema, dict):
                            transitions = logic_schema.get('transitions') or {}
                            state_transitions = transitions.get(target_state) or {}
                            transition_def = state_transitions.get(event['name'])
                            if transition_def:
                                # Found outcome-based transition
                                pospone = transition_def.get('pospone', False)
                                if pospone:
                                    fsm_instance.retain_event(event)
                                else:
                                    fsm_instance.before_event_process(event, env)
                                    env['event'] = event
                                    # Provide helper to set outcome from code
                                    def _set_outcome(name):
                                        env['outcome'] = name
                                    env['set_outcome'] = _set_outcome
                                    code_definition = transition_def.get('code') or ''
                                    # Execute code. It may set env['outcome'] or variable outcome
                                    try:
                                        exec(code_definition, global_objects, env)
                                    except Exception as ex:
                                        raise exceptions.UserError(_(
                                            "Error executing transition code for %s/%s: %s"
                                        ) % (target_state, event['name'], str(ex)))
                                    # Normalize outcome: check env mapping or plain variable
                                    outcome = env.get('outcome')
                                    if outcome is None and 'outcome' in locals():
                                        # locals() here refers to function scope; executed code won't put variables here
                                        # So we only rely on env
                                        outcome = None
                                    # If outcome is provided, resolve and change state
                                    if outcome is not None:
                                        outcomes_map = (transition_def.get('outcomes') or {})
                                        if outcome not in outcomes_map:
                                            raise exceptions.UserError(_(
                                                "Outcome '%s' not defined for transition %s/%s"
                                            ) % (outcome, target_state, event['name']))
                                        new_state = outcomes_map[outcome]
                                        if new_state:
                                            fsm_instance.change_state(new_state)
                                    else:
                                        # No outcome set: keep state, but log warning for visibility
                                        _logger.warning(
                                            "FSM outcome-based transition produced no outcome: instance=%s state=%s event=%s",
                                            fsm_instance.display_name, target_state, event.get('name')
                                        )
                                    fsm_instance.after_event_process(event, env)
                                handled = True
                        if handled:
                            break

                        # 2) Fallback to legacy compiled definition
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

                # Trace logging (success path)
                if (fsm_instance.debug_mode or 'off') == 'trace':
                    try:
                        output_snapshot = json.dumps({
                            'event': event,
                            'env': env,
                            'current_state': fsm_instance.current_state,
                        })
                    except Exception:
                        output_snapshot = '{}'
                    self.env['fsm.execution.log'].create({
                        'instance_id': fsm_instance.id,
                        'event_name': event.get('name') if isinstance(event, dict) else str(event),
                        'from_state': before_state,
                        'to_state': fsm_instance.current_state,
                        'input_snapshot': input_snapshot,
                        'output_snapshot': output_snapshot,
                        'status': 'success',
                        'log_type': 'info',
                    })

                return env

            except Exception as e:
                _logger.exception(e, exc_info=True)
                # Trace logging (error path)
                try:
                    self.env['fsm.execution.log'].create({
                        'instance_id': fsm_instance.id,
                        'event_name': event.get('name') if isinstance(event, dict) else str(event),
                        'from_state': fsm_instance.current_state,
                        'to_state': fsm_instance.current_state,
                        'input_snapshot': input_snapshot if 'input_snapshot' in locals() else '{}',
                        'output_snapshot': json.dumps({'error': True}),
                        'status': 'error',
                        'log_type': 'error',
                        'error_msg': str(e),
                    })
                except Exception:
                    # avoid masking original error if logging fails
                    pass
                fsm_instance.message_post(
                    subject=f"Exception processing event",
                    body=Markup(
                        f"<i>Processing {event['name']} "
                        f"for instance {fsm_instance.display_name}"
                        f"unexpected exception <pre>{pprint.pformat(e)}</pre></i>"
                    )
                )

    def send_event(self, event):
        """
        Send an event asynchronously to the FSM instance.

        This method queues an event for asynchronous processing after the current
        transaction commits. It uses the FSM executor thread pool to process the
        event in a separate thread, avoiding blocking the current transaction.

        The event will only be processed if the current transaction commits successfully.

        Args:
            event (dict): The event to send, containing at least a 'name' key

        Returns:
            None
        """
        # Send an event to potentially multiple receivers
        # Events will only be sent if the transaction commits

        for fsm_instance in self:
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

                            fsm_instance.message_post(
                                subject=f"Exception processing service",
                                body=Markup(
                                    f"<i>For instance {fsm_instance.display_name}"
                                    f"unexpected exception <pre>{pprint.pformat(e)}</pre></i>"
                                )
                            )

            instance_id = instance.id
            @api.cr.postcommit.add
            def trigger_service():
                background_service_executor.submit(exec_service, instance_id)

    def start(self):
        """
        Initialize and start the FSM instance.

        This method initializes the FSM instance by setting its initial state and
        executing the start code from the FSM definition. It also sets the instance
        state to 'running' and logs the start event if logging is enabled.

        The method can only be called on instances in the 'init' state.

        Returns:
            None
        """
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
        """
        End the FSM instance.

        This method ends the FSM instance by stopping all timers and setting the
        state to 'ended'. It also logs the end event if logging is enabled.

        The method can only be called on instances in the 'running' state.

        Raises:
            odoo.exceptions.UserError: If the instance is not in the 'running' state

        Returns:
            None
        """
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
        """
        Change the current state of the FSM instance.

        This method changes the current state of the FSM instance to the specified
        new state. It also logs the state change if logging is enabled.

        Args:
            new_state (str): The new state to transition to

        Returns:
            None
        """
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
        """
        Start a timer that will trigger an event after a delay or at a specific time.

        This method creates a timer that will send the specified event to the FSM instance
        either after the specified delay or at the specified time. The timer is stored
        in the database and will be processed by the scheduler.

        Args:
            event (dict): The event to send when the timer triggers
            delay (int, optional): The delay in seconds before triggering the event
            at (datetime, optional): The specific time at which to trigger the event

        Note:
            Either delay or at must be specified. If both are specified, at takes precedence.
            If neither is specified, the event is triggered immediately.

        Returns:
            None
        """
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

        target_model = target_object._name
        target_id = target_object.id

        @self.env.cr.postcommit.add
        def send_mail_after_commit():
            env = api.Environment(self.env.cr, self.env.uid, self.env.context)
            target_object = env[target_model].browse(target_id).exists()
            if target_object:
                target_object.message_notify(
                    subject=concrete_subject,
                    body=Markup(concrete_body),
                    attachment_ids=mail_template.attachment_ids.ids,
                    partner_ids=[fsm_instance.partner_id.id] if fsm_instance.partner_id else False,
                )

    # ------------------------------------------------------------------
    # Debugging Controls (Step Over / Resume / Discard)
    # NOTE: XML buttons will be added in a later sub-step
    # ------------------------------------------------------------------
    def action_debug_step_over(self):
        """Process the oldest pending debug event once, bypassing interception."""
        self.ensure_one()
        pending = self.env['fsm.debug.event'].search([
            ('instance_id', '=', self.id),
            ('state', '=', 'pending'),
        ], order='id asc', limit=1)
        if not pending:
            return
        try:
            payload = json.loads(pending.event_payload or '{}')
        except Exception:
            payload = {}
        # Process using process_event with bypass flag
        env = self.prepare_env()
        self.with_context(debug_step_bypass=True).process_event(payload, env)
        # Persist env changes
        self.flush_env(env)
        pending.state = 'processed'

    def action_debug_resume(self):
        """Switch to trace mode and process all pending debug events sequentially."""
        self.ensure_one()
        self.debug_mode = 'trace'
        pendings = self.env['fsm.debug.event'].search([
            ('instance_id', '=', self.id),
            ('state', '=', 'pending'),
        ], order='id asc')
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
        """Discard the oldest pending debug event and optionally log it."""
        self.ensure_one()
        pending = self.env['fsm.debug.event'].search([
            ('instance_id', '=', self.id),
            ('state', '=', 'pending'),
        ], order='id asc', limit=1)
        if not pending:
            return
        # Mark as discarded
        pending.state = 'discarded'
        # Optional: log discard
        self.env['fsm.execution.log'].create({
            'instance_id': self.id,
            'event_name': (json.loads(pending.event_payload or '{}') or {}).get('name', 'N/A'),
            'from_state': self.current_state,
            'to_state': self.current_state,
            'input_snapshot': pending.event_payload or '{}',
            'output_snapshot': json.dumps({'discarded': True}),
            'status': 'intercepted',
            'log_type': 'warning',
        })

