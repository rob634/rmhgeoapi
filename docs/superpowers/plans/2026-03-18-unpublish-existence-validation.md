# Unpublish Existence Validation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resource existence checks to the unpublish dry_run path so users get immediate, descriptive "not found" errors at request time instead of a false-positive preview or an async job failure.

**Architecture:** All existence checks live in the trigger-level `_execute_*_unpublish()` functions inside `triggers/platform/unpublish.py`. When `dry_run=True` (or `False`), the function queries the relevant data store (PostGIS `information_schema` for vector, pgstac for raster, pgstac + Release for zarr, `release_tables` for vector_multi_source) and returns an HTTP 404 with a descriptive message if the target doesn't exist. This is a pure trigger-layer change — no job classes, handlers, or validators are modified.

**Tech Stack:** Python 3.12, Azure Functions, psycopg3, pgstac, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `triggers/platform/unpublish.py` | Modify | Add per-type existence check helpers + call from each `_execute_*` function |
| `services/platform_response.py` | Modify | Add `not_found_error()` response builder (HTTP 404) |
| `tests/unit/test_unpublish_existence.py` | Create | Unit tests for existence check logic |

**Design rationale:** Four private helpers (`_vector_table_exists`, `_raster_stac_item_exists`, `_zarr_item_exists`, `_release_tables_exist`) live in the trigger file, co-located with the functions that call them. These are simple boolean queries — no business logic, no side effects.

**Note on line numbers:** Task 2 adds ~80 lines of helper functions before `_execute_vector_unpublish`. All subsequent tasks use function-relative anchors ("after `_check_approved_block`, before the `if dry_run:` branch") rather than absolute line numbers, so they remain valid regardless of insertion.

---

## Chunk 1: Response Builder + Existence Checker

### Task 1: Add `not_found_error` response builder

**Files:**
- Modify: `services/platform_response.py` (after `validation_error` at ~line 131)
- Test: `tests/unit/test_unpublish_existence.py`

- [ ] **Step 1: Write failing test for `not_found_error`**

```python
# tests/unit/test_unpublish_existence.py
"""Tests for unpublish existence validation."""

import json
import pytest


class TestNotFoundResponse:
    """Test the not_found_error response builder."""

    def test_not_found_returns_404(self):
        from services.platform_response import not_found_error
        resp = not_found_error("Table 'geo.my_table' does not exist")
        assert resp.status_code == 404

    def test_not_found_includes_error_message(self):
        from services.platform_response import not_found_error
        resp = not_found_error("Table 'geo.my_table' does not exist")
        body = json.loads(resp.get_body())
        assert body["error"] == "Table 'geo.my_table' does not exist"
        assert body["error_type"] == "NotFoundError"

    def test_not_found_includes_extra_fields(self):
        from services.platform_response import not_found_error
        resp = not_found_error(
            "STAC item 'x' not found",
            stac_item_id="x",
            collection_id="y"
        )
        body = json.loads(resp.get_body())
        assert body["stac_item_id"] == "x"
        assert body["collection_id"] == "y"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestNotFoundResponse -v`
Expected: FAIL — `not_found_error` doesn't exist yet.

- [ ] **Step 3: Implement `not_found_error` in platform_response.py**

Add after the `validation_error` function (~line 131):

```python
def not_found_error(error: str, **extra_fields) -> func.HttpResponse:
    """
    Build a 404 Not Found response for missing resources.

    Used by unpublish dry_run to report non-existent targets
    before job creation.

    Args:
        error: Descriptive message about what was not found
        **extra_fields: Additional fields (e.g. table_name, stac_item_id)

    Returns:
        Azure Functions HttpResponse with status 404
    """
    return error_response(error, "NotFoundError", status_code=404, **extra_fields)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestNotFoundResponse -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add services/platform_response.py tests/unit/test_unpublish_existence.py
git commit -m "feat: add not_found_error (HTTP 404) response builder for unpublish existence checks"
```

---

### Task 2: Add existence check helpers to unpublish trigger

**Files:**
- Modify: `triggers/platform/unpublish.py` (add helper functions before `_execute_vector_unpublish`)

These are private functions that query the data stores. Each returns a tuple: `(exists: bool, detail: str)`. The `detail` string is a human-readable message describing what was checked and what was found (or not).

- [ ] **Step 1: Write failing tests for each existence checker**

Append to `tests/unit/test_unpublish_existence.py`:

