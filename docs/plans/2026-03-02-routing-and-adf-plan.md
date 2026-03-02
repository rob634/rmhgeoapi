# Routing & ADF Public Data Pipeline — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `geo.b2c_routes` and `geo.b2b_routes` tables so the orchestrator writes versioned route records at approval time, enabling the service layer (rmhtitiler) to resolve friendly slug URLs to concrete data resources.

**Architecture:** Route tables live in the `geo` schema (replicable). The orchestrator writes routes during approve/revoke. ADF replicates `b2c_routes` to the external database for public data. rmhtitiler reads routes — same code, zone-parameterized table. See `rmhtitiler/ROUTING_DESIGN.md` for full design.

**Tech Stack:** Python 3.12, psycopg3, Pydantic V2, PostgreSQL 16 (Azure Flex), existing `_slugify_for_stac()` from `config/platform_config.py`

---

## Task 1: Define `B2CRoute` Pydantic Model

**Files:**
- Modify: `core/models/geo.py` (append after line ~550, after `FeatureCollectionStyles`)
- Modify: `core/models/__init__.py:188-191` (add import)
- Modify: `core/models/__init__.py:339-341` (add to `__all__`)

**Step 1: Add model to `core/models/geo.py`**

Append after the `FeatureCollectionStyles` class (after line ~550):

```python
# ============================================================================
# B2C ROUTES (Public API Routing - 02 MAR 2026)
# ============================================================================

class B2CRoute(BaseModel):
    """
    Public API route mapping — resolves slug + version to data resources.

    External TiTiler reads this table to resolve /assets/{slug}/latest
    to concrete TiTiler/TiPG endpoints. Written by the orchestrator at
    approval time. Replicated to external DB by ADF.

    Maps to: geo.b2c_routes (and geo.b2b_routes — identical schema)

    See: rmhtitiler/ROUTING_DESIGN.md for full design.

    Created: 02 MAR 2026
    Epic: E4 Security Zones / Externalization
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # DDL generation hints
    __sql_table_name: ClassVar[str] = "b2c_routes"
    __sql_schema: ClassVar[str] = "geo"
    __sql_primary_key: ClassVar[List[str]] = ["slug", "version_id"]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["slug"], "name": "idx_b2c_routes_latest", "partial_where": "is_latest = true", "unique": True},
        {"columns": ["slug", "version_ordinal"], "name": "idx_b2c_routes_slug_ordinal"},
        {"columns": ["data_type"], "name": "idx_b2c_routes_data_type"},
    ]

    # Identity
    slug: str = Field(..., max_length=200, description="Flattened slug from dataset_id-resource_id")
    version_id: str = Field(..., max_length=50, description="Version identifier (v1, v2)")

    # Classification
    data_type: str = Field(..., max_length=20, description="raster, vector, or zarr")

    # Version resolution
    is_latest: bool = Field(default=False, description="Only one TRUE per slug")
    version_ordinal: int = Field(..., description="Ordering within slug (1, 2, 3...)")

    # Target resources
    table_name: Optional[str] = Field(default=None, max_length=63, description="Vector: geo.{table_name}")
    stac_item_id: Optional[str] = Field(default=None, max_length=200, description="Raster/zarr: pgstac item")
    stac_collection_id: Optional[str] = Field(default=None, max_length=200, description="STAC collection")
    blob_path: Optional[str] = Field(default=None, max_length=500, description="Direct download path")

    # Display
    title: str = Field(..., max_length=300, description="Display name")
    description: Optional[str] = Field(default=None, description="Short description")

    # Provenance (denormalized — external DB has no app schema)
    asset_id: Optional[str] = Field(default=None, max_length=64)
    release_id: Optional[str] = Field(default=None, max_length=64)
    cleared_by: Optional[str] = Field(default=None, max_length=200)
    cleared_at: Optional[datetime] = Field(default=None)

    # Timestamps
    created_at: Optional[datetime] = Field(default=None)


class B2BRoute(BaseModel):
    """
    Internal API route mapping — identical schema to B2CRoute.

    Internal TiTiler reads this table. All approved releases (OUO + PUBLIC)
    get a b2b_routes entry. Only PUBLIC releases also get a b2c_routes entry.

    Maps to: geo.b2b_routes
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    __sql_table_name: ClassVar[str] = "b2b_routes"
    __sql_schema: ClassVar[str] = "geo"
    __sql_primary_key: ClassVar[List[str]] = ["slug", "version_id"]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["slug"], "name": "idx_b2b_routes_latest", "partial_where": "is_latest = true", "unique": True},
        {"columns": ["slug", "version_ordinal"], "name": "idx_b2b_routes_slug_ordinal"},
        {"columns": ["data_type"], "name": "idx_b2b_routes_data_type"},
    ]

    # All fields identical to B2CRoute
    slug: str = Field(..., max_length=200)
    version_id: str = Field(..., max_length=50)
    data_type: str = Field(..., max_length=20)
    is_latest: bool = Field(default=False)
    version_ordinal: int = Field(...))
    table_name: Optional[str] = Field(default=None, max_length=63)
    stac_item_id: Optional[str] = Field(default=None, max_length=200)
    stac_collection_id: Optional[str] = Field(default=None, max_length=200)
    blob_path: Optional[str] = Field(default=None, max_length=500)
    title: str = Field(..., max_length=300)
    description: Optional[str] = Field(default=None)
    asset_id: Optional[str] = Field(default=None, max_length=64)
    release_id: Optional[str] = Field(default=None, max_length=64)
    cleared_by: Optional[str] = Field(default=None, max_length=200)
    cleared_at: Optional[datetime] = Field(default=None)
    created_at: Optional[datetime] = Field(default=None)
```

