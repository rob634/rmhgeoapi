# ============================================================================
# CLAUDE CONTEXT - PREFLIGHT CHECK: BLOB STORAGE
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Preflight check - Azure token acquisition + blob CRUD canary
# PURPOSE: Validate blob storage write-path: token acquisition, silver CRUD,
#          bronze read access — with actionable RBAC remediation on failure
# LAST_REVIEWED: 29 MAR 2026
# EXPORTS: StorageTokenCheck, BlobCRUDCheck
# DEPENDENCIES: azure.identity, infrastructure.blob, config
# ============================================================================
"""
Preflight checks: Azure Blob Storage write-path validation.

Two checks:
1. StorageTokenCheck  — DefaultAzureCredential can acquire a storage token
2. BlobCRUDCheck      — Silver WRITE/READ/DELETE + Bronze LIST round-trip
"""

import logging

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

# ============================================================================
# Mode sets
# ============================================================================

_TOKEN_MODES = {AppMode.STANDALONE, AppMode.WORKER_DOCKER}
_CRUD_MODES = {AppMode.WORKER_DOCKER}

_CANARY_BLOB = "_preflight_canary/canary.txt"
_CANARY_CONTENT = b"preflight-canary-test"

_STORAGE_SCOPE = "https://storage.azure.com/.default"


# ============================================================================
# Check 1: StorageTokenCheck — credential → token acquisition
# ============================================================================

class StorageTokenCheck(PreflightCheck):
    """Verify DefaultAzureCredential can acquire an Azure Storage token."""

    name = "storage_token"
    description = "Verify managed identity can acquire an Azure Storage OAuth token"
    required_modes = _TOKEN_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            token = credential.get_token(_STORAGE_SCOPE)

            # Compute TTL in minutes (token.expires_on is a Unix timestamp int)
            import time
            ttl_minutes = max(0, int((token.expires_on - time.time()) / 60))

            return PreflightResult.passed(
                f"Storage token acquired successfully (TTL ~{ttl_minutes} min)"
            )

        except Exception as exc:
            logger.warning("StorageTokenCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"Storage token acquisition failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action=(
                        "Assign managed identity the 'Storage Blob Data Contributor' role "
                        "on the storage account(s). Verify the app's system-assigned managed "
                        "identity is enabled and has access to the correct storage scope."
                    ),
                    azure_role="Storage Blob Data Contributor",
                    eservice_summary=(
                        "AZURE RBAC: App managed identity cannot acquire storage token. "
                        "Assign 'Storage Blob Data Contributor' role on both Silver and Bronze "
                        "storage accounts."
                    ),
                ),
            )


# ============================================================================
# Check 2: BlobCRUDCheck — silver WRITE/READ/DELETE + bronze LIST
# ============================================================================

