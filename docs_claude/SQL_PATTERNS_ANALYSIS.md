# SQL Patterns Analysis - postgis_connection_string Usage

**Date**: 26 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document the multiple SQL patterns in use and assess their appropriateness

## Executive Summary

The codebase uses **THREE distinct SQL patterns**, each justified for its specific context:

1. **Repository Pattern** (Primary) - Used by CoreMachine and business logic
2. **Direct psycopg Pattern** - Used for infrastructure setup and health checks
3. **STAC/PostGIS Pattern** - Used for geospatial operations

All patterns correctly use `config.postgis_connection_string` as the single source of truth.

## Pattern 1: Repository Pattern (Primary Architecture)

### Used By
- **CoreMachine** → StateManager → RepositoryFactory → JobRepository/TaskRepository
- **Platform Service Layer** → PlatformRepository
- **All business logic operations**

### Connection Flow
```python
# 1. Config provides connection string
config.postgis_connection_string
    ↓
# 2. PostgreSQLRepository base class
PostgreSQLRepository.__init__(connection_string=config.postgis_connection_string)
    ↓
# 3. Context manager for connections
with self._get_connection() as conn:
    # psycopg.connect() with row_factory=dict_row
    ↓
# 4. SQL composition for safety
sql.SQL("INSERT INTO {}.{} ...").format(
    sql.Identifier(schema),
    sql.Identifier(table)
)
```

### Characteristics
- **Inheritance hierarchy**: PostgreSQLRepository → JobRepository → business logic
- **Connection pooling**: Each operation creates new connection (thread-safe)
- **SQL injection protection**: psycopg.sql composition
- **Transaction management**: Explicit commits, automatic rollbacks
- **Schema awareness**: Configurable schema (default: "app")

### Example
```python
class JobRepository(PostgreSQLJobRepository):
    def create_job(self, job: JobRecord) -> bool:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                query = sql.SQL("INSERT INTO {}.{} ...").format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs")
                )
                cur.execute(query, params)
```

### ✅ Justification
- **Appropriate for**: All business logic, job/task operations
- **Benefits**: Consistent error handling, connection management, SQL safety
- **Pattern correctness**: CORRECT - follows enterprise patterns

## Pattern 2: Direct psycopg Pattern (Infrastructure)

### Used By
- **Health checks** (`triggers/health.py`)
- **Schema deployment** (`triggers/schema_pydantic_deploy.py`)
- **Database queries** (`triggers/db_query.py`)
- **Infrastructure setup**

### Connection Flow
```python
# Direct connection for one-off operations
conn = psycopg.connect(config.postgis_connection_string)
try:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS pgstac")
        conn.commit()
finally:
    conn.close()
```

### Characteristics
- **Direct connections**: No repository abstraction
- **Simple operations**: Schema creation, health checks, diagnostics
- **Manual management**: Explicit close() in finally blocks
- **Raw SQL**: Direct SQL strings for DDL operations

### Example
```python
# From health.py
def _check_database_connectivity(self) -> Dict[str, Any]:
    conn_str = self.config.postgis_connection_string
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
```

### ✅ Justification
- **Appropriate for**: Infrastructure operations, health checks, schema setup
- **Benefits**: Simple, direct, no abstraction overhead
- **Pattern correctness**: CORRECT - infrastructure doesn't need business abstraction

## Pattern 3: STAC/PostGIS Pattern (Geospatial)

### Used By
- **StacInfrastructure** (`infrastructure/stac.py`)
- **Vector services** (`services/service_stac_vector.py`)
- **PostGIS operations** (`services/vector/postgis_handler.py`)

### Connection Flow
```python
# STAC operations with geospatial focus
self.connection_string = config.postgis_connection_string

# For PgSTAC operations
with psycopg.connect(self.connection_string) as conn:
    # PgSTAC-specific operations
    conn.execute("SELECT pgstac.create_collection(%s)", [collection_json])

# For PostGIS operations
with psycopg.connect(self.conn_string) as conn:
    # Geospatial queries
    cur.execute("""
        SELECT ST_AsGeoJSON(geometry) as geom,
               ST_Extent(geometry) as bbox
        FROM geo.vectors
    """)
```

### Characteristics
- **Geospatial focus**: PostGIS and PgSTAC specific operations
- **Schema variety**: Works with multiple schemas (pgstac, geo, public)
- **Specialized SQL**: ST_* functions, PgSTAC procedures
- **JSON handling**: Heavy use of JSONB for STAC items

### Example
```python
class StacInfrastructure:
    def __init__(self):
        self.connection_string = config.postgis_connection_string

    def create_stac_item(self, item: Dict) -> bool:
        with psycopg.connect(self.connection_string) as conn:
            conn.execute(
                "SELECT pgstac.create_item(%s::jsonb)",
                [json.dumps(item)]
            )
```

### ✅ Justification
- **Appropriate for**: Geospatial operations, STAC catalog management
- **Benefits**: Direct access to PostGIS/PgSTAC functions
- **Pattern correctness**: CORRECT - geospatial operations need specialized access

## Connection String Management

### Single Source of Truth ✅
```python
# config.py
@property
def postgis_connection_string(self) -> str:
    """Build PostgreSQL connection string from configuration."""
    # Priority: env var > individual components
    if env_conn_str := os.getenv("POSTGRESQL_CONNECTION_STRING"):
        return env_conn_str

    # Build from components
    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=require"
```

### Usage Consistency ✅
All three patterns correctly use:
```python
config = get_config()
conn_string = config.postgis_connection_string
```

## Recommendations

### 1. Current State: APPROPRIATE ✅
The multiple patterns are **justified and correct**:
- **Repository pattern** for business logic (clean, testable)
- **Direct pattern** for infrastructure (simple, efficient)
- **STAC pattern** for geospatial (specialized operations)

### 2. No Refactoring Needed
Each pattern serves its purpose well:
- Don't force repository pattern on infrastructure operations
- Don't simplify geospatial operations that need special handling
- Keep business logic in repositories for testing/mocking

### 3. Documentation Enhancement
Consider adding pattern guidance:
```python
# Pattern selection guide
if operation_type == "business_logic":
    use_repository_pattern()  # JobRepository, TaskRepository
elif operation_type == "infrastructure":
    use_direct_pattern()      # Health checks, schema ops
elif operation_type == "geospatial":
    use_stac_pattern()        # STAC items, PostGIS queries
```

### 4. Connection Pool Consideration
Current approach creates new connections per operation. For high-throughput scenarios, consider:
```python
# Future enhancement
from psycopg_pool import ConnectionPool

class PostgreSQLRepository:
    def __init__(self):
        self.pool = ConnectionPool(
            conninfo=config.postgis_connection_string,
            min_size=4,
            max_size=20
        )
```

## Summary

The codebase demonstrates **mature architecture** with appropriate pattern selection:

1. **Business logic** → Repository pattern (abstraction, safety)
2. **Infrastructure** → Direct psycopg (simplicity)
3. **Geospatial** → STAC/PostGIS pattern (specialized needs)

All patterns correctly use `config.postgis_connection_string` as the single source of truth, ensuring connection consistency while allowing architectural flexibility where needed.

**Verdict**: The multiple SQL patterns are **APPROPRIATE and WELL-DESIGNED**. No refactoring needed.