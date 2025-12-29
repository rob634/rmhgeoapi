# ============================================================================
# CLAUDE CONTEXT - JOB PROGRESS CONTEXT MIXINS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Domain-Specific Progress Tracking
# PURPOSE: Context mixins for H3, FATHOM, and Raster job tracking
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: H3AggregationContext, FathomETLContext, RasterCollectionContext,
#          H3AggregationTracker, FathomETLTracker, RasterCollectionTracker
# DEPENDENCIES: infrastructure.job_progress
# ============================================================================
"""
Domain-Specific Progress Context Mixins.

Provides context mixins that add domain-specific metrics to the universal
JobProgressTracker. Each mixin tracks metrics relevant to its domain.

Architecture:
-------------
```
JobProgressTracker (universal)
    │
    ├── H3AggregationContext (mixin)
    │   └── cells, stats, tiles
    │
    ├── FathomETLContext (mixin)
    │   └── tiles, bytes, regions
    │
    └── RasterCollectionContext (mixin)
        └── files, COGs, sizes
```

Concrete Trackers:
------------------
```python
# H3 Aggregation (cells, stats, tiles)
class H3AggregationTracker(JobProgressTracker, H3AggregationContext):
    pass

# FATHOM ETL (tiles, bytes, regions)
class FathomETLTracker(JobProgressTracker, FathomETLContext):
    pass

# Raster Collection (files, COGs, sizes)
class RasterCollectionTracker(JobProgressTracker, RasterCollectionContext):
    pass
```

Usage:
------
```python
from infrastructure.job_progress_contexts import H3AggregationTracker

tracker = H3AggregationTracker(
    job_id="abc123",
    job_type="h3_raster_aggregation"
)

# Set H3-specific totals
tracker.set_cells_total(68597)

# Track batch progress
tracker.record_batch(
    cells=1000,
    stats=4000,
    tile_id="Copernicus_DSM_COG_10_S02_00_E029_00"
)

# Get snapshot with H3 context
snapshot = tracker.get_snapshot()
print(f"Cells: {snapshot.context['cells_processed']}/{snapshot.context['cells_total']}")
print(f"Rate: {snapshot.context['cells_rate_per_sec']:.0f} cells/sec")
```
"""

import time
from typing import Dict, Any, Optional, List
from collections import deque

from infrastructure.job_progress import JobProgressTracker


# ============================================================================
# H3 AGGREGATION CONTEXT
# ============================================================================

class H3AggregationContext:
    """
    H3 Aggregation context mixin.

    Tracks H3-specific metrics:
    - cells_total: Total H3 cells to process
    - cells_processed: Cells completed so far
    - stats_computed: Total zonal stats computed
    - tiles_discovered: STAC tiles found for coverage
    - current_tile: Currently processing tile ID

    Rate Calculation:
    - cells_rate_per_sec: Rolling average cells/second
    """

    def __init__(self, *args, **kwargs):
        """Initialize H3 context."""
        super().__init__(*args, **kwargs)

        # H3-specific counters
        self._h3_cells_total = 0
        self._h3_cells_processed = 0
        self._h3_stats_computed = 0
        self._h3_tiles_discovered = 0
        self._h3_current_tile: Optional[str] = None
        self._h3_tiles_processed: List[str] = []

        # Rate tracking (cells per second)
        self._h3_cell_times: deque = deque(maxlen=100)  # (timestamp, count)

        # Set context type
        self.set_context("type", "h3_aggregation")

    def set_cells_total(self, count: int):
        """Set total cells to process."""
        self._h3_cells_total = count
        self.set_context("cells_total", count)
        self.emit_debug(f"Total cells: {count:,}")

    def set_tiles_discovered(self, count: int, tile_ids: Optional[List[str]] = None):
        """Set discovered STAC tiles."""
        self._h3_tiles_discovered = count
        self.set_context("tiles_discovered", count)
        if tile_ids:
            self.set_context("tile_ids", tile_ids[:10])  # First 10
        self.emit_debug(f"Discovered {count} tiles")

    def start_tile(self, tile_id: str):
        """Mark start of processing a tile."""
        self._h3_current_tile = tile_id
        self.set_context("current_tile", tile_id)
        self.emit_debug(f"Processing tile: {tile_id}")

    def complete_tile(self, tile_id: str):
        """Mark tile as complete."""
        if tile_id not in self._h3_tiles_processed:
            self._h3_tiles_processed.append(tile_id)
        self.set_context("tiles_processed", len(self._h3_tiles_processed))
        self.emit_debug(f"Completed tile: {tile_id}")

    def record_batch(
        self,
        cells: int,
        stats: int,
        tile_id: Optional[str] = None,
        batch_index: Optional[int] = None
    ):
        """
        Record a batch of cells processed.

        Args:
            cells: Number of cells in batch
            stats: Number of stats computed
            tile_id: Optional tile ID for this batch
            batch_index: Optional batch index for logging
        """
        now = time.time()

        self._h3_cells_processed += cells
        self._h3_stats_computed += stats
        self._h3_cell_times.append((now, cells))

        if tile_id:
            self._h3_current_tile = tile_id

        # Update context
        self.update_context({
            "cells_processed": self._h3_cells_processed,
            "stats_computed": self._h3_stats_computed,
            "cells_rate_per_sec": self._calculate_cells_rate(),
            "current_tile": self._h3_current_tile
        })

        # Debug output
        rate = self._calculate_cells_rate()
        batch_str = f"Batch {batch_index}" if batch_index is not None else "Batch"
        self.emit_debug(
            f"  {batch_str}: {cells:,} cells, {stats:,} stats @ {rate:.0f} cells/sec",
            indent=1
        )

    def _calculate_cells_rate(self) -> float:
        """Calculate cells per second (rolling average)."""
        if not self._h3_cell_times:
            return 0.0

        now = time.time()
        window_start = now - 60  # Last 60 seconds

        # Sum cells in window
        total_cells = sum(
            c for t, c in self._h3_cell_times
            if t > window_start
        )

        if total_cells == 0:
            return 0.0

        # Calculate window duration
        recent = [t for t, _ in self._h3_cell_times if t > window_start]
        if len(recent) < 2:
            return float(total_cells)  # Single point

        window_duration = max(recent) - min(recent)
        if window_duration < 0.1:
            return float(total_cells)

        return total_cells / window_duration

    def get_h3_progress_summary(self) -> Dict[str, Any]:
        """Get H3-specific progress summary."""
        pct = 0.0
        if self._h3_cells_total > 0:
            pct = (self._h3_cells_processed / self._h3_cells_total) * 100

        return {
            "cells_total": self._h3_cells_total,
            "cells_processed": self._h3_cells_processed,
            "cells_remaining": self._h3_cells_total - self._h3_cells_processed,
            "cells_progress_pct": round(pct, 1),
            "stats_computed": self._h3_stats_computed,
            "cells_rate_per_sec": round(self._calculate_cells_rate(), 1),
            "tiles_discovered": self._h3_tiles_discovered,
            "tiles_processed": len(self._h3_tiles_processed),
            "current_tile": self._h3_current_tile
        }


