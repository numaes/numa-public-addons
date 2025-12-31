from odoo import models, fields, api
from datetime import timedelta

class MrpWorkcenter(models.Model):
    _inherit = ['mrp.workcenter', 'numa.planning.resource']

    # Map capacity and name
    capacity = fields.Float(related='capacity', inherited=True)
    name = fields.Char(related='name', inherited=True)

    @api.constrains('resource_calendar_id', 'capacity', 'name')
    def _check_resource_calendar_id_numa(self):
        for wc in self:
            start = fields.Datetime.now()
            end = start + timedelta(days=90)
            wc.action_pln_generate_availability(start, end)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            start = fields.Datetime.now()
            end = start + timedelta(days=90)
            record.action_pln_generate_availability(start, end)
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ['resource_calendar_id', 'capacity', 'name']):
            for record in self:
                start = fields.Datetime.now()
                end = start + timedelta(days=90)
                record.action_pln_generate_availability(start, end)
        return res
