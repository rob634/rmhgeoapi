# Handler Contract Patterns - Preventing Parameter Mismatches

**Date**: 20 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Design Document

## Problem Statement

The MosaicJSON workflow failed at Stage 3 because of a **handler contract mismatch**:

```python
# What create_cog RETURNS:
{
    "success": True,
    "result": {
        "cog_blob": "path/to/file.tif",  # ← Field name
        ...
    }
}

# What create_mosaicjson EXPECTED:
cog_blob = result_data.get("cog_blob_name")  # ← Wrong field name AND wrong nesting level
```

**Root Cause**: No enforced contract between handler outputs and consumer expectations.

---

## Current State: Documentation Patterns

### 1. JobBase ABC (jobs/base.py)

**Strengths**:
- ✅ Enforces method signatures at import time via `@abstractmethod`
- ✅ Comprehensive docstrings with examples
- ✅ Clear parameter documentation in docstrings
- ✅ Documents return structures in examples

**Pattern**:
```python
class JobBase(ABC):
    @staticmethod
    @abstractmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameter dicts for a stage.

        Args:
            stage: Stage number (1-based, sequential)
            job_params: Job parameters from submission
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage (for fan-out patterns)
                             STRUCTURE: List[result_data_dict]
                             Each result_data_dict = task.result_data from completed tasks

        Returns:
            List of task parameter dicts, each containing:
            - task_id (str): Unique task identifier
            - task_type (str): Handler name from services registry
            - parameters (dict): Task-specific parameters
            - metadata (dict, optional): Additional task metadata
        """
```

### 2. Handler Documentation (services/*.py)

**Strengths**:
- ✅ Clear parameter documentation in docstrings
- ✅ Return structure documented in module-level docstrings
- ✅ Examples of input/output structures

**Pattern** (from `raster_validation.py`):
```python
"""
Validation Result Structure:
    {
        "success": True/False,
        "result": {
            "valid": True,
            "source_blob": "sample.tif",
            "band_count": 3,
            "dtype": "uint8",

            "raster_type": {
                "detected_type": "rgb",
                "confidence": "HIGH",
                "evidence": ["3 bands, uint8 (standard RGB)"],
                "optimal_cog_settings": {
                    "compression": "jpeg",
                    "jpeg_quality": 85
                }
            }
        }
    }
"""

def validate_raster(params: dict) -> dict:
    """
    Args:
        params: Task parameters dict with:
            - blob_url: Azure blob URL for raster (with SAS token)
            - raster_type: Expected raster type or 'auto'
            - strict_mode: Enforce strict validation

    Returns:
        dict: See module docstring for structure
    """
```

**Pattern** (from `raster_cog.py`):
```python
def create_cog(params: dict) -> dict:
    """
    Args:
        params: Task parameters dict with:
            - blob_url: Azure blob URL for bronze raster (with SAS token)
            - source_crs: CRS from validation stage
            - target_crs: Target CRS (default: EPSG:4326)
            - raster_type: Detected raster type from validation
            - output_blob_name: Silver container blob path
            - container_name: Bronze container name
            - blob_name: Bronze blob name

    Returns:
        dict: {
            "success": True/False,
            "result": {...COG metadata...},
            "error": "ERROR_CODE" (if failed)
        }
    """
```

---

## Gap Analysis: What's Missing

### 1. **Handler Output Schema Definition**

**Current**: Inline docstrings describe return structure
**Problem**: Not machine-readable, not enforceable

**Example of Current Approach**:
```python
# In raster_cog.py docstring:
"""
Returns:
    dict: {
        "success": True/False,
        "result": {...COG metadata...}
    }
"""

# Actual return structure buried in code (line 340+):
return {
    "success": True,
    "result": {
        "cog_blob": output_blob_name,  # ← Consumer must discover this field
        "cog_container": silver_container,
        ...
    }
}
```

### 2. **Handler Input Schema Validation**

**Current**: Manual validation in handler code
**Problem**: No type checking, easy to miss required fields

