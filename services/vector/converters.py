# ============================================================================
# FORMAT-SPECIFIC VECTOR CONVERTERS
# ============================================================================
# STATUS: Service layer - File format conversion functions
# PURPOSE: Convert CSV, GeoJSON, GPKG, KML, KMZ, Shapefile to GeoDataFrame
# LAST_REVIEWED: 26 FEB 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: _convert_csv, _convert_geojson, _convert_geopackage, _convert_kml, _convert_kmz, _convert_shapefile
# DEPENDENCIES: geopandas, pandas
# ============================================================================
"""
Format-Specific Vector Converters.

Private helper functions for converting various file formats to GeoDataFrame.
Called by the load_vector_file task.

Exports:
    _convert_csv: Convert CSV with lat/lon or WKT
    _convert_geojson: Convert GeoJSON/JSON files
    _convert_geopackage: Convert GeoPackage with layer selection
    _convert_kml: Convert KML files
    _convert_kmz: Convert KMZ (zipped KML) files
    _convert_shapefile: Convert Shapefile (zipped)
"""

import csv
import re
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple, Union
import logging
import pandas as pd
import geopandas as gpd
from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
from util_logger import LoggerFactory, ComponentType

# Type alias: converters accept BytesIO (in-memory) or file path (mount-based)
ConverterInput = Union[BytesIO, str, Path]

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_converters"
)


def _is_file_path(data: ConverterInput) -> bool:
    """Check if data is a file path (str or Path) rather than BytesIO."""
    return isinstance(data, (str, Path))


# Common null patterns to catch beyond pandas defaults
COMMON_NA_VALUES = ['NA', 'N/A', 'NULL', 'null', 'None', 'none', '-', '', '#N/A', '#NA']

# Coordinate-like pattern for header row detection (e.g. -73.9857, 40.7484)
_COORD_PATTERN = re.compile(r'^-?\d+\.\d{2,}$')


def _detect_csv_encoding(raw_bytes: bytes) -> str:
    """
    Detect CSV encoding from a raw byte sample.

    Tries UTF-8-SIG (BOM), UTF-8, then Latin-1 (universal fallback).
    No external dependencies — uses only bytes.decode().

    Args:
        raw_bytes: First ~8KB of the CSV file

    Returns:
        Encoding name suitable for pd.read_csv(encoding=...)
    """
    for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            raw_bytes.decode(encoding)
            return encoding
        except (UnicodeDecodeError, ValueError):
            continue
    # latin-1 never fails (maps 0x00–0xFF 1:1), so this is a safety fallback
    return 'latin-1'


def _detect_csv_delimiter(sample_text: str) -> str:
    """
    Detect CSV delimiter using Python's csv.Sniffer.

    Args:
        sample_text: Decoded text sample (first ~8KB)

    Returns:
        Single-character delimiter string (defaults to ',' if Sniffer fails)
    """
    try:
        dialect = csv.Sniffer().sniff(sample_text)
        return dialect.delimiter
    except csv.Error:
        logger.warning("csv.Sniffer could not detect delimiter, defaulting to comma")
        return ','


def _check_header_row(df: pd.DataFrame) -> None:
    """
    Warn if CSV column names look like data rather than headers.

    Checks for all-numeric column names or coordinate-like values.
    Logs warnings but does not reject the file.

    Args:
        df: DataFrame to check (only column names inspected)
    """
    col_names = [str(c) for c in df.columns]

    # Check 1: All columns are purely numeric (0, 1, 2, ...)
    if all(name.strip().isdigit() for name in col_names):
        logger.warning(
            f"CSV may be missing a header row: all column names are numeric "
            f"({col_names[:5]}{'...' if len(col_names) > 5 else ''}). "
            f"If so, the first data row was used as column names."
        )
        return

    # Check 2: Any column name looks like a coordinate value
    coord_cols = [name for name in col_names if _COORD_PATTERN.match(name.strip())]
    if coord_cols:
        logger.warning(
            f"CSV may be missing a header row: column name(s) look like "
            f"coordinate values: {coord_cols[:3]}. "
            f"If so, the first data row was used as column names."
        )


