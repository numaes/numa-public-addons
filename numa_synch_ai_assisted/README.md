# Numa Synch AI Assisted Module

**Version:** 18.0.1.0.0  
**Author:** Gustavo Marino <gamarino@numaes.com>  
**License:** LGPL-3  
**Category:** Extra Tools

## Overview

The `numa_synch_ai_assisted` module extends the Numa Synch synchronization system with AI-powered schema adaptation capabilities. When standard metadata validation fails (e.g., connecting to non-Odoo systems or modified schemas), this module uses AI to automatically generate transformation maps, enabling seamless synchronization with external systems.

## Purpose

This module acts as an **intelligent fallback adapter** that:

1. **Intercepts validation failures** when standard hash-based schema validation fails
2. **Leverages AI** to analyze schema mismatches and generate field mappings
3. **Caches successful mappings** to avoid repeated AI calls
4. **Logs detailed gap analysis** when AI cannot resolve issues automatically
5. **Transforms payloads** transparently using cached mappings

## Key Features

### 1. AI-Powered Schema Mapping

- Automatically analyzes schema differences between source and target systems
- Generates field mappings based on semantic similarity and type compatibility
- Provides confidence scores for mapping quality
- Identifies critical issues that prevent automatic resolution

### 2. Intelligent Caching

- Stores successful AI-generated mappings in `numa.synch.ai.map`
- Avoids repeated AI calls for the same remote system and model
- Supports active/inactive status for manual override
- Includes transformation scripts for complex value transformations

### 3. Gap Analysis Logging

- Logs detailed issues when AI cannot resolve schema mismatches
- Categorizes issues: missing fields, type mismatches, ambiguities
- Provides AI-generated suggestions for resolution
- Includes sample data for context

### 4. Transparent Payload Transformation

- Automatically transforms incoming payloads using cached mappings
- Renames fields from remote schema to local Odoo schema
- Executes transformation scripts for complex value conversions
- Seamlessly integrates with existing synchronization flow

## Architecture

### Module Dependencies

- **`numa_synch`**: Core synchronization module (required)
- **`numa_ai`**: AI engine module (required)

### Models

#### `numa.synch.ai.map`

Stores AI-generated transformation maps.

**Fields:**
- `remote_token`: Identifier of the remote system
- `model_name`: Target Odoo model name
- `mapping_json`: JSON dictionary mapping remote fields to local fields
- `transformation_script`: Optional Python code for complex transformations
- `confidence_score`: AI confidence score (0.0 to 1.0)
- `active`: Enable/disable this mapping

**Example Mapping:**
```json
{
  "fname": "name",
  "lname": "name",  // Will be concatenated via transformation script
  "email_addr": "email",
  "phone_num": "phone"
}
```

#### `numa.synch.issue`

Logs gap analysis when AI cannot resolve schema mismatches.

**Fields:**
- `batch_id`: Identifier for the batch that triggered the issue
- `remote_token`: Remote system identifier
- `model_name`: Odoo model name with the issue
- `issue_type`: Type of issue (missing_field, type_mismatch, ambiguity, other)
- `description`: AI explanation of the problem
- `remote_field_sample`: Sample data from payload for context
- `suggestion`: AI proposed fix
- `confidence_score`: AI confidence for this analysis
- `resolved`: Manual resolution flag

### Engine Extension

The module extends `numa.synch.engine` by overriding:

1. **`_validate_metadata()`**: Adds AI-assisted fallback logic
2. **`process_incoming_batch_master()`**: Adds payload transformation

## Workflow

### Standard Flow (No AI Needed)

```
1. Incoming batch arrives
2. Standard metadata validation succeeds
3. Process batch normally
```

### AI-Assisted Flow

```
1. Incoming batch arrives
2. Standard metadata validation fails
3. Check cache for existing mapping
   ├─ If found: Apply mapping and proceed
   └─ If not found: Continue to AI analysis
4. Invoke AI to analyze schema mismatch
5. AI returns mapping + confidence + issues
6. Decision:
   ├─ High confidence (>0.9) + No critical issues
   │  └─ Create mapping → Cache → Apply → Proceed
   └─ Low confidence OR Critical issues
      └─ Log gap analysis → Abort with UserError
```

### Payload Transformation Flow

```
1. Batch arrives with remote schema fields
2. Check for cached mapping (remote_token + model_name)
3. If mapping exists:
   ├─ Rename fields according to mapping_json
   ├─ Execute transformation_script if present
   └─ Pass transformed payload to standard processing
4. If no mapping:
   └─ Pass payload unchanged (will trigger AI analysis)
```

## AI Prompt Engineering

The module uses a carefully crafted prompt that instructs the AI to:

1. **Act as a Data Engineer** specializing in schema mapping
2. **Analyze semantic similarity** (not just name matching)
3. **Consider type compatibility** (e.g., string → char, but integer ≠ date)
4. **Identify critical issues** (missing required fields, incompatible types)
5. **Provide confidence scores** conservatively
6. **Return structured JSON** with mapping, confidence, and issues

### Example AI Response

