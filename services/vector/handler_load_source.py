# ============================================================================
# CLAUDE CONTEXT - VECTOR LOAD SOURCE ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Stream blob to ETL mount, convert to GeoParquet
# PURPOSE: Stream a blob from bronze storage to the ETL mount, convert
#          format-specific files to GeoDataFrame, persist as GeoParquet for
#          downstream consumption.
# LAST_REVIEWED: 19 MAR 2026
# EXPORTS: vector_load_source
# DEPENDENCIES: infrastructure.blob, services.vector.core, pyogrio, geopandas
# ============================================================================
"""
Vector Load Source — atomic handler for DAG workflows.

Streams a source file from Azure Blob Storage (bronze zone) to the ETL mount,
detects and validates the file format, converts to a GeoDataFrame, and writes
a GeoParquet intermediate file for downstream handlers.

Extracted from: handler_vector_docker_complete (Phase 0 mount setup L162-207,
                Phase 1 _load_and_validate_source L421-602)

Supported formats: csv, geojson, json, gpkg, kml, kmz, shp, zip
"""

import logging
import os
import traceback
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Formats recognised by this handler (matches get_converter_map() keys)
SUPPORTED_FORMATS = frozenset({'csv', 'geojson', 'json', 'gpkg', 'kml', 'kmz', 'shp', 'zip'})

# ZIP-like formats that need an on-mount extraction directory
_ZIP_FORMATS = frozenset({'shp', 'zip', 'kmz'})

# QGIS metadata layer detection — overlap >= 2 triggers rejection (H1-B9)
_QGIS_SIGNATURE_COLUMNS = frozenset({
    'geometry_generator',
    'label_expression',
    'stylename',
    'styleqml',
    'stylesld',
    'useasdefault',
    'f_table_catalog',
    'f_geometry_column',
})


# =============================================================================
# GPKG HELPERS
# =============================================================================

def _validate_gpkg_layer(
    blob_url: str,
    blob_name: str,
    requested_layer: Optional[str],
) -> tuple:
    """
    Validate GPKG layer selection and spatial geometry.

    Returns (selected_layer, spatial_layers) where spatial_layers is a list of
    (name, geom_type) tuples for layers that have geometry.

    Raises ValueError on:
    - requested_layer not present in the file (H1-B7)
    - selected layer is non-spatial / attributes-only (H1-B8)
    """
    import pyogrio

    available_layers = pyogrio.list_layers(blob_url)
    layer_names = [name for name, _ in available_layers]
    spatial_layers = [(name, gtype) for name, gtype in available_layers if gtype is not None]

    # H1-B7: Validate requested layer exists
    if requested_layer and requested_layer not in layer_names:
        raise ValueError(
            f"Layer '{requested_layer}' not found in GeoPackage '{blob_name}'. "
            f"Available layers: {layer_names}"
        )

    selected_layer = requested_layer or layer_names[0]

    # H1-B8: Reject non-spatial (attributes-only) layers
    layer_geom_types = {name: gtype for name, gtype in available_layers}
    if layer_geom_types.get(selected_layer) is None:
        spatial_names = [name for name, _ in spatial_layers]
        raise ValueError(
            f"Layer '{selected_layer}' is a non-spatial (attributes-only) table, "
            f"not a geospatial layer. Cannot upload to PostGIS. "
            f"Spatial layers in this file: {spatial_names}"
        )

    return selected_layer, spatial_layers


def _check_qgis_metadata_layer(gdf, blob_name: str, spatial_layers: list) -> None:
    """
    Detect QGIS project metadata layers masquerading as spatial data (H1-B9).

    spatial_layers MUST be passed explicitly — do not rely on closure scope (S-2).

    Raises ValueError if the loaded GeoDataFrame looks like QGIS metadata.
    """
    gdf_cols_lower = {c.lower() for c in gdf.columns if c != 'geometry'}
    qgis_overlap = gdf_cols_lower & _QGIS_SIGNATURE_COLUMNS
    if len(qgis_overlap) >= 2:
        spatial_hint = ""
        try:
            spatial_names = [
                n for n, g in spatial_layers
                if g is not None and n.lower() not in ('dashboard', 'chart', 'layer_styles')
            ]
            if spatial_names:
                spatial_hint = f" Data layers in this file: {spatial_names}"
        except Exception:
            pass
        raise ValueError(
            f"Layer appears to be QGIS project metadata, not geospatial data. "
            f"Detected QGIS columns: {sorted(qgis_overlap)}. "
            f"Dashboard/chart/style layers contain rendering definitions, "
            f"not uploadable features.{spatial_hint}"
        )


# =============================================================================
# HANDLER ENTRY POINT
# =============================================================================

