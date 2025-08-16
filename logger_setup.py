"""
Centralized logging setup for RMH Geospatial API
Simple console logger that Azure Functions will pick up directly
"""
import os
import logging


# Create console handler
console_handler = logging.StreamHandler()

# Simple formatter
formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(formatter)

# Create a simple logger that writes directly to console
logger = logging.getLogger("RMHGeoAPI")

# Add handler to logger
logger.addHandler(console_handler)

# Set logging level from environment or default to DEBUG
#log_level = os.environ.get('LOG_LEVEL', 'DEBUG').upper()
logger.setLevel(logging.DEBUG)

# Prevent duplicate logging
logger.propagate = False

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