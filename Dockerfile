# ============================================================================
# CLAUDE CONTEXT - GDAL DOCKER WORKER IMAGE
# ============================================================================
# STATUS: Container Definition - Docker image for long-running GDAL operations
# PURPOSE: Build Python 3.11 + GDAL environment for processing long-running-tasks queue
# LAST_REVIEWED: 10 JAN 2026
# ============================================================================
#
# This Docker image runs the same codebase as the Azure Functions app,
# but with APP_MODE=worker_docker for processing long-running tasks.
#
# Base Image: Official OSGeo GDAL (ghcr.io/osgeo/gdal)
#   - Pre-built GDAL with all dependencies
#   - Python bindings already configured
#   - No compilation headaches
#
# Build:
#   docker build -t geospatial-worker:latest .
#
# Run:
#   docker run --env-file docker.env geospatial-worker:latest
#
# ============================================================================

# Official OSGeo GDAL image - Python + GDAL pre-configured
# Using ubuntu-full for comprehensive driver support on heavy ETL tasks
# See: https://github.com/OSGeo/gdal/blob/master/docker/README.md
FROM ghcr.io/osgeo/gdal:ubuntu-full-3.10.1

# For Production use JFROG Artifactory base image (uncomment below)
#FROM artifactory.worldbank.org/itsdt-docker-virtual/ubuntu-full:3.10.1

# Install additional system dependencies:
# - python3-pip: pip for Python 3 (not included in ubuntu-small)
# - libpq: PostgreSQL client library (for psycopg2)
# - curl: Health check utility
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -s /bin/bash worker
WORKDIR /home/worker/app

# Install Python dependencies first (better layer caching)
# Note: GDAL Python bindings already included in base image
# --break-system-packages: Safe in Docker (PEP 668 protection not needed)
# --ignore-installed: Override debian-installed packages (numpy, etc.)
COPY requirements-docker.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages --ignore-installed -r requirements-docker.txt

# Copy application code
COPY --chown=worker:worker . .

# Switch to non-root user
USER worker

# Set environment variables
ENV APP_MODE=worker_docker
ENV PYTHONPATH=/home/worker/app
ENV PYTHONUNBUFFERED=1

# Expose port 80 for Azure Web App (default port)
EXPOSE 80

# Health check - hit the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

# Entry point - Docker Service (HTTP + Queue Worker)
# Runs FastAPI for health checks + background thread polling Service Bus
CMD ["python3", "-m", "uvicorn", "docker_service:app", "--host", "0.0.0.0", "--port", "80", "--log-level", "info", "--access-log"]
