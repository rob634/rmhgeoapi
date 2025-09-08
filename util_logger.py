# ============================================================================
# CLAUDE CONTEXT - SERVICE
# ============================================================================
# PURPOSE: Strongly typed logger factory providing consistent logging across Job→Stage→Task architecture
# EXPORTS: LoggerFactory, ComponentType, LogLevel, TypedLogger, get_logger(), log_job_stage(), log_queue_operation()
# INTERFACES: None - provides logging infrastructure for all components
# PYDANTIC_MODELS: ComponentConfig, LogContext (dataclasses for type safety)
# DEPENDENCIES: logging, enum, dataclasses, typing, os, datetime, json, azure.functions (optional)
# SOURCE: Environment variables (LOG_LEVEL, ENVIRONMENT), Azure Functions context for structured logging
# SCOPE: Global logging infrastructure for all application components and services
# VALIDATION: Component type validation, log level validation, context validation via dataclasses
# PATTERNS: Factory pattern, Singleton (LoggerFactory), Strategy pattern (formatters), Decorator (context injection)
# ENTRY_POINTS: logger = LoggerFactory.get_logger(ComponentType.SERVICE, 'MyService'); logger.info('message')
# INDEX: ComponentType:67, LogLevel:80, ComponentConfig:101, TypedLogger:208, LoggerFactory:398, get_logger:627
# ============================================================================

"""
Strongly Typed Logger Factory - Job→Stage→Task Architecture

Provides centralized, type-safe logging infrastructure for the Azure Geospatial ETL Pipeline
with component-specific configurations, correlation ID tracing, and Azure Application Insights
structured logging integration. Eliminates logging inconsistencies and provides comprehensive
debugging capabilities across the entire workflow architecture.

Key Features:
- Type-safe logger creation with Pydantic validation
- Component-specific log levels and formatters (Controllers, Services, Repositories, etc.)
- Automatic correlation ID injection for request tracing across components
- Azure Application Insights structured logging with custom dimensions
- Environment-aware configuration (development, staging, production)
- Performance-optimized buffering strategies per component type
- Workflow-specific loggers with job/task context injection
- Centralized configuration management with runtime validation

Architecture Integration:
- HTTP Triggers: Request tracking with correlation IDs
- Queue Triggers: Job/task processing with workflow context
- Controllers: Workflow orchestration logging with stage progression
- Services: Business logic execution with detailed debugging
- Repositories: Data operations with performance metrics
- Adapters: Storage operations with connection monitoring
- Validators: Schema validation with error details

Usage Patterns:
    # Component-specific loggers
    logger = LoggerFactory.get_logger('controller', 'HelloWorldController')
    logger = LoggerFactory.get_logger('service', 'HelloWorldService')
    
    # Workflow-specific loggers with automatic context
    logger = LoggerFactory.get_workflow_logger(job_id=job_id, stage=stage)
    logger = LoggerFactory.get_task_logger(task_id=task_id, job_id=job_id)
    
    # Automatic structured logging for Azure
    logger.info("Processing stage", extra={'stage': 1, 'task_count': 3})

Author: Azure Geospatial ETL Team
"""

import os
import logging
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, Union, List
from dataclasses import dataclass, field
from logging.handlers import MemoryHandler
import threading
from contextlib import contextmanager

# ============================================================================
# TYPE DEFINITIONS - Strong typing for logger components
# ============================================================================

class ComponentType(Enum):
    """Strongly typed component types for logger factory"""
    HTTP_TRIGGER = "http_trigger"
    QUEUE_TRIGGER = "queue_trigger"
    CONTROLLER = "controller"
    SERVICE = "service"
    REPOSITORY = "repository"
    ADAPTER = "adapter"
    VALIDATOR = "validator"
    UTIL = "util"
    HEALTH = "health"
    POISON_MONITOR = "poison_monitor"

