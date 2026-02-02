# ============================================================================
# RASTER COG SERVICE
# ============================================================================
# STATUS: Services - Cloud Optimized GeoTIFF creation with rio-cogeo
# PURPOSE: Single-pass reprojection + COG creation with type-specific optimization
# LAST_REVIEWED: 21 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Raster COG Creation Service - Stage 2 of Raster Pipeline.

Creates Cloud Optimized GeoTIFFs with optional reprojection using rio-cogeo.

Key Innovation: Single-pass reprojection + COG creation
    - rio-cogeo.cog_translate() does both operations in one pass
    - Auto-selects optimal compression and resampling based on raster type
    - BAND interleave for cloud-native selective band access

Processing Modes (25 JAN 2026):
    DISK-BASED (when ETL mount enabled):
        - stream_blob_to_mount(): Download to mounted filesystem
        - cog_translate(file, file): Process file-to-file, GDAL uses disk for all ops
        - stream_mount_to_blob(): Upload from mounted filesystem
        - Memory usage: ~100MB regardless of file size

    IN-MEMORY (when ETL mount disabled / Function App):
        - read_blob(): Download to memory
        - MemoryFile + cog_translate: Process in RAM
        - write_blob(): Upload from memory
        - Memory usage: ~2-3x file size

Type-Specific Optimizations:
    RGB: JPEG compression (97% reduction), cubic resampling
    RGBA: WebP compression (supports alpha), cubic resampling
    DEM: LERC+DEFLATE (lossless), average overviews, bilinear reproject
    Categorical: DEFLATE, mode overviews (preserves classes), nearest reproject
    Multispectral: DEFLATE (lossless), average overviews, bilinear reproject

Exports:
    create_cog: COG creation handler function
