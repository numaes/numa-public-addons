# -*- coding: utf-8 -*-
from odoo import models, fields, api

class CrmBot(models.Model):
    """
    CRM Bot model that extends fsm.definition.
    
    Similar to conversation.bot, this model represents a bot/FSM definition
    that can be assigned to CRM leads to automate lead processing workflows.
    """
    _name = 'crm.bot'
    _description = 'CRM Bot (FSM Definition)'
    _depend_models = {'fsm.definition': 'fsm_definition_id'}
    
    @api.model_create_multi
    def create(self, vals_list):
        """Set default type to 'crm_bot' if not provided."""
        for vals in vals_list:
            if 'type' not in vals:
                vals['type'] = 'crm_bot'
        return super().create(vals_list)

    def _get_thread_with_access(self, thread_id, **kwargs):
        """
        Delegate access check to the underlying fsm.definition to avoid MRO issues
        with portal's mail.thread override.
        """
        # We browse the base model with the same ID because they share the ID space (numa_poly)
        mode = kwargs.get('mode') or 'read'
        return self.env['fsm.definition'].browse(thread_id)._get_thread_with_access(thread_id, mode=mode, **kwargs)
