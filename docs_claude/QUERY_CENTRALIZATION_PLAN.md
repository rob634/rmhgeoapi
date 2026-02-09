# Query Centralization Plan

**Created**: 09 FEB 2026
**Status**: In Progress
**Epic**: Repository Pattern Enforcement

---

## Problem Statement

17+ hardcoded SQL queries bypass the repository layer, causing:
- Column drift when models change (e.g., FK columns missing from queries)
- Duplicated query logic across files
- No single source of truth for table schemas

---

## Design Principle

```
Models define columns → Repository builds queries → Everyone uses repository
```

---

## Phase 1: Add Missing Repository Methods

**Goal**: Create centralized methods that consumers can call instead of writing raw SQL.

### 1.1 JobRepository Enhancements

| Method | Purpose | Replaces |
|--------|---------|----------|
| `list_jobs_with_filters()` | List jobs with status/time/type filters | `db_data.py:268`, `execution/interface.py:846` |
| `list_jobs_with_task_counts()` | Jobs + aggregated task status counts | `db_data.py:268`, `jobs/interface.py:257` |
| `get_job_summary()` | Lightweight job info (no JSONB) | `execution/interface.py:867` |

**Status**:
- [x] `list_jobs_with_filters()` - DONE 09 FEB 2026
- [x] `list_jobs_with_task_counts()` - DONE 09 FEB 2026
- [x] `get_job_summary()` - DONE 09 FEB 2026

### 1.2 TaskRepository Enhancements

| Method | Purpose | Replaces |
|--------|---------|----------|
| `get_task_counts_for_job()` | Count tasks by status for a job | `execution/interface.py:906` |
| `get_task_counts_by_stage()` | Count tasks by stage and status | `execution/interface.py:925` |
| `list_tasks_with_filters()` | List tasks with filters | `db_data.py:537`, `execution/interface.py:967` |

**Status**:
- [x] `get_task_counts_for_job()` - DONE 09 FEB 2026
- [x] `get_task_counts_by_stage()` - DONE 09 FEB 2026
- [x] `list_tasks_with_filters()` - DONE 09 FEB 2026

### 1.3 ApiRequestRepository Fixes

| Method | Purpose | Status |
|--------|---------|--------|
| `get_all_requests()` | List API requests with FK columns | Fixed 09 FEB 2026 |

**Note**: ApiRequestRepository already existed in `infrastructure/platform.py`. Fixed `get_all_requests()` to include `asset_id` and `platform_id` columns.

**Status**:
- [x] Fix `get_all_requests()` to include FK columns - DONE 09 FEB 2026

---

## Phase 2: Refactor Consumers to Use Repository

**Goal**: Replace all hardcoded SQL with repository method calls.

### 2.1 triggers/admin/db_data.py (10+ violations)

| Method | Lines | Repository Call |
|--------|-------|-----------------|
| `_get_jobs()` | 268-349 | `JobRepository.list_jobs_with_task_counts()` |
| `_get_job()` | 439-452 | `JobRepository.get_job()` |
| `_get_tasks()` | 537-572 | `TaskRepository.list_tasks_with_filters()` |
| `_get_tasks_for_job()` | 655-670 | **DEFERRED** - Needs specialized method with checkpoint fields |
| `_get_api_requests()` | 808-834 | `ApiRequestRepository.get_all_requests()` |
| `_get_api_request()` | 914-926 | `ApiRequestRepository.get_request()` |

**Status**:
- [x] `_get_jobs()` refactored - DONE 09 FEB 2026
- [x] `_get_job()` refactored - DONE 09 FEB 2026
- [x] `_get_tasks()` refactored - DONE 09 FEB 2026
- [ ] `_get_tasks_for_job()` - DEFERRED (needs `TaskRepository.get_tasks_for_job_detailed()`)
- [x] `_get_api_requests()` refactored - DONE 09 FEB 2026
- [x] `_get_api_request()` refactored - DONE 09 FEB 2026

### 2.2 web_interfaces/execution/interface.py (5 violations)

| Method | Lines | Repository Call |
|--------|-------|-----------------|
| `_query_jobs()` | 846 | `JobRepository.list_jobs_with_filters()` |
| `_get_job_info()` | 866-870 | `JobRepository.get_job_summary()` |
| `_get_task_counts()` | 906-912 | `TaskRepository.get_task_counts_for_job()` |
| `_get_task_counts_by_stage()` | 925-930 | `TaskRepository.get_task_counts_by_stage()` |
| `_query_tasks()` | 967-975 | `TaskRepository.list_tasks_with_filters()` |

**Status**:
- [x] `_query_jobs()` refactored - DONE 09 FEB 2026
- [x] `_get_job_info()` refactored - DONE 09 FEB 2026
- [x] `_get_task_counts()` refactored - DONE 09 FEB 2026
- [x] `_get_task_counts_by_stage()` refactored - DONE 09 FEB 2026
- [x] `_query_tasks()` refactored - DONE 09 FEB 2026

### 2.3 web_interfaces/jobs/interface.py (1 violation)

| Method | Lines | Repository Call |
|--------|-------|-----------------|
| `_query_jobs_with_task_counts()` | 296 | `JobRepository.list_jobs_with_task_counts()` |

