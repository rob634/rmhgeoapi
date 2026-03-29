# ============================================================================
# CLAUDE CONTEXT - PREFLIGHT VALIDATION ENDPOINT
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Diagnostic endpoint -- mode-aware write-path validation
# PURPOSE: Validate environment capabilities for QA deployment. Produces
#          actionable punch list of eService requests for missing RBAC/config.
# LAST_REVIEWED: 29 MAR 2026
# EXPORTS: bp (Blueprint), _run_preflight
# DEPENDENCIES: triggers.preflight_checks, config
# ============================================================================
"""
Preflight validation endpoint.

Runs mode-aware write-path checks and returns a structured punch list
of failures with Azure RBAC remediation for eService requests.

Endpoints:
    GET /api/preflight  - Run all checks for the current APP_MODE

Response codes:
    200: All checks passed (or skipped/warned)
    424: One or more checks failed (Failed Dependency)
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import azure.functions as func
from azure.functions import Blueprint

logger = logging.getLogger(__name__)

bp = Blueprint()


def _run_preflight() -> Tuple[Dict[str, Any], int]:
    """
    Execute all preflight checks for the current APP_MODE.

    Returns:
        Tuple of (response_body, http_status_code).
        200 if all checks pass/skip/warn, 424 if any fail.
    """
    from config import get_config, get_app_mode_config, __version__
    from triggers.preflight_checks import get_checks_for_mode

    config = get_config()
    app_mode_config = get_app_mode_config()
    mode = app_mode_config.mode

    checks = get_checks_for_mode(mode, app_mode_config.docker_worker_enabled)

    results: Dict[str, Any] = {}
    summary = {"pass": 0, "fail": 0, "skip": 0, "warn": 0}
    punch_list = []

    for check in checks:
        start = time.monotonic()
        try:
            result = check.run(config, mode)
        except Exception as exc:
            logger.exception("Preflight check '%s' raised an exception", check.name)
            from triggers.preflight_checks.base import PreflightResult
            result = PreflightResult.failed(
                detail=f"Check raised {type(exc).__name__}: {exc}"
            )
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        entry = result.to_dict()
        entry["elapsed_ms"] = elapsed_ms
        results[check.name] = entry

        summary[result.status] = summary.get(result.status, 0) + 1

        if result.status == "fail":
            item = {"check": check.name, "detail": result.detail}
            if result.remediation:
                item["remediation"] = result.remediation.to_dict()
            punch_list.append(item)

    status = "pass" if summary["fail"] == 0 else "fail"
    http_status = 200 if status == "pass" else 424

    body = {
        "status": status,
        "app_mode": mode.value,
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "checks": results,
        "punch_list": punch_list,
    }

    return body, http_status


@bp.route(
    route="preflight",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def preflight(req: func.HttpRequest) -> func.HttpResponse:
    """
    Preflight validation -- mode-aware write-path checks.

    Runs all preflight checks relevant to the current APP_MODE and returns
    a structured report with pass/fail/skip/warn per check. Failed checks
    include Azure RBAC remediation details for eService requests.

    Returns:
        200: All checks passed (or skipped/warned)
        424: One or more checks failed (Failed Dependency)
    """
    try:
        body, status_code = _run_preflight()
        return func.HttpResponse(
            json.dumps(body, indent=2),
            status_code=status_code,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.exception("Preflight endpoint failed")
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }, indent=2),
            status_code=500,
            mimetype="application/json",
        )
