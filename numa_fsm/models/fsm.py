import logging
import uuid
from datetime import date, datetime, timedelta

import json
import base64

import odoo
from odoo import api, _, exceptions
from odoo import models, fields
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval, wrap_module

import pprint

_logger = logging.getLogger(__name__)


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


class FSMTimer(models.Model):
    _name = 'fsm.timer'
    _description = 'FSM Timer'
    _order = 'trigger_at desc'
    _rec_name = 'name'

    name = fields.Char('Event name', required=True)
    json_event = fields.Text('JSON Event')

    fsm_instance_id = fields.Many2one('fsm.instance', 'Target FSM instance')
    trigger_at = fields.Datetime('Trigger at')

    @api.model
    def schedule_timers(self):
        now = fields.Datetime.now()

        triggered_timers = self.search([('trigger_at', '<', now)])
        for timer in triggered_timers:
            timer.fsm_instance_id.send_event(json.loads(timer.json_event))
        if triggered_timers:
            triggered_timers.unlink()


class FSMEventEntry(models.Model):
    _name = 'fsm.event_entry'
    _description = 'FSM Event'
    _order = 'sequence'

    instance_id = fields.Many2one('fsm.instance', 'Target instance', required=True)
    retained_instance_id = fields.Many2one('fsm.instance', 'Retained instance')
    name = fields.Char('Name', required=True)
    json_definition = fields.Text('JSON Definition')
    sequence = fields.Integer('Sequence')


