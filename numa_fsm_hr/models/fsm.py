import logging
import re
from odoo import _, exceptions
from odoo import models, fields

_logger = logging.getLogger(__name__)

# Syntax of the data URL Scheme: https://tools.ietf.org/html/rfc2397#section-3
# Used to find inline images
image_re = re.compile(r"data:(image/[A-Za-z]+);base64,(.*)")


class HRWorkflow(models.Model):
    _name = 'hr.workflow'
    _description = 'HR Workflow'
    _order = 'create_date desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'fsm.instance': 'fsm_instance_id'}

    fsm_instance_id = fields.Many2one('fsm.instance', 'FSM instance',
                                      required=True, ondelete='cascade')

    employee_id = fields.Many2one('hr.employee', 'Employee')
    partner_id = fields.Many2one('res.partner', 'Contact',
                                 related='employee_id.partner_id')
    reply_to = fields.Char('Reply_to')

    manual_operation_needed = fields.Boolean('Manual operation required?')

    # Repair inheritance limitations

    def set_page(self, page_name):
        for workflow in self:
            workflow.fsm_instance_id.set_page(page_name)

    def prepare_env(self):
        self.ensure_one()
        return self.fsm_instance_id.prepare_env()

    def flush_env(self, env):
        for workflow in self:
            workflow.fsm_instance_id.flush_env(env)

    def get_globals(self):
        self.ensure_one()
        return self.fsm_instance_id.get_globals()

    def consume_event(self, event):
        for workflow in self:
            workflow.fsm_instance_id.consume_event(event)

    def process_event(self, event, env):
        for workflow in self:
            workflow.fsm_instance_id.process_event(event, env)

    def process_events(self):
        for workflow in self:
            workflow.fsm_instance_id.process_events()

    def send_event(self, event):
        for workflow in self:
            workflow.fsm_instance_id.send_event(event)

    def start(self):
        for workflow in self:
            workflow.fsm_instance_id.start()

    def end(self):
        for workflow in self:
            workflow.fsm_instance_id.end()

    def start_logging(self):
        for workflow in self:
            workflow.fsm_instance_id.start_logging()

    def stop_logging(self):
        for workflow in self:
            workflow.fsm_instance_id.stop_logging()

    def on_send_event(self, event):
        for workflow in self:
            workflow.fsm_instance_id.on_send_event(event)

    def before_event_process(self, event, env):
        for workflow in self:
            workflow.fsm_instance_id.before_event_process(event, env)

    def after_event_process(self, event, env):
        for workflow in self:
            workflow.fsm_instance_id.after_event_process(event, env)

    def recover_retained_events(self):
        for workflow in self:
            workflow.fsm_instance_id.recover_retained_events()

    def retain_event(self, event):
        for workflow in self:
            workflow.fsm_instance_id.retain_event()

    def change_state(self, new_state):
        for workflow in self:
            workflow.fsm_instance_id.change_state(new_state)

    def start_timer(self, event, delay=None, at=None):
        for workflow in self:
            workflow.fsm_instance_id.start_timer(event, delay, at)

    def stop_timer(self, event_name):
        for workflow in self:
            workflow.fsm_instance_id.stop_timer(event_name)

    def stop_all_timers(self):
        for workflow in self:
            workflow.fsm_instance_id.stop_all_timers()

    def render_dynamic_html(self, template, **params):
        self.ensure_one()
        return self.fsm_instance_id.render_dynamic_html(template, **params)

    # End of reflected methods

    def workflow_local_link(self):
        self.ensure_one()

        return f'/crm_workflow/{self.name.replace("-", "_")}'

    def workflow_link(self):
        site_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        if not site_url:
            raise exceptions.UserError(
                _('"web.base.url" system parameter not set! Please check it!')
            )

        return site_url + self.workflow_local_link()

    def send_mail_to_employee(self, mail_template_name, subject=None):
        self.ensure_one()

        self.fsm_instance_id.action_send_template_mail(self, self.employee_id, mail_template_name, subject)

    def send_mail_to_contact(self, mail_template_name, subject=None):
        self.ensure_one()

        self.fsm_instance_id.action_send_template_mail(self, self.partner_id, mail_template_name, subject)

    def action_confirm_manual_operation(self):
        for instance in self:
            if instance.manual_operation_needed:
                instance.manual_operation_needed = False
            instance.consume_event(dict(name='manualOperationCheck'))


