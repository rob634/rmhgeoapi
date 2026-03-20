# ============================================================================
# CLAUDE CONTEXT - VECTOR VALIDATE AND CLEAN ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Geometry cleaning, CRS handling, column ops, type split
# PURPOSE: Clean a loaded GeoDataFrame (GeoParquet in, GeoParquet out) producing
#          1-3 geometry-type-split files ready for PostGIS loading.
# LAST_REVIEWED: 19 MAR 2026
# EXPORTS: vector_validate_and_clean
# DEPENDENCIES: geopandas, shapely, services.vector.postgis_handler,
#               services.vector.column_sanitizer, services.vector.core
# ============================================================================
"""
Vector Validate and Clean — atomic handler for DAG workflows.

Reads a GeoParquet written by vector_load_source, applies all geometry
cleaning operations (null removal, make_valid, force-2D, antimeridian fix,
multi-type normalization, winding order, type validation, datetime validation,
null column pruning, CRS handling, column sanitization, reserved column
filtering, optional simplification/quantization), splits by geometry type,
and writes 1-3 cleaned GeoParquet files to the ETL mount.

Operation ordering is LOAD-BEARING. Do not reorder.

Extracted from: handler_vector_docker_complete (validate/prepare section)
                services/vector/postgis_handler.py (prepare_gdf)
                services/vector/core.py (apply_column_mapping, filter_reserved_columns)
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Reserved columns that conflict with our PostGIS schema.
# Kept local to avoid import coupling with core.py at module load time.
_RESERVED_COLUMNS = {'id', 'geom', 'geometry', 'etl_batch_id'}

# Geometry-type suffix mapping (mirrors postgis_handler.prepare_gdf)
_GEOM_TYPE_SUFFIX = {
    'MultiPolygon': 'polygon',
    'MultiLineString': 'line',
    'MultiPoint': 'point',
}


def vector_validate_and_clean(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Clean and split a GeoDataFrame loaded from GeoParquet.

    Params (all from `params` dict):
        source_path (str, required): Absolute mount path to source GeoParquet.
        processing_options (dict, optional): Keys consumed:
            column_mapping (dict|None): {"old": "new"} rename rules, applied first.
            split_column (str|None): Column for split-view pre-validation.
            simplify (dict|None): {"tolerance": float} Douglas-Peucker.
            quantize (dict|None): {"precision": int} coordinate precision.
        _run_id (str, required): Injected by DAG runtime. Used to build output dir.
        _node_name (str, required): Injected by DAG runtime. Used in logging.

    Returns:
        {"success": True, "result": {...}} or {"success": False, "error": ..., "error_type": ...}
    """
    # ------------------------------------------------------------------
    # 1. PARAMETER EXTRACTION AND VALIDATION
    # ------------------------------------------------------------------
    source_path = params.get('source_path')
    if not source_path:
        return {
            "success": False,
            "error": "source_path is required",
            "error_type": "ValidationError",
        }

    run_id = params.get('_run_id')
    if not run_id:
        return {
            "success": False,
            "error": "_run_id is required (system-injected parameter missing)",
            "error_type": "ValidationError",
        }

    node_name = params.get('_node_name', 'vector_validate_and_clean')
    processing_options = params.get('processing_options') or {}

    # Consume ONLY the allowed keys from processing_options (spec constraint)
    column_mapping: Optional[Dict[str, str]] = processing_options.get('column_mapping')
    split_column: Optional[str] = processing_options.get('split_column')
    simplify_opts: Optional[Dict[str, Any]] = processing_options.get('simplify')
    quantize_opts: Optional[Dict[str, Any]] = processing_options.get('quantize')

    log_prefix = f"[{run_id[:8]}][{node_name}]"

    # ------------------------------------------------------------------
    # 2. SOURCE FILE CHECK
    # ------------------------------------------------------------------
    if not os.path.exists(source_path):
        return {
            "success": False,
            "error": f"Source parquet not found on mount: {source_path}",
            "error_type": "IntermediateNotFoundError",
        }

    # ------------------------------------------------------------------
    # 3. LOAD GEOPARQUET (deferred import — heavy dependency)
    # ------------------------------------------------------------------
    try:
        import geopandas as gpd
    except ImportError as exc:
        return {
            "success": False,
            "error": f"geopandas not available: {exc}",
            "error_type": "ValidationError",
        }

    try:
        gdf = gpd.read_parquet(source_path)
        logger.info(f"{log_prefix} Loaded GeoParquet: {len(gdf)} rows from {source_path}")
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to read GeoParquet at {source_path}: {exc}",
            "error_type": "ValidationError",
        }

    original_row_count = len(gdf)

    # Capture original CRS before any manipulation
    crs_input: Optional[str] = str(gdf.crs) if gdf.crs else None

    warnings: List[str] = []

    # ==================================================================
    # OPERATION SEQUENCE — ORDER IS LOAD-BEARING (spec requirement)
    # ==================================================================

    # ------------------------------------------------------------------
    # H2-B12: COLUMN MAPPING — apply FIRST, before any validation
    # ------------------------------------------------------------------
    if column_mapping:
        try:
            gdf = _apply_column_mapping(gdf, column_mapping, log_prefix)
            logger.info(
                f"{log_prefix} Column mapping applied: {list(column_mapping.keys())} renamed"
            )
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "error_type": "ValidationError",
            }

    # ------------------------------------------------------------------
    # H2-B1: NULL GEOMETRY REMOVAL WITH DIAGNOSTIC SAMPLING
    # ------------------------------------------------------------------
    null_mask = gdf.geometry.isna()
    null_count = int(null_mask.sum())

    logger.info(
        f"{log_prefix} Geometry validation starting: "
        f"{original_row_count} total, {null_count} null geometries"
    )

    if null_count > 0:
        null_samples = gdf[null_mask].head(5)
        logger.warning(f"{log_prefix} Sample rows with null geometries (first 5):")
        for idx, row in null_samples.iterrows():
            non_geom_cols = [col for col in gdf.columns if col != 'geometry']
            sample_data = {col: row[col] for col in non_geom_cols[:3]}
            logger.warning(f"{log_prefix}   Row {idx}: {sample_data}")

        gdf = gdf[~null_mask].copy()

        if len(gdf) == 0:
            return {
                "success": False,
                "error": (
                    f"GeoDataFrame has no valid geometries after removing nulls. "
                    f"Original: {original_row_count}, null: {null_count} (100%). "
                    f"Common causes: corrupted shapefile, incompatible format, "
                    f"invalid layer, or failed ZIP extraction."
                ),
                "error_type": "AllNullGeometryError",
            }

        removed = original_row_count - len(gdf)
        pct = round(removed / original_row_count * 100, 1)
        logger.warning(f"{log_prefix} Removed {removed} null geometries ({pct}%)")
        warnings.append(
            f"NULL_GEOMETRY_DROPPED: {removed} of {original_row_count} features had "
            f"null geometries and were dropped. {len(gdf)} features remaining."
        )

    # ------------------------------------------------------------------
    # H2-B2: MAKE_VALID — fix invalid geometries
    # ------------------------------------------------------------------
    try:
        from shapely.validation import make_valid
    except ImportError as exc:
        return {
            "success": False,
            "error": f"shapely.validation.make_valid not available: {exc}",
            "error_type": "ValidationError",
        }

    invalid_mask = ~gdf.geometry.is_valid
    invalid_count = int(invalid_mask.sum())
    if invalid_count > 0:
        logger.warning(f"{log_prefix} Fixing {invalid_count} invalid geometries using make_valid()")
        gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].apply(make_valid)

        still_invalid = int((~gdf.geometry.is_valid).sum())
        if still_invalid > 0:
            logger.warning(
                f"{log_prefix} {still_invalid} geometries still invalid after make_valid() "
                f"— may be unfixable"
            )
        else:
            logger.info(f"{log_prefix} All {invalid_count} invalid geometries repaired successfully")

    # After make_valid, check we still have rows
    if len(gdf) == 0:
        return {
            "success": False,
            "error": "All features filtered out during geometry repair (make_valid).",
            "error_type": "AllFilteredError",
        }

    # ------------------------------------------------------------------
    # H2-B3: FORCE 2D — strip Z and M dimensions, RECONSTRUCT GeoDataFrame
    # ------------------------------------------------------------------
    try:
        from shapely import force_2d
    except ImportError as exc:
        return {
            "success": False,
            "error": f"shapely.force_2d not available: {exc}",
            "error_type": "ValidationError",
        }

    has_z = gdf.geometry.has_z.any()
    has_m = gdf.geometry.has_m.any() if hasattr(gdf.geometry, 'has_m') else False

    if has_z or has_m:
        dims = []
        if has_z:
            dims.append('Z')
        if has_m:
            dims.append('M')
        logger.info(
            f"{log_prefix} Detected {'/'.join(dims)} dimension(s) — forcing to 2D"
        )

        crs_before = gdf.crs
        geoms_2d = gdf.geometry.apply(force_2d)

        # CRITICAL (H2-B3): Reconstruct GeoDataFrame — in-place assignment does
        # not update geometry column metadata. Must drop + recreate.
        gdf = gpd.GeoDataFrame(
            gdf.drop(columns=['geometry']),
            geometry=geoms_2d,
            crs=crs_before,
        )
        logger.info(f"{log_prefix} Converted all geometries to 2D and rebuilt GeoDataFrame")

    # ------------------------------------------------------------------
    # H2-B4: ANTIMERIDIAN FIX — detect and split geometries crossing 180deg
    # ------------------------------------------------------------------
    gdf, antimeridian_count = _fix_antimeridian(gdf, log_prefix)
    if antimeridian_count > 0:
        logger.warning(
            f"{log_prefix} Fixed {antimeridian_count} geometries crossing the antimeridian"
        )

    # ------------------------------------------------------------------
    # H2-B5: MULTI-TYPE NORMALIZATION — Polygon→MultiPolygon, etc.
    # ------------------------------------------------------------------
    type_counts_before = gdf.geometry.geom_type.value_counts().to_dict()
    logger.info(f"{log_prefix} Geometry types before normalization: {type_counts_before}")

    gdf['geometry'] = gdf.geometry.apply(_to_multi)

    type_counts_after = gdf.geometry.geom_type.value_counts().to_dict()
    logger.info(f"{log_prefix} Geometry types after normalization: {type_counts_after}")

    # ------------------------------------------------------------------
    # H2-B6: POLYGON WINDING ORDER — CCW exterior, CW holes (MVT compliance)
    # ------------------------------------------------------------------
    polygon_types = {'Polygon', 'MultiPolygon'}
    has_polygons = any(t in polygon_types for t in type_counts_after)
    if has_polygons:
        logger.info(
            f"{log_prefix} Enforcing polygon winding order (CCW exterior, CW holes)"
        )
        gdf['geometry'] = gdf.geometry.apply(_orient_polygon)

    # ------------------------------------------------------------------
    # H2-B7: POSTGIS GEOMETRY TYPE VALIDATION — reject GeometryCollection
    # ------------------------------------------------------------------
    SUPPORTED_GEOM_TYPES = {
        'MultiPoint', 'MultiLineString', 'MultiPolygon',
        'Point', 'LineString', 'Polygon',  # Rare after normalization but accepted
    }

    unique_types = set(gdf.geometry.geom_type.unique())
    unsupported = unique_types - SUPPORTED_GEOM_TYPES

    if unsupported:
        affected = int(gdf.geometry.geom_type.isin(unsupported).sum())
        return {
            "success": False,
            "error": (
                f"Unsupported geometry types detected: {', '.join(sorted(unsupported))}. "
                f"PostGIS CREATE TABLE supports: {', '.join(sorted(SUPPORTED_GEOM_TYPES))}. "
                f"Solutions: (1) explode GeometryCollections to single-type features, "
                f"(2) filter source data to single geometry type, "
                f"(3) split source file by geometry type. "
                f"Affected features: {affected} of {len(gdf)}"
            ),
            "error_type": "UnsupportedGeometryError",
        }

    logger.info(f"{log_prefix} All geometry types supported: {unique_types}")

    # ------------------------------------------------------------------
    # H2-B8: DATETIME VALIDATION — NaT/out-of-range year detection (CRITICAL S-1)
    # ------------------------------------------------------------------
    # PRIMARY defense against year-48113 corruption bug (psycopg3 treats pd.NaT
    # as a real datetime, dumping its internal ns representation as year ~48113).
    # Must convert pd.NaT to None at the pandas level here.
    import pandas as pd

    MIN_YEAR = 1
    MAX_YEAR = 9999

    for col in list(gdf.columns):
        if col == 'geometry':
            continue
        if pd.api.types.is_datetime64_any_dtype(gdf[col]):
            # All-NaT datetime columns: drop them (H2-B9 catches other nulls below,
            # but datetime all-NaT gets a specific log message here, matching monolith)
            if gdf[col].isna().all():
                warning_msg = f"Column '{col}': all datetime values are NaT — dropping empty column"
                logger.warning(f"{log_prefix} {warning_msg}")
                warnings.append(warning_msg)
                gdf.drop(columns=[col], inplace=True)
                continue

            # Detect out-of-range years
            try:
                years = gdf[col].dt.year
                invalid_mask = (years < MIN_YEAR) | (years > MAX_YEAR)
                invalid_count = int(invalid_mask.sum())

                if invalid_count > 0:
                    invalid_samples = gdf.loc[invalid_mask, col].head(3).tolist()
                    sample_str = ", ".join(str(v) for v in invalid_samples)
                    warning_msg = (
                        f"Column '{col}': {invalid_count} datetime values outside Python range "
                        f"(years {MIN_YEAR}-{MAX_YEAR}) set to NULL. Samples: {sample_str}"
                    )
                    logger.warning(f"{log_prefix} {warning_msg}")
                    warnings.append(warning_msg)
                    # Set out-of-range values to NaT first (pandas null)
                    gdf.loc[invalid_mask, col] = pd.NaT

            except Exception as exc:
                # Mixed-type column: log warning, let it pass through
                logger.warning(
                    f"{log_prefix} Could not validate datetime column '{col}': {exc} — passing through"
                )

    # S-1 (NaT-to-None conversion): Convert remaining pd.NaT to Python None
    # in all datetime columns so psycopg3 treats them as NULL, not year ~48113.
    for col in list(gdf.columns):
        if col == 'geometry':
            continue
        if pd.api.types.is_datetime64_any_dtype(gdf[col]):
            gdf[col] = gdf[col].where(gdf[col].notna(), other=None)

    # ------------------------------------------------------------------
    # H2-B9: ALL-NULL COLUMN PRUNING
    # ------------------------------------------------------------------
    null_columns_dropped = []
    for col in list(gdf.columns):
        if col == 'geometry':
            continue
        if gdf[col].isna().all():
            null_columns_dropped.append(col)
            gdf.drop(columns=[col], inplace=True)

    if null_columns_dropped:
        warning_msg = (
            f"Dropped {len(null_columns_dropped)} all-null column(s): "
            f"{', '.join(null_columns_dropped)}"
        )
        logger.warning(f"{log_prefix} {warning_msg}")
        warnings.append(warning_msg)

    # ------------------------------------------------------------------
    # H2-B10: CRS HANDLING (CR-1: assign 4326 for CRS-less data with WARNING)
    # ------------------------------------------------------------------
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        logger.info(f"{log_prefix} Reprojecting from {gdf.crs} to EPSG:4326")
        gdf = gdf.to_crs("EPSG:4326")
    elif not gdf.crs:
        # CRS-less data: ASSIGN 4326 with WARNING (do NOT reject — spec CR-1)
        warning_msg = "No CRS defined in source data — assuming EPSG:4326"
        logger.warning(f"{log_prefix} {warning_msg}")
        warnings.append(f"CRS_ASSUMED: {warning_msg}")
        gdf = gdf.set_crs("EPSG:4326")
    else:
        logger.info(f"{log_prefix} CRS already EPSG:4326 — no reprojection needed")

    crs_output = "EPSG:4326"

    # ------------------------------------------------------------------
    # H2-B11: COLUMN NAME SANITIZATION
    # ------------------------------------------------------------------
    from services.vector.column_sanitizer import sanitize_columns
    gdf.columns = sanitize_columns(list(gdf.columns))

    # ------------------------------------------------------------------
    # H2-B16: RESERVED COLUMN FILTERING
    # ------------------------------------------------------------------
    reserved_found = [col for col in gdf.columns if col.lower() in _RESERVED_COLUMNS and col != 'geometry']
    if reserved_found:
        warning_msg = (
            f"Reserved columns removed from source data: {reserved_found}. "
            f"These names are managed by our schema (id=PK, geom=geometry, etl_batch_id=idempotency)."
        )
        logger.warning(f"{log_prefix} {warning_msg}")
        warnings.append(warning_msg)
        gdf.drop(columns=reserved_found, inplace=True)

    # ------------------------------------------------------------------
    # H2-B15: OPTIONAL SIMPLIFICATION AND QUANTIZATION
    # ------------------------------------------------------------------
    geometry_params: Dict[str, Any] = {}
    if simplify_opts:
        geometry_params['simplify'] = simplify_opts
    if quantize_opts:
        geometry_params['quantize'] = quantize_opts

    if geometry_params:
        gdf = _apply_geometry_processing(gdf, geometry_params, log_prefix)

    # ------------------------------------------------------------------
    # H2-B13: GEOMETRY TYPE SPLIT — 1-3 groups, each written as GeoParquet
    # ------------------------------------------------------------------
    groups: Dict[str, gpd.GeoDataFrame] = {}
    for geom_type, sub_gdf in gdf.groupby(gdf.geometry.geom_type):
        suffix = _GEOM_TYPE_SUFFIX.get(geom_type, geom_type.lower())
        groups[suffix] = sub_gdf.copy()

    if len(groups) == 0:
        return {
            "success": False,
            "error": "All features filtered out during geometry cleaning. 0 rows remaining.",
            "error_type": "AllFilteredError",
        }

    if len(groups) > 1:
        type_summary = {k: len(v) for k, v in groups.items()}
        type_list = ', '.join(f"{k} ({v})" for k, v in type_summary.items())
        warning_msg = (
            f"GEOMETRY_TYPE_SPLIT: File contains mixed geometry types. "
            f"Data split into {len(groups)} groups: {type_list}."
        )
        logger.info(f"{log_prefix} {warning_msg}")
        warnings.append(warning_msg)

    # ------------------------------------------------------------------
    # WRITE GEOPARQUET FILES (N-2: GeoParquet as intermediate format)
    # ------------------------------------------------------------------
    output_dir = os.path.join("/mnt/etl", run_id, "validated")
    os.makedirs(output_dir, exist_ok=True)

    geometry_groups = []
    total_row_count = 0

    for suffix, group_gdf in groups.items():
        row_count = len(group_gdf)
        parquet_filename = f"{suffix}.parquet"
        parquet_path = os.path.join(output_dir, parquet_filename)

        try:
            group_gdf.to_parquet(parquet_path, index=False)
            logger.info(
                f"{log_prefix} Wrote {row_count} rows ({suffix}) -> {parquet_path}"
            )
        except Exception as exc:
            return {
                "success": False,
                "error": f"Failed to write GeoParquet for '{suffix}' group: {exc}",
                "error_type": "ValidationError",
            }

        geometry_groups.append({
            "geometry_type": suffix,
            "row_count": row_count,
            "parquet_path": parquet_path,
        })
        total_row_count += row_count

    # Collect final sanitized column names (excluding geometry)
    # Use the first group's columns as representative (all groups share the same schema)
    first_group = next(iter(groups.values()))
    columns_out = [col for col in first_group.columns if col != 'geometry']

    rows_removed = original_row_count - total_row_count

    # ------------------------------------------------------------------
    # SC-1/SC-2/SC-3/SC-4: SPLIT COLUMN PRE-VALIDATION
    # ------------------------------------------------------------------
    split_column_validated = False
    split_column_values: Optional[List[str]] = None
    split_column_cardinality: Optional[int] = None

    if split_column:
        # SC-1: Check split_column exists in sanitized columns
        # Note: sanitization may have renamed the column; check the sanitized names.
        if split_column not in columns_out:
            return {
                "success": False,
                "error": (
                    f"split_column '{split_column}' not found in sanitized columns. "
                    f"Available columns: {columns_out}"
                ),
                "error_type": "SplitColumnNotFoundError",
            }

        # SC-2: Check split_column is not a geometry or binary type
        # Use the full gdf (pre-split) to check dtypes
        if split_column in gdf.columns:
            col_dtype = gdf[split_column].dtype
            if hasattr(col_dtype, 'name') and col_dtype.name in ('geometry', 'bytes', 'object'):
                # For 'object', check if values are bytes/geometry
                if col_dtype.name == 'object':
                    sample = gdf[split_column].dropna().head(10)
                    if len(sample) > 0 and all(isinstance(v, (bytes, bytearray)) for v in sample):
                        return {
                            "success": False,
                            "error": (
                                f"split_column '{split_column}' appears to contain binary data "
                                f"and cannot be used as a split column."
                            ),
                            "error_type": "SplitColumnTypeError",
                        }
                elif col_dtype.name == 'geometry':
                    return {
                        "success": False,
                        "error": (
                            f"split_column '{split_column}' is a geometry column "
                            f"and cannot be used as a split column."
                        ),
                        "error_type": "SplitColumnTypeError",
                    }

        # SC-3: Check cardinality <= 100 (N-1: prevent creation of thousands of views)
        distinct_values = gdf[split_column].dropna().unique().tolist()
        cardinality = len(distinct_values)
        if cardinality > 100:
            return {
                "success": False,
                "error": (
                    f"split_column '{split_column}' has {cardinality} distinct values "
                    f"(limit: 100). Splitting into more than 100 views is not supported."
                ),
                "error_type": "SplitColumnCardinalityError",
            }

        # SC-4: ADVISORY values — Node 4 re-discovers from PostGIS via SELECT DISTINCT
        split_column_validated = True
        split_column_values = [str(v) for v in distinct_values]
        split_column_cardinality = cardinality
        logger.info(
            f"{log_prefix} split_column '{split_column}' validated: "
            f"{cardinality} distinct values (advisory)"
        )

    # ------------------------------------------------------------------
    # BUILD RESULT
    # ------------------------------------------------------------------
    result = {
        "intermediate_path": output_dir,
        "geometry_groups": geometry_groups,
        "total_row_count": total_row_count,
        "original_row_count": original_row_count,
        "rows_removed": rows_removed,
        "crs_output": crs_output,
        "crs_input": crs_input,
        "columns": columns_out,
        "warnings": warnings,
        "split_column_validated": split_column_validated,
        "split_column_values": split_column_values,
        "split_column_cardinality": split_column_cardinality,
    }

    logger.info(
        f"{log_prefix} Validation complete: "
        f"{total_row_count} rows in {len(geometry_groups)} group(s), "
        f"{rows_removed} removed, {len(warnings)} warning(s)"
    )

    return {"success": True, "result": result}


