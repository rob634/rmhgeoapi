"""
ISO3 Country Attribution Service.

Provides geographic attribution for STAC items by querying PostGIS admin0
boundaries to determine which countries a geometry intersects.

Features:
    - Centroid-based primary country detection
    - Fallback to first intersecting country
    - Graceful degradation when admin0 table unavailable
    - Support for both bbox and GeoJSON geometry inputs

Exports:
    ISO3Attribution: Result dataclass
    ISO3AttributionService: Attribution query service
"""

import logging
import traceback
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


@dataclass
class ISO3Attribution:
    """
    Result of ISO3 country attribution query.

    Attributes:
        iso3_codes: List of ISO3 codes for all intersecting countries
        primary_iso3: ISO3 code for the "primary" country (centroid-based)
        countries: List of country names (if name column available)
        attribution_method: How primary was determined ('centroid', 'first_intersect', None)
        available: Whether attribution was successful (False if table missing or error)
    """
    iso3_codes: List[str] = field(default_factory=list)
    primary_iso3: Optional[str] = None
    countries: List[str] = field(default_factory=list)
    attribution_method: Optional[str] = None
    available: bool = False

    def to_stac_properties(self, prefix: str = "geo") -> Dict[str, Any]:
        """
        Convert to STAC properties dict with namespaced keys.

        Args:
            prefix: Property namespace prefix (default: "geo")

        Returns:
            Dict with geo:primary_iso3, geo:iso3, geo:countries, geo:attribution_method
        """
        props = {}
        if self.primary_iso3:
            props[f'{prefix}:primary_iso3'] = self.primary_iso3
        if self.iso3_codes:
            props[f'{prefix}:iso3'] = self.iso3_codes
        if self.countries:
            props[f'{prefix}:countries'] = self.countries
        if self.attribution_method:
            props[f'{prefix}:attribution_method'] = self.attribution_method
        return props


