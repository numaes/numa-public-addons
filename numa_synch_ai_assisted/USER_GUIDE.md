# Numa Synch AI Assisted - User Guide

## Introduction

The **Numa Synch AI Assisted** module automatically handles schema mismatches when synchronizing with non-Odoo systems or systems with modified schemas. This guide explains how to use and manage the AI-assisted features.

## Quick Start

### Installation

1. Install the module: **Apps → Search "Numa Synch AI Assisted" → Install**
2. Ensure `numa_synch` and `numa_ai` modules are installed
3. Configure your AI engine in `numa_ai` module settings

### First Synchronization

When you first attempt to synchronize with a non-standard system:

1. **Standard validation fails** (expected)
2. **AI automatically analyzes** the schema mismatch
3. **Mapping is generated and cached** (if confidence is high)
4. **Synchronization proceeds** with transformed payload

**No action required** - the module handles everything automatically!

## Managing AI Mappings

### Viewing Mappings

Navigate to: **Synchronization → AI Assisted → AI Mappings**

You'll see a list of all cached mappings with:
- Remote Token (system identifier)
- Model Name (Odoo model)
- Confidence Score
- Active status

### Understanding Mappings

Each mapping shows:
- **Remote Token**: The identifier of the external system
- **Model Name**: The Odoo model being synchronized
- **Mapping JSON**: Field name mappings (e.g., `{"fname": "name"}`)
- **Confidence Score**: How confident the AI was (0.0 to 1.0)
- **Transformation Script**: Optional code for complex transformations

### Activating/Deactivating Mappings

1. Open a mapping record
2. Click **Deactivate** or **Activate** button
3. Deactivated mappings won't be used for transformation

### Editing Mappings

You can manually edit mappings if needed:

1. Open the mapping
2. Edit the **Mapping JSON** field directly**
3. Format: `{"remote_field": "local_field", ...}`
4. Save changes

**Example:**
```json
{
  "customer_name": "name",
  "email_address": "email",
  "phone_number": "phone"
}
```

### Adding Transformation Scripts

For complex value transformations, add a Python script:

1. Open a mapping record
2. Edit the **Transformation Script** field
3. Write Python code that sets `result` variable

**Example Script:**
```python
# Combine first and last name
if field_name == "name":
    if isinstance(value, dict):
        fname = value.get("fname", "")
        lname = value.get("lname", "")
        result = f"{fname} {lname}".strip()
    else:
        result = value
else:
    result = value
```

## Managing Synchronization Issues

### Viewing Issues

Navigate to: **Synchronization → AI Assisted → Synchronization Issues**

Issues are automatically created when:
- AI confidence is too low (< 0.9)
- Critical problems are detected (missing required fields, etc.)

### Understanding Issue Types

- **Missing Required Field**: Target model requires a field that source doesn't provide
- **Type Mismatch**: Field types are incompatible (e.g., string vs integer)
- **Ambiguity**: Multiple source fields could map to the same target field
- **Other**: General schema incompatibility

### Resolving Issues

1. **Review the issue**:
   - Read the description
   - Check the remote field sample
   - Review AI suggestions

2. **Take action**:
   - Fix the source system schema (if possible)
   - Create a manual mapping with defaults
   - Add transformation script to handle missing fields

3. **Mark as resolved**:
   - Click **Mark as Resolved** button
   - Issue moves to resolved filter

### Filtering Issues

Use filters to find specific issues:
- **Unresolved**: Only show open issues
- **Resolved**: Show completed issues
- **By Type**: Filter by issue type
- **By Model**: Filter by model name

## Common Scenarios

### Scenario 1: External System with Different Field Names

**Problem:** External system uses `customer_name` but Odoo expects `name`

**Solution:**
1. First sync attempt triggers AI analysis
2. AI generates mapping: `{"customer_name": "name"}`
3. Mapping is cached automatically
4. Future syncs use cached mapping

**Manual Override:**
- Edit mapping if AI got it wrong
- Adjust confidence threshold if needed

### Scenario 2: Missing Required Fields

**Problem:** Odoo requires `is_company` but external system doesn't provide it

**Solution:**
1. AI detects missing field
2. Issue is logged with suggestion
3. Add transformation script with default:
   ```python
   if field_name == "is_company":
       result = False  # Default value
   else:
       result = value
   ```
4. Or update source system to provide the field

### Scenario 3: Complex Field Transformation

**Problem:** External system has separate `first_name` and `last_name`, Odoo has single `name`

**Solution:**
1. Create mapping: `{"first_name": "name", "last_name": "name"}`
2. Add transformation script:
   ```python
   if field_name == "name":
       # Get both values from context (requires custom logic)
       result = f"{first_name} {last_name}".strip()
   else:
       result = value
   ```

**Note:** This scenario may require custom implementation in the transformation logic.

## Best Practices

### 1. Review After First Sync

After the first automatic mapping:
- Review the generated mapping
- Verify field mappings are correct
- Adjust if needed

### 2. Monitor Issues Regularly

- Check unresolved issues weekly
- Address critical issues promptly
- Use suggestions as starting points

### 3. Use Transformation Scripts Wisely

- Keep scripts simple and readable
- Test scripts with sample data
- Document complex transformations

### 4. Maintain Clean Cache

- Deactivate unused mappings
- Remove mappings for deprecated systems
- Review confidence scores periodically

## Troubleshooting

### Mappings Not Working

**Symptoms:** Payloads not being transformed

**Solutions:**
1. Verify mapping is **Active**
2. Check **Remote Token** matches exactly
3. Verify **Model Name** is correct
4. Review logs for transformation errors

### AI Analysis Not Running

**Symptoms:** Standard validation fails but no AI analysis

**Solutions:**
1. Verify `numa_ai` module is installed
2. Check AI engine is configured
3. Review module dependencies
4. Check logs for AI engine errors

### Low Confidence Mappings

**Symptoms:** Mappings created but confidence is low

**Solutions:**
1. Review the mapping manually
2. Adjust field mappings if needed
3. Add transformation scripts for edge cases
4. Consider manual mapping creation

### Issues Not Appearing

**Symptoms:** Problems occur but no issues logged

**Solutions:**
1. Check confidence threshold (default: 0.9)
2. Verify AI is returning proper structure
3. Check database directly for issue records
4. Review filter settings in issue view

## Advanced Usage

### Manual Mapping Creation

Create mappings manually for predictable scenarios:

1. Go to **AI Mappings → Create**
2. Enter Remote Token
3. Enter Model Name
4. Write Mapping JSON
5. Set confidence score (1.0 for manual)
6. Add transformation script if needed
7. Activate

### Batch Operations

Currently, mappings and issues must be managed individually. Future versions may include:
- Bulk activation/deactivation
- Batch issue resolution
- Import/export mappings

### Integration with Custom Code

You can programmatically:
- Create mappings via API
- Query issues for monitoring
- Trigger AI analysis manually

**Example:**
```python
# Create mapping programmatically
mapping = env['numa.synch.ai.map'].create({
    'remote_token': 'external-system-123',
    'model_name': 'res.partner',
    'mapping_json': '{"fname": "name"}',
    'confidence_score': 1.0,
    'active': True,
})
```

## Support

For additional help:
- Review module README.md
- Check Odoo logs for detailed error messages
- Contact system administrator
- Consult Numa Synch documentation

---

**Guide Version:** 1.0  
**Last Updated:** 2024
