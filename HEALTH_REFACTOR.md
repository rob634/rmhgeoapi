# Health Check Refactoring Plan

**Created**: 29 JAN 2026
**Status**: COMPLETE - All 7 Phases Done (19 checks in plugin architecture)
**Priority**: Medium (technical debt reduction)
**Last Updated**: 29 JAN 2026

---

## Executive Summary

The `triggers/health.py` file has grown to **3,231 lines** with **22 check methods** in a single class. This refactoring plan extracts health checks into a modular plugin architecture for improved maintainability, testability, and extensibility.

---

## Current State Analysis

### File Statistics
| Metric | Value |
|--------|-------|
| Total Lines | 3,231 |
| Token Count | ~36,000 |
| Check Methods | 22 |
| Class | `HealthCheckTrigger` (God Class) |

### Check Methods Inventory

| # | Method | Lines | Category |
|---|--------|-------|----------|
| 1 | `_check_deployment_config` | 1874-1993 | Startup |
| 2 | `_check_app_mode` | 1994-2052 | Application |
| 3 | `_check_endpoint_registration` | 2053-2170 | Application |
| 4 | `_check_runtime_environment` | 2790-2937 | Startup |
| 5 | `_check_network_environment` | 2938-3108 | Infrastructure |
| 6 | `_check_import_validation` | 1288-1343 | Startup |
| 7 | `_check_startup_validation` | 1209-1287 | Startup |
| 8 | `_check_storage_containers` | 493-616 | Infrastructure |
| 9 | `_check_service_bus_queues` | 617-919 | Infrastructure |
| 10 | `_check_database` | 920-1143 | Database |
| 11 | `_check_database_configuration` | 1144-1208 | Database |
| 12 | `_check_duckdb` | 1344-1403 | Database |
| 13 | `_check_jobs_registry` | 1404-1437 | Application |
| 14 | `_check_pgstac` | 1438-1630 | Database |
| 15 | `_check_system_reference_tables` | 1631-1873 | Database |
| 16 | `_check_schema_summary` | 2176-2308 | Database |
| 17 | `_check_public_database` | 2309-2425 | Database |
| 18 | `_check_geotiler_health` | 2426-2629 | External Services |
| 19 | `_check_ogc_features_health` | 2630-2710 | External Services |
| 20 | `_check_docker_worker_health` | 2711-2789 | External Services |
| 21 | `_get_config_sources` | 3110-3228 | Utilities |
| 22 | `_run_checks_parallel` | 87-159 | Utilities |

### Problems with Current Architecture

1. **God Class Anti-Pattern**: Single class with 22+ responsibilities
2. **No Modularity**: Cannot test check categories independently
3. **Maintenance Burden**: Adding a check requires modifying 3,200-line file
4. **Mixed Concerns**: Infrastructure, database, external services intermingled
5. **No Extensibility**: No plugin pattern for dynamically adding checks
6. **Difficult Code Review**: Changes touch massive file

---

## Target Architecture

### Directory Structure

```
triggers/
├── health.py                     # Orchestrator (~300 lines)
└── health_checks/                # Check plugins
    ├── __init__.py               # Plugin registry + exports
    ├── base.py                   # HealthCheckPlugin base class (~80 lines)
    ├── infrastructure.py         # Storage, Service Bus, Network (~500 lines)
    ├── database.py               # Database, PgSTAC, DuckDB, Schema (~950 lines)
    ├── external_services.py      # GeoTiler, OGC Features, Docker (~400 lines)
    ├── application.py            # App Mode, Endpoints, Jobs (~450 lines)
    └── startup.py                # Startup, Imports, Runtime, Deployment (~500 lines)
```

### Base Plugin Class

