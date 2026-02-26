"""
Randomized model factories — anti-overfitting design.

Every factory call generates randomized non-identity fields
(timestamps, descriptions, string suffixes) so tests cannot
rely on specific default values.
"""

import hashlib
import random
import string
import uuid
from datetime import datetime, timezone, timedelta


def _random_suffix(length: int = 6) -> str:
    """Generate random alphanumeric suffix."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _random_timestamp() -> datetime:
    """Generate random timestamp within last 30 days."""
    offset = random.randint(0, 30 * 24 * 3600)
    return datetime.now(timezone.utc) - timedelta(seconds=offset)


def _sha256(seed: str) -> str:
    """Generate SHA256 hex digest from seed."""
    return hashlib.sha256(seed.encode()).hexdigest()


def make_job_record(job_id: str = None, status=None, **overrides):
    """
    Build a JobRecord with randomized non-identity fields.

    Args:
        job_id: Optional fixed job_id (generates random if None)
        status: Optional fixed status
        **overrides: Any field override

    Returns:
        dict suitable for JobRecord(**result)
    """
    from core.models.enums import JobStatus

    suffix = _random_suffix()
    _job_id = job_id or _sha256(f"job-{suffix}-{uuid.uuid4()}")

    base = {
        "job_id": _job_id,
        "job_type": f"test_job_{suffix}",
        "parameters": {"seed": suffix, "random_val": random.randint(1, 9999)},
        "status": status or JobStatus.QUEUED,
        "stage": 1,
        "total_stages": random.randint(1, 5),
        "stage_results": {},
        "metadata": {"factory": True, "suffix": suffix},
        "created_at": _random_timestamp(),
        "updated_at": _random_timestamp(),
    }
    base.update(overrides)
    return base


def make_task_record(parent_job_id: str = None, status=None, **overrides):
    """
    Build a TaskRecord with randomized non-identity fields.

    Returns:
        dict suitable for TaskRecord(**result)
    """
    from core.models.enums import TaskStatus

    suffix = _random_suffix()
    _parent_id = parent_job_id or _sha256(f"parent-{suffix}-{uuid.uuid4()}")

    base = {
        "task_id": f"task-{suffix}-{random.randint(100, 999)}",
        "parent_job_id": _parent_id,
        "job_type": f"test_job_{suffix}",
        "task_type": f"test_handler_{suffix}",
        "stage": 1,
        "parameters": {"seed": suffix},
        "status": status or TaskStatus.PENDING,
        "retry_count": 0,
        "metadata": {"factory": True},
        "created_at": _random_timestamp(),
        "updated_at": _random_timestamp(),
    }
    base.update(overrides)
    return base


def make_asset(platform_id: str = None, dataset_id: str = None,
               resource_id: str = None, **overrides):
    """Build an Asset with randomized non-identity fields."""
    suffix = _random_suffix()
    _pid = platform_id or "ddh"
    _did = dataset_id or f"dataset-{suffix}"
    _rid = resource_id or f"resource-{suffix}"

    from core.models.asset import Asset
    asset_id = Asset.generate_asset_id(_pid, _did, _rid)

    base = {
        "asset_id": asset_id,
        "platform_id": _pid,
        "dataset_id": _did,
        "resource_id": _rid,
        "data_type": random.choice(["raster", "vector"]),
        "release_count": random.randint(0, 10),
        "created_at": _random_timestamp(),
        "updated_at": _random_timestamp(),
    }
    base.update(overrides)
    return base


def make_asset_release(asset_id: str = None, approval_state=None, **overrides):
    """Build an AssetRelease with randomized non-identity fields."""
    from core.models.asset import ApprovalState

    suffix = _random_suffix()
    _asset_id = asset_id or _sha256(f"asset-{suffix}")[:32]

    base = {
        "release_id": f"rel-{suffix}-{random.randint(100, 999)}",
        "asset_id": _asset_id,
        "stac_item_id": f"stac-item-{suffix}",
        "stac_collection_id": f"stac-col-{suffix}",
        "approval_state": approval_state or ApprovalState.PENDING_REVIEW,
        "version_ordinal": random.randint(0, 5),
        "revision": random.randint(1, 3),
        "priority": random.randint(1, 10),
        "created_at": _random_timestamp(),
        "updated_at": _random_timestamp(),
    }
    base.update(overrides)
    return base


def make_task_result(status=None, **overrides):
    """Build a TaskResult with randomized fields."""
    from core.models.enums import TaskStatus

    suffix = _random_suffix()
    _status = status or random.choice([TaskStatus.COMPLETED, TaskStatus.FAILED])

    base = {
        "task_id": f"task-{suffix}-{random.randint(100, 999)}",
        "task_type": f"handler_{suffix}",
        "status": _status,
        "result_data": {"key": suffix} if _status == TaskStatus.COMPLETED else None,
        "error_details": f"Error-{suffix}" if _status == TaskStatus.FAILED else None,
        "execution_time_ms": random.randint(10, 5000),
        "timestamp": _random_timestamp(),
    }
    base.update(overrides)
    return base
