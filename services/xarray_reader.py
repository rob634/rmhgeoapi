# ============================================================================
# CLAUDE CONTEXT - XARRAY ZARR READER SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Layer - Direct Zarr access for time-series operations
# PURPOSE: Read Zarr files directly with xarray for efficient time-series queries
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: XarrayReader
# DEPENDENCIES: xarray, zarr, fsspec, adlfs
# ============================================================================
"""
xarray Zarr Reader Service.

Provides direct Zarr access for time-series operations that would be
inefficient via TiTiler (N HTTP requests for N time steps).

Uses fsspec + adlfs for Azure Blob storage access.

Operations:
- Point time-series extraction
- Regional statistics over time
- Temporal aggregation (mean, max, min over time)
"""

import logging
import statistics
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)

# Lazy imports - these are heavy dependencies
_xarray = None
_fsspec = None


def _get_xarray():
    """Lazy import xarray."""
    global _xarray
    if _xarray is None:
        import xarray as xr
        _xarray = xr
    return _xarray


def _get_fsspec():
    """Lazy import fsspec."""
    global _fsspec
    if _fsspec is None:
        import fsspec
        _fsspec = fsspec
    return _fsspec


@dataclass
class TimeSeriesPoint:
    """Single point in a time series."""
    time: str
    value: float
    bidx: Optional[int] = None


@dataclass
class TimeSeriesResult:
    """Result of a time-series query."""
    success: bool
    location: Optional[Tuple[float, float]] = None
    item_id: Optional[str] = None
    variable: Optional[str] = None
    unit: Optional[str] = None
    time_series: List[TimeSeriesPoint] = field(default_factory=list)
    statistics: Optional[Dict[str, float]] = None
    error: Optional[str] = None


@dataclass
class AggregationResult:
    """Result of a temporal aggregation."""
    success: bool
    bbox: Optional[Tuple[float, float, float, float]] = None
    item_id: Optional[str] = None
    variable: Optional[str] = None
    aggregation: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    data: Optional[np.ndarray] = None
    lat_coords: Optional[np.ndarray] = None
    lon_coords: Optional[np.ndarray] = None
    error: Optional[str] = None


@dataclass
class RegionalStatsResult:
    """Result of regional statistics query."""
    success: bool
    bbox: Optional[Tuple[float, float, float, float]] = None
    item_id: Optional[str] = None
    variable: Optional[str] = None
    time_series: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


