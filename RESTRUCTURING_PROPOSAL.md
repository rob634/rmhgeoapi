# Codebase Restructuring Proposal

## Current Issues
1. **Flat structure**: All 29 Python files in root directory
2. **Mixed concerns**: Test files, utilities, and core services together
3. **Duplicate functionality**: Multiple STAC services with overlapping code
4. **Inconsistent naming**: Some files use underscores, others don't follow patterns
5. **No clear separation**: Core vs auxiliary functionality mixed

## Proposed Directory Structure

```
rmhgeoapi/
│
├── function_app.py              # Keep at root (Azure Functions requirement)
├── host.json                    # Keep at root (Azure Functions requirement)
├── requirements.txt             # Keep at root
├── local.settings.json          # Keep at root
│
├── core/                        # Core business logic
│   ├── __init__.py
│   ├── config.py               # Configuration and constants
│   ├── models.py               # Data models and schemas
│   └── exceptions.py           # Custom exceptions (new)
│
├── services/                    # Service layer (processing logic)
│   ├── __init__.py
│   ├── base.py                # BaseProcessingService (extracted from services.py)
│   ├── factory.py              # ServiceFactory (extracted from services.py)
│   ├── hello_world.py          # HelloWorldService (extracted)
│   ├── container.py            # ContainerListingService (extracted)
│   │
│   ├── raster/                 # Raster-specific services
│   │   ├── __init__.py
│   │   ├── processing.py       # RasterProcessingService
│   │   └── cog.py             # COG-specific operations (extracted)
│   │
│   ├── stac/                   # STAC services (consolidated)
│   │   ├── __init__.py
│   │   ├── item.py            # STACItemService (unified quick/full/smart)
│   │   ├── sync.py            # STACContainerSyncService
│   │   ├── setup.py           # STACSetupService
│   │   └── models.py          # STAC-specific models
│   │
│   ├── metadata/               # Metadata extraction
│   │   ├── __init__.py
│   │   └── extractor.py       # MetadataExtractionService
│   │
│   └── database/               # Database operations
│       ├── __init__.py
│       └── introspection.py   # DatabaseIntrospectionService
│
├── repositories/               # Data access layer
│   ├── __init__.py
│   ├── storage.py            # StorageRepository
│   ├── table.py              # TableRepository
│   ├── postgis.py            # PostGIS operations (consolidated)
│   └── stac.py               # STAC repository operations
│
├── utils/                      # Utilities and helpers
│   ├── __init__.py
│   ├── logger.py             # Logger setup
│   └── auth.py               # Authentication helpers (new)
│
├── scripts/                    # Standalone scripts
│   ├── __init__.py
│   ├── manual_bronze_sync.py
│   ├── full_stac_inventory.py
│   ├── query_jobs_table.py
│   ├── direct_table_query.py
│   ├── update_job_status.py
│   └── manual_process_job.py
│
├── tests/                      # All test files
│   ├── __init__.py
│   ├── test_api_local.py
│   ├── test_api_comprehensive.py
│   ├── test_container_list.py
│   ├── test_database_introspection.py
│   ├── test_managed_identity.py
│   ├── test_stac_direct.py
│   └── test_ancient_code.py
│
└── docs/                       # Documentation
    ├── API_DOCUMENTATION.md
    ├── CLAUDE.md
    ├── README.md
    ├── TESTING.md
    └── stac/
        ├── STAC_INTEGRATION_PLAN.md
        ├── STAC_POSTGIS_IMPLEMENTATION.md
        └── STAC_STORAGE_ANALYSIS.md
```

## Key Refactoring Actions

### 1. **Consolidate STAC Services**
Currently have 5 STAC-related files with overlapping functionality:
- Merge `stac_service.py`, `stac_repository.py`, `postgis_stac_repository.py`
- Keep distinct services: `item.py` (cataloging), `sync.py` (batch), `setup.py` (infrastructure)

### 2. **Extract Base Classes**
- Move `BaseProcessingService` from `services.py` to `services/base.py`
- Move `ServiceFactory` to `services/factory.py`
- Create `repositories/base.py` for repository patterns

### 3. **Improve Naming Conventions**
```python
# Current (inconsistent)
database_introspection_service.py
manual_bronze_sync.py
test_api_comprehensive.py

# Proposed (consistent)
services/database/introspection.py
scripts/bronze_sync.py
tests/api/test_comprehensive.py
```

### 4. **Separate Concerns**
- Move all test files to `tests/`
- Move utility scripts to `scripts/`
- Keep only Azure Functions entry points at root

### 5. **Add Missing Components**
```python
# core/exceptions.py
class GeospatialETLException(Exception):
    """Base exception for all custom errors"""
    pass

class RasterProcessingError(GeospatialETLException):
    """Raised when raster processing fails"""
    pass

class STACCatalogError(GeospatialETLException):
    """Raised when STAC operations fail"""
    pass

# utils/auth.py
class AuthenticationHelper:
    """Centralize authentication logic"""
    @staticmethod
    def get_storage_client():
        """Get authenticated storage client"""
        pass
    
    @staticmethod
    def get_postgres_connection():
        """Get database connection"""
        pass
```

