# ============================================================================
# CLAUDE CONTEXT - LOGGING
# ============================================================================
# EPOCH: SHARED - BOTH EPOCHS
# STATUS: Used by Epoch 3 and Epoch 4
# NOTE: Careful migration required
# PURPOSE: JSON-only structured logging for Azure Functions with Application Insights
# EXPORTS: ComponentType, LogLevel, LogContext, LogEvent, LoggerFactory, log_exceptions, get_memory_stats, log_memory_checkpoint
# INTERFACES: Dataclass models, enums, factory, JSON formatter, exception decorator, DEBUG_MODE memory tracking
# DEPENDENCIES: enum, dataclasses, typing, datetime, logging, json, traceback (stdlib only!)
# SOURCE: Application architecture layers define component types
# SCOPE: Foundation and factory layers for all logging in the application
# VALIDATION: Simple type checking via dataclasses
# PATTERNS: JSON-only output, Azure Functions integration, Exception decorator pattern
# ENTRY_POINTS: LoggerFactory.create_logger(), @log_exceptions decorator
# INDEX: ComponentType:50, LogLevel:70, LogContext:95, LogEvent:165, JSONFormatter:255, LoggerFactory:305, log_exceptions:510
# ============================================================================

"""
Unified Logger System - Combined Schemas and Factory

Combines the foundation layer (schemas) and factory layer into a single
module for simplified imports while maintaining pyramid architecture principles.

This file replaces the previous logger_schemas.py and logger_factories.py
with a unified implementation.

Design Principles:
- Strong typing with dataclasses (stdlib only)
- Enum safety for categories
- Component-specific loggers
- Clean factory pattern
- No external dependencies

Author: Robert and Geospatial Claude Legion
Date: 9 September 2025
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import logging
import sys
import json
import traceback
from functools import wraps


# ============================================================================
# DEBUG MODE - Lazy imports for memory tracking (8 NOV 2025)
# ============================================================================

def _lazy_import_psutil():
    """
    Lazy import psutil for memory tracking.

    Returns tuple of (psutil, os) modules or (None, None) if unavailable.
    This prevents import failures if psutil is not installed.
    """
    try:
        import psutil
        import os
        return psutil, os
    except ImportError:
        return None, None


def get_memory_stats() -> Optional[Dict[str, float]]:
    """
    Get current process and system memory statistics.

    Only executes if DEBUG_MODE=true in config.

    Returns:
        dict with memory stats or None if debug disabled or psutil unavailable
        {
            'process_rss_mb': float,      # Resident Set Size (actual RAM used)
            'process_vms_mb': float,      # Virtual Memory Size
            'system_available_mb': float, # Available system memory
            'system_percent': float       # System memory usage %
        }
    """
    # Check if debug mode enabled
    try:
        from config import get_config
        config = get_config()

        if not config.debug_mode:
            return None
    except Exception as e:
        # Fail silently - debug feature shouldn't break anything
        # But print to stderr for debugging during development
        import sys
        print(f"DEBUG_MODE check failed: {e}", file=sys.stderr, flush=True)
        return None

    # Lazy import psutil
    psutil_module, os_module = _lazy_import_psutil()
    if not psutil_module:
        import sys
        print("DEBUG_MODE: psutil import failed", file=sys.stderr, flush=True)
        return None

    try:
        process = psutil_module.Process(os_module.getpid())
        mem_info = process.memory_info()
        system_mem = psutil_module.virtual_memory()

        return {
            'process_rss_mb': round(mem_info.rss / (1024**2), 1),
            'process_vms_mb': round(mem_info.vms / (1024**2), 1),
            'system_available_mb': round(system_mem.available / (1024**2), 1),
            'system_percent': round(system_mem.percent, 1)
        }
    except Exception as e:
        # Fail silently - debug feature shouldn't break production
        import sys
        print(f"DEBUG_MODE: memory stats collection failed: {e}", file=sys.stderr, flush=True)
        return None


def log_memory_checkpoint(logger: logging.Logger, checkpoint_name: str, **extra_fields):
    """
    Log a memory usage checkpoint.

    Only logs if DEBUG_MODE=true. Otherwise, this is a no-op.
    Adds memory stats and custom fields to the log entry.

    Args:
        logger: Python logger instance
        checkpoint_name: Descriptive name for this checkpoint
        **extra_fields: Additional context fields (e.g., file_size_mb=815)

    Example:
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "create_cog")
        log_memory_checkpoint(logger, "After blob download", file_size_mb=815)
    """
    mem_stats = get_memory_stats()
    if mem_stats:
        # Merge memory stats with extra fields
        all_fields = {**mem_stats, **extra_fields, 'checkpoint': checkpoint_name}
        logger.info(f"📊 MEMORY CHECKPOINT: {checkpoint_name}", extra={'custom_dimensions': all_fields})


# ============================================================================
# COMPONENT TYPES - Aligned with pyramid architecture
# ============================================================================

class ComponentType(Enum):
    """
    Component types aligned with pyramid architecture layers.
    
    Each layer has specific logging needs and levels.
    NO "UTIL" or other non-architectural types.
    """
    CONTROLLER = "controller"  # Job orchestration layer
    SERVICE = "service"        # Business logic layer  
    REPOSITORY = "repository"  # Data access layer
    FACTORY = "factory"        # Object creation layer
    SCHEMA = "schema"          # Foundation layer
    TRIGGER = "trigger"        # Entry point layer
    ADAPTER = "adapter"        # External integration layer
    VALIDATOR = "validator"    # Validation layer (import validator, etc.)


# ============================================================================
# LOG LEVELS - Standard Python levels with enum safety
# ============================================================================

class LogLevel(Enum):
    """
    Standard Python log levels as enum for type safety.
    """
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    
    def to_python_level(self) -> int:
        """Convert to Python logging level constant."""
        return getattr(logging, self.value)
    
    @classmethod
    def from_string(cls, level: str) -> 'LogLevel':
        """Create from string, case-insensitive."""
        return cls[level.upper()]


# ============================================================================
# LOG CONTEXT - Correlation and tracking
# ============================================================================

@dataclass
class LogContext:
    """
    Context for log correlation across operations.
    
    Implements Robert's lineage pattern where task IDs
    contain stage information for multi-stage workflows.
    """
    # Job-level correlation
    job_id: Optional[str] = None  # Parent job ID
    job_type: Optional[str] = None  # Type of job
    
    # Task-level correlation
    task_id: Optional[str] = None  # Task ID with stage (a1b2c3d4-s2-tile_x5_y10)
    task_type: Optional[str] = None  # Type of task
    
    # Stage tracking
    stage: Optional[int] = None  # Current stage number
    
    # Request correlation
    correlation_id: Optional[str] = None  # Request correlation ID
    request_id: Optional[str] = None  # HTTP request ID
    
    # User context
    user_id: Optional[str] = None  # User identifier
    tenant_id: Optional[str] = None  # Tenant identifier
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            k: v for k, v in {
                'job_id': self.job_id,
                'job_type': self.job_type,
                'task_id': self.task_id,
                'task_type': self.task_type,
                'stage': self.stage,
                'correlation_id': self.correlation_id,
                'request_id': self.request_id,
                'user_id': self.user_id,
                'tenant_id': self.tenant_id
            }.items() if v is not None
        }


# ============================================================================
# COMPONENT CONFIGURATION - Per-component settings
# ============================================================================

@dataclass
class ComponentConfig:
    """
    Configuration for component-specific logging.
    
    Each component type can have different settings.
    """
    component_type: ComponentType
    log_level: LogLevel = LogLevel.INFO
    enable_performance_logging: bool = False
    enable_debug_context: bool = False
    max_message_length: int = 1000


# ============================================================================
# LOG EVENT - Structured log entry
# ============================================================================

def _utc_now() -> datetime:
    """Helper function to get current UTC time."""
    return datetime.now(timezone.utc)

@dataclass
class LogEvent:
    """
    Structured log event for consistent logging.
    
    This can be used for structured logging to external
    systems like Azure Application Insights.
    """
    # Core fields
    level: LogLevel
    message: str
    component_type: ComponentType
    component_name: str
    timestamp: datetime = field(default_factory=_utc_now)
    
    # Context
    context: Optional[LogContext] = None
    
    # Error information
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    
    # Performance metrics
    duration_ms: Optional[float] = None
    operation: Optional[str] = None
    
    # Custom dimensions for Azure
    custom_dimensions: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        result = {
            'timestamp': self.timestamp.isoformat(),
            'level': self.level.value,
            'message': self.message,
            'component_type': self.component_type.value,
            'component_name': self.component_name
        }
        
        # Add optional fields if present
        if self.context:
            result['context'] = self.context.to_dict()
        if self.error_type:
            result['error_type'] = self.error_type
        if self.error_message:
            result['error_message'] = self.error_message
        if self.stack_trace:
            result['stack_trace'] = self.stack_trace
        if self.duration_ms is not None:
            result['duration_ms'] = self.duration_ms
        if self.operation:
            result['operation'] = self.operation
        if self.custom_dimensions:
            result['custom_dimensions'] = self.custom_dimensions
            
        return result


# ============================================================================
# OPERATION RESULT - For tracking operation outcomes
# ============================================================================

@dataclass
class OperationResult:
    """
    Result of an operation for consistent success/failure logging.
    """
    success: bool
    operation: str
    component: ComponentType
    duration_ms: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def log_level(self) -> LogLevel:
        """Determine appropriate log level based on result."""
        if self.success:
            return LogLevel.INFO
        elif self.error_message and "critical" in self.error_message.lower():
            return LogLevel.CRITICAL
        else:
            return LogLevel.ERROR


# ============================================================================
# JSON FORMATTER - Structured logging for Azure Functions
# ============================================================================

class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging in Azure Functions.
    Outputs logs in a format that Application Insights can automatically parse.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON for Application Insights.
        
        Args:
            record: Python LogRecord to format
            
        Returns:
            JSON string with structured log data
        """
        # Build base log structure
        log_obj = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'logger': record.name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add custom dimensions if present (for Application Insights)
        if hasattr(record, 'custom_dimensions'):
            log_obj['customDimensions'] = record.custom_dimensions
        
        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': self.formatException(record.exc_info) if record.exc_info else None
            }
        
        # Add any extra fields from the record
        if hasattr(record, 'extra_fields'):
            log_obj.update(record.extra_fields)
        
        return json.dumps(log_obj, default=str)


