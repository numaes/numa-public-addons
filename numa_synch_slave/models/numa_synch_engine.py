"""
Slave Synchronization Engine Implementation

Implements the Slave-side logic for detecting changes, serializing records,
and sending them to the Master server.
"""

from odoo import models, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.fields import Datetime
import logging
import requests
from collections import deque

_logger = logging.getLogger(__name__)


class NumaSynchEngineSlave(models.Model):
    """
    Slave Synchronization Engine
    
    Inherits from the abstract numa.synch.engine and implements
    Slave-specific logic for detecting changes and sending them to Master.
    """
    _name = 'numa.synch.engine'
    _inherit = 'numa.synch.engine'
    _description = 'Slave Synchronization Engine'

    def run_synchronization_cycle(self, connection):
        """
        Main orchestrator for the synchronization cycle.
        
        This method:
        1. Discovers modified records (delta detection)
        2. Resolves dependencies (BFS exploration)
        3. Serializes records
        4. Sends batches to Master
        5. Processes responses and updates mappings
        6. Updates last_sync_date on success
        
        :param recordset connection: numa.synch.connection record
        """
        connection.ensure_one()
        
        if not connection.active:
            _logger.info('Skipping sync: connection %s is not active', connection.name)
            return
        
        _logger.info(
            'Starting synchronization cycle for connection %s (last_sync: %s)',
            connection.name,
            connection.last_sync_date or 'Never'
        )
        
        try:
            # Step 1: Discovery (Delta Detection + Dependencies)
            records_to_sync = self._discover_records(connection)
            
            if not records_to_sync:
                _logger.info('No records to synchronize')
                return
            
            _logger.info('Found %d records to synchronize', len(records_to_sync))
            
            # Step 2: Serialization
            # Build mapping of model_name -> sync_rule for binary sync config
            rules_by_model = {}
            for rule in self.env['numa.synch.rule'].search([
                ('active', '=', True),
                ('direction', 'in', ['bidirectional', 'outgoing'])
            ]):
                if rule.model_name:
                    rules_by_model[rule.model_name] = rule
            
            serialized_records = self._serialize_records(records_to_sync, rules_by_model)
            
            # Step 2.5: Prepare metadata for protocol validation
            # Get unique models from serialized records
            active_models = list(set(rec.get('model') for rec in serialized_records if rec.get('model')))
            metadata = self._prepare_metadata(active_models, rules_by_model)
            
            # Step 3: Batching & Transport
            batches = self._create_batches(serialized_records, connection.batch_size)
            
            # Step 4: Send batches and process responses
            all_batches_succeeded = True
            for batch_idx, batch in enumerate(batches, 1):
                _logger.info(
                    'Sending batch %d/%d (%d records)',
                    batch_idx, len(batches), len(batch)
                )
                
                success = self._send_batch(connection, batch, batch_idx, metadata)
                
                if not success:
                    all_batches_succeeded = False
                    _logger.error('Batch %d failed, stopping synchronization', batch_idx)
                    break
            
            # Step 5: Finalization
            if all_batches_succeeded:
                connection.write({
                    'last_sync_date': Datetime.now()
                })
                _logger.info(
                    'Synchronization cycle completed successfully. '
                    'Processed %d records in %d batches',
                    len(records_to_sync),
                    len(batches)
                )
            else:
                _logger.error(
                    'Synchronization cycle failed. last_sync_date not updated.'
                )
                raise UserError(_(
                    'Synchronization failed. Some batches could not be sent. '
                    'Please check the logs and try again.'
                ))
                
        except Exception as e:
            _logger.exception('Error in synchronization cycle')
            raise

    def _discover_records(self, connection):
        """
        Discover records that need to be synchronized.
        
        Includes:
        - Records modified since last_sync_date (delta detection)
        - Dependencies of those records (BFS exploration)
        
        :param recordset connection: numa.synch.connection record
        :return: List of recordsets to synchronize
        :rtype: list
        """
        # Get all active sync rules
        rules = self.env['numa.synch.rule'].search([
            ('active', '=', True),
            ('direction', 'in', ['bidirectional', 'outgoing'])
        ])
        
        if not rules:
            _logger.info('No active sync rules found')
            return []
        
        # Set to track discovered records (model_name, record_id)
        discovered = set()
        records_to_sync = []
        
        # Queue for BFS exploration
        queue = deque()
        
        # Step 1: Find modified records for each rule
        for rule in rules:
            if not rule.model_name:
                continue
            
            try:
                model = self.env[rule.model_name]
            except KeyError:
                _logger.warning('Model %s does not exist', rule.model_name)
                continue
            
            # Get delta domain
            delta_domain = rule.get_delta_domain(connection.last_sync_date)
            
            # Search for modified records
            modified_records = model.search(delta_domain)
            
            _logger.info(
                'Found %d modified records for model %s (rule: %s)',
                len(modified_records),
                rule.model_name,
                rule.name
            )
            
            # Add to queue for processing
            for record in modified_records:
                key = (rule.model_name, record.id)
                if key not in discovered:
                    discovered.add(key)
                    queue.append((rule.model_name, record))
        
        # Step 2: BFS exploration for dependencies
        while queue:
            model_name, record = queue.popleft()
            
            # Check if record needs synchronization
            needs_sync = self._record_needs_sync(model_name, record, connection)
            
            if needs_sync:
                records_to_sync.append(record)
            
            # Find Many2one dependencies
            dependencies = self._find_many2one_dependencies(record)
            
            for dep_model_name, dep_record in dependencies:
                dep_key = (dep_model_name, dep_record.id)
                if dep_key not in discovered:
                    discovered.add(dep_key)
                    queue.append((dep_model_name, dep_record))
        
        return records_to_sync

    def _record_needs_sync(self, model_name, record, connection):
        """
        Check if a record needs to be synchronized.
        
        A record needs sync if:
        - It's not mapped yet, OR
        - It's mapped but was modified after the last sync
        
        :param str model_name: Technical name of the model
        :param recordset record: Single record
        :param recordset connection: numa.synch.connection record
        :return: True if record needs sync, False otherwise
        :rtype: bool
        """
        synch_map = self.env['numa.synch.map']
        
        # Check if record is mapped
        mapping = synch_map.search([
            ('model_name', '=', model_name),
            ('local_id', '=', record.id),
            ('node_token', '=', 'MASTER')
        ], limit=1)
        
        if not mapping:
            # Not mapped - needs sync
            return True
        
        # Check if record was modified after last sync
        if not connection.last_sync_date:
            # Never synced - needs sync
            return True
        
        # Record was modified after last sync
        if record.write_date and record.write_date > connection.last_sync_date:
            return True
        
        # Also check if mapping's last_sync_date is older than record's write_date
        if mapping.last_sync_date and record.write_date:
            if record.write_date > mapping.last_sync_date:
                return True
        
        # Record is up to date
        return False

    def _find_many2one_dependencies(self, record):
        """
        Find Many2one dependencies of a record.
        
        :param recordset record: Single record
        :return: List of tuples (model_name, record) for dependencies
        :rtype: list
        """
        dependencies = []
        
        if not record or len(record) != 1:
            return dependencies
        
        record.ensure_one()
        model_fields = record._fields
        
        for field_name, field in model_fields.items():
            # Only process Many2one fields
            if field.type != 'many2one':
                continue
            
            # Skip computed fields that are not stored
            if field.compute and not field.store:
                continue
            
            # Skip related fields
            if field.related:
                continue
            
            try:
                field_value = record[field_name]
                if field_value:
                    dependencies.append((field.comodel_name, field_value))
            except Exception as e:
                _logger.debug(
                    'Error getting dependency %s.%s: %s',
                    record._name, field_name, str(e)
                )
                continue
        
        return dependencies

    def _serialize_records(self, records, rules_by_model=None):
        """
        Serialize a list of records to JSON-compatible dictionaries.
        
        :param list records: List of recordsets
        :param dict rules_by_model: Dictionary mapping model_name to sync_rule
        :return: List of serialized record dictionaries
        :rtype: list
        """
        if rules_by_model is None:
            rules_by_model = {}
        
        serialized = []
        
        for record in records:
            try:
                # Get sync rule for this model (if available)
                sync_rule = rules_by_model.get(record._name)
                vals_dict, _ = self._serialize_record(record, sync_rule=sync_rule)
                
                # Add metadata
                serialized_record = {
                    'model': record._name,
                    'local_id': record.id,
                    'vals': vals_dict,
                    'write_date': record.write_date.isoformat() if record.write_date else None,
                }
                
                serialized.append(serialized_record)
                
            except Exception as e:
                _logger.error(
                    'Error serializing record %s (ID: %s): %s',
                    record._name, record.id, str(e),
                    exc_info=True
                )
                # Continue with other records
                continue
        
        return serialized

    def _create_batches(self, records, batch_size):
        """
        Split records into batches.
        
        :param list records: List of serialized records
        :param int batch_size: Maximum records per batch
        :return: List of batches (each batch is a list of records)
        :rtype: list
        """
        batches = []
        
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            batches.append(batch)
        
        return batches

    def _prepare_metadata(self, active_models, rules_by_model):
        """
        Prepare metadata for protocol validation.
        
        :param list active_models: List of model names in the batch
        :param dict rules_by_model: Dictionary mapping model_name to sync_rule
        :return: Metadata dictionary
        :rtype: dict
        """
        # Get system metadata
        system_meta = self._get_system_metadata()
        
        # Calculate model hashes
        model_hashes = {}
        for model_name in active_models:
            sync_rule = rules_by_model.get(model_name)
            model_hash = self._compute_model_hash(model_name, sync_rule)
            if model_hash:
                model_hashes[model_name] = model_hash
        
        return {
            'system': system_meta,
            'models': model_hashes,
        }

    def _send_batch(self, connection, batch, batch_number, metadata=None):
        """
        Send a batch of records to the Master server.
        
        :param recordset connection: numa.synch.connection record
        :param list batch: List of serialized records
        :param int batch_number: Batch number for logging
        :param dict metadata: Optional metadata for protocol validation
        :return: True if successful, False otherwise
        :rtype: bool
        """
        # Prepare endpoint URL
        master_url = connection.master_url.rstrip('/')
        endpoint = f"{master_url}/numa_synch/api/v1/sync_batch"
        
        # Prepare payload with metadata
        payload = {
            'slave_token': connection.slave_token,
            'records': batch
        }
        
        # Add metadata if provided (only for first batch to avoid redundancy)
        if metadata and batch_number == 1:
            payload['meta'] = metadata
        
        # Prepare headers
        headers = {
            'Authorization': f'Bearer {connection.api_key}',
            'Content-Type': 'application/json',
        }
        
        try:
            # Send POST request
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=60  # 60 second timeout
            )
            
            if response.status_code == 200:
                # Success - process response
                response_data = response.json()
                
                if response_data.get('status') == 'success':
                    # Update mappings with returned Master IDs
                    self._process_batch_response(batch, response_data, connection)
                    
                    # Commit transaction to save mapping progress
                    self.env.cr.commit()
                    
                    _logger.info('Batch %d sent successfully', batch_number)
                    return True
                else:
                    _logger.error(
                        'Batch %d returned error status: %s',
                        batch_number,
                        response_data.get('message', 'Unknown error')
                    )
                    return False
            else:
                _logger.error(
                    'Batch %d failed with HTTP status %s: %s',
                    batch_number,
                    response.status_code,
                    response.text[:200]
                )
                return False
                
        except requests.exceptions.ConnectionError as e:
            _logger.error(
                'Network error sending batch %d: %s',
                batch_number, str(e)
            )
            return False
        except requests.exceptions.Timeout:
            _logger.error('Timeout sending batch %d', batch_number)
            return False
        except requests.exceptions.RequestException as e:
            _logger.error(
                'Request error sending batch %d: %s',
                batch_number, str(e)
            )
            return False
        except Exception as e:
            _logger.exception('Unexpected error sending batch %d', batch_number)
            return False

    def _process_batch_response(self, batch, response_data, connection):
        """
        Process the response from Master and update local mappings.
        
        :param list batch: List of records that were sent
        :param dict response_data: JSON response from Master
        :param recordset connection: numa.synch.connection record
        """
        updated_mappings = response_data.get('updated_mappings', [])
        
        if not updated_mappings:
            _logger.debug('No mappings returned in response')
            return
        
        synch_map = self.env['numa.synch.map']
        
        for mapping in updated_mappings:
            model_name = mapping.get('model')
            slave_id = mapping.get('slave_id')  # Our local ID
            master_id = mapping.get('master_id')  # Master's ID
            
            if not model_name or slave_id is None or master_id is None:
                _logger.warning(
                    'Invalid mapping in response: %s',
                    mapping
                )
                continue
            
            try:
                # Create or update mapping
                # From Slave perspective:
                # - local_id = slave_id (our local ID)
                # - remote_id = master_id (Master's ID)
                # - node_token = 'MASTER'
                synch_map.set_mapping(
                    model_name,
                    slave_id,  # local_id
                    master_id,  # remote_id
                    'MASTER',  # node_token
                    last_sync_date=Datetime.now()
                )
                
                _logger.debug(
                    'Updated mapping: %s (slave_id: %s -> master_id: %s)',
                    model_name, slave_id, master_id
                )
                
            except Exception as e:
                _logger.error(
                    'Error updating mapping for %s (slave_id: %s, master_id: %s): %s',
                    model_name, slave_id, master_id, str(e),
                    exc_info=True
                )
                # Continue with other mappings
                continue
