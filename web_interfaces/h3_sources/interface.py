# ============================================================================
# CLAUDE CONTEXT - H3 SOURCES WEB INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - H3 Source Catalog CRUD API
# PURPOSE: REST endpoints for managing H3 data source metadata
# LAST_REVIEWED: 27 DEC 2025
# EXPORTS: bp (Blueprint)
# DEPENDENCIES: azure.functions, infrastructure.h3_source_repository
# ============================================================================
"""
H3 Sources Web Interface - REST API for Source Catalog Management.

Provides CRUD endpoints for managing h3.source_catalog entries, which define
data sources for H3 aggregation pipelines.

Endpoints:
    GET  /api/h3/sources              - List all sources (with optional filters)
    GET  /api/h3/sources/{source_id}  - Get a single source
    POST /api/h3/sources              - Register a new source
    PATCH /api/h3/sources/{source_id} - Update a source
    DELETE /api/h3/sources/{source_id} - Deactivate (soft delete) a source
"""

import json
import logging
import traceback
from azure.functions import Blueprint, HttpRequest, HttpResponse

from infrastructure.h3_source_repository import H3SourceRepository

# Logger setup
logger = logging.getLogger(__name__)

# Create Blueprint
bp = Blueprint()


# ============================================================================
# LIST SOURCES
# ============================================================================

