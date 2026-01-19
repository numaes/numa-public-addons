"""
AI-Assisted Synchronization Mapping Models

This module defines models for storing AI-generated transformation maps
and logging synchronization issues when AI cannot resolve schema mismatches.
"""

import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class NumaSynchAiMap(models.Model):
    """
    AI-Generated Transformation Map
    
    Stores mapping rules derived by AI to transform incoming payloads
    from non-standard schemas to Odoo model schemas.
    """
    _name = 'numa.synch.ai.map'
    _description = 'AI-Assisted Synchronization Mapping'
    _rec_name = 'display_name'
    _order = 'model_name, remote_token'

    remote_token = fields.Char(
        string='Remote Token',
        required=True,
        index=True,
        help='Identifier of the remote system (Slave token or external system ID)'
    )
    
    model_name = fields.Char(
        string='Model Name',
        required=True,
        index=True,
        help='Target Odoo model name (e.g., res.partner)'
    )
    
    mapping_json = fields.Text(
        string='Field Mapping (JSON)',
        required=True,
        help='JSON dictionary mapping remote field names to local field names. '
             'Format: {"remote_field": "local_field"}'
    )
    
    transformation_script = fields.Text(
        string='Transformation Script',
        help='Optional Python code snippet for complex transformations. '
             'This code will be executed in a safe context to transform field values.'
    )
    
    confidence_score = fields.Float(
        string='Confidence Score',
        digits=(5, 2),
        help='AI confidence score (0.0 to 1.0) for this mapping'
    )
    
    active = fields.Boolean(
        string='Active',
        default=True,
        help='If unchecked, this mapping will not be used'
    )
    
    create_date = fields.Datetime(
        string='Created On',
        readonly=True
    )
    
    create_uid = fields.Many2one(
        'res.users',
        string='Created By',
        readonly=True
    )
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    @api.depends('remote_token', 'model_name')
    def _compute_display_name(self):
        """Compute display name from remote token and model"""
        for record in self:
            record.display_name = f"{record.remote_token} → {record.model_name}"

    def toggle_active(self):
        """Toggle active status"""
        for record in self:
            record.active = not record.active
        return True

    @api.constrains('mapping_json')
    def _check_mapping_json(self):
        """Validate that mapping_json is valid JSON"""
        for record in self:
            if not record.mapping_json:
                continue
            try:
                mapping = json.loads(record.mapping_json)
                if not isinstance(mapping, dict):
                    raise ValidationError(_(
                        'Mapping JSON must be a dictionary object'
                    ))
            except json.JSONDecodeError as e:
                raise ValidationError(_(
                    'Invalid JSON in mapping_json: %s'
                ) % str(e))

    def get_mapping(self):
        """
        Get the mapping dictionary.
        
        :return: Dictionary mapping remote fields to local fields
        :rtype: dict
        """
        self.ensure_one()
        if not self.mapping_json:
            return {}
        try:
            return json.loads(self.mapping_json)
        except json.JSONDecodeError:
            _logger.error('Invalid JSON in mapping for %s', self.display_name)
            return {}

    def apply_transformation(self, field_value, field_name):
        """
        Apply transformation script to a field value if transformation_script exists.
        
        :param field_value: Original field value
        :param str field_name: Field name
        :return: Transformed field value
        """
        self.ensure_one()
        if not self.transformation_script:
            return field_value
        
        try:
            # Create a safe execution context
            safe_globals = {
                '__builtins__': {
                    'str': str,
                    'int': int,
                    'float': float,
                    'bool': bool,
                    'len': len,
                    'list': list,
                    'dict': dict,
                    'None': None,
                },
            }
            safe_locals = {
                'value': field_value,
                'field_name': field_name,
            }
            
            # Execute transformation script
            exec(self.transformation_script, safe_globals, safe_locals)
            
            # Return transformed value (script should set 'result')
            return safe_locals.get('result', field_value)
        except Exception as e:
            _logger.warning(
                'Error applying transformation script for %s.%s: %s',
                self.model_name, field_name, str(e)
            )
            return field_value


class NumaSynchIssue(models.Model):
    """
    Synchronization Gap Analysis Issue
    
    Logs issues detected by AI when schema mapping cannot be automatically resolved.
    """
    _name = 'numa.synch.issue'
    _description = 'Synchronization Schema Issue'
    _rec_name = 'display_name'
    _order = 'create_date desc'

    batch_id = fields.Char(
        string='Batch ID',
        index=True,
        help='Identifier for the batch that triggered this issue'
    )
    
    remote_token = fields.Char(
        string='Remote Token',
        required=True,
        index=True,
        help='Identifier of the remote system'
    )
    
    model_name = fields.Char(
        string='Model Name',
        required=True,
        index=True,
        help='Odoo model name that has the issue'
    )
    
    issue_type = fields.Selection(
        [
            ('missing_field', 'Missing Required Field'),
            ('type_mismatch', 'Type Mismatch'),
            ('ambiguity', 'Ambiguous Mapping'),
            ('other', 'Other'),
        ],
        string='Issue Type',
        required=True,
        default='other'
    )
    
    description = fields.Text(
        string='Description',
        required=True,
        help='AI explanation of the problem'
    )
    
    remote_field_sample = fields.Text(
        string='Remote Field Sample',
        help='Sample data from the payload to provide context'
    )
    
    suggestion = fields.Text(
        string='Suggestion',
        help='AI proposed fix or recommendation'
    )
    
    confidence_score = fields.Float(
        string='Confidence Score',
        digits=(5, 2),
        help='AI confidence score for this issue analysis'
    )
    
    resolved = fields.Boolean(
        string='Resolved',
        default=False,
        help='Mark as resolved when the issue has been addressed'
    )
    
    create_date = fields.Datetime(
        string='Created On',
        readonly=True
    )
    
    create_uid = fields.Many2one(
        'res.users',
        string='Created By',
        readonly=True
    )
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    @api.depends('model_name', 'issue_type', 'remote_token')
    def _compute_display_name(self):
        """Compute display name"""
        for record in self:
            issue_type_label = dict(record._fields['issue_type'].selection).get(
                record.issue_type, record.issue_type
            )
            record.display_name = f"{record.model_name} - {issue_type_label} ({record.remote_token})"

    def action_resolve(self):
        """Mark issue as resolved"""
        self.write({'resolved': True})
        return True
