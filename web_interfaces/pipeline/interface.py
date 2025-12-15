"""
Pipeline workflows interface module.

Web dashboard showing ETL pipeline workflows, job status, and the ability to
monitor and manage data processing pipelines.

Exports:
    PipelineInterface: Pipeline workflow dashboard with job monitoring
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('pipeline')
class PipelineInterface(BaseInterface):
    """
    Pipeline Workflows interface for monitoring ETL jobs.

    Displays:
        - Available pipeline types (Vector, Raster, Raster Collection)
        - Recent job status and progress
        - Pipeline workflow diagrams
        - Quick actions to view job details
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Pipeline Workflows HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        return self.wrap_html(
            title="Pipeline Workflows",
            content=self._generate_html_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_js()
        )

    def _generate_css(self) -> str:
        """Pipeline-specific styles."""
        return """
            .dashboard-header {
                background: linear-gradient(135deg, var(--ds-navy) 0%, var(--ds-blue-dark) 100%);
                color: white;
                padding: 30px;
                border-radius: 8px;
                margin-bottom: 24px;
            }

            .dashboard-header h1 {
                margin: 0 0 8px 0;
                font-size: 28px;
            }

            .subtitle {
                opacity: 0.9;
                font-size: 16px;
                margin: 0;
            }

            .section {
                background: white;
                border-radius: 8px;
                padding: 24px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }

            .section h2 {
                color: var(--ds-navy);
                font-size: 20px;
                margin: 0 0 16px 0;
                padding-bottom: 12px;
                border-bottom: 2px solid var(--ds-blue-primary);
            }

            .pipeline-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
                gap: 20px;
            }

            .pipeline-card {
                background: var(--ds-bg);
                border: 2px solid var(--ds-gray-light);
                border-radius: 8px;
                padding: 20px;
                transition: all 0.2s;
            }

            .pipeline-card:hover {
                border-color: var(--ds-blue-primary);
                box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            }

            .pipeline-card h3 {
                color: var(--ds-navy);
                font-size: 18px;
                margin: 0 0 8px 0;
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .pipeline-card .icon {
                font-size: 24px;
            }

            .pipeline-card .description {
                color: var(--ds-gray);
                font-size: 14px;
                margin-bottom: 16px;
                line-height: 1.5;
            }

            .pipeline-stages {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 16px;
                flex-wrap: wrap;
            }

            .stage {
                background: white;
                border: 1px solid var(--ds-gray-light);
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                color: var(--ds-navy);
            }

            .stage-arrow {
                color: var(--ds-blue-primary);
                font-size: 16px;
            }

            .pipeline-stats {
                display: flex;
                gap: 16px;
                padding-top: 12px;
                border-top: 1px solid var(--ds-gray-light);
            }

            .stat {
                text-align: center;
            }

            .stat-value {
                font-size: 20px;
                font-weight: 700;
                color: var(--ds-blue-primary);
            }

            .stat-label {
                font-size: 11px;
                color: var(--ds-gray);
                text-transform: uppercase;
            }

            /* Recent Jobs Table */
            .jobs-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }

            .jobs-table th,
            .jobs-table td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .jobs-table th {
                background: var(--ds-bg);
                font-weight: 600;
                color: var(--ds-navy);
            }

            .jobs-table tr:hover {
                background: #f8f9fa;
            }

            .status-badge {
                display: inline-block;
                padding: 4px 10px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 600;
            }

            .status-badge.completed {
                background: #d4edda;
                color: #155724;
            }

            .status-badge.processing {
                background: #cce5ff;
                color: #004085;
            }

            .status-badge.pending {
                background: #fff3cd;
                color: #856404;
            }

            .status-badge.failed {
                background: #f8d7da;
                color: #721c24;
            }

            .job-type {
                font-family: monospace;
                background: var(--ds-bg);
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 12px;
            }

            .job-id {
                font-family: monospace;
                font-size: 12px;
                color: var(--ds-gray);
            }

            .job-id a {
                color: var(--ds-blue-primary);
                text-decoration: none;
            }

            .job-id a:hover {
                text-decoration: underline;
            }

            .refresh-btn {
                background: var(--ds-blue-primary);
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                margin-bottom: 16px;
            }

            .refresh-btn:hover {
                background: var(--ds-blue-dark);
            }

            .loading {
                text-align: center;
                padding: 40px;
                color: var(--ds-gray);
            }

            .empty-state {
                text-align: center;
                padding: 40px;
                color: var(--ds-gray);
            }

            /* Custom pipelines section */
            .coming-soon {
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                border: 2px dashed var(--ds-gray-light);
                border-radius: 8px;
                padding: 30px;
                text-align: center;
            }

            .coming-soon h3 {
                color: var(--ds-navy);
                margin: 0 0 8px 0;
            }

            .coming-soon p {
                color: var(--ds-gray);
                margin: 0;
            }
        """

    def _generate_html_content(self) -> str:
        """Generate main content HTML."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>Pipeline Workflows</h1>
                <p class="subtitle">Monitor and manage ETL data processing pipelines</p>
            </header>

            <!-- Available Pipelines -->
            <div class="section">
                <h2>Available Pipelines</h2>
                <div class="pipeline-grid">
                    <!-- Process Vector -->
                    <div class="pipeline-card">
                        <h3><span class="icon">🗺️</span> Process Vector</h3>
                        <p class="description">
                            Ingest vector files (GeoJSON, Shapefile, GeoPackage, CSV) into PostGIS
                            with automatic CRS detection and STAC cataloging.
                        </p>
                        <div class="pipeline-stages">
                            <span class="stage">Validate</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">Transform</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">Load PostGIS</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">STAC Catalog</span>
                        </div>
                        <div class="pipeline-stats">
                            <div class="stat">
                                <div class="stat-value" id="vector-24h">--</div>
                                <div class="stat-label">Last 24h</div>
                            </div>
                            <div class="stat">
                                <div class="stat-value" id="vector-success">--</div>
                                <div class="stat-label">Success Rate</div>
                            </div>
                        </div>
                    </div>

                    <!-- Process Raster -->
                    <div class="pipeline-card">
                        <h3><span class="icon">🛰️</span> Process Raster</h3>
                        <p class="description">
                            Convert raster files to Cloud-Optimized GeoTIFF (COG) format with
                            automatic tiling, compression, and STAC cataloging.
                        </p>
                        <div class="pipeline-stages">
                            <span class="stage">Validate</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">COG Convert</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">Upload Silver</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">STAC Catalog</span>
                        </div>
                        <div class="pipeline-stats">
                            <div class="stat">
                                <div class="stat-value" id="raster-24h">--</div>
                                <div class="stat-label">Last 24h</div>
                            </div>
                            <div class="stat">
                                <div class="stat-value" id="raster-success">--</div>
                                <div class="stat-label">Success Rate</div>
                            </div>
                        </div>
                    </div>

                    <!-- Process Raster Collection -->
                    <div class="pipeline-card">
                        <h3><span class="icon">🗂️</span> Raster Collection</h3>
                        <p class="description">
                            Process multiple raster tiles as a unified collection with MosaicJSON
                            generation for seamless visualization via TiTiler.
                        </p>
                        <div class="pipeline-stages">
                            <span class="stage">Validate All</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">Parallel COG</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">MosaicJSON</span>
                            <span class="stage-arrow">→</span>
                            <span class="stage">STAC</span>
                        </div>
                        <div class="pipeline-stats">
                            <div class="stat">
                                <div class="stat-value" id="collection-24h">--</div>
                                <div class="stat-label">Last 24h</div>
                            </div>
                            <div class="stat">
                                <div class="stat-value" id="collection-success">--</div>
                                <div class="stat-label">Success Rate</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Custom Pipelines (Coming Soon) -->
            <div class="section">
                <h2>Custom Pipelines</h2>
                <div class="coming-soon">
                    <h3>Coming Soon</h3>
                    <p>Custom pipeline definitions will appear here. Build your own ETL workflows with configurable stages.</p>
                </div>
            </div>

            <!-- Recent Jobs -->
            <div class="section">
                <h2>Recent Pipeline Jobs</h2>
                <button class="refresh-btn" onclick="loadRecentJobs()">Refresh</button>
                <div id="jobs-container">
                    <div class="loading">
                        <div class="spinner"></div>
                        <p>Loading recent jobs...</p>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_js(self) -> str:
        """JavaScript for loading job data."""
        return """
        // Pipeline job types to track
        const PIPELINE_TYPES = [
            'process_vector',
            'process_raster_v2',
            'process_raster_collection_v2',
            'process_large_raster_v2'
        ];

        async function loadRecentJobs() {
            const container = document.getElementById('jobs-container');
            container.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading...</p></div>';

            try {
                // Fetch recent jobs
                const response = await fetch(`${API_BASE_URL}/api/dbadmin/jobs?limit=20&hours=48`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const data = await response.json();
                const jobs = data.jobs || [];

                // Filter to pipeline jobs only
                const pipelineJobs = jobs.filter(job =>
                    PIPELINE_TYPES.some(type => job.job_type && job.job_type.includes(type.replace('_', '')))
                    || PIPELINE_TYPES.includes(job.job_type)
                );

                if (pipelineJobs.length === 0) {
                    container.innerHTML = '<div class="empty-state"><p>No recent pipeline jobs found.</p></div>';
                    return;
                }

                // Build table
                let html = `
                    <table class="jobs-table">
                        <thead>
                            <tr>
                                <th>Job ID</th>
                                <th>Type</th>
                                <th>Status</th>
                                <th>Stage</th>
                                <th>Created</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                pipelineJobs.forEach(job => {
                    const statusClass = job.status || 'pending';
                    const jobId = job.job_id || job.id;
                    const shortId = jobId ? jobId.substring(0, 12) + '...' : '--';
                    const created = job.created_at ? new Date(job.created_at).toLocaleString() : '--';

                    html += `
                        <tr>
                            <td class="job-id">
                                <a href="/api/interface/jobs?job_id=${jobId}" title="${jobId}">${shortId}</a>
                            </td>
                            <td><span class="job-type">${job.job_type || '--'}</span></td>
                            <td><span class="status-badge ${statusClass}">${job.status || 'unknown'}</span></td>
                            <td>${job.current_stage || job.stage || '--'}</td>
                            <td>${created}</td>
                        </tr>
                    `;
                });

                html += '</tbody></table>';
                container.innerHTML = html;

                // Update stats
                updatePipelineStats(jobs);

            } catch (error) {
                console.error('Failed to load jobs:', error);
                container.innerHTML = `<div class="empty-state"><p>Error loading jobs: ${error.message}</p></div>`;
            }
        }

        function updatePipelineStats(jobs) {
            // Calculate stats by pipeline type
            const now = new Date();
            const last24h = new Date(now - 24 * 60 * 60 * 1000);

            // Vector stats
            const vectorJobs = jobs.filter(j => j.job_type === 'process_vector');
            const vectorRecent = vectorJobs.filter(j => new Date(j.created_at) > last24h);
            const vectorSuccess = vectorJobs.filter(j => j.status === 'completed').length;
            document.getElementById('vector-24h').textContent = vectorRecent.length;
            document.getElementById('vector-success').textContent =
                vectorJobs.length > 0 ? Math.round(vectorSuccess / vectorJobs.length * 100) + '%' : '--';

            // Raster stats (includes v2 and large)
            const rasterJobs = jobs.filter(j =>
                j.job_type === 'process_raster_v2' || j.job_type === 'process_large_raster_v2'
            );
            const rasterRecent = rasterJobs.filter(j => new Date(j.created_at) > last24h);
            const rasterSuccess = rasterJobs.filter(j => j.status === 'completed').length;
            document.getElementById('raster-24h').textContent = rasterRecent.length;
            document.getElementById('raster-success').textContent =
                rasterJobs.length > 0 ? Math.round(rasterSuccess / rasterJobs.length * 100) + '%' : '--';

            // Collection stats
            const collectionJobs = jobs.filter(j => j.job_type === 'process_raster_collection_v2');
            const collectionRecent = collectionJobs.filter(j => new Date(j.created_at) > last24h);
            const collectionSuccess = collectionJobs.filter(j => j.status === 'completed').length;
            document.getElementById('collection-24h').textContent = collectionRecent.length;
            document.getElementById('collection-success').textContent =
                collectionJobs.length > 0 ? Math.round(collectionSuccess / collectionJobs.length * 100) + '%' : '--';
        }

        // Load on page ready
        document.addEventListener('DOMContentLoaded', () => {
            loadRecentJobs();
        });
        """