def _resolve_column_name(user_name: str, column_lookup: dict, label: str) -> str:
    """
    Resolve a user-specified column name against actual CSV columns (case-insensitive).

    Args:
        user_name: Column name provided by user (e.g. 'Latitude')
        column_lookup: {col.lower().strip(): actual_col} from DataFrame
        label: Human label for error messages (e.g. 'lat_name')

    Returns:
        Actual column name from the DataFrame

    Raises:
        ValueError: If no match found (exact or case-insensitive)
    """
    # Exact match — no resolution needed
    if user_name in column_lookup.values():
        return user_name

    # Case-insensitive match
    key = user_name.lower().strip()
    if key in column_lookup:
        actual = column_lookup[key]
        logger.info(f"Matched {label}='{user_name}' -> '{actual}' (case-insensitive)")
        return actual

    # No match
    available = list(column_lookup.values())
    raise ValueError(
        f"{label}='{user_name}' not found in CSV file. "
        f"Available columns: {available[:20]}{'...' if len(available) > 20 else ''}"
    )


def _read_csv_with_detection(data: ConverterInput, nrows: Optional[int] = None) -> Tuple[pd.DataFrame, str, str]:
    """
    Read CSV with automatic encoding and delimiter detection.

    Args:
        data: BytesIO buffer or file path string
        nrows: Optional row limit (for sample validation)

    Returns:
        Tuple of (DataFrame, detected_encoding, detected_delimiter)
    """
    if _is_file_path(data):
        # File path: read 8KB sample from disk
        with open(data, 'rb') as f:
            raw_sample = f.read(8192)
    else:
        data.seek(0)
        raw_sample = data.read(8192)
        data.seek(0)

    encoding = _detect_csv_encoding(raw_sample)
    sample_text = raw_sample.decode(encoding, errors='replace')
    delimiter = _detect_csv_delimiter(sample_text)

    logger.info(f"CSV detection: encoding={encoding}, delimiter={repr(delimiter)}")

    read_kwargs = dict(
        encoding=encoding,
        sep=delimiter,
        na_values=COMMON_NA_VALUES,
    )
    if nrows is not None:
        read_kwargs['nrows'] = nrows

    df = pd.read_csv(data, **read_kwargs)
    return df, encoding, delimiter


