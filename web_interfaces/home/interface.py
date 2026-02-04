"""
Home interface module.

Landing page for Geospatial API platform with quick actions and navigation.

Features (15 JAN 2026):
    - Dashboard header with quick action buttons
    - Submit job quick links (Upload, Vector, Raster)
    - Navigation cards to all dashboards

Exports:
    HomeInterface: Landing page interface with quick actions and dashboard links
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
from config import __version__


@InterfaceRegistry.register('home')
class HomeInterface(BaseInterface):
    """
    Home page interface for Geospatial API platform.

    Displays dashboard header with quick actions and navigation cards
    to all available dashboards and APIs.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Render home page with quick actions and navigation cards.

        Args:
            request: Azure Functions HTTP request

        Returns:
            Complete HTML page string
        """
        content = f"""
        <div class="container">
            <!-- Dashboard Header -->
            <header class="dashboard-header">
                <div class="header-content">
                    <div class="header-title">
                        <h1>Geospatial ETL Pipeline</h1>
                        <p class="subtitle">Cloud-native platform for geospatial data processing v{__version__}</p>
                    </div>
                    <div class="header-actions">
                        <a href="/api/interface/health" class="status-link">
                            <span class="status-dot"></span>
                            System Status
                        </a>
                    </div>
                </div>
            </header>

            <!-- Quick Actions Section -->
            <section class="quick-actions">
                <h2 class="section-title">Submit Data</h2>
                <div class="action-grid">
                    <a href="/api/interface/upload" class="action-card upload">
                        <div class="action-icon">📤</div>
                        <div class="action-content">
                            <h3>Upload File</h3>
                            <p>Upload files to bronze storage</p>
                        </div>
                        <div class="action-arrow">→</div>
                    </a>

                    <a href="/api/interface/submit" class="action-card vector">
                        <div class="action-icon">📤</div>
                        <div class="action-content">
                            <h3>Submit Job</h3>
                            <p>Vector, Raster, or Collection ETL</p>
                        </div>
                        <div class="action-arrow">→</div>
                    </a>
                </div>
            </section>

            <!-- Browse Data Section -->
            <section class="browse-section">
                <h2 class="section-title">Browse Data</h2>
                <div class="cards-grid">
                    <a href="/api/interface/gallery" class="card featured">
                        <div class="card-icon">🎨</div>
                        <h3 class="card-title">Data Gallery</h3>
                        <p class="card-description">Featured datasets with interactive visualizations</p>
                        <div class="card-footer">Explore Gallery</div>
                    </a>

                    <a href="/api/interface/stac" class="card">
                        <div class="card-icon">📦</div>
                        <h3 class="card-title">STAC Collections</h3>
                        <p class="card-description">Browse STAC metadata catalog for raster datasets</p>
                        <div class="card-footer">View Collections</div>
                    </a>

                    <a href="/api/interface/vector" class="card">
                        <div class="card-icon">📍</div>
                        <h3 class="card-title">OGC Features</h3>
                        <p class="card-description">Explore vector collections with map previews</p>
                        <div class="card-footer">Browse Features</div>
                    </a>

                    <a href="/api/interface/map" class="card">
                        <div class="card-icon">🗺️</div>
                        <h3 class="card-title">Map Viewer</h3>
                        <p class="card-description">Interactive Leaflet map for vector features</p>
                        <div class="card-footer">Open Map</div>
                    </a>
                </div>
            </section>

            <!-- System Section -->
            <section class="system-section">
                <h2 class="section-title">System</h2>
                <div class="cards-grid">
                    <a href="/api/interface/storage" class="card">
                        <div class="card-icon">💾</div>
                        <h3 class="card-title">Storage Browser</h3>
                        <p class="card-description">Browse Bronze, Silver, and Gold storage zones</p>
                        <div class="card-footer">Browse Storage</div>
                    </a>

                    <a href="/api/interface/jobs" class="card">
                        <div class="card-icon">⚙️</div>
                        <h3 class="card-title">Job Monitor</h3>
                        <p class="card-description">Track ETL job execution and task progress</p>
                        <div class="card-footer">Monitor Jobs</div>
                    </a>

                    <a href="/api/interface/pipeline" class="card">
                        <div class="card-icon">🔄</div>
                        <h3 class="card-title">Pipeline Status</h3>
                        <p class="card-description">View pipeline workflows and recent activity</p>
                        <div class="card-footer">View Pipelines</div>
                    </a>

                    <a href="/api/interface/health" class="card">
                        <div class="card-icon">💚</div>
                        <h3 class="card-title">System Health</h3>
                        <p class="card-description">Platform status, database, and service health</p>
                        <div class="card-footer">Check Status</div>
                    </a>

                    <a href="/api/interface/docs" class="card">
                        <div class="card-icon">📖</div>
                        <h3 class="card-title">Platform API Docs</h3>
                        <p class="card-description">B2B integration endpoints for DDH</p>
                        <div class="card-footer">View Docs</div>
                    </a>

                    <a href="/api/interface/redoc" class="card">
                        <div class="card-icon">📋</div>
                        <h3 class="card-title">ReDoc</h3>
                        <p class="card-description">OpenAPI reference documentation</p>
                        <div class="card-footer">View ReDoc</div>
                    </a>

                    <a href="/api/interface/database" class="card">
                        <div class="card-icon">🗄️</div>
                        <h3 class="card-title">Database Admin</h3>
                        <p class="card-description">Database diagnostics and maintenance</p>
                        <div class="card-footer">Open Admin</div>
                    </a>

                    <a href="/api/interface/external-services" class="card">
                        <div class="card-icon">🌐</div>
                        <h3 class="card-title">External Services</h3>
                        <p class="card-description">Register and monitor external geospatial services</p>
                        <div class="card-footer">Manage Services</div>
                    </a>
                </div>
            </section>

            <!-- Footer -->
            <footer class="footer-info">
                <p><strong>Architecture:</strong> Azure Functions (Python v2) + PostgreSQL/PostGIS + pgSTAC</p>
                <p><strong>Standards:</strong> STAC v1.0 | OGC API - Features Core 1.0</p>
                <p><strong>Storage Tiers:</strong> Bronze (raw) -> Silver (COGs/PostGIS) -> Gold (exports)</p>
            </footer>
        </div>
        """

        custom_css = """
        /* Dashboard Header */
        .dashboard-header {
            background: white;
            padding: 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            border-left: 4px solid var(--ds-blue-primary);
        }

        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
        }

        .dashboard-header h1 {
            color: var(--ds-navy);
            font-size: 28px;
            margin: 0 0 8px 0;
            font-weight: 700;
        }

        .subtitle {
            color: var(--ds-gray);
            font-size: 14px;
            margin: 0;
        }

        .status-link {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: var(--ds-bg);
            border-radius: 3px;
            text-decoration: none;
            color: var(--ds-navy);
            font-weight: 600;
            font-size: 14px;
            transition: background 0.2s;
        }

        .status-link:hover {
            background: var(--ds-gray-light);
        }

        .status-dot {
            width: 10px;
            height: 10px;
            background: #059669;
            border-radius: 50%;
            animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* Section Titles */
        .section-title {
            font-size: 18px;
            font-weight: 700;
            color: var(--ds-navy);
            margin: 0 0 20px 0;
            padding-bottom: 10px;
            border-bottom: 2px solid var(--ds-gray-light);
        }

        /* Quick Actions */
        .quick-actions {
            margin-bottom: 40px;
        }

        .action-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
        }

        .action-card {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 20px 24px;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            text-decoration: none;
            color: inherit;
            transition: all 0.2s;
            border-left: 4px solid var(--ds-blue-primary);
        }

        .action-card:hover {
            transform: translateX(4px);
            box-shadow: 0 4px 12px rgba(0,113,188,0.15);
        }

        .action-card.upload { border-left-color: #059669; }
        .action-card.vector { border-left-color: #7c3aed; }
        .action-card.raster { border-left-color: #d97706; }
        .action-card.collection { border-left-color: #0891b2; }

        .action-icon {
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--ds-bg);
            border-radius: 8px;
            font-size: 28px;
            flex-shrink: 0;
        }

        .action-card.upload .action-icon { background: #d1fae5; }
        .action-card.vector .action-icon { background: #ede9fe; }
        .action-card.raster .action-icon { background: #fef3c7; }
        .action-card.collection .action-icon { background: #cffafe; }

        .action-content {
            flex: 1;
        }

        .action-content h3 {
            font-size: 16px;
            font-weight: 700;
            color: var(--ds-navy);
            margin: 0 0 4px 0;
        }

        .action-content p {
            font-size: 13px;
            color: var(--ds-gray);
            margin: 0;
        }

        .action-arrow {
            font-size: 20px;
            color: var(--ds-gray-light);
            transition: color 0.2s, transform 0.2s;
        }

        .action-card:hover .action-arrow {
            color: var(--ds-blue-primary);
            transform: translateX(4px);
        }

        /* Browse & System Sections */
        .browse-section, .system-section {
            margin-bottom: 40px;
        }

        .cards-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
        }

        .card {
            background: white;
            border-radius: 3px;
            padding: 24px;
            text-decoration: none;
            color: inherit;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            border-left: 4px solid var(--ds-blue-primary);
            transition: all 0.2s;
            display: flex;
            flex-direction: column;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            border-left-color: var(--ds-cyan);
        }

        .card.featured {
            border-left-color: var(--ds-gold);
            background: linear-gradient(135deg, white 0%, #fffbf0 100%);
        }

        .card-icon {
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--ds-bg);
            border-radius: 6px;
            font-size: 24px;
            margin-bottom: 12px;
        }

        .card.featured .card-icon {
            background: #fef3c7;
        }

        .card-title {
            font-size: 16px;
            font-weight: 700;
            color: var(--ds-navy);
            margin-bottom: 8px;
        }

        .card-description {
            font-size: 13px;
            color: var(--ds-gray);
            line-height: 1.5;
            margin-bottom: 16px;
            flex-grow: 1;
        }

        .card-footer {
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-blue-primary);
        }

        .card:hover .card-footer {
            color: var(--ds-cyan);
        }

        /* Footer */
        .footer-info {
            text-align: center;
            padding: 24px;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .footer-info p {
            margin: 6px 0;
            color: var(--ds-gray);
            font-size: 13px;
        }

        .footer-info strong {
            color: var(--ds-navy);
        }

        /* Responsive */
        @media (max-width: 768px) {
            .header-content {
                flex-direction: column;
                align-items: flex-start;
            }

            .action-grid, .cards-grid {
                grid-template-columns: 1fr;
            }
        }
        """

        return self.wrap_html(
            title="Geospatial ETL Pipeline - Home",
            content=content,
            custom_css=custom_css,
            include_htmx=True
        )
