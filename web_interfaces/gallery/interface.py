# ============================================================================
# CLAUDE CONTEXT - DATA GALLERY INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web interface - Data showcase gallery with preview cards
# PURPOSE: Display featured datasets with thumbnails linking to visualizations
# LAST_REVIEWED: 19 DEC 2025
# EXPORTS: GalleryInterface
# DEPENDENCIES: web_interfaces.base, config
# ============================================================================
"""
Data Gallery Interface.

Showcase gallery for featured datasets with preview thumbnails and
links to interactive map visualizations.

Features:
    - Preview cards with thumbnail images
    - Dataset metadata (source type, variables, extent)
    - Deep links to visualization interfaces (Zarr, Map, STAC)
    - Responsive grid layout
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

from config import get_config


# ============================================================================
# GALLERY ITEMS CONFIGURATION
# ============================================================================
# Add new datasets here to display them in the gallery.
# Each item links to its visualization interface.

GALLERY_ITEMS = [
    {
        "id": "era5-climate",
        "title": "ERA5 Global Climate Data",
        "subtitle": "Global Reanalysis at 0.25° Resolution",
        "description": "ERA5 global climate reanalysis (~27GB) with 9 meteorological variables: "
                       "temperature, wind, pressure, and more. Hourly data served via TiTiler-xarray.",
        "icon": "🌡️",
        "source_type": "Zarr",
        "source_badge_color": "#00A3DA",  # Cyan for Zarr
        "link": "/api/interface/zarr",
        "link_text": "Open Climate Viewer",
        "metadata": {
            "Variables": "9 (temperature, wind, pressure...)",
            "Size": "~27 GB (1 month global)",
            "Renderer": "TiTiler-xarray"
        },
        # Thumbnail: TiTiler preview endpoint for the Zarr dataset
        # Will be constructed dynamically from config
        "thumbnail_type": "zarr_preview"
    },
    {
        "id": "ogc-features-demo",
        "title": "OGC Features Browser",
        "subtitle": "Interactive Vector Data Viewer",
        "description": "Browse PostGIS vector collections with OGC API - Features. "
                       "Leaflet map with click-to-query properties and simplification controls.",
        "icon": "🗺️",
        "source_type": "PostGIS",
        "source_badge_color": "#0071BC",  # Blue for PostGIS
        "link": "/api/interface/map",
        "link_text": "Open Map Viewer",
        "metadata": {
            "API": "OGC API - Features Core 1.0",
            "Format": "GeoJSON",
            "Renderer": "Leaflet.js"
        },
        "thumbnail_type": "static",
        "thumbnail_url": None  # Will use placeholder
    },
    {
        "id": "stac-catalog",
        "title": "STAC Catalog Explorer",
        "subtitle": "Raster Metadata & Visualization",
        "description": "Search and browse STAC collections with TiTiler visualization. "
                       "View COG rasters, inspect metadata, and open tile viewers.",
        "icon": "📦",
        "source_type": "STAC + COG",
        "source_badge_color": "#FFC14D",  # Gold for STAC
        "link": "/api/interface/stac",
        "link_text": "Open STAC Browser",
        "metadata": {
            "API": "STAC API 1.0",
            "Format": "Cloud Optimized GeoTIFF",
            "Renderer": "TiTiler-pgSTAC"
        },
        "thumbnail_type": "static",
        "thumbnail_url": None
    }
]


@InterfaceRegistry.register('gallery')
class GalleryInterface(BaseInterface):
    """
    Data Gallery Interface.

    Displays a showcase of featured datasets with preview thumbnails
    and links to their respective visualization interfaces.
    """

    # Zarr dataset path for thumbnail generation (ERA5 global climate data)
    ZARR_PATH = "test-zarr/era5-global-sample.zarr"

    def render(self, request: func.HttpRequest) -> str:
        """
        Render the data gallery page.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        config = get_config()

        # Build thumbnail URL for CMIP6 Zarr dataset
        zarr_thumbnail_url = self._build_zarr_thumbnail_url(config)

        # Update gallery items with dynamic URLs
        items = self._prepare_gallery_items(zarr_thumbnail_url)

        content = self._render_gallery_content(items)

        custom_css = self._generate_css()

        return self.wrap_html(
            title="Data Gallery - Geospatial API",
            content=content,
            custom_css=custom_css
        )

    def _build_zarr_thumbnail_url(self, config) -> str:
        """
        Build thumbnail URL for the Zarr dataset using TiTiler-xarray.

        Returns a preview PNG URL that can be used as a thumbnail.
        """
        try:
            storage_account = config.storage.silver.account_name
            container = config.storage.silver.cogs
            zarr_url = f"https://{storage_account}.blob.core.windows.net/{container}/{self.ZARR_PATH}"

            titiler_url = config.titiler_base_url.rstrip('/')

            # TiTiler-xarray preview endpoint
            # Using ERA5 air temperature variable with viridis colormap
            import urllib.parse
            encoded_url = urllib.parse.quote(zarr_url, safe='')

            # Use low-zoom tile as thumbnail (no /xarray/preview endpoint exists)
            # Per WIKI.md: /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@{scale}x.{format}
            # decode_times=false required for non-standard calendars
            # bidx=1 required for temporal data (prevents aggregation noise)
            thumbnail_url = (
                f"{titiler_url}/xarray/tiles/WebMercatorQuad/0/0/0@1x.png"
                f"?url={encoded_url}"
                f"&variable=air_temperature_at_2_metres"
                f"&colormap_name=viridis"
                f"&decode_times=false"
                f"&bidx=1"
                f"&rescale=250,320"  # Kelvin range for temperature
            )

            return thumbnail_url

        except Exception:
            # Return placeholder if config not available
            return None

    def _prepare_gallery_items(self, zarr_thumbnail_url: str) -> list:
        """
        Prepare gallery items with resolved thumbnail URLs.
        """
        items = []
        for item in GALLERY_ITEMS:
            prepared = item.copy()

            if item.get("thumbnail_type") == "zarr_preview" and zarr_thumbnail_url:
                prepared["thumbnail_url"] = zarr_thumbnail_url
            elif not item.get("thumbnail_url"):
                # Use SVG placeholder for items without thumbnails
                prepared["thumbnail_url"] = None

            items.append(prepared)

        return items

    def _render_gallery_content(self, items: list) -> str:
        """Render the gallery HTML content."""
        cards_html = ""

        for item in items:
            # Build metadata rows
            metadata_html = ""
            for key, value in item.get("metadata", {}).items():
                metadata_html += f"""
                    <div class="meta-row">
                        <span class="meta-label">{key}:</span>
                        <span class="meta-value">{value}</span>
                    </div>
                """

            # Thumbnail or placeholder
            if item.get("thumbnail_url"):
                thumbnail_html = f"""
                    <div class="card-thumbnail" style="background-image: url('{item["thumbnail_url"]}');">
                        <div class="thumbnail-overlay"></div>
                    </div>
                """
            else:
                # SVG placeholder with icon
                thumbnail_html = f"""
                    <div class="card-thumbnail placeholder">
                        <div class="placeholder-icon">{item["icon"]}</div>
                        <div class="placeholder-text">Preview</div>
                    </div>
                """

            cards_html += f"""
            <div class="gallery-card">
                {thumbnail_html}
                <div class="card-content">
                    <div class="card-header">
                        <span class="source-badge" style="background: {item["source_badge_color"]};">
                            {item["source_type"]}
                        </span>
                    </div>
                    <h3 class="card-title">{item["icon"]} {item["title"]}</h3>
                    <p class="card-subtitle">{item["subtitle"]}</p>
                    <p class="card-description">{item["description"]}</p>
                    <div class="card-metadata">
                        {metadata_html}
                    </div>
                    <a href="{item["link"]}" class="card-link">
                        {item["link_text"]} <span class="arrow">→</span>
                    </a>
                </div>
            </div>
            """

        return f"""
        <div class="container">
            <div class="gallery-header">
                <h1 class="gallery-title">Data Gallery</h1>
                <p class="gallery-subtitle">
                    Interactive visualizations of featured geospatial datasets
                </p>
            </div>

            <div class="gallery-grid">
                {cards_html}
            </div>

            <div class="gallery-footer">
                <p>
                    <strong>Add Your Data:</strong> Process data via
                    <a href="/api/interface/pipeline">Pipelines</a>
                </p>
            </div>
        </div>
        """

    def _generate_css(self) -> str:
        """Generate CSS styles for the gallery."""
        return """
        /* Gallery Header */
        .gallery-header {
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, var(--ds-blue-primary) 0%, var(--ds-navy) 100%);
            color: white;
            border-radius: 8px;
            margin-bottom: 32px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }

        .gallery-title {
            font-size: 36px;
            font-weight: 700;
            margin-bottom: 12px;
        }

        .gallery-subtitle {
            font-size: 18px;
            opacity: 0.9;
            max-width: 600px;
            margin: 0 auto;
        }

        /* Gallery Grid */
        .gallery-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
            gap: 28px;
            margin-bottom: 32px;
        }

        /* Gallery Card */
        .gallery-card {
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            transition: all 0.3s ease;
            display: flex;
            flex-direction: column;
        }

        .gallery-card:hover {
            transform: translateY(-6px);
            box-shadow: 0 12px 32px rgba(0,113,188,0.18);
        }

        /* Card Thumbnail */
        .card-thumbnail {
            height: 200px;
            background-size: cover;
            background-position: center;
            position: relative;
        }

        .card-thumbnail.placeholder {
            background: linear-gradient(135deg, #e9ecef 0%, #f8f9fa 100%);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }

        .placeholder-icon {
            font-size: 64px;
            margin-bottom: 8px;
        }

        .placeholder-text {
            font-size: 14px;
            color: var(--ds-gray);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .thumbnail-overlay {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 60px;
            background: linear-gradient(transparent, rgba(0,0,0,0.3));
        }

        /* Card Content */
        .card-content {
            padding: 24px;
            display: flex;
            flex-direction: column;
            flex-grow: 1;
        }

        .card-header {
            margin-bottom: 12px;
        }

        .source-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 700;
            color: white;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .card-title {
            font-size: 22px;
            font-weight: 700;
            color: var(--ds-navy);
            margin-bottom: 6px;
        }

        .card-subtitle {
            font-size: 14px;
            color: var(--ds-blue-primary);
            font-weight: 600;
            margin-bottom: 12px;
        }

        .card-description {
            font-size: 14px;
            color: var(--ds-gray);
            line-height: 1.6;
            margin-bottom: 16px;
            flex-grow: 1;
        }

        /* Card Metadata */
        .card-metadata {
            background: var(--ds-bg);
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 16px;
        }

        .meta-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 12px;
        }

        .meta-row:not(:last-child) {
            border-bottom: 1px solid #e9ecef;
            padding-bottom: 6px;
            margin-bottom: 4px;
        }

        .meta-label {
            color: var(--ds-gray);
            font-weight: 600;
        }

        .meta-value {
            color: var(--ds-navy);
            font-family: monospace;
            font-size: 11px;
        }

        /* Card Link */
        .card-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 20px;
            background: var(--ds-blue-primary);
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.2s;
        }

        .card-link:hover {
            background: var(--ds-cyan);
            gap: 12px;
        }

        .card-link .arrow {
            transition: transform 0.2s;
        }

        .card-link:hover .arrow {
            transform: translateX(4px);
        }

        /* Gallery Footer */
        .gallery-footer {
            text-align: center;
            padding: 24px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .gallery-footer p {
            color: var(--ds-gray);
            font-size: 14px;
            margin: 0;
        }

        .gallery-footer a {
            color: var(--ds-blue-primary);
            text-decoration: none;
            font-weight: 600;
        }

        .gallery-footer a:hover {
            color: var(--ds-cyan);
            text-decoration: underline;
        }

        .gallery-footer strong {
            color: var(--ds-navy);
        }

        /* Responsive */
        @media (max-width: 768px) {
            .gallery-grid {
                grid-template-columns: 1fr;
            }

            .gallery-title {
                font-size: 28px;
            }

            .card-thumbnail {
                height: 160px;
            }
        }
        """