**Status**:
- [x] `_query_jobs_with_task_counts()` refactored - DONE 09 FEB 2026

### 2.4 triggers/admin/data_cleanup.py (1 violation)

| Method | Lines | Repository Call |
|--------|-------|-----------------|
| `cleanup_old_records()` | 105 | `JobRepository.delete_old_jobs()` (new method) |

**Status**:
- [ ] `cleanup_old_records()` - DEFERRED (maintenance operation, less critical)

---

## Phase 3: Model-Driven Column Generation

**Goal**: Repository generates SELECT columns from Pydantic model fields automatically.

### 3.1 Base Repository Enhancement

```python
class BaseRepository:
    @classmethod
    def _get_select_columns(cls, model_class: Type[BaseModel]) -> List[str]:
        """Generate SELECT columns from Pydantic model fields."""
        return [name for name, field in model_class.model_fields.items()
                if not getattr(field, 'exclude_from_select', False)]
```

**Status**:
- [ ] Add `_get_select_columns()` to base repository
- [ ] Update JobRepository to use model-driven columns
- [ ] Update TaskRepository to use model-driven columns
- [ ] Update ApiRequestRepository to use model-driven columns

### 3.2 Model Annotations

Add field metadata to control query generation:

```python
class JobRecord(BaseModel):
    # Included in SELECT (default)
    job_id: str

    # Excluded from lightweight queries
    parameters: Dict = Field(..., json_schema_extra={'heavy': True})
```

**Status**:
- [ ] Define field metadata conventions
- [ ] Update JobRecord with metadata
- [ ] Update TaskRecord with metadata

---

## Verification Checklist

After all phases complete:

- [ ] `grep -r "SELECT.*FROM.*\.jobs" --include="*.py"` returns only repository files
- [ ] `grep -r "SELECT.*FROM.*\.tasks" --include="*.py"` returns only repository files
- [ ] `grep -r "SELECT.*FROM.*\.api_requests" --include="*.py"` returns only repository files
- [ ] Adding a column to JobRecord automatically appears in all queries
- [ ] All tests pass

---

## Progress Log

| Date | Phase | Item | Status |
|------|-------|------|--------|
| 09 FEB 2026 | - | Plan created | Done |
| 09 FEB 2026 | 1.1 | `JobRepository.list_jobs_with_filters()` | Done |
| 09 FEB 2026 | 1.1 | `JobRepository.list_jobs_with_task_counts()` | Done |
| 09 FEB 2026 | 1.1 | `JobRepository.get_job_summary()` | Done |
| 09 FEB 2026 | 1.2 | `TaskRepository.get_task_counts_for_job()` | Done |
| 09 FEB 2026 | 1.2 | `TaskRepository.get_task_counts_by_stage()` | Done |
| 09 FEB 2026 | 1.2 | `TaskRepository.list_tasks_with_filters()` | Done |
| 09 FEB 2026 | 1.3 | `ApiRequestRepository.get_all_requests()` FK fix | Done |
| 09 FEB 2026 | - | **Phase 1 Complete** | ✅ |
| 09 FEB 2026 | 2.1 | `db_data._get_jobs()` → repository | Done |
| 09 FEB 2026 | 2.1 | `db_data._get_job()` → repository | Done |
| 09 FEB 2026 | 2.1 | `db_data._get_tasks()` → repository | Done |
| 09 FEB 2026 | 2.1 | `db_data._get_api_requests()` → repository | Done |
| 09 FEB 2026 | 2.1 | `db_data._get_api_request()` → repository | Done |
| 09 FEB 2026 | 2.1 | `db_data._get_tasks_for_job()` | DEFERRED |
| 09 FEB 2026 | 2.2 | `execution._query_jobs()` → repository | Done |
| 09 FEB 2026 | 2.2 | `execution._get_job_info()` → repository | Done |
| 09 FEB 2026 | 2.2 | `execution._get_task_counts()` → repository | Done |
| 09 FEB 2026 | 2.2 | `execution._get_task_counts_by_stage()` → repository | Done |
| 09 FEB 2026 | 2.2 | `execution._query_tasks()` → repository | Done |
| 09 FEB 2026 | 2.3 | `jobs._query_jobs_with_task_counts()` → repository | Done |
| 09 FEB 2026 | 2.4 | `data_cleanup.cleanup_old_records()` | DEFERRED |
| 09 FEB 2026 | - | **Phase 2 Complete** | ✅ |

---

## Files Changed

| File | Phase | Changes |
|------|-------|---------|
| `infrastructure/jobs_tasks.py` | 1.1, 1.2 | +6 repository methods (JobRepository + TaskRepository) |
| `infrastructure/platform.py` | 1.3 | Fixed FK columns in `get_all_requests()` |
| `triggers/admin/db_data.py` | 2.1 | 5 methods refactored to use repos |
| `web_interfaces/execution/interface.py` | 2.2 | 5 methods refactored to use repos |
| `web_interfaces/jobs/interface.py` | 2.3 | 1 method refactored to use repos |
| `config/__init__.py` | - | Version bumped to 0.8.16 |

---

*End of Plan*
