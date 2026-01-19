"""
Synchronization Rules Configuration

This model allows users to define what records to synchronize using
Odoo's domain widget for flexible filtering.
"""

from odoo import models, fields, api, _
from odoo.osv import expression
import ast
import logging

_logger = logging.getLogger(__name__)


class NumaSynchRule(models.Model):
    """
    Synchronization Rules
    
    Defines what records should be synchronized based on domain filters
    and synchronization direction.
    """
    _name = 'numa.synch.rule'
    _description = 'Synchronization Rule'
    _order = 'name'

    name = fields.Char(
        string='Name',
        required=True,
        help='Descriptive name for this synchronization rule'
    )
    
    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        help='The Odoo model this rule applies to'
    )
    
    model_name = fields.Char(
        string='Model Name',
        related='model_id.model',
        store=True,
        readonly=True,
        help='Technical name of the model (e.g., res.partner)'
    )
    
    domain_filter = fields.Char(
        string='Domain Filter',
        default='[]',
        help='Domain filter to select which records to synchronize. '
             'Use Odoo domain syntax (e.g., [("active", "=", True)])'
    )
    
    direction = fields.Selection(
        [
            ('bidirectional', 'Bidirectional'),
            ('outgoing', 'Outgoing Only'),
            ('incoming', 'Incoming Only'),
        ],
        string='Direction',
        default='bidirectional',
        required=True,
        help='Synchronization direction: '
             'Bidirectional (both ways), '
             'Outgoing (local to remote), or '
             'Incoming (remote to local)'
    )
    
    active = fields.Boolean(
        string='Active',
        default=True,
        help='If unchecked, this rule will be ignored during synchronization'
    )

    @api.model
    def get_delta_domain(self, last_sync_date):
        """
        Get the domain filter combined with write_date filter for delta synchronization.
        
        This method combines the user-defined domain_filter with a write_date
        condition to only get records modified since the last sync.
        
        :param datetime last_sync_date: Timestamp of last synchronization.
                                       If False, returns only the user domain.
        :return: Combined domain list
        :rtype: list
        """
        self.ensure_one()
        
        # Parse the user's domain filter
        try:
            user_domain = ast.literal_eval(self.domain_filter or '[]')
            if not isinstance(user_domain, list):
                user_domain = []
        except (ValueError, SyntaxError) as e:
            _logger.warning(
                'Invalid domain filter in rule %s (ID: %s): %s. Using empty domain.',
                self.name, self.id, str(e)
            )
            user_domain = []
        
        # If no last_sync_date, return only user domain
        if not last_sync_date:
            return user_domain
        
        # Combine user domain with write_date filter
        delta_domain = [('write_date', '>', last_sync_date)]
        
        # Use Odoo's expression.AND to combine domains
        combined_domain = expression.AND([user_domain, delta_domain])
        
        return combined_domain

    @api.constrains('domain_filter')
    def _check_domain_filter(self):
        """Validate that domain_filter is a valid Python list expression"""
        for record in self:
            if not record.domain_filter:
                continue
            
            try:
                domain = ast.literal_eval(record.domain_filter)
                if not isinstance(domain, list):
                    raise ValidationError(_(
                        'Domain filter must be a valid Python list expression. '
                        'Example: [("active", "=", True)]'
                    ))
            except (ValueError, SyntaxError) as e:
                raise ValidationError(_(
                    'Invalid domain filter syntax: %s\n'
                    'Domain must be a valid Python list expression. '
                    'Example: [("active", "=", True)]'
                ) % str(e))
