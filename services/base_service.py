"""Base classes for all services."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import logging


class BaseService(ABC):
    """Base class for all services."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize service with optional logger."""
        self.logger = logger or logging.getLogger(self.__class__.__name__)


class BaseProcessingService(BaseService):
    """Abstract base class for all processing services."""
    
    @abstractmethod
    def process(
        self, 
        job_id: str, 
        dataset_id: str, 
        resource_id: str, 
        version_id: str, 
        operation_type: str
    ) -> Dict:
        """
        Process a job with given parameters.
        
        Args:
            job_id: Unique job identifier
            dataset_id: Dataset or container name
            resource_id: Specific resource identifier
            version_id: Version or processing parameters
            operation_type: Type of operation to perform
            
        Returns:
            Dict with status and result information
        """
        pass
    
    @abstractmethod
    def get_supported_operations(self) -> List[str]:
        """Return list of operations this service supports."""
        pass