```python
# triggers/health_checks/base.py
from typing import Dict, Any, List, Tuple, Callable, Optional
from abc import ABC, abstractmethod
from datetime import datetime, timezone


class HealthCheckPlugin(ABC):
    """
    Base class for health check plugins.

    Each plugin represents a category of related health checks.
    Plugins are automatically discovered and registered.
    """

    # Plugin metadata (override in subclasses)
    name: str = "unknown"
    description: str = ""
    priority: int = 100  # Lower = runs earlier

    def __init__(self, logger=None):
        self.logger = logger

    @abstractmethod
    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """
        Return list of (check_name, check_method) tuples.

        Each check_method should return a dict with at minimum:
        - component: str - The component name
        - status: str - "healthy", "unhealthy", "warning", "error", "disabled"
        - checked_at: str - ISO timestamp

        Example:
            return [
                ("storage_containers", self.check_storage_containers),
                ("service_bus", self.check_service_bus),
            ]
        """
        raise NotImplementedError

    def is_enabled(self, config) -> bool:
        """
        Whether this plugin should run.

        Override to conditionally disable plugins based on config.
        Default: always enabled.
        """
        return True

    def get_parallel_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """
        Return checks that can run in parallel (I/O-bound).

        By default returns empty list. Override for plugins with
        external HTTP calls that benefit from parallel execution.
        """
        return []

    def check_component_health(
        self,
        component_name: str,
        check_func: Callable[[], Dict[str, Any]],
        description: str = ""
    ) -> Dict[str, Any]:
        """
        Standard wrapper for health checks with error handling.

        Args:
            component_name: Name of the component being checked
            check_func: Function that performs the actual check
            description: Human-readable description

        Returns:
            Standardized health check result dict
        """
        try:
            result = check_func()

            # Ensure required fields
            if "component" not in result:
                result["component"] = component_name
            if "checked_at" not in result:
                result["checked_at"] = datetime.now(timezone.utc).isoformat()

            # Determine status from result
            status = result.get("_status")  # Explicit override
            if not status:
                if result.get("error"):
                    status = "unhealthy"
                else:
                    status = "healthy"
            result["status"] = status

            # Remove internal _status key
            result.pop("_status", None)

            if description:
                result["description"] = description

            return result

        except Exception as e:
            if self.logger:
                self.logger.error(f"Health check '{component_name}' failed: {e}")
            return {
                "component": component_name,
                "status": "error",
                "error": str(e)[:500],
                "error_type": type(e).__name__,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
```

### Plugin Registry

```python
# triggers/health_checks/__init__.py
"""
Health Check Plugins Registry.

Plugins are automatically discovered and registered.
Add new plugins by creating a class that extends HealthCheckPlugin.
"""

from typing import List, Type
from .base import HealthCheckPlugin
from .infrastructure import InfrastructureHealthChecks
from .database import DatabaseHealthChecks
from .external_services import ExternalServicesHealthChecks
from .application import ApplicationHealthChecks
from .startup import StartupHealthChecks


# Ordered list of plugins (by priority)
HEALTH_CHECK_PLUGINS: List[Type[HealthCheckPlugin]] = [
    StartupHealthChecks,           # Priority 10 - Run first
    ApplicationHealthChecks,       # Priority 20
    InfrastructureHealthChecks,    # Priority 30
    DatabaseHealthChecks,          # Priority 40
    ExternalServicesHealthChecks,  # Priority 50 - Run last (parallel HTTP)
]


def get_all_plugins(logger=None) -> List[HealthCheckPlugin]:
    """Instantiate all registered plugins."""
    return [plugin_class(logger=logger) for plugin_class in HEALTH_CHECK_PLUGINS]


__all__ = [
    'HealthCheckPlugin',
    'HEALTH_CHECK_PLUGINS',
    'get_all_plugins',
    'InfrastructureHealthChecks',
    'DatabaseHealthChecks',
    'ExternalServicesHealthChecks',
    'ApplicationHealthChecks',
    'StartupHealthChecks',
]
```

### Refactored Orchestrator

