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
    _depends = {'fsm.instance': 'fsm_instance_id'}

    employee_id = fields.Many2one('hr.employee', 'Employee')
    partner_id = fields.Many2one('res.partner', 'Contact',
                                 related='employee_id.partner_id')
    reply_to = fields.Char('Reply_to')

    manual_operation_needed = fields.Boolean('Manual operation required?')

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

        self.action_send_template_mail(
            self.employee_id,
            mail_template_name,
            subject or 'N/A'
        )

    def send_mail_to_contact(self, mail_template_name, subject=None):
        self.ensure_one()

        self.action_send_template_mail(
            self.partner_id,
            mail_template_name,
            subject or 'N/A'
        )

    def action_confirm_manual_operation(self):
        for instance in self:
            if instance.manual_operation_needed:
                instance.manual_operation_needed = False
            instance.consume_event(dict(name='manualOperationCheck'))


