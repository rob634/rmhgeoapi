"""Custom exceptions for the geospatial ETL pipeline."""


class GeospatialETLException(Exception):
    """Base exception for all ETL operations."""
    pass


class ValidationError(GeospatialETLException):
    """Raised when input validation fails."""
    pass


class ProcessingError(GeospatialETLException):
    """Raised when job processing fails."""
    pass


class STACProcessingError(GeospatialETLException):
    """Raised when STAC processing fails."""
    pass


class MetadataExtractionError(GeospatialETLException):
    """Raised when metadata extraction fails."""
    pass


class RasterProcessingError(GeospatialETLException):
    """Raised when raster processing fails."""
    pass


class StorageError(GeospatialETLException):
    """Raised when storage operations fail."""
    pass


class DatabaseError(GeospatialETLException):
    """Raised when database operations fail."""
    pass


class AuthenticationError(GeospatialETLException):
    """Raised when authentication fails."""
    pass


class ConfigurationError(GeospatialETLException):
    """Raised when configuration is invalid."""
    pass