**Example**:
```python
def create_cog(params: dict) -> dict:
    blob_url = params.get('blob_url')  # No validation that it's required
    source_crs = params.get('source_crs')  # No validation
    raster_type = params.get('raster_type', {}).get('detected_type')  # Assumes nested structure
```

### 3. **Inter-Stage Contract Documentation**

**Current**: Comments in job class
**Problem**: Consumer must read producer code to discover structure

**Example of Current Problem**:
```python
# In process_raster_collection.py Stage 2 task creation:
validation_result = previous_results[i]  # What's the structure?
# Have to look at CoreMachine code to discover:
# previous_results = [task.result_data, task.result_data, ...]
# Then look at validate_raster handler to see result_data structure
```

---

## Proposed Solutions (3 Options)

### **Option 1: Enhanced Documentation** (Lowest Effort)

Add structured documentation to all handlers and jobs.

**Implementation**:

```python
# In services/raster_cog.py:

# === HANDLER CONTRACT ===
# INPUT SCHEMA:
#   - blob_url (str, required): Azure blob URL with SAS token
#   - source_crs (str, required): Source CRS from validation
#   - target_crs (str, optional): Target CRS, default EPSG:4326
#   - raster_type (dict, required): Full raster_type dict from validation
#       Structure: {"detected_type": str, "optimal_cog_settings": {...}}
#   - output_blob_name (str, required): Output path in silver container
#
# OUTPUT SCHEMA:
#   {
#       "success": bool,
#       "result": {
#           "cog_blob": str,        # ← FIELD NAME DOCUMENTED
#           "cog_container": str,
#           "source_crs": str,
#           ...
#       },
#       "error": str (if success=False)
#   }
# === END CONTRACT ===

def create_cog(params: dict) -> dict:
    """Create Cloud Optimized GeoTIFF with optional reprojection."""
```

**In Job Classes**:
```python
# In process_raster_collection.py:

@staticmethod
def _create_stage_2_tasks(
    job_id: str,
    job_params: Dict[str, Any],
    previous_results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Stage 2: Create COG tasks for validated tiles (fan-out).

    CONSUMES Stage 1 OUTPUT:
        previous_results structure: List[result_data_dict]
        Each result_data_dict from validate_raster handler:
        {
            "success": bool,
            "result": {
                "source_crs": str,              # ← REQUIRED for COG creation
                "raster_type": {                # ← REQUIRED for COG creation
                    "detected_type": str,
                    "optimal_cog_settings": {...}
                },
                "recommended_compression": str,
                "recommended_resampling": str
            }
        }

    PRODUCES Stage 2 INPUT:
        Task parameters for create_cog handler (see raster_cog.py contract)
    """
```

**Pros**:
- ✅ Low implementation effort
- ✅ No code changes required
- ✅ Self-documenting
- ✅ Works with existing patterns

**Cons**:
- ❌ Not machine-readable
- ❌ Not enforceable
- ❌ Can drift out of sync with code

---

### **Option 2: Pydantic Schema Definitions** (Medium Effort)

Define input/output schemas as Pydantic models.

**Implementation**:

```python
# In services/schemas/handler_schemas.py (NEW FILE):

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

# === HANDLER OUTPUT SCHEMAS ===

class RasterTypeResult(BaseModel):
    """Raster type analysis from validation."""
    detected_type: str = Field(..., description="Detected raster type")
    confidence: str = Field(..., description="Detection confidence")
    optimal_cog_settings: Dict[str, Any] = Field(..., description="Recommended COG settings")

class ValidateRasterOutput(BaseModel):
    """Output schema for validate_raster handler."""
    success: bool
    result: Dict[str, Any] = Field(..., description="Validation result")
    error: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "result": {
                    "source_crs": "EPSG:4326",
                    "raster_type": {
                        "detected_type": "rgb",
                        "optimal_cog_settings": {...}
                    }
                }
            }
        }

class CreateCogOutput(BaseModel):
    """Output schema for create_cog handler."""
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    # Document key fields in result
    class ResultFields:
        cog_blob: str = Field(..., description="Output COG blob path")
        cog_container: str = Field(..., description="Silver container name")
        source_crs: str
        target_crs: str

# === HANDLER INPUT SCHEMAS ===

class CreateCogInput(BaseModel):
    """Input schema for create_cog handler."""
    blob_url: str = Field(..., description="Bronze raster URL with SAS")
    source_crs: str = Field(..., description="Source CRS from validation")
    target_crs: str = Field(default="EPSG:4326")
    raster_type: RasterTypeResult = Field(..., description="Full raster_type from validation")
    output_blob_name: str = Field(..., description="Output path in silver")
    container_name: str
    blob_name: str
```

