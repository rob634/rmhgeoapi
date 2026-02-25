# Vector Input Format Hardening — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reject invalid vector input files early with detailed, actionable error messages that propagate to `job.result_data` via the existing ErrorResponse pipeline.

**Architecture:** Two validation layers — pre-flight (parameter validation, no file I/O) and converter-level (opens files, structural + content checks). All errors `raise ValueError("detailed message")` which flows through `_map_exception_to_error_code()` → `create_error_response_v2()` → `job.result_data`.

**Tech Stack:** Python 3.12, geopandas, shapely, xml.etree.ElementTree, json, re

**Reference:** Design conversation 25 FEB 2026. Builds on completed `2026-02-24-vector-etl-validation.md` (G1-G3 post-insert guards, column sanitizer).

---

## Task 1: Add new ErrorCodes (dependency for all other tasks)

**Files:**
- Modify: `core/errors.py:117-125` (ErrorCode enum), `:364-372` (classification map), `:440-457` (category map), `:535-542` (scope map)

**Step 1: Add ErrorCode enum values**

In `core/errors.py`, after `VECTOR_TABLE_NAME_INVALID` (line ~125), add:

```python
    VECTOR_FORMAT_MISMATCH = "VECTOR_FORMAT_MISMATCH"  # Content doesn't match declared format
    VECTOR_MIXED_GEOMETRY = "VECTOR_MIXED_GEOMETRY"  # Multiple incompatible geometry types
```

**Step 2: Add classifications**

In the `ERROR_CLASSIFICATIONS` dict (around line 364), after the `VECTOR_ENCODING_ERROR` entry:

```python
    ErrorCode.VECTOR_FORMAT_MISMATCH: ErrorClassification.PERMANENT,
    ErrorCode.VECTOR_MIXED_GEOMETRY: ErrorClassification.PERMANENT,
```

**Step 3: Add categories**

In the `ERROR_CATEGORIES` dict (around line 440), in the vector section:

```python
    ErrorCode.VECTOR_FORMAT_MISMATCH: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_MIXED_GEOMETRY: ErrorCategory.DATA_QUALITY,
```

**Step 4: Add scopes**

In the `ERROR_SCOPES` dict (around line 535), in the vector section:

```python
    ErrorCode.VECTOR_FORMAT_MISMATCH: ErrorScope.NODE,
    ErrorCode.VECTOR_MIXED_GEOMETRY: ErrorScope.NODE,
```

**Step 5: Commit**

```bash
git add core/errors.py
git commit -m "feat: Add VECTOR_FORMAT_MISMATCH and VECTOR_MIXED_GEOMETRY ErrorCodes"
```

---

## Task 2: Fix error message propagation + add new error mappings

**Files:**
- Modify: `services/handler_vector_docker_complete.py:435-493` (error handling block), `:997-1060` (`_map_exception_to_error_code`), `:1062-1130` (`_get_vector_remediation`)

**Problem:** Currently the `message` field wraps the ValueError in boilerplate:
```
"message": "Vector Docker ETL failed: ValueError: Shapefile ZIP is missing..."
```
And the `remediation` field is always generic per-error-code text. The specific diagnostic
from our detailed ValueError is buried inside the boilerplate message, and there's no
dedicated field that contains JUST the data quality details.

**Step 1: Add `data_quality_detail` field to error response**

At line ~437, change the error_msg construction and add a detail extraction:

```python
    except Exception as e:
        elapsed = time.time() - start_time
        # Extract the raw diagnostic (the ValueError message itself)
        raw_detail = str(e)
        error_msg = f"Vector Docker ETL failed: {type(e).__name__}: {e}"
        logger.error(f"[{job_id[:8]}] {error_msg}\n{traceback.format_exc()}")
```

Then at line ~476, add `data_quality_detail` to the return dict (after `"error_type"`):

