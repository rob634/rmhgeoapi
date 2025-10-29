# Platform Layer Boundary Analysis

**Date**: 26 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document all Python-External System boundaries in Platform layer

---

## 🎯 Executive Summary

**Total Boundaries Analyzed**: 3 types
**Critical Issues Found**: 1 (Issue #5 - row indexing)
**Status**: ✅ All issues fixed, Platform layer follows CoreMachine patterns

---

## 1️⃣ Python ↔ PostgreSQL Boundary

### **Outbound (Python → Postgres)**: `✅ CORRECT`

**Pattern**: Use `json.dumps()` to convert Python dict/list to JSON string before INSERT/UPDATE

**CoreMachine Reference**: [infrastructure/postgresql.py:643-646](infrastructure/postgresql.py#L643-L646)
```python
params = (
    json.dumps(job.parameters),      # dict → JSON string
    json.dumps(job.stage_results),   # dict → JSON string
    json.dumps(job.metadata),        # dict → JSON string
)
```

**Platform Implementation**: [triggers/trigger_platform.py:251-252](triggers/trigger_platform.py#L251-L252)
```python
params = (
    json.dumps(request.parameters),  # ✅ Correct - dict → JSON
    json.dumps(request.metadata),    # ✅ Correct - dict → JSON
)
```

**Additional Examples in Platform**:
- Line 306: `json.dumps([job_id])` - ✅ Correct (list → JSON array)
- Line 689: `json.dumps(clean_params, sort_keys=True)` - ✅ Correct (for job ID generation)

**Status**: ✅ **ALL CORRECT** - Platform follows CoreMachine pattern

---

### **Inbound (Postgres → Python)**: `🔴 WAS BROKEN → ✅ NOW FIXED`

**Pattern**: Use **dictionary key access** (`row['column_name']`) with dict_row factory

**Why dict_row?**: [infrastructure/postgresql.py:293](infrastructure/postgresql.py#L293)
```python
conn = psycopg.connect(self.conn_string, row_factory=dict_row)
```

All PostgreSQL connections use `dict_row` factory, which returns rows as **dictionaries** (not tuples).

---

#### **CoreMachine Reference**: [infrastructure/postgresql.py:694-709](infrastructure/postgresql.py#L694-L709)

```python
# Step 1: Build intermediate dict with explicit column mapping
job_data = {
    'job_id': row['job_id'],        # Dictionary access ✅
    'job_type': row['job_type'],    # Dictionary access ✅
    'status': row['status'],        # Dictionary access ✅
    'parameters': row['parameters'] if isinstance(row['parameters'], dict)
                  else json.loads(row['parameters']) if row['parameters'] else {},
    # Handle JSONB: if already dict (psycopg auto-conversion), use as-is
    # Otherwise parse JSON string, or default to {}
}

# Step 2: Pydantic model unpacking for validation
job_record = JobRecord(**job_data)
```

**Key Points**:
1. **Use `row['column']` NOT `row[0]`** - rows are dicts, not tuples
2. **Handle JSONB fields**: Check if already dict (psycopg auto-parses JSONB), otherwise `json.loads()`
3. **Use `.get()` for optional fields**: Handles missing columns gracefully
4. **Pydantic unpacking**: `**job_data` provides validation

---

#### **Platform Implementation - BEFORE (BROKEN)**:

[triggers/trigger_platform.py:318-333](triggers/trigger_platform.py#L318-L333) - **OLD CODE**
```python
def _row_to_record(self, row) -> PlatformRecord:
    """Convert database row to PlatformRecord"""
    return PlatformRecord(
        request_id=row[0],    # ❌ WRONG - integer indexing
        dataset_id=row[1],    # ❌ WRONG - KeyError: 0
        resource_id=row[2],   # ❌ WRONG - rows are dicts!
        # ... etc
    )
```

**Error**: `KeyError: 0` - trying to access dict with integer key

---

#### **Platform Implementation - AFTER (FIXED)**:

[triggers/trigger_platform.py:318-344](triggers/trigger_platform.py#L318-L344) - **NEW CODE**
```python
def _row_to_record(self, row) -> PlatformRecord:
    """
    Convert database row to PlatformRecord.

    Uses CoreMachine pattern (infrastructure/postgresql.py:694-709):
    - Build intermediate dictionary with explicit column name mapping
    - Use Pydantic model unpacking for validation
    - Rows are dict-like (psycopg dict_row factory) NOT tuples
    """
    # Build intermediate dictionary with explicit column mapping
    record_data = {
        'request_id': row['request_id'],        # ✅ Dictionary access
        'dataset_id': row['dataset_id'],        # ✅ Dictionary access
        'resource_id': row['resource_id'],      # ✅ Dictionary access
        'version_id': row['version_id'],        # ✅ Dictionary access
        'data_type': row['data_type'],          # ✅ Dictionary access
        'status': row['status'],                # ✅ Dictionary access
        'job_ids': row['job_ids'] if row['job_ids'] else [],
        'parameters': row['parameters'] if isinstance(row['parameters'], dict)
                      else json.loads(row['parameters']) if row['parameters'] else {},
        'metadata': row['metadata'] if isinstance(row['metadata'], dict)
                    else json.loads(row['metadata']) if row['metadata'] else {},
        'result_data': row.get('result_data'),  # ✅ Optional field
        'created_at': row.get('created_at'),    # ✅ Optional field
        'updated_at': row.get('updated_at')     # ✅ Optional field
    }

    # Use Pydantic unpacking for validation
    return PlatformRecord(**record_data)
```

**Status**: ✅ **FIXED** - Now follows CoreMachine pattern exactly

---

## 2️⃣ Python ↔ Service Bus Boundary

**Pattern**: Use `ServiceBusRepository` + Pydantic `JobQueueMessage` model

### **Outbound (Python → Service Bus)**: `✅ CORRECT (Fixed in Issue #2)`

**CoreMachine Reference**: [core/machine.py:926-933](core/machine.py#L926-L933)
```python
from infrastructure.service_bus import ServiceBusRepository
from core.schema.queue import JobQueueMessage

service_bus_repo = ServiceBusRepository()

queue_message = JobQueueMessage(  # Pydantic model
    job_id=job.job_id,
    job_type=job.job_type,
    parameters=job.parameters,
    stage=next_stage,
    correlation_id=correlation_id
)

message_id = service_bus_repo.send_message(
    config.service_bus_jobs_queue,  # Queue name from config
    queue_message                    # Pydantic model (auto-serializes)
)
```

**Platform Implementation**: [triggers/trigger_platform.py:635-668](triggers/trigger_platform.py#L635-L668)
```python
async def _submit_to_queue(self, job: JobRecord):
    """Submit job to Service Bus jobs queue via repository pattern"""
    from infrastructure.service_bus import ServiceBusRepository
    from core.schema.queue import JobQueueMessage

    service_bus_repo = ServiceBusRepository()  # ✅ Repository pattern

    queue_message = JobQueueMessage(           # ✅ Pydantic model
        job_id=job.job_id,
        job_type=job.job_type,
        parameters=job.parameters,
        stage=1,                                # Platform creates Stage 1 jobs
        correlation_id=str(uuid.uuid4())[:8]
    )

    message_id = service_bus_repo.send_message(
        config.service_bus_jobs_queue,          # ✅ Config-based queue name
        queue_message                            # ✅ Pydantic auto-serialization
    )
```

**Status**: ✅ **CORRECT** - Uses repository pattern, Pydantic models, config-based queue names

---

## 3️⃣ Python ↔ HTTP Boundary (Pydantic)

**Pattern**: Pydantic models handle all HTTP request/response serialization automatically

**Platform Models**: [triggers/trigger_platform.py:101-132](triggers/trigger_platform.py#L101-L132)
```python
class PlatformRequest(BaseModel):
    """Incoming HTTP request from external applications"""
    dataset_id: str
    resource_id: str
    version_id: str
    data_type: str
    source_location: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    client_id: str

class PlatformRecord(BaseModel):
    """Database record for platform requests"""
    request_id: str
    dataset_id: str
    resource_id: str
    version_id: str
    data_type: str
    status: PlatformRequestStatus
    job_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    result_data: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

**HTTP Handler**: [triggers/trigger_platform.py:350-440](triggers/trigger_platform.py#L350-L440)
```python
async def platform_request_submit(req: func.HttpRequest) -> func.HttpResponse:
    # Pydantic parses JSON automatically
    data = req.get_json()
    platform_request = PlatformRequest(**data)  # ✅ Pydantic validation

    # ... processing ...

    # Pydantic serializes to JSON automatically
    return func.HttpResponse(
        json.dumps({
            "success": True,
            "request_id": record.request_id,
            "jobs_created": job_ids
        }),
        mimetype="application/json"
    )
```

**Status**: ✅ **CORRECT** - Pydantic handles all serialization/validation

---

## 🔍 Summary of All Boundary Crossings in Platform Layer

| Boundary | Direction | Location | Pattern | Status |
|----------|-----------|----------|---------|--------|
| **PostgreSQL** | **Python → DB** | Line 251-252 | `json.dumps()` for JSONB | ✅ Correct |
| | | Line 306 | `json.dumps([job_id])` for array | ✅ Correct |
| **PostgreSQL** | **DB → Python** | Line 318-344 | `_row_to_record()` with dict access | ✅ Fixed (was Issue #5) |
| **Service Bus** | **Python → Queue** | Line 635-668 | ServiceBusRepository + Pydantic | ✅ Correct (Fixed Issue #2) |
| **HTTP** | **Request → Python** | Line 350-440 | Pydantic PlatformRequest | ✅ Correct |
| **HTTP** | **Python → Response** | Line 350-440 | `json.dumps()` for responses | ✅ Correct |

---

## 🎓 Lessons Learned

### **Root Cause of Issue #5**:
Platform layer was written **before** understanding that `PostgreSQLRepository` uses `dict_row` factory. The code assumed tuple-style integer indexing (`row[0]`, `row[1]`) instead of dictionary key access (`row['column']`).

### **Why This Happened**:
1. **Implicit behavior**: `row_factory=dict_row` set at connection level (line 293)
2. **Not documented in Platform code**: No comments explaining row format
3. **Different from Python's default**: sqlite3 uses tuples by default, psycopg uses tuples unless `row_factory` specified

### **Prevention Strategy**:
✅ **Always follow CoreMachine patterns** for boundary crossings
✅ **Document boundary assumptions** in code comments
✅ **Reference CoreMachine implementation** when implementing new features
✅ **Test boundary crossings early** (unit tests with real DB connections)

---

## ✅ Final Status

**All Platform boundaries now follow CoreMachine patterns**:
- ✅ PostgreSQL: Dictionary access + JSONB handling
- ✅ Service Bus: Repository pattern + Pydantic models
- ✅ HTTP: Pydantic auto-serialization

**Ready for deployment and testing.**

---

**Document Version**: 1.0
**Last Updated**: 26 OCT 2025 00:30 UTC
**Military Date Format**: 26 OCT 2025
