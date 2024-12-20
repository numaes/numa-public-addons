import logging

from odoo import http
import json

_logger = logging.getLogger(__name__)

from odoo.addons.website.controllers import form
from odoo.http import request


class WebsiteForm(form.WebsiteForm):

    # Check and insert values from the form on the model <model> + validation phone fields
    def _handle_website_form(self, model_name, **kwargs):
        if model_name == 'fsm.form_input':
            form_input_model = request.env['fsm.form_input'].sudo()
            form_input = form_input_model.create(kwargs)
            return json.dumps({'id': form_input.id})
        else:
            return super()._handle_website_form(model_name, **kwargs)


class FSMController(http.Controller):
    @http.route('/fsm_page_template/<int:page_id>', auth='public', type='http',
                csrf=False, website=True)
    def fsm_page_template(self, page_id, **kwargs):
        page_template_model = request.env['fsm.wf.page_template'].sudo()

        page = page_template_model.browse(page_id).exists()
        if not page:
            return request.render('numa_fsm.error_page', {
                'message': 'Nothing to show for this workflow'
            })

        return request.render('numa_fsm.page_edit_template', dict(
            page=page,
            **kwargs
        ))

