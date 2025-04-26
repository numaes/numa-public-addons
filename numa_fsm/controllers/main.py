import logging

from odoo import http
import json

_logger = logging.getLogger(__name__)

from odoo.addons.website.controllers import form
from odoo.http import request


class WebsiteForm(form.WebsiteForm):
    """
    Extension of the WebsiteForm controller to handle form submissions for the FSM module.
    This class overrides the _handle_website_form method to process form inputs for FSM instances.
    """

    def _handle_website_form(self, model_name, **kwargs):
        """
        Handle form submissions from the website.

        This method overrides the standard Odoo WebsiteForm controller to handle
        form submissions specifically for the FSM module. It creates form input
        records when the model is 'fsm.form_input'.

        Args:
            model_name (str): The model to which the form data should be submitted
            **kwargs: Form field values

        Returns:
            str: JSON response with the created record ID or standard response
        """
        if model_name == 'fsm.form_input':
            form_input_model = request.env['fsm.form_input'].sudo()
            form_input = form_input_model.create(kwargs)
            return json.dumps({'id': form_input.id})
        else:
            return super()._handle_website_form(model_name, **kwargs)


class FSMController(http.Controller):
    """
    Controller for handling FSM page template requests.
    This class provides routes for displaying FSM page templates to users.
    """
    @http.route('/fsm_page_template/<int:page_id>', auth='public', type='http',
                csrf=False, website=True)
    def fsm_page_template(self, page_id, **kwargs):
        """
        Route handler for displaying FSM page templates.

        Args:
            page_id (int): ID of the page template to display
            **kwargs: Additional parameters passed to the template

        Returns:
            http response: Rendered template or error page
        """
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