def vector_load_source(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Stream blob from bronze storage to ETL mount and convert to GeoParquet.

    Params:
        blob_name (str, required): Blob path within the container.
        container_name (str, required): Azure blob container name.
        file_extension (str, required): Normalised lowercase file extension.
        job_id (str, required): Workflow job identifier.
        processing_options (dict, optional): Format-specific options:
            lat_name   - CSV latitude column name
            lon_name   - CSV longitude column name
            wkt_column - CSV WKT geometry column name
            layer_name - GPKG layer to load
        _run_id (str, required): System-injected DAG run identifier.
        _node_name (str, required): System-injected DAG node name.

    Returns:
        {"success": True, "result": {...}} or
        {"success": False, "error": "...", "error_type": "..."}
    """
    # -------------------------------------------------------------------------
    # PARAM VALIDATION (fail immediately, no I/O)
    # -------------------------------------------------------------------------
    _run_id = params.get('_run_id')
    if not _run_id:
        return {
            "success": False,
            "error": "_run_id is required",
            "error_type": "ValidationError",
        }

    _node_name = params.get('_node_name')
    if not _node_name:
        return {
            "success": False,
            "error": "_node_name is required",
            "error_type": "ValidationError",
        }

    job_id = params.get('job_id')
    if not job_id:
        return {
            "success": False,
            "error": "job_id is required",
            "error_type": "ValidationError",
        }

    blob_name = params.get('blob_name')
    if not blob_name:
        return {
            "success": False,
            "error": "blob_name is required",
            "error_type": "ValidationError",
        }

    container_name = params.get('container_name')
    if not container_name:
        return {
            "success": False,
            "error": "container_name is required",
            "error_type": "ValidationError",
        }

    raw_extension = params.get('file_extension')
    if not raw_extension:
        return {
            "success": False,
            "error": "file_extension is required",
            "error_type": "ValidationError",
        }

    file_extension = raw_extension.lower().lstrip('.')

    # N-5: Unsupported format check
    if file_extension not in SUPPORTED_FORMATS:
        return {
            "success": False,
            "error": (
                f"Unsupported file format: '{file_extension}'. "
                f"Supported formats: {sorted(SUPPORTED_FORMATS)}"
            ),
            "error_type": "UnsupportedFormatError",
        }

    processing_options = params.get('processing_options') or {}

    log_prefix = f"[{job_id[:8]}][{_node_name}]"
    logger.info(f"{log_prefix} vector_load_source starting: {blob_name} ({file_extension})")

    try:
        # ---------------------------------------------------------------------
        # H1-B1: Create mount directories
        # ---------------------------------------------------------------------
        from config import get_config
        _config = get_config()
        etl_mount_root = _config.docker.etl_mount_path if _config.docker and _config.docker.etl_mount_path else "/mnt/etl"
        mount_base = os.path.join(etl_mount_root, _run_id)
        source_dir = os.path.join(mount_base, "source")
        extract_dir = os.path.join(mount_base, "extract")

        try:
            os.makedirs(source_dir, exist_ok=True)
            os.makedirs(extract_dir, exist_ok=True)
        except Exception as mkdir_err:
            return {
                "success": False,
                "error": f"Failed to create ETL mount directories at {mount_base}: {mkdir_err}",
                "error_type": "MountUnavailableError",
            }

        # H1-B2: Mount writability probe
        test_file = os.path.join(source_dir, ".write-test")
        try:
            with open(test_file, "w") as fh:
                fh.write("ok")
            os.remove(test_file)
        except Exception as probe_err:
            return {
                "success": False,
                "error": f"ETL mount at {source_dir} is not writable: {probe_err}",
                "error_type": "MountUnavailableError",
            }

        # ---------------------------------------------------------------------
        # H1-B3: Stream blob to mount
        # ---------------------------------------------------------------------
        from infrastructure.blob import BlobRepository
        from azure.core.exceptions import ResourceNotFoundError

        blob_repo = BlobRepository.for_zone("bronze")
        dest_path = os.path.join(source_dir, os.path.basename(blob_name))

        logger.info(f"{log_prefix} Streaming {blob_name} to mount: {dest_path}")
        try:
            blob_repo.stream_blob_to_mount(
                container_name, blob_name, dest_path, chunk_size_mb=32
            )
        except ResourceNotFoundError:
            return {
                "success": False,
                "error": (
                    f"Blob not found: '{blob_name}' in container '{container_name}'"
                ),
                "error_type": "BlobNotFoundError",
            }
        except Exception as stream_err:
            return {
                "success": False,
                "error": f"Blob streaming failed for '{blob_name}': {stream_err}",
                "error_type": "BlobStreamError",
            }

        # H1-B4: Log file size after stream
        source_size_bytes = os.path.getsize(dest_path)
        logger.info(
            f"{log_prefix} Streamed to mount: {source_size_bytes / (1024 * 1024):.1f}MB "
            f"({dest_path})"
        )

        # ---------------------------------------------------------------------
        # Build converter params
        # H1-B5: CSV param merging — top-level processing_options override
        # H1-B6: GPKG layer name routing
        # ---------------------------------------------------------------------
        converter_params: Dict[str, Any] = {}

        if file_extension == 'csv':
            from services.vector.core import build_csv_converter_params
            # build_csv_converter_params expects a flat dict with lat_name etc.
            # at the top level. We forward processing_options as the "parameters"
            # argument so top-level keys are picked up correctly.
            converter_params = build_csv_converter_params(
                processing_options, converter_params
            )

        if file_extension == 'gpkg':
            layer_name = processing_options.get('layer_name')
            if layer_name:
                converter_params['layer_name'] = layer_name

        # H1-B7 / H1-B8: GPKG layer existence + spatial validation
        # Must happen BEFORE load so we have spatial_layers for H1-B9 (S-2).
        spatial_layers: list = []
        if file_extension == 'gpkg':
            requested_layer = converter_params.get('layer_name')
            try:
                blob_url = blob_repo.get_blob_url_with_sas(container_name, blob_name)
                _selected_layer, spatial_layers = _validate_gpkg_layer(
                    blob_url, blob_name, requested_layer
                )
            except ValueError as gpkg_val_err:
                return {
                    "success": False,
                    "error": str(gpkg_val_err),
                    "error_type": "ValidationError",
                }

        # H1-B10: ZIP-like formats need extract_dir on the mount
        if file_extension in _ZIP_FORMATS:
            converter_params['extract_dir'] = extract_dir

        # H1-B12: Multi-file ZIP/KMZ rejection
        # ZIP archives must contain exactly ONE primary file (.shp or .kml).
        # Multi-file archives are a user error — reject immediately before
        # the expensive extraction/load step. Uses zipfile central directory
        # scan (reads ~10KB of metadata, not the full archive).
        if file_extension in ('zip', 'kmz'):
            import zipfile as _zf
            _scan_ext = '.shp' if file_extension == 'zip' else '.kml'
            _scan_label = 'shapefiles' if file_extension == 'zip' else 'KML files'
            try:
                with _zf.ZipFile(dest_path) as zf:
                    matches = [f for f in zf.namelist() if f.lower().endswith(_scan_ext)]
                if len(matches) > 1:
                    return {
                        "success": False,
                        "error": (
                            f"{'ZIP' if file_extension == 'zip' else 'KMZ'} contains "
                            f"{len(matches)} {_scan_label} — only one is allowed "
                            f"per submission. Found: "
                            f"{', '.join(sorted(matches)[:5])}"
                            f"{'... and more' if len(matches) > 5 else ''}. "
                            f"Split into separate files with one each."
                        ),
                        "error_type": f"Multi{'Shapefile' if file_extension == 'zip' else 'KML'}Error",
                    }
            except _zf.BadZipFile:
                pass  # Let the converter handle corrupt zips with its own error

        # ---------------------------------------------------------------------
        # Load via shared core function (mount path — no RAM copy)
        # ---------------------------------------------------------------------
        from services.vector.core import load_vector_source

        logger.info(f"{log_prefix} Loading {file_extension} from mount path")
        try:
            gdf, _load_info = load_vector_source(
                blob_name=blob_name,
                container_name=container_name,
                file_extension=file_extension,
                converter_params=converter_params,
                job_id=job_id,
                mount_source_path=dest_path,
            )
        except Exception as conv_err:
            return {
                "success": False,
                "error": f"Format conversion failed for '{blob_name}': {conv_err}",
                "error_type": "FormatConversionError",
            }

        # H1-B9: QGIS metadata layer detection (spatial_layers passed explicitly — S-2)
        if file_extension == 'gpkg':
            try:
                _check_qgis_metadata_layer(gdf, blob_name, spatial_layers)
            except ValueError as qgis_err:
                return {
                    "success": False,
                    "error": str(qgis_err),
                    "error_type": "ValidationError",
                }

        # H1-B11: Zero-feature guard
        if len(gdf) == 0:
            return {
                "success": False,
                "error": "Source file contains zero features.",
                "error_type": "EmptyFileError",
            }

        # ---------------------------------------------------------------------
        # Write GeoParquet intermediate file
        # ---------------------------------------------------------------------
        intermediate_path = os.path.join(source_dir, f"{_run_id}.parquet")
        logger.info(f"{log_prefix} Writing GeoParquet to {intermediate_path}")
        gdf.to_parquet(intermediate_path, index=False)

        # H1-B12: Build result dict
        geometry_column = gdf.geometry.name
        attribute_columns = [c for c in gdf.columns if c != geometry_column]
        crs_raw = str(gdf.crs) if gdf.crs else None

        result = {
            "intermediate_path": intermediate_path,
            "row_count": len(gdf),
            "file_extension": file_extension,
            "source_size_bytes": source_size_bytes,
            "column_count": len(attribute_columns),
            "columns": attribute_columns,
            "geometry_column": geometry_column,
            "crs_raw": crs_raw,
            "source_file": blob_name,
        }

        logger.info(
            f"{log_prefix} vector_load_source complete: "
            f"{result['row_count']:,} features, "
            f"{result['column_count']} columns, "
            f"CRS={crs_raw}"
        )
        return {"success": True, "result": result}

    except Exception as exc:
        return {
            "success": False,
            "error": (
                f"Unexpected error in vector_load_source: {exc}\n"
                f"{traceback.format_exc()}"
            ),
            "error_type": "HandlerError",
        }