```python
        return {
            "success": False,
            "error": response.error_code,
            "error_code": response.error_code,
            "error_category": response.error_category,
            "error_scope": response.error_scope,
            "message": response.message,
            "detail": raw_detail,  # <-- Raw diagnostic from ValueError
            "remediation": response.remediation,
            "user_fixable": response.user_fixable,
            "retryable": response.retryable,
            "http_status": response.http_status,
            "error_id": response.error_id,
            "error_type": type(e).__name__,
            "last_checkpoint": checkpoints[-1] if checkpoints else None,
            "checkpoint_data": checkpoint_data,
            "elapsed_seconds": round(elapsed, 2),
            "_debug": debug.model_dump(),
        }
```

This means a failed job result now includes:
- `error_code`: Machine-readable code (`"VECTOR_UNREADABLE"`)
- `message`: Full wrapped message (backwards compat)
- **`detail`**: Raw diagnostic — the exact ValueError text e.g. `"Shapefile ZIP is missing required component files: .shx (spatial index), .dbf (attribute table). A valid shapefile requires..."`
- `remediation`: Generic how-to-fix guidance per error code

**Step 2: Add pattern matches to `_map_exception_to_error_code()`**

At line ~1017, BEFORE the existing file/parsing block, add a new format mismatch block:

```python
    # Format mismatch (file content doesn't match declared type)
    if 'not valid json' in error_str or 'not valid geojson' in error_str:
        return ErrorCode.VECTOR_FORMAT_MISMATCH
    if 'not valid xml' in error_str or 'not a kml document' in error_str:
        return ErrorCode.VECTOR_FORMAT_MISMATCH
    if 'missing required component' in error_str:
        return ErrorCode.VECTOR_UNREADABLE
```

At line ~1027, BEFORE the existing geometry block, add mixed geometry:

```python
    # Mixed geometry types
    if 'mixed geometry types' in error_str:
        return ErrorCode.VECTOR_MIXED_GEOMETRY
```

**Step 3: Add remediation entries to `_get_vector_remediation()`**

In the `remediation_map` dict (after `VECTOR_ENCODING_ERROR` entry, around line 1090):

```python
        ErrorCode.VECTOR_FORMAT_MISMATCH: (
            "The file content does not match the declared format. Verify the file "
            "extension matches the actual data. For example, ensure .geojson files "
            "contain valid GeoJSON (RFC 7946) and .kml files contain valid KML/XML. "
            "See the 'detail' field for the specific parsing error."
        ),
        ErrorCode.VECTOR_MIXED_GEOMETRY: (
            "Your file contains multiple geometry types (e.g., points and polygons) "
            "that cannot coexist in a single PostGIS table. Split your file by "
            "geometry type using QGIS (Vector > Geometry Tools > Explode) or ogr2ogr "
            "with a WHERE clause on geometry type, then submit each file separately. "
            "See the 'detail' field for the geometry type breakdown."
        ),
```