**Step 2: Export from `core/models/__init__.py`**

At line 188-191 (geo imports section), add:

```python
from .geo import (
    GeoTableCatalog,
    FeatureCollectionStyles,  # OGC API Styles (22 JAN 2026)
    B2CRoute,                 # Public routing (02 MAR 2026)
    B2BRoute,                 # Internal routing (02 MAR 2026)
)
```

At line 339-341 (`__all__` geo section), add:

```python
'GeoTableCatalog',
'FeatureCollectionStyles',
'B2CRoute',   # Public routing (02 MAR 2026)
'B2BRoute',   # Internal routing (02 MAR 2026)
```

**Step 3: Verify model loads**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from core.models import B2CRoute, B2BRoute; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add core/models/geo.py core/models/__init__.py
git commit -m "feat: add B2CRoute and B2BRoute Pydantic models for geo schema routing"
```

---

## Task 2: Register Routes in SQL Generator

**Files:**
- Modify: `core/schema/sql_generator.py:88` (add import)
- Modify: `core/schema/sql_generator.py:533` (add DDL generation)

**Step 1: Add import at line 88**

In the geo model imports (line 88), add the new models:

```python
from ..models.geo import GeoTableCatalog, FeatureCollectionStyles, B2CRoute, B2BRoute
```

**Step 2: Add DDL generation in `generate_geo_schema_ddl()` after line 533**

After the `FeatureCollectionStyles` block (line 533), add:

```python
        # B2CRoute: Public API routing (02 MAR 2026)
        statements.append(self.generate_table_from_model(B2CRoute))
        statements.extend(self.generate_add_columns_from_model(B2CRoute))
        statements.extend(self.generate_indexes_from_model(B2CRoute))

        # B2BRoute: Internal API routing (02 MAR 2026)
        statements.append(self.generate_table_from_model(B2BRoute))
        statements.extend(self.generate_add_columns_from_model(B2BRoute))
        statements.extend(self.generate_indexes_from_model(B2BRoute))
```

**Step 3: Verify DDL generates**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.schema.sql_generator import PydanticToSQL
gen = PydanticToSQL()
stmts = gen.generate_geo_schema_ddl()
print(f'{len(stmts)} statements generated')
for s in stmts:
    text = s.as_string(None) if hasattr(s, 'as_string') else str(s)
    if 'b2c_routes' in text.lower() or 'b2b_routes' in text.lower():
        print(text[:120])
"`

Expected: Statements containing `b2c_routes` and `b2b_routes` CREATE TABLE and CREATE INDEX.

**Step 4: Commit**

```bash
git add core/schema/sql_generator.py
git commit -m "feat: register B2CRoute and B2BRoute in geo schema DDL generator"
```

