# Numa Synch Protocol Specification

**Version:** 1.0  
**Last Updated:** 2024  
**License:** LGPL-3

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Protocol Endpoints](#protocol-endpoints)
4. [Request Format](#request-format)
5. [Response Format](#response-format)
6. [Data Serialization](#data-serialization)
7. [Metadata and Schema Validation](#metadata-and-schema-validation)
8. [Dynamic Schema Implementation](#dynamic-schema-implementation)
9. [Error Handling](#error-handling)
10. [Implementation Guide](#implementation-guide)

---

## Overview

The Numa Synch protocol is a RESTful JSON-based synchronization protocol designed for offline-first data synchronization between a Master (Odoo server) and Slave nodes (any system). The protocol supports:

- **Bidirectional synchronization** (currently Slave → Master implemented)
- **Strict schema validation** to prevent data corruption
- **Dynamic schema adaptation** for maximum flexibility
- **Batch processing** for efficiency
- **Conflict resolution** using Last Write Wins (LWW) strategy

### Protocol Version

Current protocol version: **v1**

Base endpoint: `/numa_synch/api/v1/`

---

## Authentication

### Authentication Method

The protocol uses **Bearer Token Authentication** via HTTP headers.

### Headers Required

```
Authorization: Bearer <api_key>
Content-Type: application/json
```

### API Key Generation

API keys are generated on the Master server (Odoo) through:
- Settings → Technical → API → API Keys
- Create a new API key for the user account that has access to synchronization models

### Slave Token

Each Slave node must have a unique identifier (UUID) called `slave_token`. This token:
- Identifies the Slave node to the Master
- Is generated once and never changes
- Must be included in every request payload

---

## Protocol Endpoints

### Synchronization Batch Endpoint

**Endpoint:** `POST /numa_synch/api/v1/sync_batch`

**Description:** Sends a batch of records to the Master for synchronization.

**Authentication:** Required (Bearer token)

**Content-Type:** `application/json`

**CSRF Protection:** Disabled (uses Bearer token authentication)

---

## Request Format

### Request Structure

```json
{
  "slave_token": "550e8400-e29b-41d4-a716-446655440000",
  "meta": {
    "system": {
      "odoo_version": "18.0",
      "db_uuid": "database-uuid-string",
      "module_version": "18.0.1.0.0"
    },
    "models": {
      "res.partner": "sha256_hash_string...",
      "sale.order": "sha256_hash_string..."
    }
  },
  "records": [
    {
      "model": "res.partner",
      "local_id": 123,
      "vals": {
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "+1234567890",
        "category_id": [
          {
            "__type__": "ref",
            "model": "res.partner.category",
            "id": 5
          }
        ]
      },
      "write_date": "2024-01-15T14:30:00"
    }
  ]
}
```

### Field Descriptions

#### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `slave_token` | string (UUID) | Yes | Unique identifier for the Slave node |
| `meta` | object | No* | Metadata for protocol validation (*required for first batch) |
| `records` | array | Yes | List of records to synchronize |

#### Metadata Object (`meta`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system` | object | Yes | System identification information |
| `models` | object | Yes | Schema hashes for each model in the batch |

**System Object:**

| Field | Type | Description |
|-------|------|-----------|
| `odoo_version` | string | Odoo version (e.g., "18.0") - must match Master exactly |
| `db_uuid` | string | Database UUID (informational, not validated) |
| `module_version` | string | Version of numa_synch module |

**Models Object:**

Key-value pairs where:
- **Key:** Model name (e.g., "res.partner")
- **Value:** SHA256 hash string representing the model's schema

#### Record Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | Technical name of the model (e.g., "res.partner") |
| `local_id` | integer | Yes | Local ID of the record on the Slave |
| `vals` | object | Yes | Field values dictionary |
| `write_date` | string (ISO 8601) | No | Timestamp of last modification |

---

## Response Format

### Success Response

```json
{
  "status": "success",
  "message": "Processed 10 records",
  "updated_mappings": [
    {
      "model": "res.partner",
      "slave_id": 123,
      "master_id": 456
    }
  ]
}
```

### Error Response

```json
{
  "status": "error",
  "message": "Validation error: Schema Mismatch in model res.partner...",
  "updated_mappings": []
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Either "success" or "error" |
| `message` | string | Human-readable message |
| `updated_mappings` | array | List of ID mappings created/updated |

#### Mapping Object

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Model name |
| `slave_id` | integer | Original Slave local ID |
| `master_id` | integer | New Master ID (for new records) or existing Master ID |

---

## Data Serialization

### Field Type Serialization

#### Scalar Fields

| Odoo Type | JSON Type | Example |
|-----------|-----------|---------|
| `char` | string | `"John Doe"` |
| `text` | string | `"Long text content"` |
| `integer` | number | `42` |
| `float` | number | `3.14159` |
| `boolean` | boolean | `true` or `false` |
| `selection` | string | `"draft"` |

#### Date/Time Fields

| Odoo Type | JSON Format | Example |
|-----------|-------------|---------|
| `date` | string (YYYY-MM-DD) | `"2024-01-15"` |
| `datetime` | string (ISO 8601) | `"2024-01-15T14:30:00"` |

**Note:** Use `false` or `null` for empty date/datetime values.

#### Relational Fields

##### Many2one

```json
{
  "partner_id": {
    "__type__": "ref",
    "model": "res.partner",
    "id": 123
  }
}
```

Or `false`/`null` if empty.

##### One2many / Many2many

```json
{
  "category_id": [
    {
      "__type__": "ref",
      "model": "res.partner.category",
      "id": 5
    },
    {
      "__type__": "ref",
      "model": "res.partner.category",
      "id": 7
    }
  ]
}
```

Or empty array `[]` if no relations.

#### Binary Fields

```json
{
  "image_1920": {
    "__type__": "binary",
    "data": "base64_encoded_string...",
    "compressed": true,
    "size_bytes": 1024,
    "original_size_mb": 0.5
  }
}
```

**Note:** Binary fields are optional and must be explicitly enabled in sync rules.

### Special Reference Format

All relational fields use the `__type__: "ref"` format:

```json
{
  "__type__": "ref",
  "model": "target_model_name",
  "id": local_id_on_slave
}
```

The Master will resolve these references using the identity mapping table.

---

## Metadata and Schema Validation

### Purpose

Metadata validation ensures that the Slave and Master have compatible data structures before processing any records. This prevents data corruption from schema mismatches.

### Metadata Generation

#### System Metadata

```python
system_meta = {
    "odoo_version": "18.0",  # Must match Master exactly
    "db_uuid": "uuid-string",  # Informational only
    "module_version": "18.0.1.0.0"  # Version of sync module
}
```

#### Model Schema Hash

The schema hash is a SHA256 hash calculated from:

1. **Field signatures** for each field in the model:
   - Format: `field_name:field_type:required:relation`
   - Example: `name:char:False:` or `partner_id:many2one:False:res.partner`

2. **Sorted alphabetically** for determinism

3. **Excludes:**
   - System fields (id, create_date, write_date, etc.)
   - Related fields (computed from base fields)
   - Non-stored computed fields (unless enabled in sync rule)

**Example Hash Calculation (Pseudocode):**

```python
def compute_model_hash(model_name, fields):
    signatures = []
    for field in fields:
        if field.name in system_fields:
            continue
        signature = f"{field.name}:{field.type}:{field.required}:{field.relation or ''}"
        signatures.append(signature)
    
    signatures.sort()  # Alphabetical order
    concatenated = "\n".join(signatures)
    return sha256(concatenated).hexdigest()
```

### Validation Process

1. **Version Check:** `odoo_version` must match exactly
2. **Schema Check:** Model hashes must match for all models in the batch
3. **Error on Mismatch:** If validation fails, the entire batch is rejected with a descriptive error

### Validation Errors

If validation fails, the Master returns:

```json
{
  "status": "error",
  "message": "Schema Mismatch in model res.partner.\nRemote hash: abc123...\nLocal hash: def456...\n\nThis indicates that the model structure differs between the Slave and Master. Ensure both servers have the same modules installed and the same field definitions.",
  "updated_mappings": []
}
```

**Action Required:** Update the Slave's schema to match the Master, or update the Master to match the Slave.

---

## Dynamic Schema Implementation

### Overview

One of the key strengths of the Numa Synch protocol is its support for **dynamic schema implementation**. This allows Slave implementations to adapt to the Master's schema on-the-fly without requiring code changes or recompilation.

### Implementation Strategy

#### 1. Schema Discovery

Before sending data, the Slave should:

1. **Query Master Schema** (optional but recommended):
   - Make a test request with empty records but include metadata
   - Master will validate and return any schema mismatches
   - Use this to discover expected schema

2. **Build Dynamic Model Definitions:**
   ```python
   class DynamicModel:
       def __init__(self, model_name, fields_config):
           self.model_name = model_name
           self.fields = {}
           for field_config in fields_config:
               self.fields[field_config['name']] = DynamicField(field_config)
   ```

#### 2. Field Type Mapping

Create a mapping between your local field types and Odoo field types:

```python
FIELD_TYPE_MAPPING = {
    'string': 'char',
    'varchar': 'char',
    'text': 'text',
    'integer': 'integer',
    'bigint': 'integer',  # Odoo integers are 64-bit
    'decimal': 'float',
    'numeric': 'float',
    'boolean': 'boolean',
    'date': 'date',
    'timestamp': 'datetime',
    'foreign_key': 'many2one',
    'array': 'many2many',  # Depending on semantics
}
```

#### 3. Dynamic Serialization

Implement a generic serializer that adapts to any schema:

```python
class DynamicSerializer:
    def serialize_record(self, record, model_def):
        vals = {}
        
        for field_name, field_def in model_def.fields.items():
            value = getattr(record, field_name, None)
            
            if value is None:
                vals[field_name] = False
                continue
            
            # Handle by field type
            if field_def.type == 'many2one':
                vals[field_name] = {
                    "__type__": "ref",
                    "model": field_def.relation,
                    "id": value.id  # Assuming value is an object with id
                }
            elif field_def.type in ('one2many', 'many2many'):
                vals[field_name] = [
                    {
                        "__type__": "ref",
                        "model": field_def.relation,
                        "id": item.id
                    }
                    for item in value
                ]
            elif field_def.type == 'date':
                vals[field_name] = value.strftime('%Y-%m-%d')
            elif field_def.type == 'datetime':
                vals[field_name] = value.isoformat()
            elif field_def.type == 'binary':
                # Handle binary with base64 encoding
                vals[field_name] = self.serialize_binary(value, field_def)
            else:
                # Scalar types: char, text, integer, float, boolean
                vals[field_name] = value
        
        return vals
```

#### 4. Schema Hash Calculation

Calculate schema hash dynamically:

```python
def calculate_schema_hash(model_def):
    signatures = []
    
    for field_name, field_def in sorted(model_def.fields.items()):
        if field_def.is_system_field:
            continue
        
        relation = field_def.relation if field_def.type in ('many2one', 'one2many', 'many2many') else ''
        signature = f"{field_name}:{field_def.type}:{field_def.required}:{relation}"
        signatures.append(signature)
    
    signatures.sort()
    concatenated = "\n".join(signatures)
    return hashlib.sha256(concatenated.encode('utf-8')).hexdigest()
```

#### 5. Runtime Schema Adaptation

Implement a schema adapter that can:

1. **Detect schema changes** from Master validation errors
2. **Update local schema definitions** dynamically
3. **Retry synchronization** with updated schema

```python
class SchemaAdapter:
    def __init__(self):
        self.model_definitions = {}
        self.schema_hashes = {}
    
    def update_schema_from_error(self, error_message, master_hash):
        # Parse error message to extract model name and expected hash
        # Update local schema definition to match Master
        # Recalculate hash
        pass
    
    def adapt_field_mapping(self, local_field, master_field_def):
        # Map local field to Master field definition
        # Handle type conversions
        # Handle missing fields (skip or use defaults)
        pass
```

### Example: Python Implementation

```python
import requests
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any

class NumaSynchSlave:
    def __init__(self, master_url: str, api_key: str, slave_token: str):
        self.master_url = master_url.rstrip('/')
        self.api_key = api_key
        self.slave_token = slave_token
        self.endpoint = f"{self.master_url}/numa_synch/api/v1/sync_batch"
        self.model_definitions = {}
        self.schema_hashes = {}
    
    def register_model(self, model_name: str, fields: List[Dict]):
        """Register a model definition dynamically"""
        self.model_definitions[model_name] = {
            'fields': {f['name']: f for f in fields},
            'hash': self._calculate_hash(model_name, fields)
        }
        self.schema_hashes[model_name] = self.model_definitions[model_name]['hash']
    
    def _calculate_hash(self, model_name: str, fields: List[Dict]) -> str:
        """Calculate SHA256 hash for model schema"""
        signatures = []
        for field in sorted(fields, key=lambda x: x['name']):
            if field.get('system', False):
                continue
            relation = field.get('relation', '')
            sig = f"{field['name']}:{field['type']}:{field.get('required', False)}:{relation}"
            signatures.append(sig)
        concatenated = "\n".join(signatures)
        return hashlib.sha256(concatenated.encode('utf-8')).hexdigest()
    
    def serialize_record(self, record: Any, model_name: str) -> Dict:
        """Serialize a record according to registered model definition"""
        model_def = self.model_definitions[model_name]
        vals = {}
        
        for field_name, field_def in model_def['fields'].items():
            value = getattr(record, field_name, None)
            
            if value is None:
                vals[field_name] = False
                continue
            
            field_type = field_def['type']
            
            if field_type == 'many2one':
                vals[field_name] = {
                    "__type__": "ref",
                    "model": field_def['relation'],
                    "id": value.id if hasattr(value, 'id') else value
                }
            elif field_type in ('one2many', 'many2many'):
                vals[field_name] = [
                    {
                        "__type__": "ref",
                        "model": field_def['relation'],
                        "id": item.id if hasattr(item, 'id') else item
                    }
                    for item in (value if isinstance(value, list) else [value])
                ]
            elif field_type == 'date':
                vals[field_name] = value.strftime('%Y-%m-%d') if hasattr(value, 'strftime') else str(value)
            elif field_type == 'datetime':
                vals[field_name] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
            elif field_type == 'binary':
                # Base64 encode binary data
                import base64
                if isinstance(value, bytes):
                    vals[field_name] = {
                        "__type__": "binary",
                        "data": base64.b64encode(value).decode('utf-8'),
                        "compressed": False,
                        "size_bytes": len(value)
                    }
            else:
                vals[field_name] = value
        
        return {
            "model": model_name,
            "local_id": record.id if hasattr(record, 'id') else record['id'],
            "vals": vals,
            "write_date": datetime.now().isoformat() if hasattr(record, 'write_date') else None
        }
    
    def prepare_metadata(self, model_names: List[str]) -> Dict:
        """Prepare metadata for protocol validation"""
        return {
            "system": {
                "odoo_version": "18.0",  # Should match Master
                "db_uuid": "",  # Optional
                "module_version": "1.0.0"
            },
            "models": {
                model_name: self.schema_hashes[model_name]
                for model_name in model_names
                if model_name in self.schema_hashes
            }
        }
    
    def send_batch(self, records: List[Dict], include_metadata: bool = False) -> Dict:
        """Send a batch of records to Master"""
        payload = {
            "slave_token": self.slave_token,
            "records": records
        }
        
        if include_metadata:
            model_names = list(set(r["model"] for r in records))
            payload["meta"] = self.prepare_metadata(model_names)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            self.endpoint,
            json=payload,
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Sync failed: {response.status_code} - {response.text}")

# Usage Example
slave = NumaSynchSlave(
    master_url="https://master.example.com",
    api_key="your-api-key",
    slave_token="550e8400-e29b-41d4-a716-446655440000"
)

# Register model dynamically
slave.register_model("res.partner", [
    {"name": "name", "type": "char", "required": True},
    {"name": "email", "type": "char", "required": False},
    {"name": "phone", "type": "char", "required": False},
    {"name": "category_id", "type": "many2many", "relation": "res.partner.category", "required": False}
])

# Serialize and send records
records = [slave.serialize_record(partner, "res.partner") for partner in local_partners]
result = slave.send_batch(records, include_metadata=True)
```

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response and update mappings |
| 400 | Bad Request | Check payload format and required fields |
| 401 | Unauthorized | Verify API key is correct |
| 403 | Forbidden | Check API key permissions |
| 500 | Internal Server Error | Retry after delay, contact Master administrator |

### Error Response Format

All errors return JSON in this format:

```json
{
  "status": "error",
  "message": "Descriptive error message",
  "updated_mappings": []
}
```

### Common Errors

#### 1. Schema Mismatch

```json
{
  "status": "error",
  "message": "Schema Mismatch in model res.partner.\nRemote hash: abc123...\nLocal hash: def456..."
}
```

**Solution:** Update Slave schema to match Master, or vice versa.

#### 2. Version Mismatch

```json
{
  "status": "error",
  "message": "Version Mismatch: Remote Odoo version (17.0) does not match local version (18.0)..."
}
```

**Solution:** Ensure Slave and Master run the same Odoo version.

#### 3. Missing Required Field

```json
{
  "status": "error",
  "message": "Validation error: Missing required field 'name' in model res.partner"
}
```

**Solution:** Ensure all required fields are included in the payload.

#### 4. Invalid Reference

```json
{
  "status": "error",
  "message": "Reference to res.partner (ID: 999) not found in mapping"
}
```

**Solution:** Ensure referenced records are synchronized before referencing them, or include them in the same batch.

### Retry Strategy

Recommended retry strategy:

1. **Transient Errors** (network, 500): Exponential backoff (1s, 2s, 4s, 8s, 16s)
2. **Schema Errors**: Do not retry, fix schema first
3. **Validation Errors**: Do not retry, fix data first
4. **Authentication Errors**: Do not retry, fix credentials

---

## Implementation Guide

### Step-by-Step Implementation

#### 1. Setup

1. Obtain API key from Master administrator
2. Generate a unique UUID for `slave_token`
3. Store credentials securely

#### 2. Model Registration

Register all models you want to synchronize:

```python
# Define model schema
partner_fields = [
    {"name": "name", "type": "char", "required": True},
    {"name": "email", "type": "char", "required": False},
    # ... more fields
]

slave.register_model("res.partner", partner_fields)
```

#### 3. Record Serialization

Serialize local records according to registered schemas:

```python
serialized = slave.serialize_record(local_partner, "res.partner")
```

#### 4. Batch Preparation

Group records into batches (recommended: 50-200 records per batch):

```python
batches = [records[i:i+100] for i in range(0, len(records), 100)]
```

#### 5. Send Batches

Send each batch with metadata in the first batch:

```python
for i, batch in enumerate(batches):
    result = slave.send_batch(
        batch,
        include_metadata=(i == 0)  # Only first batch
    )
    
    if result["status"] == "success":
        # Update local ID mappings
        for mapping in result["updated_mappings"]:
            update_local_mapping(
                mapping["model"],
                mapping["slave_id"],
                mapping["master_id"]
            )
    else:
        # Handle error
        handle_error(result["message"])
```

#### 6. Handle Mappings

Store ID mappings locally for reference resolution:

```python
mappings = {
    ("res.partner", 123): 456,  # (model, slave_id) -> master_id
}
```

### Best Practices

1. **Always include metadata** in the first batch of each sync cycle
2. **Validate schema** before sending large batches
3. **Handle errors gracefully** with appropriate retry logic
4. **Store ID mappings** for efficient reference resolution
5. **Respect batch size limits** (50-200 records recommended)
6. **Implement delta detection** to only sync changed records
7. **Use connection pooling** for HTTP requests
8. **Log all synchronization activities** for debugging

### Testing

#### Test Connection

```python
# Send empty batch to test connection
result = slave.send_batch([], include_metadata=False)
assert result["status"] == "success"
```

#### Test Schema Validation

```python
# Register model and send with metadata
slave.register_model("res.partner", partner_fields)
result = slave.send_batch([test_record], include_metadata=True)

if result["status"] == "error" and "Schema Mismatch" in result["message"]:
    # Schema needs updating
    update_schema_from_error(result["message"])
```

---

## Appendix

### Field Type Reference

| Odoo Type | Description | JSON Representation |
|-----------|-------------|---------------------|
| `char` | Short text (varchar) | string |
| `text` | Long text | string |
| `integer` | Integer number | number |
| `float` | Decimal number | number |
| `boolean` | True/false | boolean |
| `date` | Date only | string (YYYY-MM-DD) |
| `datetime` | Date and time | string (ISO 8601) |
| `many2one` | Foreign key | object with `__type__: "ref"` |
| `one2many` | One-to-many relation | array of ref objects |
| `many2many` | Many-to-many relation | array of ref objects |
| `binary` | Binary data | object with `__type__: "binary"` |
| `selection` | Choice from list | string |

### Example Payloads

#### Minimal Payload

```json
{
  "slave_token": "550e8400-e29b-41d4-a716-446655440000",
  "records": [
    {
      "model": "res.partner",
      "local_id": 1,
      "vals": {
        "name": "Test Partner"
      }
    }
  ]
}
```

#### Complete Payload with Metadata

```json
{
  "slave_token": "550e8400-e29b-41d4-a716-446655440000",
  "meta": {
    "system": {
      "odoo_version": "18.0",
      "db_uuid": "123e4567-e89b-12d3-a456-426614174000",
      "module_version": "18.0.1.0.0"
    },
    "models": {
      "res.partner": "a1b2c3d4e5f6..."
    }
  },
  "records": [
    {
      "model": "res.partner",
      "local_id": 1,
      "vals": {
        "name": "John Doe",
        "email": "john@example.com",
        "category_id": [
          {"__type__": "ref", "model": "res.partner.category", "id": 1}
        ]
      },
      "write_date": "2024-01-15T14:30:00"
    }
  ]
}
```

---

## License

This protocol specification is licensed under LGPL-3.

## Support

For questions, issues, or contributions, please contact the Numa Synch development team.

---

**Document Version:** 1.0  
**Last Updated:** 2024  
**Protocol Version:** v1
