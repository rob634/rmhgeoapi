# ============================================================================
# CLAUDE CONTEXT - UNIFIED SUBMIT WEB INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Unified Platform Submit Form (Raster + Vector)
# PURPOSE: HTMX interface for Platform API submission with dry_run validation
# CREATED: 01 FEB 2026
# EXPORTS: UnifiedSubmitInterface
# DEPENDENCIES: azure.functions, web_interfaces.base
# ============================================================================
"""
Unified Submit Interface module.

Web interface for submitting Platform API requests for both raster and vector
data types with dry_run validation workflow.

Features (01 FEB 2026):
    - Data type selection (Raster Single, Raster Collection, Vector)
    - HTMX-powered file browser with dynamic extension filtering
    - dry_run validation workflow with results dialog
    - Optional collection_id field (auto-generated if not provided)
    - Multi-step workflow: Select files -> Configure -> Validate -> Submit
    - cURL generation for API debugging

Workflow:
    1. Select data type (raster/raster_collection/vector)
    2. Browse and select source files
    3. Configure DDH identifiers and options
    4. Click "Validate" for dry_run validation
    5. Review validation results
    6. Click "Submit" to create job

Exports:
    UnifiedSubmitInterface: Unified job submission interface
"""

import logging
from datetime import datetime
from typing import List, Dict, Any
import json

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)

# Valid storage zones
VALID_ZONES = ["bronze"]

# File extensions by data type
RASTER_EXTENSIONS = ['.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5']
VECTOR_EXTENSIONS = ['.csv', '.geojson', '.json', '.gpkg', '.kml', '.kmz', '.shp', '.zip']

# Collection constraints
MAX_COLLECTION_FILES = 20
MIN_COLLECTION_FILES = 2


