# Startup Reform: Kubernetes-Style Health Probes

**Created**: 03 JAN 2026
**Status**: PLANNED
**Priority**: HIGH (blocking QA/corporate deployment diagnostics)

---

## Problem Statement

### Current Behavior

The application uses **fail-fast startup validation** that crashes the entire app if:
- Required environment variables are missing
- Service Bus DNS cannot be resolved (VNet/ASE issue)
- Service Bus queues don't exist
- Critical imports fail

```
function_app.py startup sequence:
1. Import validation          → raises ImportError
2. Pre-flight env var check   → raises RuntimeError
3. Service Bus DNS check      → raises RuntimeError   ← BLOCKS HERE IN QA
4. Service Bus queue check    → raises RuntimeError
5. Trigger registration       → never reached
```

### The Problem

When startup validation fails:
- **No /api/health endpoint** - cannot diagnose issues via HTTP
- **No /api/livez endpoint** - load balancer sees app as dead
- **Only Application Insights** has error details (requires Azure Portal access)
- **Corporate QA environments** with VNet/ASE restrictions cannot self-diagnose

### Root Cause

Diagnostic endpoints are registered AFTER validation runs. If validation fails, no endpoints exist.

---

## Proposed Solution: Option A+C Combined

### Kubernetes-Style Probe Pattern

| Endpoint | Purpose | Availability | Response |
|----------|---------|--------------|----------|
| `/api/livez` | Is process alive? | **ALWAYS** | 200 if Python loaded |
| `/api/readyz` | Ready for traffic? | **ALWAYS** | 200 if validation passed, 503 if failed |
| `/api/health` | Full diagnostics | **ALWAYS** | JSON with component status + startup errors |

### Architecture Change

```
BEFORE (Current):
┌─────────────────────────────────────────────────────┐
│  function_app.py                                    │
├─────────────────────────────────────────────────────┤
│  1. Import validation        → CRASH if fails      │
│  2. Env var check            → CRASH if fails      │
│  3. Service Bus validation   → CRASH if fails      │
│  4. Register ALL endpoints   → Never reached       │
└─────────────────────────────────────────────────────┘

AFTER (Proposed):
┌─────────────────────────────────────────────────────┐
│  function_app.py                                    │
├─────────────────────────────────────────────────────┤
│  PHASE 1: Core Endpoints (ALWAYS register)         │
│    - /api/livez                                     │
│    - /api/readyz                                    │
│    - /api/health                                    │
├─────────────────────────────────────────────────────┤
│  PHASE 2: Soft Validation (store errors, no crash) │
│    - _startup_state["env_vars"] = {...}            │
│    - _startup_state["service_bus_dns"] = {...}     │
│    - _startup_state["service_bus_queues"] = {...}  │
│    - _startup_state["imports"] = {...}             │
├─────────────────────────────────────────────────────┤
│  PHASE 3: Conditional Registration                  │
│    - IF validation passed: register triggers       │
│    - IF validation failed: log, skip triggers      │
└─────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Create Startup State Module

**File**: `startup_state.py` (new file at root)

```python
"""
Startup State Module.

Stores validation results for diagnostic endpoints.
This module has ZERO dependencies to ensure it loads first.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    name: str
    passed: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class StartupState:
    """Global startup state for diagnostic endpoints."""

    # Validation results
    env_vars: Optional[ValidationResult] = None
    imports: Optional[ValidationResult] = None
    service_bus_dns: Optional[ValidationResult] = None
    service_bus_queues: Optional[ValidationResult] = None
    database: Optional[ValidationResult] = None

    # Overall status
    validation_complete: bool = False
    all_passed: bool = False
    startup_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "validation_complete": self.validation_complete,
            "all_passed": self.all_passed,
            "startup_time": self.startup_time,
            "checks": {
                "env_vars": self.env_vars.__dict__ if self.env_vars else None,
                "imports": self.imports.__dict__ if self.imports else None,
                "service_bus_dns": self.service_bus_dns.__dict__ if self.service_bus_dns else None,
                "service_bus_queues": self.service_bus_queues.__dict__ if self.service_bus_queues else None,
                "database": self.database.__dict__ if self.database else None,
            }
        }

    def get_failed_checks(self) -> List[ValidationResult]:
        """Get list of failed validation checks."""
        checks = [self.env_vars, self.imports, self.service_bus_dns,
                  self.service_bus_queues, self.database]
        return [c for c in checks if c and not c.passed]


# Global singleton - imported by diagnostic endpoints
STARTUP_STATE = StartupState()
```

**TODO**:
- [ ] Create `startup_state.py` at project root
- [ ] Ensure ZERO imports from other project modules (must load first)
- [ ] Add unit tests for serialization

---

### Phase 2: Create Minimal Probe Endpoints

**File**: `triggers/probes.py` (new file)

```python
"""
Kubernetes-Style Health Probes.

These endpoints have MINIMAL dependencies and are registered FIRST
to ensure they're always available for diagnostics.

Endpoints:
    GET /api/livez  - Liveness probe (always 200 if process alive)
    GET /api/readyz - Readiness probe (200 if ready, 503 if not)
