"""
Identity Mapping Table for Synchronization

This model provides high-performance mapping between local IDs and remote IDs
for different models and nodes in a distributed synchronization system.
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class NumaSynchMap(models.Model):
    """
    Identity Mapping Table
    
    Translates Local IDs to Remote IDs for synchronization purposes.
    This table must be high-performance with proper indexing.
    """
    _name = 'numa.synch.map'
    _description = 'Synchronization Identity Mapping'
    _rec_name = 'display_name'
    _order = 'model_name, local_id, node_token'

    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        index=True,
        help='The Odoo model this mapping refers to'
    )
    
    model_name = fields.Char(
        string='Model Name',
        related='model_id.model',
        store=True,
        index=True,
        readonly=True,
        help='Technical name of the model (e.g., res.partner)'
    )
    
    local_id = fields.Integer(
        string='Local ID',
        required=True,
        index=True,
        help='The ID of the record in this local database'
    )
    
    remote_id = fields.Integer(
        string='Remote ID',
        required=True,
        index=True,
        help='The ID of the record in the remote database'
    )
    
    node_token = fields.Char(
        string='Node Token',
        required=True,
        index=True,
        help="Identifier of the remote node (Slave UUID or 'MASTER')"
    )
    
    last_sync_date = fields.Datetime(
        string='Last Sync Date',
        help='Timestamp of the last synchronization for this mapping'
    )
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=False
    )

    _sql_constraints = [
        (
            'unique_mapping',
            'UNIQUE(model_id, local_id, node_token)',
            'A mapping for this model, local ID, and node token already exists!'
        ),
    ]

    @api.depends('model_name', 'local_id', 'remote_id', 'node_token')
    def _compute_display_name(self):
        """Compute display name for the mapping record"""
        for record in self:
            record.display_name = (
                f"{record.model_name or ''} "
                f"[Local: {record.local_id} -> Remote: {record.remote_id}] "
                f"({record.node_token or ''})"
            )

    @api.model
    def get_remote_id(self, model_name, local_id, node_token):
        """
        Get the remote ID for a given local ID and node token.
        
        :param str model_name: Technical name of the model (e.g., 'res.partner')
        :param int local_id: Local record ID
        :param str node_token: Node identifier (Slave UUID or 'MASTER')
        :return: Remote ID (integer) or False if not found
        :rtype: int or False
        """
        if not model_name or not local_id or not node_token:
            return False
        
        mapping = self.search([
            ('model_name', '=', model_name),
            ('local_id', '=', local_id),
            ('node_token', '=', node_token)
        ], limit=1)
        
        return mapping.remote_id if mapping else False

    @api.model
    def get_local_id(self, model_name, remote_id, node_token):
        """
        Get the local ID for a given remote ID and node token.
        
        :param str model_name: Technical name of the model (e.g., 'res.partner')
        :param int remote_id: Remote record ID
        :param str node_token: Node identifier (Slave UUID or 'MASTER')
        :return: Local ID (integer) or False if not found
        :rtype: int or False
        """
        if not model_name or not remote_id or not node_token:
            return False
        
        mapping = self.search([
            ('model_name', '=', model_name),
            ('remote_id', '=', remote_id),
            ('node_token', '=', node_token)
        ], limit=1)
        
        return mapping.local_id if mapping else False

    @api.model
    def set_mapping(self, model_name, local_id, remote_id, node_token, last_sync_date=None):
        """
        Create or update a mapping between local and remote IDs.
        This method is idempotent.
        
        :param str model_name: Technical name of the model (e.g., 'res.partner')
        :param int local_id: Local record ID
        :param int remote_id: Remote record ID
        :param str node_token: Node identifier (Slave UUID or 'MASTER')
        :param datetime last_sync_date: Optional timestamp of synchronization
        :return: The mapping record (created or updated)
        :rtype: recordset
        """
        if not model_name or not local_id or not remote_id or not node_token:
            raise ValidationError(_(
                'All parameters (model_name, local_id, remote_id, node_token) '
                'are required to set a mapping.'
            ))
        
        # Get or create the ir.model record
        ir_model = self.env['ir.model'].search([
            ('model', '=', model_name)
        ], limit=1)
        
        if not ir_model:
            raise ValidationError(_(
                'Model %s does not exist in the system.'
            ) % model_name)
        
        # Search for existing mapping
        mapping = self.search([
            ('model_id', '=', ir_model.id),
            ('local_id', '=', local_id),
            ('node_token', '=', node_token)
        ], limit=1)
        
        # Prepare values
        values = {
            'model_id': ir_model.id,
            'local_id': local_id,
            'remote_id': remote_id,
            'node_token': node_token,
        }
        
        if last_sync_date:
            values['last_sync_date'] = last_sync_date
        
        # Create or update
        if mapping:
            mapping.write(values)
            return mapping
        else:
            return self.create(values)
