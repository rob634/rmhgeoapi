# Job Creation Quick Reference Card

**Quick reference for creating new job types. For full details see [`docs_claude/ARCHITECTURE_REFERENCE.md`](docs_claude/ARCHITECTURE_REFERENCE.md)**

---

## 5 Required Methods (Validated at Import!)

All jobs MUST implement these 5 static methods:

```python
class YourJob:
    job_type: str = "your_job"
    stages: List[Dict[str, Any]] = [{"number": 1, "name": "...", "task_type": "..."}]

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """Validate and normalize parameters. Raise ValueError if invalid."""
        return params

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """Return deterministic SHA256 hash for idempotency."""
        import hashlib, json
        return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """Create JobRecord and persist to database."""
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus

        job_record = JobRecord(
            job_id=job_id,
            job_type="your_job",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=len(YourJob.stages),
            stage_results={},
            metadata={"description": "..."}
        )

        repos = RepositoryFactory.create_repositories()
        repos['job_repo'].create_job(job_record)
        return {"job_id": job_id, "status": "queued"}

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """Queue JobQueueMessage to Service Bus."""
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        import uuid

        message = JobQueueMessage(
            job_id=job_id,
            job_type="your_job",
            stage=1,
            parameters=params,
            message_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4())
        )

        config = get_config()
        service_bus = ServiceBusRepository(
            connection_string=config.get_service_bus_connection(),
            queue_name=config.jobs_queue_name
        )
        message_id = service_bus.send_message(message.model_dump_json())
        return {"queued": True, "queue_type": "service_bus", "message_id": message_id}

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameter dicts for a stage.

        Each dict must have: task_id, task_type, parameters
        """
        return [
            {
                "task_id": f"{job_id[:8]}-s{stage}-{i}",
                "task_type": "handler_name_from_services_registry",
                "parameters": {"key": "value"}
            }
            for i in range(count)
        ]
```

---

## Registration (3 Steps)

### 1. Register Job
```python
# jobs/__init__.py
from .your_job import YourJob

ALL_JOBS = {
    # ... existing jobs ...
    "your_job": YourJob,
}
```

### 2. Register Handler
```python
# services/__init__.py
from .service_your_domain import your_handler

ALL_HANDLERS = {
    # ... existing handlers ...
    "handler_name": your_handler,
}
```

### 3. Validate Locally
```bash
python3 -c "from jobs import validate_job_registry; validate_job_registry()"
```

---

## Task Dict Structure

**Required keys:**
```python
{
    "task_id": str,        # Unique ID (format: "{job_id[:8]}-s{stage}-{index}")
    "task_type": str,      # Handler name from services registry
    "parameters": dict     # Task-specific params
}
```

**Optional keys:**
```python
{
    "metadata": dict       # Additional task metadata
}
```

---

## Testing Commands

```bash
# 1. Validate job structure
python3 -c "from jobs import validate_job_registry; validate_job_registry()"

# 2. Test compilation
python3 -m py_compile jobs/your_job.py

# 3. Deploy
func azure functionapp publish rmhgeoapibeta --python --build remote

# 4. Health check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# 5. Submit test job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/your_job \
  -H "Content-Type: application/json" \
  -d '{"param1": "value1"}'

# 6. Check status (use job_id from response)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## Reference Implementations

- **Simple**: [`jobs/create_h3_base.py`](jobs/create_h3_base.py) - Single stage, minimal
- **Multi-stage**: [`jobs/hello_world.py`](jobs/hello_world.py) - Two stages with parameters
- **Complex**: [`jobs/process_raster.py`](jobs/process_raster.py) - Dynamic fan-out

---

## Common Mistakes

❌ Forgetting `@staticmethod` decorator
❌ Missing required keys in task dicts (`task_id`, `task_type`, `parameters`)
❌ Not registering handler in `services/__init__.py`
❌ Using `job_type` string that doesn't match registry key
❌ Forgetting to add job to `ALL_JOBS` dict

---

## What Validation Catches

✅ Missing required methods (caught at import)
✅ Missing `stages` attribute (caught at import)
✅ Empty `stages` list (caught at import)
✅ Missing task dict keys (caught when job processes)
✅ Invalid handler names (caught when task executes)

---

**For complete documentation see: [`docs_claude/ARCHITECTURE_REFERENCE.md`](docs_claude/ARCHITECTURE_REFERENCE.md) lines 232-331**
