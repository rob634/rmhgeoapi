# ============================================================================
# METADATA CONSISTENCY TIMER HANDLER
# ============================================================================
# STATUS: Trigger layer - Timer trigger handler for metadata consistency checks
# PURPOSE: Unified metadata validation across vector, raster, STAC, DDH refs
# CREATED: 09 JAN 2026
# SCHEDULE: Every 6 hours (offset from geo_orphan by 3 hours)
# EPIC: E7 Pipeline Infrastructure → F7.10 Metadata Consistency
# ============================================================================
"""
Metadata Consistency Timer Handler.

Timer trigger handler for Tier 1 metadata consistency validation.
Uses TimerHandlerBase for consistent logging and error handling.

Checks performed:
- STAC ↔ Metadata cross-reference (vector and raster)
- Broken backlinks (metadata → STAC)
- Dataset refs FK integrity
- Raster blob existence (HEAD only)

Detection only - does NOT auto-delete. Logs findings to Application Insights.

Usage:
    # In function_app.py:
    from triggers.admin.metadata_consistency_timer import metadata_consistency_timer_handler

    @app.timer_trigger(schedule="0 0 3,9,15,21 * * *", ...)
    def metadata_consistency_timer(timer: func.TimerRequest) -> None:
        metadata_consistency_timer_handler.handle(timer)

Exports:
    MetadataConsistencyTimerHandler: Handler class
    metadata_consistency_timer_handler: Singleton instance
"""

from typing import Dict, Any

from triggers.timer_base import TimerHandlerBase


class MetadataConsistencyTimerHandler(TimerHandlerBase):
    """
    Timer handler for metadata consistency checks.

    Wraps MetadataConsistencyChecker with standard timer handling patterns.
    """

    name = "MetadataConsistency"

    def execute(self) -> Dict[str, Any]:
        """
        Execute metadata consistency checks.

        Returns:
            Result dict from MetadataConsistencyChecker.run()
        """
        from services.metadata_consistency import get_metadata_consistency_checker

        checker = get_metadata_consistency_checker()
        result = checker.run()

        # Log issue details at warning level for visibility
        if result.get("issues"):
            for issue in result["issues"][:10]:  # Limit to first 10
                self.logger.warning(
                    f"⚠️ {issue.get('type')}: {issue.get('message')} "
                    f"[{issue.get('stac_item_id') or issue.get('cog_id') or issue.get('table_name') or issue.get('dataset_id')}]"
                )
            if len(result["issues"]) > 10:
                self.logger.warning(
                    f"⚠️ ... and {len(result['issues']) - 10} more issues"
                )

        return result


# Singleton instance
metadata_consistency_timer_handler = MetadataConsistencyTimerHandler()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ['MetadataConsistencyTimerHandler', 'metadata_consistency_timer_handler']
