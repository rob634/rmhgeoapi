# Quick Improvements - Immediate Actions

## 1. Remove Obsolete Files (5 minutes)

### Files to Delete:
```bash
# Old test file with 866 lines
rm test_ancient_code.py

# Managed identity debug (not using MI for PostGIS)
rm debug_managed_identity_service.py

# Old manual scripts that are superseded
rm update_job_status.py  # Functionality in API
rm query_jobs_table.py   # Use direct_table_query.py instead
```

## 2. Consolidate STAC Files (30 minutes)

### Current STAC Files (5 files, ~2,900 lines):
- `stac_service.py` (403 lines) - Generic STAC operations
- `stac_repository.py` (364 lines) - Repository pattern
- `postgis_stac_repository.py` (493 lines) - PostGIS operations
- `stac_models.py` (328 lines) - Data models
- `stac_item_service.py` (617 lines) - Item operations
- `stac_sync_service.py` (665 lines) - Sync operations
- `stac_setup_service.py` (1067 lines) - Setup operations

### Consolidation Plan:
```python
# stac_unified_repository.py - Merge repositories (500 lines)
class STACRepository:
    """Unified STAC repository combining all PostGIS operations."""
    def __init__(self, connection_params):
        self.conn_params = connection_params
    
    # Methods from both repository files
    def upsert_collection(self, ...): pass
    def upsert_item(self, ...): pass
    def get_item(self, ...): pass
    def search_items(self, ...): pass
```

## 3. Add Type Hints (1 hour)

### Priority Files for Type Hints:
```python
# Before (services.py)
def get_service(operation_type):
    if operation_type == "list_container":
        return ContainerListingService()

# After
from typing import Optional
from services.base import BaseProcessingService

def get_service(operation_type: str) -> Optional[BaseProcessingService]:
    """Get the appropriate service for the operation type.
    
    Args:
        operation_type: The type of operation to perform
        
    Returns:
        Service instance or None if not found
    """
    if operation_type == "list_container":
        return ContainerListingService()
```

## 4. Extract Constants (30 minutes)

### Create core/constants.py:
```python
"""Central location for all constants and magic values."""

from enum import Enum

class StorageContainers:
    """Azure storage container names."""
    BRONZE = "rmhazuregeobronze"
    SILVER = "rmhazuregeosilver"
    GOLD = "rmhazuregeogold"

class FileSizeLimits:
    """File size limits in MB."""
    QUICK_MODE_THRESHOLD = 10000  # 10GB
    SMART_MODE_THRESHOLD = 5000   # 5GB
    FULL_MODE_THRESHOLD = 1000    # 1GB

class GeospatialExtensions:
    """Supported file extensions."""
    RASTER = {'.tif', '.tiff', '.geotiff', '.cog'}
    VECTOR = {'.geojson', '.json', '.gpkg', '.shp'}
    ALL = RASTER | VECTOR

class JobStatus(Enum):
    """Job processing statuses."""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
```

## 5. Improve Error Messages (30 minutes)

### Current:
```python
except Exception as e:
    logger.error(f"Error: {e}")
    raise
```

### Improved:
```python
except FileNotFoundError as e:
    logger.error(
        f"Blob not found in container '{container_name}': {blob_name}",
        extra={
            "job_id": job_id,
            "container": container_name,
            "blob": blob_name,
            "error": str(e)
        }
    )
    raise STACProcessingError(
        f"Cannot process non-existent blob: {blob_name}"
    ) from e
```

## 6. Add Docstrings (1 hour)

### Template for Consistent Docstrings:
```python
def process_stac_item(
    self,
    container_name: str,
    blob_name: str,
    mode: str = "auto"
) -> Dict[str, Any]:
    """Process a blob and create/update STAC item.
    
    This method handles the complete workflow of extracting metadata
    from a geospatial file and updating the STAC catalog.
    
    Args:
        container_name: Azure storage container name
        blob_name: Path to blob within container
        mode: Processing mode ('quick', 'full', 'smart', 'auto')
            - quick: Use blob metadata only
            - full: Download and extract complete metadata
            - smart: Use header-only access for large files
            - auto: Automatically select based on file size
    
    Returns:
        Dictionary containing:
            - status: 'success' or 'failed'
            - item_id: STAC item identifier
            - mode: Actual mode used
            - metadata: Extracted metadata
    
    Raises:
        STACProcessingError: If processing fails
        ValueError: If mode is invalid
    
    Example:
        >>> service = STACItemService()
        >>> result = service.process_stac_item(
        ...     "bronze", 
        ...     "data/sample.tif",
        ...     mode="smart"
        ... )
        >>> print(result['item_id'])
        'bronze_data_sample_tif'
    """
```

## 7. Create Simple Test Suite (1 hour)

