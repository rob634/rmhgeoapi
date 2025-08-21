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
    
    @classmethod
    def bytes_to_mb(cls, size_bytes: int) -> float:
        """Convert bytes to megabytes."""
        return size_bytes / (1024 * 1024)


class GeospatialExtensions:
    """Supported file extensions."""
    RASTER = {'.tif', '.tiff', '.geotiff', '.cog', '.img', '.hdf', '.nc'}
    VECTOR = {'.geojson', '.json', '.gpkg', '.shp', '.kml', '.gml'}
    ALL = RASTER | VECTOR


class JobStatus(Enum):
    """Job processing statuses."""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingMode(Enum):
    """Processing modes for STAC operations."""
    QUICK = "quick"
    FULL = "full"
    SMART = "smart"
    AUTO = "auto"


class Operations:
    """Available operation types."""
    HELLO_WORLD = "hello_world"
    LIST_CONTAINER = "list_container"
    COG_CONVERSION = "cog_conversion"
    VECTOR_UPLOAD = "vector_upload"
    
    # STAC operations
    STAC_ITEM_QUICK = "stac_item_quick"
    STAC_ITEM_FULL = "stac_item_full"
    STAC_ITEM_SMART = "stac_item_smart"
    STAC_ITEM_UPDATE = "stac_item_update"
    STAC_ITEM_VALIDATE = "stac_item_validate"
    STAC_SETUP = "stac_setup"
    STAC_CONTAINER_SYNC = "stac_container_sync"
    
    # Database operations
    DATABASE_INTROSPECTION = "database_introspection"
    
    @classmethod
    def get_stac_operations(cls) -> list:
        """Get all STAC-related operations."""
        return [
            cls.STAC_ITEM_QUICK,
            cls.STAC_ITEM_FULL,
            cls.STAC_ITEM_SMART,
            cls.STAC_ITEM_UPDATE,
            cls.STAC_ITEM_VALIDATE,
            cls.STAC_SETUP,
            cls.STAC_CONTAINER_SYNC
        ]


class QueueNames:
    """Azure Queue names."""
    GEOSPATIAL_JOBS = "geospatial-jobs"
    STAC_SYNC = "stac-sync"
    RASTER_PROCESSING = "raster-processing"


class TableNames:
    """Azure Table Storage names."""
    JOBS = "jobs"
    METADATA = "metadata"
    PROCESSING_HISTORY = "processinghistory"