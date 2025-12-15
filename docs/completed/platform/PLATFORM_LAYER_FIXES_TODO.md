# Platform Layer Fixes TODO

**Date Created**: 26 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Platform triggers load successfully, but have runtime issues

## 🎯 Context

The Platform orchestration layer was added on **25 OCT 2025** to create a "Platform-as-a-Service" layer above CoreMachine. This implements the fractal "turtle above CoreMachine" pattern where external applications (like DDH - Development Data Hub) can submit high-level requests that get translated into CoreMachine jobs.

**Architecture Pattern**:
```
External App (DDH) → Platform Layer → CoreMachine → Tasks
                      (trigger_platform.py)  (core/machine.py)
```

**Files Involved**:
- `triggers/trigger_platform.py` - Platform request submission endpoint
- `triggers/trigger_platform_status.py` - Platform status monitoring endpoint
- See: `docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md` for complete architecture guide

---

## ✅ COMPLETED - Import Errors Fixed (26 OCT 2025)

### Issue: Critical ImportError Blocking Function App

**Problems Fixed**:
1. ✅ Wrong config function: `get_settings()` → `get_config()`
2. ✅ Wrong module path: `from core.models import JobRecord` → `from core.models.job import JobRecord`
3. ✅ Wrong property name: `settings.SERVICE_BUS_CONNECTION_STRING` → `config.service_bus_connection_string`
4. ✅ Added comprehensive error handling with verbose logging for all imports

**Result**: Function app now starts successfully, health endpoint returns 200 OK, Platform triggers load without errors.

**Git Commit**: [Include commit hash after committing this file]

---

## 🔴 CRITICAL - Issue #1: CoreMachine Instantiation Missing Required Registries

**Location**: `triggers/trigger_platform.py:438`

**Current Code (BROKEN)**:
```python
def __init__(self):
    self.platform_repo = PlatformRepository()
    self.job_repo = JobRepository()
    self.core_machine = CoreMachine()  # ❌ Missing required parameters
```

**Problem**:
CoreMachine requires **explicit job and handler registries** passed as constructor arguments. The decorator-based auto-discovery was removed on 10 SEP 2025 due to import timing issues.

**Error When Called**:
```
TypeError: __init__() missing 2 required positional arguments: 'all_jobs' and 'all_handlers'
```

**Fix Required**:
```python
def __init__(self):
    from jobs import ALL_JOBS
    from services import ALL_HANDLERS

    self.platform_repo = PlatformRepository()
    self.job_repo = JobRepository()
    self.core_machine = CoreMachine(
        all_jobs=ALL_JOBS,
        all_handlers=ALL_HANDLERS
    )
```

**Reference**: See `core/machine.py:116-149` for CoreMachine constructor signature

**Impact**: 🔴 **CRITICAL** - Platform endpoints will crash immediately when `PlatformOrchestrator()` is instantiated

**Effort**: 5 minutes

**Testing After Fix**:
```bash
# Test Platform request submission
curl -X POST 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit' \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_id": "test-dataset",
    "resource_id": "test-resource",
    "version_id": "v1.0",
    "data_type": "raster",
    "source_location": "https://rmhazuregeo.blob.core.windows.net/bronze/test.tif",
    "parameters": {},
    "client_id": "test"
  }'
```

---

## 🟠 MEDIUM - Issue #2: Direct Service Bus Usage Instead of Repository Pattern

**Location**: `triggers/trigger_platform.py:621-643`

**Current Code (INCONSISTENT)**:
```python
async def _submit_to_queue(self, job: JobRecord):
    """Submit job to Service Bus jobs queue"""
    try:
        client = ServiceBusClient.from_connection_string(
            config.service_bus_connection_string  # ✅ Property name fixed
        )

        with client:
            sender = client.get_queue_sender(queue_name="jobs")  # ❌ Hardcoded

            message = ServiceBusMessage(
                json.dumps({  # ❌ Manual JSON serialization
                    'job_id': job.job_id,
                    'job_type': job.job_type
                })
            )

            sender.send_messages(message)
```