### tests/test_core_functionality.py:
```python
"""Core functionality tests that can run locally."""

import pytest
from unittest.mock import Mock, patch
from services.stac.item import STACItemService
from core.models import BlobMetadata

class TestSTACItemService:
    """Test STAC item service functionality."""
    
    @pytest.fixture
    def service(self):
        """Create service with mock dependencies."""
        storage_mock = Mock()
        stac_mock = Mock()
        return STACItemService(storage_mock, stac_mock)
    
    def test_determine_mode_for_large_file(self, service):
        """Test that large files use smart mode."""
        blob = BlobMetadata(
            name="large.tif",
            size=11 * 1024 * 1024 * 1024,  # 11GB
            last_modified=datetime.now(),
            etag="abc123"
        )
        
        mode = service._determine_mode("stac_item_update", "auto", blob)
        assert mode == ProcessingMode.SMART
    
    def test_skip_non_geospatial_files(self, service):
        """Test that non-geospatial files are skipped."""
        result = service._skip_non_geospatial("document.pdf")
        assert result["status"] == "skipped"
        assert "pdf" in result["extension"]
```

## 8. Add Logging Configuration (15 minutes)

### logger_config.py:
```python
"""Centralized logging configuration."""

import logging
import logging.config
from typing import Dict, Any

def get_logging_config(level: str = "INFO") -> Dict[str, Any]:
    """Get logging configuration dictionary."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            },
            "detailed": {
                "format": "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(funcName)s(): %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "standard",
                "stream": "ext://sys.stdout"
            }
        },
        "root": {
            "level": level,
            "handlers": ["console"]
        },
        "loggers": {
            "azure": {
                "level": "WARNING"  # Reduce Azure SDK verbosity
            },
            "urllib3": {
                "level": "WARNING"  # Reduce HTTP client verbosity
            }
        }
    }

# Apply configuration
logging.config.dictConfig(get_logging_config())
```

## 9. Add Performance Monitoring (30 minutes)

### utils/performance.py:
```python
"""Performance monitoring utilities."""

import time
import functools
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

def measure_time(func: Callable) -> Callable:
    """Decorator to measure function execution time."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.info(
                f"{func.__name__} completed in {elapsed:.2f}s",
                extra={"function": func.__name__, "duration": elapsed}
            )
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error(
                f"{func.__name__} failed after {elapsed:.2f}s: {e}",
                extra={"function": func.__name__, "duration": elapsed}
            )
            raise
    return wrapper

# Usage
class STACItemService:
    @measure_time
    def process(self, ...):
        """Process with timing."""
        pass
```

## 10. Create Development Setup Script (15 minutes)

### scripts/setup_dev.py:
```python
#!/usr/bin/env python3
"""Setup development environment."""

import os
import sys
import subprocess
from pathlib import Path

def setup_dev_environment():
    """Setup local development environment."""
    print("🚀 Setting up development environment...")
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required")
        sys.exit(1)
    
    # Create virtual environment
    if not Path(".venv").exists():
        print("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", ".venv"])
    
    # Install dependencies
    print("Installing dependencies...")
    pip = ".venv/bin/pip" if os.name != "nt" else ".venv\\Scripts\\pip"
    subprocess.run([pip, "install", "-r", "requirements.txt"])
    subprocess.run([pip, "install", "-r", "requirements-dev.txt"])
    
    # Create local settings
    if not Path("local.settings.json").exists():
        print("Creating local.settings.json...")
        # Copy template
    
    print("✅ Development environment ready!")
    print("\nActivate with: source .venv/bin/activate")

if __name__ == "__main__":
    setup_dev_environment()
```

## Implementation Priority

### Week 1 (Immediate):
1. ✅ Remove obsolete files (5 min)
2. ✅ Extract constants (30 min)
3. ✅ Add logging config (15 min)

### Week 2 (High Value):
1. ⏳ Consolidate STAC repositories (2 hours)
2. ⏳ Add type hints to services (2 hours)
3. ⏳ Improve error handling (1 hour)

### Week 3 (Quality):
1. ⏳ Add comprehensive docstrings (3 hours)
2. ⏳ Create test suite (2 hours)
3. ⏳ Add performance monitoring (1 hour)

## Benefits of These Quick Wins

### Immediate Benefits:
- **Reduced complexity**: ~1,500 fewer lines of code
- **Better errors**: Clear, actionable error messages
- **Improved debugging**: Structured logging with context

### Long-term Benefits:
- **Faster onboarding**: Clear code structure and documentation
- **Easier maintenance**: Type hints catch errors early
- **Better performance**: Monitoring identifies bottlenecks

### Metrics:
- **Code reduction**: ~15% fewer lines
- **Test coverage**: From 0% to ~40%
- **Type coverage**: From 0% to ~60%
- **Documentation**: From ~20% to ~80%

These improvements can be implemented incrementally without breaking existing functionality, providing immediate value while setting the foundation for larger refactoring efforts.