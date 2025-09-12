# Configuration Usage Guide

## Strongly Typed Configuration with Pydantic v2

The application uses a strongly typed configuration system that validates all environment variables and provides clear error messages when configuration is invalid.

## Basic Usage

```python
from config import get_config

# Get validated configuration
config = get_config()

# Access typed properties
storage_url = config.blob_service_url  # Returns: https://rmhazuregeo.blob.core.windows.net
queue_name = config.job_processing_queue  # Returns: geospatial-jobs
connection_str = config.postgis_connection_string  # Built automatically
```

## Configuration Properties

### Azure Storage
- `storage_account_name`: Account name (validated format)
- `bronze_container_name`: Raw data container
- `silver_container_name`: Processed data container  
- `gold_container_name`: Analytics/export container
- `blob_service_url`: Computed property for blob operations
- `queue_service_url`: Computed property for queue operations
- `table_service_url`: Computed property for table operations

### PostgreSQL/PostGIS
- `postgis_host`: Server hostname
- `postgis_port`: Port number (default: 5432)
- `postgis_user`: Username
- `postgis_password`: Optional password
- `postgis_database`: Database name
- `postgis_schema`: Schema name (default: "geo")
- `postgis_connection_string`: Computed connection string

### Queues
- `job_processing_queue`: Job orchestration queue (default: "geospatial-jobs")
- `task_processing_queue`: Task execution queue (default: "geospatial-tasks")

### Application Settings
- `function_timeout_minutes`: Azure Function timeout (1-10, default: 5)
- `max_retry_attempts`: Retry count (1-10, default: 3)
- `log_level`: Logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL, default: INFO)
- `enable_database_health_check`: Enable DB checks (default: true)

## Environment Variables

### Required
```bash
STORAGE_ACCOUNT_NAME=rmhazuregeo
BRONZE_CONTAINER_NAME=rmhazuregeobronze
SILVER_CONTAINER_NAME=rmhazuregeosilver
GOLD_CONTAINER_NAME=rmhazuregeogold
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_USER=rob634
POSTGIS_DATABASE=geopgflex
```

### Optional (with defaults)
```bash
POSTGIS_PORT=5432
POSTGIS_PASSWORD=secretpassword
POSTGIS_SCHEMA=geo
JOB_PROCESSING_QUEUE=geospatial-jobs
TASK_PROCESSING_QUEUE=geospatial-tasks
FUNCTION_TIMEOUT_MINUTES=5
MAX_RETRY_ATTEMPTS=3
LOG_LEVEL=INFO
ENABLE_DATABASE_HEALTH_CHECK=true
```

## Validation Features

### Automatic Validation
- **Storage account name**: Format validation (lowercase, 3-24 chars)
- **Log level**: Must be valid Python logging level
- **Timeout/retry**: Range validation (1-10)
- **Required fields**: Clear errors for missing variables

### Error Examples
```python
# Missing required variable
ValueError: Missing required environment variable: 'STORAGE_ACCOUNT_NAME'

# Invalid storage account name
ValueError: Configuration validation failed: storage_account_name must be lowercase

# Invalid log level  
ValueError: Configuration validation failed: log_level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Development/Debugging

### Debug Configuration
```python
from config import debug_config
import json

# Get sanitized config (passwords masked)
print(json.dumps(debug_config(), indent=2))
```

### Configuration Testing
```python
from config import AppConfig

# Test configuration without environment
test_config = AppConfig(
    storage_account_name="teststorage",
    bronze_container_name="testbronze",
    # ... other required fields
)

# Access computed properties
assert test_config.blob_service_url == "https://teststorage.blob.core.windows.net"
```

## Benefits

✅ **Single Source of Truth**: All configuration in one place  
✅ **Strong Typing**: Pydantic validation with clear errors  
✅ **Documentation**: Field descriptions and examples  
✅ **Computed Properties**: Automatic URL/connection string building  
✅ **Development Friendly**: Debug helpers and test utilities  
✅ **Production Ready**: Validation prevents runtime failures  

## Migration from Old Config

### Before (scattered)
```python
storage_account = os.environ.get('STORAGE_ACCOUNT_NAME')
queue_url = f"https://{storage_account}.queue.core.windows.net"
log_level = os.environ.get('LOG_LEVEL', 'INFO')
```

### After (strongly typed)
```python
config = get_config()
queue_url = config.queue_service_url
log_level = config.log_level  # Already validated
```

The new approach provides better error messages, type safety, and eliminates configuration bugs at startup rather than runtime.