# ============================================================================
# LOGGER FACTORY - Creates component-specific loggers
# ============================================================================

class LoggerFactory:
    """
    Factory for creating component-specific loggers.
    
    This factory creates Python loggers configured for each
    component type with appropriate settings and context.
    
    Example:
        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "HelloWorldController"
        )
        logger.info("Processing job")
    """
    
    # Default configurations per component type
    # Check environment variable for debug mode
    import os
    default_level = LogLevel.DEBUG if os.getenv('DEBUG_LOGGING', '').lower() == 'true' else LogLevel.INFO
    
    DEFAULT_CONFIGS = {
        ComponentType.CONTROLLER: ComponentConfig(
            component_type=ComponentType.CONTROLLER,
            log_level=default_level,
            enable_performance_logging=True,
            enable_debug_context=True if default_level == LogLevel.DEBUG else False
        ),
        ComponentType.SERVICE: ComponentConfig(
            component_type=ComponentType.SERVICE,
            log_level=default_level,
            enable_performance_logging=True
        ),
        ComponentType.REPOSITORY: ComponentConfig(
            component_type=ComponentType.REPOSITORY,
            log_level=LogLevel.DEBUG,  # Always debug for repositories to track SQL
            enable_debug_context=True
        ),
        ComponentType.FACTORY: ComponentConfig(
            component_type=ComponentType.FACTORY,
            log_level=default_level
        ),
        ComponentType.SCHEMA: ComponentConfig(
            component_type=ComponentType.SCHEMA,
            log_level=LogLevel.DEBUG  # Always debug for schema operations
        ),
        ComponentType.TRIGGER: ComponentConfig(
            component_type=ComponentType.TRIGGER,
            log_level=default_level,
            enable_performance_logging=True
        ),
        ComponentType.ADAPTER: ComponentConfig(
            component_type=ComponentType.ADAPTER,
            log_level=default_level,
            enable_performance_logging=True
        ),
        ComponentType.VALIDATOR: ComponentConfig(
            component_type=ComponentType.VALIDATOR,
            log_level=default_level
        )
    }
    
    @classmethod
    def create_logger(
        cls,
        component_type: ComponentType,
        name: str,
        context: Optional[LogContext] = None,
        config: Optional[ComponentConfig] = None
    ) -> logging.Logger:
        """
        Create a logger for a specific component.
        
        Args:
            component_type: Type of component
            name: Component name (e.g., "HelloWorldController")
            context: Optional log context for correlation
            config: Optional custom configuration
            
        Returns:
            Configured Python logger
        """
        # Use custom config or default for component type
        if config is None:
            config = cls.DEFAULT_CONFIGS.get(
                component_type,
                ComponentConfig(component_type=component_type)
            )
        
        # Create hierarchical logger name
        logger_name = f"{component_type.value}.{name}"
        logger = logging.getLogger(logger_name)
        
        # Set log level - handle both LogLevel enum and string
        if isinstance(config.log_level, str):
            log_level = LogLevel.from_string(config.log_level).to_python_level()
        else:
            log_level = config.log_level.to_python_level()
        logger.setLevel(log_level)
        
        # Remove existing handlers to avoid duplicates
        logger.handlers.clear()
        
        # Create console handler with JSON formatting
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        
        # Use JSON formatter for all output
        formatter = JSONFormatter()
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
        
        # Allow propagation to Azure's root logger for Application Insights
        logger.propagate = True
        
        # Create a wrapper that adds context as custom dimensions
        original_log = logger._log
        
        def log_with_context(level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1):
            """Wrapper to inject context as custom dimensions."""
            if extra is None:
                extra = {}

            # Build base custom dimensions from context
            if context:
                custom_dims = context.to_dict()
                custom_dims['component_type'] = component_type.value
                custom_dims['component_name'] = name
            else:
                custom_dims = {
                    'component_type': component_type.value,
                    'component_name': name
                }

            # Merge with any custom_dimensions passed in extra (for DEBUG_MODE, etc.)
            if 'custom_dimensions' in extra:
                custom_dims.update(extra['custom_dimensions'])

            extra['custom_dimensions'] = custom_dims

            # Call original log method
            original_log(level, msg, args, exc_info=exc_info, extra=extra,
                        stack_info=stack_info, stacklevel=stacklevel)
        
        # Replace the _log method with our wrapper
        logger._log = log_with_context
        
        return logger
    
    @classmethod
    def create_from_config(
        cls,
        config: ComponentConfig,
        name: str,
        context: Optional[LogContext] = None
    ) -> logging.Logger:
        """
        Create logger from explicit configuration.
        
        Args:
            config: Component configuration
            name: Component name
            context: Optional log context
            
        Returns:
            Configured Python logger
        """
        return cls.create_logger(
            component_type=config.component_type,
            name=name,
            context=context,
            config=config
        )
    
    @classmethod
    def create_with_context(
        cls,
        component_type: ComponentType,
        name: str,
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: Optional[int] = None
    ) -> logging.Logger:
        """
        Create logger with job/task context.
        
        Convenience method for creating loggers with common context fields.
        
        Args:
            component_type: Type of component
            name: Component name
            job_id: Optional job ID
            task_id: Optional task ID
            stage: Optional stage number
            
        Returns:
            Configured Python logger with context
        """
        context = LogContext(
            job_id=job_id,
            task_id=task_id,
            stage=stage
        ) if any([job_id, task_id, stage]) else None
        
        return cls.create_logger(
            component_type=component_type,
            name=name,
            context=context
        )


