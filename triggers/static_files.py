"""
Static File Server - Serve dashboard HTML/JS/CSS from Function App.

Routes:
    GET /api/dashboard              -> index.html (redirect)
    GET /api/dashboard/             -> index.html
    GET /api/dashboard/{filename}   -> static/{filename}

Supported file types:
    .html -> text/html
    .js   -> application/javascript
    .css  -> text/css
    .json -> application/json

Example:
    https://rmhazuregeoapi-.../api/dashboard/          -> Landing page
    https://rmhazuregeoapi-.../api/dashboard/health    -> Health dashboard
    https://rmhazuregeoapi-.../api/dashboard/storage   -> Storage browser
    https://rmhazuregeoapi-.../api/dashboard/map       -> OGC Features map
"""

import os
import logging
import azure.functions as func

logger = logging.getLogger(__name__)

# Path to static files relative to function app root
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')

# Content type mapping
CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
}

# Default file for directory requests
DEFAULT_FILE = 'index.html'


def static_files_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Serve static files from the static/ directory.

    Args:
        req: HTTP request with optional filename route parameter

    Returns:
        File contents with appropriate content-type, or 404 if not found
    """
    # Get requested filename from route
    filename = req.route_params.get('filename', '')

    # Handle empty filename or directory request -> serve index.html
    if not filename or filename == '/':
        filename = DEFAULT_FILE

    # Add .html extension if no extension provided (clean URLs)
    if '.' not in filename:
        filename = filename + '.html'

    # Security: prevent directory traversal
    if '..' in filename or filename.startswith('/'):
        logger.warning(f"Blocked directory traversal attempt: {filename}")
        return func.HttpResponse(
            "Invalid path",
            status_code=400
        )

    # Build full file path
    file_path = os.path.join(STATIC_DIR, filename)

    # Check file exists
    if not os.path.isfile(file_path):
        logger.info(f"Static file not found: {filename}")
        return func.HttpResponse(
            f"File not found: {filename}",
            status_code=404
        )

    # Determine content type
    _, ext = os.path.splitext(filename)
    content_type = CONTENT_TYPES.get(ext.lower(), 'application/octet-stream')

    try:
        # Read file
        with open(file_path, 'rb') as f:
            content = f.read()

        logger.debug(f"Serving static file: {filename} ({len(content)} bytes)")

        return func.HttpResponse(
            content,
            status_code=200,
            mimetype=content_type,
            headers={
                'Cache-Control': 'public, max-age=300',  # 5 min cache
            }
        )

    except Exception as e:
        logger.error(f"Error reading static file {filename}: {e}")
        return func.HttpResponse(
            f"Error reading file: {str(e)}",
            status_code=500
        )