class XarrayReader:
    """
    Direct Zarr reader using xarray.

    Optimized for time-series operations that would require
    many HTTP requests via TiTiler.

    Usage:
        reader = XarrayReader()

        # Point time-series
        result = reader.get_point_timeseries(
            zarr_url="https://storage.blob.core.windows.net/container/data.zarr",
            variable="tasmax",
            lon=-77.0,
            lat=38.9,
            start_time="2015-01-01",
            end_time="2015-12-31"
        )

        # Temporal aggregation
        result = reader.get_temporal_aggregation(
            zarr_url=...,
            variable="tasmax",
            bbox=(-125, 25, -65, 50),
            start_time="2015-01-01",
            end_time="2015-12-31",
            aggregation="mean"
        )
    """

    def __init__(self, storage_account: str = "rmhazuregeo"):
        """
        Initialize xarray reader.

        Args:
            storage_account: Azure storage account name for fsspec
        """
        self.storage_account = storage_account
        self._datasets: Dict[str, Any] = {}  # Cache open datasets

    def _get_store(self, zarr_url: str) -> Any:
        """
        Get fsspec mapper for Zarr URL.

        Args:
            zarr_url: Full URL to Zarr dataset

        Returns:
            fsspec mapper for xarray
        """
        fsspec = _get_fsspec()

        # Handle different URL formats
        if zarr_url.startswith("https://"):
            # Azure Blob URL: https://account.blob.core.windows.net/container/path.zarr
            # Convert to abfs:// format for adlfs
            return fsspec.get_mapper(
                zarr_url,
                anon=True  # Public read access
            )
        elif zarr_url.startswith("abfs://") or zarr_url.startswith("az://"):
            return fsspec.get_mapper(
                zarr_url,
                account_name=self.storage_account
            )
        else:
            # Local path or other
            return zarr_url

    def _open_zarr(self, zarr_url: str, variable: Optional[str] = None) -> Any:
        """
        Open Zarr dataset with xarray.

        Args:
            zarr_url: URL to Zarr dataset
            variable: Optional variable to select

        Returns:
            xarray Dataset or DataArray
        """
        xr = _get_xarray()

        # Check cache
        cache_key = zarr_url
        if cache_key not in self._datasets:
            store = self._get_store(zarr_url)
            try:
                ds = xr.open_zarr(store, consolidated=True)
            except Exception:
                # Try without consolidated metadata
                ds = xr.open_zarr(store, consolidated=False)
            self._datasets[cache_key] = ds

        ds = self._datasets[cache_key]

        if variable:
            return ds[variable]
        return ds

    def get_point_timeseries(
        self,
        zarr_url: str,
        variable: str,
        lon: float,
        lat: float,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        aggregation: str = "none"
    ) -> TimeSeriesResult:
        """
        Extract time-series at a point.

        Args:
            zarr_url: URL to Zarr dataset
            variable: Variable name
            lon: Longitude
            lat: Latitude
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            aggregation: Temporal aggregation (none, daily, monthly, yearly)

        Returns:
            TimeSeriesResult with time-series data
        """
        try:
            da = self._open_zarr(zarr_url, variable)

            # Select point (nearest neighbor)
            point_da = da.sel(lat=lat, lon=lon, method="nearest")

            # Select time range if specified
            if start_time and end_time:
                point_da = point_da.sel(time=slice(start_time, end_time))
            elif start_time:
                point_da = point_da.sel(time=slice(start_time, None))
            elif end_time:
                point_da = point_da.sel(time=slice(None, end_time))

            # Load data (this is when actual I/O happens)
            values = point_da.values
            times = point_da.time.values if "time" in point_da.dims else None

            # Build time series
            time_series = []
            if times is not None:
                for i, (t, v) in enumerate(zip(times, values)):
                    time_str = str(np.datetime_as_string(t, unit='D'))[:10] if hasattr(t, 'astype') else str(t)[:10]
                    time_series.append(TimeSeriesPoint(
                        time=time_str,
                        value=float(v) if not np.isnan(v) else None,
                        bidx=i + 1
                    ))
            else:
                # No time dimension - single value
                time_series.append(TimeSeriesPoint(
                    time="static",
                    value=float(values) if not np.isnan(values) else None,
                    bidx=1
                ))

            # Apply aggregation if requested
            if aggregation != "none" and times is not None:
                time_series = self._aggregate_timeseries(time_series, aggregation)

            # Calculate statistics
            valid_values = [p.value for p in time_series if p.value is not None]
            stats = None
            if valid_values:
                stats = {
                    "min": min(valid_values),
                    "max": max(valid_values),
                    "mean": sum(valid_values) / len(valid_values),
                    "std": statistics.stdev(valid_values) if len(valid_values) > 1 else 0.0,
                    "count": len(valid_values)
                }

            # Get unit from attributes
            unit = da.attrs.get("units") or da.attrs.get("unit")

            return TimeSeriesResult(
                success=True,
                location=(lon, lat),
                variable=variable,
                unit=unit,
                time_series=time_series,
                statistics=stats
            )

        except Exception as e:
            logger.exception(f"Error reading Zarr time-series: {e}")
            return TimeSeriesResult(
                success=False,
                error=str(e)
            )

    def _aggregate_timeseries(
        self,
        time_series: List[TimeSeriesPoint],
        aggregation: str
    ) -> List[TimeSeriesPoint]:
        """
        Aggregate time series to coarser resolution.

        Args:
            time_series: Input time series
            aggregation: Aggregation period (daily, monthly, yearly)

        Returns:
            Aggregated time series
        """
        if aggregation == "daily":
            # Already daily in most cases
            return time_series

        # Group by period
        groups: Dict[str, List[float]] = {}
        for point in time_series:
            if point.value is None:
                continue

            if aggregation == "monthly":
                key = point.time[:7]  # YYYY-MM
            elif aggregation == "yearly":
                key = point.time[:4]  # YYYY
            else:
                key = point.time

            if key not in groups:
                groups[key] = []
            groups[key].append(point.value)

        # Calculate mean for each period
        result = []
        for period, values in sorted(groups.items()):
            result.append(TimeSeriesPoint(
                time=period,
                value=sum(values) / len(values),
                bidx=None
            ))

        return result

    def get_temporal_aggregation(
        self,
        zarr_url: str,
        variable: str,
        bbox: Tuple[float, float, float, float],
        start_time: str,
        end_time: str,
        aggregation: str = "mean"
    ) -> AggregationResult:
        """
        Compute temporal aggregation over a region.

        Args:
            zarr_url: URL to Zarr dataset
            variable: Variable name
            bbox: Bounding box (minx, miny, maxx, maxy)
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            aggregation: Aggregation method (mean, max, min, sum)

        Returns:
            AggregationResult with 2D array
        """
        try:
            minx, miny, maxx, maxy = bbox
            da = self._open_zarr(zarr_url, variable)

            # Select bbox (note: lat may be in decreasing order)
            lat_slice = slice(maxy, miny) if da.lat[0] > da.lat[-1] else slice(miny, maxy)
            subset = da.sel(
                lat=lat_slice,
                lon=slice(minx, maxx),
                time=slice(start_time, end_time)
            )

            # Compute aggregation over time
            if aggregation == "mean":
                result = subset.mean(dim="time")
            elif aggregation == "max":
                result = subset.max(dim="time")
            elif aggregation == "min":
                result = subset.min(dim="time")
            elif aggregation == "sum":
                result = subset.sum(dim="time")
            else:
                return AggregationResult(
                    success=False,
                    error=f"Unknown aggregation: {aggregation}"
                )

            # Load result
            data = result.values
            lat_coords = result.lat.values
            lon_coords = result.lon.values

            return AggregationResult(
                success=True,
                bbox=bbox,
                variable=variable,
                aggregation=aggregation,
                start_time=start_time,
                end_time=end_time,
                data=data,
                lat_coords=lat_coords,
                lon_coords=lon_coords
            )

        except Exception as e:
            logger.exception(f"Error computing temporal aggregation: {e}")
            return AggregationResult(
                success=False,
                error=str(e)
            )

    def get_regional_statistics(
        self,
        zarr_url: str,
        variable: str,
        bbox: Tuple[float, float, float, float],
        start_time: str,
        end_time: str,
        temporal_resolution: str = "monthly"
    ) -> RegionalStatsResult:
        """
        Compute spatial statistics over time for a region.

        Args:
            zarr_url: URL to Zarr dataset
            variable: Variable name
            bbox: Bounding box (minx, miny, maxx, maxy)
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            temporal_resolution: Time grouping (daily, monthly, yearly)

        Returns:
            RegionalStatsResult with statistics per time period
        """
        try:
            minx, miny, maxx, maxy = bbox
            da = self._open_zarr(zarr_url, variable)

            # Select bbox
            lat_slice = slice(maxy, miny) if da.lat[0] > da.lat[-1] else slice(miny, maxy)
            subset = da.sel(
                lat=lat_slice,
                lon=slice(minx, maxx),
                time=slice(start_time, end_time)
            )

            # Resample if needed
            if temporal_resolution == "monthly":
                resampled = subset.resample(time="ME")
            elif temporal_resolution == "yearly":
                resampled = subset.resample(time="YE")
            else:
                resampled = subset.resample(time="D")

            # Compute statistics for each time period
            time_series = []
            for label, group in resampled:
                if group.size == 0:
                    continue

                spatial_data = group.values.flatten()
                valid_data = spatial_data[~np.isnan(spatial_data)]

                if len(valid_data) == 0:
                    continue

                period_str = str(label)[:10] if temporal_resolution == "daily" else str(label)[:7]

                time_series.append({
                    "period": period_str,
                    "spatial_mean": float(np.mean(valid_data)),
                    "spatial_min": float(np.min(valid_data)),
                    "spatial_max": float(np.max(valid_data)),
                    "spatial_std": float(np.std(valid_data)),
                    "valid_pixels": int(len(valid_data))
                })

            return RegionalStatsResult(
                success=True,
                bbox=bbox,
                variable=variable,
                time_series=time_series
            )

        except Exception as e:
            logger.exception(f"Error computing regional statistics: {e}")
            return RegionalStatsResult(
                success=False,
                error=str(e)
            )

    def close(self):
        """Close cached datasets."""
        for ds in self._datasets.values():
            try:
                ds.close()
            except Exception:
                pass
        self._datasets.clear()