# ============================================================================
# EXCEPTION DECORATOR - Automatic exception logging with context
# ============================================================================

def log_exceptions(component_type: Optional[ComponentType] = None, 
                  component_name: Optional[str] = None,
                  logger: Optional[logging.Logger] = None):
    """
    Decorator to automatically log exceptions with full context.
    
    Can be used in three ways:
    1. With existing logger: @log_exceptions(logger=my_logger)
    2. With component info: @log_exceptions(ComponentType.CONTROLLER, "MyController")
    3. Simple: @log_exceptions() - uses function module and name
    
    Args:
        component_type: Optional component type for creating logger
        component_name: Optional component name for creating logger
        logger: Optional existing logger to use
        
    Returns:
        Decorator function that wraps the target function
        
    Example:
        @log_exceptions(ComponentType.SERVICE, "DataService")
        def process_data(data):
            # If this throws, exception is logged automatically
            return transform(data)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Determine which logger to use
            if logger:
                log = logger
            elif component_type and component_name:
                log = LoggerFactory.create_logger(component_type, component_name)
            else:
                # Create a default logger based on function module
                log = LoggerFactory.create_logger(
                    ComponentType.SERVICE,  # Default to service
                    func.__module__ or "unknown"
                )
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Log with full exception context
                log.error(
                    f"Exception in {func.__name__}",
                    exc_info=True,
                    extra={
                        'custom_dimensions': {
                            'function_name': func.__name__,
                            'function_module': func.__module__,
                            'exception_type': type(e).__name__,
                            'exception_message': str(e),
                            'function_args': str(args)[:500],  # Limit size
                            'function_kwargs': str(kwargs)[:500],  # Limit size
                            'traceback': traceback.format_exc()
                        }
                    }
                )
                # Re-raise the exception - don't swallow it
                raise
        return wrapper
    return decorator


# ============================================================================
# NO LEGACY PATTERNS
# ============================================================================

# NO global logger instances
# NO setup_logger functions  
# NO get_logger with string-only parameters
# NO log_job_stage or other mixed-responsibility functions
# NO backward compatibility layers

# Everything is strongly typed and follows pyramid architecture