**Step 4: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "feat: Add 'detail' field to error response + VECTOR_FORMAT_MISMATCH/VECTOR_MIXED_GEOMETRY mappings"
```

---

## Task 3: Pre-flight validators — bare .shp rejection + table_name syntax

**Files:**
- Modify: `infrastructure/validators.py` (add 2 new `@register_validator` functions, after `csv_geometry_params` at line ~1397)
- Modify: `jobs/vector_docker_etl.py:276-307` (add validator entries to `resource_validators` list)

**Step 1: Add `bare_shp_rejection` validator to `infrastructure/validators.py`**

After the `csv_geometry_params` validator (line ~1397), add:

```python
@register_validator("bare_shp_rejection")
def validate_bare_shp_rejection(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Reject bare .shp files — shapefiles must be submitted as ZIP archives.

    Shapefiles consist of multiple component files (.shp, .shx, .dbf, .prj).
    Submitting a bare .shp without companions will always fail at processing.
    Users must ZIP all components together.

    Config options:
        file_extension_param: str - Parameter name for file extension
        blob_param: str - Parameter name for blob path
        error: str - Custom error message
    """
    file_ext_param = config.get('file_extension_param', 'file_extension')
    blob_param = config.get('blob_param', 'blob_name')

    file_extension = (params.get(file_ext_param) or '').lower()
    blob_name = params.get(blob_param) or ''

    # Only trigger for shp extension with a bare .shp blob
    if file_extension == 'shp' and blob_name.lower().endswith('.shp'):
        error_msg = config.get('error') or (
            "Shapefiles must be submitted as a ZIP archive containing all required "
            "component files (.shp, .shx, .dbf, and .prj). Upload a .zip file "
            "containing your shapefile components, then select file_extension='zip'."
        )
        logger.warning(f"❌ bare_shp_rejection: {error_msg}")
        return ValidatorResult(valid=False, message=error_msg)

    return ValidatorResult(valid=True, message=None)
```

**Step 2: Add `table_name_syntax` validator to `infrastructure/validators.py`**

Immediately after `bare_shp_rejection`:

```python
@register_validator("table_name_syntax")
def validate_table_name_syntax(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate PostGIS table name syntax before job creation.

    Rules:
        - Lowercase letters, numbers, underscores only
        - Cannot start with a digit
        - Max 63 characters (PostgreSQL NAMEDATALEN)
        - Cannot be a SQL reserved word

    Config options:
        table_param: str - Parameter name for table name (default: 'table_name')
        error: str - Custom error message prefix
    """
    import re

    table_param = config.get('table_param', 'table_name')
    table_name = params.get(table_param)

    if not table_name:
        # Other validators handle required field checks
        return ValidatorResult(valid=True, message=None)

    # Lowercase for validation
    name = table_name.lower()

    # Check pattern: lowercase alphanumeric + underscore, starts with letter/underscore
    if not re.match(r'^[a-z_][a-z0-9_]*$', name):
        if name[0].isdigit():
            reason = "starts with a digit"
        else:
            reason = "contains invalid characters (only a-z, 0-9, underscore allowed)"
        return ValidatorResult(
            valid=False,
            message=(
                f"Table name '{table_name}' is invalid for PostGIS: {reason}. "
                f"Rules: lowercase letters, numbers, underscores only. Cannot start "
                f"with a number. Max 63 characters. Cannot be a SQL reserved word."
            )
        )

    # Check length
    if len(name) > 63:
        return ValidatorResult(
            valid=False,
            message=(
                f"Table name '{table_name}' is invalid for PostGIS: exceeds 63 "
                f"character limit ({len(name)} chars). PostgreSQL identifiers are "
                f"limited to 63 characters (NAMEDATALEN)."
            )
        )

    # Check reserved words (reuse from column_sanitizer)
    from services.vector.column_sanitizer import PG_RESERVED_WORDS
    if name in PG_RESERVED_WORDS:
        return ValidatorResult(
            valid=False,
            message=(
                f"Table name '{table_name}' is invalid for PostGIS: '{name}' is a "
                f"PostgreSQL reserved word. Choose a different name (e.g., "
                f"'{name}_data' or '{name}_layer')."
            )
        )

    return ValidatorResult(valid=True, message=None)
```

**Step 3: Wire validators into `jobs/vector_docker_etl.py`**

In `resource_validators` list (line ~276), add two new entries BEFORE the existing `blob_exists` validator:

```python
    resource_validators = [
        {
            'type': 'bare_shp_rejection',
            'blob_param': 'blob_name',
            'file_extension_param': 'file_extension',
        },
        {
            'type': 'table_name_syntax',
            'table_param': 'table_name',
        },
        # ... existing blob_exists, table_not_exists, csv_geometry_params ...
    ]
```

**Step 4: Commit**

```bash
git add infrastructure/validators.py jobs/vector_docker_etl.py
git commit -m "feat: Pre-flight validators — bare .shp rejection + table_name syntax check"
```

---

## Task 4: Harden GeoJSON converter

**Files:**
- Modify: `services/vector/converters.py:105-116` (`_convert_geojson`)

**Step 1: Replace the one-liner with validated parsing**

Replace the entire `_convert_geojson` function (lines 105-116) with:

```python
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
```

**Step 2: Commit**

```bash
git add services/vector/converters.py
git commit -m "feat: Harden GeoJSON converter — JSON parse, structure, empty collection checks"
```

---

## Task 5: Harden Shapefile converter

**Files:**
- Modify: `services/vector/converters.py:188-236` (`_convert_shapefile`)

**Step 1: Replace the diagnostic-only function with fail-fast validation**

Replace the entire `_convert_shapefile` function (lines 188-236) with:

```python
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
```

**Step 2: Commit**

```bash
git add services/vector/converters.py
git commit -m "feat: Harden Shapefile converter — companion file check, fail on all-NULL geometry"
```

---

## Task 6: Harden KML/KMZ converters + shared validation helper

**Files:**
- Modify: `services/vector/converters.py:158-185` (`_convert_kml`, `_convert_kmz`)
- Add `_validate_kml_content` helper function in same file
- Add `import zipfile` to imports if not present

**Step 1: Add `_validate_kml_content` helper**

Add this function BEFORE `_convert_kml` (around line 157):

```python
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
```

**Step 2: Replace `_convert_kml` (lines 158-169)**

```python
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
```

**Step 3: Replace `_convert_kmz` (lines 172-185)**

```python
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
```

**Step 4: Commit**

```bash
git add services/vector/converters.py
git commit -m "feat: Harden KML/KMZ converters — XML validation, root element check, Placemark guard"
```

---

## Task 7: Harden CSV converter — numeric dtype + WKT sampling

**Files:**
- Modify: `services/vector/converters.py:41-102` (`_convert_csv`)

**Step 1: Add numeric dtype and WKT sample checks**

Insert these checks AFTER the existing column existence validation (line ~96, after the `logger.info("✅ CSV column validation passed...")` line) and BEFORE the `if wkt_column: return wkt_df_to_gdf(...)` block (line ~99):

```python
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
```

**Step 2: Commit**

```bash
git add services/vector/converters.py
git commit -m "feat: Harden CSV converter — numeric dtype check for lat/lon, WKT sample validation"
```

---

## Task 8: Mixed geometry type detection in postgis_handler

**Files:**
- Modify: `services/vector/postgis_handler.py` — in `prepare_gdf()`, after geometry normalization (Step 5, around line ~420) and BEFORE the PostGIS type support validation (Step 7, around line ~456)

**Step 1: Add mixed geometry detection block**

Insert between the winding order fix block and the PostGIS type validation block:

```python
        # ========================================================================
        # MIXED GEOMETRY TYPE DETECTION (25 FEB 2026)
        # ========================================================================
        # After normalization, all geometries should be the same Multi-type.
        # If multiple Multi-types exist (e.g., MultiPoint + MultiPolygon), the
        # table can only be typed to one — mismatched rows would fail on INSERT
        # or produce an unusable mixed-type table.
        # ========================================================================
        multi_types = set(gdf.geometry.geom_type.unique())
        if len(multi_types) > 1:
            type_counts = gdf.geometry.geom_type.value_counts().to_dict()
            type_summary = ", ".join(
                f"{t}: {c} features" for t, c in type_counts.items()
            )
            raise ValueError(
                f"File contains mixed geometry types that cannot be stored in a "
                f"single PostGIS table: {type_summary}. "
                f"Each table requires a uniform geometry type. "
                f"Split the source file by geometry type (e.g., polygons in one "
                f"file, points in another) and submit separately."
            )

        emit("geometry_type_uniform", {
            "geometry_type": list(multi_types)[0],
            "features": len(gdf)
        })
```

**Step 2: Commit**

```bash
git add services/vector/postgis_handler.py
git commit -m "feat: Reject mixed geometry types after normalization — fail before PostGIS upload"
```

---

## Task 9: Final commit + docs update

**Step 1: Update ERRORS_AND_FIXES.md with new error codes**

Add a section to `docs_claude/ERRORS_AND_FIXES.md` documenting the two new error codes:

```markdown
### VEC-010: VECTOR_FORMAT_MISMATCH

**Error Message**: "File is not valid JSON" / "File is valid JSON but not valid GeoJSON" / "not valid XML" / "not a KML document"

**Likely Causes**:
1. File extension doesn't match actual content (e.g., .geojson file contains HTML)
2. File is corrupted or truncated
3. Wrong file selected for upload

**Fix**: Verify the file is the correct format. Open it in a text editor — GeoJSON should start with `{`, KML should start with `<?xml`.

---

### VEC-011: VECTOR_MIXED_GEOMETRY

**Error Message**: "File contains mixed geometry types that cannot be stored in a single PostGIS table"

**Likely Causes**:
1. GeoJSON FeatureCollection with both Point and Polygon features
2. KML with Placemarks of different geometry types
3. Shapefile converted from mixed-type source

**Fix**: Split the file by geometry type in QGIS (Vector > Geometry Tools > Explode) or use ogr2ogr with a WHERE clause, then submit each file separately.
```

**Step 2: Final commit**

```bash
git add docs_claude/ERRORS_AND_FIXES.md
git commit -m "docs: Add VEC-010 VECTOR_FORMAT_MISMATCH and VEC-011 VECTOR_MIXED_GEOMETRY to error reference"
```

---

## Execution Order Summary

| Task | What | Files | Depends On |
|------|------|-------|------------|
| 1 | ErrorCodes | `core/errors.py` | — |
| 2 | Error mapping | `services/handler_vector_docker_complete.py` | Task 1 |
| 3 | Pre-flight validators | `infrastructure/validators.py`, `jobs/vector_docker_etl.py` | — |
| 4 | GeoJSON converter | `services/vector/converters.py` | — |
| 5 | Shapefile converter | `services/vector/converters.py` | — |
| 6 | KML/KMZ converters | `services/vector/converters.py` | — |
| 7 | CSV converter | `services/vector/converters.py` | — |
| 8 | Mixed geometry detection | `services/vector/postgis_handler.py` | Task 1 |
| 9 | Docs | `docs_claude/ERRORS_AND_FIXES.md` | All |

Tasks 3-7 are independent of each other and can be parallelized. Tasks 1-2 must run first (ErrorCode dependency). Task 8 depends on Task 1. Task 9 runs last.

## Testing Checklist

After all tasks are implemented, verify with these test scenarios:

- [ ] Bare `.shp` file → rejected at submit with "must be submitted as ZIP"
- [ ] `table_name="123bad"` → rejected at submit with "starts with a digit"
- [ ] `table_name="select"` → rejected at submit with "reserved word"
- [ ] `.geojson` containing `{"name": "not geojson"}` → `VECTOR_FORMAT_MISMATCH`
- [ ] `.geojson` with `{"type": "FeatureCollection", "features": []}` → `VECTOR_NO_FEATURES`
- [ ] `.kml` containing HTML → `VECTOR_FORMAT_MISMATCH`
- [ ] KML with no Placemarks → `VECTOR_NO_FEATURES`
- [ ] KMZ that is not a valid ZIP → `VECTOR_UNREADABLE`
- [ ] Shapefile ZIP missing `.shx` → `VECTOR_UNREADABLE`
- [ ] Shapefile with all NULL geometries → `VECTOR_GEOMETRY_EMPTY`
- [ ] CSV with text in lat/lon column → `VECTOR_COORDINATE_ERROR`
- [ ] CSV with garbage in WKT column → `VECTOR_COORDINATE_ERROR`
- [ ] GeoJSON with mixed Point + Polygon → `VECTOR_MIXED_GEOMETRY`
