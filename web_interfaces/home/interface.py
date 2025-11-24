# ============================================================================
# CLAUDE CONTEXT - HOME INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Landing page for Geospatial API platform
# PURPOSE: Provide welcome splash screen and navigation overview
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: HomeInterface
# INTERFACES: BaseInterface (inherited)
# PYDANTIC_MODELS: None
# DEPENDENCIES: web_interfaces.base.BaseInterface, InterfaceRegistry
# SOURCE: HTTP GET requests to /api/interface/home
# SCOPE: Landing page for all users
# VALIDATION: None (read-only display)
# PATTERNS: Template Method (BaseInterface), Registry Pattern
# ENTRY_POINTS: Registered as 'home' in InterfaceRegistry
# INDEX: HomeInterface:40, render:60
# ============================================================================

"""
Home Interface

Landing page for Geospatial API platform. Provides:
    - Welcome message
    - Platform overview
    - Quick links to all dashboards
    - System status summary

Route: /api/interface/home

"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('home')
class HomeInterface(BaseInterface):
    """
    Home page interface for Geospatial API platform.

    Displays welcome splash screen with navigation cards to all available
    dashboards and APIs.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Render home page with welcome message and navigation cards.

        Args:
            request: Azure Functions HTTP request

        Returns:
            Complete HTML page string
        """
        content = """
        <div class="container">
            <div class="hero">
                <h1 class="hero-title">🛰️ Geospatial ETL Pipeline</h1>
                <p class="hero-subtitle">
                    Cloud-native platform for geospatial data processing, cataloging, and distribution
                </p>
            </div>

            <div class="cards-grid">
                <!-- STAC Collections Card -->
                <a href="/api/interface/stac" class="card">
                    <div class="card-icon">📦</div>
                    <h3 class="card-title">STAC Collections</h3>
                    <p class="card-description">
                        Browse and search STAC metadata catalog for raster datasets
                    </p>
                    <div class="card-footer">View Collections →</div>
                </a>

                <!-- OGC Features Card -->
                <a href="/api/interface/vector" class="card">
                    <div class="card-icon">🗺️</div>
                    <h3 class="card-title">OGC Features</h3>
                    <p class="card-description">
                        Explore vector collections with interactive map previews
                    </p>
                    <div class="card-footer">Browse Features →</div>
                </a>

                <!-- Pipeline Dashboard Card -->
                <a href="/api/interface/pipeline" class="card">
                    <div class="card-icon">📂</div>
                    <h3 class="card-title">Pipeline Dashboard</h3>
                    <p class="card-description">
                        Browse Bronze/Silver/Gold containers and manage data staging
                    </p>
                    <div class="card-footer">View Files →</div>
                </a>

                <!-- Job Monitor Card -->
                <a href="/api/interface/jobs" class="card">
                    <div class="card-icon">⚙️</div>
                    <h3 class="card-title">Job Monitor</h3>
                    <p class="card-description">
                        Track ETL job execution and task progress in real-time
                    </p>
                    <div class="card-footer">Monitor Jobs →</div>
                </a>

                <!-- API Documentation Card -->
                <a href="/api/interface/docs" class="card">
                    <div class="card-icon">📖</div>
                    <h3 class="card-title">API Documentation</h3>
                    <p class="card-description">
                        Interactive API reference with examples and endpoints
                    </p>
                    <div class="card-footer">View Docs →</div>
                </a>

                <!-- Health Status Card -->
                <a href="/api/health" class="card">
                    <div class="card-icon">💚</div>
                    <h3 class="card-title">System Health</h3>
                    <p class="card-description">
                        Check platform status, database connections, and service health
                    </p>
                    <div class="card-footer">Check Status →</div>
                </a>
            </div>

            <div class="footer-info">
                <p><strong>Architecture:</strong> Azure Functions (Python v2) + PostgreSQL/PostGIS + pgSTAC</p>
                <p><strong>Standards:</strong> STAC v1.0 • OGC API - Features Core 1.0</p>
                <p><strong>Storage Tiers:</strong> Bronze (raw) → Silver (COGs/PostGIS) → Gold (exports)</p>
            </div>
        </div>
        """

        custom_css = """
        /* Hero Section */
        .hero {
            text-align: center;
            padding: 60px 20px;
            background: linear-gradient(135deg, var(--wb-blue-primary) 0%, var(--wb-navy) 100%);
            color: white;
            border-radius: 8px;
            margin-bottom: 40px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }

        .hero-title {
            font-size: 48px;
            font-weight: 700;
            margin-bottom: 16px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }

        .hero-subtitle {
            font-size: 20px;
            opacity: 0.95;
            max-width: 700px;
            margin: 0 auto;
            line-height: 1.6;
        }

        /* Cards Grid */
        .cards-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 24px;
            margin-bottom: 40px;
        }

        .card {
            background: white;
            border-radius: 8px;
            padding: 32px;
            text-decoration: none;
            color: inherit;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            border-left: 4px solid var(--wb-blue-primary);
            transition: all 0.3s ease;
            display: flex;
            flex-direction: column;
        }

        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0,113,188,0.2);
            border-left-color: var(--wb-cyan);
        }

        .card-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }

        .card-title {
            font-size: 22px;
            font-weight: 700;
            color: var(--wb-navy);
            margin-bottom: 12px;
        }

        .card-description {
            font-size: 15px;
            color: var(--wb-gray);
            line-height: 1.6;
            margin-bottom: 20px;
            flex-grow: 1;
        }

        .card-footer {
            font-size: 15px;
            font-weight: 600;
            color: var(--wb-blue-primary);
            transition: color 0.2s;
        }

        .card:hover .card-footer {
            color: var(--wb-cyan);
        }

        /* Footer Info */
        .footer-info {
            text-align: center;
            padding: 32px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .footer-info p {
            margin: 8px 0;
            color: var(--wb-gray);
            font-size: 14px;
        }

        .footer-info strong {
            color: var(--wb-navy);
        }
        """

        return self.wrap_html(
            title="Geospatial ETL Pipeline - Home",
            content=content,
            custom_css=custom_css
        )