**Handler Updates**:
```python
def create_cog(params: dict) -> dict:
    """
    Create Cloud Optimized GeoTIFF.

    Schema: services.schemas.handler_schemas.CreateCogInput → CreateCogOutput
    """
    # Optional: Validate input
    try:
        validated = CreateCogInput(**params)
    except ValidationError as e:
        return {"success": False, "error": "PARAMETER_ERROR", "message": str(e)}

    # ... rest of implementation
```

**Job Class Updates**:
```python
def _create_stage_2_tasks(
    job_id: str,
    job_params: Dict[str, Any],
    previous_results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Stage 2: Create COG tasks.

    Consumes: ValidateRasterOutput.result (from previous_results)
    Produces: CreateCogInput (as task parameters)
    """
    for result_data in previous_results:
        # Type hint helps IDE
        result: ValidateRasterOutput = result_data  # Type hint for clarity

        # Access with confidence - schema documents structure
        source_crs = result["result"]["source_crs"]
        raster_type = result["result"]["raster_type"]
```

**Pros**:
- ✅ Machine-readable schemas
- ✅ Optional runtime validation
- ✅ IDE autocomplete support
- ✅ Can generate API documentation
- ✅ Type hints improve code clarity

**Cons**:
- ❌ Medium implementation effort
- ❌ Requires updating all handlers
- ❌ Adds Pydantic dependency overhead

---

### **Option 3: TypedDict + Type Hints** (Low-Medium Effort)

Use Python's built-in `TypedDict` for type hinting without Pydantic overhead.

**Implementation**:

```python
# In services/types/handler_types.py (NEW FILE):

from typing import TypedDict, Literal, Optional, List

# === HANDLER OUTPUT TYPES ===

class RasterTypeResult(TypedDict):
    """Raster type analysis from validation."""
    detected_type: str
    confidence: Literal["VERY_HIGH", "HIGH", "MEDIUM", "LOW"]
    optimal_cog_settings: dict

class ValidateRasterResult(TypedDict):
    """Result field from validate_raster output."""
    source_crs: str
    raster_type: RasterTypeResult
    recommended_compression: str
    recommended_resampling: str
    band_count: int
    dtype: str

class ValidateRasterOutput(TypedDict):
    """Complete output from validate_raster handler."""
    success: bool
    result: ValidateRasterResult
    error: Optional[str]

class CreateCogResult(TypedDict):
    """Result field from create_cog output."""
    cog_blob: str  # ← EXPLICITLY TYPED
    cog_container: str
    source_crs: str
    target_crs: str
    compression: str

class CreateCogOutput(TypedDict):
    """Complete output from create_cog handler."""
    success: bool
    result: CreateCogResult
    error: Optional[str]

# === HANDLER INPUT TYPES ===

class CreateCogInput(TypedDict):
    """Input parameters for create_cog handler."""
    blob_url: str
    source_crs: str
    target_crs: str  # Optional fields should use NotRequired in Python 3.11+
    raster_type: RasterTypeResult
    output_blob_name: str
    container_name: str
    blob_name: str
```

