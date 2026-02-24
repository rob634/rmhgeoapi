# ============================================================================
# STORAGE UPLOAD HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/storage/upload
# PURPOSE: Upload files to bronze storage via multipart form-data
# LAST_REVIEWED: 15 JAN 2026
# EXPORTS: storage_upload_handler
# DEPENDENCIES: azure.functions, infrastructure.blob, config
# ============================================================================
"""
Storage Upload - Upload files to bronze storage containers.

Route: POST /api/storage/upload

Accepts multipart/form-data with:
    - file: The file to upload (required)
    - container: Target container name (required)
    - path: Blob path within container (optional, defaults to filename)

Security:
    - Uploads restricted to bronze storage account
    - Admin functionality - not exposed to external Platform API

Example Usage:
    curl -X POST "https://{app-url}/api/storage/upload" \\
        -F "file=@myfile.gpkg" \\
        -F "container=source-data" \\
        -F "path=uploads/myfile.gpkg"

Created: 15 JAN 2026
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

import azure.functions as func

from config import get_config
from infrastructure.blob import BlobRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "storage_upload")

# Maximum file size (100MB)
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024


def _parse_multipart(req: func.HttpRequest) -> Tuple[Optional[bytes], Dict[str, str]]:
    """
    Parse multipart/form-data from Azure Functions request.

    Uses stdlib boundary-based parsing instead of the deprecated cgi module
    (removed in Python 3.13) [C5.2].

    Args:
        req: Azure Functions HTTP request

    Returns:
        Tuple of (file_data, form_fields) where form_fields contains
        container, path, filename, content_type
    """
    content_type = req.headers.get("Content-Type", "")

    if "multipart/form-data" not in content_type:
        raise ValueError("Content-Type must be multipart/form-data")

    # Extract boundary from Content-Type
    # Format: multipart/form-data; boundary=----WebKitFormBoundary...
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:]
            # Remove quotes if present
            if boundary.startswith('"') and boundary.endswith('"'):
                boundary = boundary[1:-1]
            break

    if not boundary:
        raise ValueError("Could not extract boundary from Content-Type")

    # Get request body
    body = req.get_body()

    # Parse multipart body by splitting on boundary markers
    # Each part is separated by --boundary, with --boundary-- at the end
    boundary_bytes = ("--" + boundary).encode("utf-8")
    parts = body.split(boundary_bytes)

    # Extract form fields
    form_fields = {
        "container": "",
        "path": "",
        "filename": "",
        "content_type": "application/octet-stream",
    }
    file_data = None

    for part in parts:
        # Skip empty parts and the closing boundary marker
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue

        # Split headers from body (separated by double CRLF)
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue

        header_section = part[:header_end].decode("utf-8", errors="replace")
        part_body = part[header_end + 4:]
        # Strip trailing CRLF from body
        if part_body.endswith(b"\r\n"):
            part_body = part_body[:-2]

        # Parse Content-Disposition header for name and filename
        name_match = re.search(r'name="([^"]*)"', header_section)
        filename_match = re.search(r'filename="([^"]*)"', header_section)
        part_content_type_match = re.search(
            r'Content-Type:\s*(.+)', header_section, re.IGNORECASE
        )

        if not name_match:
            continue

        field_name = name_match.group(1)

        if filename_match and filename_match.group(1):
            # This is a file field
            file_data = part_body
            form_fields["filename"] = filename_match.group(1)
            if part_content_type_match:
                form_fields["content_type"] = part_content_type_match.group(1).strip()
        else:
            # This is a regular form field
            field_value = part_body.decode("utf-8", errors="replace")
            if field_name == "container":
                form_fields["container"] = field_value
            elif field_name == "path":
                form_fields["path"] = field_value

    return file_data, form_fields


def storage_upload_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle file upload to bronze storage.

    Args:
        req: HTTP request with multipart/form-data

    Returns:
        JSON response with upload result or error
    """
    start_time = datetime.now(timezone.utc)
    logger.info("Processing storage upload request")

    try:
        # Parse multipart request
        file_data, form_fields = _parse_multipart(req)

        container = form_fields.get("container", "").strip()
        path = form_fields.get("path", "").strip()
        filename = form_fields.get("filename", "")
        content_type = form_fields.get("content_type", "application/octet-stream")

        # Validate file was provided
        if not file_data:
            return func.HttpResponse(
                json.dumps({
                    "error": "No file provided",
                    "hint": "Include a 'file' field in your multipart/form-data request"
                }, indent=2),
                status_code=400,
                mimetype="application/json"
            )

        # Validate container
        if not container:
            return func.HttpResponse(
                json.dumps({
                    "error": "Container name required",
                    "hint": "Include a 'container' field"
                }, indent=2),
                status_code=400,
                mimetype="application/json"
            )

        # Note: Security is enforced by BlobRepository.for_zone("bronze")
        # which restricts uploads to the bronze storage account only

        # Use filename if path not provided
        if not path:
            path = filename

        if not path:
            return func.HttpResponse(
                json.dumps({
                    "error": "No path specified and no filename in upload",
                    "hint": "Include a 'path' field or ensure file has a filename"
                }, indent=2),
                status_code=400,
                mimetype="application/json"
            )

        # Validate file size
        file_size = len(file_data)
        if file_size > MAX_FILE_SIZE_BYTES:
            return func.HttpResponse(
                json.dumps({
                    "error": f"File too large: {file_size / (1024*1024):.2f} MB",
                    "max_size_mb": MAX_FILE_SIZE_BYTES / (1024 * 1024),
                    "hint": "Maximum file size is 100MB via HTTP upload"
                }, indent=2),
                status_code=413,
                mimetype="application/json"
            )

        logger.info(f"Uploading file: container={container}, path={path}, size={file_size} bytes")

        # Get bronze storage repository
        repo = BlobRepository.for_zone("bronze")

        # Ensure container exists
        container_result = repo.ensure_container_exists(container)
        if container_result.get("created"):
            logger.info(f"Created container: {container}")

        # Upload the file
        result = repo.write_blob(
            container=container,
            blob_path=path,
            data=file_data,
            overwrite=True,
            content_type=content_type,
            metadata={
                "upload_source": "web_interface",
                "original_filename": filename,
                "upload_timestamp": start_time.isoformat()
            }
        )

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        response = {
            "success": True,
            "message": f"File uploaded successfully",
            "upload": {
                "container": container,
                "path": path,
                "size_bytes": file_size,
                "size_mb": round(file_size / (1024 * 1024), 2),
                "content_type": content_type,
                "etag": result.get("etag"),
                "original_filename": filename
            },
            "storage": {
                "zone": "bronze",
                "account": repo.account_name
            },
            "upload_time_seconds": round(duration, 3),
            "timestamp": start_time.isoformat()
        }

        logger.info(f"Upload successful: {container}/{path} ({file_size} bytes) in {duration:.3f}s")

        return func.HttpResponse(
            json.dumps(response, indent=2),
            status_code=200,
            mimetype="application/json"
        )

    except ValueError as e:
        logger.warning(f"Upload validation error: {e}")
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "hint": "Ensure request is multipart/form-data with 'file' and 'container' fields"
            }, indent=2),
            status_code=400,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Upload failed",
                "message": str(e)
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )
