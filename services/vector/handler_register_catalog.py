# ============================================================================
# CLAUDE CONTEXT - VECTOR REGISTER CATALOG ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Register vector table(s) in geo.table_catalog
# PURPOSE: Standalone DAG node wrapping VectorToPostGISHandler.register_table_metadata()
# LAST_REVIEWED: 19 MAR 2026
# EXPORTS: vector_register_catalog
# DEPENDENCIES: services.vector.postgis_handler, services.vector.core
# ============================================================================
"""
Vector Register Catalog - atomic handler for DAG workflows.

Registers one or more PostGIS tables in geo.table_catalog and
app.vector_etl_tracking. Called after tables are created and loaded.

In the monolith, catalog registration happens inside _create_table_and_metadata().
As an atomic node, it receives table metadata from the create_and_load_tables
predecessor and writes catalog entries independently.

Extracted from: handler_vector_docker_complete._create_table_and_metadata() (line 605)
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def vector_register_catalog(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Register vector table(s) in the catalog.

    Params:
        table_name: Base table name
        schema_name: PostGIS schema (default: "geo")
        tables_info: List of table result dicts from create_and_load_tables, each with:
            - table_name, geometry_type, total_rows, srid
        job_id: ETL job ID for traceability
        blob_name: Source file path
        file_extension: Source format
        original_crs: CRS before reprojection
        title: Optional display name
        description: Optional dataset description
        attribution: Optional data source attribution
        license: Optional SPDX license identifier
        keywords: Optional comma-separated tags
        temporal_property: Optional column name for temporal extent

    Returns:
        {"success": True, "result": {tables_registered, catalog_entries}}
    """
    table_name = params.get('table_name')
    schema_name = params.get('schema_name', 'geo')
    tables_info = params.get('tables_info', [])
    job_id = params.get('job_id', params.get('_run_id', 'unknown'))

    if not table_name:
        return {"success": False, "error": "table_name is required"}
    if not tables_info:
        return {"success": False, "error": "tables_info is required (list of table results)"}

    try:
        from config import get_config
        from services.vector.postgis_handler import VectorToPostGISHandler

        config = get_config()
        handler = VectorToPostGISHandler()
        registered = []

        for table_info in tables_info:
            t_name = table_info['table_name']
            geometry_type = table_info.get('geometry_type', 'unknown')
            total_rows = table_info.get('total_rows', 0)
            srid = table_info.get('srid', 4326)

            # Generate vector tile URLs
            vector_tile_urls = config.generate_vector_tile_urls(t_name, schema_name)

            custom_props = {
                "vector_tiles": {
                    "tilejson_url": vector_tile_urls.get("tilejson"),
                    "tiles_url": vector_tile_urls.get("tiles"),
                    "viewer_url": vector_tile_urls.get("viewer"),
                    "tipg_map_url": vector_tile_urls.get("tipg_map"),
                },
                "tipg_collection_id": f"{schema_name}.{t_name}",
            }

            handler.register_table_metadata(
                table_name=t_name,
                schema=schema_name,
                etl_job_id=job_id,
                source_file=params.get('blob_name'),
                source_format=params.get('file_extension'),
                source_crs=params.get('original_crs'),
                feature_count=total_rows,
                geometry_type=geometry_type,
                bbox=tuple(table_info.get('bbox', [0, 0, 0, 0])),
                title=params.get('title'),
                description=params.get('description'),
                attribution=params.get('attribution'),
                license=params.get('license'),
                keywords=params.get('keywords'),
                temporal_property=params.get('temporal_property'),
                custom_properties=custom_props,
            )

            # Create OGC default style (non-fatal)
            style_created = False
            try:
                from ogc_styles.service import OGCStylesService
                collection_id = f"{schema_name}.{t_name}"
                OGCStylesService().create_default_style(
                    collection_id=collection_id,
                    geometry_type=geometry_type.upper(),
                )
                style_created = True
                logger.info(f"Created default OGC style for {collection_id}")
            except Exception as style_err:
                logger.warning(f"OGC style creation failed for {schema_name}.{t_name} (non-fatal): {style_err}")

            registered.append({
                "table_name": t_name,
                "geometry_type": geometry_type,
                "feature_count": total_rows,
                "vector_tile_urls": vector_tile_urls,
                "style_created": style_created,
            })

            logger.info(f"Registered catalog entry for {schema_name}.{t_name} ({geometry_type}, {total_rows} rows)")

        # --------------------------------------------------------------
        # Update release with table entries and processing status
        # --------------------------------------------------------------
        release_id = params.get('release_id')
        if release_id:
            try:
                from infrastructure.release_repository import ReleaseRepository
                from core.models.asset import ProcessingStatus
                from datetime import datetime, timezone

                release_repo = ReleaseRepository()

                # Write release_tables junction entries
                try:
                    from infrastructure.release_table_repository import ReleaseTableRepository
                    release_table_repo = ReleaseTableRepository()
                    for entry in registered:
                        release_table_repo.create(
                            release_id=release_id,
                            table_name=entry["table_name"],
                            geometry_type=entry["geometry_type"],
                            feature_count=entry.get("feature_count", 0),
                            table_role="primary" if len(registered) == 1 else "geometry_split",
                        )
                except ImportError:
                    logger.debug("ReleaseTableRepository not available - skipping junction entries")
                except Exception as rt_err:
                    logger.warning("Failed to write release_tables for %s: %s", release_id[:16], rt_err)

                release_repo.update_processing_status(
                    release_id,
                    ProcessingStatus.COMPLETED,
                    completed_at=datetime.now(timezone.utc),
                )
                logger.info("Updated release %s with %d vector table entries", release_id[:16], len(registered))
            except Exception as rel_err:
                logger.warning("Failed to update release %s: %s (non-fatal)", release_id[:16], rel_err)

        return {
            "success": True,
            "result": {
                "tables_registered": len(registered),
                "catalog_entries": registered,
            },
        }

    except Exception as e:
        logger.error(f"vector_register_catalog failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
