# Pandas DataFrame (WKT) to GeoPandas Conversion Guide

**Date**: 14 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document easy conversion from Pandas DataFrames with WKT geometries to GeoPandas GeoDataFrames

---

## Overview

Our H3 grid service uses **Pandas DataFrames with WKT (Well-Known Text) strings** for geometry storage. This is optimal for our current use case, but you can easily convert to **GeoPandas** if needed for:

- Advanced spatial operations (buffer, union, intersection)
- Spatial indexing and joins
- Integration with QGIS, Folium, or other GIS tools
- Plotting maps with `.plot()`

## Current Data Structure

```python
# Our H3 grid DataFrames look like this:
df = pd.DataFrame({
    'h3_index': [617700169958293503, 617700169958359039],
    'geometry_wkt': [
        'POLYGON((-122.4 37.8, -122.3 37.8, -122.3 37.7, -122.4 37.7, -122.4 37.8))',
        'POLYGON((-122.5 37.9, -122.4 37.9, -122.4 37.8, -122.5 37.8, -122.5 37.9))'
    ],
    'resolution': [4, 4],
    'is_valid': [True, True]
})

# Type: pandas.DataFrame
# Geometry: WKT strings (text)
```

---

## Method 1: Simple Conversion (Recommended)

**One-liner conversion** using GeoPandas + Shapely:

```python
import geopandas as gpd
from shapely import wkt

# Convert WKT strings to shapely geometries
df['geometry'] = df['geometry_wkt'].apply(wkt.loads)

# Create GeoDataFrame with EPSG:4326 (WGS84) coordinate system
gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')

# Now you have a GeoDataFrame!
print(type(gdf))  # <class 'geopandas.geodataframe.GeoDataFrame'>
```

**What this does:**
1. `wkt.loads()` - Converts WKT string → Shapely Polygon/Point object
2. `gpd.GeoDataFrame()` - Creates GeoDataFrame with geometry column
3. `crs='EPSG:4326'` - Sets coordinate reference system (latitude/longitude)

**Advantages:**
- ✅ Simple and explicit
- ✅ Preserves original `geometry_wkt` column for reference
- ✅ Fast (shapely is C-accelerated)

---

## Method 2: Helper Function (Graceful Fallback)

**Production-ready helper** that works with or without GeoPandas:

```python
from typing import Union
import pandas as pd

def to_geopandas(
    df: pd.DataFrame,
    geometry_col: str = 'geometry_wkt',
    crs: str = 'EPSG:4326',
    drop_wkt: bool = False
) -> Union['gpd.GeoDataFrame', pd.DataFrame]:
    """
    Convert Pandas DataFrame with WKT to GeoPandas GeoDataFrame.

    Falls back to returning original DataFrame if GeoPandas unavailable.

    Args:
        df: Pandas DataFrame with WKT geometry column
        geometry_col: Name of column containing WKT strings (default: 'geometry_wkt')
        crs: Coordinate reference system (default: 'EPSG:4326' for WGS84)
        drop_wkt: Whether to drop original WKT column after conversion (default: False)

    Returns:
        GeoDataFrame if geopandas available, else original DataFrame

    Example:
        >>> df = pd.DataFrame({'geometry_wkt': ['POINT(0 0)']})
        >>> gdf = to_geopandas(df)
        >>> print(type(gdf))  # GeoDataFrame or DataFrame
    """
    try:
        import geopandas as gpd
        from shapely import wkt

        # Create copy to avoid modifying original
        result = df.copy()

        # Convert WKT to shapely geometry objects
        result['geometry'] = result[geometry_col].apply(wkt.loads)

        # Create GeoDataFrame
        gdf = gpd.GeoDataFrame(result, geometry='geometry', crs=crs)

        # Optionally drop original WKT column
        if drop_wkt:
            gdf = gdf.drop(columns=[geometry_col])

        return gdf

    except ImportError:
        # GeoPandas not available - return original DataFrame
        # This allows code to work in environments without geopandas
        return df
```

**Usage:**

```python
# Convert to GeoDataFrame if available
gdf = to_geopandas(df, geometry_col='geometry_wkt')

# Code works regardless of whether GeoPandas is installed
if isinstance(gdf, gpd.GeoDataFrame):
    # GeoPandas-specific operations
    gdf.plot()
    buffered = gdf.buffer(0.1)
else:
    # Fallback for Pandas DataFrame
    print("GeoPandas not available - using WKT strings")
```

---

## Method 3: In-Place Add to H3GridService (Optional)

**Add conversion method to H3GridService** for convenience:

```python
# services/h3_grid.py

class H3GridService:
    # ... existing methods ...

    def to_geopandas(
        self,
        df: pd.DataFrame,
        geometry_col: str = 'geometry_wkt'
    ) -> Union['gpd.GeoDataFrame', pd.DataFrame]:
        """
        Convert H3 grid DataFrame to GeoPandas GeoDataFrame.

        Args:
            df: DataFrame from generate_level4_grid(), filter_by_land(), etc.
            geometry_col: Name of WKT column (default: 'geometry_wkt')

        Returns:
            GeoDataFrame if geopandas available, else original DataFrame

        Example:
            >>> h3_service = H3GridService(...)
            >>> grid_df = h3_service.generate_level4_grid()
            >>> geo_df = h3_service.to_geopandas(grid_df)
            >>> geo_df.plot()  # Works if geopandas installed
        """
        try:
            import geopandas as gpd
            from shapely import wkt

            self.logger.info(f"🗺️  Converting DataFrame to GeoDataFrame...")

            # Create geometry column
            df['geometry'] = df[geometry_col].apply(wkt.loads)

            # Create GeoDataFrame with WGS84 CRS
            gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')

            self.logger.info(f"✅ GeoDataFrame created with {len(gdf):,} features")
            self.logger.info(f"   CRS: {gdf.crs}")

            return gdf

        except ImportError:
            self.logger.warning(
                "⚠️  GeoPandas not available - returning Pandas DataFrame. "
                "Install with: pip install geopandas"
            )
            return df
        except Exception as e:
            self.logger.error(f"❌ GeoPandas conversion failed: {e}")
            self.logger.warning("   Returning original DataFrame")
            return df
```