class LogLevel(Enum):
    """Strongly typed log levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class FormatType(Enum):
    """Strongly typed formatter types"""
    REQUEST = "request"        # HTTP request/response logging
    QUEUE = "queue"           # Queue processing with job context
    WORKFLOW = "workflow"     # Job→Stage→Task progression
    BUSINESS = "business"     # Service layer business logic
    DATA = "data"            # Repository/database operations
    STORAGE = "storage"      # Adapter storage operations
    VALIDATION = "validation" # Schema/data validation
    UTILITY = "utility"      # General utility operations
    STRUCTURED = "structured" # Azure Application Insights format

@dataclass
class ComponentConfig:
    """Strongly typed component configuration"""
    level: LogLevel
    format_type: FormatType
    structured: bool = True
    buffer_size: int = 100
    flush_level: LogLevel = LogLevel.ERROR
    include_context: bool = True
    performance_tracking: bool = False

@dataclass
class LogContext:
    """Strongly typed logging context for workflow tracing"""
    correlation_id: Optional[str] = None
    job_id: Optional[str] = None
    stage: Optional[int] = None
    task_id: Optional[str] = None
    job_type: Optional[str] = None
    task_type: Optional[str] = None
    component: Optional[str] = None
    custom_dimensions: Dict[str, Any] = field(default_factory=dict)

# ============================================================================
# COMPONENT CONFIGURATIONS - Type-safe configuration mapping
# ============================================================================

COMPONENT_CONFIGURATIONS: Dict[ComponentType, ComponentConfig] = {
    ComponentType.HTTP_TRIGGER: ComponentConfig(
        level=LogLevel.INFO,
        format_type=FormatType.REQUEST,
        structured=True,
        include_context=True,
        performance_tracking=True
    ),
    ComponentType.QUEUE_TRIGGER: ComponentConfig(
        level=LogLevel.DEBUG,
        format_type=FormatType.QUEUE,
        structured=True,
        buffer_size=1,  # Immediate flushing for debugging poison queue issues
        flush_level=LogLevel.DEBUG,
        include_context=True,
        performance_tracking=True
    ),
    ComponentType.CONTROLLER: ComponentConfig(
        level=LogLevel.INFO,
        format_type=FormatType.WORKFLOW,
        structured=True,
        include_context=True,
        performance_tracking=True
    ),
    ComponentType.SERVICE: ComponentConfig(
        level=LogLevel.DEBUG,
        format_type=FormatType.BUSINESS,
        structured=True,
        include_context=True,
        performance_tracking=False
    ),
    ComponentType.REPOSITORY: ComponentConfig(
        level=LogLevel.INFO,
        format_type=FormatType.DATA,
        structured=True,
        include_context=True,
        performance_tracking=True
    ),
    ComponentType.ADAPTER: ComponentConfig(
        level=LogLevel.WARNING,
        format_type=FormatType.STORAGE,
        structured=True,
        include_context=False,
        performance_tracking=True
    ),
    ComponentType.VALIDATOR: ComponentConfig(
        level=LogLevel.ERROR,
        format_type=FormatType.VALIDATION,
        structured=True,
        include_context=True,
        performance_tracking=False
    ),
    ComponentType.UTIL: ComponentConfig(
        level=LogLevel.INFO,
        format_type=FormatType.UTILITY,
        structured=False,
        include_context=False,
        performance_tracking=False
    ),
    ComponentType.HEALTH: ComponentConfig(
        level=LogLevel.INFO,
        format_type=FormatType.STRUCTURED,
        structured=True,
        include_context=False,
        performance_tracking=True
    ),
    ComponentType.POISON_MONITOR: ComponentConfig(
        level=LogLevel.DEBUG,
        format_type=FormatType.QUEUE,
        structured=True,
        buffer_size=1,  # Critical for debugging poison queue issues
        flush_level=LogLevel.DEBUG,
        include_context=True,
        performance_tracking=True
    )
}

# ============================================================================
# STRONGLY TYPED LOGGER CLASS - Enhanced logging capabilities
# ============================================================================

class TypedLogger:
    """
    Strongly typed logger with workflow context and structured logging capabilities.
    
    Provides type-safe logging operations with automatic context injection,
    structured logging for Azure Application Insights, and performance tracking.
    """
    
    def __init__(self, 
                 logger: logging.Logger, 
                 component_type: ComponentType,
                 component_name: str,
                 config: ComponentConfig,
                 context: Optional[LogContext] = None):
        self._logger = logger
        self.component_type = component_type
        self.component_name = component_name
        self.config = config
        self._context = context or LogContext()
        self._performance_data: Dict[str, float] = {}
    
    @property
    def context(self) -> LogContext:
        """Get current logging context"""
        return self._context
    
    def update_context(self, **kwargs) -> None:
        """Update logging context with new values"""
        for key, value in kwargs.items():
            if hasattr(self._context, key):
                setattr(self._context, key, value)
            else:
                self._context.custom_dimensions[key] = value
    
    def _build_extra_data(self, extra_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build structured logging extra data"""
        if not self.config.structured:
            return extra_data or {}
        
        # Base custom dimensions
        custom_dimensions = {
            'component_type': self.component_type.value,
            'component_name': self.component_name,
            'timestamp_utc': datetime.now(timezone.utc).isoformat()
        }
        
        # Add context if enabled
        if self.config.include_context and self._context:
            if self._context.correlation_id:
                custom_dimensions['correlation_id'] = self._context.correlation_id
            if self._context.job_id:
                custom_dimensions['job_id'] = self._context.job_id
            if self._context.stage is not None:
                custom_dimensions['stage'] = self._context.stage
            if self._context.task_id:
                custom_dimensions['task_id'] = self._context.task_id
            if self._context.job_type:
                custom_dimensions['job_type'] = self._context.job_type
            if self._context.task_type:
                custom_dimensions['task_type'] = self._context.task_type
            
            # Add custom dimensions from context
            custom_dimensions.update(self._context.custom_dimensions)
        
        # Add performance data if tracking enabled
        if self.config.performance_tracking and self._performance_data:
            custom_dimensions['performance'] = self._performance_data.copy()
        
        # Merge with provided extra data
        if extra_data:
            if 'custom_dimensions' in extra_data:
                custom_dimensions.update(extra_data['custom_dimensions'])
                extra_data = extra_data.copy()
                extra_data['custom_dimensions'] = custom_dimensions
            else:
                extra_data['custom_dimensions'] = custom_dimensions
        else:
            extra_data = {'custom_dimensions': custom_dimensions}
        
        return extra_data
    
    @contextmanager
    def performance_timer(self, operation: str):
        """Context manager for performance timing"""
        if not self.config.performance_tracking:
            yield
            return
        
        start_time = datetime.now()
        try:
            yield
        finally:
            duration = (datetime.now() - start_time).total_seconds()
            self._performance_data[operation] = duration
    
    def debug(self, msg: str, *args, extra: Optional[Dict[str, Any]] = None, exc_info=None, **kwargs) -> None:
        """Debug level logging with structured data"""
        extra_data = self._build_extra_data(extra)
        self._logger.debug(msg, *args, extra=extra_data, exc_info=exc_info, **kwargs)
    
    def info(self, msg: str, *args, extra: Optional[Dict[str, Any]] = None, exc_info=None, **kwargs) -> None:
        """Info level logging with structured data"""
        extra_data = self._build_extra_data(extra)
        self._logger.info(msg, *args, extra=extra_data, exc_info=exc_info, **kwargs)
    
    def warning(self, msg: str, *args, extra: Optional[Dict[str, Any]] = None, exc_info=None, **kwargs) -> None:
        """Warning level logging with structured data"""
        extra_data = self._build_extra_data(extra)
        self._logger.warning(msg, *args, extra=extra_data, exc_info=exc_info, **kwargs)
    
    def error(self, msg: str, *args, extra: Optional[Dict[str, Any]] = None, exc_info=None, **kwargs) -> None:
        """Error level logging with structured data"""
        extra_data = self._build_extra_data(extra)
        self._logger.error(msg, *args, extra=extra_data, exc_info=exc_info, **kwargs)
    
    def critical(self, msg: str, *args, extra: Optional[Dict[str, Any]] = None, exc_info=None, **kwargs) -> None:
        """Critical level logging with structured data"""
        extra_data = self._build_extra_data(extra)
        self._logger.critical(msg, *args, extra=extra_data, exc_info=exc_info, **kwargs)