**Problems**:
1. **Violates repository pattern** - creates `ServiceBusClient` directly instead of using `ServiceBusRepository`
2. **Hardcoded queue name** - uses `"jobs"` instead of `config.service_bus_jobs_queue`
3. **Manual serialization** - uses `json.dumps()` instead of Pydantic `JobQueueMessage` model
4. **Connection management** - creates new client per message (inefficient)

**Fix Required**:
```python
async def _submit_to_queue(self, job: JobRecord):
    """Submit job to Service Bus jobs queue via repository pattern"""
    try:
        import uuid
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage

        # Use repository pattern (handles connection pooling, retries, etc.)
        service_bus_repo = ServiceBusRepository()

        # Use Pydantic message model (automatic serialization + validation)
        queue_message = JobQueueMessage(
            job_id=job.job_id,
            job_type=job.job_type,
            parameters=job.parameters,
            stage=1,  # Platform always creates Stage 1 jobs
            correlation_id=str(uuid.uuid4())[:8]
        )

        # Send via repository (uses config for queue name)
        message_id = service_bus_repo.send_message(
            config.service_bus_jobs_queue,
            queue_message
        )

        logger.info(f"Submitted job {job.job_id} to jobs queue (message_id: {message_id})")

    except Exception as e:
        logger.error(f"Failed to submit job to queue: {e}", exc_info=True)
        raise
```

**Reference**: See `core/machine.py:926-933` for correct Service Bus usage pattern

**Impact**: 🟠 **MEDIUM** - Works but violates architecture, inconsistent with rest of codebase

**Effort**: 10 minutes

**Why Fix**: Architectural consistency, uses connection pooling, automatic retry logic, proper error handling

---

## 🟡 LOW - Issue #3: Platform Schema Initialization on Every Request

**Location**: `triggers/trigger_platform.py:142-197`

**Current Code (INEFFICIENT)**:
```python
class PlatformRepository(PostgreSQLRepository):
    def __init__(self):
        super().__init__()
        self._ensure_schema()  # ❌ Runs on every repository instantiation

    def _ensure_schema(self):
        """Create platform schema and tables if they don't exist"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # 50+ lines of CREATE SCHEMA, CREATE TABLE, CREATE INDEX SQL
                cur.execute("CREATE SCHEMA IF NOT EXISTS platform")
                cur.execute("CREATE TABLE IF NOT EXISTS platform.requests ...")
                # ... many more statements
```

**Problems**:
1. **Runs on every HTTP request** - `PlatformRepository()` is instantiated per request in `PlatformOrchestrator.__init__()`
2. **Database operations in constructor** - violates separation of concerns
3. **No coordination with schema deployment system** - bypasses `triggers/schema_pydantic_deploy.py`
4. **Potential conflicts** - could interfere with `/api/db/schema/redeploy` endpoint

**Fix Required**:

**Step 1**: Change `PlatformRepository.__init__()` to validation only:
```python
def __init__(self):
    super().__init__()
    # Remove _ensure_schema() call

    # Add lightweight validation instead
    self._validate_schema_exists()

def _validate_schema_exists(self):
    """Verify platform schema exists (doesn't create)"""
    with self._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'platform'
                )
            """)
            if not cur.fetchone()[0]:
                raise RuntimeError(
                    "Platform schema not found. Deploy schema via "
                    "POST /api/db/schema/redeploy?confirm=yes"
                )
```

