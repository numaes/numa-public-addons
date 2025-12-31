from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = ['res.partner', 'numa.planning.resource']

    # capacity is already defined in numa.planning.resource
    # We can add a default or logic if needed, but the requirement says 
    # it could represent "Simultaneous Orders" or "Credit Limit".
    # Since it's a generic abstraction, we leave the field from numa.planning.resource.

    def action_pln_generate_availability(self, start_date, end_date):
        """
        Overrides or extends to use Partner's specific delivery calendars if available.
        Standard Odoo Partners don't always have a resource_calendar_id.
        """
        # If partner has no calendar, we might want to use a global one or 24/7.
        # For now, let's try to use the logic in numa.planning.resource if we can
        # provide it with a calendar.
        
        # Check if numa.planning.resource expects a specific field for calendar on the partner.
        # In numa_planning.py:
        # if self.user_id and self.user_id.employee_id:
        #     calendar = self.user_id.employee_id.resource_calendar_id
        # elif self.workcenter_id:
        #     calendar = self.workcenter_id.resource_calendar_id

        # We can add a calendar field to res.partner for Purchasing purposes if not present.
        return super().action_pln_generate_availability(start_date, end_date)
