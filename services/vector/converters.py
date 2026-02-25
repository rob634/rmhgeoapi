# ============================================================================
# FORMAT-SPECIFIC VECTOR CONVERTERS
# ============================================================================
# STATUS: Service layer - File format conversion functions
# PURPOSE: Convert CSV, GeoJSON, GPKG, KML, KMZ, Shapefile to GeoDataFrame
# LAST_REVIEWED: 04 JAN 2026
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

from io import BytesIO
from typing import Optional
import logging
import pandas as pd
import geopandas as gpd
from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
from util_logger import LoggerFactory, ComponentType

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_converters"
)


def _convert_csv(
    data: BytesIO,
    lat_name: Optional[str] = None,
    lon_name: Optional[str] = None,
    wkt_column: Optional[str] = None,
    **kwargs
) -> gpd.GeoDataFrame:
    """
    Convert CSV to GeoDataFrame (lat/lon or WKT).

    Args:
        data: BytesIO containing CSV data
        lat_name: Latitude column name (for point geometry)
        lon_name: Longitude column name (for point geometry)
        wkt_column: WKT geometry column name (alternative to lat/lon)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame with geometries

    Raises:
        ValueError: If neither lat/lon nor wkt_column provided
        ValueError: If specified columns don't exist in CSV (GAP-008b)
    """
    if not (wkt_column or (lat_name and lon_name)):
        raise ValueError(
            "CSV conversion requires either 'wkt_column' or both 'lat_name' and 'lon_name'"
        )

    # Read CSV to DataFrame
    df = pd.read_csv(data)

    # GAP-008b FIX (15 DEC 2025): Validate that specified columns exist in the CSV
    # This gives a clear error message when parameters don't match file contents
    csv_columns = list(df.columns)

    if wkt_column:
        if wkt_column not in csv_columns:
            raise ValueError(
                f"WKT column '{wkt_column}' not found in CSV file. "
                f"Available columns: {csv_columns[:20]}{'...' if len(csv_columns) > 20 else ''}"
            )
    else:
        missing_cols = []
        if lat_name not in csv_columns:
            missing_cols.append(f"lat_name='{lat_name}'")
        if lon_name not in csv_columns:
            missing_cols.append(f"lon_name='{lon_name}'")

        if missing_cols:
            raise ValueError(
                f"Geometry column(s) not found in CSV file: {', '.join(missing_cols)}. "
                f"Available columns: {csv_columns[:20]}{'...' if len(csv_columns) > 20 else ''}"
            )

    logger.info(f"✅ CSV column validation passed: using {'wkt_column=' + wkt_column if wkt_column else f'lat={lat_name}, lon={lon_name}'}")

    # Numeric dtype validation for lat/lon columns
    if not wkt_column:
        for col_name, col_label in [(lat_name, 'latitude'), (lon_name, 'longitude')]:
            if not pd.api.types.is_numeric_dtype(df[col_name]):
                sample_values = df[col_name].head(5).tolist()
                raise ValueError(
                    f"{col_label.title()} column '{col_name}' is not numeric "
                    f"(dtype: {df[col_name].dtype}). First 5 values: {sample_values}. "
                    f"Ensure the column contains numeric coordinate values, "
                    f"not text or mixed-type data."
                )

    # WKT sample validation — catch garbage early with clear diagnostics
    if wkt_column:
        from shapely import wkt as shapely_wkt
        from shapely.errors import ShapelyError

        sample = df[wkt_column].dropna().head(5)
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
                f"⚠️  WKT column '{wkt_column}': {len(parse_errors)} of "
                f"{len(sample)} sampled values failed to parse:\n"
                + "\n".join(parse_errors)
            )

    # Convert based on provided parameters
    if wkt_column:
        return wkt_df_to_gdf(df, wkt_column)
    else:
        return xy_df_to_gdf(df, lat_name, lon_name)