@bp.route(route="h3/sources", methods=["GET"])
def list_sources(req: HttpRequest) -> HttpResponse:
    """
    List all H3 data sources.

    Query Parameters:
        theme (str, optional): Filter by theme (terrain, water, climate, etc.)
        source_type (str, optional): Filter by source type (planetary_computer, azure_blob, etc.)
        is_active (bool, optional): Only active sources (default: true)

    Returns:
        200: List of sources
        500: Error response
    """
    try:
        repo = H3SourceRepository()

        # Get query parameters
        theme = req.params.get('theme')
        source_type = req.params.get('source_type')
        is_active_param = req.params.get('is_active', 'true')
        is_active = is_active_param.lower() in ('true', '1', 'yes')

        sources = repo.list_sources(
            theme=theme,
            source_type=source_type,
            is_active=is_active
        )

        # Convert datetime objects to strings for JSON serialization
        for source in sources:
            for key in ['created_at', 'updated_at', 'temporal_extent_start', 'temporal_extent_end']:
                if source.get(key):
                    source[key] = source[key].isoformat()
            # Handle geometry (spatial_extent)
            if source.get('spatial_extent'):
                source['spatial_extent'] = str(source['spatial_extent'])

        return HttpResponse(
            json.dumps({
                "sources": sources,
                "count": len(sources),
                "filters": {
                    "theme": theme,
                    "source_type": source_type,
                    "is_active": is_active
                }
            }),
            status_code=200,
            mimetype="application/json"
        )

    except ValueError as e:
        logger.warning(f"Validation error in list_sources: {e}")
        return HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Error listing sources: {e}\n{traceback.format_exc()}")
        return HttpResponse(
            json.dumps({"error": f"Failed to list sources: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


# ============================================================================
# GET SINGLE SOURCE
# ============================================================================

@bp.route(route="h3/sources/{source_id}", methods=["GET"])
def get_source(req: HttpRequest) -> HttpResponse:
    """
    Get a single H3 data source by ID.

    Path Parameters:
        source_id (str): Source identifier

    Returns:
        200: Source details
        404: Source not found
        500: Error response
    """
    try:
        source_id = req.route_params.get('source_id')
        if not source_id:
            return HttpResponse(
                json.dumps({"error": "source_id is required"}),
                status_code=400,
                mimetype="application/json"
            )

        repo = H3SourceRepository()
        source = repo.get_source(source_id)

        # Convert datetime objects to strings
        for key in ['created_at', 'updated_at', 'temporal_extent_start', 'temporal_extent_end']:
            if source.get(key):
                source[key] = source[key].isoformat()
        # Handle geometry
        if source.get('spatial_extent'):
            source['spatial_extent'] = str(source['spatial_extent'])

        return HttpResponse(
            json.dumps(source),
            status_code=200,
            mimetype="application/json"
        )

    except ValueError as e:
        logger.warning(f"Source not found: {e}")
        return HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=404,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Error getting source: {e}\n{traceback.format_exc()}")
        return HttpResponse(
            json.dumps({"error": f"Failed to get source: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


# ============================================================================
# REGISTER SOURCE
# ============================================================================

@bp.route(route="h3/sources", methods=["POST"])
def register_source(req: HttpRequest) -> HttpResponse:
    """
    Register a new H3 data source.

    Request Body (JSON):
        Required:
            id (str): Unique source identifier
            display_name (str): Human-readable name
            source_type (str): planetary_computer, azure_blob, url, postgis
            theme (str): terrain, water, climate, demographics, etc.

        Optional:
            description, stac_api_url, collection_id, asset_key,
            tile_size_degrees, tile_count, native_resolution_m,
            nodata_value, value_range, recommended_stats, unit,
            source_provider, source_url, source_license, etc.

    Returns:
        201: Created source
        400: Validation error
        500: Error response
    """
    try:
        # Parse request body
        try:
            body = req.get_json()
        except Exception:
            return HttpResponse(
                json.dumps({"error": "Invalid JSON body"}),
                status_code=400,
                mimetype="application/json"
            )

        if not body:
            return HttpResponse(
                json.dumps({"error": "Request body is required"}),
                status_code=400,
                mimetype="application/json"
            )

        repo = H3SourceRepository()
        result = repo.register_source(body)

        return HttpResponse(
            json.dumps({
                "message": "Source registered successfully" if result.get('created') else "Source updated successfully",
                "id": result['id'],
                "theme": result['theme'],
                "created": result.get('created', False),
                "updated_at": result['updated_at'].isoformat() if result.get('updated_at') else None
            }),
            status_code=201 if result.get('created') else 200,
            mimetype="application/json"
        )

    except ValueError as e:
        logger.warning(f"Validation error in register_source: {e}")
        return HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Error registering source: {e}\n{traceback.format_exc()}")
        return HttpResponse(
            json.dumps({"error": f"Failed to register source: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


# ============================================================================
# UPDATE SOURCE
# ============================================================================

@bp.route(route="h3/sources/{source_id}", methods=["PATCH"])
def update_source(req: HttpRequest) -> HttpResponse:
    """
    Update an existing H3 data source.

    Path Parameters:
        source_id (str): Source identifier

    Request Body (JSON):
        Fields to update (any valid source field)

    Returns:
        200: Updated source
        400: Validation error
        404: Source not found
        500: Error response
    """
    try:
        source_id = req.route_params.get('source_id')
        if not source_id:
            return HttpResponse(
                json.dumps({"error": "source_id is required"}),
                status_code=400,
                mimetype="application/json"
            )

        # Parse request body
        try:
            updates = req.get_json()
        except Exception:
            return HttpResponse(
                json.dumps({"error": "Invalid JSON body"}),
                status_code=400,
                mimetype="application/json"
            )

        if not updates:
            return HttpResponse(
                json.dumps({"error": "Request body is required"}),
                status_code=400,
                mimetype="application/json"
            )

        repo = H3SourceRepository()
        result = repo.update_source(source_id, updates)

        return HttpResponse(
            json.dumps({
                "message": "Source updated successfully",
                "id": result['id'],
                "theme": result['theme'],
                "updated_at": result['updated_at'].isoformat() if result.get('updated_at') else None
            }),
            status_code=200,
            mimetype="application/json"
        )

    except ValueError as e:
        logger.warning(f"Error updating source: {e}")
        return HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=404 if "not found" in str(e).lower() else 400,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Error updating source: {e}\n{traceback.format_exc()}")
        return HttpResponse(
            json.dumps({"error": f"Failed to update source: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


# ============================================================================
# DEACTIVATE SOURCE
# ============================================================================

@bp.route(route="h3/sources/{source_id}", methods=["DELETE"])
def deactivate_source(req: HttpRequest) -> HttpResponse:
    """
    Deactivate (soft delete) an H3 data source.

    Path Parameters:
        source_id (str): Source identifier

    Returns:
        200: Source deactivated
        404: Source not found
        500: Error response
    """
    try:
        source_id = req.route_params.get('source_id')
        if not source_id:
            return HttpResponse(
                json.dumps({"error": "source_id is required"}),
                status_code=400,
                mimetype="application/json"
            )

        repo = H3SourceRepository()
        success = repo.deactivate_source(source_id)

        if success:
            return HttpResponse(
                json.dumps({
                    "message": f"Source '{source_id}' deactivated successfully",
                    "id": source_id
                }),
                status_code=200,
                mimetype="application/json"
            )
        else:
            return HttpResponse(
                json.dumps({"error": f"Source not found: {source_id}"}),
                status_code=404,
                mimetype="application/json"
            )

    except Exception as e:
        logger.error(f"Error deactivating source: {e}\n{traceback.format_exc()}")
        return HttpResponse(
            json.dumps({"error": f"Failed to deactivate source: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


# ============================================================================
# H3 CELL STATISTICS
# ============================================================================

@bp.route(route="h3/stats", methods=["GET"])
def get_h3_stats(req: HttpRequest) -> HttpResponse:
    """
    Get H3 cell statistics with optional country filter.

    Query Parameters:
        iso3 (str, optional): Filter by ISO3 country code (e.g., 'RWA', 'GRC')
        resolution (int, optional): Filter by specific resolution (0-15)

    Returns:
        200: Cell counts grouped by resolution and optionally by country
        500: Error response

    Examples:
        GET /api/h3/stats                    - All cells by resolution
        GET /api/h3/stats?iso3=RWA           - Rwanda cells by resolution
        GET /api/h3/stats?iso3=RWA&resolution=6  - Rwanda cells at res 6 only
    """
    try:
        from infrastructure.h3_repository import H3Repository
        from psycopg import sql

        repo = H3Repository()

        # Get query parameters
        iso3 = req.params.get('iso3')
        resolution_str = req.params.get('resolution')
        resolution = int(resolution_str) if resolution_str else None

        # Validate resolution if provided
        if resolution is not None and (resolution < 0 or resolution > 15):
            return HttpResponse(
                json.dumps({"error": "resolution must be between 0 and 15"}),
                status_code=400,
                mimetype="application/json"
            )

        # Build query based on filters (uses repo.schema_name for consistency)
        if iso3:
            # Query with country filter via cell_admin0 join
            if resolution is not None:
                query = sql.SQL("""
                    SELECT
                        ca.iso3,
                        c.resolution,
                        COUNT(*) as cell_count
                    FROM {schema}.cells c
                    JOIN {schema}.cell_admin0 ca ON c.h3_index = ca.h3_index
                    WHERE ca.iso3 = %s AND c.resolution = %s
                    GROUP BY ca.iso3, c.resolution
                    ORDER BY c.resolution
                """).format(schema=sql.Identifier(repo.schema_name))
                params = (iso3.upper(), resolution)
            else:
                query = sql.SQL("""
                    SELECT
                        ca.iso3,
                        c.resolution,
                        COUNT(*) as cell_count
                    FROM {schema}.cells c
                    JOIN {schema}.cell_admin0 ca ON c.h3_index = ca.h3_index
                    WHERE ca.iso3 = %s
                    GROUP BY ca.iso3, c.resolution
                    ORDER BY c.resolution
                """).format(schema=sql.Identifier(repo.schema_name))
                params = (iso3.upper(),)
        else:
            # Query all cells (no country filter)
            if resolution is not None:
                query = sql.SQL("""
                    SELECT
                        c.resolution,
                        COUNT(*) as cell_count
                    FROM {schema}.cells c
                    WHERE c.resolution = %s
                    GROUP BY c.resolution
                    ORDER BY c.resolution
                """).format(schema=sql.Identifier(repo.schema_name))
                params = (resolution,)
            else:
                query = sql.SQL("""
                    SELECT
                        c.resolution,
                        COUNT(*) as cell_count
                    FROM {schema}.cells c
                    GROUP BY c.resolution
                    ORDER BY c.resolution
                """).format(schema=sql.Identifier(repo.schema_name))
                params = ()

        # Execute query
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()

        # Format response
        stats = [dict(row) for row in results]
        total_cells = sum(s.get('cell_count', 0) for s in stats)

        return HttpResponse(
            json.dumps({
                "stats": stats,
                "total_cells": total_cells,
                "filters": {
                    "iso3": iso3.upper() if iso3 else None,
                    "resolution": resolution
                }
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Error getting H3 stats: {e}\n{traceback.format_exc()}")
        return HttpResponse(
            json.dumps({"error": f"Failed to get H3 stats: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )


@bp.route(route="h3/stats/countries", methods=["GET"])
def get_h3_countries(req: HttpRequest) -> HttpResponse:
    """
    List all countries with H3 cells and their total counts.

    Returns:
        200: List of countries with cell counts
        500: Error response
    """
    try:
        from infrastructure.h3_repository import H3Repository
        from psycopg import sql

        repo = H3Repository()

        query = sql.SQL("""
            SELECT
                ca.iso3,
                COUNT(DISTINCT ca.h3_index) as cell_count,
                MIN(c.resolution) as min_resolution,
                MAX(c.resolution) as max_resolution
            FROM {schema}.cell_admin0 ca
            JOIN {schema}.cells c ON ca.h3_index = c.h3_index
            GROUP BY ca.iso3
            ORDER BY ca.iso3
        """).format(schema=sql.Identifier(repo.schema_name))

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                results = cur.fetchall()

        countries = [dict(row) for row in results]
        total_cells = sum(c.get('cell_count', 0) for c in countries)

        return HttpResponse(
            json.dumps({
                "countries": countries,
                "country_count": len(countries),
                "total_cells": total_cells
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Error getting H3 countries: {e}\n{traceback.format_exc()}")
        return HttpResponse(
            json.dumps({"error": f"Failed to get H3 countries: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )
