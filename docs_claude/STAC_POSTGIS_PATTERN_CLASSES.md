# STAC/PostGIS Pattern - Class Analysis

**Date**: 26 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Identify Group #3 classes and assess if they should use repository pattern

## Group #3: Classes Using Direct STAC/PostGIS Pattern

### 1. StacInfrastructure (`infrastructure/stac.py`)

**Purpose**: PgSTAC schema management and STAC collection/item operations

**Direct Connection Usage**:
```python
def __init__(self, connection_string: Optional[str] = None):
    self.connection_string = connection_string or self.config.postgis_connection_string

# Example operations
with psycopg.connect(self.connection_string) as conn:
    conn.execute("SELECT pgstac.create_collection(%s::jsonb)", [collection_json])
    conn.execute("SELECT pgstac.create_item(%s::jsonb)", [item_json])
```

**Should Use Repository Pattern?**: ❌ **NO**
- **Reason**: Calls PgSTAC-specific stored procedures (`pgstac.*` functions)
- **Justification**: These are PostgreSQL extension functions, not regular CRUD
- **Verdict**: Direct connection is appropriate

---

### 2. StacVectorService (`services/service_stac_vector.py`)

**Purpose**: Extract STAC metadata from PostGIS vector tables

**Direct Connection Usage**:
```python
def _get_table_metadata(self, schema: str, table_name: str):
    with psycopg.connect(self.config.postgis_connection_string) as conn:
        # Query geometry_columns view
        cur.execute("""
            SELECT f_geometry_column, srid, type
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s
        """)

        # PostGIS spatial functions
        cur.execute("""
            SELECT
                ST_Extent({geom_col}) as bbox,
                COUNT(*) as feature_count,
                ST_GeometryType({geom_col}) as geom_type
            FROM {schema}.{table}
        """)
```

**Should Use Repository Pattern?**: 🤔 **MAYBE**
- **Reason**: Mix of metadata queries and PostGIS spatial functions
- **Could Refactor**: Metadata queries could use repository
- **Must Keep Direct**: ST_* spatial functions need direct access
- **Verdict**: Partial refactor possible but low priority

---

### 3. VectorToPostGISHandler (`services/vector/postgis_handler.py`)

**Purpose**: Import vector data (GeoDataFrame) into PostGIS

**Direct Connection Usage**:
```python
def ingest_to_postgis(self, gdf: gpd.GeoDataFrame, table_name: str):
    with psycopg.connect(self.conn_string) as conn:
        # Create table with PostGIS geometry column
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS geo.{table_name} (
                id SERIAL PRIMARY KEY,
                geometry geometry(Geometry, 4326),
                ...
            )
        """)

        # Bulk insert with ST_GeomFromText
        cur.execute("""
            INSERT INTO geo.{table} (geometry, ...)
            VALUES (ST_GeomFromText(%s, 4326), ...)
        """)
```

**Should Use Repository Pattern?**: ❌ **NO**
- **Reason**: Bulk geospatial data ingestion with PostGIS functions
- **Justification**: Needs direct control over PostGIS-specific DDL and spatial functions
- **Verdict**: Direct connection is appropriate

---

### 4. StacMetadataService (`services/service_stac_metadata.py`)

**Purpose**: Extract STAC metadata from raster files

**Direct Connection Usage**: ✅ **NONE** (Uses StacInfrastructure)
```python
def __init__(self):
    self.stac = StacInfrastructure()  # Delegates to StacInfrastructure

def insert_item(self, item: Dict):
    return self.stac.insert_item(item_dict, collection_id)
```

**Should Use Repository Pattern?**: N/A
- **Already using abstraction** through StacInfrastructure
- **Verdict**: Good separation of concerns

---

### 5. H3GridService (`services/h3_grid.py`)

**Purpose**: Generate H3 hexagonal grids for spatial indexing

**Direct Connection Usage**: 🔍 **TO BE VERIFIED**
- Need to check if this service uses database connections
- May only generate grids in memory

---

## Summary Analysis

### Classes That MUST Use Direct Connections

1. **StacInfrastructure** - PgSTAC stored procedures
2. **VectorToPostGISHandler** - PostGIS DDL and spatial functions

**Justification**: These classes interact with PostgreSQL extensions (PgSTAC, PostGIS) that require:
- Extension-specific functions (`pgstac.*`, `ST_*`)
- Specialized DDL for geometry columns
- Direct control over spatial operations

### Classes That COULD Use Repository Pattern (Low Priority)

1. **StacVectorService** - For metadata queries (not spatial functions)

**Potential Refactor**:
```python
# Could create a PostGISMetadataRepository
class PostGISMetadataRepository(PostgreSQLRepository):
    def get_table_extent(self, schema: str, table: str) -> Dict:
        # Query geometry_columns and table metadata
        pass

    def get_geometry_info(self, schema: str, table: str) -> Dict:
        # Get SRID, geometry type, etc.
        pass
```

But the **spatial queries must stay direct**:
```python
# Must keep direct for ST_* functions
with psycopg.connect(...) as conn:
    cur.execute("SELECT ST_Extent(geometry) FROM geo.table")
```

## Architectural Decision

### Current Approach is Correct ✅

The classes in Group #3 are appropriately using direct connections because they:

1. **Interact with PostgreSQL Extensions** (PgSTAC, PostGIS)
2. **Need Spatial SQL Functions** (ST_Transform, ST_Extent, ST_GeomFromText)
3. **Perform Specialized DDL** (Creating geometry columns, spatial indexes)
4. **Execute Extension Procedures** (pgstac.create_collection, pgstac.search)

### Why Repository Pattern Doesn't Fit

The repository pattern is designed for:
- **Business entities** (Jobs, Tasks, Users)
- **CRUD operations** (Create, Read, Update, Delete)
- **Domain logic** (Status transitions, validation)

It's NOT designed for:
- **Extension-specific functions** (PostGIS spatial operations)
- **Stored procedures** (PgSTAC functions)
- **DDL operations** (Table creation with geometry columns)

## Recommendation

**Keep the current architecture as-is.** The three-pattern approach is justified:

1. **Repository Pattern** → Business logic (Jobs, Tasks)
2. **Direct Infrastructure** → Schema setup, health checks
3. **Direct STAC/PostGIS** → Spatial operations, extension functions

The classes in Group #3 need direct database access for legitimate technical reasons related to PostgreSQL extensions, not because of poor architecture.