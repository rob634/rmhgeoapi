# Zarr DAG handlers (v0.10.6)
#
# Shared utilities used across zarr handlers live here to avoid duplication.

import numpy as np

# Paired lat/lon coordinate names — matched by index, not cross-product.
# ("latitude", "longitude"), ("lat", "lon"), ("y", "x")
_COORD_PAIRS = [
    ("latitude", "longitude"),
    ("lat", "lon"),
    ("y", "x"),
]


def extract_spatial_extent(ds) -> list | None:
    """
    Extract ``[minx, miny, maxx, maxy]`` bbox from xarray Dataset coordinates.

    Uses paired coordinate name matching: ``(latitude, longitude)``,
    ``(lat, lon)``, ``(y, x)``.  Returns the first matching pair.
    Returns ``None`` if no recognised coordinate pair is found.

    This is the single canonical implementation — do not duplicate in
    individual handlers.
    """
    for lat_name, lon_name in _COORD_PAIRS:
        if lat_name in ds.coords and lon_name in ds.coords:
            try:
                lats = ds.coords[lat_name].values
                lons = ds.coords[lon_name].values
                return [
                    float(np.nanmin(lons)), float(np.nanmin(lats)),
                    float(np.nanmax(lons)), float(np.nanmax(lats)),
                ]
            except Exception:
                return None
    return None