class BlobCRUDCheck(PreflightCheck):
    """
    Canary blob CRUD round-trip against Silver and Bronze storage zones.

    Silver: WRITE → READ (verify content) → DELETE
    Bronze: LIST (verify read access with limit=1)

    STANDALONE inherits this check when docker_worker_enabled=False (via
    PreflightCheck.is_required() which includes WORKER_DOCKER checks in that case).
    """

    name = "blob_crud"
    description = (
        "Canary blob WRITE/READ/DELETE on Silver + LIST on Bronze "
        "to verify storage write-path permissions"
    )
    required_modes = _CRUD_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        from infrastructure.blob import BlobRepository

        silver_container = config.storage.silver.cogs
        silver_account = config.storage.silver.account_name
        bronze_container = config.storage.bronze.rasters
        bronze_account = config.storage.bronze.account_name

        sub_checks: dict = {}
        failures: list[str] = []

        # ------------------------------------------------------------------ #
        # Silver WRITE
        # ------------------------------------------------------------------ #
        silver_repo = None
        try:
            silver_repo = BlobRepository.for_zone("silver")
            silver_repo.write_blob(
                silver_container,
                _CANARY_BLOB,
                _CANARY_CONTENT,
                overwrite=True,
                content_type="text/plain",
            )
            sub_checks["silver_write"] = "pass"
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            sub_checks["silver_write"] = f"fail: {detail}"
            failures.append(
                f"silver_write failed — {detail}"
            )
            logger.warning("BlobCRUDCheck silver_write failed: %s", exc, exc_info=True)

        # ------------------------------------------------------------------ #
        # Silver READ (only attempt if write succeeded — blob must exist)
        # ------------------------------------------------------------------ #
        if sub_checks.get("silver_write") == "pass":
            try:
                data = silver_repo.read_blob(silver_container, _CANARY_BLOB)
                if data == _CANARY_CONTENT:
                    sub_checks["silver_read"] = "pass"
                else:
                    sub_checks["silver_read"] = (
                        f"fail: content mismatch (got {len(data)} bytes, "
                        f"expected {len(_CANARY_CONTENT)})"
                    )
                    failures.append("silver_read failed — content mismatch")
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                sub_checks["silver_read"] = f"fail: {detail}"
                failures.append(f"silver_read failed — {detail}")
                logger.warning("BlobCRUDCheck silver_read failed: %s", exc, exc_info=True)
        else:
            sub_checks["silver_read"] = "skip: write failed"

        # ------------------------------------------------------------------ #
        # Silver DELETE (attempt even if read failed — clean up canary blob)
        # ------------------------------------------------------------------ #
        if sub_checks.get("silver_write") == "pass":
            try:
                silver_repo.delete_blob(silver_container, _CANARY_BLOB)
                sub_checks["silver_delete"] = "pass"
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                sub_checks["silver_delete"] = f"fail: {detail}"
                failures.append(f"silver_delete failed — {detail}")
                logger.warning("BlobCRUDCheck silver_delete failed: %s", exc, exc_info=True)
        else:
            sub_checks["silver_delete"] = "skip: write failed"

        # ------------------------------------------------------------------ #
        # Bronze READ (LIST with limit=1)
        # ------------------------------------------------------------------ #
        try:
            bronze_repo = BlobRepository.for_zone("bronze")
            bronze_repo.list_blobs(bronze_container, prefix="", limit=1)
            sub_checks["bronze_read"] = "pass"
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            sub_checks["bronze_read"] = f"fail: {detail}"
            failures.append(f"bronze_read failed — {detail}")
            logger.warning("BlobCRUDCheck bronze_read failed: %s", exc, exc_info=True)

        # ------------------------------------------------------------------ #
        # Determine overall result
        # ------------------------------------------------------------------ #
        if not failures:
            return PreflightResult.passed(
                "Blob CRUD canary passed: silver write/read/delete + bronze list",
                sub_checks=sub_checks,
            )

        # Build a per-failure remediation for the first actionable failure
        remediation = _build_remediation(failures, silver_account, bronze_account)

        return PreflightResult.failed(
            f"Blob CRUD canary failed ({len(failures)} operation(s)): "
            + "; ".join(failures),
            remediation=remediation,
            sub_checks=sub_checks,
        )


def _build_remediation(
    failures: list[str],
    silver_account: str,
    bronze_account: str,
) -> Remediation:
    """Return the most actionable remediation for the first blob failure."""

    first = failures[0]

    if first.startswith("silver_write") or first.startswith("silver_delete"):
        return Remediation(
            action=(
                f"Assign managed identity 'Storage Blob Data Contributor' role "
                f"on Silver storage account '{silver_account}'"
            ),
            azure_role="Storage Blob Data Contributor",
            scope=f"Silver storage account: {silver_account}",
            eservice_summary=(
                f"AZURE RBAC: App managed identity lacks write access to Silver storage "
                f"account '{silver_account}'. Assign 'Storage Blob Data Contributor' role."
            ),
        )

    if first.startswith("bronze_read"):
        return Remediation(
            action=(
                f"Assign managed identity 'Storage Blob Data Reader' role "
                f"on Bronze storage account '{bronze_account}'"
            ),
            azure_role="Storage Blob Data Reader",
            scope=f"Bronze storage account: {bronze_account}",
            eservice_summary=(
                f"AZURE RBAC: App managed identity lacks read access to Bronze storage "
                f"account '{bronze_account}'. Assign 'Storage Blob Data Reader' role."
            ),
        )

    # Fallback for silver_read or any unexpected failure
    return Remediation(
        action=(
            "Check managed identity RBAC assignments on Silver and Bronze storage accounts"
        ),
        azure_role="Storage Blob Data Contributor",
        eservice_summary=(
            "AZURE RBAC: Blob storage operation failed. "
            "Verify managed identity has 'Storage Blob Data Contributor' on Silver "
            f"('{silver_account}') and 'Storage Blob Data Reader' on Bronze "
            f"('{bronze_account}')."
        ),
    )