---

## Task 3: Create `RouteRepository`

**Files:**
- Create: `infrastructure/route_repository.py`
- Modify: `infrastructure/__init__.py:277-279` (add to `__getattr__`)
- Modify: `infrastructure/__init__.py:95-96` (add TYPE_CHECKING import)
- Modify: `infrastructure/__init__.py:328-329` (add to `__all__`)

**Step 1: Create `infrastructure/route_repository.py`**

```python
# ============================================================================
# CLAUDE CONTEXT - ROUTE REPOSITORY
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Infrastructure - Route table CRUD for geo.b2c_routes / geo.b2b_routes
# PURPOSE: Write/read/delete versioned route records for service layer routing
# LAST_REVIEWED: 02 MAR 2026
# EXPORTS: RouteRepository
# DEPENDENCIES: psycopg, infrastructure.postgresql
# ============================================================================
"""
Route Repository — CRUD for geo.b2c_routes and geo.b2b_routes.

The orchestrator writes routes at approval time. The service layer (rmhtitiler)
reads them. Both tables share the same schema — the table name is parameterized.

Key operations:
    - upsert_route: Insert or update a route record
    - delete_route: Remove a specific slug+version
    - clear_latest: Set is_latest=false for all versions of a slug
    - promote_next_latest: Find and promote the next most recent version

See: rmhtitiler/ROUTING_DESIGN.md for full design.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from .postgresql import PostgreSQLRepository

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "RouteRepository")


class RouteRepository(PostgreSQLRepository):
    """
    Repository for geo.b2c_routes and geo.b2b_routes tables.

    All methods accept a `table` parameter ('b2c_routes' or 'b2b_routes')
    to select which routes table to operate on. Defaults to 'b2c_routes'.
    """

    SCHEMA = "geo"
    VALID_TABLES = ("b2c_routes", "b2b_routes")

    _UPSERT_COLUMNS = (
        "slug", "version_id", "data_type", "is_latest", "version_ordinal",
        "table_name", "stac_item_id", "stac_collection_id", "blob_path",
        "title", "description", "asset_id", "release_id",
        "cleared_by", "cleared_at", "created_at"
    )

    def __init__(self):
        super().__init__()

    def _validate_table(self, table: str) -> str:
        if table not in self.VALID_TABLES:
            raise ValueError(f"Invalid route table: {table}. Must be one of {self.VALID_TABLES}")
        return table

    def upsert_route(self, route: Dict[str, Any], table: str = "b2c_routes") -> bool:
        """
        Insert or update a route record.

        Uses INSERT ON CONFLICT (slug, version_id) DO UPDATE to handle
        both new routes and version re-approvals.

        Args:
            route: Dict with keys matching _UPSERT_COLUMNS
            table: 'b2c_routes' or 'b2b_routes'

        Returns:
            True if upserted successfully
        """
        table = self._validate_table(table)
        logger.info(f"Upserting route: {route['slug']}/{route['version_id']} → {table}")

        cols = ", ".join(self._UPSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(self._UPSERT_COLUMNS))

        # Build SET clause for ON CONFLICT (exclude PK columns)
        update_cols = [c for c in self._UPSERT_COLUMNS if c not in ("slug", "version_id")]
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

        values = tuple(route.get(c) for c in self._UPSERT_COLUMNS)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        f"INSERT INTO {{}}.{{}} ({cols}) VALUES ({placeholders}) "
                        f"ON CONFLICT (slug, version_id) DO UPDATE SET {update_set}"
                    ).format(
                        sql.Identifier(self.SCHEMA),
                        sql.Identifier(table)
                    ),
                    values
                )
                conn.commit()
                logger.info(f"Upserted route: {route['slug']}/{route['version_id']} → {table}")
                return True

    def clear_latest(self, slug: str, table: str = "b2c_routes") -> int:
        """
        Set is_latest=false for all versions of a slug.

        Called before setting a new version as latest.

        Returns:
            Number of rows updated
        """
        table = self._validate_table(table)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "UPDATE {}.{} SET is_latest = false WHERE slug = %s AND is_latest = true"
                    ).format(
                        sql.Identifier(self.SCHEMA),
                        sql.Identifier(table)
                    ),
                    (slug,)
                )
                count = cur.rowcount
                conn.commit()
                if count > 0:
                    logger.info(f"Cleared is_latest for {slug} in {table} ({count} rows)")
                return count

    def delete_route(self, slug: str, version_id: str, table: str = "b2c_routes") -> bool:
        """
        Delete a specific route (on revocation).

        Returns:
            True if a row was deleted
        """
        table = self._validate_table(table)
        logger.info(f"Deleting route: {slug}/{version_id} from {table}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {}.{} WHERE slug = %s AND version_id = %s"
                    ).format(
                        sql.Identifier(self.SCHEMA),
                        sql.Identifier(table)
                    ),
                    (slug, version_id)
                )
                deleted = cur.rowcount > 0
                conn.commit()
                if deleted:
                    logger.info(f"Deleted route: {slug}/{version_id} from {table}")
                else:
                    logger.warning(f"Route not found for deletion: {slug}/{version_id} in {table}")
                return deleted

    def promote_next_latest(self, slug: str, table: str = "b2c_routes") -> Optional[str]:
        """
        After revoking the latest version, promote the next most recent.

        Finds the approved version with the highest version_ordinal and
        sets is_latest=true. Must be called within same transaction context
        as the revocation.

        Returns:
            version_id of newly promoted version, or None if no versions remain
        """
        table = self._validate_table(table)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Find next most recent version
                cur.execute(
                    sql.SQL(
                        "SELECT version_id FROM {}.{} "
                        "WHERE slug = %s "
                        "ORDER BY version_ordinal DESC LIMIT 1"
                    ).format(
                        sql.Identifier(self.SCHEMA),
                        sql.Identifier(table)
                    ),
                    (slug,)
                )
                row = cur.fetchone()

                if not row:
                    logger.info(f"No remaining versions for {slug} in {table}")
                    conn.commit()
                    return None

                next_version = row[0]

                # Promote it
                cur.execute(
                    sql.SQL(
                        "UPDATE {}.{} SET is_latest = true "
                        "WHERE slug = %s AND version_id = %s"
                    ).format(
                        sql.Identifier(self.SCHEMA),
                        sql.Identifier(table)
                    ),
                    (slug, next_version)
                )
                conn.commit()
                logger.info(f"Promoted {slug}/{next_version} to is_latest in {table}")
                return next_version

    def get_by_slug(self, slug: str, version: str = "latest", table: str = "b2c_routes") -> Optional[Dict[str, Any]]:
        """
        Look up a route by slug and version. Used for verification.

        Args:
            slug: Route slug
            version: 'latest' or specific version_id
            table: Which routes table

        Returns:
            Dict of route fields, or None
        """
        table = self._validate_table(table)

        if version == "latest":
            where = "slug = %s AND is_latest = true"
            params = (slug,)
        else:
            where = "slug = %s AND version_id = %s"
            params = (slug, version)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        f"SELECT * FROM {{}}.{{}} WHERE {where}"
                    ).format(
                        sql.Identifier(self.SCHEMA),
                        sql.Identifier(table)
                    ),
                    params
                )
                row = cur.fetchone()
                if not row:
                    return None
                # Get column names from cursor description
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
```

**Step 2: Register in `infrastructure/__init__.py`**

At line 95 (TYPE_CHECKING block), add:

```python
    from .route_repository import RouteRepository as _RouteRepository
```

At line 277 (before `else: raise AttributeError`), add:

```python
    # Route Repository (02 MAR 2026 - Public/Internal Routing)
    elif name == "RouteRepository":
        from .route_repository import RouteRepository
        return RouteRepository
```

At line 329 (`__all__` list, before closing `]`), add:

```python
    # Route Repository (02 MAR 2026 - Public/Internal Routing)
    "RouteRepository",
```

**Step 3: Verify import**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from infrastructure import RouteRepository; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add infrastructure/route_repository.py infrastructure/__init__.py
git commit -m "feat: add RouteRepository for geo.b2c_routes and geo.b2b_routes"
```

---

## Task 4: Wire Route Creation into Approval Service

**Files:**
- Modify: `services/asset_approval_service.py:365-387` (add route creation after ADF trigger)
- Modify: `services/asset_approval_service.py:561-564` (add route deletion on revocation)

**Step 1: Add route creation helper method**

Add after the `_trigger_adf_pipeline` method (after line 821):

```python
    # =========================================================================
    # ROUTE MANAGEMENT
    # =========================================================================

    def _create_routes(
        self,
        release: AssetRelease,
        asset,
        version_id: str,
        clearance_state: ClearanceState,
        reviewer: str
    ) -> Dict[str, Any]:
        """
        Create route records for approved release.

        PUBLIC: writes both b2b_routes and b2c_routes
        OUO: writes b2b_routes only

        Args:
            release: The approved release
            asset: The parent asset (has dataset_id, resource_id)
            version_id: Assigned version
            clearance_state: OUO or PUBLIC
            reviewer: Who approved

        Returns:
            Dict with success, slug, tables_written
        """
        try:
            from infrastructure import RouteRepository
            from config.platform_config import _slugify_for_stac
            from infrastructure import ReleaseTableRepository

            route_repo = RouteRepository()
            now = datetime.now(timezone.utc)

            slug = _slugify_for_stac(f"{asset.dataset_id}-{asset.resource_id}")

            # Determine data_type
            data_type = asset.data_type or 'raster'
            if release.stac_item_json and release.stac_item_json.get('properties', {}).get('geoetl:data_type') == 'zarr':
                data_type = 'zarr'

            # Get table_name for vector
            table_name = None
            if data_type == 'vector':
                release_tables = ReleaseTableRepository().get_table_names(release.release_id)
                table_name = release_tables[0] if release_tables else None

            route = {
                'slug': slug,
                'version_id': version_id,
                'data_type': data_type,
                'is_latest': True,
                'version_ordinal': release.version_ordinal,
                'table_name': table_name,
                'stac_item_id': release.stac_item_id,
                'stac_collection_id': release.stac_collection_id,
                'blob_path': release.blob_path,
                'title': getattr(asset, 'title', None) or slug,
                'description': getattr(asset, 'description', None),
                'asset_id': asset.asset_id,
                'release_id': release.release_id,
                'cleared_by': reviewer,
                'cleared_at': now,
                'created_at': now,
            }

            tables_written = []

            # B2B always (all approved releases get internal routing)
            route_repo.clear_latest(slug, table='b2b_routes')
            route_repo.upsert_route(route, table='b2b_routes')
            tables_written.append('b2b_routes')

            # B2C only for PUBLIC
            if clearance_state == ClearanceState.PUBLIC:
                route_repo.clear_latest(slug, table='b2c_routes')
                route_repo.upsert_route(route, table='b2c_routes')
                tables_written.append('b2c_routes')

            logger.info(f"Routes created for {slug}/{version_id}: {tables_written}")
            return {'success': True, 'slug': slug, 'tables_written': tables_written}

        except Exception as e:
            logger.warning(f"Route creation failed (non-fatal): {e}")
            return {'success': False, 'error': str(e)}

    def _delete_routes(self, release: AssetRelease, asset) -> Dict[str, Any]:
        """
        Delete route records on revocation and promote next latest.

        Args:
            release: The revoked release
            asset: The parent asset

        Returns:
            Dict with success, promoted_version
        """
        try:
            from infrastructure import RouteRepository
            from config.platform_config import _slugify_for_stac

            route_repo = RouteRepository()
            slug = _slugify_for_stac(f"{asset.dataset_id}-{asset.resource_id}")
            version_id = release.version_id

            if not version_id:
                return {'success': False, 'error': 'Release has no version_id'}

            # Delete from both tables
            route_repo.delete_route(slug, version_id, table='b2c_routes')
            route_repo.delete_route(slug, version_id, table='b2b_routes')

            # Promote next latest if this was the latest
            promoted = None
            if release.is_latest:
                promoted = route_repo.promote_next_latest(slug, table='b2b_routes')
                route_repo.promote_next_latest(slug, table='b2c_routes')

            logger.info(f"Routes deleted for {slug}/{version_id}, promoted: {promoted}")
            return {'success': True, 'promoted_version': promoted}

        except Exception as e:
            logger.warning(f"Route deletion failed (non-fatal): {e}")
            return {'success': False, 'error': str(e)}
