# ============================================================================
# UNIT TESTS - Pydantic V2 @field_serializer on domain models
# ============================================================================
# PURPOSE: Verify model_dump() produces DB-ready values (EN-TD.2 Phase 2)
# CREATED: 18 FEB 2026
# RUN: conda activate azgeo && python -m pytest test/test_model_serializers.py -v
# ============================================================================
"""
Unit tests for @field_serializer on Asset, AssetRelease, JobRecord, TaskRecord, Artifact.

Verifies that model_dump() (mode='python') produces values ready for psycopg3:
- Enums → string values
- Dicts/lists → JSON strings (for JSONB columns)
- Datetimes → datetime objects (psycopg3 handles natively)
- Scalars → passthrough

V0.9 (21 FEB 2026): GeospatialAsset tests replaced with Asset + AssetRelease tests.
"""

import json
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models.asset import (
    Asset, AssetRelease, ApprovalState, ClearanceState, ProcessingStatus
)
from core.models.job import JobRecord
from core.models.task import TaskRecord
from core.models.artifact import Artifact, ArtifactStatus
from core.models.enums import JobStatus, TaskStatus


# ============================================================================
# HELPER
# ============================================================================

def _make_asset(**overrides) -> Asset:
    """Create an Asset with required fields filled in."""
    defaults = {
        "asset_id": "abc123",
        "platform_id": "ddh",
        "dataset_id": "floods",
        "resource_id": "jakarta",
        "data_type": "raster",
    }
    defaults.update(overrides)
    return Asset(**defaults)


def _make_release(**overrides) -> AssetRelease:
    """Create an AssetRelease with required fields filled in."""
    defaults = {
        "release_id": "rel123",
        "asset_id": "abc123",
        "stac_item_id": "floods-jakarta",
        "stac_collection_id": "floods",
    }
    defaults.update(overrides)
    return AssetRelease(**defaults)


def _make_job(**overrides) -> JobRecord:
    """Create a JobRecord with required fields filled in."""
    defaults = {
        "job_id": "a" * 64,  # SHA256 hash length
        "job_type": "raster_cog",
        "parameters": {"input": "test.tif"},
    }
    defaults.update(overrides)
    return JobRecord(**defaults)


def _make_task(**overrides) -> TaskRecord:
    """Create a TaskRecord with required fields filled in."""
    defaults = {
        "task_id": "task-001",
        "parent_job_id": "job-001",
        "job_type": "raster_cog",
        "task_type": "process_raster",
        "stage": 1,
        "task_index": "0",
        "parameters": {"chunk": 0},
    }
    defaults.update(overrides)
    return TaskRecord(**defaults)


def _make_artifact(**overrides) -> Artifact:
    """Create an Artifact with required fields filled in."""
    defaults = {
        "storage_account": "rmhazuregeobronze",
        "container": "silver-cogs",
        "blob_path": "floods/jakarta.tif",
        "client_type": "ddh",
        "client_refs": {"dataset_id": "floods"},
    }
    defaults.update(overrides)
    return Artifact(**defaults)


# ============================================================================
# Asset TESTS (V0.9 identity container)
# ============================================================================

class TestAssetModelDump:

    def test_datetime_stays_as_object(self):
        """mode='python' (default) preserves datetime for psycopg3."""
        asset = _make_asset()
        data = asset.model_dump()
        assert isinstance(data["created_at"], datetime)
        assert isinstance(data["updated_at"], datetime)

    def test_optional_datetime_none(self):
        asset = _make_asset()
        data = asset.model_dump()
        assert data["deleted_at"] is None

    def test_scalar_fields_passthrough(self):
        asset = _make_asset(data_type="vector")
        data = asset.model_dump()
        assert data["data_type"] == "vector"
        assert data["platform_id"] == "ddh"

    def test_jsonb_platform_refs_preserved(self):
        """JSONB fields stay as dicts in model_dump(); psycopg3 handles dict→JSONB."""
        refs = {"extra_key": "extra_val"}
        asset = _make_asset(platform_refs=refs)
        data = asset.model_dump()
        assert data["platform_refs"] == refs


# ============================================================================
# AssetRelease TESTS (V0.9 versioned artifact)
# ============================================================================

class TestAssetReleaseModelDump:

    def test_enum_fields_serialize_to_strings(self):
        release = _make_release(
            approval_state=ApprovalState.APPROVED,
            clearance_state=ClearanceState.PUBLIC,
            processing_status=ProcessingStatus.COMPLETED,
        )
        data = release.model_dump()
        assert data["approval_state"] == "approved"
        assert data["clearance_state"] == "public"
        assert data["processing_status"] == "completed"

    def test_enum_defaults_serialize(self):
        release = _make_release()
        data = release.model_dump()
        assert data["approval_state"] == "pending_review"
        assert data["clearance_state"] == "uncleared"
        assert data["processing_status"] == "pending"

    def test_jsonb_none_stays_none(self):
        release = _make_release(node_summary=None)
        data = release.model_dump()
        assert data["node_summary"] is None

    def test_jsonb_node_summary_preserved(self):
        """JSONB fields stay as dicts in model_dump(); psycopg3 handles dict→JSONB."""
        summary = {"total": 5, "completed": 3, "failed": 0}
        release = _make_release(node_summary=summary)
        data = release.model_dump()
        assert data["node_summary"] == summary

    def test_jsonb_stac_item_json_preserved(self):
        """JSONB fields stay as dicts in model_dump(); psycopg3 handles dict→JSONB."""
        stac = {"type": "Feature", "id": "test-item"}
        release = _make_release(stac_item_json=stac)
        data = release.model_dump()
        assert data["stac_item_json"] == stac

    def test_datetime_stays_as_object(self):
        """mode='python' (default) preserves datetime for psycopg3."""
        release = _make_release()
        data = release.model_dump()
        assert isinstance(data["created_at"], datetime)
        assert isinstance(data["updated_at"], datetime)

    def test_optional_datetime_none(self):
        release = _make_release()
        data = release.model_dump()
        assert data["reviewed_at"] is None
        assert data["revoked_at"] is None

    def test_scalar_fields_passthrough(self):
        release = _make_release(revision=3)
        data = release.model_dump()
        assert data["revision"] == 3

    def test_model_dump_json_mode_iso_strings(self):
        """mode='json' converts datetimes to ISO strings (for API responses)."""
        release = _make_release()
        data = release.model_dump(mode="json")
        assert isinstance(data["created_at"], str)


