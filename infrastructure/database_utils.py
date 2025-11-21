# ============================================================================
# CLAUDE CONTEXT - DATABASE UTILITIES
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - Shared PostgreSQL bulk operation utilities
# PURPOSE: Reusable batching patterns for efficient database operations
# LAST_REVIEWED: 9 NOV 2025
# EXPORTS: batched_executemany (sync), batched_executemany_async (async)
# INTERFACES: Works with psycopg (sync) and asyncpg (async)
# DEPENDENCIES: psycopg[binary], asyncpg (optional)
# SOURCE: Used by H3, vector, and raster workflows
# SCOPE: All PostgreSQL bulk insert/update operations
# VALIDATION: Type hints, batch size validation
# PATTERNS: Generator pattern, batch processing, progress logging
# ENTRY_POINTS: Import and use in service handlers
# INDEX:
#   - Lines 50-115: batched_executemany (sync psycopg version)
#   - Lines 120-185: batched_executemany_async (async asyncpg version)
# ============================================================================

"""
Shared PostgreSQL Bulk Operation Utilities

Provides reusable, optimized patterns for bulk database operations
using batched executemany() for maximum performance.

Performance Comparison:
- Row-by-row: ~100-500 rows/second (1 round-trip per row)
- Batched executemany(): ~10,000-50,000 rows/second (1 round-trip per batch)
- PostgreSQL COPY: ~50,000-100,000 rows/second (bulk binary protocol)

Usage:
    Sync (psycopg):
        from infrastructure.database_utils import batched_executemany

        stmt = sql.SQL("INSERT INTO geo.features VALUES (%s, %s)")
        rows = [(1, 'a'), (2, 'b'), (3, 'c')]
        total = batched_executemany(cur, stmt, iter(rows), batch_size=1000)

    Async (asyncpg):
        from infrastructure.database_utils import batched_executemany_async

        stmt = "INSERT INTO geo.h3_grids VALUES ($1, $2, $3)"
        rows = [(1, 4, 'POLYGON(...)'), ...]
        total = await batched_executemany_async(conn, stmt, iter(rows), 1000)

"""

from typing import Iterator, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)


