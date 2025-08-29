"""
Centralized logging setup for RMH Geospatial API
Provides both simple logging for Azure Functions and buffered logging for services
"""
import os
import logging
from logging.handlers import MemoryHandler
from typing import Optional

BUFFER_SIZE = 1

class BufferedLogger(logging.Logger):
    """Logger with buffering capabilities for better log management"""
    
    def __init__(self, name: str, level: int = logging.NOTSET):
        super().__init__(name, level)
        self.memory_handler: Optional[MemoryHandler] = None

    def set_memory_handler(self, memory_handler: MemoryHandler):
        """Set and add a memory handler for buffering logs"""
        self.memory_handler = memory_handler
        self.addHandler(memory_handler)

    def flush_logger(self):
        if self.memory_handler:
            self.memory_handler.flush()
            
class ListHandler(logging.Handler):
    """Custom logging handler to store log messages in a list."""
    def __init__(self):
        super().__init__()
        self.log_messages = []

    def emit(self, record):
        # Add log messages with WARNING or higher level to the list
        if record.levelno >= logging.DEBUG:
            self.log_messages.append(self.format(record))
            

# Simple formatter
formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
# Create console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)  # Set to DEBUG for detailed output
console_handler.setFormatter(formatter)

# Create a simple logger that writes directly to console
#logger = logging.getLogger("RMHGeoAPI")

# Add handler to logger
#logger.addHandler(console_handler)

logger = BufferedLogger("AzureFunctionAppLogger")
memory_handler = MemoryHandler(
    capacity=BUFFER_SIZE, 
    flushLevel=logging.DEBUG,  # Flush on DEBUG and above
    target=console_handler)

logger.set_memory_handler(memory_handler)
# Prevent duplicate logging
logger.setLevel(logging.DEBUG)  # Set to DEBUG for detailed output
logger.propagate = False
log_list = ListHandler()
log_list.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
logger.addHandler(log_list)
# Function to get a logger for modules
def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module"""
    module_logger = logging.getLogger(name)
    module_logger.setLevel(logging.DEBUG)
    module_logger.addHandler(console_handler)
    module_logger.propagate = False
    return module_logger

# Simple logging methods for job tracking
def log_job_stage(job_id: str, stage: str, status: str, duration: float = None):
    """Log job processing stages with structured logging for Azure"""
    msg = f"JOB_STAGE job_id={job_id[:16]}... stage={stage} status={status}"
    if duration:
        msg += f" duration={duration:.2f}s"
    
    # Add structured logging for Application Insights
    logger.info(msg, extra={
        "custom_dimensions": {
            "job_id": job_id,
            "stage": stage,
            "status": status,
            "duration": duration if duration else 0,
            "event_type": "job_stage"
        }
    })

def log_queue_operation(job_id: str, operation: str, queue_name: str = "geospatial-jobs"):
    """Log queue operations with structured logging for Azure"""
    logger.info(f"QUEUE_OP job_id={job_id[:16]}... operation={operation} queue={queue_name}", extra={
        "custom_dimensions": {
            "job_id": job_id,
            "operation": operation,
            "queue_name": queue_name,
            "event_type": "queue_operation"
        }
    })

def log_service_processing(service_name: str, operation_type: str, job_id: str, status: str):
    """Log service processing with structured logging for Azure"""
    logger.info(f"SERVICE_PROC service={service_name} operation={operation_type} job_id={job_id[:16]}... status={status}", extra={
        "custom_dimensions": {
            "job_id": job_id,
            "service_name": service_name,
            "operation_type": operation_type,
            "status": status,
            "event_type": "service_processing"
        }
    })

# Create buffered logger function for STAC modules
def create_buffered_logger(name: str, 
                          target_handler: logging.Handler = None,
                          capacity: int = 1000,
                          flush_level: int = logging.ERROR) -> BufferedLogger:
    """
    Create a buffered logger with memory handler
    
    Args:
        name: Logger name
        target_handler: Handler to flush to (defaults to StreamHandler)
        capacity: Maximum number of records to buffer
        flush_level: Log level that triggers automatic flush
        
    Returns:
        Configured BufferedLogger instance
    """
    # Set BufferedLogger as the logger class
    logging.setLoggerClass(BufferedLogger)
    
    # Create logger
    logger = logging.getLogger(name)
    
    # Create target handler if not provided
    if target_handler is None:
        target_handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        target_handler.setFormatter(formatter)
    
    # Create memory handler
    memory_handler = MemoryHandler(
        capacity=capacity,
        flushLevel=flush_level,
        target=target_handler
    )
    
    # Set up the buffered logger
    logger.set_memory_handler(memory_handler)
    logger.setLevel(logging.DEBUG)
    
    # Reset logger class to default
    logging.setLoggerClass(logging.Logger)
    
    return logger

# Log initialization
#logger.info("RMH Geospatial API Simple Logger initialized")