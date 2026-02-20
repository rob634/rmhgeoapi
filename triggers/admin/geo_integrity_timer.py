# ============================================================================
# GEO INTEGRITY TIMER HANDLER
# ============================================================================
# STATUS: Trigger layer - Timer trigger handler for geo schema integrity checks
# PURPOSE: Detect improperly configured geo tables (untyped geometry, missing SRID)
# CREATED: 14 JAN 2026
# SCHEDULE: Every 6 hours (offset from geo_orphan by 2 hours)
# DESIGN: First principle - we detect and warn, tables must be deleted manually
# ============================================================================
"""
Geo Integrity Timer Handler.

Timer trigger handler for detecting improperly configured tables in the geo schema
that won't work with TiPG/OGC Features API.

Detects:
1. Untyped geometry columns (GEOMETRY without subtype like POLYGON)
2. Missing SRID (srid = 0 or NULL)
3. Missing spatial indexes
4. Tables not registered in geometry_columns view

Detection only - does NOT auto-delete. Logs findings to Application Insights.

Why this matters:
- TiPG requires typed geometries to serve vector tiles
- OGC Features API needs SRID for CRS declarations
- Missing spatial indexes cause slow queries

Usage:
    # In function_app.py:
    from triggers.admin.geo_integrity_timer import geo_integrity_timer_handler

    @app.timer_trigger(schedule="0 0 2,8,14,20 * * *", ...)
    def geo_integrity_check_timer(timer: func.TimerRequest) -> None:
        geo_integrity_timer_handler.handle(timer)

Exports:
    GeoIntegrityTimerHandler: Handler class
    geo_integrity_timer_handler: Singleton instance
"""

from typing import Dict, Any

from triggers.timer_base import TimerHandlerBase


class GeoIntegrityTimerHandler(TimerHandlerBase):
    """
    Timer handler for geo schema integrity validation.

    Wraps GeoSchemaValidator from core.diagnostics with standard
    timer handling patterns.
    """

    name = "GeoIntegrityCheck"

    def execute(self) -> Dict[str, Any]:
        """
        Execute geo schema integrity validation.

        Returns:
            Result dict with validation report
        """
        from infrastructure import RepositoryFactory, PostgreSQLRepository
        from core.diagnostics import GeoSchemaValidator

        try:
            repos = RepositoryFactory.create_repositories()
            db_repo = repos['job_repo']

            if not isinstance(db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with db_repo._get_connection() as conn:
                validator = GeoSchemaValidator(conn, schema='geo')
                report = validator.validate_all(include_row_counts=False)

            # Determine health status based on findings
            tipg_incompatible = report.get('tipg_incompatible', 0)
            invalid_count = report.get('invalid_tables', 0)

            if tipg_incompatible > 0:
                health_status = "DEGRADED"
                self.logger.warning(
                    f"⚠️ Found {tipg_incompatible} tables incompatible with TiPG"
                )
            elif invalid_count > 0:
                health_status = "WARNING"
                self.logger.warning(
                    f"⚠️ Found {invalid_count} tables with minor issues"
                )
            else:
                health_status = "HEALTHY"
                self.logger.info(
                    f"✅ All {report.get('total_tables', 0)} geo tables are valid"
                )

            # Log specific issues
            for table_info in report.get('issues_found', [])[:10]:
                self.logger.warning(
                    f"   ❌ {table_info['full_name']}: {table_info['issues']}"
                )

            if len(report.get('issues_found', [])) > 10:
                self.logger.warning(
                    f"   ... and {len(report['issues_found']) - 10} more tables with issues"
                )

            # Log TiPG-specific incompatibilities (critical)
            tipg_issues = [
                t for t in report.get('tables', [])
                if not t.get('is_tipg_compatible')
            ]
            if tipg_issues:
                self.logger.error(
                    f"🚨 CRITICAL: {len(tipg_issues)} tables CANNOT be served by TiPG:"
                )
                for t in tipg_issues[:5]:
                    self.logger.error(
                        f"   DELETE CANDIDATE: {t['full_name']} "
                        f"(type={t.get('geometry_type')}, srid={t.get('srid')}, issues={t.get('issues')})"
                    )

            # TiPG sync check results
            tipg_sync = report.get('tipg_sync', {})
            missing_from_tipg = tipg_sync.get('missing_from_tipg', [])

            if missing_from_tipg:
                self.logger.warning(
                    f"🚨 {len(missing_from_tipg)} tables in geo schema but NOT served by TiPG:"
                )
                for table in missing_from_tipg[:5]:
                    self.logger.warning(f"   - geo.{table}")
                if len(missing_from_tipg) > 5:
                    self.logger.warning(f"   ... and {len(missing_from_tipg) - 5} more")

                # Escalate to DEGRADED if tables are missing from TiPG
                if health_status == "HEALTHY":
                    health_status = "WARNING"

            return {
                "success": True,
                "health_status": health_status,
                "total_tables": report.get('total_tables', 0),
                "valid_tables": report.get('valid_tables', 0),
                "invalid_tables": invalid_count,
                "tipg_compatible": report.get('tipg_compatible', 0),
                "tipg_incompatible": tipg_incompatible,
                "tipg_sync": {
                    "in_sync": tipg_sync.get('in_sync'),
                    "missing_from_tipg": missing_from_tipg,
                    "geo_tables_count": tipg_sync.get('geo_tables_count', 0),
                    "tipg_collections_count": tipg_sync.get('tipg_collections_count', 0)
                },
                "summary": report.get('summary', {}),
                "delete_candidates": [
                    t['full_name'] for t in tipg_issues
                ]
            }

        except Exception as e:
            self.logger.error(f"❌ Geo integrity check failed: {e}")
            return {
                "success": False,
                "health_status": "ERROR",
                "error": str(e),
                "total_tables": 0,
                "invalid_tables": 0
            }


# Singleton instance
geo_integrity_timer_handler = GeoIntegrityTimerHandler()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ['GeoIntegrityTimerHandler', 'geo_integrity_timer_handler']
