# ============================================================================
# CLAUDE CONTEXT - INGEST SERVICE MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Module - Collection Ingest Handlers
# PURPOSE: Handlers for ingesting pre-processed COG collections
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: ALL_HANDLERS
# DEPENDENCIES: infrastructure.blob, infrastructure.pgstac_repository
# ============================================================================
"""
Ingest Service Module.

Provides task handlers for ingesting pre-processed COG collections from
bronze to silver storage with pgSTAC registration.

Handlers:
    ingest_inventory: Parse collection.json, create batch plan
    ingest_copy_batch: Copy batch of COG files to silver
    ingest_register_collection: Register collection in pgSTAC
    ingest_register_items: Register batch of items in pgSTAC
    ingest_finalize: Create source_catalog entry, finalize

Usage:
    from services.ingest import ALL_HANDLERS as INGEST_HANDLERS
    ALL_HANDLERS.update(INGEST_HANDLERS)
"""

from typing import Dict, Callable

# Import handlers
from .handler_inventory import ingest_inventory
from .handler_copy import ingest_copy_batch
from .handler_register import (
    ingest_register_collection,
    ingest_register_items,
    ingest_finalize
)

# Handler registry for this module
ALL_HANDLERS: Dict[str, Callable] = {
    "ingest_inventory": ingest_inventory,
    "ingest_copy_batch": ingest_copy_batch,
    "ingest_register_collection": ingest_register_collection,
    "ingest_register_items": ingest_register_items,
    "ingest_finalize": ingest_finalize,
}

__all__ = [
    'ALL_HANDLERS',
]