class FSMInstance(models.Model):
    _name = 'fsm.instance'
    _description = 'FSM Instance'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

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

    @api.model_create_single
    def create(self, vals):
        fsm_instance = super().create(vals)

        if not self.env.get('no_start'):
            fsm_instance.start()

        return fsm_instance

    def prepare_env(self):
        self.ensure_one()
        env = json.loads(self.json_instance_values or '{}')
        return env or {}

    def flush_env(self, env):
        self.ensure_one()
        self.json_instance_values = json.dumps(env)

    def get_globals(self):
        self.ensure_one()

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
            fsm_instance=self,
            fsm_definition=self.definition_id,
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

        global_objects = self.get_globals()

        fsm_instance = self

        if fsm_instance.state != 'running':
            # Nothing to do if it is not running
            return

        try:
            for target_state in [fsm_instance.current_state, 'all']:
                current_fsmd = fsm_instance.definition_id
                while current_fsmd:
                    compiled_definition = json.loads(current_fsmd.json_compiled_definition)
                    if target_state in compiled_definition['states']:
                        state_definition = compiled_definition['states'][target_state]
                        if event['name'] in state_definition:
                            event_definition = state_definition[event['name']]
                            if event_definition.get('pospone', False):
                                self.retain_event(event)
                            else:
                                env = fsm_instance.prepare_env()
                                fsm_instance.before_event_process(event, env)
                                env['event'] = event
                                code_definition = event_definition['code']
                                exec(code_definition, global_objects, env)
                                del env['event']
                                self.flush_env(env)
                                fsm_instance.after_event_process(event, env)
                            return env
                    current_fsmd = current_fsmd.parent_id

        except Exception as e:
            _logger.exception(e, exc_info=True)
            raise exceptions.UserError(
                f"Processing event {event['name']}, "
                f"instance {fsm_instance.display_name}, "
                f"on state {fsm_instance.current_state}\n"
                f"Unexpected exception {e}"
            )

    def process_events(self):
        for fsm_instance in self:
            no_more_events = False
            while not no_more_events:
                # acquire lock
                self.env.cr.execute(f'SELECT id FROM fsm_instance WHERE id = {fsm_instance.id} FOR UPDATE')

                if fsm_instance.state != 'running':
                    self.env.cr.commit()
                    no_more_events = True
                    continue

                try:
                    env = fsm_instance.prepare_env()
                    # Process next event
                    if fsm_instance.events_queue:
                        event_entry = fsm_instance.events_queue[0]
                        event = json.loads(event_entry.json_definition)
                        env = fsm_instance.process_event(event, env)
                        event_entry.unlink()
                        fsm_instance.flush_env(env)
                        fsm_instance.flush()
                        if env and env.get('fsm_instance_ended', False):
                            break
                    else:
                        no_more_events = True
                except Exception as e:
                    _logger.exception(e, exc_info=True)
                    self.env.cr.rollback()
                    fsm_instance.message_post(
                        subject='Unexpected exception',
                        body=f'<pre>{pprint.pformat(e)}</pre>',
                    )
                    _logger.info(f'FSM Instance of FSM {fsm_instance.definition_id.display_name}, '
                                 f'unexpected exception: {e}')
                self.env.cr.commit()

    def send_event(self, event):
        event_model = self.env['fsm.event_entry']

        for fsm_instance in self:
            if fsm_instance.state != 'running':
                _logger.info(f'Discarded event to a non running FSM instance {fsm_instance.display_name}')
                continue

            fsm_instance.on_send_event(event)
            last_event = event_model.search([('instance_id', '=', fsm_instance.id)], limit=1, order='sequence desc')
            fsm_instance.events_queue = [(0, 0, {
                'name': event['name'],
                'json_definition': json.dumps(event),
                'sequence': last_event.sequence + 1 if last_event else 1,
            })]

            def trigger():
                fsm_instance.process_events()

            self.env.cr.postcommit.add(trigger)

    def start(self):
        self.ensure_one()

        fsm_instance = self
        if fsm_instance.state != 'init':
            _logger.info(f'You cannot not start a not initialized FSM Instance! ({fsm_instance.display_name}')
            return

        env = {}

        global_objects = self.get_globals()

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

        except Exception as e:
            _logger.exception(e, exc_info=True)
            raise exceptions.UserError(
                f'''Starting FSM {fsmd.display_name}, on instance {fsm_instance.display_name}\n
                Unexpected exception {e}'''
            )

        fsm_instance.state = 'running'

    def end(self):
        for fsm_instance in self:
            if fsm_instance.state != 'running':
                raise exceptions.UserError(
                    f'You cannot not end a non running FSM Instance! ({fsm_instance.display_name}'
                )

            fsm_instance.stop_all_timers()
            fsm_instance.state = 'ended'
            if fsm_instance.logging:
                fsm_instance.message_post(
                    subject=f"Ending FSM",
                    body=f'<i>Ending FSM instance {fsm_instance.display_name}</i>'
                )
                _logger.info(f"Ending FSM instance {fsm_instance.display_name}")
                fsm_instance.flush()

    def start_logging(self):
        for instance in self:
            instance.logging = True

    def stop_logging(self):
        for instance in self:
            instance.logging = False

    def on_send_event(self, event):
        for fsm_instance in self:
            if fsm_instance.logging:
                fsm_instance.message_post(
                    subject=f"Sending event",
                    body=f"<i>Sending event: {event['name']} to instance {fsm_instance.display_name}</i><br/>"
                         f"<b>Event:</b><br/>"
                         f"<pre>{pprint.pformat(event)}</pre><br/>"
                )
                _logger.info(f"Sending event: {event['name']} to instance {fsm_instance.display_name}. "
                             f"Event: {event}")
                fsm_instance.flush()

    def before_event_process(self, event, env):
        for fsm_instance in self:
            if fsm_instance.logging:
                fsm_instance.message_post(
                    subject=f"Before event process",
                    body=f"Before event process. Event {event['name']} for instance {fsm_instance.display_name}</i><br/>"
                         f"<b>Event:</b><br/>"
                         f"<pre>{pprint.pformat(event)}</pre><br/>"
                )
                _logger.info(f"Before event process: {event['name']} to instance {fsm_instance.display_name}. "
                             f"Event: {event}")
                fsm_instance.flush()

    def after_event_process(self, event, env):
        for fsm_instance in self:
            if fsm_instance.logging:
                fsm_instance.message_post(
                    subject=f"After event process",
                    body=f'<i>After event process for instance {fsm_instance.display_name}</i>.<br/>'
                         f'<b>Environment:</b><br/>'
                         f'<pre>{pprint.pformat(env)}</pre><br/>'
                )
                _logger.info(f"After event process: {event['name']} for instance {fsm_instance.display_name}. "
                             f"Environment: {env}")
                fsm_instance.flush()

    def recover_retained_events(self):
        for fsm_instance in self:
            for event_entry in fsm_instance.retained_events:
                event = json.loads(event_entry.json_definition)
                fsm_instance.send_event(event)
                event_entry.unlink()

    def retain_event(self, event):
        event_model = self.env['fsm.event_entry']

        self.ensure_one()

        fsm_instance = self
        if fsm_instance.logging:
            fsm_instance.message_post(
                subject=f"Posponing event",
                body=f"<i>Posponing event {pprint.pformat(event)}, for instance {fsm_instance.display_name}</i>"
            )
            _logger.info(f"Posponing event {event}, for instance {fsm_instance.display_name}")

        last_event = event_model.search([('retained_instance_id', '=', fsm_instance.id)],
                                        limit=1, order='sequence desc')
        fsm_instance.retained_events = [(0, 0, {
            'name': event['name'],
            'json_definition': json.dumps(event),
            'sequence': last_event.sequence + 1 if last_event else 1,
        })]

    def change_state(self, new_state):
        self.ensure_one()

        fsm_instance = self
        if fsm_instance.logging:
            fsm_instance.message_post(
                subject=f"Changing state",
                body=f"<i>Changing state from {fsm_instance.current_state} "
                     f"to: {new_state} for instance {fsm_instance.display_name}</i>"
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
                fsm_instance.message_post(
                    subject=f"Sending timer",
                    body=f"<i>Sending timer {event} "
                         f"for: {delay}, trigger at: {at} for instance {fsm_instance.display_name}</i>"
                )
                _logger.info(f"Sending timer {event} "
                             f"for: {delay}, trigger at: {at} for instance {fsm_instance.display_name}")

            timer_model.create(dict(
                name=event['name'],
                json_event=json.dumps(event),
                fsm_instance_id=self.id,
                trigger_at=at,
            ))

    def stop_timer(self, event_name):
        timer_model = self.env['fsm.timer']

        timers = timer_model.search([('name', '=', event_name), ('fsm_instance_id', '=', self.id)])
        if timers:
            timers.unlink()

        for fsm_instance in self:
            if fsm_instance.logging:
                fsm_instance.message_post(
                    subject=f"Stopping timer",
                    body=f"<i>Stopping timer {event_name} "
                         f"for instance {fsm_instance.display_name}</i>"
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
                fsm_instance.message_post(
                    subject=f"Stopping all timers",
                    body=f"<i>Stopping all timers "
                         f"for instance {fsm_instance.display_name}</i>"
                )
                _logger.info(f"Stopping all timers "
                             f"for instance {fsm_instance.display_name}")