def batched_executemany(
    cur: 'psycopg.Cursor',
    stmt: 'psycopg.sql.Composable',
    data_iterator: Iterator[Tuple[Any, ...]],
    batch_size: int = 1000,
    description: str = "rows"
) -> int:
    """
    Execute batched INSERT/UPDATE using psycopg executemany().

    Batches data into groups and executes them in a single round-trip
    to the database, significantly improving performance over row-by-row.

    Args:
        cur: psycopg cursor (from connection context)
        stmt: Prepared SQL statement (psycopg.sql.SQL object)
        data_iterator: Iterator yielding data tuples (one per row)
        batch_size: Rows per batch (default: 1000)
        description: Log description for progress messages

    Returns:
        Total number of rows inserted/updated

    Example:
        import psycopg
        from psycopg import sql
        from infrastructure.database_utils import batched_executemany

        # Prepare statement
        stmt = sql.SQL('''
            INSERT INTO {schema}.{table} (geom, name, value)
            VALUES (ST_GeomFromText(%s, 4326), %s, %s)
        ''').format(
            schema=sql.Identifier('geo'),
            table=sql.Identifier('features')
        )

        # Generate data
        def generate_rows():
            for i in range(10000):
                yield (f'POINT({i} {i})', f'feature_{i}', i * 10)

        # Execute batched insert
        with psycopg.connect(conn_string) as conn:
            with conn.cursor() as cur:
                total = batched_executemany(
                    cur, stmt, generate_rows(),
                    batch_size=1000, description="features"
                )
                conn.commit()
                print(f"Inserted {total} features")

    Performance:
        - Row-by-row: ~500 rows/second
        - Batched (1000/batch): ~10,000 rows/second (20x faster)

    Notes:
        - Caller must commit the transaction
        - Generator pattern allows processing large datasets without holding all in memory
        - Progress logged every 10 batches for long-running operations
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    batch = []
    total_inserted = 0
    batch_count = 0

    for row_data in data_iterator:
        batch.append(row_data)

        # Execute when batch is full
        if len(batch) >= batch_size:
            cur.executemany(stmt, batch)
            total_inserted += len(batch)
            batch_count += 1

            # Log progress every 10 batches
            if batch_count % 10 == 0:
                logger.debug(
                    f"Batched insert progress: {total_inserted:,} {description} "
                    f"({batch_count} batches of {batch_size})"
                )

            batch = []

    # Insert remaining rows (partial batch)
    if batch:
        cur.executemany(stmt, batch)
        total_inserted += len(batch)
        batch_count += 1

    logger.info(
        f"✅ Batched insert complete: {total_inserted:,} {description} "
        f"in {batch_count} batches"
    )

    return total_inserted


async def batched_executemany_async(
    conn: 'asyncpg.Connection',
    stmt: str,
    data_iterator: Iterator[Tuple[Any, ...]],
    batch_size: int = 1000,
    description: str = "rows"
) -> int:
    """
    Execute batched INSERT/UPDATE using asyncpg executemany() (async version).

    Async variant for use with asyncpg connections. Provides same batching
    benefits with non-blocking I/O for better concurrency.

    Args:
        conn: asyncpg connection (from connection pool)
        stmt: SQL statement string (asyncpg uses $1, $2 placeholders)
        data_iterator: Iterator yielding data tuples (one per row)
        batch_size: Rows per batch (default: 1000)
        description: Log description for progress messages

    Returns:
        Total number of rows inserted/updated

    Example:
        import asyncpg
        from infrastructure.database_utils import batched_executemany_async

        async def insert_h3_cells():
            # Create connection pool
            pool = await asyncpg.create_pool(conn_string)

            # Prepare statement (asyncpg uses $1, $2, $3 placeholders)
            stmt = '''
                INSERT INTO geo.h3_grids (h3_index, resolution, geom)
                VALUES ($1, $2, ST_GeomFromText($3, 4326))
            '''

            # Generate data
            def generate_cells():
                for i in range(100000):
                    yield (i, 4, f'POLYGON(...)')

            # Execute batched insert
            async with pool.acquire() as conn:
                total = await batched_executemany_async(
                    conn, stmt, generate_cells(),
                    batch_size=1000, description="H3 cells"
                )
                print(f"Inserted {total} H3 cells")

            await pool.close()

    Performance:
        - Async I/O allows CPU generation to overlap with database writes
        - ~10,000-50,000 rows/second depending on data complexity
        - Memory efficient (generator pattern)

    Notes:
        - asyncpg auto-commits unless in explicit transaction
        - Use connection from pool.acquire() context
        - asyncpg uses $1, $2, $3 placeholders (not %s like psycopg)
        - Generator allows large dataset processing without memory pressure
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    batch = []
    total_inserted = 0
    batch_count = 0

    for row_data in data_iterator:
        batch.append(row_data)

        # Execute when batch is full
        if len(batch) >= batch_size:
            await conn.executemany(stmt, batch)
            total_inserted += len(batch)
            batch_count += 1

            # Log progress every 10 batches
            if batch_count % 10 == 0:
                logger.debug(
                    f"Async batched insert progress: {total_inserted:,} {description} "
                    f"({batch_count} batches of {batch_size})"
                )

            batch = []

    # Insert remaining rows (partial batch)
    if batch:
        await conn.executemany(stmt, batch)
        total_inserted += len(batch)
        batch_count += 1

    logger.info(
        f"✅ Async batched insert complete: {total_inserted:,} {description} "
        f"in {batch_count} batches"
    )

    return total_inserted


__all__ = [
    'batched_executemany',
    'batched_executemany_async',
]