def _convert_csv(
    data: ConverterInput,
    lat_name: Optional[str] = None,
    lon_name: Optional[str] = None,
    wkt_column: Optional[str] = None,
    **kwargs
) -> gpd.GeoDataFrame:
    """
    Convert CSV to GeoDataFrame (lat/lon or WKT).

    Hardened pipeline (26 FEB 2026):
        1. Encoding detection (UTF-8-SIG / UTF-8 / Latin-1)
        2. Delimiter auto-detection (csv.Sniffer)
        3. Common null pattern handling
        4. Header row validation (warnings)
        5. Case-insensitive column matching
        6. Sample-first validation (100 rows before full load)
        7. Empty row filtering with metrics

    Args:
        data: BytesIO containing CSV data, or file path string (mount-based)
        lat_name: Latitude column name (for point geometry)
        lon_name: Longitude column name (for point geometry)
        wkt_column: WKT geometry column name (alternative to lat/lon)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame with geometries

    Raises:
        ValueError: If neither lat/lon nor wkt_column provided
        ValueError: If specified columns don't exist in CSV
        ValueError: If all rows are empty after filtering
    """
    if not (wkt_column or (lat_name and lon_name)):
        raise ValueError(
            "CSV conversion requires either 'wkt_column' or both 'lat_name' and 'lon_name'"
        )

    # ── Phase 1: Sample validation (100 rows) ──────────────────────────
    sample_df, encoding, delimiter = _read_csv_with_detection(data, nrows=100)

    # Header row sanity check
    _check_header_row(sample_df)

    # Build case-insensitive column lookup
    column_lookup = {str(c).lower().strip(): str(c) for c in sample_df.columns}

    # Resolve column names (case-insensitive matching)
    if wkt_column:
        wkt_column = _resolve_column_name(wkt_column, column_lookup, 'wkt_column')
    else:
        lat_name = _resolve_column_name(lat_name, column_lookup, 'lat_name')
        lon_name = _resolve_column_name(lon_name, column_lookup, 'lon_name')

    logger.info(
        f"CSV column validation passed: using "
        f"{'wkt_column=' + wkt_column if wkt_column else f'lat={lat_name}, lon={lon_name}'}"
    )

    # Validate types on sample
    if not wkt_column:
        for col_name, col_label in [(lat_name, 'latitude'), (lon_name, 'longitude')]:
            if not pd.api.types.is_numeric_dtype(sample_df[col_name]):
                sample_values = sample_df[col_name].head(5).tolist()
                raise ValueError(
                    f"{col_label.title()} column '{col_name}' is not numeric "
                    f"(dtype: {sample_df[col_name].dtype}). First 5 values: {sample_values}. "
                    f"Ensure the column contains numeric coordinate values, "
                    f"not text or mixed-type data."
                )

    # WKT sample validation — catch garbage early
    if wkt_column:
        from shapely import wkt as shapely_wkt
        from shapely.errors import ShapelyError

        sample = sample_df[wkt_column].dropna().head(5)
        if len(sample) == 0:
            raise ValueError(
                f"WKT column '{wkt_column}' contains only NULL/empty values. "
                f"No geometry data to parse."
            )

        parse_errors = []
        for i, val in enumerate(sample):
            try:
                shapely_wkt.loads(str(val))
            except (ShapelyError, Exception) as e:
                parse_errors.append(
                    f"  Row {sample.index[i]}: '{str(val)[:80]}' -> {e}"
                )

        if len(parse_errors) == len(sample):
            raise ValueError(
                f"WKT column '{wkt_column}' contains no parseable WKT geometry. "
                f"Sampled {len(sample)} values, all failed:\n"
                + "\n".join(parse_errors)
                + "\n\nExpected WKT format: 'POINT(lon lat)', 'POLYGON((...))' etc."
            )
        elif parse_errors:
            logger.warning(
                f"WKT column '{wkt_column}': {len(parse_errors)} of "
                f"{len(sample)} sampled values failed to parse:\n"
                + "\n".join(parse_errors)
            )

    # ── Phase 2: Full file load ─────────────────────────────────────────
    if _is_file_path(data):
        data_size = Path(data).stat().st_size
    else:
        data_size = data.seek(0, 2)  # seek to end to get size
        data.seek(0)
    logger.info(f"Sample validation passed (100 rows), loading full file ({data_size:,} bytes)")

    df = pd.read_csv(
        data,
        encoding=encoding,
        sep=delimiter,
        na_values=COMMON_NA_VALUES,
    )

    # ── Phase 3: Empty row filtering ────────────────────────────────────
    total_rows = len(df)
    df = df.dropna(how='all')
    dropped = total_rows - len(df)

    if dropped > 0:
        pct = (dropped / total_rows * 100) if total_rows > 0 else 0
        logger.warning(f"Removed {dropped} empty rows ({pct:.1f}%) from CSV")

    if len(df) == 0:
        raise ValueError(
            f"CSV file contains no data rows after filtering. "
            f"Original row count: {total_rows}, all rows were empty/null."
        )

    logger.info(f"CSV loaded: {len(df)} rows, {len(df.columns)} columns")

    # Convert based on provided parameters
    if wkt_column:
        return wkt_df_to_gdf(df, wkt_column)
    else:
        return xy_df_to_gdf(df, lat_name, lon_name)