```python
from unittest.mock import patch, MagicMock


class TestVectorExists:
    """Test _vector_table_exists existence check."""

    @patch("triggers.platform.unpublish.PostgreSQLRepository")
    def test_returns_true_when_table_exists(self, mock_repo_cls):
        # Set up nested context manager mocks (connection → cursor)
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"exists": True}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_repo_cls.return_value._get_connection.return_value.__enter__.return_value = mock_conn

        from triggers.platform.unpublish import _vector_table_exists
        exists, detail = _vector_table_exists("my_table", "geo")
        assert exists is True
        assert "my_table" in detail

    @patch("triggers.platform.unpublish.PostgreSQLRepository")
    def test_returns_false_when_table_missing(self, mock_repo_cls):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"exists": False}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_repo_cls.return_value._get_connection.return_value.__enter__.return_value = mock_conn

        from triggers.platform.unpublish import _vector_table_exists
        exists, detail = _vector_table_exists("ghost_table", "geo")
        assert exists is False
        assert "ghost_table" in detail
        assert "does not exist" in detail

    @patch("triggers.platform.unpublish.PostgreSQLRepository")
    def test_returns_true_on_db_error(self, mock_repo_cls):
        """Fail-open: DB errors should not produce false 404."""
        mock_repo_cls.return_value._get_connection.side_effect = Exception("connection refused")

        from triggers.platform.unpublish import _vector_table_exists
        exists, detail = _vector_table_exists("any_table", "geo")
        assert exists is True
        assert "Could not verify" in detail


class TestRasterExists:
    """Test _raster_stac_item_exists existence check."""

    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_when_item_exists(self, mock_repo_cls):
        mock_repo_cls.return_value.get_item.return_value = {"id": "item-1"}

        from triggers.platform.unpublish import _raster_stac_item_exists
        exists, detail = _raster_stac_item_exists("item-1", "collection-1")
        assert exists is True

    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_false_when_item_missing(self, mock_repo_cls):
        mock_repo_cls.return_value.get_item.return_value = None

        from triggers.platform.unpublish import _raster_stac_item_exists
        exists, detail = _raster_stac_item_exists("ghost-item", "collection-1")
        assert exists is False
        assert "ghost-item" in detail
        assert "not found" in detail


class TestZarrExists:
    """Test _zarr_item_exists — checks pgstac THEN Release fallback."""

    @patch("infrastructure.ReleaseRepository")
    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_when_in_pgstac(self, mock_pgstac_cls, mock_release_cls):
        mock_pgstac_cls.return_value.get_item.return_value = {"id": "zarr-1"}

        from triggers.platform.unpublish import _zarr_item_exists
        exists, detail = _zarr_item_exists("zarr-1", "coll-1")
        assert exists is True

    @patch("infrastructure.ReleaseRepository")
    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_when_in_release_only(self, mock_pgstac_cls, mock_rel_cls):
        mock_pgstac_cls.return_value.get_item.return_value = None
        mock_release = MagicMock()
        mock_release.stac_item_json = {"id": "zarr-1"}
        mock_rel_cls.return_value.get_by_stac_item_id.return_value = mock_release

        from triggers.platform.unpublish import _zarr_item_exists
        exists, detail = _zarr_item_exists("zarr-1", "coll-1")
        assert exists is True
        assert "Release" in detail

    @patch("infrastructure.ReleaseRepository")
    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_false_when_nowhere(self, mock_pgstac_cls, mock_rel_cls):
        mock_pgstac_cls.return_value.get_item.return_value = None
        mock_rel_cls.return_value.get_by_stac_item_id.return_value = None

        from triggers.platform.unpublish import _zarr_item_exists
        exists, detail = _zarr_item_exists("ghost-zarr", "coll-1")
        assert exists is False
        assert "ghost-zarr" in detail
        assert "not found" in detail

    @patch("triggers.platform.unpublish.PgStacRepository")
    def test_returns_true_on_both_lookups_error(self, mock_pgstac_cls):
        """Fail-open: if both pgstac and Release error out, proceed."""
        mock_pgstac_cls.return_value.get_item.side_effect = Exception("pgstac down")

        with patch("infrastructure.ReleaseRepository") as mock_rel_cls:
            mock_rel_cls.return_value.get_by_stac_item_id.side_effect = Exception("release down")

            from triggers.platform.unpublish import _zarr_item_exists
            exists, detail = _zarr_item_exists("any-zarr", "coll-1")
            assert exists is True
            assert "Could not verify" in detail


class TestMultiSourceExists:
    """Test _release_tables_exist."""

    def test_returns_true_when_tables_found(self):
        mock_rt = MagicMock()
        mock_rt.table_name = "table_a"
        with patch("infrastructure.release_table_repository.ReleaseTableRepository") as mock_cls:
            mock_cls.return_value.get_tables.return_value = [mock_rt]

            from triggers.platform.unpublish import _release_tables_exist
            exists, detail = _release_tables_exist("rel-123")
            assert exists is True
            assert "1 table" in detail

    def test_returns_false_when_no_tables(self):
        with patch("infrastructure.release_table_repository.ReleaseTableRepository") as mock_cls:
            mock_cls.return_value.get_tables.return_value = []

            from triggers.platform.unpublish import _release_tables_exist
            exists, detail = _release_tables_exist("rel-ghost")
            assert exists is False
            assert "rel-ghost" in detail
            assert "no tables" in detail.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py -v -k "not TestNotFound"`