# ============================================================================
# FORMATTER FACTORY - Type-safe formatter creation
# ============================================================================

class FormatterFactory:
    """Factory for creating type-safe formatters"""
    
    _formatters: Dict[FormatType, logging.Formatter] = {}
    
    @classmethod
    def get_formatter(cls, format_type: FormatType) -> logging.Formatter:
        """Get or create formatter for format type"""
        if format_type not in cls._formatters:
            cls._formatters[format_type] = cls._create_formatter(format_type)
        return cls._formatters[format_type]
    
    @classmethod
    def _create_formatter(cls, format_type: FormatType) -> logging.Formatter:
        """Create formatter based on format type"""
        
        if format_type == FormatType.REQUEST:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] HTTP:%(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        elif format_type == FormatType.QUEUE:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] QUEUE:%(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        elif format_type == FormatType.WORKFLOW:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] WORKFLOW:%(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        elif format_type == FormatType.BUSINESS:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] SERVICE:%(name)s:%(funcName)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        elif format_type == FormatType.DATA:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] DATA:%(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        elif format_type == FormatType.STORAGE:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] STORAGE:%(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        elif format_type == FormatType.VALIDATION:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] VALIDATION:%(name)s:%(funcName)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        elif format_type == FormatType.STRUCTURED:
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        else:  # UTILITY or default
            return logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )

# ============================================================================
# STRONGLY TYPED LOGGER FACTORY - Main factory implementation
# ============================================================================