```python
# triggers/health.py (after refactor - ~300 lines)
"""
Health Check HTTP Trigger - Orchestrator.

Coordinates health check plugins and aggregates results.
Individual checks are implemented in triggers/health_checks/*.py
"""

from typing import Dict, Any, List
from datetime import datetime, timezone
import azure.functions as func

from .http_base import SystemMonitoringTrigger
from .health_checks import get_all_plugins


class HealthCheckTrigger(SystemMonitoringTrigger):
    """Health check HTTP trigger - orchestrates plugins."""

    def __init__(self):
        super().__init__("health_check")
        self.plugins = get_all_plugins(logger=self.logger)

    def get_allowed_methods(self) -> List[str]:
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """Orchestrate all health check plugins."""
        from config import get_config, __version__

        config = get_config()
        health_data = {
            "status": "healthy",
            "version": __version__,
            "components": {},
            "warnings": [],
            "errors": []
        }

        # Run each plugin
        for plugin in self.plugins:
            if not plugin.is_enabled(config):
                continue

            # Run sequential checks
            for check_name, check_method in plugin.get_checks():
                result = check_method()
                health_data["components"][check_name] = result
                self._update_status(health_data, result)

            # Run parallel checks (I/O-bound)
            parallel_checks = plugin.get_parallel_checks()
            if parallel_checks:
                parallel_results = self._run_checks_parallel(parallel_checks)
                for check_name, result in parallel_results.items():
                    health_data["components"][check_name] = result
                    self._update_status(health_data, result)

        return health_data

    def _update_status(self, health_data: Dict, result: Dict):
        """Update overall status based on check result."""
        status = result.get("status")
        if status == "unhealthy":
            health_data["status"] = "unhealthy"
            if result.get("error"):
                health_data["errors"].append(result["error"])
        elif status == "warning" and health_data["status"] == "healthy":
            health_data["status"] = "degraded"
            if result.get("warning"):
                health_data["warnings"].append(result["warning"])
```

---

## Implementation Phases

### Phase 1: Foundation - COMPLETE (29 JAN 2026)

**Goal**: Create plugin infrastructure without breaking existing functionality.

**Tasks**:
1. [x] Create `triggers/health_checks/` directory
2. [x] Create `base.py` with `HealthCheckPlugin` base class
3. [x] Create `__init__.py` with plugin registry
4. [x] Create empty plugin files with class stubs
5. [x] **Test**: Verify existing health endpoint still works

**Files Created**:
- `triggers/health_checks/__init__.py` - Plugin registry with `get_all_plugins()`
- `triggers/health_checks/base.py` - `HealthCheckPlugin` ABC with `check_component_health()`
- `triggers/health_checks/infrastructure.py` (stub) - Priority 30
- `triggers/health_checks/database.py` (stub) - Priority 40
- `triggers/health_checks/external_services.py` (stub) - Priority 50
- `triggers/health_checks/application.py` (stub) - Priority 20
- `triggers/health_checks/startup.py` (stub) - Priority 10

**Validation Results**:
```
=== Health Check Plugin Architecture Test ===
Registered plugins: 5

  [10] startup              - 0 checks, 0 parallel
  [20] application          - 0 checks, 0 parallel
  [30] infrastructure       - 0 checks, 0 parallel
  [40] database             - 0 checks, 0 parallel
  [50] external_services    - 0 checks, 0 parallel

All imports successful!
HealthCheckTrigger initialized: health_check
Existing health.py still works!
```

---

### Phase 2: Application Checks - COMPLETE (29 JAN 2026)

**Goal**: Migrate smallest category first as proof of concept.

**Methods Migrated**:
- [x] `check_app_mode` (~60 lines)
- [x] `check_endpoint_registration` (~120 lines)
- [x] `check_jobs_registry` (~35 lines)

**Total**: ~290 lines → `application.py`

**Validation Results**:
```
  [20] application          - 3 sequential, 0 parallel = 3 total
       - app_mode
       - endpoint_registration
       - jobs
```

---

### Phase 3: Startup Checks - COMPLETE (29 JAN 2026)

**Goal**: Migrate startup-related checks.

**Methods Migrated**:
- [x] `check_deployment_config` (~120 lines)
- [x] `check_startup_validation` (~80 lines)
- [x] `check_import_validation` (~55 lines)
- [x] `check_runtime_environment` (~150 lines)

**Total**: ~450 lines → `startup.py`

**Validation Results**:
```
  [10] startup              - 4 sequential, 0 parallel = 4 total
       - deployment_config
       - startup_validation
       - imports
       - runtime
```

