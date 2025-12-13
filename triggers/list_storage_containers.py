"""
List Storage Containers - Sync endpoint to list containers across all zones.

Route: GET /api/storage/containers

Parameters:
    - zone (optional): Filter to specific zone (bronze, silver, silverext, gold)
    - prefix (optional): Container name prefix filter

Returns containers grouped by zone with storage account info.

Example Usage:
    # List all containers across all zones
    curl https://rmhazuregeoapi-.../api/storage/containers

    # Filter to bronze zone only
    curl "https://rmhazuregeoapi-.../api/storage/containers?zone=bronze"

    # Filter by container name prefix
    curl "https://rmhazuregeoapi-.../api/storage/containers?prefix=silver-"
"""

import json
from datetime import datetime, timezone

import azure.functions as func

from config import get_config
from config.defaults import StorageDefaults
from infrastructure.blob import BlobRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "list_storage_containers")

VALID_ZONES = ["bronze", "silver", "silverext", "gold"]


def _get_configured_zones() -> list:
    """
    Get list of zones that have valid storage accounts configured.

    Zones with placeholder account names (fail-fast defaults) are skipped
    to prevent hanging on non-existent storage accounts.
    """
    config = get_config()
    configured = []

    for zone in VALID_ZONES:
        try:
            zone_config = config.storage.get_account(zone)
            # Skip zones with placeholder account name (not configured)
            if zone_config.account_name != StorageDefaults.DEFAULT_ACCOUNT_NAME:
                configured.append(zone)
            else:
                logger.debug(f"Zone {zone} has placeholder account name, skipping")
        except Exception as e:
            logger.debug(f"Zone {zone} not configured: {e}")

    return configured


def list_storage_containers_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    List containers across all storage zones.

    Args:
        req: HTTP request with optional zone and prefix query params

    Returns:
        JSON response with containers grouped by zone
    """
    start_time = datetime.now(timezone.utc)

    zone_filter = req.params.get("zone")
    prefix = req.params.get("prefix")

    # Get zones that are actually configured
    configured_zones = _get_configured_zones()

    # Validate zone if provided
    if zone_filter and zone_filter not in VALID_ZONES:
        return func.HttpResponse(
            json.dumps({
                "error": f"Invalid zone '{zone_filter}'",
                "valid_zones": VALID_ZONES,
                "configured_zones": configured_zones,
                "hint": "Use ?zone=bronze, ?zone=silver, etc."
            }, indent=2),
            status_code=400,
            mimetype="application/json"
        )

    # Determine which zones to query (only configured zones unless specific zone requested)
    if zone_filter:
        zones_to_query = [zone_filter] if zone_filter in configured_zones else []
        if not zones_to_query:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Zone '{zone_filter}' is not configured",
                    "configured_zones": configured_zones,
                    "hint": f"Available zones: {', '.join(configured_zones)}"
                }, indent=2),
                status_code=400,
                mimetype="application/json"
            )
    else:
        zones_to_query = configured_zones

    result = {
        "zones": {},
        "total_containers": 0,
        "query_params": {
            "zone_filter": zone_filter,
            "prefix_filter": prefix
        }
    }

    for zone in zones_to_query:
        try:
            repo = BlobRepository.for_zone(zone)
            containers = repo.list_containers(prefix=prefix)

            result["zones"][zone] = {
                "account": repo.account_name,
                "containers": [c["name"] for c in containers],
                "container_count": len(containers)
            }
            result["total_containers"] += len(containers)

            logger.debug(f"Zone {zone}: found {len(containers)} containers in account {repo.account_name}")

        except Exception as e:
            logger.warning(f"Failed to list containers for zone {zone}: {e}")
            result["zones"][zone] = {
                "error": str(e),
                "containers": [],
                "container_count": 0
            }

    # Add timing info
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    result["query_time_seconds"] = round(duration, 3)

    logger.info(f"Listed {result['total_containers']} containers across {len(zones_to_query)} zones in {duration:.3f}s")

    return func.HttpResponse(
        json.dumps(result, indent=2),
        status_code=200,
        mimetype="application/json"
    )