```

**Step 2: Call `_create_routes` in `approve_release` (after line 364, before ADF trigger)**

Insert at line 365, before the `# Step 7: Trigger ADF if PUBLIC` comment:

```python
        # Step 6b: Create route records
        route_result = self._create_routes(release, asset, version_id, clearance_state, reviewer)
        if route_result.get('success'):
            logger.info(f"Routes created: {route_result.get('slug')}")
        else:
            logger.warning(f"Route creation failed (non-fatal): {route_result.get('error')}")
```

**Step 3: Call `_delete_routes` in `revoke_release` (after line 562, after STAC deletion)**

Insert after the `stac_result = self._delete_stac(release)` line:

```python
        # Delete route records
        route_result = self._delete_routes(release, asset_for_routes)
```

This requires reading the asset earlier in the revoke method. Add before the STAC deletion block (around line 560):

```python
        # Get asset for route deletion (need dataset_id, resource_id for slug)
        from infrastructure import AssetRepository
        asset_repo = AssetRepository()
        asset_for_routes = asset_repo.get_by_id(release.asset_id)
```

**Step 4: Add `slug` to ADF pipeline parameters**

In `_trigger_adf_pipeline` (line 783-796), add slug to the parameters dict:

```python
                parameters={
                    'release_id': release.release_id,
                    'asset_id': release.asset_id,
                    'slug': _slugify_for_stac(f"{asset.dataset_id}-{asset.resource_id}") if asset else None,
                    # ... existing parameters ...
                }
```