# ==============================================================================
# PRIVATE HELPERS
# ==============================================================================

def _apply_column_mapping(
    gdf: Any,
    mapping: Dict[str, str],
    log_prefix: str,
) -> Any:
    """
    Apply user-specified column renames. Raises ValueError on missing source columns.
    Mirrors services.vector.core.apply_column_mapping (deferred to avoid import at startup).
    """
    if not mapping:
        return gdf

    available_cols = [c for c in gdf.columns if c != 'geometry']
    missing = [col for col in mapping if col not in gdf.columns]

    if missing:
        raise ValueError(
            f"Column mapping failed. Source columns not found: {missing}. "
            f"Available columns: {available_cols}"
        )

    gdf = gdf.rename(columns=mapping)
    renamed_pairs = [f"'{src}' -> '{tgt}'" for src, tgt in mapping.items()]
    logger.info(f"{log_prefix} Applied column mapping: {', '.join(renamed_pairs)}")
    return gdf


def _to_multi(geom: Any) -> Any:
    """
    Normalize single-part geometries to Multi- variants.
    Mirrors the to_multi() inner function in postgis_handler.prepare_gdf.
    """
    from shapely.geometry import MultiPolygon, MultiLineString, MultiPoint
    geom_type = geom.geom_type
    if geom_type == 'Polygon':
        return MultiPolygon([geom])
    elif geom_type == 'LineString':
        return MultiLineString([geom])
    elif geom_type == 'Point':
        return MultiPoint([geom])
    return geom  # Already Multi- or GeometryCollection — unchanged


