# ============================================================================
# WDPA HANDLER
# ============================================================================
# STATUS: Service layer - WDPA data handler for IBAT API
# PURPOSE: Fetch and process WDPA (World Database on Protected Areas) data
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: WDPAHandler, wdpa_handler
# DEPENDENCIES: httpx, geopandas
# ============================================================================
"""
WDPA (World Database on Protected Areas) Handler.

Handles fetching and processing WDPA data from the IBAT API.

IBAT API: https://api.ibat-alliance.org/v1
Auth: Query params auth_key + auth_token
Bulk Downloads: GET /data-downloads

Exports:
    WDPAHandler: Handler for WDPA data operations
"""

import os
import tempfile
import zipfile
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

try:
    import geopandas as gpd
except ImportError:
    gpd = None

from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "WDPAHandler")

# IBAT API Configuration
IBAT_BASE_URL = "https://api.ibat-alliance.org/v1"
IBAT_DATA_DOWNLOADS_ENDPOINT = "/data-downloads"

# Environment variable names for credentials
WDPA_AUTH_KEY_ENV = "WDPA_AUTH_KEY"
WDPA_AUTH_TOKEN_ENV = "WDPA_AUTH_TOKEN"


class WDPAHandler:
    """
    Handler for WDPA (World Database on Protected Areas) operations.

    Fetches data from IBAT API and processes to PostGIS.
    Supports full_replace update strategy (TRUNCATE + INSERT).
    """

    def __init__(self):
        """Initialize WDPA handler with configuration."""
        self.config = get_config()
        self._auth_key: Optional[str] = None
        self._auth_token: Optional[str] = None

        # Check dependencies
        if httpx is None:
            logger.warning("httpx not available - WDPA handler will fail on API calls")
        if gpd is None:
            logger.warning("geopandas not available - WDPA handler will fail on data processing")

    @property
    def auth_key(self) -> str:
        """Get IBAT auth key from environment."""
        if self._auth_key is None:
            self._auth_key = os.environ.get(WDPA_AUTH_KEY_ENV, "")
        return self._auth_key

    @property
    def auth_token(self) -> str:
        """Get IBAT auth token from environment."""
        if self._auth_token is None:
            self._auth_token = os.environ.get(WDPA_AUTH_TOKEN_ENV, "")
        return self._auth_token

    def _get_auth_params(self) -> Dict[str, str]:
        """Get authentication query parameters for IBAT API."""
        return {
            "auth_key": self.auth_key,
            "auth_token": self.auth_token
        }

    def check_for_updates(self) -> Dict[str, Any]:
        """
        Check IBAT API for available WDPA downloads.

        Queries the /data-downloads endpoint to get:
        - Available download URLs
        - Dataset versions
        - File formats

        Returns:
            {
                'success': bool,
                'downloads': [...],  # List of available downloads
                'wdpa_version': str,  # Version if available
                'needs_update': bool,  # True if new version available
                'download_url': str,  # Best download URL
                'error': str  # If failed
            }
        """
        if httpx is None:
            return {
                "success": False,
                "error": "httpx library not available",
                "error_type": "DependencyError"
            }

        if not self.auth_key or not self.auth_token:
            return {
                "success": False,
                "error": f"Missing IBAT credentials. Set {WDPA_AUTH_KEY_ENV} and {WDPA_AUTH_TOKEN_ENV} environment variables.",
                "error_type": "AuthenticationError"
            }

        try:
            url = f"{IBAT_BASE_URL}{IBAT_DATA_DOWNLOADS_ENDPOINT}"
            params = self._get_auth_params()

            logger.info(f"Checking IBAT API for WDPA downloads: {url}")

            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params)

                if response.status_code == 401:
                    return {
                        "success": False,
                        "error": "IBAT API authentication failed - check credentials",
                        "error_type": "AuthenticationError",
                        "status_code": 401
                    }

                if response.status_code == 429:
                    return {
                        "success": False,
                        "error": "IBAT API rate limit exceeded - try again later",
                        "error_type": "RateLimitError",
                        "status_code": 429
                    }

                response.raise_for_status()
                data = response.json()

                # Parse response to find WDPA downloads
                downloads = self._parse_downloads(data)

                # Find the best download (prefer GeoJSON, then Shapefile, then GDB)
                best_download = self._select_best_download(downloads)

                return {
                    "success": True,
                    "downloads": downloads,
                    "wdpa_version": best_download.get("version") if best_download else None,
                    "needs_update": True,  # For now, always assume update needed
                    "download_url": best_download.get("url") if best_download else None,
                    "download_format": best_download.get("format") if best_download else None,
                    "checked_at": datetime.now(timezone.utc).isoformat()
                }

        except httpx.HTTPStatusError as e:
            logger.error(f"IBAT API HTTP error: {e}")
            return {
                "success": False,
                "error": f"IBAT API returned {e.response.status_code}",
                "error_type": "HTTPError",
                "status_code": e.response.status_code
            }
        except httpx.RequestError as e:
            logger.error(f"IBAT API request error: {e}")
            return {
                "success": False,
                "error": f"Failed to connect to IBAT API: {str(e)}",
                "error_type": "ConnectionError"
            }
        except Exception as e:
            logger.error(f"Unexpected error checking WDPA updates: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def _parse_downloads(self, api_response: Any) -> list:
        """
        Parse IBAT API response to extract download information.

        The actual structure depends on the IBAT API response format.
        This is a placeholder that should be updated based on actual API docs.
        """
        downloads = []

        # If response is a list of downloads
        if isinstance(api_response, list):
            for item in api_response:
                if isinstance(item, dict):
                    downloads.append({
                        "url": item.get("download_url") or item.get("url"),
                        "format": item.get("format") or item.get("file_format"),
                        "version": item.get("version") or item.get("release_date"),
                        "dataset": item.get("dataset") or item.get("name"),
                        "size_bytes": item.get("size_bytes") or item.get("file_size")
                    })

        # If response is a dict with downloads key
        elif isinstance(api_response, dict):
            download_list = api_response.get("downloads") or api_response.get("data") or []
            for item in download_list:
                if isinstance(item, dict):
                    downloads.append({
                        "url": item.get("download_url") or item.get("url"),
                        "format": item.get("format") or item.get("file_format"),
                        "version": item.get("version") or item.get("release_date"),
                        "dataset": item.get("dataset") or item.get("name"),
                        "size_bytes": item.get("size_bytes") or item.get("file_size")
                    })

        # Filter to WDPA-related downloads
        wdpa_downloads = [
            d for d in downloads
            if d.get("dataset") and "wdpa" in d.get("dataset", "").lower()
        ]

        return wdpa_downloads if wdpa_downloads else downloads

    def _select_best_download(self, downloads: list) -> Optional[Dict]:
        """
        Select the best download format for processing.

        Preference order:
        1. GeoJSON (easiest to process)
        2. Shapefile (widely supported)
        3. File Geodatabase (GDB) (most complete but requires fiona)
        """
        if not downloads:
            return None

        # Score downloads by format preference
        format_scores = {
            "geojson": 3,
            "json": 3,
            "shapefile": 2,
            "shp": 2,
            "gdb": 1,
            "geodatabase": 1,
            "gpkg": 2,
            "geopackage": 2
        }

        scored = []
        for d in downloads:
            fmt = (d.get("format") or "").lower()
            score = 0
            for key, value in format_scores.items():
                if key in fmt:
                    score = value
                    break
            scored.append((score, d))

        # Sort by score (highest first)
        scored.sort(key=lambda x: x[0], reverse=True)

        return scored[0][1] if scored else downloads[0]

    def download_dataset(
        self,
        download_url: str,
        output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Download WDPA dataset from IBAT.

        Args:
            download_url: URL to download from
            output_dir: Directory to save files (uses tempdir if None)

        Returns:
            {
                'success': bool,
                'file_path': str,  # Path to downloaded file
                'file_size': int,
                'error': str
            }
        """
        if httpx is None:
            return {
                "success": False,
                "error": "httpx library not available"
            }

        try:
            # Create output directory
            if output_dir is None:
                output_dir = tempfile.mkdtemp(prefix="wdpa_")

            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Add auth params to URL
            if "?" in download_url:
                full_url = f"{download_url}&auth_key={self.auth_key}&auth_token={self.auth_token}"
            else:
                full_url = f"{download_url}?auth_key={self.auth_key}&auth_token={self.auth_token}"

            logger.info(f"Downloading WDPA data from: {download_url}")

            # Stream download for large files
            with httpx.Client(timeout=None, follow_redirects=True) as client:
                with client.stream("GET", full_url) as response:
                    response.raise_for_status()

                    # Determine filename from headers or URL
                    content_disposition = response.headers.get("content-disposition", "")
                    if "filename=" in content_disposition:
                        filename = content_disposition.split("filename=")[1].strip('"\'')
                    else:
                        filename = download_url.split("/")[-1].split("?")[0]
                        if not filename:
                            filename = "wdpa_data.zip"

                    file_path = output_path / filename

                    # Write to file
                    total_size = 0
                    with open(file_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            total_size += len(chunk)

                    logger.info(f"Downloaded {total_size / 1024 / 1024:.2f} MB to {file_path}")

            return {
                "success": True,
                "file_path": str(file_path),
                "file_size": total_size,
                "filename": filename
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Download HTTP error: {e}")
            return {
                "success": False,
                "error": f"Download failed with status {e.response.status_code}",
                "status_code": e.response.status_code
            }
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def extract_and_load(
        self,
        file_path: str,
        target_table: str = "curated_wdpa_protected_areas",
        target_schema: str = "geo"
    ) -> Dict[str, Any]:
        """
        Extract downloaded file and load to PostGIS.

        Uses VectorToPostGISHandler for the actual ETL.
        Implements full_replace strategy (TRUNCATE + INSERT).

        Args:
            file_path: Path to downloaded file (ZIP, SHP, GDB, GeoJSON)
            target_table: PostGIS table name (must start with curated_)
            target_schema: PostgreSQL schema (default: geo)

        Returns:
            {
                'success': bool,
                'records_loaded': int,
                'table_name': str,
                'error': str
            }
        """
        if gpd is None:
            return {
                "success": False,
                "error": "geopandas library not available"
            }

        try:
            file_path = Path(file_path)

            # Handle ZIP files
            if file_path.suffix.lower() == ".zip":
                extract_dir = file_path.parent / file_path.stem
                extract_dir.mkdir(exist_ok=True)

                with zipfile.ZipFile(file_path, "r") as zf:
                    zf.extractall(extract_dir)

                logger.info(f"Extracted ZIP to {extract_dir}")

                # Find the actual data file
                data_file = self._find_data_file(extract_dir)
                if not data_file:
                    return {
                        "success": False,
                        "error": f"No supported data file found in {extract_dir}"
                    }
            else:
                data_file = file_path

            logger.info(f"Loading data from: {data_file}")

            # Load with geopandas
            gdf = gpd.read_file(str(data_file))
            record_count = len(gdf)
            logger.info(f"Loaded {record_count} features from {data_file}")

            if record_count == 0:
                return {
                    "success": False,
                    "error": "No features loaded from data file"
                }

            # Use VectorToPostGISHandler for ETL
            from services.vector.postgis_handler import VectorToPostGISHandler

            handler = VectorToPostGISHandler()

            # Prepare the GeoDataFrame (reproject, clean columns, etc.)
            prepared_groups = handler.prepare_gdf(gdf)
            # WDPA is always single-type (polygons) — take the one entry
            if len(prepared_groups) != 1:
                raise ValueError(
                    f"WDPA data unexpectedly contains {len(prepared_groups)} geometry types: "
                    f"{list(prepared_groups.keys())}. Expected single type."
                )
            gdf = list(prepared_groups.values())[0]

            # Full replace: TRUNCATE then INSERT
            # First, truncate the target table
            self._truncate_table(target_table, target_schema)

            # Then upload all data
            result = handler.upload_chunk(
                gdf=gdf,
                table_name=target_table,
                schema_name=target_schema,
                chunk_index=0,
                if_exists="append"  # append to freshly truncated table
            )

            if not result.get("success", False):
                return {
                    "success": False,
                    "error": result.get("error", "Upload failed"),
                    "records_attempted": record_count
                }

            logger.info(f"Loaded {record_count} records to {target_schema}.{target_table}")

            return {
                "success": True,
                "records_loaded": record_count,
                "table_name": target_table,
                "schema_name": target_schema,
                "source_file": str(data_file)
            }

        except Exception as e:
            logger.error(f"Extract and load error: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def _find_data_file(self, directory: Path) -> Optional[Path]:
        """Find the main data file in an extracted directory."""
        # Priority order for file types
        extensions = [".geojson", ".json", ".gpkg", ".shp", ".gdb"]

        for ext in extensions:
            files = list(directory.rglob(f"*{ext}"))
            if files:
                # Prefer WDPA-named files
                wdpa_files = [f for f in files if "wdpa" in f.name.lower()]
                if wdpa_files:
                    return wdpa_files[0]
                return files[0]

        # Check for GDB (directory)
        gdb_dirs = list(directory.rglob("*.gdb"))
        if gdb_dirs:
            return gdb_dirs[0]

        return None

    def _truncate_table(self, table_name: str, schema_name: str) -> None:
        """Truncate the target table for full_replace strategy."""
        from infrastructure.postgresql import PostgreSQLRepository
        from psycopg import sql

        repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if table exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                    ) as exists
                    """,
                    (schema_name, table_name)
                )
                exists = cur.fetchone()['exists']

                if exists:
                    truncate_query = sql.SQL("TRUNCATE TABLE {}.{} CASCADE").format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name)
                    )
                    cur.execute(truncate_query)
                    logger.info(f"Truncated table: {schema_name}.{table_name}")
                else:
                    logger.info(f"Table does not exist (will be created): {schema_name}.{table_name}")

                conn.commit()


# Module-level instance
wdpa_handler = WDPAHandler()

__all__ = [
    'WDPAHandler',
    'wdpa_handler',
    'IBAT_BASE_URL',
    'WDPA_AUTH_KEY_ENV',
    'WDPA_AUTH_TOKEN_ENV'
]
