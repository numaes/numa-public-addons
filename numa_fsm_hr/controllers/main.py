import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WorkflowController(http.Controller):

    @http.route('/crm_workflow/<string:wkf_id>', auth='public', type='http', csrf=False, website=True)
    def crm_workflow(self, wkf_id, **kwargs):
        wkf_model = request.env['crm.workflow'].sudo()

        if not wkf_id:
            return request.render('numa_fsm.error_page', {
                'message': 'You should identify the workflow you want to see'
            })

        wkf_id = wkf_id.replace('_', '-')
        wkf = wkf_model.search([('name', '=', wkf_id)], limit=1)
        if not wkf:
            return request.render('numa_fsm.error_page', {
                'message': 'Workflow ID not found'
            })

        if not wkf.current_page:
            return request.render('numa_fsm.error_page', {
                'message': 'Nothing to show for this workflow'
            })

        return request.render('numa_fsm.page_template', dict(
            page=wkf.current_page,
            processed_body=wkf.render_dynamic_html(
                wkf.current_page.body,
                page=wkf.current_page
            ),
            **kwargs
        ))

    @http.route('/crm_workflow/<string:wkf_id>/event/<string:event_id>', auth='public', type='http',
                csrf=False, website=True)
    def crm_workflow_event(self, wkf_id, event_id, **kwargs):
        wkf_model = request.env['crm.workflow'].sudo()

        if not wkf_id or not event_id:
            return request.render('numa_fsm.error_on_id', {
                'message': 'You should identify the workflow and the event you want to process'
            })

        wkf_id = wkf_id.replace('_', '-')
        wkf = wkf_model.search([('name', '=', wkf_id)], limit=1)
        if not wkf:
            return request.render('numa_fsm.error_page', {
                'message': 'Workflow ID not found'
            })

        wkf.consume_event(dict(name=event_id, **kwargs))

        if not wkf.current_page:
            return request.render('numa_fsm.error_page', {
                'message': 'Nothing to show for this workflow'
            })

        return request.render('numa_fsm.page_template', dict(
            page=wkf.current_page,
            processed_body=wkf.render_dynamic_html(
                wkf.current_page.body,
                page=wkf.current_page
            ),
        ))

    @http.route('/crm_workflow/<string:wkf_id>/json_event/<string:event_id>', auth='public', type='http',
                csrf=False, website=True)
    def crm_workflow_json_event(self, wkf_id, event_id, **kwargs):
        wkf_model = request.env['crm.workflow'].sudo()

        if not wkf_id or not event_id:
            return request.render('fsm_crm.error_on_id', {
                'message': 'You should identify the workflow and the event you want to process'
            })

        wkf_id = wkf_id.replace('_', '-')
        wkf = wkf_model.search([('name', '=', wkf_id)], limit=1)
        if not wkf:
            return request.render('numa_fsm.error_page', {
                'message': 'Workflow ID not found'
            })

        parameters = request.jsonrequest
        parameters.update(kwargs)
        wkf.consume_event(dict(name=event_id, **parameters))

        if not wkf.current_page:
            return request.render('numa_fsm.error_page', {
                'message': 'Nothing to show for this workflow'
            })

        return request.render('numa_fsm.page_template', dict(
            page=wkf.current_page,
            processed_body=wkf.render_dynamic_html(
                wkf.current_page.body,
                page=wkf.current_page
            ),
        ))

    @http.route('/crm_workflow/<string:wkf_id>/post', auth='public', type='http',
                methods=['post', 'update'], csrf=False, website=True)
    def crm_workflow_post(self, wkf_id, **kwargs):
        wkf_model = request.env['crm.workflow'].sudo()

        wkf_id = wkf_id.replace('_', '-')
        if not wkf_id:
            return request.render('numa_fsm.error_page', {
                'message': 'You should identify the workflow you want to process'
            })

        wkf = wkf_model.search([('name', '=', wkf_id)], limit=1)
        if not wkf:
            return request.render('numa_fsm.error_page', {
                'message': 'Workflow ID not found'
            })

        wkf.consume_event(dict(name='post', **kwargs))

        if not wkf.current_page:
            return request.render('numa_fsm.error_page', {
                'message': 'Nothing to show for this workflow'
            })

        return request.render('numa_fsm.page_template', dict(
            page=wkf.current_page,
            processed_body=wkf.render_dynamic_html(
                wkf.current_page.body,
                page=wkf.current_page
            ),
        ))

