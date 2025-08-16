"""
Centralized logging setup for RMH Geospatial API
Based on the ancient/original logging architecture - much better approach!
All modules import the same logger instance for unified logging.
"""
import os
import logging
from logging.handlers import MemoryHandler

BUFFER_SIZE = 5  # Flush every 5 items for faster feedback

class BufferedLogger(logging.Logger):
    """Enhanced logger with buffering capabilities for Azure Functions"""
    
    def __init__(self, name, level=logging.NOTSET):
        super().__init__(name, level)
        self.memory_handler = None

    def set_memory_handler(self, memory_handler):
        """Set and add a memory handler for buffering logs"""
        self.memory_handler = memory_handler
        self.addHandler(memory_handler)

    def flush_logger(self):
        """Flush buffered logs to target handler"""
        if self.memory_handler:
            self.memory_handler.flush()
            
    def get_buffer_contents(self) -> list:
        """Get current contents of the log buffer"""
        if self.memory_handler and hasattr(self.memory_handler, 'buffer'):
            return self.memory_handler.buffer.copy()
        return []
    
    def clear_buffer(self):
        """Clear the log buffer"""
        if self.memory_handler and hasattr(self.memory_handler, 'buffer'):
            self.memory_handler.buffer.clear()

class ColorFormatter(logging.Formatter):
    """Colored formatter for local development"""

    def _green(self, string):
        return f'\033[92m{string}\033[0m'
    
    def _yellow(self, string):
        return f'\033[93m{string}\033[0m'
    
    def _red(self, string):
        return f'\033[91m{string}\033[0m'
    
    def _blue(self, string):
        return f'\033[94m{string}\033[0m'

    def format(self, record):
        original_format = self._style._fmt

        if record.levelno == logging.ERROR:
            self._style._fmt = self._red(original_format)
        elif record.levelno == logging.WARNING:
            self._style._fmt = self._yellow(original_format)
        elif record.levelno == logging.INFO:
            self._style._fmt = self._green(original_format)
        elif record.levelno == logging.DEBUG:
            self._style._fmt = self._blue(original_format)

        result = logging.Formatter.format(self, record)
        self._style._fmt = original_format

        return result

class ListHandler(logging.Handler):
    """Custom logging handler to store log messages in a list for later retrieval"""
    
    def __init__(self):
        super().__init__()
        self.log_messages = []

    def emit(self, record):
        # Store WARNING and higher level messages
        if record.levelno >= logging.WARNING:
            self.log_messages.append(self.format(record))
    
    def get_messages(self) -> list:
        """Get all stored log messages"""
        return self.log_messages.copy()
    
    def clear_messages(self):
        """Clear stored log messages"""
        self.log_messages.clear()

class GeospatialLogger(BufferedLogger):
    """Enhanced logger with geospatial-specific logging methods"""
    
    def log_job_stage(self, job_id: str, stage: str, status: str, duration: float = None):
        """Log job processing stages"""
        msg = f"JOB_STAGE job_id={job_id[:16]}... stage={stage} status={status}"
        if duration:
            msg += f" duration={duration:.2f}s"
        self.info(msg)
        
    def log_storage_operation(self, operation: str, container: str, blob: str = None, status: str = "success"):
        """Log storage operations"""
        msg = f"STORAGE_OP operation={operation} container={container}"
        if blob:
            msg += f" blob={blob}"
        msg += f" status={status}"
        self.info(msg)
        
    def log_queue_operation(self, job_id: str, operation: str, queue_name: str = "geospatial-jobs"):
        """Log queue operations"""
        self.info(f"QUEUE_OP job_id={job_id[:16]}... operation={operation} queue={queue_name}")
        
    def log_service_processing(self, service_name: str, operation_type: str, job_id: str, status: str):
        """Log service processing"""
        self.info(f"SERVICE_PROC service={service_name} operation={operation_type} job_id={job_id[:16]}... status={status}")
        
    def log_geometry_stats(self, feature_count: int, invalid_count: int = 0, bounds: tuple = None):
        """Log geometry processing statistics"""
        msg = f"GEOMETRY_STATS features={feature_count} invalid={invalid_count}"
        if bounds:
            msg += f" bounds={bounds}"
        self.info(msg)

# Detect environment - Azure Functions vs Local Development
def _detect_environment():
    """Detect if running in Azure Functions or local environment"""
    # Azure Functions sets these environment variables
    azure_functions_indicators = [
        'FUNCTIONS_WORKER_RUNTIME',
        'AzureWebJobsStorage',
        'WEBSITE_SITE_NAME'
    ]
    
    is_azure_functions = any(os.environ.get(var) for var in azure_functions_indicators)
    is_local_dev = 'AMD64' in os.environ.get('PROCESSOR_ARCHITECTURE', '') or 'x86_64' in os.environ.get('PROCESSOR_ARCHITECTURE', '')
    
    return is_azure_functions, is_local_dev

# Initialize the logger based on environment
is_azure_functions, is_local_dev = _detect_environment()

# Create formatter
if is_local_dev and not is_azure_functions:
    # Local development - use colors
    formatter_class = ColorFormatter
    logger_name = "RMHGeoAPI_Local"
else:
    # Azure Functions - plain formatter
    formatter_class = logging.Formatter
    logger_name = "RMHGeoAPI_Azure"

formatter = formatter_class(
    fmt="%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="%",
)

# Create console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# Create the main logger
if is_local_dev and not is_azure_functions:
    # Local development - direct logging
    logger = GeospatialLogger(logger_name)
    logger.addHandler(console_handler)
else:
    # Azure Functions - buffered logging
    logger = GeospatialLogger(logger_name)
    memory_handler = MemoryHandler(
        capacity=BUFFER_SIZE, 
        flushLevel=logging.DEBUG,  # Auto-flush on debug and above for fast feedback
        target=console_handler
    )
    logger.set_memory_handler(memory_handler)

# Set logging level from environment or default to DEBUG for verbose logging
log_level = os.environ.get('LOG_LEVEL', 'DEBUG').upper()
logger.setLevel(getattr(logging, log_level, logging.INFO))
logger.propagate = False

# Add list handler for message collection
log_list = ListHandler()
log_list.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
logger.addHandler(log_list)

# Helper functions for accessing the logger features
def get_log_messages() -> list:
    """Get all collected warning/error messages"""
    return log_list.get_messages()

def clear_log_messages():
    """Clear collected log messages"""
    log_list.clear_messages()

def flush_logs():
    """Manually flush buffered logs"""
    logger.flush_logger()

def get_buffer_contents() -> list:
    """Get current buffer contents"""
    return logger.get_buffer_contents()

# Log initialization
logger.info(f"RMH Geospatial API Logger initialized - Environment: {'Azure Functions' if is_azure_functions else 'Local Development'}")
logger.debug(f"Logger configuration: level={logger.level}, handlers={len(logger.handlers)}")