class LoggerFactory:
    """
    Strongly typed logger factory for consistent logging across Job→Stage→Task architecture.
    
    Provides centralized logger creation with type safety, component-specific configurations,
    workflow context injection, and Azure Application Insights structured logging.
    """
    
    _loggers: Dict[str, TypedLogger] = {}
    _lock = threading.Lock()
    _environment: Optional[str] = None
    _azure_functions_configured: bool = False
    
    @classmethod
    def configure_environment(cls, environment: str = None) -> None:
        """Configure logging environment (development, staging, production)"""
        cls._environment = environment or os.environ.get('AZURE_FUNCTIONS_ENVIRONMENT', 'development')
        
        # Adjust log levels based on environment
        if cls._environment.lower() == 'production':
            # Reduce verbosity in production
            for config in COMPONENT_CONFIGURATIONS.values():
                if config.level == LogLevel.DEBUG:
                    config.level = LogLevel.INFO
        elif cls._environment.lower() == 'development':
            # Increase verbosity in development
            for config in COMPONENT_CONFIGURATIONS.values():
                if config.level == LogLevel.WARNING:
                    config.level = LogLevel.INFO
    
    @classmethod
    def configure_azure_functions(cls) -> None:
        """Configure logging for Azure Functions environment"""
        if cls._azure_functions_configured:
            return
        
        # Suppress noisy Azure SDK logging
        azure_loggers = [
            "azure.identity",
            "azure.identity._internal", 
            "azure.core.pipeline.policies.http_logging_policy",
            "azure.storage",
            "azure.core",
            "msal"
        ]
        
        for logger_name in azure_loggers:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        
        cls._azure_functions_configured = True
        cls.configure_environment()
    
    @classmethod
    def get_logger(cls, 
                   component_type: Union[ComponentType, str], 
                   name: str,
                   context: Optional[LogContext] = None) -> TypedLogger:
        """
        Get or create strongly typed logger for component.
        
        Args:
            component_type: Component type enum or string
            name: Logger name (typically class name)
            context: Optional logging context for workflow tracing
            
        Returns:
            TypedLogger instance with component-specific configuration
        """
        # Handle string component type
        if isinstance(component_type, str):
            try:
                component_type = ComponentType(component_type)
            except ValueError:
                component_type = ComponentType.UTIL
        
        # Create unique logger key
        logger_key = f"{component_type.value}:{name}"
        
        with cls._lock:
            if logger_key not in cls._loggers:
                cls._loggers[logger_key] = cls._create_typed_logger(
                    component_type, name, context
                )
            
            # Update context if provided
            if context:
                cls._loggers[logger_key].update_context(**context.__dict__)
            
            return cls._loggers[logger_key]
    
    @classmethod
    def get_workflow_logger(cls, 
                           job_id: str,
                           stage: Optional[int] = None,
                           job_type: Optional[str] = None,
                           correlation_id: Optional[str] = None) -> TypedLogger:
        """
        Get workflow-specific logger with job context.
        
        Args:
            job_id: Job identifier for context
            stage: Optional stage number
            job_type: Optional job type
            correlation_id: Optional correlation ID for request tracing
            
        Returns:
            TypedLogger configured for workflow processing
        """
        context = LogContext(
            correlation_id=correlation_id or job_id[:16],
            job_id=job_id,
            stage=stage,
            job_type=job_type
        )
        
        return cls.get_logger(ComponentType.CONTROLLER, "WorkflowOrchestrator", context)
    
    @classmethod
    def get_task_logger(cls,
                       task_id: str,
                       job_id: str,
                       stage: int,
                       task_type: Optional[str] = None,
                       correlation_id: Optional[str] = None) -> TypedLogger:
        """
        Get task-specific logger with task context.
        
        Args:
            task_id: Task identifier for context
            job_id: Parent job identifier
            stage: Stage number
            task_type: Optional task type
            correlation_id: Optional correlation ID for request tracing
            
        Returns:
            TypedLogger configured for task processing
        """
        context = LogContext(
            correlation_id=correlation_id or job_id[:16],
            job_id=job_id,
            stage=stage,
            task_id=task_id,
            task_type=task_type
        )
        
        return cls.get_logger(ComponentType.SERVICE, "TaskProcessor", context)
    
    @classmethod
    def get_queue_logger(cls,
                        queue_name: str,
                        job_id: Optional[str] = None,
                        task_id: Optional[str] = None) -> TypedLogger:
        """
        Get queue-specific logger optimized for debugging poison queue issues.
        
        Args:
            queue_name: Queue name (e.g., "geospatial-jobs", "geospatial-tasks")
            job_id: Optional job ID for context
            task_id: Optional task ID for context
            
        Returns:
            TypedLogger optimized for queue processing debugging
        """
        context = LogContext(
            correlation_id=job_id[:16] if job_id else None,
            job_id=job_id,
            task_id=task_id,
            custom_dimensions={'queue_name': queue_name}
        )
        
        component_type = (ComponentType.POISON_MONITOR 
                         if 'poison' in queue_name.lower() 
                         else ComponentType.QUEUE_TRIGGER)
        
        return cls.get_logger(component_type, f"QueueProcessor_{queue_name}", context)
    
    @classmethod
    def _create_typed_logger(cls, 
                            component_type: ComponentType,
                            name: str,
                            context: Optional[LogContext] = None) -> TypedLogger:
        """Create new typed logger with component configuration"""
        
        # Configure Azure Functions if not done
        cls.configure_azure_functions()
        
        # Get component configuration
        config = COMPONENT_CONFIGURATIONS[component_type]
        
        # Create underlying Python logger
        logger_name = f"{component_type.value}.{name}"
        python_logger = logging.getLogger(logger_name)
        
        # Set log level
        level = getattr(logging, config.level.value)
        python_logger.setLevel(level)
        
        # Clear existing handlers to avoid duplicates
        python_logger.handlers.clear()
        python_logger.propagate = False
        
        # Create console handler with appropriate formatter
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        formatter = FormatterFactory.get_formatter(config.format_type)
        console_handler.setFormatter(formatter)
        
        # Add buffering if configured
        if config.buffer_size > 1:
            flush_level = getattr(logging, config.flush_level.value)
            memory_handler = MemoryHandler(
                capacity=config.buffer_size,
                flushLevel=flush_level,
                target=console_handler
            )
            python_logger.addHandler(memory_handler)
        else:
            python_logger.addHandler(console_handler)
        
        # Create typed logger wrapper
        return TypedLogger(python_logger, component_type, name, config, context)