```json
{
  "mapping": {
    "fname": "name",
    "email_addr": "email",
    "phone_num": "phone"
  },
  "confidence_score": 0.95,
  "issues": [
    {
      "type": "missing_field",
      "field": "is_company",
      "description": "Target requires 'is_company' boolean field but source does not provide it",
      "suggestion": "Add default value false or infer from other fields"
    }
  ],
  "critical_issues": false
}
```

## Usage

### Automatic Operation

The module works automatically when installed. No configuration required.

1. **First sync attempt** with non-standard schema:
   - Standard validation fails
   - AI analyzes and generates mapping
   - Mapping is cached
   - Payload is transformed and processed

2. **Subsequent syncs**:
   - Standard validation still fails
   - Cached mapping is found
   - Payload is transformed immediately
   - No AI call needed

### Manual Management

#### Viewing AI Mappings

Navigate to: **Synchronization → AI Assisted → AI Mappings**

- View all cached mappings
- See confidence scores
- Activate/deactivate mappings
- Edit transformation scripts

#### Reviewing Issues

Navigate to: **Synchronization → AI Assisted → Synchronization Issues**

- View unresolved issues
- Read AI suggestions
- Review sample data
- Mark issues as resolved

#### Manual Mapping Creation

You can manually create mappings if needed:

1. Go to **AI Mappings**
2. Click **Create**
3. Fill in:
   - Remote Token
   - Model Name
   - Mapping JSON (field mappings)
   - Transformation Script (optional)
4. Set confidence score
5. Activate

## Transformation Scripts

Transformation scripts are optional Python code snippets that can transform field values.

**Available Variables:**
- `value`: Original field value
- `field_name`: Field name being transformed

**Expected Result:**
- Set `result` variable with transformed value

**Example Script:**

```python
# Concatenate first and last name
if field_name == "name" and isinstance(value, dict):
    fname = value.get("fname", "")
    lname = value.get("lname", "")
    result = f"{fname} {lname}".strip()
else:
    result = value
```

**Security:** Scripts run in a restricted execution context with limited builtins.

## Error Handling

### AI Engine Unavailable

If `numa.ai.engine` is not available or fails:
- Error is logged
- `UserError` is raised with descriptive message
- Batch processing is aborted

### Low Confidence Mappings

If AI returns confidence < 0.9:
- Gap analysis is logged
- Batch processing is aborted
- User must review issues and resolve manually

### Critical Issues Detected

If AI identifies critical issues (e.g., missing required fields):
- Gap analysis is logged
- Batch processing is aborted
- User must address issues before synchronization can proceed

## Best Practices

1. **Review AI Mappings**: After first automatic mapping, review and adjust if needed
2. **Monitor Issues**: Regularly check Synchronization Issues for unresolved problems
3. **Adjust Confidence Thresholds**: If needed, modify code to change confidence requirements
4. **Use Transformation Scripts**: For complex transformations, use transformation scripts
5. **Cache Management**: Deactivate unused mappings to keep cache clean

## Limitations

1. **AI Dependency**: Requires `numa_ai` module and configured AI engine
2. **Performance**: First-time AI analysis adds latency (subsequent calls use cache)
3. **Accuracy**: AI mappings may need manual review and adjustment
4. **Type Conversions**: Complex type conversions may require transformation scripts

## Technical Details

### Override Mechanism

The module uses Odoo's inheritance mechanism:

```python
class NumaSynchEngineAiAssisted(models.Model):
    _name = 'numa.synch.engine'
    _inherit = 'numa.synch.engine'
```

This ensures the AI-assisted logic is automatically used when the module is installed.

### Context Passing

The module passes additional context to parent methods:

```python
context = {
    'slave_token': slave_token,
    'sample_records': records[:5],  # For schema inference
    'batch_id': f"{slave_token}_{len(records)}",
}
```

### Safe Script Execution

Transformation scripts run in a restricted context:

```python
safe_globals = {
    '__builtins__': {
        'str': str, 'int': int, 'float': float, 'bool': bool,
        'len': len, 'list': list, 'dict': dict, 'None': None,
    },
}
```

## Troubleshooting

### Mappings Not Being Used

1. Check mapping is active
2. Verify remote_token matches exactly
3. Check model_name matches exactly
4. Review logs for transformation errors

### AI Analysis Failing

1. Verify `numa_ai` module is installed and configured
2. Check AI engine is accessible
3. Review prompt format (may need adjustment for your AI provider)
4. Check logs for AI engine errors

### Issues Not Being Logged

1. Verify AI is returning proper JSON structure
2. Check `critical_issues` flag in AI response
3. Review confidence score threshold
4. Check database for issue records (may be filtered)

## Future Enhancements

Potential improvements:

1. **Learning from Manual Corrections**: Update mappings based on user edits
2. **Batch Issue Resolution**: Bulk actions for resolving issues
3. **Mapping Versioning**: Track mapping changes over time
4. **Performance Metrics**: Track AI analysis time and cache hit rates
5. **Multi-Model Mapping**: Support for mapping multiple models in one analysis

## Support

For questions, issues, or contributions, please contact the Numa Synch development team.

---

**Document Version:** 1.0  
**Last Updated:** 2024
