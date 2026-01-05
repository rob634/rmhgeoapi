# ============================================================================
# STAC VECTOR CATALOGING TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/stac/vector
# PURPOSE: Catalog PostGIS vector tables in STAC
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: handle_request
# DEPENDENCIES: services.service_stac_vector, infrastructure.pgstac_bootstrap
# ============================================================================
"""
STAC Vector Cataloging Trigger.

HTTP endpoint to catalog PostGIS vector tables in STAC.

Exports:
    handle_request: HTTP trigger function for POST /api/stac/vector
"""

import azure.functions as func
from typing import Dict, Any
import json
import logging

from services.service_stac_vector import StacVectorService
from infrastructure.pgstac_bootstrap import PgStacBootstrap
from config.defaults import STACDefaults

logger = logging.getLogger(__name__)


def handle_request(req: func.HttpRequest) -> func.HttpResponse:
    """
    Catalog PostGIS vector table in STAC.

    POST /api/stac/vector

    Body:
    {
        "schema": "geo",                        // Required - PostgreSQL schema
        "table_name": "parcels_2025",           // Required - Table name
        "collection_id": "vectors",             // Optional (default: "vectors")
        "source_file": "data/parcels.gpkg",     // Optional - Original source file
        "insert": true,                         // Optional (default: true) - insert into PgSTAC
        "properties": {                         // Optional - Custom STAC properties
            "jurisdiction": "county",
            "data_source": "tax_assessor"
        }
    }

    Returns:
        STAC Item metadata and insertion result
    """
    try:
        # Parse request
        body = req.get_json()
        schema = body.get('schema')
        table_name = body.get('table_name')
        collection_id = body.get('collection_id', STACDefaults.VECTORS_COLLECTION)
        source_file = body.get('source_file')
        should_insert = body.get('insert', True)
        custom_properties = body.get('properties', {})

        # Validate required fields
        if not schema:
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': 'Missing required parameter: schema'
                }, indent=2),
                mimetype="application/json",
                status_code=400
            )

        if not table_name:
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': 'Missing required parameter: table_name'
                }, indent=2),
                mimetype="application/json",
                status_code=400
            )

        logger.info(f"STAC vector cataloging: {schema}.{table_name} → {collection_id}")

        # Extract STAC metadata from PostGIS table
        stac_service = StacVectorService()
        item = stac_service.extract_item_from_table(
            schema=schema,
            table_name=table_name,
            collection_id=collection_id,
            source_file=source_file,
            additional_properties=custom_properties
        )

        # Convert to dict for response
        item_dict = item.model_dump(mode='json', by_alias=True)

        # Optionally insert into PgSTAC
        insert_result = None
        if should_insert:
            stac = PgStacBootstrap()
            insert_result = stac.insert_item(item, collection_id)

        # Build response
        response = {
            'success': True,
            'item': item_dict,
            'item_id': item.id,
            'collection': collection_id,
            'table': f"{schema}.{table_name}",
            'inserted': should_insert,
            'insert_result': insert_result
        }

        logger.info(f"✅ STAC vector cataloging successful: {item.id}")

        return func.HttpResponse(
            json.dumps(response, indent=2, default=str),
            mimetype="application/json",
            status_code=200
        )

    except ValueError as e:
        # Validation errors (table doesn't exist, invalid data)
        logger.error(f"Validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'ValidationError'
            }, indent=2),
            mimetype="application/json",
            status_code=400
        )

    except Exception as e:
        # Unexpected errors
        logger.error(f"STAC vector cataloging failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )


# Create trigger instance
stac_vector_trigger = type('StacVectorTrigger', (), {'handle_request': staticmethod(handle_request)})()