def _orient_polygon(geom: Any) -> Any:
    """
    Orient polygon winding order: CCW exterior, CW holes.
    Mirrors orient_polygon() in postgis_handler.prepare_gdf.
    """
    from shapely.geometry.polygon import orient
    geom_type = geom.geom_type
    if geom_type == 'Polygon':
        return orient(geom, sign=1.0)
    elif geom_type == 'MultiPolygon':
        from shapely.geometry import MultiPolygon
        return MultiPolygon([orient(p, sign=1.0) for p in geom.geoms])
    return geom


def _fix_antimeridian(gdf: Any, log_prefix: str):
    """
    Detect and fix geometries that cross the antimeridian (180deg longitude).
    Returns (modified_gdf, count_fixed).
    Mirrors the antimeridian fix block in postgis_handler.prepare_gdf.
    """
    from shapely.geometry import LineString, MultiPolygon, MultiLineString, MultiPoint
    from shapely.ops import split, transform
    from shapely.affinity import translate
    import numpy as np

    def _combine_parts(parts):
        if len(parts) == 1:
            return parts[0]
        all_geoms = []
        for p in parts:
            if hasattr(p, 'geoms'):
                all_geoms.extend(p.geoms)
            else:
                all_geoms.append(p)
        if all(g.geom_type == 'Polygon' for g in all_geoms):
            return MultiPolygon(all_geoms)
        elif all(g.geom_type == 'LineString' for g in all_geoms):
            return MultiLineString(all_geoms)
        elif all(g.geom_type == 'Point' for g in all_geoms):
            return MultiPoint(all_geoms)
        from shapely.geometry import GeometryCollection
        return GeometryCollection(all_geoms)

    def fix_one(geom):
        bounds = geom.bounds
        minx, miny, maxx, maxy = bounds
        width = maxx - minx
        needs_fix = maxx > 180 or minx < -180 or width > 180

        if not needs_fix:
            return geom, False

        if maxx > 180:
            antimeridian = LineString([(180, -90), (180, 90)])
            try:
                result = split(geom, antimeridian)
                fixed_parts = []
                for part in result.geoms:
                    if part.bounds[0] >= 180:
                        part = translate(part, xoff=-360)
                    fixed_parts.append(part)
                return _combine_parts(fixed_parts), True
            except Exception:
                return geom, False

        if minx < -180:
            shifted = translate(geom, xoff=360)
            return fix_one(shifted)

        if width > 180:
            def unwrap_coords(x, y):
                x = np.array(x)
                y = np.array(y)
                x = np.where(x < 0, x + 360, x)
                return x, y

            unwrapped = transform(unwrap_coords, geom)
            antimeridian = LineString([(180, -90), (180, 90)])
            try:
                result = split(unwrapped, antimeridian)
                fixed_parts = []
                for part in result.geoms:
                    if part.bounds[0] >= 180:
                        part = translate(part, xoff=-360)
                    fixed_parts.append(part)
                return _combine_parts(fixed_parts), True
            except Exception:
                return geom, False

        return geom, False

    fixed_results = gdf.geometry.apply(fix_one)
    fixed_geoms = fixed_results.apply(lambda x: x[0])
    fixed_flags = fixed_results.apply(lambda x: x[1])
    count_fixed = int(fixed_flags.sum())

    if count_fixed > 0:
        gdf = gdf.copy()
        gdf['geometry'] = fixed_geoms

    return gdf, count_fixed