Note: The `asset` variable is already loaded earlier in approve_release (line 220). For `_trigger_adf_pipeline`, the asset is not currently available. Add it as a parameter to the method, or compute slug from the release's cached data.

**Step 5: Commit**

```bash
git add services/asset_approval_service.py
git commit -m "feat: wire route creation/deletion into approval and revocation workflows"
```

---

## Task 5: Deploy and Verify

**Step 1: Deploy schema changes**

```bash
# Deploy function app (creates tables with action=ensure)
./deploy.sh orchestrator
```

After deploy:

```bash
# Wait for restart
sleep 45

# Health check
curl -sf https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Create tables (safe, additive)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=ensure&confirm=yes"
```

**Step 2: Verify tables exist**

```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/diagnostics/all | python3 -m json.tool | grep -i "b2c_routes\|b2b_routes"
```

**Step 3: Test end-to-end**

Submit a test raster, then approve it as PUBLIC:

```bash
# Submit
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test-routing",
    "resource_id": "sample-raster",
    "file_url": "https://rmhazuregeo.blob.core.windows.net/bronze-rasters/test/sample.tif",
    "data_type": "raster"
  }'

# Wait for processing, then approve as PUBLIC
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/approve \
  -H "Content-Type: application/json" \
  -d '{
    "release_id": "<RELEASE_ID>",
    "reviewer": "test@example.com",
    "clearance_state": "public",
    "version_id": "v1"
  }'

# Verify route was created
# (check via dbadmin or direct SQL query)
```

**Step 4: Commit version bump if all passes**

```bash
# Update version in config/__init__.py
git add config/__init__.py
git commit -m "v0.9.12.0 - routing tables and approval integration"
```

---

## Summary of All Files Changed

| File | Action | Task |
|---|---|---|
| `core/models/geo.py` | Add B2CRoute + B2BRoute models | 1 |
| `core/models/__init__.py` | Export new models | 1 |
| `core/schema/sql_generator.py` | Register in geo DDL generator | 2 |
| `infrastructure/route_repository.py` | **Create** — CRUD for route tables | 3 |
| `infrastructure/__init__.py` | Register RouteRepository | 3 |
| `services/asset_approval_service.py` | Wire route create/delete into approve/revoke | 4 |

---

## What This Does NOT Include (rmhtitiler scope)

- `AssetResolver` rewrite (reads routes table)
- `/assets/{slug}/*` router endpoints
- Zone-parameterized config
- These are rmhtitiler tasks — see `rmhtitiler/ROUTING_DESIGN.md`

## What This Does NOT Include (ADF scope)

- `export_to_public` pipeline creation in Azure Data Factory
- External PostgreSQL server provisioning
- External blob storage provisioning
- These are blocked by eService request (T4.3.3)