**Step 2**: Add Platform schema to `triggers/schema_pydantic_deploy.py`:
```python
# In schema_deployment() function, after app schema deployment:

# Deploy Platform schema (if enabled)
if deploy_platform_schema:
    logger.info("🔄 Deploying Platform schema...")
    platform_sql = """
    -- Platform schema for request tracking
    CREATE SCHEMA IF NOT EXISTS platform;

    CREATE TABLE IF NOT EXISTS platform.requests (
        request_id VARCHAR(32) PRIMARY KEY,
        dataset_id VARCHAR(255) NOT NULL,
        resource_id VARCHAR(255) NOT NULL,
        version_id VARCHAR(50) NOT NULL,
        data_type VARCHAR(50) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        job_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        result_data JSONB,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_platform_status
        ON platform.requests(status);
    CREATE INDEX IF NOT EXISTS idx_platform_dataset
        ON platform.requests(dataset_id);
    CREATE INDEX IF NOT EXISTS idx_platform_created
        ON platform.requests(created_at DESC);

    CREATE TABLE IF NOT EXISTS platform.request_jobs (
        request_id VARCHAR(32) NOT NULL,
        job_id VARCHAR(32) NOT NULL,
        job_type VARCHAR(100) NOT NULL,
        sequence INTEGER NOT NULL DEFAULT 1,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (request_id, job_id)
    );
    """
    cursor.execute(platform_sql)
```

**Impact**: 🟡 **LOW** - Works but inefficient (unnecessary DB operations on every request), potential schema conflicts

**Effort**: 20 minutes

**Why Fix**:
- Performance improvement (no DB ops on every request)
- Centralized schema management
- Consistent with app schema deployment pattern

---

## 🟡 LOW - Issue #4: Duplicate Job Submission Logic

**Location**: `triggers/trigger_platform.py:577-617`

**Current Code**:
```python
async def _create_coremachine_job(self, request: PlatformRecord,
                                   job_type: str, parameters: Dict[str, Any]):
    # Generate job ID (duplicates trigger_job_submit.py)
    job_id = self._generate_job_id(job_type, job_params)

    # Create job record (duplicates trigger_job_submit.py)
    job_record = JobRecord(...)

    # Store in database (duplicates trigger_job_submit.py)
    stored_job = self.job_repo.create_job(job_record)

    # Submit to queue (duplicates trigger_job_submit.py via Issue #2)
    await self._submit_to_queue(stored_job)
```

**Problem**:
Duplicates the entire job submission flow from `triggers/trigger_job_submit.py`:
- Job ID generation logic
- JobRecord creation
- Database persistence
- Queue submission

**⚠️ INTENTIONAL DUPLICATION (Per Robert 26 OCT 2025)**:
> "duplicate job submission logic is intentional so we can test both systems - it will be reconciled in the near future"

**Why This Exists**:
- Platform layer is experimental
- Allows testing Platform submission independently from standard job submission
- Will be refactored once patterns stabilize

**Future Refactoring Options**:

**Option A: Shared Job Submission Service**
```python
# Create services/job_submission.py
class JobSubmissionService:
    @staticmethod
    def submit_job(job_type: str, parameters: Dict[str, Any],
                   metadata: Optional[Dict] = None) -> str:
        """Shared job submission logic used by all entry points"""
        # All job submission logic here
        # - Generate job ID
        # - Create JobRecord
        # - Validate parameters
        # - Check idempotency
        # - Persist to database
        # - Queue to Service Bus
        return job_id

# Both trigger_job_submit.py and trigger_platform.py use this:
job_id = JobSubmissionService.submit_job(job_type, params)
```

**Option B: HTTP Call to Standard Endpoint**
```python
# Platform calls standard job submission endpoint
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        f"http://localhost/api/jobs/submit/{job_type}",
        json=parameters
    )
    return response.json()['job_id']
```

**Impact**: 🟡 **LOW** - Maintenance burden (two places to update job submission logic), but intentional for testing

**Effort**: 30 minutes (when ready to refactor)

**Action**: **DEFER** - Leave as-is until Platform layer testing complete

---

## 📊 Priority Summary

| Issue | Severity | Status | Effort | Action |
|-------|----------|--------|--------|--------|
| #1: CoreMachine registries | 🔴 CRITICAL | **FIX IMMEDIATELY** | 5 min | Platform crashes without this |
| #2: Service Bus pattern | 🟠 MEDIUM | Fix soon | 10 min | Architectural consistency |
| #3: Schema initialization | 🟡 LOW | Can defer | 20 min | Performance improvement |
| #4: Duplicate job logic | 🟡 LOW | **DEFER** | 30 min | Intentional for testing |