def _apply_geometry_processing(
    gdf: Any,
    geometry_params: Dict[str, Any],
    log_prefix: str,
) -> Any:
    """
    Apply optional simplification (Douglas-Peucker) and quantization.
    Mirrors the geometry processing block in postgis_handler.prepare_gdf.
    """
    # Simplification
    if geometry_params.get("simplify"):
        simplify = geometry_params["simplify"]
        tolerance = simplify.get("tolerance", 0.001)
        preserve_topology = simplify.get("preserve_topology", True)

        logger.info(
            f"{log_prefix} Simplification: tolerance={tolerance}, "
            f"preserve_topology={preserve_topology}"
        )
        gdf['geometry'] = gdf.geometry.simplify(tolerance, preserve_topology=preserve_topology)
        logger.info(f"{log_prefix} Simplification applied")

    # Quantization (Shapely 2.0+)
    if geometry_params.get("quantize"):
        quantize = geometry_params["quantize"]
        snap_to_grid = quantize.get("snap_to_grid", 0.0001)

        logger.info(f"{log_prefix} Quantization: snap_to_grid={snap_to_grid}")
        try:
            from shapely import set_precision
            gdf['geometry'] = gdf.geometry.apply(
                lambda g: set_precision(g, grid_size=snap_to_grid)
            )
            logger.info(f"{log_prefix} Quantized coordinates to grid: {snap_to_grid}")
        except ImportError:
            logger.warning(
                f"{log_prefix} Shapely 2.0+ required for quantization (set_precision) — skipping"
            )

    return gdf