def _convert_geojson(data: ConverterInput, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert GeoJSON to GeoDataFrame with structural validation.

    Validates:
        1. File is valid JSON
        2. JSON has valid GeoJSON 'type' field
        3. FeatureCollection is not empty

    Args:
        data: BytesIO containing GeoJSON data, or file path string (mount-based)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If file is not valid JSON or GeoJSON
    """
    import json

    # 1. JSON parse check
    if _is_file_path(data):
        try:
            with open(data, 'r') as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"File is not valid JSON. Parse error at line {e.lineno}, "
                f"column {e.colno}: {e.msg}. Ensure the file is valid GeoJSON "
                f"(RFC 7946) and not corrupted or truncated."
            ) from e
    else:
        data.seek(0)
        try:
            raw = json.load(data)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"File is not valid JSON. Parse error at line {e.lineno}, "
                f"column {e.colno}: {e.msg}. Ensure the file is valid GeoJSON "
                f"(RFC 7946) and not corrupted or truncated."
            ) from e

    # 2. GeoJSON structure check
    VALID_GEOJSON_TYPES = {
        'FeatureCollection', 'Feature', 'GeometryCollection',
        'Point', 'MultiPoint', 'LineString', 'MultiLineString',
        'Polygon', 'MultiPolygon'
    }
    geojson_type = raw.get('type')
    if geojson_type not in VALID_GEOJSON_TYPES:
        raise ValueError(
            f"File is valid JSON but not valid GeoJSON. "
            f"Expected 'type' to be one of {sorted(VALID_GEOJSON_TYPES)}, "
            f"got: '{geojson_type}'. Ensure the file follows the GeoJSON "
            f"specification (RFC 7946)."
        )

    # 3. Empty FeatureCollection guard
    if geojson_type == 'FeatureCollection':
        features = raw.get('features')
        if not features or len(features) == 0:
            raise ValueError(
                "GeoJSON FeatureCollection contains 0 features. "
                "The file structure is valid but has no data."
            )
        logger.info(f"✅ GeoJSON validation: {len(features)} features in FeatureCollection")

    # 4. Parse with geopandas (wrap errors with context)
    if _is_file_path(data):
        read_target = str(data)
    else:
        data.seek(0)
        read_target = data
    try:
        return gpd.read_file(read_target)
    except Exception as e:
        raise ValueError(
            f"GeoJSON file is structurally valid but geopandas could not "
            f"parse it: {type(e).__name__}: {e}"
        ) from e


def _convert_geopackage(data: ConverterInput, layer_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert GeoPackage to GeoDataFrame.

    Args:
        data: BytesIO containing GeoPackage data, or file path string (mount-based)
        layer_name: Layer name to extract (optional, defaults to first layer)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If specified layer_name does not exist in GeoPackage

    Notes:
        If layer_name not provided, reads the first available layer.
        GeoPackage files can contain multiple layers.
        Invalid layer names will raise ValueError with explicit error message.
    """
    # gpd.read_file works with both BytesIO and str paths; ensure Path → str
    read_target = str(data) if _is_file_path(data) else data
    try:
        if layer_name:
            # Explicit layer requested - will fail if layer doesn't exist
            return gpd.read_file(read_target, layer=layer_name)
        else:
            # Read first layer (or only layer if single-layer GPKG)
            return gpd.read_file(read_target)
    except Exception as e:
        # Re-raise with explicit context about layer validation
        if layer_name and ('layer' in str(e).lower() or 'not found' in str(e).lower()):
            raise ValueError(
                f"Layer '{layer_name}' not found in GeoPackage. "
                f"Original error: {type(e).__name__}: {e}"
            ) from e
        else:
            # Other errors (file corruption, etc.) - re-raise as-is
            raise


def _validate_kml_content(data: ConverterInput, source_label: str = "KML") -> None:
    """
    Validate KML content before geopandas parsing.

    Checks XML well-formedness, KML root element, and Placemark existence.
    Resets data position to 0 after validation (if BytesIO).

    Args:
        data: BytesIO containing KML data, or file path string
        source_label: 'KML' or 'KMZ' for error messages

    Raises:
        ValueError: If content is not valid KML or contains no geometry data
    """
    import xml.etree.ElementTree as ET

    # 1. XML well-formedness
    if _is_file_path(data):
        try:
            tree = ET.parse(str(data))
        except ET.ParseError as e:
            raise ValueError(
                f"{source_label} file is not valid XML. Parse error: {e}. "
                f"Ensure the file is well-formed KML/XML and not corrupted."
            ) from e
    else:
        data.seek(0)
        try:
            tree = ET.parse(data)
        except ET.ParseError as e:
            raise ValueError(
                f"{source_label} file is not valid XML. Parse error: {e}. "
                f"Ensure the file is well-formed KML/XML and not corrupted."
            ) from e

    # 2. KML root element check (handle namespace variations)
    root = tree.getroot()
    tag = root.tag.lower()
    # KML namespaces: {http://www.opengis.net/kml/2.2}kml or just 'kml'
    if not tag.endswith('}kml') and tag != 'kml':
        raise ValueError(
            f"{source_label} file is valid XML but not a KML document. "
            f"Root element is '{root.tag}', expected 'kml'. "
            f"Ensure the file is a valid KML (OGC KML 2.2/2.3) document."
        )

    # 3. Placemark existence check (search all namespace variants)
    namespaces = [
        {'kml': 'http://www.opengis.net/kml/2.2'},
        {'kml': 'http://earth.google.com/kml/2.1'},
        {'kml': 'http://earth.google.com/kml/2.0'},
    ]

    placemarks = []
    for ns in namespaces:
        placemarks = root.findall('.//kml:Placemark', ns)
        if placemarks:
            break

    # Also try without namespace (unqualified XML)
    if not placemarks:
        placemarks = root.findall('.//Placemark')

    if not placemarks:
        raise ValueError(
            f"{source_label} file contains no Placemark elements. "
            f"KML files must contain at least one Placemark with geometry data. "
            f"The file may be a network link, a style-only document, "
            f"or an empty KML template."
        )

    logger.info(f"✅ {source_label} validation: {len(placemarks)} Placemarks found")
    if not _is_file_path(data):
        data.seek(0)


def _convert_kml(data: ConverterInput, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert KML to GeoDataFrame with structural validation.

    Validates XML well-formedness, KML root element, and Placemark existence.

    Args:
        data: BytesIO containing KML data, or file path string (mount-based)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If file is not valid KML or contains no Placemarks
    """
    if _is_file_path(data):
        # Validate from file, then read with geopandas using path
        _validate_kml_content(data, source_label="KML")
        try:
            return gpd.read_file(str(data))
        except Exception as e:
            raise ValueError(
                f"KML file passed structural validation but geopandas could not "
                f"parse it: {type(e).__name__}: {e}"
            ) from e
    else:
        _validate_kml_content(data, source_label="KML")
        try:
            return gpd.read_file(data)
        except Exception as e:
            raise ValueError(
                f"KML file passed structural validation but geopandas could not "
                f"parse it: {type(e).__name__}: {e}"
            ) from e


def _convert_kmz(data: ConverterInput, kml_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert KMZ (zipped KML) to GeoDataFrame with validation.

    Validates ZIP integrity, KML presence, then applies KML structural checks.

    Args:
        data: BytesIO containing KMZ data, or file path string (mount-based)
        kml_name: Specific KML filename in archive (optional, uses first .kml found)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If KMZ is not a valid ZIP, contains no KML, or KML is invalid
    """
    import zipfile as zipfile_module

    extract_dir = kwargs.get('extract_dir')
    try:
        kml_path = extract_zip_file(data, '.kml', kml_name, extract_dir=extract_dir)
    except zipfile_module.BadZipFile:
        raise ValueError(
            "KMZ file is not a valid ZIP archive. The file may be "
            "corrupted or truncated. Re-export from Google Earth "
            "or your GIS application."
        )
    except FileNotFoundError:
        raise ValueError(
            "KMZ archive does not contain a .kml file. A valid KMZ must "
            "contain at least one .kml file inside the ZIP archive."
        )

    # Validate the extracted KML content
    with open(kml_path, 'rb') as f:
        kml_buffer = BytesIO(f.read())
    _validate_kml_content(kml_buffer, source_label="KMZ")

    try:
        return gpd.read_file(kml_path)
    except Exception as e:
        raise ValueError(
            f"KMZ file passed structural validation but geopandas could not "
            f"parse it: {type(e).__name__}: {e}"
        ) from e


def _convert_shapefile(data: ConverterInput, shp_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert Shapefile (in ZIP) to GeoDataFrame with companion file validation.

    Validates (26 FEB 2026 — hardened):
        1. ZIP integrity (BadZipFile → clear error, reuses KMZ pattern)
        2. Multiple .shp detection (reject if ambiguous, no silent first-match)
        3. Required companion files (.shx, .dbf) exist
        4. .prj file REQUIRED (reject if missing — no silent CRS guessing)
        5. Geometry column exists
        6. Not all geometries are NULL

    Args:
        data: BytesIO containing zipped shapefile, or file path string (mount-based)
        shp_name: Specific .shp filename in archive (optional, uses first .shp found)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If ZIP is invalid, multiple .shp without shp_name specified,
                    missing companion files, missing .prj, no geometry column,
                    or all geometries are NULL
    """
    import os
    import zipfile as zipfile_module

    extract_dir = kwargs.get('extract_dir')

    # 0. ZIP integrity + .shp presence (KMZ pattern)
    try:
        # Pre-scan: check for multiple .shp files before extracting
        # zipfile.ZipFile accepts both BytesIO and file path strings natively
        if _is_file_path(data):
            zip_target = str(data)
        else:
            data.seek(0)
            zip_target = data

        with zipfile_module.ZipFile(zip_target) as zf:
            shp_files = [f for f in zf.namelist() if f.lower().endswith('.shp')]

        if len(shp_files) == 0:
            raise ValueError(
                "Shapefile ZIP does not contain a .shp file. "
                "A valid shapefile ZIP must contain at least .shp, .shx, .dbf, "
                "and .prj files with the same base name."
            )

        if len(shp_files) > 1 and not shp_name:
            raise ValueError(
                f"Shapefile ZIP contains {len(shp_files)} .shp files: "
                f"{shp_files}. Specify which shapefile to use via "
                f"processing_options.shp_name, or submit each shapefile "
                f"in its own ZIP."
            )

        if not _is_file_path(data):
            data.seek(0)
        shp_path = extract_zip_file(data, '.shp', shp_name, extract_dir=extract_dir)

    except zipfile_module.BadZipFile:
        raise ValueError(
            "Shapefile ZIP is not a valid ZIP archive. The file may be "
            "corrupted or truncated. Re-export from your GIS application "
            "and ensure the file is a valid .zip."
        )

    logger.info(f"Reading shapefile from: {shp_path}")

    # 1. Companion file check
    shp_dir = os.path.dirname(shp_path)
    shp_base = os.path.splitext(os.path.basename(shp_path))[0]

    required = {'.shx': 'spatial index', '.dbf': 'attribute table'}
    missing = []
    for ext, purpose in required.items():
        companion = os.path.join(shp_dir, shp_base + ext)
        # Case-insensitive fallback (some tools export .SHX, .DBF)
        if not os.path.exists(companion):
            if not os.path.exists(os.path.join(shp_dir, shp_base + ext.upper())):
                missing.append(f"{ext} ({purpose})")

    if missing:
        raise ValueError(
            f"Shapefile ZIP is missing required component files: "
            f"{', '.join(missing)}. A valid shapefile requires .shp, .shx, "
            f"and .dbf files (all with the same base name '{shp_base}'). "
            f"Required: .prj (coordinate system definition)."
        )

    # 2. .prj file REQUIRED (26 FEB 2026 — upgraded from warning to rejection)
    # Without .prj we'd guess EPSG:4326, which silently produces wrong coordinates
    # for projected CRS data (UTM, State Plane, etc.). Fail explicitly.
    prj_exists = (
        os.path.exists(os.path.join(shp_dir, shp_base + '.prj')) or
        os.path.exists(os.path.join(shp_dir, shp_base + '.PRJ'))
    )
    if not prj_exists:
        raise ValueError(
            f"Shapefile '{shp_base}' is missing a .prj file (coordinate system definition). "
            f"Without a .prj file, the coordinate reference system is unknown and data "
            f"may be silently mispositioned. Re-export from your GIS application with "
            f"the CRS/projection defined, or add the .prj file to the ZIP."
        )

    # 3. Read shapefile
    gdf = gpd.read_file(shp_path)

    # 4. Geometry column check
    if 'geometry' not in gdf.columns:
        raise ValueError(
            f"Shapefile has no geometry column. Available columns: "
            f"{list(gdf.columns)}. This may indicate a corrupted .shp file "
            f"or a non-spatial DBF-only table."
        )

    # 5. Diagnostics logging
    logger.info(f"Shapefile loaded: {len(gdf)} features, CRS: {gdf.crs}")

    if len(gdf) > 0:
        null_count = gdf.geometry.isna().sum()

        # 6. All-NULL geometry check (FAIL — not warn)
        if gdf.geometry.isna().all():
            raise ValueError(
                f"Shapefile contains {len(gdf)} features but ALL geometries "
                f"are NULL ({null_count} of {len(gdf)}). This typically means "
                f"the .shp file is corrupted or the geometry column is empty. "
                f"Re-export from your source GIS application."
            )

        if null_count > 0:
            logger.warning(
                f"{null_count} of {len(gdf)} features have NULL geometries "
                f"({null_count/len(gdf)*100:.1f}%) — these will be removed during validation"
            )

        # Log geometry types for diagnostics
        valid_geoms = gdf[~gdf.geometry.isna()]
        if len(valid_geoms) > 0:
            geom_types = valid_geoms.geometry.geom_type.value_counts().to_dict()
            logger.info(f"   Geometry types: {geom_types}")

    return gdf
