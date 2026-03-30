"""
Preflight check base class and result structures.

Preflight checks validate write-path capabilities (not just connectivity).
Each failed check includes exact Azure RBAC remediation for eService requests.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

from config.app_mode_config import AppMode


@dataclass
class Remediation:
    """Actionable fix -- maps 1:1 to an eService request."""

    action: str
    azure_role: Optional[str] = None
    scope: Optional[str] = None
    eservice_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PreflightResult:
    """Result of a single preflight check."""

    status: str  # "pass", "fail", "skip", "warn"
    detail: str
    remediation: Optional[Remediation] = None
    sub_checks: Optional[Dict[str, Any]] = None

    @classmethod
    def passed(cls, detail: str, **kwargs) -> "PreflightResult":
        return cls(status="pass", detail=detail, **kwargs)

    @classmethod
    def failed(cls, detail: str, remediation: Optional[Remediation] = None, **kwargs) -> "PreflightResult":
        return cls(status="fail", detail=detail, remediation=remediation, **kwargs)

    @classmethod
    def skipped(cls, detail: str) -> "PreflightResult":
        return cls(status="skip", detail=detail)

    @classmethod
    def warned(cls, detail: str, remediation: Optional[Remediation] = None) -> "PreflightResult":
        return cls(status="warn", detail=detail, remediation=remediation)

    def to_dict(self) -> Dict[str, Any]:
        d = {"status": self.status, "detail": self.detail}
        if self.remediation:
            d["remediation"] = self.remediation.to_dict()
        if self.sub_checks:
            d["sub_checks"] = self.sub_checks
        return d


class PreflightCheck(ABC):
    """Base class for preflight validation checks."""

    name: str = "unknown"
    description: str = ""
    required_modes: set  # Which APP_MODEs require this check

    def is_required(self, mode: AppMode, docker_worker_enabled: bool = False) -> bool:
        """Check if this check is needed for the given mode.

        STANDALONE inherits worker checks when docker_worker_enabled=False
        (it processes locally). When docker_worker_enabled=True, worker-only
        checks are skipped (external worker handles them).
        """
        if mode == AppMode.STANDALONE:
            if not docker_worker_enabled:
                # Include worker checks — standalone processes locally
                return mode in self.required_modes or AppMode.WORKER_DOCKER in self.required_modes
            else:
                # STANDALONE is explicitly listed → always run.
                # Only skip checks where STANDALONE is NOT listed but WORKER_DOCKER is
                # (those are worker-only checks the external worker handles).
                if mode in self.required_modes:
                    return True
                return False
        return mode in self.required_modes

    @abstractmethod
    def run(self, config, app_mode: AppMode) -> PreflightResult:
        """Execute the check. Returns structured result with remediation on failure."""
        ...
