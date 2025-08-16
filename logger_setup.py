"""
Centralized logging setup for RMH Geospatial API
Simple console logger that Azure Functions will pick up directly
"""
import os
import logging
from logging.handlers import MemoryHandler

BUFFER_SIZE = 1

class BufferedLogger(logging.Logger):
    def __init__(self, name, level=logging.NOTSET):
        super().__init__(name, level)
        self.memory_handler = None

    def set_memory_handler(self, memory_handler):
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
# Simple logging methods for job tracking
def log_job_stage(job_id: str, stage: str, status: str, duration: float = None):
    """Log job processing stages"""
    msg = f"JOB_STAGE job_id={job_id[:16]}... stage={stage} status={status}"
    if duration:
        msg += f" duration={duration:.2f}s"
    logger.info(msg)

def log_queue_operation(job_id: str, operation: str, queue_name: str = "geospatial-jobs"):
    """Log queue operations"""
    logger.info(f"QUEUE_OP job_id={job_id[:16]}... operation={operation} queue={queue_name}")

def log_service_processing(service_name: str, operation_type: str, job_id: str, status: str):
    """Log service processing"""
    logger.info(f"SERVICE_PROC service={service_name} operation={operation_type} job_id={job_id[:16]}... status={status}")

# Add these methods to the logger instance
logger.log_job_stage = log_job_stage
logger.log_queue_operation = log_queue_operation 
logger.log_service_processing = log_service_processing

# Log initialization
#logger.info("RMH Geospatial API Simple Logger initialized")