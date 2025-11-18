# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - STAC metadata extraction from rasters
# PURPOSE: Extract STAC metadata from raster blobs and insert into PgSTAC
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: handle_request (function-based trigger)
# INTERFACES: Direct Azure Functions HttpTrigger (func.HttpRequest -> func.HttpResponse)
# PYDANTIC_MODELS: None (uses dict for request/response)
# DEPENDENCIES: azure.functions, services.service_stac_metadata.StacMetadataService (lazy import)
# SOURCE: HTTP POST requests to /api/stac/extract with container/blob parameters
# SCOPE: STAC metadata extraction from COG/GeoTIFF files in blob storage
# VALIDATION: Container name, blob name, collection ID validation
# PATTERNS: Function-based trigger, Lazy loading (GDAL/rasterio imported inside function), Service delegation
# ENTRY_POINTS: POST /api/stac/extract
# INDEX: handle_request:21
# ============================================================================

"""
STAC Metadata Extraction Trigger

HTTP endpoint to extract STAC metadata from raster blobs and insert into PgSTAC.

**IMPORTANT**: Uses lazy loading for GDAL/rasterio to prevent cold start delays.
Heavy dependencies are imported inside handle_request(), not at module level.

Author: Robert and Geospatial Claude Legion
Date: 5 OCT 2025
Last Updated: 29 OCT 2025
"""

import azure.functions as func
from typing import Dict, Any
import json
import logging

# LAZY LOADING: Import heavy dependencies INSIDE function, not at module level
# This prevents GDAL/rasterio from loading during Azure Functions cold start

logger = logging.getLogger(__name__)


def handle_request(req: func.HttpRequest) -> func.HttpResponse:
    """
    Extract STAC metadata from raster blob and insert into PgSTAC.

    POST /api/stac/extract

    Body:
    {
        "container": "rmhazuregeobronze",      // Required (use config.storage.bronze.get_container('rasters'))
        "blob_name": "test/file.tif",          // Required
        "collection_id": "dev",                // Optional (default: "dev")
        "insert": true                         // Optional (default: true) - insert into PgSTAC
    }

    Returns:
        STAC Item metadata and insertion result
    """
    import traceback

    # STEP 1: Import StacMetadataService
    try:
        logger.info("🔄 STEP 1: Starting StacMetadataService import (may load rasterio/GDAL)...")
        logger.debug("   → This import chain: services.service_stac_metadata → rio_stac → rasterio → GDAL")
        from services.service_stac_metadata import StacMetadataService
        logger.info("✅ STEP 1: StacMetadataService imported successfully")
    except ImportError as e:
        logger.error(f"❌ STEP 1 FAILED: ImportError importing StacMetadataService")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Failed to import StacMetadataService: {str(e)}',
                'error_type': 'ImportError',
                'step': 'STEP 1: Import StacMetadataService'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )
    except Exception as e:
        logger.error(f"❌ STEP 1 FAILED: Unexpected error importing StacMetadataService")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'step': 'STEP 1: Import StacMetadataService'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )

    # STEP 2: Import StacInfrastructure
    try:
        logger.info("🔄 STEP 2: Starting StacInfrastructure import...")
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        logger.info("✅ STEP 2: StacInfrastructure imported successfully")
    except ImportError as e:
        logger.error(f"❌ STEP 2 FAILED: ImportError importing StacInfrastructure")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Failed to import StacInfrastructure: {str(e)}',
                'error_type': 'ImportError',
                'step': 'STEP 2: Import StacInfrastructure'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )
    except Exception as e:
        logger.error(f"❌ STEP 2 FAILED: Unexpected error importing StacInfrastructure")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'step': 'STEP 2: Import StacInfrastructure'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )

    # STEP 3: Parse request body
    try:
        logger.info("🔄 STEP 3: Parsing request body...")
        body = req.get_json()
        logger.debug(f"   Request body keys: {list(body.keys())}")
        container = body.get('container')
        blob_name = body.get('blob_name')
        collection_id = body.get('collection_id', 'dev')
        should_insert = body.get('insert', True)
        logger.info(f"✅ STEP 3: Request parsed - container={container}, blob={blob_name}, collection={collection_id}")
    except Exception as e:
        logger.error(f"❌ STEP 3 FAILED: Error parsing request body")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Failed to parse request body: {str(e)}',
                'error_type': type(e).__name__,
                'step': 'STEP 3: Parse request'
            }, indent=2),
            mimetype="application/json",
            status_code=400
        )

    # STEP 4: Validate required fields
    if not container:
        logger.warning("❌ STEP 4 FAILED: Missing required parameter: container")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': 'Missing required parameter: container',
                'step': 'STEP 4: Validate parameters'
            }, indent=2),
            mimetype="application/json",
            status_code=400
        )

    if not blob_name:
        logger.warning("❌ STEP 4 FAILED: Missing required parameter: blob_name")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': 'Missing required parameter: blob_name',
                'step': 'STEP 4: Validate parameters'
            }, indent=2),
            mimetype="application/json",
            status_code=400
        )

    logger.info(f"✅ STEP 4: Parameters validated")
    logger.info(f"📋 STAC extraction request: {container}/{blob_name} → {collection_id}")

    # STEP 5: Create StacMetadataService instance
    try:
        logger.info("🔄 STEP 5: Creating StacMetadataService instance...")
        stac_service = StacMetadataService()
        logger.info("✅ STEP 5: StacMetadataService instance created")
    except Exception as e:
        logger.error(f"❌ STEP 5 FAILED: Error creating StacMetadataService instance")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Failed to create StacMetadataService: {str(e)}',
                'error_type': type(e).__name__,
                'step': 'STEP 5: Create service instance'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )

    # STEP 6: Extract STAC metadata (calls rasterio operations)
    try:
        logger.info("🔄 STEP 6: Calling extract_item_from_blob() - Will open raster and extract metadata...")
        logger.debug(f"   Parameters: container={container}, blob_name={blob_name}, collection_id={collection_id}")
        item = stac_service.extract_item_from_blob(
            container=container,
            blob_name=blob_name,
            collection_id=collection_id
        )
        logger.info(f"✅ STEP 6: extract_item_from_blob() completed - Item ID: {item.id}")
    except ValueError as e:
        logger.error(f"❌ STEP 6 FAILED: ValueError during STAC extraction")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e),
                'error_type': 'ValidationError',
                'step': 'STEP 6: Extract STAC metadata'
            }, indent=2),
            mimetype="application/json",
            status_code=400
        )
    except Exception as e:
        logger.error(f"❌ STEP 6 FAILED: Unexpected error during STAC extraction")
        logger.error(f"   Error: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'step': 'STEP 6: Extract STAC metadata'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )

    # STEP 7: Convert to dict for response
    try:
        logger.info("🔄 STEP 7: Converting STAC Item to dict...")
        item_dict = item.model_dump(mode='json', by_alias=True)
        logger.info(f"✅ STEP 7: Item converted to dict - {len(item_dict)} top-level keys")
    except Exception as e:
        logger.error(f"❌ STEP 7 FAILED: Error converting Item to dict")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Failed to convert Item to dict: {str(e)}',
                'error_type': type(e).__name__,
                'step': 'STEP 7: Convert to dict'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )

    # STEP 8: Optionally insert into PgSTAC
    insert_result = None
    if should_insert:
        try:
            logger.info("🔄 STEP 8: Inserting STAC Item into PgSTAC...")
            stac = PgStacBootstrap()
            insert_result = stac.insert_item(item, collection_id)
            logger.info(f"✅ STEP 8: Item inserted into PgSTAC - Result: {insert_result}")
        except Exception as e:
            logger.error(f"❌ STEP 8 FAILED: Error inserting into PgSTAC")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            return func.HttpResponse(
                json.dumps({
                    'success': False,
                    'error': f'Failed to insert into PgSTAC: {str(e)}',
                    'error_type': type(e).__name__,
                    'step': 'STEP 8: Insert into PgSTAC'
                }, indent=2),
                mimetype="application/json",
                status_code=500
            )
    else:
        logger.info("⏭️  STEP 8: Skipping PgSTAC insertion (insert=false)")

    # STEP 9: Build response
    try:
        logger.info("🔄 STEP 9: Building final response...")
        response = {
            'success': True,
            'item': item_dict,
            'item_id': item.id,
            'collection': collection_id,
            'inserted': should_insert,
            'insert_result': insert_result
        }
        logger.info("✅ STEP 9: Response built successfully")
    except Exception as e:
        logger.error(f"❌ STEP 9 FAILED: Error building response")
        logger.error(f"   Error: {e}")
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': f'Failed to build response: {str(e)}',
                'error_type': type(e).__name__,
                'step': 'STEP 9: Build response'
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )

    logger.info(f"✅ STAC EXTRACTION COMPLETE: {item.id}")

    return func.HttpResponse(
        json.dumps(response, indent=2, default=str),
        mimetype="application/json",
        status_code=200
    )


# Create trigger instance
stac_extract_trigger = type('StacExtractTrigger', (), {'handle_request': staticmethod(handle_request)})()
