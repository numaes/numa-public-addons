# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website_form.controllers.main import WebsiteForm

class FSMFormController(http.Controller):

    @http.route('/fsm/form/<string:instance_uuid>', type='http', auth='public', website=True)
    def render_fsm_form(self, instance_uuid, **kwargs):
        """
        Renders a website_form, injecting the FSM instance UUID into the form's action
        to ensure the submission is linked back to the correct FSM instance.
        """
        instance = request.env['fsm.instance'].sudo().search([('name', '=', instance_uuid)], limit=1)
        if not instance:
            return request.not_found()

        # Assuming the form is linked on the FSM definition
        form = instance.definition_id.website_form_id
        if not form:
            return request.make_response("This FSM instance does not have an associated form.", status=500)

        # Dynamically build the form action URL to include our instance identifier
        form_action = f"/website/form/{form.model_id.model}?instance_uuid={instance_uuid}"
        
        return request.render("website_form.form", {
            'main_object': form,
            'website_form_action': form_action,
        })

class FSMWebsiteForm(WebsiteForm):

    @http.route('/website/form/<string:model_name>', type='http', auth="public", methods=['POST'], website=True, csrf=False)
    def website_form(self, model_name, **kwargs):
        """
        Intercepts the standard website_form submission to handle FSM-related forms.
        If an 'instance_uuid' is present, it processes the form data, creates an
        fsm.form_input record, and triggers an event on the corresponding FSM instance.
        Otherwise, it falls back to the original method.
        """
        instance_uuid = kwargs.get('instance_uuid')
        
        if instance_uuid and model_name == 'fsm.form_input':
            try:
                instance = request.env['fsm.instance'].sudo().search([('name', '=', instance_uuid)], limit=1)
                if not instance:
                    # Fallback if instance is not found
                    return super(FSMWebsiteForm, self).website_form(model_name, **kwargs)

                # Create the fsm.form_input record using its custom create method
                form_input = request.env['fsm.form_input'].create(kwargs)

                # Trigger the event on the FSM instance
                instance.send_event({
                    'name': 'form_submitted',
                    'form_input_id': form_input.id,
                    'form_data': form_input.json_data,
                })

                # Redirect to a thank you page
                return request.render("website.contactus_thanks")
            except Exception as e:
                _logger.error("Error processing FSM form submission: %s", e)
                return request.make_response("An error occurred while processing your form.", status=500)

        # If it's not our specific case, call the original method
        return super(FSMWebsiteForm, self).website_form(model_name, **kwargs)
