# ============================================================================
# CLAUDE CONTEXT - DATA_PANEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Dashboard panel - Data asset browsing (STAC, vector, storage)
# PURPOSE: Tab 3 of the dashboard: data catalog browsing and inspection
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: DataPanel
# DEPENDENCIES: azure.functions, web_dashboard.base_panel, web_dashboard.registry
# ============================================================================
"""
Data panel for the dashboard.

Provides sub-tabs for:
    - assets: Registered assets and approval stats
    - stac: STAC collection and item browsing
    - vector: Vector/OGC Features collection browsing
    - storage: Blob storage browser (placeholder -- deferred D-5)

Exports:
    DataPanel: Registered panel class
"""

import html as html_module
import logging
import azure.functions as func

from web_dashboard.base_panel import BasePanel
from web_dashboard.registry import PanelRegistry

logger = logging.getLogger(__name__)


@PanelRegistry.register
class DataPanel(BasePanel):
    """Data browsing panel -- assets, STAC, vector, storage."""

    tab_order = 3

    def tab_name(self) -> str:
        return "data"

    def tab_label(self) -> str:
        return "Data"

    def default_section(self) -> str:
        return "assets"

    def sections(self) -> list:
        return [
            ("assets", "Assets"),
            ("stac", "STAC"),
            ("vector", "Vector"),
            ("storage", "Storage"),
        ]

    def render_section(self, request: func.HttpRequest, section: str) -> str:
        dispatch = {
            "assets": self._render_assets,
            "stac": self._render_stac,
            "vector": self._render_vector,
            "storage": self._render_storage,
        }
        handler = dispatch.get(section)
        if not handler:
            raise ValueError(f"Unknown data section: {section}")
        return handler(request)

    def render_fragment(self, request: func.HttpRequest, fragment_name: str) -> str:
        dispatch = {
            "asset-list": self._fragment_asset_list,
            "collections-list": self._fragment_collections_list,
            "items-list": self._fragment_items_list,
            "vector-collections-list": self._fragment_vector_collections_list,
        }
        handler = dispatch.get(fragment_name)
        if not handler:
            raise ValueError(f"Unknown data fragment: {fragment_name}")
        return handler(request)

    # -----------------------------------------------------------------------
    # ASSETS section
    # -----------------------------------------------------------------------

    def _render_assets(self, request: func.HttpRequest) -> str:
        """Render registered assets with approval stats."""
        # Approval stats
        ok_stats, stats_data = self.call_api(request, "/api/assets/approval-stats")
        stats_html = ""
        if ok_stats and isinstance(stats_data, dict):
            counts = {
                "Pending": stats_data.get("pending_review", stats_data.get("pending", 0)),
                "Approved": stats_data.get("approved", 0),
                "Rejected": stats_data.get("rejected", 0),
                "Total": stats_data.get("total", 0),
            }
            stats_html = self.stat_strip(counts)

        # Pending assets
        ok, data = self.call_api(request, "/api/assets/pending-review")

        if not ok:
            return stats_html + self.error_block(
                f"Failed to load assets: {data}",
                retry_url="/api/dashboard?tab=data&section=assets",
            )

        assets = []
        if isinstance(data, dict):
            assets = data.get("assets", data.get("items", []))
        elif isinstance(data, list):
            assets = data

        if not assets:
            return stats_html + self.empty_block(
                "No assets registered. Submit data via the Platform tab."
            )

        headers = ["Asset ID", "Dataset", "Type", "Version", "State", "Created"]
        rows = []
        for asset in assets:
            aid = asset.get("asset_id", asset.get("id", ""))
            dataset = asset.get("dataset_id", asset.get("identifier", "--"))
            data_type = asset.get("data_type", "--")
            version = asset.get("version_ordinal", asset.get("version", "--"))
            state = asset.get("approval_state", asset.get("status", "--"))
            created = asset.get("created_at", "")

            rows.append([
                self.truncate_id(aid),
                html_module.escape(str(dataset)),
                self.data_type_badge(data_type),
                html_module.escape(str(version)),
                self.approval_badge(state),
                self.format_date(created),
            ])

        table = self.data_table(headers, rows, table_id="assets-table")
        return stats_html + table

    def _fragment_asset_list(self, request: func.HttpRequest) -> str:
        """Fragment: asset list content only."""
        return self._render_assets(request)

    # -----------------------------------------------------------------------
    # STAC section
    # -----------------------------------------------------------------------

    def _render_stac(self, request: func.HttpRequest) -> str:
        """Render STAC collections and item browsing."""
        collection_id = request.params.get("collection_id", "")

        if collection_id:
            return self._render_stac_items(request, collection_id)

        # Show collection list
        ok, data = self.call_api(request, "/api/stac/collections")

        if not ok:
            return self.error_block(
                f"Failed to load STAC collections: {data}",
                retry_url="/api/dashboard?tab=data&section=stac",
            )

        collections = []
        if isinstance(data, dict):
            collections = data.get("collections", [])
        elif isinstance(data, list):
            collections = data

        if not collections:
            return self.empty_block("No STAC collections found.")

        # Stats
        stats = self.stat_strip({"Collections": len(collections)})

        headers = ["Collection", "Title", "Items", "Extent", "Actions"]
        rows = []
        for coll in collections:
            cid = coll.get("id", "")
            title = coll.get("title", coll.get("description", "--"))
            # Item count from numberMatched or links
            item_count = coll.get("numberMatched", coll.get("item_count", "--"))
            extent = "--"
            if "extent" in coll:
                spatial = coll["extent"].get("spatial", {}).get("bbox", [])
                if spatial and isinstance(spatial[0], list):
                    bbox = spatial[0]
                    extent = f"[{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}]"
                elif spatial:
                    extent = str(spatial)

            safe_cid = html_module.escape(str(cid))
            actions = (
                f'<a hx-get="/api/dashboard?tab=data&section=stac&collection_id={safe_cid}" '
                f'hx-target="#panel-content" hx-push-url="true" hx-swap="innerHTML" '
                f'class="btn btn-sm btn-primary">Browse Items</a>'
            )

            rows.append([
                html_module.escape(str(cid)),
                html_module.escape(str(title)[:60]),
                html_module.escape(str(item_count)),
                f'<span style="font-family:var(--ds-font-mono); font-size:11px;">{html_module.escape(str(extent))}</span>',
                actions,
            ])

        table = self.data_table(headers, rows, table_id="stac-collections-table")
        return stats + table

    def _render_stac_items(self, request: func.HttpRequest, collection_id: str) -> str:
        """Render items within a specific STAC collection."""
        safe_cid = html_module.escape(collection_id)
        limit = int(request.params.get("limit", "25"))

        header = (
            f'<div style="margin-bottom:16px; display:flex; align-items:center; gap:12px;">'
            f'<h3 class="section-heading" style="margin:0; border:none; padding:0;">'
            f'Collection: {safe_cid}</h3>'
            f'<a hx-get="/api/dashboard?tab=data&section=stac" '
            f'hx-target="#panel-content" hx-push-url="true" hx-swap="innerHTML" '
            f'class="btn btn-sm btn-secondary">Back to Collections</a>'
            f'</div>'
        )

        ok, data = self.call_api(
            request,
            f"/api/stac/collections/{collection_id}/items",
            params={"limit": str(limit)},
        )

        if not ok:
            return header + self.error_block(
                f"Failed to load items: {data}",
                retry_url=f"/api/dashboard?tab=data&section=stac&collection_id={safe_cid}",
            )

        items = []
        if isinstance(data, dict):
            items = data.get("features", data.get("items", []))
        elif isinstance(data, list):
            items = data

        if not items:
            return header + self.empty_block(
                f"No items in collection '{safe_cid}'."
            )

        headers = ["Item ID", "Type", "Geometry", "Properties", "Assets"]
        rows = []
        for item in items:
            iid = item.get("id", "")
            geom_type = "--"
            if "geometry" in item and item["geometry"]:
                geom_type = item["geometry"].get("type", "--")
            props = item.get("properties", {})
            datetime_str = props.get("datetime", "")
            asset_count = len(item.get("assets", {}))

            rows.append([
                html_module.escape(str(iid)),
                html_module.escape(str(geom_type)),
                self.format_date(datetime_str) if datetime_str else "--",
                html_module.escape(str(len(props))) + " fields",
                html_module.escape(str(asset_count)),
            ])

        table = self.data_table(headers, rows, table_id="stac-items-table")
        return header + table

    def _fragment_collections_list(self, request: func.HttpRequest) -> str:
        """Fragment: STAC collections list only."""
        return self._render_stac(request)

    def _fragment_items_list(self, request: func.HttpRequest) -> str:
        """Fragment: STAC items list for a collection."""
        collection_id = request.params.get("collection_id", "")
        if not collection_id:
            return self.empty_block("No collection ID specified.")
        return self._render_stac_items(request, collection_id)

    # -----------------------------------------------------------------------
    # VECTOR section
    # -----------------------------------------------------------------------

    def _render_vector(self, request: func.HttpRequest) -> str:
        """Render OGC Features / vector collections."""
        ok, data = self.call_api(request, "/api/features/collections")

        if not ok:
            return self.error_block(
                f"Failed to load vector collections: {data}",
                retry_url="/api/dashboard?tab=data&section=vector",
            )

        collections = []
        if isinstance(data, dict):
            collections = data.get("collections", [])
        elif isinstance(data, list):
            collections = data

        if not collections:
            return self.empty_block("No vector collections found.")

        stats = self.stat_strip({"Collections": len(collections)})

        headers = ["Collection", "Title", "Features", "CRS"]
        rows = []
        for coll in collections:
            cid = coll.get("id", coll.get("name", ""))
            title = coll.get("title", coll.get("description", "--"))
            feature_count = coll.get("numberMatched", coll.get("feature_count", "--"))
            crs = coll.get("crs", coll.get("storageCrs", "--"))
            if isinstance(crs, list):
                crs = crs[0] if crs else "--"

            rows.append([
                html_module.escape(str(cid)),
                html_module.escape(str(title)[:60]),
                html_module.escape(str(feature_count)),
                html_module.escape(str(crs)[-20:] if len(str(crs)) > 20 else str(crs)),
            ])

        table = self.data_table(headers, rows, table_id="vector-collections-table")
        return stats + table

    def _fragment_vector_collections_list(self, request: func.HttpRequest) -> str:
        """Fragment: vector collections list only."""
        return self._render_vector(request)

    # -----------------------------------------------------------------------
    # STORAGE section (deferred -- D-5)
    # -----------------------------------------------------------------------

    def _render_storage(self, request: func.HttpRequest) -> str:
        """Render storage browser placeholder."""
        return f"""<div class="empty-state">
<div class="empty-icon">--</div>
<p>Storage browser is not yet available.</p>
<p style="font-size:var(--ds-font-size-sm); color:var(--ds-gray); margin-top:8px;">
Blob storage browsing requires additional API capabilities.
This feature is planned for a future iteration (D-5).
</p>
</div>"""