**Usage:**

```python
# Generate grid
h3_service = H3GridService(duckdb_repo, blob_repo, 'gold')
grid_df = h3_service.generate_level4_grid()

# Convert to GeoDataFrame for visualization
geo_df = h3_service.to_geopandas(grid_df)

# Now you can use GeoPandas methods
geo_df.plot()
geo_df.to_file('h3_grid.geojson', driver='GeoJSON')
```

---

## When to Use Each Method

| Use Case | Recommended Method |
|----------|-------------------|
| **Quick conversion in notebook** | Method 1 (simple one-liner) |
| **Production code** | Method 2 (helper function with fallback) |
| **Frequent conversions** | Method 3 (add to H3GridService) |
| **Keep as Pandas** | Don't convert (current approach) ✅ |

---

## GeoPandas Operations After Conversion

Once you have a GeoDataFrame, these operations become available:

```python
# Spatial operations
buffered = gdf.buffer(0.1)  # Buffer by 0.1 degrees
unioned = gdf.unary_union   # Merge all geometries
intersections = gdf.overlay(other_gdf, how='intersection')

# Spatial indexing
gdf.sindex  # R-tree spatial index for fast lookups

# Plotting
gdf.plot(column='resolution', legend=True)
gdf.explore()  # Interactive map (requires folium)

# Export formats
gdf.to_file('output.geojson', driver='GeoJSON')
gdf.to_file('output.shp', driver='ESRI Shapefile')
gdf.to_parquet('output.geoparquet')  # GeoParquet with native geometry

# Coordinate transformations
gdf_webmercator = gdf.to_crs('EPSG:3857')  # Web Mercator for maps
```

---

## Why We Currently Use Pandas (Not GeoPandas)

Our current approach (Pandas + WKT strings) is optimal because:

1. **DuckDB handles all spatial operations** - No Python-side geometry processing needed
2. **Simpler dependencies** - pandas vs. (geopandas + shapely + GEOS + PROJ)
3. **Sufficient for storage** - WKT works perfectly with DuckDB and GeoParquet
4. **Smaller memory footprint** - WKT strings < Shapely objects
5. **Azure Functions compatibility** - Fewer binary dependencies to deploy

**GeoPandas is beneficial when:**
- ❌ Doing Python-side spatial operations (we use DuckDB for this)
- ❌ Creating maps and visualizations (could add later if needed)
- ❌ Exporting to GIS formats (we export GeoParquet which works with WKT)

**Bottom line:** Pandas + WKT is the right choice for our current architecture. But conversion to GeoPandas is trivial if needs change!

---

## Performance Comparison

| Aspect | Pandas + WKT | GeoPandas + Shapely |
|--------|--------------|---------------------|
| **Memory** | Lower (strings) | Higher (Python objects) |
| **DuckDB spatial ops** | ✅ Same speed | ✅ Same speed |
| **Python spatial ops** | ❌ Need conversion | ✅ Native |
| **Serialization** | ✅ Faster (text) | ⚠️ Slower (binary) |
| **Dependencies** | ✅ Minimal | ⚠️ Complex (GEOS, PROJ) |
| **Azure Functions** | ✅ Easy deploy | ⚠️ Harder deploy |

**For 875 Level 4 cells:**
- Pandas DataFrame: ~100 KB
- GeoPandas GeoDataFrame: ~200 KB
- Difference negligible at our scale

**For 300K Level 6 cells:**
- Pandas DataFrame: ~30 MB
- GeoPandas GeoDataFrame: ~60 MB
- Still manageable, but 2x memory

---

## Summary

**Question:** Is there an easy way to convert Pandas with WKT to GeoPandas?

**Answer:** YES! It's a simple one-liner:

```python
from shapely import wkt
import geopandas as gpd

df['geometry'] = df['geometry_wkt'].apply(wkt.loads)
gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')
```

**Should we do it now?** No - Pandas + WKT is optimal for our use case.

**Should we add the helper function?** Maybe - if you anticipate future visualization/export needs.

**Is it worth the complexity?** Not yet - but it's available when needed!

---

## References

- **Shapely WKT docs**: https://shapely.readthedocs.io/en/stable/manual.html#wkt
- **GeoPandas docs**: https://geopandas.org/en/stable/docs/user_guide/data_structures.html
- **DuckDB spatial**: https://duckdb.org/docs/extensions/spatial.html
- **GeoParquet spec**: https://geoparquet.org/

---

**Recommendation:** Keep current Pandas + WKT approach. Add `to_geopandas()` helper to `H3GridService` only if visualization/export needs arise.
