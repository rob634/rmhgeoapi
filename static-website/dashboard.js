/**
 * Geospatial Dashboard - Azure Functions Integration
 * Static website integration with Azure Functions geospatial pipeline
 */
class GeospatialDashboard {
    constructor() {
        this.functionAppUrl = 'https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net';
        this.map = null;
        this.baseLayers = {};
        this.dataLayers = new Map();
        this.jobs = new Map();
        this.currentBbox = null;
        this.pollingInterval = null;
        
        // Initialize dashboard
        this.initMap();
        this.loadConfiguration();
        this.testConnection();
        this.startJobPolling();
        
        console.log('🌍 Geospatial Dashboard initialized');
    }
    
    // =============================================
    // MAP INITIALIZATION
    // =============================================
    
    initMap() {
        // Initialize map centered on Afghanistan (your typical AOI)
        this.map = L.map('map').setView([34.5, 69.2], 6);
        
        // Base layers
        this.baseLayers.osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        });
        
        this.baseLayers.satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: '© Esri',
            maxZoom: 19
        });
        
        // Add default base layer
        this.baseLayers.osm.addTo(this.map);
        
        // Map event listeners
        this.map.on('moveend', () => this.updateBboxDisplay());
        this.map.on('zoomend', () => this.updateBboxDisplay());
        
        // Initialize bbox display
        this.updateBboxDisplay();
        
        console.log('📍 Map initialized');
    }
    
    toggleBaseLayer(layerName, show) {
        Object.values(this.baseLayers).forEach(layer => this.map.removeLayer(layer));
        
        if (show && this.baseLayers[layerName]) {
            this.baseLayers[layerName].addTo(this.map);
        }
    }
    
    updateBboxDisplay() {
        const bounds = this.map.getBounds();
        this.currentBbox = [
            bounds.getWest(),
            bounds.getSouth(),
            bounds.getEast(), 
            bounds.getNorth()
        ];
        
        const formatted = this.currentBbox.map(coord => coord.toFixed(4)).join(', ');
        document.getElementById('current-bbox').innerHTML = `
            <strong>Current Map Extent:</strong><br>
            [${formatted}]<br>
            <small>West, South, East, North</small>
        `;
    }
    
    useCurrentView() {
        this.updateBboxDisplay();
        this.showMessage('Map extent captured for job submission', 'info');
    }
    
    // =============================================
    // CONFIGURATION MANAGEMENT
    // =============================================
    
    loadConfiguration() {
        const saved = localStorage.getItem('functionAppUrl');
        if (saved) {
            this.functionAppUrl = saved;
            document.getElementById('function-app-url').value = saved;
        }
    }
    
    updateConfig() {
        const url = document.getElementById('function-app-url').value.trim();
        if (!url) {
            this.showMessage('Please enter a valid Function App URL', 'error');
            return;
        }
        
        this.functionAppUrl = url;
        localStorage.setItem('functionAppUrl', url);
        this.testConnection();
        this.showMessage('Configuration updated', 'success');
    }
    
    async testConnection() {
        const statusEl = document.getElementById('connection-status');
        statusEl.textContent = 'Status: Testing connection...';
        
        try {
            const response = await this.makeApiCall('/api/health');
            const data = await response.json();
            
            statusEl.innerHTML = `
                <strong>✅ Connected</strong><br>
                ${data.message || 'Function App is healthy'}
            `;
            statusEl.style.color = '#28a745';
        } catch (error) {
            statusEl.innerHTML = `
                <strong>❌ Connection Failed</strong><br>
                ${error.message}
            `;
            statusEl.style.color = '#dc3545';
        }
    }
    
    // =============================================
    // API COMMUNICATION
    // =============================================
    
    async makeApiCall(endpoint, options = {}) {
        const url = `${this.functionAppUrl}${endpoint}`;
        
        try {
            const response = await fetch(url, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                mode: 'cors'
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            return response;
        } catch (error) {
            console.error(`API call failed: ${url}`, error);
            throw error;
        }
    }
    
    // =============================================
    // JOB MANAGEMENT
    // =============================================
    
    async submitMapJob() {
        const operationType = document.getElementById('operation-type').value;
        const datasetId = document.getElementById('dataset-id').value.trim();
        const resourceId = document.getElementById('resource-id').value.trim();
        
        if (!datasetId || !resourceId) {
            this.showMessage('Please fill in Dataset ID and Resource ID', 'error');
            return;
        }
        
        if (!this.currentBbox) {
            this.showMessage('Please set map extent first', 'error');
            return;
        }
        
        const submitBtn = document.getElementById('submit-job-btn');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting...';
        
        try {
            const jobData = {
                operation_type: operationType,
                dataset_id: datasetId,
                resource_id: resourceId,
                version_id: 'v1.0.0',
                bbox: this.currentBbox,
                system: false
            };
            
            console.log('Submitting job:', jobData);
            
            const response = await this.makeApiCall(`/api/jobs/${operationType}`, {
                method: 'POST',
                body: JSON.stringify(jobData)
            });
            
            const result = await response.json();
            console.log('Job submitted:', result);
            
            // Track job
            this.jobs.set(result.job_id, {
                ...jobData,
                job_id: result.job_id,
                status: 'submitted',
                timestamp: new Date(),
                is_duplicate: result.is_duplicate || false
            });
            
            // Show job area on map
            this.showJobAreaOnMap(result.job_id, this.currentBbox);
            
            // Update UI
            this.updateJobsList();
            this.showMessage(`Job submitted: ${result.job_id}`, 'success');
            
        } catch (error) {
            console.error('Job submission failed:', error);
            this.showMessage(`Job submission failed: ${error.message}`, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit Job';
        }
    }
    
    showJobAreaOnMap(jobId, bbox) {
        const bounds = L.latLngBounds(
            [bbox[1], bbox[0]], // South, West
            [bbox[3], bbox[2]]  // North, East
        );
        
        const jobRect = L.rectangle(bounds, {
            color: '#0078d4',
            weight: 2,
            fillOpacity: 0.1,
            dashArray: '5, 5'
        }).addTo(this.map);
        
        jobRect.bindPopup(`
            <strong>Processing Job</strong><br>
            ID: ${jobId.substring(0, 8)}...<br>
            Status: <span id="popup-status-${jobId}">Submitted</span>
        `);
        
        // Store for later updates
        this.dataLayers.set(`job-${jobId}`, jobRect);
    }
    
    async startJobPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }
        
        this.pollingInterval = setInterval(async () => {
            await this.pollJobStatuses();
        }, 5000); // Poll every 5 seconds
        
        console.log('📊 Job polling started');
    }
    
    async pollJobStatuses() {
        for (const [jobId, job] of this.jobs) {
            if (job.status === 'completed' || job.status === 'failed') {
                continue; // Skip completed jobs
            }
            
            try {
                const response = await this.makeApiCall(`/api/jobs/${jobId}`);
                const status = await response.json();
                
                // Update job status
                job.status = status.status || 'unknown';
                job.updated_at = new Date();
                
                if (status.result_data) {
                    job.result_data = status.result_data;
                }
                
                // Handle completed jobs
                if (job.status === 'completed' && status.result_data) {
                    await this.handleCompletedJob(jobId, job, status.result_data);
                }
                
                // Update popup if exists
                const popupStatus = document.getElementById(`popup-status-${jobId}`);
                if (popupStatus) {
                    popupStatus.textContent = job.status;
                }
                
            } catch (error) {
                console.error(`Error polling job ${jobId}:`, error);
            }
        }
        
        this.updateJobsList();
    }
    
    async handleCompletedJob(jobId, job, resultData) {
        console.log(`Job ${jobId} completed:`, resultData);
        
        try {
            // Handle different job types
            switch (job.operation_type) {
                case 'cog_conversion':
                    if (resultData.cog_url) {
                        await this.addCOGLayer(jobId, resultData.cog_url);
                    }
                    break;
                    
                case 'vector_processing':
                    await this.addVectorLayer(jobId);
                    break;
                    
                case 'stac_generation':
                    // Could load STAC metadata
                    break;
                    
                default:
                    console.log(`No visualization handler for ${job.operation_type}`);
            }
        } catch (error) {
            console.error(`Error handling completed job ${jobId}:`, error);
        }
    }
    
    async addCOGLayer(jobId, cogUrl) {
        try {
            // Add COG via TiTiler (if available)
            const tiTilerUrl = `${this.functionAppUrl}/api/titiler/cog/tiles/{z}/{x}/{y}?url=${encodeURIComponent(cogUrl)}`;
            
            const cogLayer = L.tileLayer(tiTilerUrl, {
                attribution: `COG: ${jobId.substring(0, 8)}`,
                opacity: 0.8
            }).addTo(this.map);
            
            this.dataLayers.set(`cog-${jobId}`, cogLayer);
            this.updateDynamicLayersList();
            
            this.showMessage(`COG layer added for job ${jobId.substring(0, 8)}`, 'success');
        } catch (error) {
            console.error('Error adding COG layer:', error);
        }
    }
    
    async addVectorLayer(jobId) {
        try {
            const response = await this.makeApiCall(`/api/vector/${jobId}`);
            const geojson = await response.json();
            
            const vectorLayer = L.geoJSON(geojson, {
                style: {
                    color: '#ff7800',
                    weight: 2,
                    opacity: 0.8,
                    fillOpacity: 0.3
                }
            }).addTo(this.map);
            
            this.dataLayers.set(`vector-${jobId}`, vectorLayer);
            this.updateDynamicLayersList();
            
            this.showMessage(`Vector layer added for job ${jobId.substring(0, 8)}`, 'success');
        } catch (error) {
            console.error('Error adding vector layer:', error);
        }
    }
    
    // =============================================
    // UI UPDATES
    // =============================================
    
    updateJobsList() {
        const jobsListEl = document.getElementById('jobs-list');
        
        if (this.jobs.size === 0) {
            jobsListEl.innerHTML = 'No active jobs';
            return;
        }
        
        const jobsArray = Array.from(this.jobs.entries());
        jobsListEl.innerHTML = jobsArray.map(([jobId, job]) => `
            <div class="job-item status-${job.status}">
                <strong>${jobId.substring(0, 8)}...</strong>
                <br>
                <small>${job.operation_type} - ${job.status}</small>
                <br>
                <small>${job.dataset_id}/${job.resource_id}</small>
                ${job.is_duplicate ? '<br><small>⚠️ Duplicate job</small>' : ''}
            </div>
        `).join('');
    }
    
    updateDynamicLayersList() {
        const dynamicLayersEl = document.getElementById('dynamic-layers');
        const dataLayerEntries = Array.from(this.dataLayers.entries())
            .filter(([id, layer]) => !id.startsWith('job-')); // Exclude job area rectangles
        
        if (dataLayerEntries.length === 0) {
            dynamicLayersEl.innerHTML = 'No processed layers yet';
            return;
        }
        
        dynamicLayersEl.innerHTML = dataLayerEntries.map(([layerId, layer]) => `
            <div class="layer-item">
                <input type="checkbox" id="layer-${layerId}" checked 
                       onchange="dashboard.toggleDataLayer('${layerId}', this.checked)">
                <label for="layer-${layerId}">${layerId}</label>
            </div>
        `).join('');
    }
    
    toggleDataLayer(layerId, visible) {
        const layer = this.dataLayers.get(layerId);
        if (layer) {
            if (visible) {
                this.map.addLayer(layer);
            } else {
                this.map.removeLayer(layer);
            }
        }
    }
    
    showMessage(message, type = 'info') {
        // Simple message display - could be enhanced with toast notifications
        const colors = {
            success: '#28a745',
            error: '#dc3545', 
            info: '#17a2b8',
            warning: '#ffc107'
        };
        
        console.log(`${type.toUpperCase()}: ${message}`);
        
        // Could add a toast notification system here
        if (type === 'error') {
            alert(`Error: ${message}`);
        }
    }
    
    // =============================================
    // TESTING AND DEBUG FUNCTIONS
    // =============================================
    
    async testHealth() {
        try {
            const response = await this.makeApiCall('/api/health');
            const data = await response.json();
            this.showMessage(`Health check passed: ${data.message}`, 'success');
        } catch (error) {
            this.showMessage(`Health check failed: ${error.message}`, 'error');
        }
    }
    
    async testJobStatus() {
        const testJobId = 'test-job-id';
        try {
            const response = await this.makeApiCall(`/api/jobs/${testJobId}`);
            const data = await response.json();
            this.showMessage(`Job status test: ${JSON.stringify(data)}`, 'info');
        } catch (error) {
            this.showMessage(`Job status test failed: ${error.message}`, 'error');
        }
    }
    
    async loadFunctions() {
        try {
            const response = await this.makeApiCall('/api/functions');
            const functions = await response.json();
            console.log('Available functions:', functions);
            this.showMessage(`Loaded ${functions.length} functions`, 'success');
        } catch (error) {
            console.log('Functions endpoint not available:', error.message);
            this.showMessage('Functions list endpoint not implemented yet', 'warning');
        }
    }
    
    showDebugInfo() {
        const debugInfo = {
            functionAppUrl: this.functionAppUrl,
            mapCenter: this.map.getCenter(),
            mapZoom: this.map.getZoom(),
            currentBbox: this.currentBbox,
            activeJobs: this.jobs.size,
            dataLayers: this.dataLayers.size,
            localStorageItems: Object.keys(localStorage).length
        };
        
        document.getElementById('debug-output').innerHTML = 
            '<pre>' + JSON.stringify(debugInfo, null, 2) + '</pre>';
    }
    
    // =============================================
    // CLEANUP
    // =============================================
    
    destroy() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }
        console.log('🧹 Dashboard cleaned up');
    }
}

// =============================================
// UTILITY FUNCTIONS
// =============================================

// Format coordinates for display
function formatCoordinate(coord, precision = 4) {
    return parseFloat(coord).toFixed(precision);
}

// Generate UUID for job IDs (simplified)
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Handle page unload
window.addEventListener('beforeunload', () => {
    if (window.dashboard) {
        window.dashboard.destroy();
    }
});

console.log('📜 Dashboard JavaScript loaded');