import logging
import uuid
from datetime import date, datetime, timedelta

import json
import lxml
import re

import odoo
from odoo import api, _, exceptions
from odoo import models, fields
from odoo.exceptions import UserError

import pprint

_logger = logging.getLogger(__name__)


class FSMInstance(models.Model):
    _inherit = 'fsm.instance'

    employee_id = fields.Many2one('hr.employee', 'Employee')

    def send_mail_to_employee(self, mail_template_name, subject=None):
        self.ensure_one()

        mail_template = self.definition_id.mail_templates.filtered(lambda x: x.name == mail_template_name)
        if mail_template and len(mail_template) == 1 and self.partner_id:
            mcm_model = self.env['mail.compose.message']
            mcm = mcm_model.create(dict(
                subject=subject if subject else _('Automatic mail'),
                body=self.render_dynamic_html(f'<div>{mail_template.body_view_html}</div>'),
                attachment_ids=mail_template.attachment_ids.ids,
                composition_mode='comment',
                model='hr.employee',
                res_id=self.employee_id.id if self.employee_id else False,
                use_active_domain=False,
                no_auto_thread=False,
                auto_delete_message=False,
            ))
            mcm.send_mail()
        elif len(mail_template) > 1:
            self.message_post(
                subject='Execution error',
                body=_("<span>Error trying to send mail template with ambiguous name %s</span>") % mail_template_name,
            )
        else:
            self.message_post(
                subject='Execution error',
                body=_("<span>Error trying to send mail template with invalid name %s or no co</span>") %
                     mail_template_name,
            )
