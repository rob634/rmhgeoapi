# ============================================================================
# EXTERNAL SERVICES INTERFACE
# ============================================================================
# STATUS: Web Interface - External geospatial service registry dashboard
# PURPOSE: Register, monitor, and manage external geospatial services
# CREATED: 23 JAN 2026
# ============================================================================
"""
External Services Interface - Service Registry Dashboard.

Provides a web interface for:
    - Registering new external geospatial services (ArcGIS, WMS, STAC, etc.)
    - Viewing registered services with health status
    - Managing services (enable/disable, force check, delete)

URL: /api/interface/external-services
"""

import json
import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface


@InterfaceRegistry.register('external-services')
class ExternalServicesInterface(BaseInterface):
    """
    External Services Registry Dashboard.

    Top section: Registration form for new services
    Bottom section: List of registered services with status and actions
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate the full page HTML."""
        return self.wrap_html(
            title="External Service Registry",
            content=self._generate_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_js(),
            include_htmx=True
        )

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """Handle HTMX partial updates."""
        if fragment == 'services-list':
            return self._render_services_list()
        elif fragment == 'register':
            return self._handle_register(request)
        elif fragment == 'check':
            return self._handle_check(request)
        elif fragment == 'delete':
            return self._handle_delete(request)
        elif fragment == 'toggle':
            return self._handle_toggle(request)
        elif fragment == 'details':
            return self._render_details(request)
        elif fragment == 'save':
            return self._handle_save(request)
        return '<div class="error">Unknown fragment</div>'

    def _generate_content(self) -> str:
        """Generate the main page content."""
        return f"""
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <h1>External Service Registry</h1>
                <p class="subtitle">Register and monitor external geospatial services (ArcGIS, WMS, WFS, STAC, etc.)</p>
            </header>

            <!-- Registration Form Section -->
            <div class="section registration-section">
                <div class="section-header">
                    <h2>Register New Service</h2>
                    <span class="section-hint">Enter a URL to auto-detect service type and capabilities</span>
                </div>
                <form id="register-form"
                      hx-post="/api/interface/external-services?fragment=register"
                      hx-target="#register-result"
                      hx-indicator="#register-spinner">
                    <div class="form-grid">
                        <div class="form-group form-group-wide">
                            <label for="url">Service URL <span class="required">*</span></label>
                            <input type="url" id="url" name="url" required
                                   placeholder="https://services.nationalmap.gov/arcgis/rest/services/wbd/MapServer">
                            <span class="field-hint">Full URL to the service endpoint</span>
                        </div>
                        <div class="form-group">
                            <label for="name">Service Name <span class="required">*</span></label>
                            <input type="text" id="name" name="name" required
                                   placeholder="USGS Watershed Boundary Dataset">
                        </div>
                        <div class="form-group">
                            <label for="check_interval">Check Interval (minutes)</label>
                            <input type="number" id="check_interval" name="check_interval"
                                   value="60" min="5" max="1440">
                            <span class="field-hint">5 min to 24 hours</span>
                        </div>
                        <div class="form-group form-group-wide">
                            <label for="description">Description</label>
                            <input type="text" id="description" name="description"
                                   placeholder="National hydrologic unit boundaries">
                        </div>
                        <div class="form-group form-group-wide">
                            <label for="tags">Tags (comma-separated)</label>
                            <input type="text" id="tags" name="tags"
                                   placeholder="hydrology, usgs, federal">
                        </div>
                    </div>
                    <div class="form-actions">
                        <button type="submit" class="btn btn-primary">
                            <span class="btn-icon">+</span> Register Service
                        </button>
                        <span id="register-spinner" class="htmx-indicator spinner"></span>
                    </div>
                </form>
                <div id="register-result"></div>
            </div>

            <!-- Services List Section -->
            <div class="section services-section">
                <div class="section-header">
                    <h2>Registered Services</h2>
                    <div class="section-actions">
                        <button class="btn btn-secondary btn-sm"
                                hx-get="/api/interface/external-services?fragment=services-list"
                                hx-target="#services-container"
                                hx-indicator="#refresh-spinner">
                            <span class="btn-icon">&#8635;</span> Refresh
                        </button>
                        <span id="refresh-spinner" class="htmx-indicator spinner"></span>
                    </div>
                </div>
                <div id="services-container" hx-get="/api/interface/external-services?fragment=services-list"
                     hx-trigger="load" hx-indicator="#initial-spinner">
                    <div class="loading-placeholder">
                        <span id="initial-spinner" class="spinner"></span> Loading services...
                    </div>
                </div>
            </div>
        </div>

        <!-- Confirmation Modal -->
        <div id="confirm-modal" class="modal hidden">
            <div class="modal-backdrop" onclick="closeModal()"></div>
            <div class="modal-content">
                <div class="modal-header">
                    <h3 id="modal-title">Confirm Action</h3>
                    <button class="modal-close" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <p id="modal-message">Are you sure?</p>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button id="modal-confirm-btn" class="btn btn-primary">Confirm</button>
                </div>
            </div>
        </div>

        <!-- Details Slide-out Panel -->
        <div id="details-panel" class="details-panel hidden">
            <div class="panel-backdrop" onclick="closeDetailsPanel()"></div>
            <div class="panel-content">
                <div class="panel-header">
                    <h3 id="panel-title">Service Details</h3>
                    <button class="panel-close" onclick="closeDetailsPanel()">&times;</button>
                </div>
                <div id="panel-body" class="panel-body">
                    <!-- Content loaded via HTMX -->
                </div>
            </div>
        </div>
        """

    def _render_services_list(self) -> str:
        """Render the services list table."""
        try:
            from infrastructure.external_service_repository import ExternalServiceRepository
            repository = ExternalServiceRepository()
            services = repository.get_all(limit=100)

            if not services:
                return """
                <div class="empty-state">
                    <div class="empty-icon">&#128269;</div>
                    <h3>No Services Registered</h3>
                    <p>Register your first external geospatial service using the form above.</p>
                </div>
                """

            rows = []
            for svc in services:
                status_class = self._get_status_class(svc.status.value if hasattr(svc.status, 'value') else svc.status)
                status_icon = self._get_status_icon(svc.status.value if hasattr(svc.status, 'value') else svc.status)
                service_type = svc.service_type.value if hasattr(svc.service_type, 'value') else svc.service_type

                # Format last check time
                last_check = 'Never'
                if svc.last_check_at:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc)
                    # Check if datetime is timezone-aware (tzinfo is not None)
                    # hasattr() always returns True since all datetimes have tzinfo attr
                    if svc.last_check_at.tzinfo is not None:
                        delta = now - svc.last_check_at
                    else:
                        delta = now - svc.last_check_at.replace(tzinfo=timezone.utc)

                    if delta.total_seconds() < 60:
                        last_check = 'Just now'
                    elif delta.total_seconds() < 3600:
                        last_check = f'{int(delta.total_seconds() / 60)} min ago'
                    elif delta.total_seconds() < 86400:
                        last_check = f'{int(delta.total_seconds() / 3600)} hr ago'
                    else:
                        last_check = f'{int(delta.total_seconds() / 86400)} days ago'

                # Format response time
                response_time = f'{svc.avg_response_ms}ms' if svc.avg_response_ms else '-'

                # Enabled/disabled toggle
                toggle_icon = '&#9208;' if svc.enabled else '&#9654;'  # pause/play
                toggle_action = 'disable' if svc.enabled else 'enable'
                toggle_title = 'Disable monitoring' if svc.enabled else 'Enable monitoring'
                enabled_class = '' if svc.enabled else 'disabled-row'

                rows.append(f"""
                <tr class="{enabled_class}" data-service-id="{svc.service_id}">
                    <td class="status-cell">
                        <span class="status-indicator {status_class}" title="{svc.status.value if hasattr(svc.status, 'value') else svc.status}">
                            {status_icon}
                        </span>
                    </td>
                    <td class="name-cell clickable"
                        hx-get="/api/interface/external-services?fragment=details&service_id={svc.service_id}"
                        hx-target="#panel-body"
                        hx-trigger="click"
                        onclick="openDetailsPanel()">
                        <div class="service-name">{svc.name}</div>
                        <div class="service-url" title="{svc.url}">{self._truncate_url(svc.url)}</div>
                    </td>
                    <td class="type-cell">
                        <span class="type-badge type-{service_type.replace('_', '-')}">{self._format_type(service_type)}</span>
                    </td>
                    <td class="confidence-cell">
                        <div class="confidence-bar" title="{svc.detection_confidence:.0%} confidence">
                            <div class="confidence-fill" style="width: {svc.detection_confidence * 100}%"></div>
                        </div>
                    </td>
                    <td class="response-cell">{response_time}</td>
                    <td class="check-cell">{last_check}</td>
                    <td class="actions-cell">
                        <button class="action-btn check-btn" title="Force health check"
                                hx-post="/api/interface/external-services?fragment=check&service_id={svc.service_id}"
                                hx-target="#services-container"
                                hx-indicator="#action-spinner-{svc.service_id[:8]}">
                            &#128269;
                        </button>
                        <button class="action-btn toggle-btn" title="{toggle_title}"
                                hx-post="/api/interface/external-services?fragment=toggle&service_id={svc.service_id}&action={toggle_action}"
                                hx-target="#services-container">
                            {toggle_icon}
                        </button>
                        <button class="action-btn delete-btn" title="Delete service"
                                onclick="confirmDelete('{svc.service_id}', '{svc.name}')">
                            &#128465;
                        </button>
                        <span id="action-spinner-{svc.service_id[:8]}" class="htmx-indicator spinner-small"></span>
                    </td>
                </tr>
                """)

            return f"""
            <div class="services-stats">
                <span class="stat">{len(services)} services registered</span>
                <span class="stat-separator">|</span>
                <span class="stat active-count">{sum(1 for s in services if (s.status.value if hasattr(s.status, 'value') else s.status) == 'active')} active</span>
                <span class="stat degraded-count">{sum(1 for s in services if (s.status.value if hasattr(s.status, 'value') else s.status) == 'degraded')} degraded</span>
                <span class="stat offline-count">{sum(1 for s in services if (s.status.value if hasattr(s.status, 'value') else s.status) == 'offline')} offline</span>
            </div>
            <table class="services-table">
                <thead>
                    <tr>
                        <th class="status-col">Status</th>
                        <th class="name-col">Service</th>
                        <th class="type-col">Type</th>
                        <th class="confidence-col">Confidence</th>
                        <th class="response-col">Avg Response</th>
                        <th class="check-col">Last Check</th>
                        <th class="actions-col">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
            """

        except Exception as e:
            return f"""
            <div class="error-state">
                <div class="error-icon">&#9888;</div>
                <h3>Error Loading Services</h3>
                <p>{str(e)}</p>
                <p class="error-hint">The database table may not exist yet. Run: <code>POST /api/dbadmin/maintenance?action=ensure&confirm=yes</code></p>
            </div>
            """

    def _handle_register(self, request: func.HttpRequest) -> str:
        """Handle service registration."""
        try:
            # Get form data
            url = request.params.get('url') or (request.form.get('url') if hasattr(request, 'form') else None)
            name = request.params.get('name') or (request.form.get('name') if hasattr(request, 'form') else None)

            # Try to parse form body
            if not url or not name:
                try:
                    body = request.get_body().decode('utf-8')
                    from urllib.parse import parse_qs
                    form_data = parse_qs(body)
                    url = url or (form_data.get('url', [None])[0])
                    name = name or (form_data.get('name', [None])[0])
                    description = form_data.get('description', [None])[0]
                    tags_str = form_data.get('tags', [''])[0]
                    check_interval = int(form_data.get('check_interval', ['60'])[0])
                except:
                    pass

            if not url:
                return '<div class="alert alert-error">URL is required</div>'
            if not name:
                return '<div class="alert alert-error">Name is required</div>'

            # Parse optional fields
            description = request.params.get('description', description if 'description' in dir() else None)
            tags_str = request.params.get('tags', tags_str if 'tags_str' in dir() else '')
            tags = [t.strip() for t in tags_str.split(',') if t.strip()] if tags_str else []
            check_interval = int(request.params.get('check_interval', check_interval if 'check_interval' in dir() else 60))

            # Register service
            from services.external_service_health import ExternalServiceHealthService
            service = ExternalServiceHealthService()
            registered = service.register_service(
                url=url,
                name=name,
                description=description,
                tags=tags,
                check_interval_minutes=check_interval
            )

            service_type = registered.service_type.value if hasattr(registered.service_type, 'value') else registered.service_type

            return f"""
            <div class="alert alert-success">
                <strong>Service registered successfully!</strong><br>
                <span class="type-badge type-{service_type.replace('_', '-')}">{self._format_type(service_type)}</span>
                detected with {registered.detection_confidence:.0%} confidence
            </div>
            <script>
                setTimeout(() => {{
                    htmx.trigger('#services-container', 'htmx:load');
                    document.getElementById('register-form').reset();
                }}, 1000);
            </script>
            """

        except Exception as e:
            return f'<div class="alert alert-error">Registration failed: {str(e)}</div>'

    def _handle_check(self, request: func.HttpRequest) -> str:
        """Handle force health check."""
        try:
            service_id = request.params.get('service_id')
            if not service_id:
                return self._render_services_list()

            from infrastructure.external_service_repository import ExternalServiceRepository
            from services.external_service_health import ExternalServiceHealthService

            repository = ExternalServiceRepository()
            service = repository.get_by_id(service_id)

            if not service:
                return self._render_services_list()

            health_service = ExternalServiceHealthService(repository=repository)
            result = health_service.check_service(service)

            # Return updated list
            return self._render_services_list()

        except Exception as e:
            return self._render_services_list()

    def _handle_delete(self, request: func.HttpRequest) -> str:
        """Handle service deletion."""
        try:
            service_id = request.params.get('service_id')
            if not service_id:
                return self._render_services_list()

            from infrastructure.external_service_repository import ExternalServiceRepository
            repository = ExternalServiceRepository()
            repository.delete(service_id)

            return self._render_services_list()

        except Exception as e:
            return self._render_services_list()

    def _handle_toggle(self, request: func.HttpRequest) -> str:
        """Handle enable/disable toggle."""
        try:
            service_id = request.params.get('service_id')
            action = request.params.get('action')  # 'enable' or 'disable'

            if not service_id or not action:
                return self._render_services_list()

            from infrastructure.external_service_repository import ExternalServiceRepository
            repository = ExternalServiceRepository()
            repository.update(service_id, {'enabled': action == 'enable'})

            return self._render_services_list()

        except Exception as e:
            return self._render_services_list()

    def _render_details(self, request: func.HttpRequest) -> str:
        """Render service details panel content."""
        try:
            service_id = request.params.get('service_id')
            edit_mode = request.params.get('edit') == 'true'

            if not service_id:
                return '<div class="panel-error">Service ID required</div>'

            from infrastructure.external_service_repository import ExternalServiceRepository
            repository = ExternalServiceRepository()
            svc = repository.get_by_id(service_id)

            if not svc:
                return '<div class="panel-error">Service not found</div>'

            service_type = svc.service_type.value if hasattr(svc.service_type, 'value') else svc.service_type
            status = svc.status.value if hasattr(svc.status, 'value') else svc.status
            status_class = self._get_status_class(status)

            # Format timestamps
            created_at = svc.created_at.strftime('%d %b %Y %H:%M') if svc.created_at else 'Unknown'
            updated_at = svc.updated_at.strftime('%d %b %Y %H:%M') if svc.updated_at else 'Unknown'
            last_check = svc.last_check_at.strftime('%d %b %Y %H:%M') if svc.last_check_at else 'Never'

            # Format tags
            tags = svc.tags if svc.tags else []
            tags_str = ', '.join(tags) if tags else ''
            tags_html = ' '.join(f'<span class="tag">{t}</span>' for t in tags) if tags else '<span class="no-tags">No tags</span>'

            # Format capabilities
            caps = svc.detected_capabilities or {}
            caps_html = self._format_capabilities(caps, service_type)

            # Format health history
            health_history = svc.health_history or []
            history_html = self._format_health_history(health_history)

            if edit_mode:
                return self._render_edit_form(svc, service_type, tags_str)

            return f"""
            <div class="details-view">
                <!-- Status Banner -->
                <div class="status-banner {status_class}">
                    <span class="status-dot"></span>
                    <span class="status-text">{status.upper()}</span>
                    <span class="type-badge type-{service_type.replace('_', '-')}">{self._format_type(service_type)}</span>
                </div>

                <!-- Service Info -->
                <div class="detail-section">
                    <h4>Service Information</h4>
                    <div class="detail-row">
                        <label>Name</label>
                        <span>{svc.name}</span>
                    </div>
                    <div class="detail-row">
                        <label>URL</label>
                        <span class="url-value"><a href="{svc.url}" target="_blank">{svc.url}</a></span>
                    </div>
                    <div class="detail-row">
                        <label>Description</label>
                        <span>{svc.description or '<em>No description</em>'}</span>
                    </div>
                    <div class="detail-row">
                        <label>Tags</label>
                        <span class="tags-list">{tags_html}</span>
                    </div>
                </div>

                <!-- Detection Info -->
                <div class="detail-section">
                    <h4>Detection</h4>
                    <div class="detail-row">
                        <label>Service Type</label>
                        <span>{self._format_type(service_type)}</span>
                    </div>
                    <div class="detail-row">
                        <label>Confidence</label>
                        <span>{svc.detection_confidence:.0%}</span>
                    </div>
                </div>

                <!-- Health Info -->
                <div class="detail-section">
                    <h4>Health Monitoring</h4>
                    <div class="detail-row">
                        <label>Enabled</label>
                        <span>{'Yes' if svc.enabled else 'No'}</span>
                    </div>
                    <div class="detail-row">
                        <label>Check Interval</label>
                        <span>{svc.check_interval_minutes} minutes</span>
                    </div>
                    <div class="detail-row">
                        <label>Last Check</label>
                        <span>{last_check}</span>
                    </div>
                    <div class="detail-row">
                        <label>Avg Response</label>
                        <span>{svc.avg_response_ms}ms</span> if svc.avg_response_ms else '<span>-</span>'
                    </div>
                    <div class="detail-row">
                        <label>Consecutive Failures</label>
                        <span class="{'failure-count' if svc.consecutive_failures > 0 else ''}">{svc.consecutive_failures}</span>
                    </div>
                    {f'<div class="detail-row"><label>Last Failure</label><span class="failure-reason">{svc.last_failure_reason}</span></div>' if svc.last_failure_reason else ''}
                </div>

                <!-- Capabilities -->
                <div class="detail-section collapsible">
                    <h4 onclick="toggleSection(this)">
                        <span class="collapse-icon">&#9654;</span> Detected Capabilities
                    </h4>
                    <div class="section-content hidden">
                        {caps_html}
                    </div>
                </div>

                <!-- Health History -->
                <div class="detail-section collapsible">
                    <h4 onclick="toggleSection(this)">
                        <span class="collapse-icon">&#9654;</span> Recent Health History
                    </h4>
                    <div class="section-content hidden">
                        {history_html}
                    </div>
                </div>

                <!-- Timestamps -->
                <div class="detail-section timestamps">
                    <div class="detail-row">
                        <label>Registered</label>
                        <span>{created_at}</span>
                    </div>
                    <div class="detail-row">
                        <label>Last Updated</label>
                        <span>{updated_at}</span>
                    </div>
                    <div class="detail-row">
                        <label>Service ID</label>
                        <span class="service-id">{svc.service_id}</span>
                    </div>
                </div>

                <!-- Actions -->
                <div class="panel-actions">
                    <button class="btn btn-primary"
                            hx-get="/api/interface/external-services?fragment=details&service_id={svc.service_id}&edit=true"
                            hx-target="#panel-body">
                        &#9998; Edit
                    </button>
                    <button class="btn btn-secondary"
                            hx-post="/api/interface/external-services?fragment=check&service_id={svc.service_id}"
                            hx-target="#services-container">
                        &#128269; Health Check
                    </button>
                    <button class="btn btn-outline" onclick="openPreviewMap('{svc.service_id}', '{service_type}', '{svc.url}')">
                        &#128506; Preview Map
                    </button>
                </div>
            </div>
            """

        except Exception as e:
            return f'<div class="panel-error">Error loading details: {str(e)}</div>'

    def _render_edit_form(self, svc, service_type: str, tags_str: str) -> str:
        """Render the edit form for a service."""
        return f"""
        <div class="edit-view">
            <form id="edit-form"
                  hx-post="/api/interface/external-services?fragment=save&service_id={svc.service_id}"
                  hx-target="#panel-body">

                <div class="edit-section">
                    <h4>Service Information</h4>

                    <div class="form-group">
                        <label for="edit-name">Name <span class="required">*</span></label>
                        <input type="text" id="edit-name" name="name" value="{svc.name}" required>
                    </div>

                    <div class="form-group">
                        <label for="edit-url">URL <span class="required">*</span></label>
                        <input type="url" id="edit-url" name="url" value="{svc.url}" required>
                        <span class="field-hint">Changing URL will re-detect service type</span>
                    </div>

                    <div class="form-group">
                        <label for="edit-description">Description</label>
                        <textarea id="edit-description" name="description" rows="3">{svc.description or ''}</textarea>
                    </div>

                    <div class="form-group">
                        <label for="edit-tags">Tags (comma-separated)</label>
                        <input type="text" id="edit-tags" name="tags" value="{tags_str}">
                    </div>
                </div>

                <div class="edit-section">
                    <h4>Health Monitoring</h4>

                    <div class="form-group">
                        <label for="edit-interval">Check Interval (minutes)</label>
                        <input type="number" id="edit-interval" name="check_interval_minutes"
                               value="{svc.check_interval_minutes}" min="5" max="1440">
                    </div>

                    <div class="form-group checkbox-group">
                        <label>
                            <input type="checkbox" name="enabled" {'checked' if svc.enabled else ''}>
                            Enable health monitoring
                        </label>
                    </div>

                    <div class="form-group checkbox-group">
                        <label>
                            <input type="checkbox" name="redetect">
                            Re-detect service type
                        </label>
                        <span class="field-hint">Probe the URL again to update detected capabilities</span>
                    </div>
                </div>

                <div class="panel-actions">
                    <button type="submit" class="btn btn-primary">
                        &#10003; Save Changes
                    </button>
                    <button type="button" class="btn btn-secondary"
                            hx-get="/api/interface/external-services?fragment=details&service_id={svc.service_id}"
                            hx-target="#panel-body">
                        Cancel
                    </button>
                </div>
            </form>
        </div>
        """

    def _handle_save(self, request: func.HttpRequest) -> str:
        """Handle saving service edits."""
        try:
            service_id = request.params.get('service_id')
            if not service_id:
                return '<div class="panel-error">Service ID required</div>'

            # Parse form data
            body = request.get_body().decode('utf-8')
            from urllib.parse import parse_qs
            form_data = parse_qs(body)

            name = form_data.get('name', [None])[0]
            url = form_data.get('url', [None])[0]
            description = form_data.get('description', [None])[0]
            tags_str = form_data.get('tags', [''])[0]
            tags = [t.strip() for t in tags_str.split(',') if t.strip()] if tags_str else []
            check_interval = int(form_data.get('check_interval_minutes', ['60'])[0])
            enabled = 'enabled' in form_data
            redetect = 'redetect' in form_data

            if not name or not url:
                return '<div class="alert alert-error">Name and URL are required</div>'

            from infrastructure.external_service_repository import ExternalServiceRepository
            repository = ExternalServiceRepository()

            # Get current service to check if URL changed
            current = repository.get_by_id(service_id)
            url_changed = current and current.url != url

            # Build update dict
            updates = {
                'name': name,
                'url': url,
                'description': description,
                'tags': tags,
                'check_interval_minutes': check_interval,
                'enabled': enabled
            }

            # Re-detect service type if requested or URL changed
            if redetect or url_changed:
                from services.external_service_detector import ExternalServiceDetector
                detector = ExternalServiceDetector()
                detection = detector.detect_service_type(url)
                updates['service_type'] = detection.service_type
                updates['detection_confidence'] = detection.confidence
                updates['detected_capabilities'] = detection.capabilities

            repository.update(service_id, updates)

            # Refresh the services list in background
            return f"""
            <div class="alert alert-success" style="margin-bottom: 15px;">
                Service updated successfully!
                {' Service type re-detected.' if (redetect or url_changed) else ''}
            </div>
            <script>
                setTimeout(() => {{
                    htmx.trigger('#services-container', 'htmx:load');
                }}, 500);
            </script>
            """ + self._render_details(request)

        except Exception as e:
            return f'<div class="alert alert-error">Error saving: {str(e)}</div>'

    def _format_capabilities(self, caps: dict, service_type: str) -> str:
        """Format detected capabilities as HTML."""
        if not caps:
            return '<p class="no-data">No capabilities detected</p>'

        html_parts = []

        # Format based on service type
        if 'layers' in caps:
            layers = caps['layers']
            if isinstance(layers, list):
                html_parts.append(f'<div class="cap-item"><strong>Layers:</strong> {len(layers)} available</div>')
                if len(layers) <= 10:
                    html_parts.append('<ul class="layer-list">')
                    for layer in layers:
                        if isinstance(layer, dict):
                            html_parts.append(f'<li>{layer.get("name", layer.get("id", "Unknown"))}</li>')
                        else:
                            html_parts.append(f'<li>{layer}</li>')
                    html_parts.append('</ul>')

        if 'formats' in caps:
            html_parts.append(f'<div class="cap-item"><strong>Formats:</strong> {", ".join(caps["formats"])}</div>')

        if 'spatial_reference' in caps:
            sr = caps['spatial_reference']
            if isinstance(sr, dict):
                html_parts.append(f'<div class="cap-item"><strong>Spatial Reference:</strong> EPSG:{sr.get("wkid", sr.get("latestWkid", "Unknown"))}</div>')
            else:
                html_parts.append(f'<div class="cap-item"><strong>Spatial Reference:</strong> {sr}</div>')

        if 'extent' in caps:
            html_parts.append(f'<div class="cap-item"><strong>Has Extent:</strong> Yes</div>')

        # Generic key-value display for other properties
        shown_keys = {'layers', 'formats', 'spatial_reference', 'extent'}
        for key, value in caps.items():
            if key not in shown_keys:
                if isinstance(value, (list, dict)):
                    html_parts.append(f'<div class="cap-item"><strong>{key}:</strong> <code>{json.dumps(value)[:100]}...</code></div>')
                else:
                    html_parts.append(f'<div class="cap-item"><strong>{key}:</strong> {value}</div>')

        return ''.join(html_parts) if html_parts else '<p class="no-data">No capabilities detected</p>'

    def _format_health_history(self, history: list) -> str:
        """Format health history as HTML."""
        if not history:
            return '<p class="no-data">No health history available</p>'

        html_parts = ['<div class="health-history">']
        for entry in history[-10:]:  # Show last 10
            timestamp = entry.get('timestamp', 'Unknown')
            status = entry.get('status', 'unknown')
            response_ms = entry.get('response_ms', '-')
            status_class = 'history-success' if status == 'active' else 'history-failure'

            html_parts.append(f'''
            <div class="history-entry {status_class}">
                <span class="history-time">{timestamp[:16] if len(timestamp) > 16 else timestamp}</span>
                <span class="history-status">{status}</span>
                <span class="history-response">{response_ms}ms</span>
            </div>
            ''')
        html_parts.append('</div>')

        return ''.join(html_parts)

    def _get_status_class(self, status: str) -> str:
        """Get CSS class for status."""
        return {
            'active': 'status-active',
            'degraded': 'status-degraded',
            'offline': 'status-offline',
            'unknown': 'status-unknown',
            'maintenance': 'status-maintenance'
        }.get(status, 'status-unknown')

    def _get_status_icon(self, status: str) -> str:
        """Get icon for status."""
        return {
            'active': '&#9679;',      # filled circle
            'degraded': '&#9679;',    # filled circle (yellow)
            'offline': '&#9679;',     # filled circle (red)
            'unknown': '&#9675;',     # empty circle
            'maintenance': '&#9679;'  # filled circle (blue)
        }.get(status, '&#9675;')

    def _format_type(self, service_type: str) -> str:
        """Format service type for display."""
        type_labels = {
            'arcgis_mapserver': 'ArcGIS Map',
            'arcgis_featureserver': 'ArcGIS Feature',
            'arcgis_imageserver': 'ArcGIS Image',
            'wms': 'WMS',
            'wfs': 'WFS',
            'wmts': 'WMTS',
            'ogc_api_features': 'OGC Features',
            'ogc_api_tiles': 'OGC Tiles',
            'stac_api': 'STAC',
            'xyz_tiles': 'XYZ Tiles',
            'tms_tiles': 'TMS Tiles',
            'cog_endpoint': 'COG',
            'generic_rest': 'REST',
            'unknown': 'Unknown'
        }
        return type_labels.get(service_type, service_type)

    def _truncate_url(self, url: str, max_length: int = 50) -> str:
        """Truncate URL for display."""
        if len(url) <= max_length:
            return url
        return url[:max_length - 3] + '...'

    def _generate_css(self) -> str:
        """Generate page-specific CSS."""
        return """
            /* Section styling */
            .section {
                background: white;
                border-radius: 8px;
                padding: 24px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }

            .section-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 2px solid var(--ds-blue-primary);
            }

            .section-header h2 {
                color: var(--ds-navy);
                font-size: 18px;
                margin: 0;
            }

            .section-hint {
                font-size: 12px;
                color: var(--ds-gray);
            }

            .section-actions {
                display: flex;
                align-items: center;
                gap: 10px;
            }

            /* Form styling */
            .form-grid {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 16px;
                margin-bottom: 20px;
            }

            .form-group-wide {
                grid-column: span 2;
            }

            .form-group label {
                display: block;
                font-weight: 600;
                margin-bottom: 6px;
                color: var(--ds-navy);
                font-size: 13px;
            }

            .form-group input {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid var(--ds-gray-light);
                border-radius: 4px;
                font-size: 14px;
                transition: border-color 0.2s;
            }

            .form-group input:focus {
                outline: none;
                border-color: var(--ds-blue-primary);
                box-shadow: 0 0 0 3px rgba(0, 113, 188, 0.1);
            }

            .field-hint {
                font-size: 11px;
                color: var(--ds-gray);
                margin-top: 4px;
                display: block;
            }

            .required {
                color: #dc3545;
            }

            .form-actions {
                display: flex;
                align-items: center;
                gap: 15px;
            }

            .btn-icon {
                font-weight: bold;
            }

            /* Services table */
            .services-stats {
                margin-bottom: 15px;
                padding: 10px 15px;
                background: var(--ds-bg);
                border-radius: 4px;
                font-size: 13px;
                color: var(--ds-gray);
            }

            .stat-separator {
                margin: 0 10px;
                color: var(--ds-gray-light);
            }

            .active-count { color: #059669; }
            .degraded-count { color: #d97706; }
            .offline-count { color: #dc2626; }

            .services-table {
                width: 100%;
                border-collapse: collapse;
            }

            .services-table th,
            .services-table td {
                padding: 12px 10px;
                text-align: left;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .services-table th {
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--ds-gray);
                font-weight: 600;
                background: var(--ds-bg);
            }

            .services-table tbody tr:hover {
                background: #f8fafc;
            }

            .disabled-row {
                opacity: 0.5;
            }

            /* Status indicators */
            .status-indicator {
                font-size: 16px;
            }

            .status-active { color: #059669; }
            .status-degraded { color: #d97706; }
            .status-offline { color: #dc2626; }
            .status-unknown { color: #9ca3af; }
            .status-maintenance { color: var(--ds-blue-primary); }

            /* Service name cell */
            .service-name {
                font-weight: 600;
                color: var(--ds-navy);
                margin-bottom: 2px;
            }

            .service-url {
                font-size: 11px;
                color: var(--ds-gray);
                font-family: monospace;
            }

            /* Type badges */
            .type-badge {
                display: inline-block;
                padding: 3px 8px;
                border-radius: 12px;
                font-size: 10px;
                font-weight: 600;
                text-transform: uppercase;
                background: var(--ds-gray-light);
                color: var(--ds-gray);
            }

            .type-arcgis-mapserver,
            .type-arcgis-featureserver,
            .type-arcgis-imageserver {
                background: #e0f2fe;
                color: #0369a1;
            }

            .type-wms, .type-wfs, .type-wmts {
                background: #fef3c7;
                color: #b45309;
            }

            .type-ogc-api-features, .type-ogc-api-tiles {
                background: #d1fae5;
                color: #047857;
            }

            .type-stac-api {
                background: #ede9fe;
                color: #6d28d9;
            }

            .type-xyz-tiles, .type-tms-tiles {
                background: #fce7f3;
                color: #be185d;
            }

            .type-cog-endpoint {
                background: #fee2e2;
                color: #b91c1c;
            }

            /* Confidence bar */
            .confidence-bar {
                width: 60px;
                height: 6px;
                background: var(--ds-gray-light);
                border-radius: 3px;
                overflow: hidden;
            }

            .confidence-fill {
                height: 100%;
                background: var(--ds-blue-primary);
                border-radius: 3px;
            }

            /* Action buttons */
            .actions-cell {
                white-space: nowrap;
            }

            .action-btn {
                background: none;
                border: 1px solid var(--ds-gray-light);
                padding: 5px 8px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                margin-right: 4px;
                transition: all 0.2s;
            }

            .action-btn:hover {
                background: var(--ds-gray-light);
            }

            .check-btn:hover { border-color: var(--ds-blue-primary); }
            .toggle-btn:hover { border-color: #d97706; }
            .delete-btn:hover { border-color: #dc2626; color: #dc2626; }

            /* Alerts */
            .alert {
                padding: 12px 16px;
                border-radius: 6px;
                margin-top: 15px;
                font-size: 14px;
            }

            .alert-success {
                background: #d1fae5;
                color: #047857;
                border: 1px solid #a7f3d0;
            }

            .alert-error {
                background: #fee2e2;
                color: #b91c1c;
                border: 1px solid #fecaca;
            }

            /* Empty/Error states */
            .empty-state, .error-state {
                text-align: center;
                padding: 60px 20px;
                color: var(--ds-gray);
            }

            .empty-icon, .error-icon {
                font-size: 48px;
                margin-bottom: 15px;
            }

            .error-state { color: #b91c1c; }
            .error-hint { margin-top: 15px; font-size: 12px; }
            .error-hint code {
                background: var(--ds-gray-light);
                padding: 2px 6px;
                border-radius: 3px;
            }

            /* Loading */
            .loading-placeholder {
                text-align: center;
                padding: 40px;
                color: var(--ds-gray);
            }

            .spinner {
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 2px solid var(--ds-gray-light);
                border-top-color: var(--ds-blue-primary);
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
            }

            .spinner-small {
                width: 14px;
                height: 14px;
                border-width: 2px;
            }

            @keyframes spin {
                to { transform: rotate(360deg); }
            }

            .htmx-indicator {
                display: none;
            }
            .htmx-request .htmx-indicator {
                display: inline-block;
            }

            /* Modal */
            .modal {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                z-index: 1000;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .modal.hidden {
                display: none;
            }

            .modal-backdrop {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
            }

            .modal-content {
                position: relative;
                background: white;
                border-radius: 8px;
                width: 90%;
                max-width: 400px;
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
            }

            .modal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 20px;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .modal-header h3 {
                margin: 0;
                font-size: 16px;
                color: var(--ds-navy);
            }

            .modal-close {
                background: none;
                border: none;
                font-size: 24px;
                color: var(--ds-gray);
                cursor: pointer;
            }

            .modal-body {
                padding: 20px;
            }

            .modal-footer {
                display: flex;
                justify-content: flex-end;
                gap: 10px;
                padding: 16px 20px;
                border-top: 1px solid var(--ds-gray-light);
            }

            /* Clickable cells */
            .clickable {
                cursor: pointer;
                transition: background 0.2s;
            }

            .clickable:hover {
                background: #f0f9ff !important;
            }

            .clickable:hover .service-name {
                color: var(--ds-blue-primary);
                text-decoration: underline;
            }

            /* Details Panel (Slide-out) */
            .details-panel {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                z-index: 1001;
                display: flex;
                justify-content: flex-end;
            }

            .details-panel.hidden {
                display: none;
            }

            .panel-backdrop {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.4);
            }

            .panel-content {
                position: relative;
                background: white;
                width: 500px;
                max-width: 90%;
                height: 100%;
                box-shadow: -5px 0 30px rgba(0, 0, 0, 0.2);
                display: flex;
                flex-direction: column;
                animation: slideIn 0.2s ease-out;
            }

            @keyframes slideIn {
                from { transform: translateX(100%); }
                to { transform: translateX(0); }
            }

            .panel-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 20px;
                border-bottom: 2px solid var(--ds-blue-primary);
                background: var(--ds-bg);
            }

            .panel-header h3 {
                margin: 0;
                font-size: 18px;
                color: var(--ds-navy);
            }

            .panel-close {
                background: none;
                border: none;
                font-size: 28px;
                color: var(--ds-gray);
                cursor: pointer;
                padding: 0 5px;
                line-height: 1;
            }

            .panel-close:hover {
                color: var(--ds-navy);
            }

            .panel-body {
                flex: 1;
                overflow-y: auto;
                padding: 20px;
            }

            /* Details View */
            .details-view, .edit-view {
                font-size: 14px;
            }

            .status-banner {
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 12px 16px;
                border-radius: 6px;
                margin-bottom: 20px;
            }

            .status-banner.status-active { background: #d1fae5; }
            .status-banner.status-degraded { background: #fef3c7; }
            .status-banner.status-offline { background: #fee2e2; }
            .status-banner.status-unknown { background: #f3f4f6; }

            .status-banner .status-dot {
                width: 12px;
                height: 12px;
                border-radius: 50%;
            }

            .status-banner.status-active .status-dot { background: #059669; }
            .status-banner.status-degraded .status-dot { background: #d97706; }
            .status-banner.status-offline .status-dot { background: #dc2626; }
            .status-banner.status-unknown .status-dot { background: #9ca3af; }

            .status-banner .status-text {
                font-weight: 700;
                font-size: 13px;
            }

            .detail-section {
                margin-bottom: 24px;
                padding-bottom: 20px;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .detail-section:last-of-type {
                border-bottom: none;
            }

            .detail-section h4 {
                font-size: 13px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--ds-gray);
                margin: 0 0 12px 0;
                font-weight: 600;
            }

            .detail-section.collapsible h4 {
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .detail-section.collapsible h4:hover {
                color: var(--ds-blue-primary);
            }

            .collapse-icon {
                font-size: 10px;
                transition: transform 0.2s;
            }

            .collapse-icon.expanded {
                transform: rotate(90deg);
            }

            .detail-row {
                display: flex;
                margin-bottom: 10px;
            }

            .detail-row label {
                width: 130px;
                flex-shrink: 0;
                color: var(--ds-gray);
                font-size: 13px;
            }

            .detail-row span {
                flex: 1;
                color: var(--ds-navy);
                word-break: break-word;
            }

            .detail-row .url-value {
                font-family: monospace;
                font-size: 12px;
            }

            .detail-row .url-value a {
                color: var(--ds-blue-primary);
            }

            .tags-list .tag {
                display: inline-block;
                padding: 2px 8px;
                background: var(--ds-gray-light);
                border-radius: 12px;
                font-size: 11px;
                margin-right: 4px;
                margin-bottom: 4px;
            }

            .no-tags {
                color: var(--ds-gray);
                font-style: italic;
            }

            .failure-count {
                color: #dc2626;
                font-weight: 600;
            }

            .failure-reason {
                color: #dc2626;
                font-size: 12px;
            }

            .timestamps {
                font-size: 12px;
            }

            .timestamps .detail-row {
                margin-bottom: 6px;
            }

            .service-id {
                font-family: monospace;
                font-size: 11px;
                color: var(--ds-gray) !important;
            }

            /* Capabilities */
            .cap-item {
                margin-bottom: 8px;
                font-size: 13px;
            }

            .cap-item code {
                background: var(--ds-gray-light);
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 11px;
            }

            .layer-list {
                margin: 8px 0 0 20px;
                padding: 0;
                font-size: 12px;
            }

            .layer-list li {
                margin-bottom: 4px;
            }

            .no-data {
                color: var(--ds-gray);
                font-style: italic;
                font-size: 13px;
            }

            /* Health History */
            .health-history {
                font-size: 12px;
            }

            .history-entry {
                display: flex;
                gap: 12px;
                padding: 6px 10px;
                margin-bottom: 4px;
                border-radius: 4px;
            }

            .history-entry.history-success {
                background: #d1fae5;
            }

            .history-entry.history-failure {
                background: #fee2e2;
            }

            .history-time {
                color: var(--ds-gray);
                width: 120px;
            }

            .history-status {
                font-weight: 600;
                width: 70px;
            }

            .history-response {
                color: var(--ds-gray);
            }

            /* Panel Actions */
            .panel-actions {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
                margin-top: 20px;
                padding-top: 20px;
                border-top: 1px solid var(--ds-gray-light);
            }

            .btn-outline {
                background: white;
                border: 1px solid var(--ds-blue-primary);
                color: var(--ds-blue-primary);
            }

            .btn-outline:hover {
                background: #f0f9ff;
            }

            /* Edit Form */
            .edit-section {
                margin-bottom: 24px;
            }

            .edit-section h4 {
                font-size: 13px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--ds-gray);
                margin: 0 0 16px 0;
                padding-bottom: 8px;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .edit-view .form-group {
                margin-bottom: 16px;
            }

            .edit-view .form-group label {
                display: block;
                margin-bottom: 6px;
                font-weight: 600;
                color: var(--ds-navy);
                font-size: 13px;
            }

            .edit-view .form-group input,
            .edit-view .form-group textarea {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid var(--ds-gray-light);
                border-radius: 4px;
                font-size: 14px;
            }

            .edit-view .form-group textarea {
                resize: vertical;
                font-family: inherit;
            }

            .edit-view .form-group input:focus,
            .edit-view .form-group textarea:focus {
                outline: none;
                border-color: var(--ds-blue-primary);
                box-shadow: 0 0 0 3px rgba(0, 113, 188, 0.1);
            }

            .checkbox-group label {
                display: flex !important;
                align-items: center;
                gap: 8px;
                font-weight: normal !important;
                cursor: pointer;
            }

            .checkbox-group input[type="checkbox"] {
                width: auto;
            }

            .panel-error {
                padding: 20px;
                text-align: center;
                color: #dc2626;
            }

            /* Responsive */
            @media (max-width: 768px) {
                .form-grid {
                    grid-template-columns: 1fr;
                }
                .form-group-wide {
                    grid-column: span 1;
                }
                .services-table {
                    font-size: 12px;
                }
                .confidence-col, .response-col {
                    display: none;
                }
                .panel-content {
                    width: 100%;
                    max-width: 100%;
                }
                .detail-row {
                    flex-direction: column;
                }
                .detail-row label {
                    width: 100%;
                    margin-bottom: 4px;
                }
            }
        """

    def _generate_js(self) -> str:
        """Generate page-specific JavaScript."""
        return """
            // Modal functions
            function confirmDelete(serviceId, serviceName) {
                document.getElementById('modal-title').textContent = 'Delete Service';
                document.getElementById('modal-message').innerHTML =
                    'Are you sure you want to delete <strong>' + serviceName + '</strong>?<br>' +
                    '<span style="color: #dc2626; font-size: 12px;">This action cannot be undone.</span>';

                const confirmBtn = document.getElementById('modal-confirm-btn');
                confirmBtn.className = 'btn btn-primary';
                confirmBtn.style.background = '#dc2626';
                confirmBtn.style.borderColor = '#dc2626';
                confirmBtn.textContent = 'Delete';
                confirmBtn.onclick = function() {
                    htmx.ajax('POST', '/api/interface/external-services?fragment=delete&service_id=' + serviceId, {
                        target: '#services-container'
                    });
                    closeModal();
                };

                document.getElementById('confirm-modal').classList.remove('hidden');
            }

            function closeModal() {
                document.getElementById('confirm-modal').classList.add('hidden');
            }

            // Details panel functions
            function openDetailsPanel() {
                document.getElementById('details-panel').classList.remove('hidden');
                document.body.style.overflow = 'hidden';  // Prevent background scrolling
            }

            function closeDetailsPanel() {
                document.getElementById('details-panel').classList.add('hidden');
                document.body.style.overflow = '';
            }

            // Collapsible sections
            function toggleSection(header) {
                const content = header.nextElementSibling;
                const icon = header.querySelector('.collapse-icon');

                if (content.classList.contains('hidden')) {
                    content.classList.remove('hidden');
                    icon.classList.add('expanded');
                } else {
                    content.classList.add('hidden');
                    icon.classList.remove('expanded');
                }
            }

            // Preview map (placeholder - will open in new window or modal)
            function openPreviewMap(serviceId, serviceType, url) {
                // For now, open a simple preview page
                // In the future, this could open a modal with an embedded Leaflet map
                const previewUrl = '/api/interface/service-preview?service_id=' + serviceId +
                                   '&type=' + encodeURIComponent(serviceType) +
                                   '&url=' + encodeURIComponent(url);

                // Check if service type is supported for preview
                const supportedTypes = [
                    'arcgis_mapserver', 'arcgis_featureserver', 'arcgis_imageserver',
                    'wms', 'wmts', 'xyz_tiles', 'tms_tiles'
                ];

                if (!supportedTypes.includes(serviceType)) {
                    alert('Preview not yet available for ' + serviceType + ' services.\\n\\n' +
                          'Supported types: ArcGIS, WMS, WMTS, XYZ/TMS Tiles');
                    return;
                }

                // Open preview in new tab (for now)
                window.open(previewUrl, '_blank');
            }

            // Close panel on escape key
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    closeModal();
                    closeDetailsPanel();
                }
            });

            // Auto-refresh every 60 seconds (only when panel is closed)
            setInterval(function() {
                if (!document.hidden && document.getElementById('details-panel').classList.contains('hidden')) {
                    htmx.trigger('#services-container', 'htmx:load');
                }
            }, 60000);
        """
