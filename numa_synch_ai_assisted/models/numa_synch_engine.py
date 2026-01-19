"""
AI-Assisted Synchronization Engine

Extends the synchronization engine with AI-powered schema adaptation
for handling non-standard or external system schemas.
"""

import json
import logging
from odoo import models, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class NumaSynchEngineAiAssisted(models.Model):
    """
    AI-Assisted Synchronization Engine
    
    Extends numa.synch.engine with AI-powered schema adaptation.
    When standard metadata validation fails, this engine attempts
    to use AI to generate transformation maps.
    """
    _name = 'numa.synch.engine'
    _inherit = 'numa.synch.engine'

    def _validate_metadata(self, incoming_meta, active_models):
        """
        Override metadata validation with AI-assisted fallback.
        
        Flow:
        1. Try standard validation first
        2. If it fails, check for cached AI mapping
        3. If no cache, invoke AI to generate mapping
        4. If AI succeeds (high confidence), cache and proceed
        5. If AI fails (low confidence or critical issues), log and abort
        
        :param dict incoming_meta: Metadata dictionary from incoming JSON
        :param list active_models: List of model names in the batch
        :raises UserError: If validation fails and cannot be resolved
        """
        # Try standard validation first
        try:
            super()._validate_metadata(incoming_meta, active_models)
            # Standard validation succeeded, no AI needed
            return
        except UserError as e:
            # Standard validation failed - try AI-assisted adaptation
            _logger.info(
                'Standard metadata validation failed, attempting AI-assisted adaptation: %s',
                str(e)
            )
            
            # Extract remote token from context or metadata
            remote_token = self.env.context.get('slave_token') or incoming_meta.get('remote_token', 'unknown')
            
            # Check cache for each model
            for model_name in active_models:
                cached_map = self._get_cached_mapping(remote_token, model_name)
                
                if cached_map:
                    _logger.info(
                        'Using cached AI mapping for %s (remote: %s)',
                        model_name, remote_token
                    )
                    # Mapping exists, validation will pass after transformation
                    continue
                
                # No cache - try AI analysis
                try:
                    ai_result = self._analyze_schema_with_ai(
                        model_name,
                        incoming_meta,
                        remote_token
                    )
                    
                    if ai_result.get('confidence_score', 0) >= 0.9 and not ai_result.get('critical_issues'):
                        # High confidence, no critical issues - create mapping
                        self._create_ai_mapping(
                            remote_token,
                            model_name,
                            ai_result
                        )
                        _logger.warning(
                            'AI Mapping created for node %s, model %s (confidence: %.2f)',
                            remote_token, model_name, ai_result.get('confidence_score', 0)
                        )
                    else:
                        # Low confidence or critical issues - log gap analysis
                        self._log_gap_analysis(
                            remote_token,
                            model_name,
                            ai_result,
                            incoming_meta
                        )
                        raise UserError(_(
                            'Synchronization Blocked: Schema incompatibility detected for model %s.\n'
                            'See "Synchronization Issues" log for the AI Gap Analysis report.\n'
                            'Confidence Score: %.2f'
                        ) % (model_name, ai_result.get('confidence_score', 0)))
                        
                except Exception as ai_error:
                    _logger.error(
                        'AI analysis failed for model %s: %s',
                        model_name, str(ai_error),
                        exc_info=True
                    )
                    raise UserError(_(
                        'Synchronization Blocked: Unable to resolve schema mismatch for model %s.\n'
                        'AI analysis failed: %s'
                    ) % (model_name, str(ai_error)))

    def _get_cached_mapping(self, remote_token, model_name):
        """
        Get cached AI mapping for a remote token and model.
        
        :param str remote_token: Remote system identifier
        :param str model_name: Model name
        :return: numa.synch.ai.map record or None
        """
        return self.env['numa.synch.ai.map'].search([
            ('remote_token', '=', remote_token),
            ('model_name', '=', model_name),
            ('active', '=', True)
        ], limit=1)

    def _analyze_schema_with_ai(self, model_name, incoming_meta, remote_token):
        """
        Invoke AI to analyze schema mismatch and generate mapping.
        
        :param str model_name: Target Odoo model name
        :param dict incoming_meta: Incoming metadata
        :param str remote_token: Remote system identifier
        :return: Dictionary with mapping, confidence_score, and issues
        :rtype: dict
        """
        # Get local model schema
        local_schema = self._get_model_schema(model_name)
        
        # Extract source schema from metadata or sample records
        source_schema = self._extract_source_schema(incoming_meta, model_name)
        
        # Build AI prompt
        prompt = self._build_ai_prompt(local_schema, source_schema, model_name)
        
        # Call AI engine
        try:
            ai_engine = self.env['numa.ai.engine']
            response = ai_engine.ask_llm(prompt, json_mode=True)
            
            # Parse AI response
            if isinstance(response, str):
                ai_result = json.loads(response)
            else:
                ai_result = response
            
            return ai_result
        except Exception as e:
            _logger.error('Error calling AI engine: %s', str(e))
            raise

    def _get_model_schema(self, model_name):
        """
        Get schema definition for a local Odoo model.
        
        :param str model_name: Model name
        :return: Dictionary with field definitions
        :rtype: dict
        """
        try:
            model = self.env[model_name]
            schema = {
                'model': model_name,
                'fields': []
            }
            
            for field_name, field in model._fields.items():
                # Skip system fields
                if field_name in {'id', 'create_date', 'create_uid', 'write_date', 'write_uid',
                                 '__last_update', 'display_name', 'display_type'}:
                    continue
                
                # Skip related fields
                if field.related:
                    continue
                
                field_def = {
                    'name': field_name,
                    'type': field.type,
                    'required': field.required,
                    'string': field.string or field_name,
                }
                
                # Add relation for relational fields
                if field.type in ('many2one', 'one2many', 'many2many'):
                    field_def['relation'] = field.comodel_name or ''
                
                schema['fields'].append(field_def)
            
            return schema
        except KeyError:
            _logger.error('Model %s does not exist', model_name)
            return {'model': model_name, 'fields': []}

    def _extract_source_schema(self, incoming_meta, model_name):
        """
        Extract source schema from incoming metadata or sample records.
        
        :param dict incoming_meta: Incoming metadata
        :param str model_name: Model name
        :return: Dictionary with source field definitions
        :rtype: dict
        """
        # Try to get schema from metadata models hash info
        # If not available, we'll need to infer from sample records
        source_schema = {
            'model': model_name,
            'fields': []
        }
        
        # For now, we'll need sample records to infer schema
        # This should be passed from the calling context
        sample_records = self.env.context.get('sample_records', [])
        
        if sample_records:
            # Infer schema from first record
            first_record = next((r for r in sample_records if r.get('model') == model_name), None)
            if first_record and first_record.get('vals'):
                for field_name in first_record['vals'].keys():
                    field_value = first_record['vals'][field_name]
                    field_type = self._infer_field_type(field_value)
                    
                    source_schema['fields'].append({
                        'name': field_name,
                        'type': field_type,
                        'required': False,  # Can't determine from sample
                    })
        
        return source_schema

    def _infer_field_type(self, value):
        """
        Infer Odoo field type from a Python value.
        
        :param value: Python value
        :return: Odoo field type string
        :rtype: str
        """
        if value is None or value is False:
            return 'char'  # Default
        elif isinstance(value, bool):
            return 'boolean'
        elif isinstance(value, int):
            return 'integer'
        elif isinstance(value, float):
            return 'float'
        elif isinstance(value, str):
            return 'char'
        elif isinstance(value, list):
            if value and isinstance(value[0], dict) and value[0].get('__type__') == 'ref':
                return 'many2many'
            return 'char'  # Default
        elif isinstance(value, dict):
            if value.get('__type__') == 'ref':
                return 'many2one'
            elif value.get('__type__') == 'binary':
                return 'binary'
            return 'char'  # Default
        else:
            return 'char'  # Default

    def _build_ai_prompt(self, local_schema, source_schema, model_name):
        """
        Build AI prompt for schema mapping analysis.
        
        :param dict local_schema: Local Odoo model schema
        :param dict source_schema: Source system schema
        :param str model_name: Model name
        :return: Prompt text
        :rtype: str
        """
        prompt = f"""You are a Data Engineer specializing in schema mapping and data transformation.

TASK: Analyze two schemas and create a field mapping between them.

TARGET SCHEMA (Odoo Model: {model_name}):
{json.dumps(local_schema, indent=2)}

SOURCE SCHEMA (External/Remote System):
{json.dumps(source_schema, indent=2)}

INSTRUCTIONS:
1. Map each source field to the most semantically similar target field based on:
   - Field name similarity (e.g., "fname" → "name", "cust_name" → "name")
   - Field type compatibility (e.g., string → char, integer → integer)
   - Business context (e.g., "email_addr" → "email")
   
2. Identify CRITICAL issues:
   - Missing required fields in source that exist in target
   - Type mismatches that cannot be automatically converted
   - Ambiguous mappings (multiple source fields could map to same target)
   
3. For each mapping, assess confidence:
   - High confidence (>0.9): Clear semantic match, compatible types
   - Medium confidence (0.7-0.9): Good match but some uncertainty
   - Low confidence (<0.7): Ambiguous or incompatible

4. Return a JSON object with this structure:
{{
    "mapping": {{
        "source_field_name": "target_field_name",
        ...
    }},
    "confidence_score": 0.95,
    "issues": [
        {{
            "type": "missing_field" | "type_mismatch" | "ambiguity" | "other",
            "field": "target_field_name",
            "description": "Detailed explanation",
            "suggestion": "Proposed solution"
        }},
        ...
    ],
    "critical_issues": false
}}

IMPORTANT:
- Focus on semantic similarity, not just name matching
- Consider type compatibility (e.g., string can map to char, but integer cannot map to date)
- Mark as critical if required target fields cannot be mapped
- Be conservative with confidence scores
- Provide actionable suggestions for issues

Return ONLY valid JSON, no additional text."""
        
        return prompt

    def _create_ai_mapping(self, remote_token, model_name, ai_result):
        """
        Create and store AI-generated mapping.
        
        :param str remote_token: Remote system identifier
        :param str model_name: Model name
        :param dict ai_result: AI analysis result
        """
        mapping_data = {
            'remote_token': remote_token,
            'model_name': model_name,
            'mapping_json': json.dumps(ai_result.get('mapping', {})),
            'confidence_score': ai_result.get('confidence_score', 0.0),
            'active': True,
        }
        
        # Check if mapping already exists (update if exists)
        existing = self._get_cached_mapping(remote_token, model_name)
        if existing:
            existing.write(mapping_data)
        else:
            self.env['numa.synch.ai.map'].create(mapping_data)

    def _log_gap_analysis(self, remote_token, model_name, ai_result, incoming_meta):
        """
        Log gap analysis issues when AI cannot resolve mapping.
        
        :param str remote_token: Remote system identifier
        :param str model_name: Model name
        :param dict ai_result: AI analysis result
        :param dict incoming_meta: Incoming metadata
        """
        batch_id = self.env.context.get('batch_id', f"{remote_token}_{model_name}")
        
        issues = ai_result.get('issues', [])
        if not issues:
            # Create a generic issue if none provided
            issues = [{
                'type': 'other',
                'field': model_name,
                'description': 'AI analysis returned low confidence or critical issues',
                'suggestion': ai_result.get('suggestion', 'Review schema compatibility manually')
            }]
        
        for issue in issues:
            # Get sample data for context
            sample_records = self.env.context.get('sample_records', [])
            remote_field_sample = None
            if sample_records:
                first_record = next((r for r in sample_records if r.get('model') == model_name), None)
                if first_record and first_record.get('vals'):
                    issue_field = issue.get('field', '')
                    remote_field = next(
                        (k for k, v in ai_result.get('mapping', {}).items() if v == issue_field),
                        issue_field
                    )
                    remote_field_sample = json.dumps(
                        first_record['vals'].get(remote_field, 'N/A'),
                        indent=2
                    )[:500]  # Limit size
            
            self.env['numa.synch.issue'].create({
                'batch_id': batch_id,
                'remote_token': remote_token,
                'model_name': model_name,
                'issue_type': issue.get('type', 'other'),
                'description': issue.get('description', 'No description provided'),
                'remote_field_sample': remote_field_sample,
                'suggestion': issue.get('suggestion', ''),
                'confidence_score': ai_result.get('confidence_score', 0.0),
                'resolved': False,
            })

    def process_incoming_batch_master(self, slave_token, records, metadata=None):
        """
        Override to add payload transformation before processing.
        
        :param str slave_token: Slave token
        :param list records: Records list
        :param dict metadata: Metadata
        :return: Result dictionary
        """
        # Transform records using AI mappings if available
        transformed_records = self._transform_payload(slave_token, records)
        
        # Add context for AI validation
        context = self.env.context.copy()
        context.update({
            'slave_token': slave_token,
            'sample_records': records[:5] if records else [],  # Sample for schema inference
            'batch_id': f"{slave_token}_{len(records)}",
        })
        
        # Call parent with transformed records and context
        return super(NumaSynchEngineAiAssisted, self.with_context(**context)).process_incoming_batch_master(
            slave_token,
            transformed_records,
            metadata
        )

    def _transform_payload(self, remote_token, records):
        """
        Transform payload records using AI mappings.
        
        :param str remote_token: Remote system identifier
        :param list records: List of record dictionaries
        :return: Transformed records
        :rtype: list
        """
        transformed = []
        
        for record in records:
            model_name = record.get('model')
            if not model_name:
                transformed.append(record)
                continue
            
            # Get mapping for this model
            mapping = self._get_cached_mapping(remote_token, model_name)
            if not mapping:
                # No mapping, pass through unchanged
                transformed.append(record)
                continue
            
            # Apply mapping
            mapping_dict = mapping.get_mapping()
            if not mapping_dict:
                transformed.append(record)
                continue
            
            # Transform vals dictionary
            transformed_vals = {}
            original_vals = record.get('vals', {})
            
            for remote_field, local_field in mapping_dict.items():
                if remote_field in original_vals:
                    value = original_vals[remote_field]
                    
                    # Apply transformation script if available
                    if mapping.transformation_script:
                        value = mapping.apply_transformation(value, remote_field)
                    
                    transformed_vals[local_field] = value
            
            # Create transformed record
            transformed_record = record.copy()
            transformed_record['vals'] = transformed_vals
            transformed.append(transformed_record)
            
            _logger.debug(
                'Transformed record %s using AI mapping (remote: %s)',
                model_name, remote_token
            )
        
        return transformed