Expected: FAIL — helper functions don't exist yet.

- [ ] **Step 3: Implement existence check helpers**

Add to `triggers/platform/unpublish.py`, in the "EXECUTION HELPERS" section (before `_execute_vector_unpublish` at ~line 562), after the existing imports at the top of the file:

First, add the `PostgreSQLRepository` import near the other infrastructure imports (around line 47):

```python
from infrastructure.postgresql import PostgreSQLRepository
```

Then add the `ReleaseTableRepository` lazy import and the four helper functions before `_execute_vector_unpublish`:

```python
# ============================================================================
# EXISTENCE CHECK HELPERS (18 MAR 2026)
# ============================================================================
# Design: fail-open — if DB is unreachable, return (True, ...) so we don't
# produce false 404s during transient outages.  The downstream job-level
# validators and handlers will catch real issues.
# ============================================================================

def _vector_table_exists(table_name: str, schema_name: str) -> tuple:
    """
    Check if a PostGIS table exists via information_schema.

    Returns:
        (exists: bool, detail: str) — detail is a human-readable message.
    """
    try:
        from psycopg.rows import dict_row

        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s) AS exists",
                    (schema_name, table_name)
                )
                row = cur.fetchone()
                exists = row["exists"] if row else False
        if exists:
            return True, f"Table '{schema_name}.{table_name}' exists"
        return False, f"Table '{schema_name}.{table_name}' does not exist in PostGIS"
    except Exception as e:
        logger.warning(f"Existence check failed for table {schema_name}.{table_name}: {e}")
        return True, f"Could not verify table existence (proceeding): {e}"


def _raster_stac_item_exists(stac_item_id: str, collection_id: str) -> tuple:
    """
    Check if a STAC item exists in pgstac.

    Returns:
        (exists: bool, detail: str)
    """
    try:
        pgstac_repo = PgStacRepository()
        item = pgstac_repo.get_item(stac_item_id, collection_id)
        if item:
            return True, f"STAC item '{stac_item_id}' found in collection '{collection_id}'"
        return False, (
            f"STAC item '{stac_item_id}' not found in collection '{collection_id}'. "
            f"Verify the item ID and collection ID are correct."
        )
    except Exception as e:
        logger.warning(f"Existence check failed for STAC item {stac_item_id}: {e}")
        return True, f"Could not verify STAC item existence (proceeding): {e}"


def _zarr_item_exists(stac_item_id: str, collection_id: str) -> tuple:
    """
    Check if a zarr item exists in pgstac OR Release records.

    Zarr items may not be materialized to pgstac — the Release table
    stores stac_item_json as a fallback.

    Fail-open: if both lookups error out, returns (True, ...) so we don't
    produce false 404s during transient outages.

    Returns:
        (exists: bool, detail: str)
    """
    had_error = False

    # Try pgstac first
    try:
        pgstac_repo = PgStacRepository()
        item = pgstac_repo.get_item(stac_item_id, collection_id)
        if item:
            return True, f"Zarr item '{stac_item_id}' found in pgstac"
    except Exception as e:
        had_error = True
        logger.warning(f"pgstac lookup failed for zarr item {stac_item_id}: {e}")

    # Fallback: Release record
    try:
        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()
        release = release_repo.get_by_stac_item_id(stac_item_id)
        if release and release.stac_item_json:
            return True, f"Zarr item '{stac_item_id}' found in Release record (not materialized to pgstac)"
    except Exception as e:
        had_error = True
        logger.warning(f"Release lookup failed for zarr item {stac_item_id}: {e}")

    # Fail-open: if both lookups raised exceptions, don't produce false 404
    if had_error:
        return True, f"Could not verify zarr item existence (proceeding): lookup errors for '{stac_item_id}'"

    return False, (
        f"Zarr item '{stac_item_id}' not found in pgstac or Release records "
        f"for collection '{collection_id}'. Verify the item ID and collection ID are correct."
    )


def _release_tables_exist(release_id: str) -> tuple:
    """
    Check if a release has any tables in release_tables.

    Returns:
        (exists: bool, detail: str)
    """
    try:
        from infrastructure.release_table_repository import ReleaseTableRepository
        release_table_repo = ReleaseTableRepository()
        tables = release_table_repo.get_tables(release_id)
        if tables:
            names = [t.table_name for t in tables]
            return True, f"Release '{release_id[:16]}...' has {len(tables)} table(s): {', '.join(names[:5])}"
        return False, (
            f"Release '{release_id[:16]}...' has no tables in release_tables. "
            f"The release may not exist or has no associated PostGIS tables."
        )
    except Exception as e:
        logger.warning(f"Existence check failed for release {release_id[:16]}...: {e}")
        return True, f"Could not verify release tables (proceeding): {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add triggers/platform/unpublish.py tests/unit/test_unpublish_existence.py
git commit -m "feat: add existence check helpers for unpublish workflows (vector, raster, zarr, multi-source)"
```