"""

import azure.functions as func
from startup_state import STARTUP_STATE


def register_probes(app: func.FunctionApp) -> None:
    """Register probe endpoints. Call this FIRST in function_app.py."""

    @app.route(route="livez", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def livez(req: func.HttpRequest) -> func.HttpResponse:
        """
        Liveness probe - Is the process alive?

        Always returns 200 if the Python process loaded successfully.
        Used by load balancers to detect crashed processes.
        """
        return func.HttpResponse(
            '{"status": "alive", "probe": "livez"}',
            status_code=200,
            mimetype="application/json"
        )

    @app.route(route="readyz", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def readyz(req: func.HttpRequest) -> func.HttpResponse:
        """
        Readiness probe - Is the app ready to handle requests?

        Returns 200 if all startup validations passed.
        Returns 503 if any validation failed (with error details).
        """
        if not STARTUP_STATE.validation_complete:
            return func.HttpResponse(
                '{"status": "initializing", "probe": "readyz"}',
                status_code=503,
                mimetype="application/json"
            )

        if STARTUP_STATE.all_passed:
            return func.HttpResponse(
                '{"status": "ready", "probe": "readyz"}',
                status_code=200,
                mimetype="application/json"
            )
        else:
            import json
            failed = STARTUP_STATE.get_failed_checks()
            return func.HttpResponse(
                json.dumps({
                    "status": "not_ready",
                    "probe": "readyz",
                    "failed_checks": [f.name for f in failed],
                    "errors": [{"name": f.name, "type": f.error_type, "message": f.error_message} for f in failed]
                }),
                status_code=503,
                mimetype="application/json"
            )
```

**TODO**:
- [ ] Create `triggers/probes.py`
- [ ] Keep dependencies minimal (only azure.functions and startup_state)
- [ ] Test that 503 response includes useful error info

---

### Phase 3: Refactor function_app.py

**Changes to `function_app.py`**:

```python
# ============================================================================
# PHASE 1: PROBE ENDPOINTS (Register FIRST - before any validation)
# ============================================================================
# These endpoints MUST be available even if the app is misconfigured.
# They enable diagnostics in corporate/VNet environments.

import azure.functions as func
app = func.FunctionApp()

# Register probes immediately - no dependencies
from triggers.probes import register_probes
register_probes(app)

# Import startup state for storing validation results
from startup_state import STARTUP_STATE, ValidationResult

# ============================================================================
# PHASE 2: SOFT VALIDATION (Store errors, don't crash)
# ============================================================================

import logging
_startup_logger = logging.getLogger("startup")

# --- ENV VAR VALIDATION ---
try:
    _missing_vars = []
    # ... existing env var checks ...

    if _missing_vars:
        STARTUP_STATE.env_vars = ValidationResult(
            name="env_vars",
            passed=False,
            error_type="MISSING_ENV_VARS",
            error_message=f"Missing: {', '.join(_missing_vars)}",
            details={"missing": _missing_vars}
        )
        _startup_logger.critical(f"ENV VAR CHECK FAILED: {_missing_vars}")
    else:
        STARTUP_STATE.env_vars = ValidationResult(name="env_vars", passed=True)

except Exception as e:
    STARTUP_STATE.env_vars = ValidationResult(
        name="env_vars", passed=False, error_type="EXCEPTION", error_message=str(e)
    )

# --- SERVICE BUS DNS VALIDATION ---
try:
    import socket
    # ... existing DNS check ...

    try:
        _dns_results = socket.getaddrinfo(_hostname, 5671, ...)
        STARTUP_STATE.service_bus_dns = ValidationResult(
            name="service_bus_dns",
            passed=True,
            details={"hostname": _hostname, "ips": _resolved_ips}
        )
    except socket.gaierror as e:
        STARTUP_STATE.service_bus_dns = ValidationResult(
            name="service_bus_dns",
            passed=False,
            error_type="DNS_RESOLUTION_FAILED",
            error_message=str(e),
            details={
                "hostname": _hostname,
                "likely_causes": [
                    "SERVICE_BUS_NAMESPACE env var incorrect",
                    "VNet DNS not configured",
                    "Private DNS zone not linked"
                ]
            }
        )
        _startup_logger.critical(f"SERVICE BUS DNS FAILED: {e}")

except Exception as e:
    STARTUP_STATE.service_bus_dns = ValidationResult(
        name="service_bus_dns", passed=False, error_type="EXCEPTION", error_message=str(e)
    )

# --- SERVICE BUS QUEUE VALIDATION ---
# Only run if DNS passed
if STARTUP_STATE.service_bus_dns and STARTUP_STATE.service_bus_dns.passed:
    try:
        # ... existing queue checks ...
        pass
    except Exception as e:
        STARTUP_STATE.service_bus_queues = ValidationResult(
            name="service_bus_queues", passed=False, error_type="EXCEPTION", error_message=str(e)
        )
else:
    STARTUP_STATE.service_bus_queues = ValidationResult(
        name="service_bus_queues",
        passed=False,
        error_type="SKIPPED",
        error_message="Skipped due to DNS failure"
    )

# --- FINALIZE VALIDATION STATE ---
STARTUP_STATE.validation_complete = True
STARTUP_STATE.all_passed = all([
    STARTUP_STATE.env_vars and STARTUP_STATE.env_vars.passed,
    STARTUP_STATE.service_bus_dns and STARTUP_STATE.service_bus_dns.passed,
    STARTUP_STATE.service_bus_queues and STARTUP_STATE.service_bus_queues.passed,
])

if STARTUP_STATE.all_passed:
    _startup_logger.info("✅ STARTUP: All validations passed")
else:
    failed = STARTUP_STATE.get_failed_checks()
    _startup_logger.warning(f"⚠️ STARTUP: {len(failed)} validation(s) failed: {[f.name for f in failed]}")

# ============================================================================
# PHASE 3: CONDITIONAL REGISTRATION (Only if validation passed)
# ============================================================================

if STARTUP_STATE.all_passed:
    # Register Service Bus triggers
    @app.service_bus_queue_trigger(...)
    def process_job(...):
        ...
else:
    _startup_logger.warning("⏭️ STARTUP: Skipping trigger registration due to validation failures")
    _startup_logger.warning("   App will respond to /api/livez, /api/readyz, /api/health only")

# ALWAYS register health endpoint (but it will show validation errors)
from triggers.health import HealthCheckTrigger
# ... register health ...
```

**TODO**:
- [ ] Move `app = func.FunctionApp()` to very top
- [ ] Register probes BEFORE any imports that might fail
- [ ] Wrap each validation block in try/except
- [ ] Store results in STARTUP_STATE instead of raising
- [ ] Add validation_complete and all_passed checks
- [ ] Conditionally register Service Bus triggers
- [ ] Update health endpoint to include startup state

---

### Phase 4: Enhance Health Endpoint

**Changes to `triggers/health.py`**:

Add startup validation status to health response:

```python
def _check_startup_validation(self) -> Dict[str, Any]:
    """Check startup validation status."""
    from startup_state import STARTUP_STATE

    if not STARTUP_STATE.validation_complete:
        return {
            "component": "startup_validation",
            "status": "initializing",
            "details": {"message": "Startup validation still in progress"}
        }

    if STARTUP_STATE.all_passed:
        return {
            "component": "startup_validation",
            "status": "healthy",
            "details": STARTUP_STATE.to_dict()
        }
    else:
        failed = STARTUP_STATE.get_failed_checks()
        return {
            "component": "startup_validation",
            "status": "unhealthy",
            "details": {
                "failed_checks": [f.to_dict() for f in failed],
                "all_checks": STARTUP_STATE.to_dict()
            }
        }
```

**TODO**:
- [ ] Add `_check_startup_validation()` method to HealthCheckTrigger
- [ ] Include in health response components
- [ ] Make startup_validation a CRITICAL component (affects overall status)

---

### Phase 5: Testing Plan

**Local Testing**:
```bash
# Test with missing env vars
unset SERVICE_BUS_NAMESPACE
func start
curl http://localhost:7071/api/livez   # Should return 200
curl http://localhost:7071/api/readyz  # Should return 503 with error details
curl http://localhost:7071/api/health  # Should show startup_validation: unhealthy

# Test with invalid DNS
export SERVICE_BUS_NAMESPACE="invalid.servicebus.windows.net"
func start
curl http://localhost:7071/api/readyz  # Should return 503 with DNS error
```

**QA/Corporate Testing**:
```bash
# After deployment to VNet environment
curl https://{app-url}/api/livez   # Should return 200 (process alive)
curl https://{app-url}/api/readyz  # Should return 503 with VNet DNS error details
curl https://{app-url}/api/health  # Full diagnostics including startup_validation
```

**TODO**:
- [ ] Create test script for local validation
- [ ] Document expected responses for each failure mode
- [ ] Add integration tests for probe endpoints

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `startup_state.py` | CREATE | New module for startup state storage |
| `triggers/probes.py` | CREATE | New livez/readyz endpoints |
| `function_app.py` | MODIFY | Restructure into 3 phases |
| `triggers/health.py` | MODIFY | Add startup_validation component |
| `.funcignore` | MODIFY | Ensure new files not ignored |

---

## Rollback Plan

If issues arise:
1. Set `STARTUP_VALIDATION_MODE=strict` env var (add support for this)
2. This reverts to current fail-fast behavior
3. Remove after fixing issues

---

## Success Criteria

- [ ] `/api/livez` returns 200 even when Service Bus DNS fails
- [ ] `/api/readyz` returns 503 with clear error details
- [ ] `/api/health` shows `startup_validation` component with failure info
- [ ] Application Insights still logs STARTUP_FAILED for alerting
- [ ] Service Bus triggers only register when validation passes
- [ ] No regression in happy-path startup time

---

## References

- Kubernetes Probe Documentation: https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- Azure Functions Health Checks: https://learn.microsoft.com/en-us/azure/azure-functions/functions-monitoring
- Current health.py implementation: `triggers/health.py`
- Current startup validation: `function_app.py` lines 2186-2390

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 03 JAN 2026 | Claude | Initial design document |
