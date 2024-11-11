import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


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

