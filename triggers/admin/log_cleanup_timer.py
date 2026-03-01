# ============================================================================
# LOG CLEANUP TIMER HANDLER
# ============================================================================
# STATUS: Trigger layer - Timer trigger handler for JSONL log cleanup
# PURPOSE: Periodic cleanup of old JSONL log files from Azure Blob Storage
# CREATED: 11 JAN 2026
# SCHEDULE: Daily at 3 AM UTC
# EPIC: E7 Pipeline Infrastructure - F7.12.F JSONL Log Dump System
# ============================================================================
"""
Log Cleanup Timer Handler.

Timer trigger handler for cleaning up old JSONL log files exported by
the observability system. Uses TimerHandlerBase for consistent logging
and error handling.

Cleanup Rules:
    1. Delete verbose logs older than JSONL_DEBUG_RETENTION_DAYS (default: 7)
    2. Delete default logs older than JSONL_WARNING_RETENTION_DAYS (default: 30)
    3. Delete metrics logs older than JSONL_METRICS_RETENTION_DAYS (default: 14)

Blob Paths Cleaned:
    - applogs/logs/verbose/{date}/...   (debug/verbose logs)
    - applogs/logs/default/{date}/...   (warning+ logs)
    - applogs/service-metrics/{date}/... (service latency metrics)

Environment Variables:
    JSONL_DEBUG_RETENTION_DAYS: Days to keep verbose logs (default: 7)
    JSONL_WARNING_RETENTION_DAYS: Days to keep warning+ logs (default: 30)
    JSONL_METRICS_RETENTION_DAYS: Days to keep metrics logs (default: 14)

Usage:
    # In function_app.py:
    from triggers.admin.log_cleanup_timer import log_cleanup_timer_handler

    @app.timer_trigger(schedule="0 0 3 * * *", ...)  # Daily at 3 AM
    def log_cleanup_timer(timer: func.TimerRequest) -> None:
        log_cleanup_timer_handler.handle(timer)

Exports:
    LogCleanupTimerHandler: Handler class
    log_cleanup_timer_handler: Singleton instance
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from triggers.timer_base import TimerHandlerBase
from infrastructure.blob import BlobRepository


class LogCleanupTimerHandler(TimerHandlerBase):
    """
    Timer handler for JSONL log cleanup.

    Deletes expired log files from blob storage based on retention settings.
    """

    name = "LogCleanup"

    def _get_retention_settings(self) -> Dict[str, int]:
        """
        Get retention settings from config or environment.

        Returns:
            Dict with retention days for each log type
        """
        try:
            from config import get_config
            config = get_config()
            return {
                "verbose": config.observability.debug_retention_days,
                "default": config.observability.warning_retention_days,
                "metrics": config.observability.metrics_retention_days,
            }
        except Exception:
            # Fallback to environment variables or defaults
            return {
                "verbose": int(os.environ.get("JSONL_DEBUG_RETENTION_DAYS", "7")),
                "default": int(os.environ.get("JSONL_WARNING_RETENTION_DAYS", "30")),
                "metrics": int(os.environ.get("JSONL_METRICS_RETENTION_DAYS", "14")),
            }

    def _get_expired_date_prefixes(self, retention_days: int) -> List[str]:
        """
        Get date prefixes for folders older than retention period.

        Args:
            retention_days: Number of days to retain

        Returns:
            List of date strings (YYYY-MM-DD) that are expired
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retention_days)

        # Generate date strings going back far enough
        # We check dates from retention_days+30 back to cutoff
        expired_dates = []
        check_days = retention_days + 30  # Check extra days to catch old data

        for days_ago in range(retention_days, check_days + 1):
            date = now - timedelta(days=days_ago)
            expired_dates.append(date.strftime("%Y-%m-%d"))

        return expired_dates

    def _cleanup_log_folder(
        self,
        container_name: str,
        prefix: str,
        retention_days: int,
        log_type: str
    ) -> Dict[str, int]:
        """
        Clean up expired blobs in a log folder.

        Args:
            container_name: Azure blob container name
            prefix: Blob prefix (e.g., "logs/verbose")
            retention_days: Days to retain
            log_type: Type for logging (e.g., "verbose", "default", "metrics")

        Returns:
            Dict with deleted count and error count
        """
        result = {"deleted": 0, "errors": 0, "checked": 0}

        try:
            blob_repo = BlobRepository.instance()
        except Exception:
            self.logger.warning(f"LogCleanup: No blob repository available for {log_type}")
            return result

        try:
            # Check if container exists
            if not blob_repo.container_exists(container_name):
                self.logger.info(f"LogCleanup: Container {container_name} does not exist")
                return result

            # Get expired date prefixes
            expired_dates = self._get_expired_date_prefixes(retention_days)

            for date_str in expired_dates:
                # Build full prefix for this date
                date_prefix = f"{prefix}/{date_str}/"

                try:
                    # List blobs with this prefix
                    blobs = blob_repo.list_blobs(container_name, prefix=date_prefix)
                    result["checked"] += len(blobs)

                    if blobs:
                        self.logger.debug(
                            f"LogCleanup: Found {len(blobs)} blobs in {date_prefix}"
                        )

                        # Delete each blob
                        for blob in blobs:
                            try:
                                blob_repo.delete_blob(container_name, blob['name'])
                                result["deleted"] += 1
                            except Exception as e:
                                self.logger.warning(
                                    f"LogCleanup: Failed to delete {blob['name']}: {e}"
                                )
                                result["errors"] += 1

                except Exception as e:
                    self.logger.warning(
                        f"LogCleanup: Error listing blobs in {date_prefix}: {e}"
                    )
                    result["errors"] += 1

        except Exception as e:
            self.logger.error(f"LogCleanup: Error cleaning {log_type} logs: {e}")
            result["errors"] += 1

        return result

    def execute(self) -> Dict[str, Any]:
        """
        Execute log cleanup.

        Returns:
            Result dict with cleanup summary.
        """
        retention = self._get_retention_settings()
        container = os.environ.get("JSONL_LOG_CONTAINER", "applogs")

        self.logger.info(
            f"LogCleanup: Starting cleanup with retention - "
            f"verbose: {retention['verbose']}d, "
            f"default: {retention['default']}d, "
            f"metrics: {retention['metrics']}d"
        )

        # Cleanup each log type
        results = {
            "verbose": self._cleanup_log_folder(
                container, "logs/verbose", retention["verbose"], "verbose"
            ),
            "default": self._cleanup_log_folder(
                container, "logs/default", retention["default"], "default"
            ),
            "metrics": self._cleanup_log_folder(
                container, "service-metrics", retention["metrics"], "metrics"
            ),
        }

        # Calculate totals
        total_deleted = sum(r["deleted"] for r in results.values())
        total_errors = sum(r["errors"] for r in results.values())
        total_checked = sum(r["checked"] for r in results.values())

        # Determine health status
        if total_errors > 0:
            health_status = "ISSUES_DETECTED"
        elif total_deleted > 0:
            health_status = "CLEANED"
        else:
            health_status = "HEALTHY"

        self.logger.info(
            f"LogCleanup: Complete - deleted {total_deleted} blobs, "
            f"checked {total_checked}, errors {total_errors}"
        )

        return {
            "success": total_errors == 0 or total_deleted > 0,
            "health_status": health_status,
            "summary": {
                "total_deleted": total_deleted,
                "total_errors": total_errors,
                "total_checked": total_checked,
                "verbose_deleted": results["verbose"]["deleted"],
                "default_deleted": results["default"]["deleted"],
                "metrics_deleted": results["metrics"]["deleted"],
            },
            "retention_days": retention,
            "container": container,
        }


# Singleton instance
log_cleanup_timer_handler = LogCleanupTimerHandler()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ['LogCleanupTimerHandler', 'log_cleanup_timer_handler']
