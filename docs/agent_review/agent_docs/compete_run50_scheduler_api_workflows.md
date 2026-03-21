# COMPETE Run 50: Scheduler + API-Driven Workflows

| Field | Value |
|-------|-------|
| **Date** | 20 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | Scheduler infrastructure, APIRepository, ACLED sync workflow |
| **Version** | v0.10.4.x |
| **Split** | B (Internal vs External) |
| **Files** | 15 |
| **Findings** | 28 total: 6 CRITICAL, 7 HIGH, 8 MEDIUM, 7 LOW |
| **Gamma Blind Spots** | 9 new findings (2 CRITICAL, 3 HIGH, 2 MEDIUM, 2 confirmed expansions) |
| **Fixes Pending** | Top 5 recommended |

## Top 5 Fixes

| # | Severity | Description | File | Effort |
|---|----------|-------------|------|--------|
| 1 | CRITICAL | `get_workflow_registry` does not exist + `__contains__` not on WorkflowRegistry — schedule creation crashes | `dag_bp.py:658-663`, `workflow_registry.py` | Small |
| 2 | HIGH | `get_active_run_count` joins on `last_run_id` (scalar) — concurrency guard broken | `schedule_repository.py:440-474` | Medium |
| 3 | CRITICAL | f-string SQL in `dag_list_runs` + 5 direct `_get_connection()` calls — S1.2 + S1.4 | `dag_bp.py:89-112, 110, 169, 184, 272, 780` | Medium |
| 4 | CRITICAL | `os.environ` in ACLEDRepository + ACLED handlers missing from DOCKER_TASKS | `acled_repository.py:69-70`, `config/defaults.py` | Small |
| 5 | CRITICAL | Process-wide `urllib3.disable_warnings()` — suppresses SSL warnings for entire container | `acled_repository.py:22-23` | Small |

## Accepted Risks

| Risk | Why Acceptable | Revisit When |
|------|---------------|-------------|
| schedule_id not passed to create_run | Traceable via request_id in logs | Fix with FIX 2 schema change |
| WorkflowRegistry instantiated per-fire | Negligible I/O at current scale | Workflow count > 50 or poll < 5s |
| Pagination stops on first empty page | Incremental sync is re-runnable | Compliance-critical data use |
| Bronze blob 1-second timestamp collision | Deterministic request_id prevents double-fire | Never (window is effectively zero) |
| Health endpoint exposes internal config | Admin-only, not secrets | Endpoint exposed without APP_MODE gate |

## Architecture Wins

- Fail-open scheduler loop — per-schedule exception isolation
- SQL composition discipline in ScheduleRepository
- Deterministic schedule_id and request_id generation (SHA256)
- WorkflowRegistry.has() exists as the correct existence check
- SchedulerConfig.from_environment() properly isolated