**Total Effort to Fix Critical Issues**: 15 minutes (Issues #1 + #2)

---

## 🧪 Testing Strategy

After fixing Issues #1 and #2, test Platform endpoints:

### 1. Platform Request Submission Test
```bash
curl -X POST 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit' \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_id": "landsat-8-test",
    "resource_id": "LC08_L1TP_044034_20210622",
    "version_id": "v1.0",
    "data_type": "raster",
    "source_location": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeobronze/antigua.tif",
    "parameters": {"output_tier": "analysis"},
    "client_id": "test-client"
  }' | python3 -m json.tool
```

**Expected Response**:
```json
{
  "success": true,
  "request_id": "abc123...",
  "status": "pending",
  "jobs_created": [
    "validate_raster_job_id",
    "create_cog_job_id",
    "create_stac_item_job_id"
  ],
  "message": "Platform request submitted. 3 jobs created.",
  "monitor_url": "/api/platform/status/abc123..."
}
```

### 2. Platform Status Monitoring Test
```bash
# Get specific request status
curl 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/status/{REQUEST_ID}' \
  | python3 -m json.tool

# List all requests
curl 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/status' \
  | python3 -m json.tool
```

### 3. Check Application Insights Logs
```bash
# Check for Platform-related errors
cat > /tmp/check_platform_logs.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(10m) | where message contains 'Platform' or message contains 'CoreMachine' or severityLevel >= 3 | order by timestamp desc | take 30" \
  -G | python3 -m json.tool
EOF
chmod +x /tmp/check_platform_logs.sh
/tmp/check_platform_logs.sh
```

---

## 📚 Related Documentation

- **Architecture Guide**: `docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md` - Complete two-layer architecture explanation
- **TODO List**: `docs_claude/TODO.md` - Active task list (should include Platform fixes)
- **Primary Context**: `docs_claude/CLAUDE_CONTEXT.md` - Main system overview
- **File Catalog**: `docs_claude/FILE_CATALOG.md` - Quick file reference

---

## 🔄 Current Status (26 OCT 2025 23:30 UTC)

✅ **Import Errors Fixed** - Platform triggers load successfully
❌ **Runtime Issues Remain** - Platform endpoints will crash on use (CoreMachine instantiation)
🧪 **Not Yet Tested** - Platform layer has not been tested with real requests
⏳ **Job Running** - `process_large_raster` for antigua.tif running with new /vsimem/ pattern

**Next Steps for Future Claudes**:
1. Fix Issue #1 (CoreMachine registries) - 5 minutes
2. Fix Issue #2 (Service Bus pattern) - 10 minutes
3. Test Platform endpoints with curl commands above
4. If successful, update TODO.md with Platform layer completion
5. Consider Issues #3-4 as optional improvements

---

**Author Notes**: This document captures the state of the Platform layer as of 26 OCT 2025 after fixing critical import errors. The Platform layer implements the "turtle above CoreMachine" fractal pattern for external application integration. Issues #1-2 are blocking Platform functionality, while #3-4 are architectural improvements that can be deferred.

**Military Date Format**: 26 OCT 2025
**Document Version**: 1.0
**Last Updated**: 26 OCT 2025 23:30 UTC

---

## 📊 UPDATE - Issues #1 and #2 FIXED (26 OCT 2025 23:36 UTC)

### ✅ Issue #1: CoreMachine Registries - COMPLETED

**Fix Applied**: Modified `PlatformOrchestrator.__init__()` at line 435-450

**Changes**:
- Added explicit import of `ALL_JOBS` and `ALL_HANDLERS` registries
- Pass registries to `CoreMachine()` constructor
- Added logging to confirm successful initialization

**Code**:
```python
def __init__(self):
    # Import registries explicitly (CoreMachine requires them since 10 SEP 2025)
    from jobs import ALL_JOBS
    from services import ALL_HANDLERS

    self.platform_repo = PlatformRepository()
    self.job_repo = JobRepository()

    # CoreMachine requires explicit registries (no decorator magic!)
    self.core_machine = CoreMachine(
        all_jobs=ALL_JOBS,
        all_handlers=ALL_HANDLERS
    )

    logger.info(f"✅ PlatformOrchestrator initialized...")
```

**Result**: Platform endpoints can now instantiate `PlatformOrchestrator` without `TypeError`

---

### ✅ Issue #2: Service Bus Repository Pattern - COMPLETED

**Fix Applied**: Rewrote `_submit_to_queue()` method at line 635-668

**Changes**:
- Replaced direct `ServiceBusClient` usage with `ServiceBusRepository`
- Use Pydantic `JobQueueMessage` model instead of manual JSON serialization
- Use `config.service_bus_jobs_queue` instead of hardcoded "jobs"
- Enhanced error logging with full context

**Code**:
```python
async def _submit_to_queue(self, job: JobRecord):
    """Submit job to Service Bus jobs queue via repository pattern"""
    from infrastructure.service_bus import ServiceBusRepository
    from core.schema.queue import JobQueueMessage
    import uuid

    service_bus_repo = ServiceBusRepository()
    
    queue_message = JobQueueMessage(
        job_id=job.job_id,
        job_type=job.job_type,
        parameters=job.parameters,
        stage=1,  # Platform creates Stage 1 jobs
        correlation_id=str(uuid.uuid4())[:8]
    )

    message_id = service_bus_repo.send_message(
        config.service_bus_jobs_queue,
        queue_message
    )

    logger.info(f"✅ Submitted job... message_id: {message_id}")
```

**Benefits**:
- ✅ Architectural consistency with CoreMachine pattern
- ✅ Connection pooling and retry logic from repository
- ✅ Pydantic validation for queue messages
- ✅ Proper configuration usage

---

## 🚀 Next Steps

### Immediate (Ready for Testing):
1. **Deploy fixes to Azure Functions**
   - Issues #1 and #2 are fixed and ready to deploy
   - Platform endpoints should work without crashes

2. **Test Platform Endpoints**
   ```bash
   # Test Platform request submission
   curl -X POST 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit' \
     -H 'Content-Type: application/json' \
     -d '{
       "dataset_id": "test-raster",
       "resource_id": "antigua",
       "version_id": "v1.0",
       "data_type": "raster",
       "source_location": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeobronze/antigua.tif",
       "parameters": {"output_tier": "analysis"},
       "client_id": "test-client"
     }'
   ```

3. **Monitor Platform Request Status**
   ```bash
   # Get platform request status (replace REQUEST_ID)
   curl 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/status/{REQUEST_ID}'
   ```

### Future (Can Defer):
- **Issue #3**: Schema initialization (efficiency improvement)
- **Issue #4**: Duplicate job submission logic (intentional for testing)

---

## 📝 Updated Status Summary (26 OCT 2025 23:36 UTC)

| Issue | Severity | Status | Time to Fix | Fixed By |
|-------|----------|--------|-------------|----------|
| Import errors | 🔴 CRITICAL | ✅ COMPLETED (23:30) | 15 min | Claude & Robert |
| #1: CoreMachine registries | 🔴 CRITICAL | ✅ COMPLETED (23:35) | 5 min | Claude & Robert |
| #2: Service Bus pattern | 🟠 MEDIUM | ✅ COMPLETED (23:36) | 5 min | Claude & Robert |
| #3: Schema init | 🟡 LOW | DEFERRED | 20 min | - |
| #4: Duplicate logic | 🟡 LOW | INTENTIONAL | - | - |

**Total Critical Issues Fixed**: 3 (Import errors + Issues #1-2)
**Total Time**: ~25 minutes
**Platform Status**: ✅ Ready for testing after deployment

---

**Document Updated**: 26 OCT 2025 23:36 UTC
**Updated By**: Robert and Geospatial Claude Legion