# ============================================================================
# JobRecord TESTS
# ============================================================================

class TestJobRecordModelDump:

    def test_status_enum_serializes(self):
        job = _make_job(status=JobStatus.PROCESSING)
        data = job.model_dump()
        assert data["status"] == "processing"

    def test_jsonb_parameters_serializes(self):
        params = {"input": "test.tif", "options": {"compress": True}}
        job = _make_job(parameters=params)
        data = job.model_dump()
        assert isinstance(data["parameters"], str)
        assert json.loads(data["parameters"]) == params

    def test_jsonb_metadata_serializes(self):
        meta = {"source": "upload", "user": "robert"}
        job = _make_job(metadata=meta)
        data = job.model_dump()
        assert isinstance(data["metadata"], str)
        assert json.loads(data["metadata"]) == meta

    def test_jsonb_stage_results_serializes(self):
        results = {"1": {"tasks_completed": 3}}
        job = _make_job(stage_results=results)
        data = job.model_dump()
        assert isinstance(data["stage_results"], str)
        assert json.loads(data["stage_results"]) == results

    def test_jsonb_result_data_none(self):
        job = _make_job()
        data = job.model_dump()
        assert data["result_data"] is None

    def test_jsonb_result_data_serializes(self):
        result = {"output_path": "silver-cogs/test.tif"}
        job = _make_job(result_data=result)
        data = job.model_dump()
        assert isinstance(data["result_data"], str)
        assert json.loads(data["result_data"]) == result

    def test_datetime_stays_as_object(self):
        job = _make_job()
        data = job.model_dump()
        assert isinstance(data["created_at"], datetime)


# ============================================================================
# TaskRecord TESTS
# ============================================================================

class TestTaskRecordModelDump:

    def test_status_enum_serializes(self):
        task = _make_task(status=TaskStatus.COMPLETED)
        data = task.model_dump()
        assert data["status"] == "completed"

    def test_jsonb_parameters_serializes(self):
        params = {"chunk": 0, "bbox": [-70, -56, -69, -55]}
        task = _make_task(parameters=params)
        data = task.model_dump()
        assert isinstance(data["parameters"], str)
        assert json.loads(data["parameters"]) == params

    def test_jsonb_result_data_serializes(self):
        result = {"rows_inserted": 42}
        task = _make_task(result_data=result)
        data = task.model_dump()
        assert isinstance(data["result_data"], str)
        assert json.loads(data["result_data"]) == result

    def test_jsonb_checkpoint_data_serializes(self):
        checkpoint = {"phase": 2, "rows_done": 1000}
        task = _make_task(checkpoint_data=checkpoint)
        data = task.model_dump()
        assert isinstance(data["checkpoint_data"], str)
        assert json.loads(data["checkpoint_data"]) == checkpoint

    def test_jsonb_next_stage_params_serializes(self):
        nsp = {"output_table": "geo.floods"}
        task = _make_task(next_stage_params=nsp)
        data = task.model_dump()
        assert isinstance(data["next_stage_params"], str)
        assert json.loads(data["next_stage_params"]) == nsp

    def test_jsonb_metadata_serializes(self):
        meta = {"queue": "raster-tasks"}
        task = _make_task(metadata=meta)
        data = task.model_dump()
        assert isinstance(data["metadata"], str)
        assert json.loads(data["metadata"]) == meta

    def test_datetime_stays_as_object(self):
        task = _make_task()
        data = task.model_dump()
        assert isinstance(data["created_at"], datetime)


# ============================================================================
# Artifact TESTS
# ============================================================================

class TestArtifactModelDump:

    def test_status_enum_serializes(self):
        art = _make_artifact(status=ArtifactStatus.SUPERSEDED)
        data = art.model_dump()
        assert data["status"] == "superseded"

    def test_jsonb_client_refs_serializes(self):
        refs = {"dataset_id": "floods", "resource_id": "jakarta"}
        art = _make_artifact(client_refs=refs)
        data = art.model_dump()
        assert isinstance(data["client_refs"], str)
        assert json.loads(data["client_refs"]) == refs

    def test_jsonb_metadata_serializes(self):
        meta = {"band_count": 1, "crs": "EPSG:4326"}
        art = _make_artifact(metadata=meta)
        data = art.model_dump()
        assert isinstance(data["metadata"], str)
        assert json.loads(data["metadata"]) == meta

    def test_jsonb_metadata_empty_dict(self):
        art = _make_artifact()
        data = art.model_dump()
        assert isinstance(data["metadata"], str)
        assert json.loads(data["metadata"]) == {}

    def test_datetime_stays_as_object(self):
        art = _make_artifact()
        data = art.model_dump()
        assert isinstance(data["created_at"], datetime)