---

### Phase 4: External Services - COMPLETE (29 JAN 2026)

**Goal**: Migrate I/O-bound checks that run in parallel.

**Methods Migrated**:
- [x] `check_geotiler_health` (~200 lines)
- [x] `check_ogc_features_health` (~80 lines)
- [x] `check_docker_worker_health` (~80 lines)

**Total**: ~425 lines → `external_services.py`

**Special Feature**: Uses `get_parallel_checks()` for I/O-bound parallel execution.

**Validation Results**:
```
  [50] external_services    - 0 sequential, 2 parallel = 2 total
       - geotiler (parallel)
       - ogc_features (parallel)
```

Note: docker_worker only appears when DOCKER_WORKER_ENABLED=true

---

### Phase 5: Infrastructure Checks - COMPLETE (29 JAN 2026)

**Goal**: Migrate infrastructure-related checks.

**Methods Migrated**:
- [x] `check_storage_containers` (~175 lines)
- [x] `check_service_bus_queues` (~285 lines) + helper `_get_service_bus_fix_recommendation`
- [x] `check_network_environment` (~140 lines)

**Total**: ~630 lines → `infrastructure.py`

**Validation Results**:
```
  [30] infrastructure       - 3 sequential, 0 parallel = 3 total
       - storage_containers
       - service_bus
       - network_environment
```

---

### Phase 6: Database Checks - COMPLETE (29 JAN 2026)

**Goal**: Migrate largest category - database-related checks.

**Methods Migrated**:
- [x] `check_database` (~200 lines)
- [x] `check_database_configuration` (~55 lines)
- [x] `check_duckdb` (~45 lines)
- [x] `check_pgstac` (~175 lines)
- [x] `check_system_reference_tables` (~200 lines)
- [x] `check_schema_summary` (~115 lines)
- [x] `check_public_database` (~100 lines)

**Total**: ~1,025 lines → `database.py`

**Validation Results**:
```
  [40] database             - 7 sequential, 0 parallel = 7 total
       - database
       - database_config
       - duckdb
       - pgstac
       - system_reference_tables
       - schema_summary
       - public_database
```

---

---

## Progress Summary (Phases 1-6 Complete)

| Plugin | Priority | Sequential | Parallel | Total |
|--------|----------|------------|----------|-------|
| startup | 10 | 4 | 0 | 4 |
| application | 20 | 3 | 0 | 3 |
| infrastructure | 30 | 3 | 0 | 3 |
| database | 40 | 7 | 0 | 7 |
| external_services | 50 | 0 | 2-3* | 2-3 |
| **Total** | | **17** | **2-3** | **19-20** |

*docker_worker check only appears when `DOCKER_WORKER_ENABLED=true`

---

### Phase 7: Cleanup & Integration - COMPLETE (29 JAN 2026)

**Goal**: Final cleanup - update health.py orchestrator to use plugins.

**Tasks Completed**:
1. [x] Update `health.py` `process_request` to iterate over plugins
2. [x] Remove all migrated check methods from `health.py`
3. [x] Keep `_run_checks_parallel` in orchestrator for parallel execution
4. [x] Keep `_get_config_sources` in orchestrator for observability mode
5. [x] Final testing: all 19 checks verified working
6. [x] Update documentation

**Final File Sizes**:
| File | Lines |
|------|-------|
| `health.py` | 511 |
| `__init__.py` | 105 |
| `base.py` | 193 |
| `startup.py` | 448 |
| `application.py` | 289 |
| `infrastructure.py` | 629 |
| `database.py` | 1,024 |
| `external_services.py` | 424 |
| **Total** | **3,623** |

**Reduction**: 3,231 lines → 511 lines in main file (84% reduction)

**Final File Sizes**:
| File | Target Lines |
|------|-------------|
| `health.py` | ~300 |
| `base.py` | ~100 |
| `__init__.py` | ~50 |
| `infrastructure.py` | ~600 |
| `database.py` | ~1,050 |
| `external_services.py` | ~400 |
| `application.py` | ~250 |
| `startup.py` | ~500 |

---

## Testing Strategy