# ============================================================================
# LEGACY COMPATIBILITY - Maintain existing interfaces
# ============================================================================

# Global logger for backward compatibility
logger = LoggerFactory.get_logger(ComponentType.UTIL, "RMHGeoAPI")

def get_logger(name: str) -> TypedLogger:
    """Legacy interface - get logger with utility configuration"""
    return LoggerFactory.get_logger(ComponentType.UTIL, name)

# Structured logging functions with enhanced context
def log_job_stage(job_id: str, stage: str, status: str, duration: float = None):
    """Log job processing stages with structured logging for Azure"""
    workflow_logger = LoggerFactory.get_workflow_logger(job_id, stage=int(stage) if stage.isdigit() else None)
    
    msg = f"JOB_STAGE job_id={job_id[:16]}... stage={stage} status={status}"
    if duration:
        msg += f" duration={duration:.2f}s"
    
    extra_data = {
        'custom_dimensions': {
            'stage': stage,
            'status': status,
            'duration': duration if duration else 0,
            'event_type': 'job_stage'
        }
    }
    
    workflow_logger.info(msg, extra=extra_data)

def log_queue_operation(job_id: str, operation: str, queue_name: str = "geospatial-jobs"):
    """Log queue operations with structured logging for Azure"""
    queue_logger = LoggerFactory.get_queue_logger(queue_name, job_id=job_id)
    
    msg = f"QUEUE_OP job_id={job_id[:16]}... operation={operation} queue={queue_name}"
    
    extra_data = {
        'custom_dimensions': {
            'operation': operation,
            'event_type': 'queue_operation'
        }
    }
    
    queue_logger.info(msg, extra=extra_data)

def log_service_processing(service_name: str, job_type: str, job_id: str, status: str):
    """Log service processing with structured logging for Azure"""
    service_logger = LoggerFactory.get_logger(ComponentType.SERVICE, service_name)
    service_logger.update_context(job_id=job_id, job_type=job_type)
    
    msg = f"SERVICE_PROC service={service_name} operation={job_type} job_id={job_id[:16]}... status={status}"
    
    extra_data = {
        'custom_dimensions': {
            'status': status,
            'event_type': 'service_processing'
        }
    }
    
    service_logger.info(msg, extra=extra_data)

# Initialize factory
LoggerFactory.configure_azure_functions()

# Export public interfaces
__all__ = [
    'LoggerFactory',
    'TypedLogger', 
    'ComponentType',
    'LogContext',
    'logger',
    'get_logger',
    'log_job_stage',
    'log_queue_operation', 
    'log_service_processing'
]