"""

import sys
import os
import time
import tempfile
import threading
from typing import Any, Dict, Optional, Callable
from datetime import datetime, timezone

from exceptions import ContractViolationError

# F7.21: Type-safe result models (25 JAN 2026)
from core.models.raster_results import (
    TierProfileInfo,
    COGCreationData,
    COGCreationResult,
)


# ============================================================================
# PULSE WRAPPER - Threading Pattern for Blocking Operations (11 JAN 2026)
# ============================================================================
# Background thread updates task last_pulse while cog_translate() blocks.
# Prevents tasks from being stuck in "processing" forever on timeout.
# Added: 30 NOV 2025, Renamed heartbeat→pulse: 11 JAN 2026
# ============================================================================

class PulseWrapper:
    """
    Wraps blocking operations with periodic pulse updates.

    Uses a background daemon thread to update last_pulse while the main operation runs.
    Thread-safe and handles cleanup on completion or error.

    Why Threading (not async):
    - cog_translate() is a blocking C library call (GDAL)
    - Cannot use async/await - must use threads
    - Daemon thread auto-cleanup if main thread crashes

    Usage:
        pulse_fn = params.get('_pulse_fn')  # Injected by CoreMachine
        with PulseWrapper(task_id, pulse_fn, interval_seconds=30, logger=logger):
            cog_translate(...)  # Blocking operation
    """

    def __init__(
        self,
        task_id: str,
        pulse_fn: Callable[[], bool],
        interval_seconds: int = 30,
        logger=None
    ):
        """
        Initialize pulse wrapper.

        Args:
            task_id: Task ID (for logging only - pulse_fn has task_id bound)
            pulse_fn: No-arg callable that updates last_pulse (injected by CoreMachine)
            interval_seconds: Seconds between pulse updates (default: 30)
            logger: Optional logger instance
        """
        self.task_id = task_id  # For logging only
        self.pulse_fn = pulse_fn
        self.interval = interval_seconds
        self.logger = logger
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pulse_count = 0
        self._last_pulse: Optional[datetime] = None

    def _pulse_loop(self):
        """Background thread loop - updates last_pulse every interval."""
        while not self._stop_event.wait(timeout=self.interval):
            try:
                success = self.pulse_fn()  # No args - task_id bound in closure
                self._pulse_count += 1
                self._last_pulse = datetime.now(timezone.utc)
                if self.logger:
                    self.logger.debug(
                        f"💓 Pulse #{self._pulse_count} for task {self.task_id[:8]}",
                        extra={"task_id": self.task_id}
                    )
                if not success and self.logger:
                    self.logger.warning(
                        f"💔 Pulse update returned False for task {self.task_id[:8]}"
                    )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"💔 Pulse update failed: {e}")

    def __enter__(self):
        """Start pulse thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._pulse_loop, daemon=True)
        self._thread.start()
        if self.logger:
            self.logger.info(
                f"💓 Started pulse thread (interval={self.interval}s) for task {self.task_id[:8]}"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop pulse thread and cleanup."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self.logger:
            self.logger.info(
                f"💓 Stopped pulse thread after {self._pulse_count} pulses"
            )
        return False  # Don't suppress exceptions

    @property
    def pulse_count(self) -> int:
        """Number of successful pulse updates."""
        return self._pulse_count


# Lazy imports for Azure environment compatibility
def _lazy_imports():
    """Lazy import to avoid module-level import failures."""
    import rasterio
    from rasterio.enums import Resampling
    from rio_cogeo.cogeo import cog_translate
    from rio_cogeo.profiles import cog_profiles
    return rasterio, Resampling, cog_translate, cog_profiles


# read_vsimem_file() function removed - now using rasterio.io.MemoryFile instead
# MemoryFile provides same in-memory processing without needing GDAL osgeo module


# =============================================================================
# DISK-BASED COG PROCESSING (25 JAN 2026)
# =============================================================================
# When ETL mount is enabled, we use true disk-based processing:
# 1. stream_blob_to_mount(): Download blob → mounted filesystem (streaming)
# 2. cog_translate(file, file): GDAL processes file-to-file using disk I/O
# 3. stream_mount_to_blob(): Upload from mounted filesystem → blob (streaming)
#
# This allows processing files LARGER THAN CONTAINER RAM because:
# - Input is never fully loaded into Python memory
# - GDAL uses CPL_TMPDIR on mount for intermediate operations
# - Output is streamed directly from disk
# =============================================================================

def _process_cog_disk_based(
    input_blob_container: str,
    input_blob_path: str,
    output_blob_container: str,
    output_blob_path: str,
    mount_path: str,
    task_id: str,
    cog_profile: dict,
    cog_config: dict,
    overview_resampling: str,
    in_memory: bool,
    logger,
    compute_checksum: bool = True,
    target_crs: str = "EPSG:4326",
    reproject_resampling: str = "cubic",
    local_source_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process raster to COG using disk-based I/O via mounted filesystem.

    This is the LOW-MEMORY path for Docker workers with Azure Files mount.
    Data flows: Blob → Mount → GDAL → Mount → Blob (never fully in RAM).

    V0.8.1 (27 JAN 2026): Added local_source_path for direct local file processing.
    When provided, skips blob download and uses the local file directly.

    Args:
        input_blob_container: Source container name (can be None if local_source_path provided)
        input_blob_path: Source blob path (can be None if local_source_path provided)
        output_blob_container: Destination container name
        output_blob_path: Destination blob path
        mount_path: Path to mounted filesystem (e.g., /mounts/etl-temp)
        task_id: Task identifier for temp file naming
        cog_profile: COG profile dict for compression settings
        cog_config: Config dict for reprojection settings (will be updated with dst_crs if needed)
        overview_resampling: Resampling method for overviews
        in_memory: Whether GDAL should use in-memory processing (False for disk)
        logger: Logger instance
        compute_checksum: Whether to compute SHA-256 checksum
        target_crs: Target CRS for reprojection (default: EPSG:4326)
        reproject_resampling: Resampling method for reprojection (default: cubic)
        local_source_path: Optional local file path (skips blob download if provided)

    Returns:
        Dict with:
            - success: bool
            - cog_bytes_on_disk: int (file size)
            - input_path: str (temp input file path)
            - output_path: str (temp output file path)
            - download_result: dict (from stream_blob_to_mount, None if local_source_path used)
            - upload_result: dict (from stream_mount_to_blob)
            - raster_metadata: dict (from rasterio)
            - file_checksum: str (if compute_checksum=True)
            - reprojection_performed: bool (whether CRS was reprojected)
    """
    from pathlib import Path
    from infrastructure.blob import BlobRepository

    # Import GDAL for CPL_TMPDIR
    try:
        from osgeo import gdal
        gdal.SetConfigOption("CPL_TMPDIR", mount_path)
        os.environ["CPL_TMPDIR"] = mount_path
        logger.info(f"   GDAL CPL_TMPDIR set to: {mount_path}")
    except Exception as e:
        logger.warning(f"   Could not set GDAL CPL_TMPDIR: {e}")

    # Generate unique temp file paths
    task_short = task_id[:16] if task_id else "unknown"
    input_filename = f"input_{task_short}.tif"
    output_filename = f"output_{task_short}.cog.tif"
    temp_input_path = str(Path(mount_path) / input_filename)
    temp_output_path = str(Path(mount_path) / output_filename)

    logger.info(f"📁 DISK-BASED COG PROCESSING")
    logger.info(f"   Mount path: {mount_path}")
    logger.info(f"   Temp input: {temp_input_path}")
    logger.info(f"   Temp output: {temp_output_path}")

    # Detect source zone (not used when local_source_path provided)
    # V0.8.1: Handle None container_name when using local source
    if input_blob_container:
        is_silver_container = input_blob_container.startswith('silver-')
        source_zone = "silver" if is_silver_container else "bronze"
        source_repo = BlobRepository.for_zone(source_zone)
    else:
        source_repo = None  # Not needed for local source mode
    silver_repo = BlobRepository.for_zone("silver")

    raster_metadata = {}
    file_checksum = None
    download_result = None
    upload_result = None

    try:
        # STEP A: Get input file (either download from blob or use local source)
        # V0.8.1: Support local source path for mount-based tiled workflow
        if local_source_path:
            logger.info(f"🔄 DISK STEP A: Using local source file (no download)")
            logger.info(f"   Source: {local_source_path}")
            temp_input_path = local_source_path  # Use directly, no copy
            input_size_bytes = os.path.getsize(local_source_path)
            input_size_mb = input_size_bytes / (1024 * 1024)
            logger.info(f"   File size: {input_size_mb:.2f}MB")
            download_result = None  # No download performed
        else:
            logger.info(f"🔄 DISK STEP A: Streaming blob to mount...")
            download_result = source_repo.stream_blob_to_mount(
                container=input_blob_container,
                blob_path=input_blob_path,
                mount_path=temp_input_path,
                chunk_size_mb=32
            )

            if not download_result.get('success'):
                raise RuntimeError(f"stream_blob_to_mount failed: {download_result.get('error')}")

            input_size_bytes = download_result.get('bytes_transferred', 0)
            input_size_mb = input_size_bytes / (1024 * 1024)
            logger.info(f"   Downloaded {input_size_mb:.2f}MB to disk in {download_result.get('duration_seconds', 0):.1f}s")

        # STEP B: Open input file and get metadata
        logger.info(f"🔄 DISK STEP B: Reading raster metadata...")
        rasterio, Resampling, cog_translate, cog_profiles_module = _lazy_imports()

        with rasterio.open(temp_input_path) as src:
            detected_source_crs = src.crs
            raster_metadata = {
                'crs': str(detected_source_crs),
                'bounds': list(src.bounds),
                'shape': [src.height, src.width],
                'band_count': src.count,
                'dtype': str(src.dtypes[0]),
            }
            logger.info(f"   CRS: {raster_metadata['crs']}")
            logger.info(f"   Shape: {raster_metadata['shape']}")
            logger.info(f"   Bands: {raster_metadata['band_count']}")

        # STEP B2: Check if reprojection needed (26 JAN 2026 - Bug fix)
        # Compare source CRS with target CRS to determine if reprojection is required
        needs_reprojection = (str(detected_source_crs) != str(target_crs))
        reprojection_performed = False

        if needs_reprojection:
            logger.info(f"🔄 DISK STEP B2: Reprojection needed: {detected_source_crs} → {target_crs}")
            logger.info(f"   Reprojection resampling: {reproject_resampling}")
            reprojection_performed = True
        else:
            logger.info(f"   No reprojection needed (already {target_crs})")

        # STEP C: Create COG (file-to-file, GDAL uses disk)
        # NOTE: For reprojection, we must use WarpedVRT - passing dst_crs in config
        # only works when input is a rasterio dataset, not a file path string.
        # See: https://github.com/cogeotiff/rio-cogeo/discussions/284
        logger.info(f"🔄 DISK STEP C: Creating COG with cog_translate (disk-based)...")
        logger.info(f"   in_memory={in_memory} (should be False)")
        logger.info(f"   Overview resampling: {overview_resampling}")

        cog_start = time.time()

        if needs_reprojection:
            # Use WarpedVRT for reprojection (required for file path input)
            from rasterio.vrt import WarpedVRT
            logger.info(f"   Using WarpedVRT for reprojection to {target_crs}")
            with rasterio.open(temp_input_path) as src:
                vrt_options = {
                    'crs': target_crs,
                    'resampling': getattr(Resampling, reproject_resampling),
                }
                with WarpedVRT(src, **vrt_options) as vrt:
                    cog_translate(
                        vrt,
                        temp_output_path,
                        cog_profile,
                        config=cog_config,
                        overview_level=None,
                        overview_resampling=overview_resampling,
                        in_memory=in_memory,
                        quiet=False,
                    )
        else:
            # No reprojection - use file path directly
            cog_translate(
                temp_input_path,
                temp_output_path,
                cog_profile,
                config=cog_config,
                overview_level=None,
                overview_resampling=overview_resampling,
                in_memory=in_memory,
                quiet=False,
            )

        cog_duration = time.time() - cog_start

        # Get output file size
        output_size_bytes = Path(temp_output_path).stat().st_size
        output_size_mb = output_size_bytes / (1024 * 1024)
        logger.info(f"   COG created: {output_size_mb:.2f}MB in {cog_duration:.1f}s")

        # Update raster_metadata from OUTPUT file (important when reprojection occurred)
        if reprojection_performed:
            logger.info(f"🔄 DISK STEP C2: Reading output metadata after reprojection...")
            with rasterio.open(temp_output_path) as out_src:
                raster_metadata = {
                    'crs': str(out_src.crs),
                    'bounds': list(out_src.bounds),
                    'shape': [out_src.height, out_src.width],
                    'band_count': out_src.count,
                    'dtype': str(out_src.dtypes[0]),
                }
                logger.info(f"   Output CRS: {raster_metadata['crs']}")
                logger.info(f"   Output bounds: {raster_metadata['bounds']}")

        # Compute checksum from disk file
        if compute_checksum:
            logger.info(f"🔄 DISK STEP D: Computing checksum from disk...")
            from utils.checksum import compute_multihash
            checksum_start = time.time()
            with open(temp_output_path, 'rb') as f:
                file_checksum = compute_multihash(f.read(), log_performance=False)
            checksum_duration = time.time() - checksum_start
            logger.info(f"   Checksum: {file_checksum[:24]}... ({checksum_duration*1000:.0f}ms)")

        # STEP E: Upload from mounted filesystem to blob (streaming - low memory)
        logger.info(f"🔄 DISK STEP E: Streaming COG from mount to blob...")
        upload_result = silver_repo.stream_mount_to_blob(
            container=output_blob_container,
            blob_path=output_blob_path,
            mount_path=temp_output_path,
            content_type='image/tiff'
        )

        if not upload_result.get('success'):
            raise RuntimeError(f"stream_mount_to_blob failed: {upload_result.get('error')}")

        logger.info(f"   Uploaded {output_size_mb:.2f}MB in {upload_result.get('duration_seconds', 0):.1f}s")

        return {
            'success': True,
            'cog_bytes_on_disk': output_size_bytes,
            'input_size_bytes': input_size_bytes,
            'input_path': temp_input_path,
            'output_path': temp_output_path,
            'download_result': download_result,
            'upload_result': upload_result,
            'raster_metadata': raster_metadata,
            'file_checksum': file_checksum,
            'cog_duration_seconds': cog_duration,
            'reprojection_performed': reprojection_performed,
            'target_crs': target_crs,
        }

    except Exception as e:
        logger.error(f"❌ DISK-BASED COG PROCESSING FAILED: {e}")
        return {
            'success': False,
            'error': str(e),
            'input_path': temp_input_path,
            'output_path': temp_output_path,
            'download_result': download_result,
            'upload_result': upload_result,
        }

    finally:
        # STEP F: Cleanup temp files
        # V0.8.1: Don't delete input if using local_source_path (caller manages cleanup)
        logger.info(f"🧹 DISK STEP F: Cleaning up temp files...")
        files_to_cleanup = [temp_output_path]  # Always cleanup output
        if not local_source_path:
            files_to_cleanup.append(temp_input_path)  # Only cleanup input if we downloaded it
        for temp_file in files_to_cleanup:
            try:
                if Path(temp_file).exists():
                    Path(temp_file).unlink()
                    logger.debug(f"   Deleted: {temp_file}")
            except Exception as cleanup_error:
                logger.warning(f"   Failed to delete {temp_file}: {cleanup_error}")


def create_cog(params: dict) -> dict:
    """
    Create Cloud Optimized GeoTIFF with optional reprojection.

    Stage 2 of raster processing pipeline. Performs:
    - Single-pass reprojection + COG creation (if CRS != target)
    - Auto-selects optimal compression based on raster type
    - Auto-selects optimal resampling methods
    - Downloads from bronze, creates COG, uploads to silver
    - Cleans up temporary files

    Args:
        params: Task parameters dict with:
            - container_name (str, REQUIRED): Container name for input raster
            - blob_name (str, REQUIRED): Blob path for input raster
            - source_crs (str, REQUIRED): CRS from validation stage
            - target_crs (str, optional): Target CRS (default: EPSG:4326)
            - raster_type (dict, optional): Full raster_type dict from validation stage
                Structure: {"detected_type": str, "optimal_cog_settings": {...}}
            - output_blob_name (str, REQUIRED): Silver container blob path for output COG
            - output_tier (str, optional): COG tier (visualization, analysis, archive) - default: analysis
            - compression (str, optional): User override for compression (DEPRECATED - use output_tier)
            - jpeg_quality (int, optional): JPEG quality (1-100)
            - overview_resampling (str, optional): User override
            - reproject_resampling (str, optional): User override
            - in_memory (bool, optional): Process in-memory (True) vs disk-based (False).
                If not specified, uses config.raster_cog_in_memory (default: True).
                In-memory is faster for small files (<1GB), disk-based is better for large files.

        Note: blob_url is generated internally using BlobRepository.get_blob_url_with_sas()
              with managed identity for secure access (2-hour validity)

    Returns:
        dict: {
            "success": bool,
            "result": {
                "cog_blob": str,           # ← Output COG path in silver container
                "cog_container": str,      # ← Silver container name
                "cog_tier": str,           # ← COG tier (visualization/analysis/archive)
                "storage_tier": str,       # ← Azure storage tier (hot/cool/archive)
                "source_blob": str,
                "source_container": str,
                "reprojection_performed": bool,
                "source_crs": str,
                "target_crs": str,
                "bounds_4326": list,       # ← [minx, miny, maxx, maxy]
                "shape": list,             # ← [height, width]
                "size_mb": float,
                "compression": str,
                "jpeg_quality": int,
                "tile_size": list,
                "overview_levels": list,
                "overview_resampling": str,
                "reproject_resampling": str,
                "raster_type": str,
                "processing_time_seconds": float,
                "tier_profile": {...}
            },
            "error": str (if success=False),
            "message": str (if success=False),
            "traceback": str (if success=False)
        }

    NOTE: Downstream consumers (Stage 3+) rely on result["cog_blob"] field.
    """
    import traceback

    # STEP 0: Initialize logger
    logger = None
    task_id = params.get('_task_id')  # For checkpoint context tracking (20 DEC 2025)
    try:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "create_cog")
        logger.info("✅ STEP 0: Logger initialized successfully")
    except Exception as e:
        return {
            "success": False,
            "error": "LOGGER_INIT_FAILED",
            "message": f"Failed to initialize logger: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 1: Extract and validate parameters
    try:
        logger.info("🔄 STEP 1: Extracting and validating parameters...")

        container_name = params.get('container_name')
        blob_name = params.get('blob_name')
        source_crs = params.get('source_crs')
        target_crs = params.get('target_crs', 'EPSG:4326')
        raster_type = params.get('raster_type', {}).get('detected_type', 'unknown')
        optimal_settings = params.get('raster_type', {}).get('optimal_cog_settings', {})

        # V0.8.1: Support local source path for mount-based workflow
        local_source_path = params.get('_local_source_path')

        # Get COG tier configuration from config
        from config import get_config, CogTier, COG_TIER_PROFILES
        config_obj = get_config()

        # Get output_tier parameter (default to analysis)
        output_tier_str = params.get('output_tier', 'analysis')
        try:
            output_tier = CogTier(output_tier_str)
        except ValueError:
            logger.warning(f"⚠️ Invalid output_tier '{output_tier_str}', defaulting to 'analysis'")
            output_tier = CogTier.ANALYSIS

        # Get tier profile
        tier_profile = COG_TIER_PROFILES[output_tier]
        logger.info(f"   Using tier profile: {output_tier.value}")
        logger.info(f"   Profile: compression={tier_profile.compression}, storage_tier={tier_profile.storage_tier.value}")

        # Check tier compatibility with raster type
        raster_metadata = params.get('raster_type', {})
        band_count = raster_metadata.get('band_count', 3)
        data_type = raster_metadata.get('data_type', 'uint8')

        if not tier_profile.is_compatible(band_count, data_type):
            logger.warning(f"⚠️ Tier '{output_tier.value}' not compatible with {band_count} bands, {data_type}")
            logger.warning(f"   Falling back to 'analysis' tier (DEFLATE - universal)")
            output_tier = CogTier.ANALYSIS
            tier_profile = COG_TIER_PROFILES[output_tier]

        # Use tier profile settings (allow user overrides)
        compression = params.get('compression') or tier_profile.compression.lower()
        jpeg_quality = params.get('jpeg_quality') or tier_profile.quality or 85
        overview_resampling = params.get('overview_resampling') or optimal_settings.get('overview_resampling', 'cubic')
        reproject_resampling = params.get('reproject_resampling') or optimal_settings.get('reproject_resampling', 'cubic')

        output_blob_name = params.get('output_blob_name')

        # Add tier suffix to output blob name
        # Example: sample.tif → sample_analysis.tif
        if output_blob_name and not any(tier.value in output_blob_name for tier in CogTier):
            base_name = output_blob_name.rsplit('.', 1)[0] if '.' in output_blob_name else output_blob_name
            extension = output_blob_name.rsplit('.', 1)[1] if '.' in output_blob_name else 'tif'
            output_blob_name = f"{base_name}_{output_tier.value}.{extension}"
            logger.info(f"   Added tier suffix to output: {output_blob_name}")

        # Validate required parameters
        # V0.8.1: container_name and blob_name are optional when _local_source_path is provided
        if local_source_path:
            # Local source mode - only need source_crs and output_blob_name
            if not all([source_crs, output_blob_name]):
                missing = []
                if not source_crs: missing.append('source_crs')
                if not output_blob_name: missing.append('output_blob_name')
                logger.error(f"❌ STEP 1 FAILED: Missing required parameters: {', '.join(missing)}")
                return {
                    "success": False,
                    "error": "PARAMETER_ERROR",
                    "message": f"Missing required parameters: {', '.join(missing)}"
                }
            logger.info(f"✅ STEP 1: Parameters validated (local source mode)")
            logger.info(f"   Local source: {local_source_path}")
            blob_url = None  # Not used in local source mode
        else:
            # Standard blob mode - require all parameters
            if not all([container_name, blob_name, source_crs, output_blob_name]):
                missing = []
                if not container_name: missing.append('container_name')
                if not blob_name: missing.append('blob_name')
                if not source_crs: missing.append('source_crs')
                if not output_blob_name: missing.append('output_blob_name')

                logger.error(f"❌ STEP 1 FAILED: Missing required parameters: {', '.join(missing)}")
                return {
                    "success": False,
                    "error": "PARAMETER_ERROR",
                    "message": f"Missing required parameters: {', '.join(missing)}"
                }

            # Generate blob URL with SAS token using managed identity
            # Detect zone from container name (silver-* containers are in silver zone)
            logger.info("🔄 Generating SAS URL for input blob using managed identity...")
            from infrastructure.blob import BlobRepository
            is_silver_container = container_name.startswith('silver-')
            source_zone = "silver" if is_silver_container else "bronze"
            blob_repo = BlobRepository.for_zone(source_zone)
            blob_url = blob_repo.get_blob_url_with_sas(container_name, blob_name, hours=2)
            logger.info(f"   ✅ SAS URL generated (valid for 2 hours)")

            logger.info(f"✅ STEP 1: Parameters validated - blob={blob_name}, container={container_name}")
        logger.info(f"   Type: {raster_type}, Tier: {output_tier.value}, Compression: {compression}, CRS: {source_crs} → {target_crs}")

    except Exception as e:
        logger.error(f"❌ STEP 1 FAILED: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "PARAMETER_ERROR",
            "message": f"Failed to extract parameters: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 2: Lazy import dependencies
    try:
        logger.info("🔄 STEP 2: Lazy importing rasterio and rio-cogeo dependencies...")
        rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()
        logger.info("✅ STEP 2: Dependencies imported successfully (rasterio, rio-cogeo)")
    except ImportError as e:
        logger.error(f"❌ STEP 2 FAILED: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "DEPENDENCY_LOAD_FAILED",
            "message": f"Failed to import rio-cogeo dependencies: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 2b: Import blob storage
    try:
        logger.info("🔄 STEP 2b: Importing BlobRepository...")
        from infrastructure.blob import BlobRepository
        logger.info("✅ STEP 2b: BlobRepository imported successfully")
    except ImportError as e:
        logger.error(f"❌ STEP 2b FAILED: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "DEPENDENCY_LOAD_FAILED",
            "message": f"Failed to import BlobRepository: {e}",
            "traceback": traceback.format_exc()
        }

    # STEP 2c: Setup OOM evidence - persist memory snapshots to task metadata
    # If OOM occurs during heavy operations, last snapshot will be in DB
    task_repo = None
    try:
        from infrastructure import RepositoryFactory
        from util_logger import snapshot_memory_to_task
        task_repo = RepositoryFactory.create_task_repository()
        logger.info("✅ STEP 2c: Task repository initialized for OOM evidence")

        # Baseline snapshot - captures memory before any heavy operations
        snapshot_memory_to_task(
            task_id=task_id,
            checkpoint_name="baseline",
            logger=logger,
            task_repo=task_repo,
            blob_name=blob_name,
            container_name=container_name
        )
    except Exception as e:
        logger.warning(f"⚠️ STEP 2c: OOM evidence setup failed (non-fatal): {e}")
        # Continue without OOM evidence - core functionality still works

    # ==========================================================================
    # PROCESSING PATH SELECTION (25 JAN 2026)
    # ==========================================================================
    # Check if we should use disk-based processing (Docker with Azure Files mount)
    # or in-memory processing (Function App / small files).
    # ==========================================================================

    from config import get_config
    config_obj = get_config()
    silver_container = config_obj.storage.silver.get_container('cogs')

    # Get COG profile and settings early (needed for both paths)
    rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()

    try:
        cog_profile = cog_profiles.get(compression)
    except KeyError:
        logger.warning(f"⚠️ Unknown compression '{compression}', falling back to deflate")
        cog_profile = cog_profiles.get('deflate')

    # Set interleave based on compression type
    if compression in ("jpeg", "webp"):
        cog_profile["INTERLEAVE"] = "PIXEL"
    else:
        cog_profile["INTERLEAVE"] = "BAND"

    if compression == "jpeg":
        cog_profile["QUALITY"] = jpeg_quality

    # Get resampling settings
    try:
        overview_resampling_enum = getattr(Resampling, overview_resampling)
    except AttributeError:
        overview_resampling_enum = Resampling.cubic
    overview_resampling_name = overview_resampling_enum.name if hasattr(overview_resampling_enum, 'name') else overview_resampling

    # Build cog_config for reprojection (if needed - determined later)
    cog_config = {}

    # ==========================================================================
    # DISK-BASED PROCESSING PATH (when ETL mount enabled)
    # ==========================================================================
    if config_obj.raster.use_etl_mount:
        mount_path = config_obj.raster.etl_mount_path
        logger.info("=" * 60)
        logger.info("📁 DISK-BASED PROCESSING MODE (ETL Mount Enabled)")
        logger.info(f"   Mount path: {mount_path}")
        logger.info(f"   Memory impact: ~100MB (streaming chunks)")
        logger.info("=" * 60)

        # Call disk-based processing helper
        # V0.8.1: Pass local_source_path if provided (skips blob download)
        disk_result = _process_cog_disk_based(
            input_blob_container=container_name,
            input_blob_path=blob_name,
            output_blob_container=silver_container,
            output_blob_path=output_blob_name,
            mount_path=mount_path,
            task_id=task_id,
            cog_profile=cog_profile,
            cog_config=cog_config,
            overview_resampling=overview_resampling_name,
            in_memory=False,  # Always False for disk-based
            logger=logger,
            compute_checksum=True,
            target_crs=target_crs,
            reproject_resampling=reproject_resampling,
            local_source_path=local_source_path
        )

        if not disk_result.get('success'):
            logger.error(f"❌ Disk-based COG creation failed: {disk_result.get('error')}")
            return {
                "success": False,
                "error": disk_result.get('error', 'Unknown error in disk-based processing')
            }

        # Extract results
        output_size_bytes = disk_result.get('cog_bytes_on_disk', 0)
        output_size_mb = output_size_bytes / (1024 * 1024)
        input_size_bytes = disk_result.get('input_size_bytes', 0)
        input_size_mb = input_size_bytes / (1024 * 1024)
        file_checksum = disk_result.get('file_checksum')
        raster_metadata = disk_result.get('raster_metadata', {})
        cog_duration = disk_result.get('cog_duration_seconds', 0)

        logger.info("🎉 DISK-BASED COG CREATION COMPLETE")
        logger.info(f"   Input: {input_size_mb:.2f}MB → Output: {output_size_mb:.2f}MB")
        logger.info(f"   Processing time: {cog_duration:.1f}s")

        # Build typed result using Pydantic models (F7.21)
        tier_profile_info = TierProfileInfo(
            tier=output_tier.value,
            compression=tier_profile.compression,
            storage_tier=tier_profile.storage_tier.value,
            use_case=tier_profile.use_case,
            description=tier_profile.description
        )

        # Get reprojection status from disk_result (26 JAN 2026 - Bug fix)
        disk_reprojection_performed = disk_result.get('reprojection_performed', False)

        # BUG-007 FIX (27 JAN 2026): Handle local source mode where blob_name/container_name are None
        # When _local_source_path is provided, derive source info from the local path
        if local_source_path and not blob_name:
            # Extract blob name from local source path (e.g., /mounts/etl-temp/tile_r0_c0.tif -> tile_r0_c0.tif)
            from pathlib import Path as PathLib
            source_blob_name = PathLib(local_source_path).name
            source_container_name = "local-mount"  # Marker for local source mode
        else:
            source_blob_name = blob_name
            source_container_name = container_name

        cog_data = COGCreationData(
            cog_blob=output_blob_name,
            cog_container=silver_container,
            cog_tier=output_tier.value,
            storage_tier=tier_profile.storage_tier.value,
            source_blob=source_blob_name,
            source_container=source_container_name,
            reprojection_performed=disk_reprojection_performed,
            source_crs=raster_metadata.get('crs', str(source_crs)),
            target_crs=disk_result.get('target_crs', str(target_crs)),
            bounds_4326=raster_metadata.get('bounds'),
            shape=raster_metadata.get('shape', []),
            size_mb=round(output_size_mb, 2),
            compression=compression,
            jpeg_quality=jpeg_quality if compression == "jpeg" else None,
            tile_size=[512, 512],
            overview_levels=[],  # Not captured in disk path currently
            overview_resampling=overview_resampling,
            reproject_resampling=reproject_resampling if disk_reprojection_performed else None,
            raster_type=raster_metadata if raster_metadata else {"detected_type": raster_type},
            processing_time_seconds=round(cog_duration, 2),
            tier_profile=tier_profile_info,
            file_checksum=file_checksum,
            file_size=output_size_bytes,
            blob_version_id=None,  # Not captured in stream upload
            processing_mode="disk_based"
        )

        result = COGCreationResult(success=True, result=cog_data)
        return result.model_dump()

    # ==========================================================================
    # IN-MEMORY PROCESSING PATH (original path for Function App / small files)
    # ==========================================================================
    logger.info("=" * 60)
    logger.info("💾 IN-MEMORY PROCESSING MODE")
    logger.info("   Memory impact: ~2-3x file size")
    logger.info("=" * 60)

    # STEP 3: Setup - COG profile already configured above
    temp_dir = None
    local_output = None

    # Wrap entire COG creation in try block (no finally cleanup needed - MemoryFile handles it)
    try:
        # STEP 3: Download input tile and open with MemoryFile (in-memory processing)
        logger.info("🔄 STEP 3: Downloading input tile to memory...")

        # Download input tile bytes - detect zone from container name
        # Silver containers (silver-cogs, silver-tiles) are in silver zone
        # All other containers are in bronze zone
        from infrastructure.blob import BlobRepository
        is_silver_container = container_name.startswith('silver-')
        source_zone = "silver" if is_silver_container else "bronze"
        blob_repo = BlobRepository.for_zone(source_zone)
        logger.debug(f"   Using {source_zone} zone for container: {container_name}")

        try:
            download_start = time.time()
            input_blob_bytes = blob_repo.read_blob(
                container=container_name,
                blob_path=blob_name
            )
            download_duration = time.time() - download_start
            input_size_mb = len(input_blob_bytes) / (1024 * 1024)
            logger.info(f"   Downloaded input tile: {input_size_mb:.2f} MB")

            # Memory checkpoint 1 (DEBUG_MODE only)
            from util_logger import log_memory_checkpoint, log_io_throughput
            log_memory_checkpoint(logger, "After blob download", context_id=task_id, input_size_mb=input_size_mb)

            # I/O throughput tracking (25 JAN 2026)
            log_io_throughput(
                logger, "download",
                bytes_transferred=len(input_blob_bytes),
                duration_seconds=download_duration,
                context_id=task_id,
                source_path=f"{container_name}/{blob_name}"
            )
        except Exception as e:
            logger.error(f"❌ STEP 3 FAILED: Cannot download input tile from {container_name}/{blob_name}")
            logger.error(f"   Error: {e}")
            raise

        # COG profile and resampling already configured above
        logger.info(f"   Using COG profile: {compression}")
        logger.info(f"   Interleave: {'PIXEL' if compression in ('jpeg', 'webp') else 'BAND'}")
        if compression == "jpeg":
            logger.info(f"   JPEG quality: {jpeg_quality}")

        # Get in_memory setting for this path (in-memory path, but can still use disk for intermediates)
        in_memory_param = params.get('in_memory')
        if in_memory_param is not None:
            in_memory = in_memory_param
            logger.info(f"   Using user-specified in_memory={in_memory}")
        else:
            in_memory = config_obj.raster_cog_in_memory
            logger.info(f"   Using config default in_memory={in_memory}")

        logger.info(f"✅ STEP 3: COG profile configured")
        logger.info(f"   Processing mode: in-memory (RAM)")

        # STEP 4: Open input with MemoryFile and create COG with MemoryFile output
        logger.info("🔄 STEP 4: Opening input raster with MemoryFile...")

        from rasterio.io import MemoryFile

        start_time = datetime.now(timezone.utc)

        # Open input bytes with MemoryFile
        with MemoryFile(input_blob_bytes) as input_memfile:
            # Memory checkpoint 2 (DEBUG_MODE only)
            from util_logger import log_memory_checkpoint
            log_memory_checkpoint(logger, "After opening MemoryFile", context_id=task_id)

            with input_memfile.open() as src:
                # Get source CRS from raster
                detected_source_crs = src.crs
                logger.info(f"   Source CRS from file: {detected_source_crs}")

                # Determine reprojection needs
                needs_reprojection = (str(detected_source_crs) != str(target_crs))

                # Configure reprojection if needed
                if needs_reprojection:
                    logger.info(f"   Reprojection needed: {detected_source_crs} → {target_crs}")
                    config = {
                        "dst_crs": target_crs,
                        "resampling": getattr(Resampling, reproject_resampling),
                    }
                    logger.info(f"   Reprojection resampling: {reproject_resampling}")
                else:
                    logger.info(f"   No reprojection needed (already {target_crs})")
                    config = {}

                logger.info(f"✅ STEP 4: CRS check complete")

                # STEP 5: Create COG with MemoryFile output
                logger.info("🔄 STEP 5: Creating COG with cog_translate() in memory...")
                logger.info(f"   Compression: {compression}, Overview resampling: {overview_resampling}")

                # rio-cogeo expects string name, not enum object
                overview_resampling_name = overview_resampling_enum.name if hasattr(overview_resampling_enum, 'name') else overview_resampling
                logger.info(f"   Overview resampling (for cog_translate): {overview_resampling_name}")

                # Memory checkpoint 3 (DEBUG_MODE only)
                from util_logger import log_memory_checkpoint
                log_memory_checkpoint(logger, "Before cog_translate",
                                      context_id=task_id,
                                      in_memory=in_memory,
                                      compression=compression)

                # CRITICAL: Persist memory state to task metadata BEFORE cog_translate
                # This is the most likely OOM point - if we crash here, this evidence survives
                if task_repo and task_id:
                    try:
                        from util_logger import snapshot_memory_to_task
                        snapshot_memory_to_task(
                            task_id=task_id,
                            checkpoint_name="pre_cog_translate",
                            logger=logger,
                            task_repo=task_repo,
                            in_memory=in_memory,
                            compression=compression,
                            input_size_mb=len(input_blob_bytes) / (1024 * 1024)
                        )
                    except Exception as snap_error:
                        logger.warning(f"⚠️ Pre-cog_translate snapshot failed (non-fatal): {snap_error}")

                # ================================================================
                # PULSE DISABLED (2 DEC 2025) - Token expiration issues
                # ================================================================
                # When re-enabling pulse:
                # 1. Uncomment _pulse_fn injection in core/machine.py
                # 2. Uncomment validation and PulseWrapper below
                # See PulseWrapper class above for implementation details
                # ================================================================
                # task_id = params.get('_task_id')
                # pulse_fn = params.get('_pulse_fn')
                # if not task_id:
                #     raise ContractViolationError(...)
                # if not pulse_fn:
                #     raise ContractViolationError(...)
                # logger.info(f"💓 Pulse enabled for task {task_id[:8]}... (30s interval)")

                # Create output MemoryFile for COG
                with MemoryFile() as output_memfile:
                    try:
                        # cog_translate can accept a rasterio dataset directly (not just path string)
                        # and writes to MemoryFile's internal /vsimem/ path
                        # NOTE: PulseWrapper disabled - see comment above
                        # with PulseWrapper(task_id=task_id, pulse_fn=pulse_fn, ...):
                        cog_translate(
                            src,                        # Input rasterio dataset
                            output_memfile.name,        # Output to MemoryFile's internal /vsimem/ path
                            cog_profile,
                            config=config,
                            overview_level=None,        # Auto-calculate optimal levels
                            overview_resampling=overview_resampling_name,
                            in_memory=in_memory,
                            quiet=False,
                        )
                    except Exception as e:
                        logger.error(f"❌ STEP 5 FAILED: cog_translate() failed")
                        logger.error(f"   Error: {e}")
                        raise

                    elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                    logger.info(f"✅ STEP 5: COG created successfully in memory")
                    logger.info(f"   Processing time: {elapsed_time:.2f}s")

                    # Memory checkpoint 4 (DEBUG_MODE only)
                    from util_logger import log_memory_checkpoint, log_io_throughput
                    log_memory_checkpoint(logger, "After cog_translate",
                                          context_id=task_id,
                                          processing_time_seconds=elapsed_time)

                    # I/O throughput for COG creation (25 JAN 2026)
                    # Note: output_size not yet known, logged after reading cog_bytes
                    cog_create_duration = elapsed_time

                    # Final snapshot - captures peak memory after cog_translate success
                    if task_repo and task_id:
                        try:
                            from util_logger import snapshot_memory_to_task, get_peak_memory_mb
                            snapshot_memory_to_task(
                                task_id=task_id,
                                checkpoint_name="post_cog_translate",
                                logger=logger,
                                task_repo=task_repo,
                                processing_time_seconds=elapsed_time,
                                peak_memory_mb=get_peak_memory_mb()
                            )
                        except Exception as snap_error:
                            logger.warning(f"⚠️ Post-cog_translate snapshot failed (non-fatal): {snap_error}")

                    # Read metadata from COG
                    with output_memfile.open() as dst:
                        output_shape = dst.shape
                        output_bounds = dst.bounds
                        output_crs = dst.crs
                        overviews = dst.overviews(1) if dst.count > 0 else []

                    logger.info(f"   Shape: {output_shape}, Overview levels: {len(overviews)}")

                    # STEP 6: Get COG bytes from MemoryFile and upload to Azure Blob Storage
                    logger.info("🔄 STEP 6: Reading COG from memory and uploading to blob storage...")

                    try:
                        # Read bytes from MemoryFile (replaces read_vsimem_file())
                        cog_bytes = output_memfile.read()
                        output_size_mb = len(cog_bytes) / (1024 * 1024)
                        logger.info(f"   Read COG from memory: {output_size_mb:.2f} MB")

                        # Memory checkpoint 5 (DEBUG_MODE only)
                        from util_logger import log_memory_checkpoint
                        log_memory_checkpoint(logger, "After reading COG bytes",
                                              context_id=task_id,
                                              output_size_mb=output_size_mb)

                        # I/O throughput for COG creation (25 JAN 2026)
                        # Now we have output size, log COG creation rate
                        log_io_throughput(
                            logger, "cog_create",
                            bytes_transferred=len(cog_bytes),
                            duration_seconds=cog_create_duration,
                            context_id=task_id,
                            source_path=f"{container_name}/{blob_name}",
                            dest_path=f"{silver_container}/{output_blob_name}",
                            use_etl_mount=config_obj.raster.use_etl_mount,
                            mount_path=config_obj.raster.etl_mount_path if config_obj.raster.use_etl_mount else None,
                            compression=compression,
                            compression_ratio=round(input_size_mb / output_size_mb, 2) if output_size_mb > 0 else None
                        )
                    except Exception as e:
                        logger.error(f"❌ STEP 6 FAILED: Cannot read COG from MemoryFile")
                        logger.error(f"   Error: {e}")
                        raise

                    try:
                        # Upload bytes directly to silver zone (no BytesIO wrapper needed)
                        # compute_checksum=True computes STAC-compliant SHA-256 multihash
                        upload_start = time.time()
                        silver_repo = BlobRepository.for_zone("silver")  # Output COGs go to silver zone
                        upload_result = silver_repo.write_blob(
                            container=silver_container,
                            blob_path=output_blob_name,
                            data=cog_bytes,
                            content_type='image/tiff',
                            overwrite=True,
                            compute_checksum=True
                        )
                        upload_duration = time.time() - upload_start
                        file_checksum = upload_result.get('file_checksum')
                        checksum_time_ms = upload_result.get('checksum_time_ms', 0)
                        blob_version_id = upload_result.get('blob_version_id')  # None if versioning not enabled
                        logger.info(f"   Uploaded COG to {silver_container}/{output_blob_name}")
                        logger.info(f"   Checksum: {file_checksum[:20]}... ({checksum_time_ms}ms)")
                        if blob_version_id:
                            logger.info(f"   Blob version ID: {blob_version_id}")

                        # I/O throughput for upload (25 JAN 2026)
                        log_io_throughput(
                            logger, "upload",
                            bytes_transferred=len(cog_bytes),
                            duration_seconds=upload_duration,
                            context_id=task_id,
                            dest_path=f"{silver_container}/{output_blob_name}",
                            checksum_time_ms=checksum_time_ms
                        )
                    except Exception as e:
                        logger.error(f"❌ STEP 6 FAILED: Cannot upload COG to blob storage")
                        logger.error(f"   Error: {e}")
                        raise

                    logger.info(f"✅ STEP 6: COG uploaded successfully")
                    logger.info(f"   Size: {output_size_mb:.1f} MB, Overview levels: {len(overviews)}")

                    # Memory checkpoint 6 (DEBUG_MODE only)
                    from util_logger import log_memory_checkpoint
                    log_memory_checkpoint(logger, "After upload (cleanup)", context_id=task_id)

                    # No STEP 7 needed - MemoryFile context managers handle cleanup automatically.

        # Build typed result using Pydantic models (F7.21)
        logger.info("🎉 COG creation pipeline completed successfully")

        tier_profile_info = TierProfileInfo(
            tier=output_tier.value,
            compression=tier_profile.compression,
            storage_tier=tier_profile.storage_tier.value,
            use_case=tier_profile.use_case,
            description=tier_profile.description
        )

        cog_data = COGCreationData(
            cog_blob=output_blob_name,
            cog_container=silver_container,
            cog_tier=output_tier.value,
            storage_tier=tier_profile.storage_tier.value,
            source_blob=blob_name,
            source_container=container_name,
            reprojection_performed=needs_reprojection,
            source_crs=str(source_crs),
            target_crs=str(target_crs),
            bounds_4326=list(output_bounds) if output_crs == target_crs else None,
            shape=list(output_shape),
            size_mb=round(output_size_mb, 2),
            compression=compression,
            jpeg_quality=jpeg_quality if compression == "jpeg" else None,
            tile_size=[512, 512],  # Default from rio-cogeo
            overview_levels=overviews,
            overview_resampling=overview_resampling,
            reproject_resampling=reproject_resampling if needs_reprojection else None,
            # Return full raster_type dict for downstream STAC metadata (04 JAN 2026)
            # Contains: detected_type, band_count, data_type - needed for TiTiler bidx params
            raster_type=raster_metadata if raster_metadata else {"detected_type": raster_type},
            processing_time_seconds=round(elapsed_time, 2),
            tier_profile=tier_profile_info,
            # STAC file extension compliant checksum (21 JAN 2026)
            file_checksum=file_checksum,
            file_size=len(cog_bytes),
            # Azure Blob Storage version ID (21 JAN 2026)
            blob_version_id=blob_version_id,
            processing_mode="in_memory"
        )

        result = COGCreationResult(success=True, result=cog_data)
        return result.model_dump()

    except Exception as e:
        # Catch all errors from STEPs 3-6
        logger.error(f"❌ COG CREATION FAILED: {e}\n{traceback.format_exc()}")

        # Determine which step failed based on what variables are defined
        if 'cog_profile' not in locals():
            error_code = "SETUP_FAILED"
            step_info = "STEP 3 (setup)"
        elif 'config' not in locals():
            error_code = "CRS_CHECK_FAILED"
            step_info = "STEP 4 (CRS check)"
        elif 'output_size_mb' not in locals():
            error_code = "COG_TRANSLATE_FAILED"
            step_info = "STEP 5 (cog_translate)"
        else:
            error_code = "COG_CREATION_FAILED"
            step_info = "Unknown step"

        # Use typed result for errors too (F7.21)
        error_result = COGCreationResult(
            success=False,
            error=error_code,
            message=f"{step_info} failed: {e}",
            traceback=traceback.format_exc()
        )
        return error_result.model_dump()

    # No finally block needed - MemoryFile context managers handle all cleanup automatically.
