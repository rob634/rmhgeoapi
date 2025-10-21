# Handler Contract Documentation Convention

**Date**: 20 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## Problem This Solves

Stage 3 (MosaicJSON) failed because it looked for `cog_blob_name` but Stage 2 (COG creation) returned `cog_blob`. This was a **handler contract mismatch** - no clear documentation of what fields exist in handler outputs.

---

## Solution: Enhanced Docstring Convention

We follow the existing docstring pattern but **explicitly document field names** in return structures.

### Pattern: Handler Returns Documentation

```python
def handler_name(params: dict) -> dict:
    """
    Brief description.

    Args:
        params: Task parameters dict with:
            - field_name (type, REQUIRED/optional): Description
            - nested_field (dict, REQUIRED): Description
                Structure: {"key": type, "key2": type}  # ← Document nested structures

    Returns:
        dict: {
            "success": bool,
            "result": {
                "key_field": str,  # ← Explicitly list field names with types
                "another_field": int,
                ...
            },
            "error": str (if success=False)
        }

    NOTE: Downstream consumers rely on result["key_field"].
    """
```

### Pattern: Consumer Documentation

When a handler **consumes** another handler's output (multi-stage workflows):

```python
def consuming_handler(params: dict) -> dict:
    """
    Brief description.

    Args:
        params: Task parameters containing:
            - previous_results (list, REQUIRED): List from upstream handler
                STRUCTURE: List of result_data dicts from upstream_handler
                Each item: {
                    "success": bool,
                    "result": {
                        "field_name": str,  # ← KEY FIELD consumed by this handler
                        ...
                    }
                }
                See services/upstream_handler.py for full structure.

    NOTE: This handler extracts result["field_name"] from previous_results.
          See upstream_handler.py for upstream contract documentation.
    """
```

---

## Examples from Codebase

### Producer: `services/raster_cog.py`

```python
def create_cog(params: dict) -> dict:
    """
    Create Cloud Optimized GeoTIFF with optional reprojection.

    Args:
        params: Task parameters dict with:
            - blob_url (str, REQUIRED): Azure blob URL with SAS token
            - source_crs (str, REQUIRED): CRS from validation stage
            - raster_type (dict, REQUIRED): Full raster_type dict from validation
                Structure: {"detected_type": str, "optimal_cog_settings": {...}}
            - output_blob_name (str, REQUIRED): Silver container blob path

    Returns:
        dict: {
            "success": bool,
            "result": {
                "cog_blob": str,           # ← KEY: Output COG path (consumed by Stage 3)
                "cog_container": str,
                "source_crs": str,
                "target_crs": str,
                ...
            }
        }

    NOTE: Downstream consumers (Stage 3+) rely on result["cog_blob"] field.
    """
```

### Consumer: `services/raster_mosaicjson.py`

```python
def create_mosaicjson(params: dict, context: dict = None) -> dict:
    """
    Create MosaicJSON virtual mosaic from COG collection.

    Args:
        params: Task parameters containing:
            - previous_results (list, REQUIRED): List of Stage 2 COG creation results
                STRUCTURE: List of result_data dicts from create_cog handler
                Each item: {
                    "success": bool,
                    "result": {
                        "cog_blob": str,  # ← KEY FIELD consumed by this handler
                        ...
                    }
                }
                See services/raster_cog.py create_cog() Returns for full structure.

    NOTE: This handler extracts result["cog_blob"] from each previous_result.
          See raster_cog.py for upstream contract documentation.
    """
    # Implementation correctly accesses:
    for result_data in previous_results:
        result = result_data.get("result", {})
        cog_blob = result.get("cog_blob")  # ← Matches documented contract
```

---

## Key Principles

### 1. **Mark Required vs Optional**
```python
- blob_url (str, REQUIRED): Azure blob URL
- jpeg_quality (int, optional): JPEG quality, default 85
```

### 2. **Document Nested Structures**
```python
- raster_type (dict, REQUIRED): Raster type analysis
    Structure: {"detected_type": str, "optimal_cog_settings": {...}}
```

### 3. **Mark Key Fields for Downstream**
```python
"cog_blob": str,  # ← KEY: Consumed by Stage 3 MosaicJSON creation
```

### 4. **Cross-Reference Dependencies**
```python
NOTE: This handler extracts result["cog_blob"] from previous_results.
      See raster_cog.py for upstream contract documentation.
```

### 5. **Show Full Structure for Complex Returns**
```python
Returns:
    dict: {
        "success": bool,
        "result": {
            "field1": str,  # List ALL fields explicitly
            "field2": int,
            "nested": {
                "subfield": str
            }
        }
    }
```

---

## Benefits

✅ **No new libraries** - Uses existing docstring patterns
✅ **Self-documenting** - Contracts visible in code
✅ **IDE-friendly** - Docstrings show in tooltips
✅ **Prevents mismatches** - Explicit field names catch typos
✅ **Easy to maintain** - Update docs when code changes

---

## Anti-Patterns to Avoid

❌ **Vague documentation**:
```python
Returns:
    dict: {...COG metadata...}  # ← What fields exist?
```

✅ **Explicit documentation**:
```python
Returns:
    dict: {
        "cog_blob": str,
        "cog_container": str,
        ...
    }
```

---

❌ **Undocumented nested access**:
```python
# Code does this but docstring doesn't mention it:
cog_blob = result_data.get("cog_blob")  # ← Wrong level!
```

✅ **Documented nested structure**:
```python
# Docstring says:
#   previous_results: List of {"success": bool, "result": {"cog_blob": str}}
# Code matches:
result = result_data.get("result", {})
cog_blob = result.get("cog_blob")  # ← Correct!
```

---

## Enforcement

- **Code Review**: Check that docstrings explicitly list field names
- **Handler Updates**: When changing return structure, update docstring
- **Consumer Updates**: When consuming a handler, document expected structure
- **Cross-References**: Add "See handler_name.py" notes for dependencies

---

## Related Files

- `services/raster_cog.py` - Example producer with explicit field documentation
- `services/raster_mosaicjson.py` - Example consumer with upstream structure docs
- `services/raster_validation.py` - Example with nested structure documentation
- `jobs/base.py` - JobBase ABC with parameter documentation examples