### Unit Tests (Per Plugin)

```python
# tests/test_health_checks/test_application.py
import pytest
from triggers.health_checks.application import ApplicationHealthChecks

def test_app_mode_check():
    plugin = ApplicationHealthChecks()
    checks = plugin.get_checks()
    assert any(name == "app_mode" for name, _ in checks)

def test_check_returns_valid_structure():
    plugin = ApplicationHealthChecks()
    for name, check_method in plugin.get_checks():
        result = check_method()
        assert "component" in result
        assert "status" in result
        assert result["status"] in ("healthy", "unhealthy", "warning", "error", "disabled")
```

### Integration Tests

```bash
# Full health endpoint test
curl -sf http://localhost:7071/api/health | jq '.status'

# Component count verification (should have ~15-20 components)
curl -sf http://localhost:7071/api/health | jq '.components | length'

# No errors in healthy state
curl -sf http://localhost:7071/api/health | jq '.errors | length' | grep -q "0"
```

### Regression Prevention

After each phase:
1. Run full health check locally
2. Verify component count matches expected
3. Verify no new errors introduced
4. Deploy to dev and test

---

## Rollback Plan

Each phase is independently reversible:

1. **Git**: Each phase is a separate commit
2. **Feature Flag**: Can add `HEALTH_CHECK_PLUGINS_ENABLED` flag
3. **Fallback**: Keep original methods commented until phase complete

```python
# Example fallback pattern during migration
def process_request(self, req):
    if os.getenv("USE_LEGACY_HEALTH_CHECKS"):
        return self._legacy_process_request(req)
    return self._plugin_process_request(req)
```

---

## Success Criteria

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| `health.py` lines | 3,231 | ~300 | < 400 |
| Check methods in single file | 22 | 0 | 0 |
| Files with health checks | 1 | 6 | 5-7 |
| Max file size | 3,231 | ~1,050 | < 1,200 |
| Test coverage | Low | Per-plugin | > 80% |

---

## Dependencies

- No external dependencies required
- Uses existing `SystemMonitoringTrigger` base class
- Uses existing `check_component_health` pattern

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Regression in health checks | Medium | High | Phase-by-phase migration with testing |
| Import cycle | Low | Medium | Careful dependency management |
| Performance degradation | Low | Low | Parallel execution preserved |
| Incomplete migration | Low | Medium | Track progress per phase |

---

## Timeline

| Phase | Estimated Sessions | Dependencies |
|-------|-------------------|--------------|
| Phase 1: Foundation | 1 | None |
| Phase 2: Application | 1 | Phase 1 |
| Phase 3: Startup | 1 | Phase 1 |
| Phase 4: External Services | 1 | Phase 1 |
| Phase 5: Infrastructure | 1 | Phase 1 |
| Phase 6: Database | 2 | Phase 1 |
| Phase 7: Cleanup | 1 | Phases 2-6 |
| **Total** | **8 sessions** | |

---

## Appendix: Check Method Line Counts

```
Method                              Start   End    Lines
─────────────────────────────────────────────────────────
_run_checks_parallel                  87    159      72
process_request                      161    412     251
handle_request                       414    491      77
_check_storage_containers            493    616     123
_check_service_bus_queues            617    919     302
_check_database                      920   1143     223
_check_database_configuration       1144   1208      64
_check_startup_validation           1209   1287      78
_check_import_validation            1288   1343      55
_check_duckdb                       1344   1403      59
_check_jobs_registry                1404   1437      33
_check_pgstac                       1438   1630     192
_check_system_reference_tables      1631   1873     242
_check_deployment_config            1874   1993     119
_check_app_mode                     1994   2052      58
_check_endpoint_registration        2053   2170     117
_check_schema_summary               2176   2308     132
_check_public_database              2309   2425     116
_check_geotiler_health              2426   2629     203
_check_ogc_features_health          2630   2710      80
_check_docker_worker_health         2711   2789      78
_check_runtime_environment          2790   2937     147
_check_network_environment          2938   3108     170
_get_config_sources                 3110   3228     118
─────────────────────────────────────────────────────────
TOTAL                                              3,099
```