# ============================================================================
# FATHOM ETL CONTEXT
# ============================================================================

class FathomETLContext:
    """
    FATHOM ETL context mixin.

    Tracks FATHOM-specific metrics:
    - tiles_total: Total FATHOM tiles to process
    - tiles_merged: Tiles merged so far
    - bytes_processed: Total bytes processed
    - current_region: Current geographic region
    """

    def __init__(self, *args, **kwargs):
        """Initialize FATHOM context."""
        super().__init__(*args, **kwargs)

        # FATHOM-specific counters
        self._fathom_tiles_total = 0
        self._fathom_tiles_merged = 0
        self._fathom_bytes_processed = 0
        self._fathom_current_region: Optional[str] = None
        self._fathom_regions_completed: List[str] = []

        # Set context type
        self.set_context("type", "fathom_etl")

    def set_tiles_total(self, count: int):
        """Set total tiles to process."""
        self._fathom_tiles_total = count
        self.set_context("tiles_total", count)
        self.emit_debug(f"Total tiles: {count:,}")

    def start_region(self, region: str):
        """Mark start of processing a region."""
        self._fathom_current_region = region
        self.set_context("current_region", region)
        self.emit_debug(f"Processing region: {region}")

    def complete_region(self, region: str):
        """Mark region as complete."""
        if region not in self._fathom_regions_completed:
            self._fathom_regions_completed.append(region)
        self.set_context("regions_completed", len(self._fathom_regions_completed))
        self.emit_debug(f"Completed region: {region}")

    def record_tile(
        self,
        tile_id: str,
        size_bytes: int,
        region: Optional[str] = None
    ):
        """
        Record a tile processed.

        Args:
            tile_id: Tile identifier
            size_bytes: Size of tile in bytes
            region: Optional region for this tile
        """
        self._fathom_tiles_merged += 1
        self._fathom_bytes_processed += size_bytes

        if region:
            self._fathom_current_region = region

        # Update context
        self.update_context({
            "tiles_merged": self._fathom_tiles_merged,
            "bytes_processed": self._fathom_bytes_processed,
            "bytes_processed_gb": round(self._fathom_bytes_processed / (1024**3), 2),
            "current_region": self._fathom_current_region
        })

        size_mb = size_bytes / (1024 * 1024)
        self.emit_debug(f"  Tile {tile_id}: {size_mb:.1f} MB", indent=1)

    def get_fathom_progress_summary(self) -> Dict[str, Any]:
        """Get FATHOM-specific progress summary."""
        pct = 0.0
        if self._fathom_tiles_total > 0:
            pct = (self._fathom_tiles_merged / self._fathom_tiles_total) * 100

        return {
            "tiles_total": self._fathom_tiles_total,
            "tiles_merged": self._fathom_tiles_merged,
            "tiles_remaining": self._fathom_tiles_total - self._fathom_tiles_merged,
            "tiles_progress_pct": round(pct, 1),
            "bytes_processed": self._fathom_bytes_processed,
            "bytes_processed_gb": round(self._fathom_bytes_processed / (1024**3), 2),
            "regions_completed": len(self._fathom_regions_completed),
            "current_region": self._fathom_current_region
        }