class ISO3AttributionService:
    """
    Service for geographic ISO3 country attribution.

    Queries PostGIS admin0 boundaries to determine which countries
    a given geometry (bbox or GeoJSON) intersects.

    Args:
        admin0_table: Full qualified table name (schema.table).
                     Defaults to config.h3.system_admin0_table

    Example:
        service = ISO3AttributionService()

        # For raster bounding box
        result = service.get_attribution_for_bbox([-70.7, -56.3, -70.6, -56.2])

        # For vector geometry
        result = service.get_attribution_for_geometry({
            "type": "Polygon",
            "coordinates": [[[...], [...], ...]]
        })
    """

    def __init__(self, admin0_table: Optional[str] = None):
        """
        Initialize ISO3 attribution service.

        Args:
            admin0_table: Override admin0 table path (default: via Promote Service)
        """
        self._admin0_table = admin0_table
        self._repo = None

    @property
    def admin0_table(self) -> str:
        """
        Get admin0 table path via Promote Service.

        REQUIRES a promoted dataset with system_role='admin0_boundaries'.
        There is NO FALLBACK to config defaults (23 DEC 2025).

        Raises:
            ValueError: If no system-reserved admin0 dataset is registered
        """
        if self._admin0_table:
            return self._admin0_table

        from services.promote_service import PromoteService
        from core.models.promoted import SystemRole

        service = PromoteService()
        table = service.get_system_table_name(SystemRole.ADMIN0_BOUNDARIES.value)

        if not table:
            raise ValueError(
                "No system-reserved dataset found with role 'admin0_boundaries'. "
                "ISO3 attribution requires admin0 boundaries. "
                "Promote your admin0 table with: POST /api/promote "
                "{is_system_reserved: true, system_role: 'admin0_boundaries'}"
            )

        return table

    @property
    def repo(self):
        """Lazy-load PostgreSQL repository."""
        if self._repo is None:
            from infrastructure.postgresql import PostgreSQLRepository
            self._repo = PostgreSQLRepository()
        return self._repo

    def _parse_table_path(self, table_path: str) -> tuple:
        """Parse schema.table into (schema, table) tuple."""
        if '.' in table_path:
            schema, table = table_path.split('.', 1)
        else:
            schema, table = 'geo', table_path
        return schema, table

    def _empty_result(self, available: bool = False) -> ISO3Attribution:
        """Return empty attribution result."""
        return ISO3Attribution(
            iso3_codes=[],
            primary_iso3=None,
            countries=[],
            attribution_method=None,
            available=available
        )

    def get_attribution_for_bbox(self, bbox: List[float]) -> ISO3Attribution:
        """
        Get ISO3 country codes for geometries intersecting the bounding box.

        Uses PostGIS spatial query against admin0 boundaries table.

        Args:
            bbox: Bounding box [minx, miny, maxx, maxy] in EPSG:4326

        Returns:
            ISO3Attribution with country codes and primary country

        Example:
            attribution = service.get_attribution_for_bbox([-70.7, -56.3, -70.6, -56.2])
            # Returns: ISO3Attribution(
            #     iso3_codes=['CHL'],
            #     primary_iso3='CHL',
            #     countries=['Chile'],
            #     attribution_method='centroid',
            #     available=True
            # )

        Note:
            Returns available=False if admin0 table is not populated or query fails.
            This is graceful degradation - STAC items can be created without country codes.
        """
        if not bbox or len(bbox) != 4:
            logger.warning(f"   ⚠️  Invalid bbox for country attribution: {bbox}")
            return self._empty_result(available=False)

        try:
            admin0_table = self.admin0_table
            schema, table = self._parse_table_path(admin0_table)

            with self.repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if table exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                        ) as table_exists
                    """, (schema, table))
                    if not cur.fetchone()['table_exists']:
                        logger.debug(f"   Admin0 table {admin0_table} not found - skipping country attribution")
                        return self._empty_result(available=False)

                    # Check for required columns
                    cur.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        AND column_name IN ('iso3', 'name_en', 'name', 'geom', 'geometry')
                    """, (schema, table))
                    columns = [row['column_name'] for row in cur.fetchall()]

                    if 'iso3' not in columns:
                        logger.warning(f"   Admin0 table missing 'iso3' column - skipping country attribution")
                        return self._empty_result(available=False)

                    # Determine geometry column name
                    geom_col = 'geom' if 'geom' in columns else 'geometry' if 'geometry' in columns else None
                    if not geom_col:
                        logger.warning(f"   Admin0 table missing geometry column - skipping country attribution")
                        return self._empty_result(available=False)

                    # Determine name column
                    name_col = 'name_en' if 'name_en' in columns else 'name' if 'name' in columns else None

                    minx, miny, maxx, maxy = bbox

                    # Query 1: Get all intersecting countries
                    name_select = f", {name_col}" if name_col else ""
                    intersect_query = f"""
                        SELECT iso3{name_select}
                        FROM {schema}.{table}
                        WHERE ST_Intersects(
                            {geom_col},
                            ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                        )
                        ORDER BY iso3
                    """
                    cur.execute(intersect_query, (minx, miny, maxx, maxy))
                    results = cur.fetchall()

                    if not results:
                        logger.debug(f"   No countries found for bbox {bbox} - may be in ocean")
                        return ISO3Attribution(
                            iso3_codes=[],
                            primary_iso3=None,
                            countries=[],
                            attribution_method=None,
                            available=True  # Table exists, just no intersections (e.g., ocean)
                        )

                    iso3_codes = [row['iso3'] for row in results if row['iso3']]
                    countries = []
                    if name_col:
                        countries = [row.get(name_col, '') for row in results if row.get(name_col)]

                    # Query 2: Get primary country (centroid method)
                    centroid_x = (minx + maxx) / 2
                    centroid_y = (miny + maxy) / 2

                    centroid_query = f"""
                        SELECT iso3
                        FROM {schema}.{table}
                        WHERE ST_Contains(
                            {geom_col},
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                        )
                        LIMIT 1
                    """
                    cur.execute(centroid_query, (centroid_x, centroid_y))
                    centroid_result = cur.fetchone()

                    primary_iso3 = None
                    attribution_method = None

                    if centroid_result and centroid_result['iso3']:
                        primary_iso3 = centroid_result['iso3']
                        attribution_method = 'centroid'
                    elif iso3_codes:
                        # Fallback: Use first intersecting country
                        primary_iso3 = iso3_codes[0]
                        attribution_method = 'first_intersect'

                    logger.debug(
                        f"   Country attribution: {len(iso3_codes)} countries found, "
                        f"primary={primary_iso3} ({attribution_method})"
                    )

                    return ISO3Attribution(
                        iso3_codes=iso3_codes,
                        primary_iso3=primary_iso3,
                        countries=countries,
                        attribution_method=attribution_method,
                        available=True
                    )

        except Exception as e:
            logger.warning(f"   ⚠️  Country attribution failed (non-fatal): {e}")
            logger.debug(f"   Traceback:\n{traceback.format_exc()}")
            return self._empty_result(available=False)

    def get_attribution_for_geometry(self, geometry: Dict[str, Any]) -> ISO3Attribution:
        """
        Get ISO3 country codes for arbitrary GeoJSON geometry.

        Converts GeoJSON to bbox and delegates to get_attribution_for_bbox.

        Args:
            geometry: GeoJSON geometry dict with 'type' and 'coordinates'

        Returns:
            ISO3Attribution with country codes and primary country

        Example:
            attribution = service.get_attribution_for_geometry({
                "type": "Polygon",
                "coordinates": [[[-70.7, -56.3], [-70.6, -56.3], [-70.6, -56.2], [-70.7, -56.2], [-70.7, -56.3]]]
            })
        """
        if not geometry:
            logger.warning("   ⚠️  No geometry provided for country attribution")
            return self._empty_result(available=False)

        try:
            # Extract bbox from geometry coordinates
            bbox = self._geometry_to_bbox(geometry)
            if bbox:
                return self.get_attribution_for_bbox(bbox)
            else:
                logger.warning(f"   ⚠️  Could not extract bbox from geometry type: {geometry.get('type')}")
                return self._empty_result(available=False)

        except Exception as e:
            logger.warning(f"   ⚠️  Geometry attribution failed (non-fatal): {e}")
            logger.debug(f"   Traceback:\n{traceback.format_exc()}")
            return self._empty_result(available=False)

    def _geometry_to_bbox(self, geometry: Dict[str, Any]) -> Optional[List[float]]:
        """
        Extract bounding box from GeoJSON geometry.

        Args:
            geometry: GeoJSON geometry dict

        Returns:
            [minx, miny, maxx, maxy] or None if extraction fails
        """
        geom_type = geometry.get('type', '')
        coords = geometry.get('coordinates')

        if not coords:
            return None

        # Flatten all coordinates to extract bounds
        all_coords = []

        def extract_coords(obj):
            """Recursively extract coordinate pairs."""
            if isinstance(obj, (list, tuple)):
                if len(obj) >= 2 and isinstance(obj[0], (int, float)):
                    # This is a coordinate pair [x, y] or [x, y, z]
                    all_coords.append((obj[0], obj[1]))
                else:
                    for item in obj:
                        extract_coords(item)

        extract_coords(coords)

        if not all_coords:
            return None

        xs = [c[0] for c in all_coords]
        ys = [c[1] for c in all_coords]

        return [min(xs), min(ys), max(xs), max(ys)]


# Export the service class and result dataclass
__all__ = ['ISO3Attribution', 'ISO3AttributionService']