**Handler Updates**:
```python
from services.types.handler_types import CreateCogInput, CreateCogOutput

def create_cog(params: CreateCogInput) -> CreateCogOutput:
    """
    Create Cloud Optimized GeoTIFF.

    Type annotations provide contract enforcement via mypy/pyright.
    """
    blob_url = params['blob_url']  # IDE knows this exists and is str
    source_crs = params['source_crs']
    raster_type = params['raster_type']  # IDE knows structure

    # ... implementation

    return {
        "success": True,
        "result": {
            "cog_blob": output_path,  # Type checker verifies this matches CreateCogResult
            ...
        }
    }
```

**Job Class Updates**:
```python
from services.types.handler_types import ValidateRasterOutput, CreateCogInput
from typing import List

def _create_stage_2_tasks(
    job_id: str,
    job_params: Dict[str, Any],
    previous_results: List[ValidateRasterOutput]  # ← Type hint!
) -> List[Dict[str, Any]]:
    """
    Stage 2: Create COG tasks.

    Args:
        previous_results: Typed as ValidateRasterOutput for IDE support
    """
    for result_data in previous_results:
        # IDE autocomplete works!
        source_crs = result_data["result"]["source_crs"]  # Type checker validates
        raster_type = result_data["result"]["raster_type"]

        task_params: CreateCogInput = {  # Type checker validates all required fields
            "blob_url": blob_url,
            "source_crs": source_crs,
            "raster_type": raster_type,
            "output_blob_name": output_blob,
            ...
        }
```

**Pros**:
- ✅ Built-in Python feature (no dependencies)
- ✅ IDE autocomplete and type checking
- ✅ Zero runtime overhead
- ✅ Works with mypy/pyright for validation
- ✅ Self-documenting code

**Cons**:
- ❌ No runtime validation (unless using mypy)
- ❌ Requires Python 3.8+ (we have 3.12)
- ❌ Medium implementation effort

---

## Recommendation

**Adopt Option 3 (TypedDict) + Enhanced Documentation (Option 1)**

**Rationale**:
1. **TypedDict** provides type safety without runtime overhead
2. **IDE support** catches errors during development
3. **Enhanced documentation** provides human-readable contracts
4. **No new dependencies** (uses Python stdlib)
5. **Incremental adoption** - can add types gradually

**Implementation Priority**:
1. Create `services/types/handler_types.py` with all handler I/O types
2. Update core handlers (validate_raster, create_cog, create_mosaicjson)
3. Add structured documentation to all handlers
4. Update process_raster_collection.py to use typed previous_results
5. Configure mypy/pyright in CI pipeline

---

## Example: Fixed MosaicJSON Bug with Types

**Before (Bug)**:
```python
# In raster_mosaicjson.py (WRONG):
for result_data in previous_results:
    cog_blob = result_data.get("cog_blob_name")  # ← Wrong field name, wrong level
```

**After (With Types)**:
```python
from services.types.handler_types import CreateCogOutput

def create_mosaicjson(params: dict, context: dict = None) -> dict:
    previous_results: List[CreateCogOutput] = params.get("previous_results", [])

    cog_blobs = []
    for result_data in previous_results:
        if result_data["success"]:
            # IDE autocomplete shows: result_data["result"]["cog_blob"]
            cog_blob = result_data["result"]["cog_blob"]  # ← Correct!
            cog_blobs.append(cog_blob)
```

**Type Checker Output** (if we had written it wrong):
```
error: TypedDict "CreateCogOutput" has no key "cog_blob_name"
note: Did you mean "result"?
```

---

## Action Items

1. **Create type definitions file** - Define all handler I/O types
2. **Update handler signatures** - Add type hints to function signatures
3. **Add structured contracts** - Add contract documentation headers
4. **Update job classes** - Use typed previous_results parameters
5. **Configure type checking** - Add mypy to CI pipeline
6. **Document patterns** - Update ARCHITECTURE_REFERENCE.md with type contract patterns

---

## Related Files

- `jobs/base.py` - Current ABC with method signature enforcement
- `services/raster_cog.py` - Example handler with docstring documentation
- `services/raster_validation.py` - Example handler with result structure docs
- `core/machine.py` - CoreMachine passes previous_results to jobs
- `process_raster_collection.py` - Multi-stage job with inter-stage dependencies