# ============================================================================
# RASTER COLLECTION CONTEXT
# ============================================================================

class RasterCollectionContext:
    """
    Raster Collection context mixin.

    Tracks raster collection metrics:
    - files_total: Total files to process
    - files_processed: Files completed so far
    - cogs_created: COGs created
    - total_output_size_bytes: Total output size
    """

    def __init__(self, *args, **kwargs):
        """Initialize raster collection context."""
        super().__init__(*args, **kwargs)

        # Raster-specific counters
        self._raster_files_total = 0
        self._raster_files_processed = 0
        self._raster_cogs_created = 0
        self._raster_output_bytes = 0
        self._raster_input_bytes = 0
        self._raster_current_file: Optional[str] = None

        # Set context type
        self.set_context("type", "raster_collection")

    def set_files_total(self, count: int):
        """Set total files to process."""
        self._raster_files_total = count
        self.set_context("files_total", count)
        self.emit_debug(f"Total files: {count:,}")

    def record_file(
        self,
        filename: str,
        input_size_bytes: int,
        output_size_bytes: int,
        cog_created: bool = True
    ):
        """
        Record a file processed.

        Args:
            filename: Name of file processed
            input_size_bytes: Input file size
            output_size_bytes: Output COG size
            cog_created: Whether a COG was created
        """
        self._raster_files_processed += 1
        self._raster_input_bytes += input_size_bytes
        self._raster_output_bytes += output_size_bytes
        self._raster_current_file = filename

        if cog_created:
            self._raster_cogs_created += 1

        # Update context
        self.update_context({
            "files_processed": self._raster_files_processed,
            "cogs_created": self._raster_cogs_created,
            "input_size_gb": round(self._raster_input_bytes / (1024**3), 2),
            "output_size_gb": round(self._raster_output_bytes / (1024**3), 2),
            "current_file": filename
        })

        output_mb = output_size_bytes / (1024 * 1024)
        self.emit_debug(f"  File {filename}: {output_mb:.1f} MB COG", indent=1)

    def get_raster_progress_summary(self) -> Dict[str, Any]:
        """Get raster-specific progress summary."""
        pct = 0.0
        if self._raster_files_total > 0:
            pct = (self._raster_files_processed / self._raster_files_total) * 100

        compression_ratio = 0.0
        if self._raster_input_bytes > 0:
            compression_ratio = self._raster_output_bytes / self._raster_input_bytes

        return {
            "files_total": self._raster_files_total,
            "files_processed": self._raster_files_processed,
            "files_remaining": self._raster_files_total - self._raster_files_processed,
            "files_progress_pct": round(pct, 1),
            "cogs_created": self._raster_cogs_created,
            "input_size_gb": round(self._raster_input_bytes / (1024**3), 2),
            "output_size_gb": round(self._raster_output_bytes / (1024**3), 2),
            "compression_ratio": round(compression_ratio, 2),
            "current_file": self._raster_current_file
        }


# ============================================================================
# CONCRETE TRACKER CLASSES
# ============================================================================

class H3AggregationTracker(H3AggregationContext, JobProgressTracker):
    """
    H3 Aggregation job tracker.

    Combines universal progress tracking with H3-specific context.

    Usage:
    ```python
    tracker = H3AggregationTracker(
        job_id="abc123",
        job_type="h3_raster_aggregation"
    )
    tracker.set_cells_total(68597)
    tracker.start_stage(2, "compute_stats", task_count=5)

    for batch in batches:
        tracker.task_started(batch.task_id)
        # ... process ...
        tracker.record_batch(cells=1000, stats=4000)
        tracker.task_completed(batch.task_id)
    ```
    """
    pass


class FathomETLTracker(FathomETLContext, JobProgressTracker):
    """
    FATHOM ETL job tracker.

    Combines universal progress tracking with FATHOM-specific context.

    Usage:
    ```python
    tracker = FathomETLTracker(
        job_id="abc123",
        job_type="process_fathom_merge"
    )
    tracker.set_tiles_total(2500)
    tracker.start_region("West Africa")

    for tile in tiles:
        tracker.task_started(tile.task_id)
        # ... merge ...
        tracker.record_tile(tile.id, size_bytes=50_000_000)
        tracker.task_completed(tile.task_id)
    ```
    """
    pass


class RasterCollectionTracker(RasterCollectionContext, JobProgressTracker):
    """
    Raster Collection job tracker.

    Combines universal progress tracking with raster-specific context.

    Usage:
    ```python
    tracker = RasterCollectionTracker(
        job_id="abc123",
        job_type="process_raster_collection_v2"
    )
    tracker.set_files_total(150)

    for file in files:
        tracker.task_started(file.task_id)
        # ... process ...
        tracker.record_file(file.name, input_size, output_size)
        tracker.task_completed(file.task_id)
    ```
    """
    pass


# Export
__all__ = [
    # Context mixins
    "H3AggregationContext",
    "FathomETLContext",
    "RasterCollectionContext",

    # Concrete trackers
    "H3AggregationTracker",
    "FathomETLTracker",
    "RasterCollectionTracker",
]