def _convert_geojson(data: BytesIO, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert GeoJSON to GeoDataFrame with structural validation.

    Validates:
        1. File is valid JSON
        2. JSON has valid GeoJSON 'type' field
        3. FeatureCollection is not empty

    Args:
        data: BytesIO containing GeoJSON data
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If file is not valid JSON or GeoJSON
    """
    import json

    # 1. JSON parse check
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
    data.seek(0)
    try:
        return gpd.read_file(data)
    except Exception as e:
        raise ValueError(
            f"GeoJSON file is structurally valid but geopandas could not "
            f"parse it: {type(e).__name__}: {e}"
        ) from e


def _convert_geopackage(data: BytesIO, layer_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert GeoPackage to GeoDataFrame.

    Args:
        data: BytesIO containing GeoPackage data
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
    try:
        if layer_name:
            # Explicit layer requested - will fail if layer doesn't exist
            return gpd.read_file(data, layer=layer_name)
        else:
            # Read first layer (or only layer if single-layer GPKG)
            return gpd.read_file(data)
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


def _validate_kml_content(data: BytesIO, source_label: str = "KML") -> None:
    """
    Validate KML content before geopandas parsing.

    Checks XML well-formedness, KML root element, and Placemark existence.
    Resets data position to 0 after validation.

    Args:
        data: BytesIO containing KML data
        source_label: 'KML' or 'KMZ' for error messages

    Raises:
        ValueError: If content is not valid KML or contains no geometry data
    """
    import xml.etree.ElementTree as ET

    # 1. XML well-formedness
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
    data.seek(0)


def _convert_kml(data: BytesIO, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert KML to GeoDataFrame with structural validation.

    Validates XML well-formedness, KML root element, and Placemark existence.

    Args:
        data: BytesIO containing KML data
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If file is not valid KML or contains no Placemarks
    """
    _validate_kml_content(data, source_label="KML")
    try:
        return gpd.read_file(data)
    except Exception as e:
        raise ValueError(
            f"KML file passed structural validation but geopandas could not "
            f"parse it: {type(e).__name__}: {e}"
        ) from e


def _convert_kmz(data: BytesIO, kml_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert KMZ (zipped KML) to GeoDataFrame with validation.

    Validates ZIP integrity, KML presence, then applies KML structural checks.

    Args:
        data: BytesIO containing KMZ data
        kml_name: Specific KML filename in archive (optional, uses first .kml found)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If KMZ is not a valid ZIP, contains no KML, or KML is invalid
    """
    import zipfile as zipfile_module

    try:
        kml_path = extract_zip_file(data, '.kml', kml_name)
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


def _convert_shapefile(data: BytesIO, shp_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert Shapefile (in ZIP) to GeoDataFrame with companion file validation.

    Validates:
        1. Required companion files (.shx, .dbf) exist in ZIP
        2. Warns if .prj (CRS definition) is missing
        3. Geometry column exists
        4. Not all geometries are NULL

    Args:
        data: BytesIO containing zipped shapefile
        shp_name: Specific .shp filename in archive (optional, uses first .shp found)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If shapefile is missing components, has no geometry column,
                    or all geometries are NULL
    """
    import os

    shp_path = extract_zip_file(data, '.shp', shp_name)
    logger.info(f"📂 Reading shapefile from: {shp_path}")

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
            f"Optional but recommended: .prj (coordinate system definition)."
        )

    # 2. Missing .prj warning (non-fatal — downstream CRS handling covers this)
    prj_exists = (
        os.path.exists(os.path.join(shp_dir, shp_base + '.prj')) or
        os.path.exists(os.path.join(shp_dir, shp_base + '.PRJ'))
    )
    if not prj_exists:
        logger.warning(
            f"⚠️  Shapefile '{shp_base}' has no .prj file — coordinate system "
            f"is unknown. Will assume EPSG:4326. If data appears displaced, "
            f"re-export with the correct CRS defined."
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
    logger.info(f"📊 Shapefile loaded — {len(gdf)} features, CRS: {gdf.crs}")

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
                f"⚠️  {null_count} of {len(gdf)} features have NULL geometries "
                f"({null_count/len(gdf)*100:.1f}%) — these will be removed during validation"
            )

        # Log geometry types for diagnostics
        valid_geoms = gdf[~gdf.geometry.isna()]
        if len(valid_geoms) > 0:
            geom_types = valid_geoms.geometry.geom_type.value_counts().to_dict()
            logger.info(f"   Geometry types: {geom_types}")

    return gdf
