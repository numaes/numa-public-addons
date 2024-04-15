import logging
import uuid
from datetime import date, datetime, timedelta

import json
import lxml
import re
from jinja2 import Environment
import base64

import odoo
from odoo import api, _, exceptions
from odoo import models, fields, tools
from odoo.exceptions import UserError
from .miniqweb import render

import pprint

_logger = logging.getLogger(__name__)

# Syntax of the data URL Scheme: https://tools.ietf.org/html/rfc2397#section-3
# Used to find inline images
image_re = re.compile(r"data:(image/[A-Za-z]+);base64,(.*)")


class MailMessage(models.Model):
    _inherit = 'mail.message'

    body = fields.Html(sanitize=False, sanitize_tags=False, sanitize_style=False)


class FSMDefinition(models.Model):
    _inherit = 'fsm.definition'

    pages = fields.Many2many('fsm.wf.page_template', 'wf_page_templates_rel', string='Pages')
    mail_templates = fields.Many2many('fsm.wf.mail_template', 'wf_mail_templates_rel', string='Mail templates')


class FSMInstance(models.Model):
    _inherit = 'fsm.instance'

    partner_id = fields.Many2one('res.partner', 'Contact')

    current_page = fields.Many2one('fsm.wf.page_template', 'Current Page template')
    manual_operation_needed = fields.Boolean('Manual operation required?')
    reply_to = fields.Char('Reply_to')

    def set_page(self, page_name):
        self.ensure_one()

        target_page = self.definition_id.pages.filtered(lambda x: x.name == page_name)

        if not target_page:
            raise exceptions.UserError(_('Invalid current page to set: %s') % page_name)

        if len(target_page) > 1:
            raise exceptions.UserError(_('Ambigous page to set as current: %s') % page_name)

        self.current_page = target_page

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

    def render_dynamic_html(self, template, **params):
        templater = Environment(
            variable_start_string="{{",
            variable_end_string="}}",
        )

        processed_body = template
        while processed_body.find("{{") >= 0:
            # Inject data into the view and replace our template tags with the data
            jinja_template = templater.from_string(template)
            processed_body = jinja_template.render(
                instance=self,
                **params
            )

        return render(processed_body, self, **dict(instance=self, **params))

    def send_mail_to_partner(self, mail_template_name, subject=None):
        self.ensure_one()

        mail_template = self.definition_id.mail_templates.filtered(lambda x: x.name == mail_template_name)
        if mail_template and len(mail_template) == 1 and self.partner_id:
            body_html = self.render_dynamic_html(f'<div>{mail_template.body_view_html}</div>')

            mcm_model = self.env['mail.compose.message']
            mcm = mcm_model.create(dict(
                reply_to=self.reply_to,
                subject=subject if subject else mail_template.name,
                body=body_html,
                attachment_ids=mail_template.attachment_ids.ids,
                composition_mode='comment',
                model='res.partner',
                res_id=self.partner_id.id,
                use_active_domain=False,
                no_auto_thread=False,
                partner_ids=[],
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
                body=_("<span>Error trying to send mail template with invalid name %s or no partner</span>") % mail_template_name,
            )

    def action_confirm_manual_operation(self):
        for instance in self:
            if instance.manual_operation_needed:
                instance.manual_operation_needed = False
                instance.consume_event(dict(name='manualOperationCheck'))


class WorkFlowMailTemplate(models.Model):
    _name = 'fsm.wf.mail_template'
    _description = 'FSM WorkFlow Mail template'

    _inherit = ['mail.render.mixin']

    @api.model
    def default_body_view_id(self):
        view_model = self.env['ir.ui.view']

        return view_model.create(dict(
                type='qweb',
                name='Workflow Mail Template - ' + str(uuid.uuid4()),
                arch='<template>\n</template>',
        ))

    name = fields.Char('Name', required=True)
    subject = fields.Char('Subject')
    template_id = fields.Many2one('mail.template', 'Mail template', required=True)
    body_view_arch = fields.Html('Body', sanitize=False, translate=False)
    body_view_html = fields.Html('Body HTML', sanitize=False)

    attachment_ids = fields.Many2many(
        'ir.attachment', 'wfmt_ir_attachments_rel',
        'wfmt_id', 'attachment_id',
        string='Attachments'
    )

    def send_mail(self, res_id, force_send=False, raise_exception=False, email_values=None, notif_layout=False):

        values = email_values.copy() if email_values else {}
        base_attachment_ids = values.get('attachment_ids', [])

        for template in self:
            template_attachment_ids = base_attachment_ids + template.attachment_ids.ids
            template_values = email_values.copy() if email_values else {}
            template_values['attachment_ids'] = template_attachment_ids
            template.template_id.send_mail(
                res_id,
                force_send=force_send,
                raise_exception=raise_exception,
                email_values=template_values,
                notif_layout=notif_layout
            )

    def open_mail_template(self):
        self.ensure_one()

        compose_form = self.env.ref('numa_fsm_crm.mail_template_html_edit')

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
            "url": '/crm_page_template/%d' % self.id,
            "target": "new"
        }