@InterfaceRegistry.register('submit')
class UnifiedSubmitInterface(BaseInterface):
    """
    Unified Submit interface with dry_run validation workflow.

    Supports raster single, raster collection, and vector submissions
    with validation-first workflow.

    Fragments supported:
        - containers: Returns container <option> elements for zone
        - files: Returns file table rows (filtered by data type)
        - validate: Performs dry_run validation and returns result
        - submit: Handles job submission and returns result
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate Unified Submit HTML with HTMX attributes."""
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Submit Data",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """Handle HTMX partial requests for unified submit fragments."""
        if fragment == 'containers':
            return self._render_containers_fragment(request)
        elif fragment == 'files':
            return self._render_files_fragment(request)
        elif fragment == 'validate':
            return self._render_validate_fragment(request)
        elif fragment == 'submit':
            return self._render_submit_fragment(request)
        else:
            raise ValueError(f"Unknown fragment: {fragment}")

    def _render_containers_fragment(self, request: func.HttpRequest) -> str:
        """Render container options for a given zone."""
        zone = request.params.get('zone', '')

        if not zone:
            return '<option value="">Select zone first</option>'

        if zone not in VALID_ZONES:
            return f'<option value="">Invalid zone: {zone}</option>'

        try:
            from infrastructure.blob import BlobRepository

            repo = BlobRepository.for_zone(zone)
            containers = repo.list_containers()

            if not containers:
                return '<option value="">No containers in zone</option>'

            options = [f'<option value="{c["name"]}">{c["name"]}</option>' for c in containers]
            return '\n'.join(options)

        except Exception as e:
            logger.error(f"Error loading containers for zone {zone}: {e}")
            return '<option value="">Error loading containers</option>'

    def _render_files_fragment(self, request: func.HttpRequest) -> str:
        """Render file table rows filtered by data type."""
        zone = request.params.get('zone', '')
        container = request.params.get('container', '')
        prefix = request.params.get('prefix', '')
        data_type = request.params.get('data_type', 'raster')
        limit = int(request.params.get('limit', '250'))

        if not zone or not container:
            return self._render_files_error("Please select a zone and container first")

        # Determine extensions based on data type
        if data_type == 'vector':
            extensions = VECTOR_EXTENSIONS
            empty_msg = "No vector files found (.geojson, .gpkg, .zip, .csv, etc.)"
            icon = "📁"
        else:
            extensions = RASTER_EXTENSIONS
            empty_msg = "No raster files found (.tif, .tiff)"
            icon = "🗺️"

        # Is this a collection (multi-select)?
        is_collection = data_type == 'raster_collection'

        try:
            from infrastructure.blob import BlobRepository

            repo = BlobRepository.for_zone(zone)
            blobs = repo.list_blobs(
                container=container,
                prefix=prefix if prefix else "",
                limit=limit * 2
            )

            # Filter for appropriate extensions
            filtered_blobs = []
            for blob in blobs:
                name = blob.get('name', '').lower()
                if any(name.endswith(ext) for ext in extensions):
                    filtered_blobs.append(blob)
                if len(filtered_blobs) >= limit:
                    break

            if not filtered_blobs:
                return self._render_files_empty(empty_msg, icon)

            # Build table rows
            rows = []
            for i, blob in enumerate(filtered_blobs):
                size_mb = blob.get('size', 0) / (1024 * 1024)
                last_modified = blob.get('last_modified', '')
                if last_modified:
                    try:
                        from zoneinfo import ZoneInfo
                        eastern = ZoneInfo('America/New_York')
                        dt = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                        dt_eastern = dt.astimezone(eastern)
                        date_str = dt_eastern.strftime('%m/%d/%Y')
                    except Exception:
                        date_str = 'N/A'
                else:
                    date_str = 'N/A'

                name = blob.get('name', '')
                short_name = name.split('/')[-1] if '/' in name else name
                ext = short_name.split('.')[-1].upper() if '.' in short_name else 'File'

                # Size styling
                size_class = 'file-size'
                if size_mb > 1024:
                    size_class = 'file-size warning'

                if is_collection:
                    # Multi-select with checkboxes
                    row = f'''
                    <tr class="file-row" data-blob="{name}" data-size="{size_mb:.2f}">
                        <td class="checkbox-cell">
                            <input type="checkbox" class="file-checkbox"
                                   data-blob="{name}"
                                   data-size="{size_mb:.2f}"
                                   onchange="updateCollectionSelection()">
                        </td>
                        <td>
                            <div class="file-name" title="{name}">{short_name}</div>
                        </td>
                        <td>
                            <span class="{size_class}">{size_mb:.2f} MB</span>
                        </td>
                        <td>
                            <span class="file-date">{date_str}</span>
                        </td>
                        <td>
                            <span class="file-type">{ext}</span>
                        </td>
                    </tr>'''
                else:
                    # Single-select (click row)
                    row = f'''
                    <tr class="file-row"
                        onclick="selectFile('{name}', '{container}', '{zone}', {size_mb:.2f})"
                        data-blob="{name}"
                        data-size="{size_mb:.2f}">
                        <td>
                            <div class="file-name" title="{name}">{short_name}</div>
                        </td>
                        <td>
                            <span class="{size_class}">{size_mb:.2f} MB</span>
                        </td>
                        <td>
                            <span class="file-date">{date_str}</span>
                        </td>
                        <td>
                            <span class="file-type">{ext}</span>
                        </td>
                    </tr>'''
                rows.append(row)

            return '\n'.join(rows)

        except Exception as e:
            logger.error(f"Error loading files: {e}", exc_info=True)
            return self._render_files_error(str(e))

    def _render_files_empty(self, message: str, icon: str) -> str:
        """Render empty state for files table."""
        return f'''
        <tr>
            <td colspan="5">
                <div class="empty-state" style="margin: 0; box-shadow: none;">
                    <div class="icon" style="font-size: 48px;">{icon}</div>
                    <h3>No Files Found</h3>
                    <p>{message}</p>
                </div>
            </td>
        </tr>
        '''

    def _render_files_error(self, message: str) -> str:
        """Render error state for files table."""
        return f'''
        <tr>
            <td colspan="5">
                <div class="error-state" style="margin: 0; box-shadow: none;">
                    <div class="icon" style="font-size: 48px;">⚠️</div>
                    <h3>Error Loading Files</h3>
                    <p>{message}</p>
                </div>
            </td>
        </tr>
        '''

    def _render_validate_fragment(self, request: func.HttpRequest) -> str:
        """Handle dry_run validation via Platform API and return result HTML."""
        try:
            # Get form data
            body = request.get_body().decode('utf-8')
            from urllib.parse import parse_qs
            form_data = parse_qs(body)

            def get_param(key, default=None):
                values = form_data.get(key, [])
                return values[0] if values else default

            # Build the payload
            data_type = get_param('data_type', 'raster')
            dataset_id = get_param('dataset_id')
            resource_id = get_param('resource_id')
            version_id = get_param('version_id', 'v1.0')
            container_name = get_param('container_name')

            # Validate basic fields
            if not dataset_id:
                return self._render_validation_result({
                    'valid': False,
                    'warnings': ['Missing dataset_id. Please enter a DDH dataset identifier.']
                })
            if not resource_id:
                return self._render_validation_result({
                    'valid': False,
                    'warnings': ['Missing resource_id. Please enter a DDH resource identifier.']
                })

            # File handling
            if data_type == 'raster_collection':
                blob_list_json = get_param('blob_list', '[]')
                try:
                    blob_list = json.loads(blob_list_json)
                except json.JSONDecodeError:
                    blob_list = []

                if len(blob_list) < MIN_COLLECTION_FILES:
                    return self._render_validation_result({
                        'valid': False,
                        'warnings': [f'At least {MIN_COLLECTION_FILES} files required for a collection.']
                    })
                if len(blob_list) > MAX_COLLECTION_FILES:
                    return self._render_validation_result({
                        'valid': False,
                        'warnings': [f'Maximum {MAX_COLLECTION_FILES} files allowed. Selected: {len(blob_list)}']
                    })

                file_name = blob_list
            else:
                blob_name = get_param('blob_name')
                if not blob_name:
                    return self._render_validation_result({
                        'valid': False,
                        'warnings': ['No file selected. Please select a file from the browser.']
                    })
                file_name = blob_name

            # Build Platform API payload
            platform_payload = {
                'dataset_id': dataset_id,
                'resource_id': resource_id,
                'version_id': version_id,
                'container_name': container_name,
                'file_name': file_name
            }

            # Set data_type for API (raster_collection is detected by list)
            if data_type == 'vector':
                platform_payload['data_type'] = 'vector'
            else:
                platform_payload['data_type'] = 'raster'

            # Optional metadata
            title = get_param('title')
            description = get_param('description')
            access_level = get_param('access_level')
            tags = get_param('tags')

            if title:
                platform_payload['title'] = title
            if description:
                platform_payload['description'] = description
            if access_level:
                platform_payload['access_level'] = access_level
            if tags:
                platform_payload['tags'] = [t.strip() for t in tags.split(',') if t.strip()]

            # Processing options
            processing_options = {}

            # Common options
            overwrite = get_param('overwrite')
            if overwrite == 'true':
                processing_options['overwrite'] = True

            collection_id = get_param('collection_id')
            if collection_id:
                processing_options['collection_id'] = collection_id

            # Raster-specific
            if data_type in ['raster', 'raster_collection']:
                raster_type = get_param('raster_type', 'auto')
                if raster_type and raster_type != 'auto':
                    processing_options['raster_type'] = raster_type

                output_tier = get_param('output_tier', 'analysis')
                if output_tier and output_tier != 'analysis':
                    processing_options['output_tier'] = output_tier

                input_crs = get_param('input_crs')
                if input_crs:
                    processing_options['crs'] = input_crs

                use_docker = get_param('use_docker')
                if use_docker == 'on':
                    processing_options['processing_mode'] = 'docker'

            # Vector-specific (CSV columns)
            if data_type == 'vector':
                lat_name = get_param('lat_name')
                lon_name = get_param('lon_name')
                wkt_column = get_param('wkt_column')

                if lat_name:
                    processing_options['lat_column'] = lat_name
                if lon_name:
                    processing_options['lon_column'] = lon_name
                if wkt_column:
                    processing_options['wkt_column'] = wkt_column

            if processing_options:
                platform_payload['processing_options'] = processing_options

            # Call Platform API with dry_run=true
            import urllib.request
            import urllib.error
            import os

            website_hostname = os.environ.get('WEBSITE_HOSTNAME')
            if not website_hostname:
                return self._render_validation_result({
                    'valid': False,
                    'warnings': ['WEBSITE_HOSTNAME not set - cannot call Platform API']
                })

            platform_api_url = f"https://{website_hostname}/api/platform/submit?dry_run=true"

            logger.info(f"[UnifiedSubmit] Validating via Platform API (dry_run=true)")
            req_data = json.dumps(platform_payload).encode('utf-8')
            http_request = urllib.request.Request(
                platform_api_url,
                data=req_data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            try:
                with urllib.request.urlopen(http_request, timeout=30) as response:
                    response_data = json.loads(response.read().decode('utf-8'))
                    logger.info(f"[UnifiedSubmit] Validation response: {response_data}")

                    # Extract validation result
                    validation = response_data.get('validation', {})
                    is_valid = validation.get('valid', True)
                    warnings = validation.get('warnings', [])

                    # Add success info
                    if is_valid:
                        suggested = validation.get('suggested_params', {})
                        lineage_exists = validation.get('lineage_exists', False)

                        return self._render_validation_result({
                            'valid': True,
                            'warnings': warnings,
                            'info': {
                                'dataset_id': dataset_id,
                                'resource_id': resource_id,
                                'version_id': version_id,
                                'data_type': data_type,
                                'file_count': len(file_name) if isinstance(file_name, list) else 1,
                                'lineage_exists': lineage_exists,
                                'suggested_params': suggested
                            }
                        })
                    else:
                        return self._render_validation_result({
                            'valid': False,
                            'warnings': warnings
                        })

            except urllib.error.HTTPError as http_err:
                error_body = http_err.read().decode('utf-8')
                try:
                    error_json = json.loads(error_body)
                    error_msg = error_json.get('error', str(http_err))
                    validation = error_json.get('validation', {})
                    warnings = validation.get('warnings', [error_msg])
                except Exception:
                    warnings = [error_body or str(http_err)]
                logger.error(f"[UnifiedSubmit] Validation error: {http_err.code} - {warnings}")
                return self._render_validation_result({
                    'valid': False,
                    'warnings': warnings
                })

            except urllib.error.URLError as url_err:
                logger.error(f"[UnifiedSubmit] Platform API connection error: {url_err}")
                return self._render_validation_result({
                    'valid': False,
                    'warnings': [f"Could not connect to Platform API: {url_err}"]
                })

        except Exception as e:
            logger.error(f"Error validating submission: {e}", exc_info=True)
            return self._render_validation_result({
                'valid': False,
                'warnings': [str(e)]
            })

    def _render_validation_result(self, result: dict) -> str:
        """Render validation result dialog."""
        is_valid = result.get('valid', False)
        warnings = result.get('warnings', [])
        info = result.get('info', {})

        if is_valid:
            icon = "✅"
            title = "Validation Passed"
            status_class = "success"
            action_text = "Ready to submit. Click 'Submit Job' below to create the job."

            # Build info rows
            info_rows = ""
            if info:
                info_rows = f'''
                <div class="validation-info">
                    <div class="info-row">
                        <span class="info-label">Dataset/Resource:</span>
                        <span class="info-value">{info.get('dataset_id', '')}/{info.get('resource_id', '')}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Version:</span>
                        <span class="info-value">{info.get('version_id', 'v1.0')}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Data Type:</span>
                        <span class="info-value">{info.get('data_type', 'unknown').replace('_', ' ').title()}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">File(s):</span>
                        <span class="info-value">{info.get('file_count', 1)} file(s)</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Lineage:</span>
                        <span class="info-value">{'Existing (new version)' if info.get('lineage_exists') else 'New dataset'}</span>
                    </div>
                </div>
                '''

            warnings_html = ""
            if warnings:
                warnings_html = '<div class="validation-warnings">'
                for w in warnings:
                    warnings_html += f'<div class="warning-item">⚠️ {w}</div>'
                warnings_html += '</div>'

            return f'''
            <div class="validation-result {status_class}">
                <div class="result-header">
                    <span class="result-icon">{icon}</span>
                    <span class="result-title">{title}</span>
                </div>
                {info_rows}
                {warnings_html}
                <div class="result-action">{action_text}</div>
            </div>
            '''
        else:
            icon = "❌"
            title = "Validation Failed"
            status_class = "error"

            warnings_html = '<div class="validation-errors">'
            for w in warnings:
                warnings_html += f'<div class="error-item">{w}</div>'
            warnings_html += '</div>'

            return f'''
            <div class="validation-result {status_class}">
                <div class="result-header">
                    <span class="result-icon">{icon}</span>
                    <span class="result-title">{title}</span>
                </div>
                {warnings_html}
                <div class="result-action">Fix the issues above and try again.</div>
            </div>
            '''

    def _render_submit_fragment(self, request: func.HttpRequest) -> str:
        """Handle actual job submission via Platform API."""
        try:
            # Get form data
            body = request.get_body().decode('utf-8')
            from urllib.parse import parse_qs
            form_data = parse_qs(body)

            def get_param(key, default=None):
                values = form_data.get(key, [])
                return values[0] if values else default

            # Build the payload (same as validate but without dry_run)
            data_type = get_param('data_type', 'raster')
            dataset_id = get_param('dataset_id')
            resource_id = get_param('resource_id')
            version_id = get_param('version_id', 'v1.0')
            container_name = get_param('container_name')

            # Basic validation
            if not dataset_id:
                return self._render_submit_error("Missing dataset_id")
            if not resource_id:
                return self._render_submit_error("Missing resource_id")

            # File handling
            if data_type == 'raster_collection':
                blob_list_json = get_param('blob_list', '[]')
                try:
                    blob_list = json.loads(blob_list_json)
                except json.JSONDecodeError:
                    blob_list = []
                file_name = blob_list
            else:
                blob_name = get_param('blob_name')
                file_name = blob_name

            if not file_name or (isinstance(file_name, list) and len(file_name) == 0):
                return self._render_submit_error("No file selected")

            # Build Platform API payload
            platform_payload = {
                'dataset_id': dataset_id,
                'resource_id': resource_id,
                'version_id': version_id,
                'container_name': container_name,
                'file_name': file_name
            }

            if data_type == 'vector':
                platform_payload['data_type'] = 'vector'
            else:
                platform_payload['data_type'] = 'raster'

            # Optional metadata
            title = get_param('title')
            description = get_param('description')
            access_level = get_param('access_level')
            tags = get_param('tags')

            if title:
                platform_payload['title'] = title
            if description:
                platform_payload['description'] = description
            if access_level:
                platform_payload['access_level'] = access_level
            if tags:
                platform_payload['tags'] = [t.strip() for t in tags.split(',') if t.strip()]

            # Processing options
            processing_options = {}

            overwrite = get_param('overwrite')
            if overwrite == 'true':
                processing_options['overwrite'] = True

            collection_id = get_param('collection_id')
            if collection_id:
                processing_options['collection_id'] = collection_id

            if data_type in ['raster', 'raster_collection']:
                raster_type = get_param('raster_type', 'auto')
                if raster_type and raster_type != 'auto':
                    processing_options['raster_type'] = raster_type

                output_tier = get_param('output_tier', 'analysis')
                if output_tier and output_tier != 'analysis':
                    processing_options['output_tier'] = output_tier

                input_crs = get_param('input_crs')
                if input_crs:
                    processing_options['crs'] = input_crs

                use_docker = get_param('use_docker')
                if use_docker == 'on':
                    processing_options['processing_mode'] = 'docker'

            if data_type == 'vector':
                lat_name = get_param('lat_name')
                lon_name = get_param('lon_name')
                wkt_column = get_param('wkt_column')

                if lat_name:
                    processing_options['lat_column'] = lat_name
                if lon_name:
                    processing_options['lon_column'] = lon_name
                if wkt_column:
                    processing_options['wkt_column'] = wkt_column

            if processing_options:
                platform_payload['processing_options'] = processing_options

            # Call Platform API (no dry_run)
            import urllib.request
            import urllib.error
            import os

            website_hostname = os.environ.get('WEBSITE_HOSTNAME')
            if not website_hostname:
                return self._render_submit_error("WEBSITE_HOSTNAME not set")

            platform_api_url = f"https://{website_hostname}/api/platform/submit"

            logger.info(f"[UnifiedSubmit] Submitting to Platform API")
            req_data = json.dumps(platform_payload).encode('utf-8')
            http_request = urllib.request.Request(
                platform_api_url,
                data=req_data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            try:
                with urllib.request.urlopen(http_request, timeout=30) as response:
                    response_data = json.loads(response.read().decode('utf-8'))

                    if response_data.get('success'):
                        return self._render_submit_success({
                            'request_id': response_data.get('request_id'),
                            'job_id': response_data.get('job_id'),
                            'job_type': response_data.get('job_type'),
                            'status': 'accepted'
                        }, platform_payload, data_type)
                    else:
                        return self._render_submit_error(
                            response_data.get('error', 'Platform API returned failure')
                        )

            except urllib.error.HTTPError as http_err:
                error_body = http_err.read().decode('utf-8')
                try:
                    error_json = json.loads(error_body)
                    error_msg = error_json.get('error', str(http_err))
                except Exception:
                    error_msg = error_body or str(http_err)
                logger.error(f"[UnifiedSubmit] Platform API error: {http_err.code} - {error_msg}")
                return self._render_submit_error(f"Platform API error ({http_err.code}): {error_msg}")

            except urllib.error.URLError as url_err:
                logger.error(f"[UnifiedSubmit] Platform API connection error: {url_err}")
                return self._render_submit_error(f"Could not connect to Platform API: {url_err}")

        except Exception as e:
            logger.error(f"Error submitting job: {e}", exc_info=True)
            return self._render_submit_error(str(e))

    def _render_submit_success(self, result: dict, payload: dict, data_type: str) -> str:
        """Render successful submission result."""
        request_id = result.get('request_id', 'N/A')
        job_id = result.get('job_id', 'N/A')
        job_type = result.get('job_type', 'unknown')
        status = result.get('status', 'accepted')

        if status == 'exists':
            title = "Request Already Processed (Idempotent)"
        else:
            title = "Job Submitted Successfully"

        file_name = payload.get('file_name', 'N/A')
        file_count = len(file_name) if isinstance(file_name, list) else 1

        data_type_display = data_type.replace('_', ' ').title()

        return f'''
        <div class="submit-result success">
            <div class="result-icon">✅</div>
            <h3>{title}</h3>
            <div class="result-details">
                <div class="detail-row">
                    <span class="detail-label">Request ID</span>
                    <span class="detail-value mono">{request_id}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Job ID</span>
                    <span class="detail-value mono">{job_id}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Job Type</span>
                    <span class="detail-value mono">{job_type}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Data Type</span>
                    <span class="detail-value">{data_type_display}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">DDH Identifier</span>
                    <span class="detail-value">{payload.get('dataset_id')}/{payload.get('resource_id')}/{payload.get('version_id')}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">File(s)</span>
                    <span class="detail-value">{file_count} file(s)</span>
                </div>
            </div>
            <div class="result-actions">
                <a href="/api/interface/tasks?job_id={job_id}" class="btn btn-primary">Workflow Monitor</a>
                <button onclick="resetForm()" class="btn btn-secondary">Submit Another</button>
            </div>
        </div>
        '''

    def _render_submit_error(self, message: str) -> str:
        """Render submission error."""
        return f'''
        <div class="submit-result error">
            <div class="result-icon">❌</div>
            <h3>Submission Failed</h3>
            <p class="error-message">{message}</p>
            <button onclick="dismissError()" class="btn btn-secondary">
                Dismiss
            </button>
        </div>
        '''

    def _generate_html_content(self) -> str:
        """Generate HTML content with unified submit form."""
        return f"""
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <h1>Submit Data</h1>
                <p class="subtitle">Upload raster or vector data via Platform API with validation</p>
            </header>

            <!-- Data Type Selection -->
            <div class="type-selector">
                <div class="type-selector-label">Data Type:</div>
                <div class="type-options">
                    <label class="type-option selected" data-type="raster">
                        <input type="radio" name="data_type" value="raster" checked>
                        <span class="type-icon">🗺️</span>
                        <span class="type-name">Single Raster</span>
                        <span class="type-desc">One GeoTIFF to COG</span>
                    </label>
                    <label class="type-option" data-type="raster_collection">
                        <input type="radio" name="data_type" value="raster_collection">
                        <span class="type-icon">🗺️🗺️</span>
                        <span class="type-name">Raster Collection</span>
                        <span class="type-desc">Multiple tiles to STAC collection</span>
                    </label>
                    <label class="type-option" data-type="vector">
                        <input type="radio" name="data_type" value="vector">
                        <span class="type-icon">📁</span>
                        <span class="type-name">Vector</span>
                        <span class="type-desc">GeoJSON, CSV, GPKG to PostGIS</span>
                    </label>
                </div>
            </div>

            <div class="two-column-layout">
                <!-- Left Column: File Browser -->
                <div class="browser-section">
                    <div class="section-header">
                        <h2>1. Select Source File(s)</h2>
                        <p class="section-subtitle" id="file-browser-hint">Select a raster file</p>
                    </div>

                    <!-- Controls -->
                    <div class="controls-grid">
                        <div class="controls-row">
                            <div class="control-group">
                                <label>Zone:</label>
                                <div class="zone-badge-bronze">BRONZE (Source Data)</div>
                                <input type="hidden" id="zone-select" name="zone" value="bronze">
                            </div>

                            <div class="control-group">
                                <label for="container-select">Container:</label>
                                <select id="container-select" name="container" class="filter-select"
                                        hx-get="/api/interface/submit?fragment=containers&zone=bronze"
                                        hx-trigger="load"
                                        hx-target="this"
                                        hx-swap="innerHTML"
                                        hx-indicator="#container-spinner"
                                        onchange="updateLoadButton()">
                                    <option value="">Loading containers...</option>
                                </select>
                                <span id="container-spinner" class="htmx-indicator spinner-sm"></span>
                            </div>
                        </div>

                        <div class="controls-row">
                            <div class="control-group filter-group">
                                <label for="prefix-input">Path Filter:</label>
                                <input type="text" id="prefix-input" name="prefix" class="filter-input"
                                       placeholder="e.g., uploads/">
                            </div>

                            <button id="load-btn" class="refresh-button" disabled
                                    hx-get="/api/interface/submit?fragment=files"
                                    hx-target="#files-tbody"
                                    hx-trigger="click"
                                    hx-indicator="#loading-spinner"
                                    hx-include="#zone-select, #container-select, #prefix-input, [name='data_type']:checked"
                                    onclick="showFilesTable()">
                                Load Files
                            </button>
                        </div>
                    </div>

                    <!-- Selection Stats Banner (for collections) -->
                    <div id="selection-banner" class="selection-banner hidden">
                        <div class="selection-stats">
                            <span id="selection-count">0 files selected</span>
                            <span id="selection-size">(0 MB total)</span>
                        </div>
                        <div class="selection-actions">
                            <button type="button" class="btn-link" onclick="selectAllFiles()">Select All</button>
                            <span class="separator">|</span>
                            <button type="button" class="btn-link" onclick="clearSelection()">Clear All</button>
                        </div>
                    </div>

                    <!-- Files Table -->
                    <div class="files-section">
                        <div id="loading-spinner" class="htmx-indicator spinner"></div>

                        <table class="files-table hidden" id="files-table">
                            <thead id="files-thead">
                                <tr>
                                    <th>Name</th>
                                    <th>Size</th>
                                    <th>Modified</th>
                                    <th>Type</th>
                                </tr>
                            </thead>
                            <tbody id="files-tbody">
                            </tbody>
                        </table>

                        <!-- Initial State -->
                        <div id="initial-state" class="empty-state">
                            <div class="icon" id="initial-icon">🗺️</div>
                            <h3>Select a Container</h3>
                            <p>Choose a container from the Bronze zone to browse files</p>
                            <p class="supported-formats" id="supported-formats">Supported: .tif, .tiff</p>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Job Form -->
                <div class="form-section">
                    <div class="section-header">
                        <h2>2. Configure Request</h2>
                        <p class="section-subtitle">Set identifiers and options</p>
                    </div>

                    <form id="submit-form">
                        <!-- Hidden fields -->
                        <input type="hidden" id="form_data_type" name="data_type" value="raster">
                        <input type="hidden" id="blob_name" name="blob_name" value="">
                        <input type="hidden" id="blob_list" name="blob_list" value="[]">
                        <input type="hidden" id="container_name" name="container_name" value="">

                        <!-- Selected File Display -->
                        <div class="form-group">
                            <label>Selected File(s)</label>
                            <div id="selected-file" class="selected-file-display">
                                <span class="placeholder">No file selected - click a file in the browser</span>
                            </div>
                        </div>

                        <!-- DDH Identifiers Section -->
                        <div class="ddh-section">
                            <div class="form-group-header">DDH Identifiers (Required)</div>
                            <div class="form-group required">
                                <label for="dataset_id">Dataset ID *</label>
                                <input type="text" id="dataset_id" name="dataset_id" required
                                       placeholder="e.g., aerial-imagery-2024"
                                       pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
                                       title="Lowercase letters, numbers, hyphens. No leading/trailing hyphens.">
                            </div>

                            <div class="form-row">
                                <div class="form-group required">
                                    <label for="resource_id">Resource ID *</label>
                                    <input type="text" id="resource_id" name="resource_id" required
                                           placeholder="e.g., site-alpha"
                                           pattern="[a-z0-9][a-z0-9-]*[a-z0-9]">
                                </div>
                                <div class="form-group">
                                    <label for="version_id">Version ID</label>
                                    <input type="text" id="version_id" name="version_id"
                                           value="v1.0"
                                           placeholder="e.g., v1.0">
                                </div>
                            </div>
                        </div>

                        <!-- STAC Configuration -->
                        <div class="stac-section">
                            <div class="form-group-header">STAC Configuration</div>
                            <div class="stac-fields">
                                <div class="form-group">
                                    <label for="collection_id">Collection ID (optional)</label>
                                    <input type="text" id="collection_id" name="collection_id"
                                           placeholder="Auto-generated from DDH IDs if empty">
                                    <span class="field-hint">STAC collection to add item(s) to</span>
                                </div>
                            </div>
                        </div>

                        <!-- Metadata Section -->
                        <div class="metadata-section-open">
                            <div class="form-group-header">Metadata (Optional)</div>
                            <div class="metadata-fields">
                                <div class="form-group">
                                    <label for="title">Title</label>
                                    <input type="text" id="title" name="title"
                                           placeholder="Human-readable title">
                                </div>
                                <div class="form-group">
                                    <label for="description">Description</label>
                                    <textarea id="description" name="description" rows="2"
                                              placeholder="Dataset description"></textarea>
                                </div>
                                <div class="form-row">
                                    <div class="form-group">
                                        <label for="access_level">Access Level</label>
                                        <select id="access_level" name="access_level">
                                            <option value="">Not specified</option>
                                            <option value="OUO">OUO</option>
                                            <option value="PUBLIC">PUBLIC</option>
                                            <option value="restricted">Restricted</option>
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label for="tags">Tags</label>
                                        <input type="text" id="tags" name="tags"
                                               placeholder="e.g., aerial, rgb">
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Raster Processing Parameters -->
                        <div id="raster-options" class="processing-section">
                            <div class="form-group-header">Raster Processing</div>
                            <div class="processing-fields">
                                <div class="form-row">
                                    <div class="form-group">
                                        <label for="raster_type">Raster Type</label>
                                        <select id="raster_type" name="raster_type">
                                            <option value="auto" selected>Auto-detect</option>
                                            <option value="dem">DEM</option>
                                            <option value="rgb">RGB</option>
                                            <option value="rgba">RGBA</option>
                                            <option value="multispectral">Multispectral</option>
                                            <option value="categorical">Categorical</option>
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label for="output_tier">Output Tier</label>
                                        <select id="output_tier" name="output_tier">
                                            <option value="analysis" selected>Analysis (LZW)</option>
                                            <option value="visualization">Visualization (JPEG)</option>
                                            <option value="archive">Archive (DEFLATE)</option>
                                        </select>
                                    </div>
                                </div>
                                <div class="form-group">
                                    <label for="input_crs">Input CRS (optional)</label>
                                    <input type="text" id="input_crs" name="input_crs"
                                           placeholder="e.g., EPSG:32618">
                                </div>
                                <div class="form-group checkbox-group">
                                    <label>
                                        <input type="checkbox" id="use_docker" name="use_docker" checked>
                                        Use Docker Worker (recommended)
                                    </label>
                                </div>
                            </div>
                        </div>

                        <!-- Vector Processing Parameters -->
                        <div id="vector-options" class="processing-section hidden">
                            <div class="form-group-header">Vector Processing (CSV)</div>
                            <div class="processing-fields">
                                <div id="csv-fields">
                                    <div class="form-row">
                                        <div class="form-group">
                                            <label for="lat_name">Latitude Column</label>
                                            <input type="text" id="lat_name" name="lat_name"
                                                   placeholder="e.g., lat, latitude, y">
                                        </div>
                                        <div class="form-group">
                                            <label for="lon_name">Longitude Column</label>
                                            <input type="text" id="lon_name" name="lon_name"
                                                   placeholder="e.g., lon, longitude, x">
                                        </div>
                                    </div>
                                    <div class="form-group-or">OR</div>
                                    <div class="form-group">
                                        <label for="wkt_column">WKT Column</label>
                                        <input type="text" id="wkt_column" name="wkt_column"
                                               placeholder="e.g., geometry, geom">
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Common Options -->
                        <div class="common-options">
                            <div class="form-group checkbox-group">
                                <label>
                                    <input type="checkbox" id="overwrite" name="overwrite" value="true">
                                    Overwrite if data exists
                                </label>
                            </div>
                        </div>

                        <!-- Validation Result Area -->
                        <div id="validation-result" class="validation-result-container hidden">
                        </div>

                        <!-- cURL Section -->
                        <div class="curl-section-prominent" id="curl-section">
                            <div class="curl-section-header">
                                <span class="curl-title">Platform API cURL</span>
                                <button type="button" class="btn btn-sm btn-copy" onclick="copyCurl()">
                                    <span id="copy-icon">📋</span> Copy
                                </button>
                            </div>
                            <pre id="curl-command" class="curl-code">Fill in required fields to see the cURL command</pre>
                        </div>

                        <!-- Action Buttons -->
                        <div class="form-actions">
                            <button type="button" id="validate-btn" class="btn btn-secondary" disabled
                                    hx-post="/api/interface/submit?fragment=validate"
                                    hx-target="#validation-result"
                                    hx-include="#submit-form"
                                    hx-indicator="#validate-spinner"
                                    onclick="showValidationResult()">
                                🔍 Validate (dry run)
                                <span id="validate-spinner" class="htmx-indicator spinner-inline"></span>
                            </button>
                            <button type="button" id="submit-btn" class="btn btn-primary" disabled
                                    hx-post="/api/interface/submit?fragment=submit"
                                    hx-target="#submit-result"
                                    hx-include="#submit-form"
                                    hx-indicator="#submit-spinner"
                                    onclick="showSubmitResult()">
                                🚀 Submit Job
                                <span id="submit-spinner" class="htmx-indicator spinner-inline"></span>
                            </button>
                        </div>
                    </form>

                    <!-- Submit Result Display -->
                    <div id="submit-result" class="submit-result-container hidden">
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for unified submit interface."""
        return """
        /* Type Selector */
        .type-selector {
            background: white;
            border-radius: 6px;
            padding: 16px 24px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .type-selector-label {
            font-size: 14px;
            font-weight: 600;
            color: var(--ds-navy);
        }

        .type-options {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }

        .type-option {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 12px 20px;
            border: 2px solid var(--ds-gray-light);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            background: white;
            min-width: 140px;
        }

        .type-option:hover {
            border-color: var(--ds-blue-primary);
            background: #f8fafc;
        }

        .type-option.selected {
            border-color: var(--ds-blue-primary);
            background: #f0f7ff;
        }

        .type-option input[type="radio"] {
            display: none;
        }

        .type-icon {
            font-size: 24px;
            margin-bottom: 4px;
        }

        .type-name {
            font-weight: 600;
            font-size: 13px;
            color: var(--ds-navy);
        }

        .type-desc {
            font-size: 11px;
            color: var(--ds-gray);
            text-align: center;
        }

        /* Two-column layout */
        .two-column-layout {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }

        @media (max-width: 1200px) {
            .two-column-layout {
                grid-template-columns: 1fr;
            }
        }

        /* Section styling */
        .section-header {
            margin-bottom: 16px;
        }

        .section-header h2 {
            font-size: 18px;
            color: var(--ds-navy);
            margin-bottom: 4px;
        }

        .section-subtitle {
            font-size: 13px;
            color: var(--ds-gray);
            margin: 0;
        }

        .browser-section, .form-section {
            background: white;
            border-radius: 6px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        /* Controls */
        .controls-grid {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 16px;
        }

        .controls-row {
            display: flex;
            gap: 16px;
            align-items: flex-end;
        }

        .control-group {
            display: flex;
            flex-direction: column;
            gap: 4px;
            position: relative;
            flex: 1;
        }

        .control-group label {
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .zone-badge-bronze {
            background: #cd7f32;
            color: white;
            padding: 8px 12px;
            border-radius: 3px;
            font-weight: 600;
            text-align: center;
            font-size: 13px;
        }

        .filter-input, .filter-select {
            padding: 8px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 3px;
            font-size: 14px;
            color: var(--ds-navy);
            width: 100%;
        }

        /* Selection banner */
        .selection-banner {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f0f7ff;
            border: 1px solid var(--ds-blue-primary);
            border-radius: 4px;
            padding: 10px 16px;
            margin-bottom: 12px;
        }

        .selection-stats {
            font-size: 14px;
            font-weight: 600;
            color: var(--ds-blue-primary);
        }

        .selection-actions {
            display: flex;
            gap: 8px;
            align-items: center;
        }

        .btn-link {
            background: none;
            border: none;
            color: var(--ds-blue-primary);
            cursor: pointer;
            font-size: 13px;
            text-decoration: underline;
        }

        /* Files table */
        .files-section {
            max-height: 400px;
            overflow-y: auto;
        }

        .files-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        .files-table thead {
            background: var(--ds-bg);
            position: sticky;
            top: 0;
        }

        .files-table th {
            text-align: left;
            padding: 10px 12px;
            font-weight: 600;
            color: var(--ds-navy);
            border-bottom: 2px solid var(--ds-gray-light);
            font-size: 11px;
            text-transform: uppercase;
        }

        .checkbox-cell {
            text-align: center;
            width: 40px;
        }

        .files-table td {
            padding: 8px 12px;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .files-table tbody tr {
            cursor: pointer;
            transition: background 0.2s;
        }

        .files-table tbody tr:hover {
            background: var(--ds-bg);
        }

        .files-table tbody tr.selected {
            background: #E6F3FF;
            border-left: 3px solid var(--ds-blue-primary);
        }

        .file-name {
            font-weight: 500;
            color: var(--ds-blue-primary);
            word-break: break-all;
        }

        .file-size, .file-date {
            font-size: 12px;
            color: var(--ds-gray);
        }

        .file-size.warning {
            color: var(--ds-status-pending-fg);
            font-weight: 600;
        }

        .file-type {
            display: inline-block;
            padding: 2px 6px;
            background: var(--ds-bg);
            border-radius: 3px;
            font-size: 10px;
            font-weight: 600;
            color: var(--ds-gray);
        }

        .supported-formats {
            font-size: 12px;
            color: var(--ds-gray);
            margin-top: 8px;
        }

        /* Form styles */
        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 6px;
        }

        .form-group input[type="text"],
        .form-group input[type="number"],
        .form-group textarea,
        .form-group select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            font-size: 14px;
            color: var(--ds-navy);
            background: white;
        }

        .form-group input:focus,
        .form-group textarea:focus,
        .form-group select:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 2px rgba(0, 113, 188, 0.1);
        }

        .field-hint {
            display: block;
            font-size: 11px;
            color: var(--ds-gray);
            margin-top: 4px;
        }

        /* Checkbox group */
        .checkbox-group label {
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            font-weight: 400;
        }

        .checkbox-group input[type="checkbox"] {
            width: 16px;
            height: 16px;
        }

        /* Selected file display */
        .selected-file-display {
            padding: 12px;
            background: var(--ds-bg);
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            color: var(--ds-navy);
            word-break: break-all;
            max-height: 100px;
            overflow-y: auto;
        }

        .selected-file-display .placeholder {
            color: var(--ds-gray);
            font-family: inherit;
            font-style: italic;
        }

        .selected-file-display .file-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .selected-file-display .file-path {
            font-weight: 600;
            color: var(--ds-blue-primary);
        }

        .selected-file-display .file-meta {
            font-size: 11px;
            color: var(--ds-gray);
        }

        .file-list {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }

        .file-tag {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 3px;
            padding: 4px 8px;
            font-size: 11px;
            color: var(--ds-navy);
        }

        /* Sections */
        .ddh-section {
            background: #f0f7ff;
            border: 1px solid var(--ds-blue-primary);
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 16px;
        }

        .ddh-section .form-group-header {
            color: var(--ds-blue-primary);
            margin-bottom: 12px;
        }

        .stac-section,
        .metadata-section-open,
        .processing-section,
        .common-options {
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            margin-bottom: 16px;
            background: white;
        }

        .stac-section .form-group-header,
        .metadata-section-open .form-group-header,
        .processing-section .form-group-header {
            padding: 12px 16px;
            background: var(--ds-bg);
            border-bottom: 1px solid var(--ds-gray-light);
            border-radius: 6px 6px 0 0;
            margin-bottom: 0;
        }

        .stac-fields,
        .metadata-fields,
        .processing-fields {
            padding: 16px;
        }

        .common-options {
            padding: 16px;
        }

        .form-group-header {
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .form-group-or {
            text-align: center;
            color: var(--ds-gray);
            font-size: 12px;
            font-weight: 600;
            padding: 8px 0;
        }

        /* Validation result */
        .validation-result-container {
            margin: 16px 0;
        }

        .validation-result {
            padding: 16px;
            border-radius: 6px;
        }

        .validation-result.success {
            background: #ecfdf5;
            border: 1px solid #10b981;
        }

        .validation-result.error {
            background: #fef2f2;
            border: 1px solid #ef4444;
        }

        .result-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 12px;
        }

        .result-icon {
            font-size: 24px;
        }

        .result-title {
            font-size: 16px;
            font-weight: 600;
            color: var(--ds-navy);
        }

        .validation-info {
            background: white;
            border-radius: 4px;
            padding: 12px;
            margin-bottom: 12px;
        }

        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            border-bottom: 1px solid #f0f0f0;
        }

        .info-row:last-child {
            border-bottom: none;
        }

        .info-label {
            font-weight: 500;
            color: var(--ds-gray);
            font-size: 13px;
        }

        .info-value {
            color: var(--ds-navy);
            font-size: 13px;
        }

        .validation-warnings,
        .validation-errors {
            margin-bottom: 12px;
        }

        .warning-item {
            padding: 8px 12px;
            background: #fffbeb;
            border: 1px solid #f59e0b;
            border-radius: 4px;
            color: #92400e;
            font-size: 13px;
            margin-bottom: 8px;
        }

        .error-item {
            padding: 8px 12px;
            background: #fef2f2;
            border: 1px solid #ef4444;
            border-radius: 4px;
            color: #dc2626;
            font-size: 13px;
            margin-bottom: 8px;
        }

        .result-action {
            font-size: 13px;
            color: var(--ds-gray);
            font-style: italic;
        }

        /* cURL section */
        .curl-section-prominent {
            background: #1e293b;
            border-radius: 8px;
            padding: 16px;
            margin: 20px 0;
        }

        .curl-section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .curl-title {
            color: #e2e8f0;
            font-weight: 600;
            font-size: 14px;
        }

        .curl-code {
            background: #0f172a;
            color: #e2e8f0;
            padding: 16px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
            margin: 0;
            max-height: 200px;
        }

        .btn-copy {
            background: #334155;
            border: 1px solid #475569;
            color: #e2e8f0;
            padding: 4px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }

        .btn-copy:hover {
            background: var(--ds-blue-primary);
            border-color: var(--ds-blue-primary);
        }

        /* Form actions */
        .form-actions {
            display: flex;
            gap: 12px;
            align-items: center;
            margin-top: 20px;
        }

        .btn {
            padding: 12px 24px;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            border: none;
        }

        .btn-primary {
            background: var(--ds-blue-primary);
            color: white;
        }

        .btn-primary:hover:not(:disabled) {
            background: var(--ds-cyan);
        }

        .btn-primary:disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        .btn-secondary {
            background: white;
            color: var(--ds-blue-primary);
            border: 1px solid var(--ds-blue-primary);
        }

        .btn-secondary:hover:not(:disabled) {
            background: var(--ds-bg);
        }

        .btn-secondary:disabled {
            background: #f5f5f5;
            color: #999;
            border-color: #ccc;
            cursor: not-allowed;
        }

        /* Spinners */
        .spinner-sm {
            width: 16px;
            height: 16px;
            border: 2px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            position: absolute;
            right: -24px;
            bottom: 10px;
        }

        .spinner-inline {
            width: 16px;
            height: 16px;
            border: 2px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        /* Submit result */
        .submit-result-container {
            margin-top: 20px;
        }

        .submit-result {
            padding: 20px;
            border-radius: 6px;
            text-align: center;
        }

        .submit-result.success {
            background: var(--ds-status-completed-bg);
            border: 1px solid var(--ds-status-completed-fg);
        }

        .submit-result.error {
            background: var(--ds-status-failed-bg);
            border: 1px solid var(--ds-status-failed-fg);
        }

        .submit-result .result-icon {
            font-size: 48px;
            margin-bottom: 12px;
        }

        .submit-result h3 {
            margin: 0 0 16px 0;
            color: var(--ds-navy);
        }

        .result-details {
            background: white;
            border-radius: 4px;
            padding: 16px;
            text-align: left;
            margin-bottom: 16px;
        }

        .result-details .detail-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .result-details .detail-row:last-child {
            border-bottom: none;
        }

        .result-details .detail-label {
            font-weight: 600;
            color: var(--ds-gray);
        }

        .result-details .detail-value {
            color: var(--ds-navy);
        }

        .result-details .mono {
            font-family: 'Courier New', monospace;
            font-size: 12px;
        }

        .result-actions {
            display: flex;
            gap: 12px;
            justify-content: center;
        }

        .error-message {
            color: var(--ds-status-failed-fg);
            margin-bottom: 16px;
        }

        .refresh-button {
            padding: 8px 16px;
            background: var(--ds-blue-primary);
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }

        .refresh-button:hover:not(:disabled) {
            background: var(--ds-cyan);
        }

        .refresh-button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate JavaScript for unified submit interface."""
        return f"""
        // State
        let currentDataType = 'raster';
        let selectedFiles = [];
        const MAX_FILES = {MAX_COLLECTION_FILES};
        const MIN_FILES = {MIN_COLLECTION_FILES};

        // Initialize on load
        document.addEventListener('DOMContentLoaded', () => {{
            // Type selector click handlers
            document.querySelectorAll('.type-option').forEach(opt => {{
                opt.addEventListener('click', () => {{
                    selectDataType(opt.dataset.type);
                }});
            }});

            // Form input listeners
            const formInputs = ['dataset_id', 'resource_id', 'version_id', 'title',
                                'description', 'access_level', 'tags', 'collection_id',
                                'raster_type', 'output_tier', 'input_crs', 'use_docker',
                                'lat_name', 'lon_name', 'wkt_column', 'overwrite'];
            formInputs.forEach(id => {{
                const el = document.getElementById(id);
                if (el) {{
                    el.addEventListener('input', updateFormState);
                    el.addEventListener('change', updateFormState);
                }}
            }});

            // Initial state
            updateFormState();
        }});

        // Select data type
        function selectDataType(type) {{
            currentDataType = type;

            // Update UI
            document.querySelectorAll('.type-option').forEach(opt => {{
                opt.classList.toggle('selected', opt.dataset.type === type);
            }});

            // Update hidden input
            document.getElementById('form_data_type').value = type;

            // Update file browser hint
            const hint = document.getElementById('file-browser-hint');
            const icon = document.getElementById('initial-icon');
            const formats = document.getElementById('supported-formats');

            if (type === 'vector') {{
                hint.textContent = 'Select a vector file';
                icon.textContent = '📁';
                formats.innerHTML = 'Supported: .geojson, .json, .gpkg, .kml, .kmz, .zip (Shapefile), .csv*<br><small style="color: #6b7280;">*CSV requires WKT column OR latitude+longitude columns</small>';
            }} else if (type === 'raster_collection') {{
                hint.textContent = 'Select 2-{MAX_COLLECTION_FILES} raster files';
                icon.textContent = '🗺️';
                formats.textContent = 'Supported: .tif, .tiff';
            }} else {{
                hint.textContent = 'Select a raster file';
                icon.textContent = '🗺️';
                formats.textContent = 'Supported: .tif, .tiff';
            }}

            // Show/hide options sections
            document.getElementById('raster-options').classList.toggle('hidden', type === 'vector');
            document.getElementById('vector-options').classList.toggle('hidden', type !== 'vector');

            // Show/hide selection banner
            document.getElementById('selection-banner').classList.toggle('hidden', type !== 'raster_collection');

            // Update table header for collection (add checkbox column)
            const thead = document.getElementById('files-thead');
            if (type === 'raster_collection') {{
                thead.innerHTML = `<tr>
                    <th class="checkbox-cell"><input type="checkbox" id="select-all-checkbox" onchange="toggleSelectAll(this)"></th>
                    <th>Name</th><th>Size</th><th>Modified</th><th>Type</th>
                </tr>`;
            }} else {{
                thead.innerHTML = '<tr><th>Name</th><th>Size</th><th>Modified</th><th>Type</th></tr>';
            }}

            // Clear selection
            selectedFiles = [];
            document.getElementById('blob_name').value = '';
            document.getElementById('blob_list').value = '[]';
            document.getElementById('selected-file').innerHTML = '<span class="placeholder">No file selected - click a file in the browser</span>';

            // Reload files if container is selected
            const container = document.getElementById('container-select').value;
            if (container) {{
                document.getElementById('load-btn').click();
            }}

            updateFormState();
        }}

        // Update load button
        function updateLoadButton() {{
            const container = document.getElementById('container-select').value;
            document.getElementById('load-btn').disabled = !container;
        }}

        // Show files table
        function showFilesTable() {{
            document.getElementById('initial-state')?.classList.add('hidden');
            document.getElementById('files-table')?.classList.remove('hidden');
            selectedFiles = [];
            updateSelectionDisplay();
        }}

        // Single file selection (click)
        function selectFile(blobName, container, zone, sizeMb) {{
            document.getElementById('blob_name').value = blobName;
            document.getElementById('container_name').value = container;

            // Highlight row
            document.querySelectorAll('.files-table tbody tr').forEach(row => {{
                row.classList.remove('selected');
            }});
            event.currentTarget.classList.add('selected');

            // Update display
            const shortName = blobName.split('/').pop();
            document.getElementById('selected-file').innerHTML = `
                <div class="file-info">
                    <span class="file-path">${{shortName}}</span>
                    <span class="file-meta">${{container}} / ${{blobName}} (${{sizeMb.toFixed(2)}} MB)</span>
                </div>
            `;

            // Auto-suggest dataset_id
            const datasetInput = document.getElementById('dataset_id');
            if (!datasetInput.value) {{
                let datasetId = shortName.split('.')[0]
                    .toLowerCase()
                    .replace(/[^a-z0-9-]/g, '-')
                    .replace(/^-+|-+$/g, '')
                    .replace(/--+/g, '-');
                datasetInput.value = datasetId;
            }}

            updateFormState();
        }}

        // Collection selection (checkboxes)
        function updateCollectionSelection() {{
            const container = document.getElementById('container-select').value;
            document.getElementById('container_name').value = container;

            selectedFiles = [];
            let totalSize = 0;

            document.querySelectorAll('.file-checkbox:checked').forEach(cb => {{
                selectedFiles.push(cb.dataset.blob);
                totalSize += parseFloat(cb.dataset.size);
                cb.closest('tr').classList.add('selected');
            }});

            document.querySelectorAll('.file-checkbox:not(:checked)').forEach(cb => {{
                cb.closest('tr').classList.remove('selected');
            }});

            updateSelectionDisplay(totalSize);
            updateFormState();
        }}

        // Update selection display
        function updateSelectionDisplay(totalSize = 0) {{
            const countEl = document.getElementById('selection-count');
            const sizeEl = document.getElementById('selection-size');
            const filesEl = document.getElementById('selected-file');
            const blobListInput = document.getElementById('blob_list');

            if (countEl) countEl.textContent = `${{selectedFiles.length}} files selected`;
            if (sizeEl) sizeEl.textContent = `(${{totalSize.toFixed(2)}} MB total)`;

            blobListInput.value = JSON.stringify(selectedFiles);

            if (selectedFiles.length === 0) {{
                filesEl.innerHTML = '<span class="placeholder">No files selected - check files in the browser</span>';
            }} else {{
                const tags = selectedFiles.slice(0, 10).map(f => {{
                    const shortName = f.split('/').pop();
                    return `<span class="file-tag">${{shortName}}</span>`;
                }}).join('');
                const more = selectedFiles.length > 10 ? `<span class="file-tag">+${{selectedFiles.length - 10}} more</span>` : '';
                filesEl.innerHTML = `<div class="file-list">${{tags}}${{more}}</div>`;
            }}

            // Update select-all checkbox
            const allCheckboxes = document.querySelectorAll('.file-checkbox');
            const checkedCount = document.querySelectorAll('.file-checkbox:checked').length;
            const selectAllCb = document.getElementById('select-all-checkbox');
            if (selectAllCb) {{
                selectAllCb.checked = allCheckboxes.length > 0 && checkedCount === allCheckboxes.length;
                selectAllCb.indeterminate = checkedCount > 0 && checkedCount < allCheckboxes.length;
            }}
        }}

        function selectAllFiles() {{
            document.querySelectorAll('.file-checkbox').forEach(cb => cb.checked = true);
            updateCollectionSelection();
        }}

        function clearSelection() {{
            document.querySelectorAll('.file-checkbox').forEach(cb => cb.checked = false);
            updateCollectionSelection();
        }}

        function toggleSelectAll(headerCb) {{
            document.querySelectorAll('.file-checkbox').forEach(cb => cb.checked = headerCb.checked);
            updateCollectionSelection();
        }}

        // Update form state (buttons, cURL)
        function updateFormState() {{
            const datasetId = document.getElementById('dataset_id').value;
            const resourceId = document.getElementById('resource_id').value;

            let hasFile = false;
            if (currentDataType === 'raster_collection') {{
                hasFile = selectedFiles.length >= MIN_FILES && selectedFiles.length <= MAX_FILES;
            }} else {{
                hasFile = !!document.getElementById('blob_name').value;
            }}

            const canValidate = datasetId && resourceId && hasFile;
            document.getElementById('validate-btn').disabled = !canValidate;
            document.getElementById('submit-btn').disabled = !canValidate;

            updateCurlPreview();
        }}

        // Show validation result area
        function showValidationResult() {{
            document.getElementById('validation-result').classList.remove('hidden');
        }}

        // Show submit result area
        function showSubmitResult() {{
            document.getElementById('submit-result').classList.remove('hidden');
        }}

        // Dismiss error
        function dismissError() {{
            document.getElementById('submit-result').innerHTML = '';
            document.getElementById('submit-result').classList.add('hidden');
        }}

        // Reset form
        function resetForm() {{
            document.getElementById('submit-result').innerHTML = '';
            document.getElementById('submit-result').classList.add('hidden');
            document.getElementById('validation-result').innerHTML = '';
            document.getElementById('validation-result').classList.add('hidden');

            // Clear file selection
            document.getElementById('blob_name').value = '';
            document.getElementById('blob_list').value = '[]';
            selectedFiles = [];
            document.querySelectorAll('.files-table tbody tr').forEach(row => row.classList.remove('selected'));
            document.querySelectorAll('.file-checkbox').forEach(cb => cb.checked = false);
            document.getElementById('selected-file').innerHTML = '<span class="placeholder">No file selected</span>';

            // Clear form
            document.getElementById('dataset_id').value = '';
            document.getElementById('resource_id').value = '';
            document.getElementById('version_id').value = 'v1.0';
            document.getElementById('collection_id').value = '';
            document.getElementById('title').value = '';
            document.getElementById('description').value = '';

            updateFormState();
        }}

        // Generate cURL
        function generateCurl() {{
            const datasetId = document.getElementById('dataset_id').value;
            const resourceId = document.getElementById('resource_id').value;
            const versionId = document.getElementById('version_id').value || 'v1.0';
            const containerName = document.getElementById('container_name').value;

            if (!datasetId || !resourceId) {{
                return 'Fill in DDH identifiers to see the cURL command';
            }}

            let fileName;
            if (currentDataType === 'raster_collection') {{
                if (selectedFiles.length < MIN_FILES) {{
                    return `Select at least ${{MIN_FILES}} files to see the cURL command`;
                }}
                fileName = selectedFiles;
            }} else {{
                const blobName = document.getElementById('blob_name').value;
                if (!blobName) {{
                    return 'Select a file to see the cURL command';
                }}
                fileName = blobName;
            }}

            const payload = {{
                dataset_id: datasetId,
                resource_id: resourceId,
                version_id: versionId,
                data_type: currentDataType === 'vector' ? 'vector' : 'raster',
                container_name: containerName,
                file_name: fileName
            }};

            // Optional fields
            const title = document.getElementById('title').value;
            const description = document.getElementById('description').value;
            const accessLevel = document.getElementById('access_level').value;
            const tags = document.getElementById('tags').value;
            const collectionId = document.getElementById('collection_id').value;

            if (title) payload.title = title;
            if (description) payload.description = description;
            if (accessLevel) payload.access_level = accessLevel;
            if (tags) payload.tags = tags.split(',').map(t => t.trim()).filter(t => t);

            // Processing options
            const processingOptions = {{}};

            if (collectionId) processingOptions.collection_id = collectionId;

            const overwrite = document.getElementById('overwrite').checked;
            if (overwrite) processingOptions.overwrite = true;

            if (currentDataType !== 'vector') {{
                const rasterType = document.getElementById('raster_type').value;
                if (rasterType && rasterType !== 'auto') processingOptions.raster_type = rasterType;

                const outputTier = document.getElementById('output_tier').value;
                if (outputTier && outputTier !== 'analysis') processingOptions.output_tier = outputTier;

                const inputCrs = document.getElementById('input_crs').value;
                if (inputCrs) processingOptions.crs = inputCrs;

                const useDocker = document.getElementById('use_docker').checked;
                if (useDocker) processingOptions.processing_mode = 'docker';
            }} else {{
                const latName = document.getElementById('lat_name').value;
                const lonName = document.getElementById('lon_name').value;
                const wktColumn = document.getElementById('wkt_column').value;

                if (latName) processingOptions.lat_column = latName;
                if (lonName) processingOptions.lon_column = lonName;
                if (wktColumn) processingOptions.wkt_column = wktColumn;
            }}

            if (Object.keys(processingOptions).length > 0) {{
                payload.processing_options = processingOptions;
            }}

            const baseUrl = window.location.origin;
            const jsonStr = JSON.stringify(payload, null, 2);

            return `curl -X POST "${{baseUrl}}/api/platform/submit" \\
  -H "Content-Type: application/json" \\
  -d '${{jsonStr}}'`;
        }}

        function updateCurlPreview() {{
            const curlEl = document.getElementById('curl-command');
            if (curlEl) {{
                curlEl.textContent = generateCurl();
            }}
        }}

        function copyCurl() {{
            const curlText = generateCurl();
            navigator.clipboard.writeText(curlText).then(() => {{
                const copyIcon = document.getElementById('copy-icon');
                copyIcon.textContent = '✅';
                setTimeout(() => {{ copyIcon.textContent = '📋'; }}, 1500);
            }}).catch(err => {{
                console.error('Copy failed:', err);
                alert('Copy failed. Please select and copy manually.');
            }});
        }}

        // HTMX event handlers
        document.body.addEventListener('htmx:afterSwap', function(evt) {{
            if (evt.detail.target.id === 'files-tbody') {{
                showFilesTable();
            }}
            if (evt.detail.target.id === 'submit-result') {{
                document.getElementById('submit-result').classList.remove('hidden');
            }}
            if (evt.detail.target.id === 'validation-result') {{
                document.getElementById('validation-result').classList.remove('hidden');
            }}
        }});
        """