---

## Chunk 2: Wire Existence Checks into Execute Functions

### Task 3: Wire existence check into `_execute_vector_unpublish`

**Files:**
- Modify: `triggers/platform/unpublish.py:565-598` (`_execute_vector_unpublish`)
- Modify: import `not_found_error` at top of file
- Test: `tests/unit/test_unpublish_existence.py`

The vector path already has a `table_exists` resource_validator on the job, so this primarily improves the **dry_run** path (which currently returns a preview without checking if the table exists) and gives a better error for the live path (HTTP 404 before job creation instead of a job-level ValueError).

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_unpublish_existence.py`:

```python
class TestExecuteVectorExistenceCheck:
    """Test that _execute_vector_unpublish checks existence."""

    @patch("triggers.platform.unpublish._vector_table_exists")
    def test_dry_run_returns_404_when_table_missing(self, mock_check):
        mock_check.return_value = (False, "Table 'geo.ghost' does not exist in PostGIS")

        from triggers.platform.unpublish import _execute_vector_unpublish
        resp = _execute_vector_unpublish(
            table_name="ghost",
            schema_name="geo",
            dry_run=True,
            force_approved=False,
        )
        assert resp.status_code == 404
        body = json.loads(resp.get_body())
        assert "does not exist" in body["error"]
        assert body["table_name"] == "ghost"

    @patch("triggers.platform.unpublish._vector_table_exists")
    def test_dry_run_returns_200_when_table_exists(self, mock_check):
        mock_check.return_value = (True, "Table 'geo.my_table' exists")

        from triggers.platform.unpublish import _execute_vector_unpublish
        resp = _execute_vector_unpublish(
            table_name="my_table",
            schema_name="geo",
            dry_run=True,
            force_approved=False,
        )
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["dry_run"] is True

    @patch("triggers.platform.unpublish._vector_table_exists")
    def test_live_returns_404_when_table_missing(self, mock_check):
        mock_check.return_value = (False, "Table 'geo.ghost' does not exist in PostGIS")

        from triggers.platform.unpublish import _execute_vector_unpublish
        resp = _execute_vector_unpublish(
            table_name="ghost",
            schema_name="geo",
            dry_run=False,
            force_approved=False,
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestExecuteVectorExistenceCheck -v`
Expected: FAIL — no existence check in `_execute_vector_unpublish` yet.

- [ ] **Step 3: Implement — add existence check to `_execute_vector_unpublish`**

In `triggers/platform/unpublish.py`, add the import at the top with other platform_response imports (~line 67):

```python
from services.platform_response import (
    success_response,
    error_response,
    validation_error,
    not_found_error,       # <-- ADD THIS
    idempotent_response,
    unpublish_accepted,
)
```

Then in `_execute_vector_unpublish`, add the existence check **after** the `table_name` validation and `_check_approved_block` call, but **before** the dry_run branch (~line 580):

```python
    # Existence check — fail fast with descriptive 404
    exists, detail = _vector_table_exists(table_name, schema_name)
    if not exists:
        return not_found_error(detail, table_name=table_name, schema_name=schema_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestExecuteVectorExistenceCheck -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add triggers/platform/unpublish.py tests/unit/test_unpublish_existence.py
git commit -m "feat: vector unpublish returns 404 when target table does not exist"
```

---

### Task 4: Wire existence check into `_execute_raster_unpublish`

**Files:**
- Modify: `triggers/platform/unpublish.py:661-756` (`_execute_raster_unpublish`)
- Test: `tests/unit/test_unpublish_existence.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_unpublish_existence.py`:

```python
class TestExecuteRasterExistenceCheck:
    """Test that _execute_raster_unpublish checks existence."""

    @patch("triggers.platform.unpublish._raster_stac_item_exists")
    def test_dry_run_returns_404_when_item_missing(self, mock_check):
        mock_check.return_value = (False, "STAC item 'ghost' not found in collection 'coll'.")

        from triggers.platform.unpublish import _execute_raster_unpublish
        resp = _execute_raster_unpublish(
            stac_item_id="ghost",
            collection_id="coll",
            dry_run=True,
            force_approved=False,
        )
        assert resp.status_code == 404
        body = json.loads(resp.get_body())
        assert "not found" in body["error"]
        assert body["stac_item_id"] == "ghost"

    @patch("triggers.platform.unpublish._raster_stac_item_exists")
    def test_live_returns_404_when_item_missing(self, mock_check):
        mock_check.return_value = (False, "STAC item 'ghost' not found in collection 'coll'.")

        from triggers.platform.unpublish import _execute_raster_unpublish
        resp = _execute_raster_unpublish(
            stac_item_id="ghost",
            collection_id="coll",
            dry_run=False,
            force_approved=False,
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestExecuteRasterExistenceCheck -v`
Expected: FAIL

- [ ] **Step 3: Implement — add existence check to `_execute_raster_unpublish`**

In `_execute_raster_unpublish`, add after the `_check_approved_block` call but before the dry_run branch (~line 676):

```python
    # Existence check — fail fast with descriptive 404
    exists, detail = _raster_stac_item_exists(stac_item_id, collection_id)
    if not exists:
        return not_found_error(detail, stac_item_id=stac_item_id, collection_id=collection_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestExecuteRasterExistenceCheck -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add triggers/platform/unpublish.py tests/unit/test_unpublish_existence.py
git commit -m "feat: raster unpublish returns 404 when STAC item does not exist"
```

---

### Task 5: Wire existence check into `_execute_zarr_unpublish`

**Files:**
- Modify: `triggers/platform/unpublish.py:759-876` (`_execute_zarr_unpublish`)
- Test: `tests/unit/test_unpublish_existence.py`

This is the most important case — zarr has **no** `resource_validators` on the job class, so without this trigger-level check, a non-existent zarr item creates a job, returns HTTP 202, and fails async at Stage 1.

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_unpublish_existence.py`:

```python
class TestExecuteZarrExistenceCheck:
    """Test that _execute_zarr_unpublish checks existence."""

    @patch("triggers.platform.unpublish._zarr_item_exists")
    def test_dry_run_returns_404_when_item_missing(self, mock_check):
        mock_check.return_value = (False, "Zarr item 'ghost' not found in pgstac or Release records.")

        from triggers.platform.unpublish import _execute_zarr_unpublish
        resp = _execute_zarr_unpublish(
            stac_item_id="ghost",
            collection_id="coll",
            dry_run=True,
            force_approved=False,
            delete_data_files=True,
        )
        assert resp.status_code == 404
        body = json.loads(resp.get_body())
        assert "not found" in body["error"]

    @patch("triggers.platform.unpublish._zarr_item_exists")
    def test_live_returns_404_when_item_missing(self, mock_check):
        mock_check.return_value = (False, "Zarr item 'ghost' not found.")

        from triggers.platform.unpublish import _execute_zarr_unpublish
        resp = _execute_zarr_unpublish(
            stac_item_id="ghost",
            collection_id="coll",
            dry_run=False,
            force_approved=False,
            delete_data_files=True,
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestExecuteZarrExistenceCheck -v`
Expected: FAIL

- [ ] **Step 3: Implement — add existence check to `_execute_zarr_unpublish`**

In `_execute_zarr_unpublish`, add after the `_check_approved_block` call but before the dry_run branch (~line 794):

```python
    # Existence check — fail fast with descriptive 404
    exists, detail = _zarr_item_exists(stac_item_id, collection_id)
    if not exists:
        return not_found_error(detail, stac_item_id=stac_item_id, collection_id=collection_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py::TestExecuteZarrExistenceCheck -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add triggers/platform/unpublish.py tests/unit/test_unpublish_existence.py
git commit -m "feat: zarr unpublish returns 404 when item not found in pgstac or Release"
```

---

### Task 6: Add multi-source vector existence check

**Files:**
- Modify: `triggers/platform/unpublish.py` — need to identify where multi-source unpublish is routed

Multi-source vector is triggered when `_resolve_unpublish_data_type` returns multiple `table_names` from a release_id lookup (Option 2b). The routing happens in `platform_unpublish()` at the trigger level. However, looking at the current code, multi-source doesn't have its own `_execute_*` function — it goes through `_execute_vector_unpublish` with a single table_name. The `release_id` routing creates a `unpublish_vector_multi_source` job via a different path.

Let me trace this. In `_resolve_unpublish_data_type`:
- Option 2b (`release_id`): Returns `data_type="vector"`, `resolved_params={'table_names': [...], 'table_name': table_names[0]}`
- Then `platform_unpublish` dispatches to `_execute_vector_unpublish` with `table_name=table_names[0]`

So currently, multi-source releases get unpublished as **single-table vector unpublish of the first table only**. The `unpublish_vector_multi_source` job type exists but is only reachable if someone calls `/api/jobs/submit/unpublish_vector_multi_source` directly.

This means the `_release_tables_exist` helper is useful for future wiring but **the trigger-level routing for multi-source unpublish via `/api/platform/unpublish` isn't implemented yet**. The `_vector_table_exists` check from Task 3 already covers the current single-table path.

- [ ] **Step 1: Verify existing test coverage is sufficient**

The `_release_tables_exist` helper is already tested in Task 2. No additional wiring needed right now since multi-source goes through the vector path.

- [ ] **Step 2: Add a code comment documenting the gap**

In `triggers/platform/unpublish.py`, in the resolution Option 2b block (~line 349-354), add a comment:

```python
                    if table_names:
                        # NOTE (18 MAR 2026): Multi-source releases resolve to first table only.
                        # Full multi-source unpublish via unpublish_vector_multi_source is not
                        # yet wired into the platform endpoint. _release_tables_exist() is
                        # available for when this routing is implemented.
                        resolved_params = {'table_names': table_names, 'table_name': table_names[0]}
```

- [ ] **Step 3: Commit**

```bash
git add triggers/platform/unpublish.py
git commit -m "docs: note multi-source unpublish routing gap in platform endpoint"
```

---

### Task 7: Run full test suite + verify no regressions

- [ ] **Step 1: Run all unpublish existence tests**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/unit/test_unpublish_existence.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run the full unit test suite**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo pytest tests/ -v`
Expected: ALL PASS — no regressions in existing tests.

- [ ] **Step 3: Final commit if any cleanup needed**

Only if the test run reveals issues that need fixing.

---

## Summary of Changes

| What changes | Before | After |
|-------------|--------|-------|
| Vector dry_run with non-existent table | HTTP 200 preview (misleading) | HTTP 404 "Table does not exist" |
| Vector live with non-existent table | Job created → job-level validator fails → async error | HTTP 404 at request time |
| Raster dry_run with non-existent STAC item | HTTP 200 preview (misleading) | HTTP 404 "STAC item not found" |
| Raster live with non-existent STAC item | Job created → validator fails → async error | HTTP 404 at request time |
| Zarr dry_run with non-existent item | HTTP 200 preview (misleading) | HTTP 404 "not found in pgstac or Release" |
| Zarr live with non-existent item | Job created → Stage 1 fails → async error | HTTP 404 at request time |
| `not_found_error` response builder | Didn't exist | New HTTP 404 builder |

**Key design decisions:**
1. Existence checks are **fail-open on DB errors** — if the check itself fails (connection error), we proceed rather than blocking. The downstream job-level validators and handlers will catch real issues.
2. Checks run for **both dry_run and live paths** — giving consistent behavior regardless of mode.
3. Job-level `resource_validators` on raster/vector remain as **defense-in-depth** for direct job submission callers.