## Implementation Plan

### Phase 1: Create Directory Structure
```bash
mkdir -p core services/{raster,stac,metadata,database} repositories utils scripts tests docs/stac
```

### Phase 2: Move Files (Non-Breaking)
```bash
# Move without breaking imports
git mv config.py core/
git mv models.py core/
git mv logger_setup.py utils/logger.py
# ... etc
```

### Phase 3: Update Imports
```python
# Old
from config import Config
from services import ServiceFactory

# New
from core.config import Config
from services.factory import ServiceFactory
```

### Phase 4: Consolidate Duplicate Code
- Merge three STAC repository files
- Extract common patterns to base classes
- Remove redundant implementations

### Phase 5: Add Type Hints and Documentation
```python
from typing import Dict, List, Optional
from abc import ABC, abstractmethod

class BaseProcessingService(ABC):
    """Abstract base class for all processing services.
    
    This class defines the interface that all processing services
    must implement to work with the job processing pipeline.
    """
    
    @abstractmethod
    def process(
        self, 
        job_id: str, 
        dataset_id: str, 
        resource_id: str,
        version_id: str, 
        operation_type: str
    ) -> Dict[str, any]:
        """Process a job with given parameters.
        
        Args:
            job_id: Unique job identifier (SHA256 hash)
            dataset_id: Container or dataset name
            resource_id: Specific resource (file, table, etc.)
            version_id: Processing parameters or version
            operation_type: Type of operation to perform
            
        Returns:
            Dictionary containing status and results
            
        Raises:
            ProcessingError: If processing fails
        """
        pass
```

## Benefits of Restructuring

### 1. **Improved Maintainability**
- Clear separation of concerns
- Easier to locate functionality
- Reduced code duplication

### 2. **Better Testing**
- Tests isolated from production code
- Can run test suite without deploying scripts
- Clear test organization by component

### 3. **Enhanced Scalability**
- Easy to add new services
- Clear patterns for extension
- Modular architecture

### 4. **Cleaner Deployment**
- Only deploy necessary code
- Scripts separated from core functionality
- Reduced deployment size

### 5. **Better Developer Experience**
- Intuitive file organization
- Consistent naming patterns
- Clear dependency graph

## Migration Strategy

### Option 1: Big Bang (Not Recommended)
- Restructure everything at once
- High risk of breaking changes
- Requires extensive testing

### Option 2: Gradual Migration (Recommended)
1. **Week 1**: Create new structure, move test files
2. **Week 2**: Move utility scripts
3. **Week 3**: Consolidate STAC services
4. **Week 4**: Reorganize core services
5. **Week 5**: Update documentation and cleanup

### Option 3: Parallel Structure
- Create new structure alongside old
- Gradually migrate functionality
- Deprecate old files over time

## Code Quality Improvements

### 1. **Add Type Hints Throughout**
```python
def process_raster(
    container_name: str,
    blob_name: str,
    target_epsg: Optional[int] = 4326
) -> Tuple[bytes, Dict[str, Any]]:
    """Process raster with type safety."""
    pass
```

### 2. **Implement Consistent Error Handling**
```python
try:
    result = process_operation()
except RasterProcessingError as e:
    logger.error(f"Raster processing failed: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise GeospatialETLException(f"Processing failed: {e}")
```

### 3. **Add Configuration Validation**
```python
from pydantic import BaseSettings, validator

class Settings(BaseSettings):
    storage_account_name: str
    bronze_container: str
    postgis_host: str
    
    @validator('bronze_container')
    def validate_container_name(cls, v):
        if not v or len(v) < 3:
            raise ValueError("Invalid container name")
        return v
```

### 4. **Implement Dependency Injection**
```python
class RasterService:
    def __init__(
        self,
        storage_repo: StorageRepository,
        metadata_extractor: MetadataExtractor,
        logger: Logger
    ):
        self.storage = storage_repo
        self.extractor = metadata_extractor
        self.logger = logger
```

## Immediate Quick Wins

Without major restructuring, these improvements can be made immediately:

1. **Delete unused files**:
   - `test_ancient_code.py` (866 lines of old code)
   - `debug_managed_identity_service.py` (if MI not used)

2. **Consolidate STAC repositories**:
   - Merge `stac_repository.py` and `postgis_stac_repository.py`
   - Remove duplicate implementations

3. **Extract constants**:
   - Create `core/constants.py` for all magic strings
   - Move file extensions, limits, etc.

4. **Improve logging**:
   - Standardize log format
   - Add correlation IDs
   - Implement log levels properly

5. **Add docstrings**:
   - Document all public methods
   - Add module-level docstrings
   - Include usage examples

## Conclusion

The proposed restructuring would transform a flat 29-file codebase into a well-organized, maintainable system. The gradual migration approach minimizes risk while providing immediate benefits. The new structure follows Python best practices and makes the codebase more approachable for new developers.

Priority should be given to:
1. Moving test files (low risk)
2. Consolidating STAC services (high value)
3. Creating proper package structure (long-term benefit)