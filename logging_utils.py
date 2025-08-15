"""
Logging utilities for Azure Functions geospatial ETL pipeline
Enhanced logging with buffering capabilities
"""
import logging
import logging.handlers
from typing import Optional


class BufferedLogger(logging.Logger):
    """Logger with buffering capabilities for better log management"""
    
    def __init__(self, name: str, level: int = logging.NOTSET):
        super().__init__(name, level)
        self.memory_handler: Optional[logging.handlers.MemoryHandler] = None

    def set_memory_handler(self, memory_handler: logging.handlers.MemoryHandler):
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
    memory_handler = logging.handlers.MemoryHandler(
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


def create_job_logger(job_id: str) -> BufferedLogger:
    """
    Create a job-specific buffered logger
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        BufferedLogger configured for job processing
    """
    logger_name = f"job.{job_id[:8]}"  # Use first 8 chars of job_id
    
    # Create Azure Functions compatible handler
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        f'[JOB:{job_id[:8]}] %(asctime)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    
    return create_buffered_logger(
        name=logger_name,
        target_handler=handler,
        capacity=500,  # Smaller buffer for job-specific logs
        flush_level=logging.WARNING  # Flush on warnings and errors
    )