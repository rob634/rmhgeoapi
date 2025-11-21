# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER BASE CLASS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - Abstract base class for all HTTP triggers
# PURPOSE: Abstract HTTP trigger base class providing consistent request/response handling for Azure Functions
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: BaseHttpTrigger, JobManagementTrigger, SystemMonitoringTrigger
# INTERFACES: ABC (Abstract Base Class) - defines contract for HTTP trigger implementations
# PYDANTIC_MODELS: None - uses dict validation for request/response data
# DEPENDENCIES: abc, azure.functions, util_logger, typing, json, datetime, uuid
# SOURCE: HTTP requests from Azure Functions runtime, environment variables for configuration
# SCOPE: HTTP infrastructure layer - request validation, response formatting, error handling, repository access
# VALIDATION: Request method validation, required parameter checking, JSON body parsing, job ID format validation
# PATTERNS: Template Method pattern, Abstract Factory (for trigger types), Lazy Initialization (repositories)
# ENTRY_POINTS: class MyTrigger(BaseHttpTrigger); trigger.handle_request(req)
# INDEX: BaseHttpTrigger:52, handle_request:111, extract_path_params:211, JobManagementTrigger:377, SystemMonitoringTrigger:421
# ============================================================================

"""
HTTP Trigger Base Class - Infrastructure Layer

Abstract base class for all Azure Functions HTTP triggers providing consistent
infrastructure patterns for request/response handling, validation, and repository access.

Key Features:
- Template Method pattern for consistent HTTP request flow
- Standardized error handling with proper HTTP status codes
- Parameter extraction and validation (path params, query params, JSON body)
- Structured logging with request context (request_id, correlation tracking)
- Lazy repository initialization (job_repository, task_repository properties)
- Standard HTTP response formatting (JSON serialization, headers)

Three Specialized Trigger Types:
1. BaseHttpTrigger - Generic HTTP endpoint (implement process_request)
2. JobManagementTrigger - Job submission/status endpoints (adds repository access)
3. SystemMonitoringTrigger - Health check/monitoring endpoints (adds component_health utility)

This separates HTTP infrastructure concerns from business logic.
HTTP triggers are system interface functions, not core business logic.

Usage Pattern:
    1. Inherit from appropriate base class (BaseHttpTrigger, JobManagementTrigger, SystemMonitoringTrigger)
    2. Implement get_allowed_methods() -> List[str]
    3. Implement process_request(req) -> Dict[str, Any]
    4. Use provided utilities (extract_path_params, extract_json_body, validate_job_id)
    5. Return dict from process_request (automatically serialized to JSON)

Template Method Flow:
    handle_request(req) [concrete]
    ├── Validate HTTP method
    ├── Log request start
    ├── Call process_request(req) [abstract - implement in subclass]
    ├── Serialize response to JSON
    ├── Add response headers (request_id, timestamp)
    └── Return func.HttpResponse

Example:
    ```python
    class MyTrigger(JobManagementTrigger):
        def __init__(self):
            super().__init__("my_trigger")

        def get_allowed_methods(self) -> List[str]:
            return ["POST"]

        def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
            # Extract parameters
            params = self.extract_json_body(req, required=True)

            # Use repository access (from JobManagementTrigger)
            job = self.job_repository.get_job(params['job_id'])

            # Return response dict
            return {"status": "success", "job": job}
    ```

Last Updated: 29 OCT 2025
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Union, List
import uuid
import json
from datetime import datetime, timezone

import azure.functions as func
from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext


class BaseHttpTrigger(ABC):
    """
    Abstract base class for Azure Functions HTTP triggers.
    
    Provides consistent infrastructure for HTTP request/response handling,
    parameter extraction, error handling, and logging patterns.
    """
    
    def __init__(self, trigger_name: str):
        """
        Initialize HTTP trigger with name for logging context.
        
        Args:
            trigger_name: Name of the trigger for logging (e.g., "submit_job", "health_check")
        """
        self.trigger_name = trigger_name
        self.logger = LoggerFactory.create_logger(ComponentType.TRIGGER, f"HttpTrigger.{trigger_name}")
    
    # ========================================================================
    # ABSTRACT METHODS - Must be implemented by concrete triggers
    # ========================================================================
    
    @abstractmethod
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process the HTTP request and return response data.
        
        This is where business logic goes. Should raise appropriate exceptions
        for error conditions that will be handled by the base class.
        
        Args:
            req: Azure Functions HTTP request object
            
        Returns:
            Dictionary to be serialized as JSON response
            
        Raises:
            ValueError: For client errors (400)
            PermissionError: For authorization errors (403) 
            FileNotFoundError: For not found errors (404)
            Exception: For internal server errors (500)
        """
        pass
    
    @abstractmethod
    def get_allowed_methods(self) -> List[str]:
        """
        Return list of allowed HTTP methods for this trigger.
        
        Returns:
            List of HTTP methods (e.g., ["GET"], ["POST"], ["GET", "POST"])
        """
        pass
    
    # ========================================================================
    # CONCRETE INFRASTRUCTURE METHODS
    # ========================================================================
    
    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Main entry point for HTTP request handling.
        
        Provides consistent error handling, logging, and response formatting.
        
        Args:
            req: Azure Functions HTTP request object
            
        Returns:
            Azure Functions HTTP response with JSON content
        """
        request_id = self._generate_request_id()
        
        # Log request start with context
        self.logger.info(
            f"🌐 [{self.trigger_name}] Request {request_id} started: "
            f"{req.method} {req.url}"
        )
        
        try:
            # Validate HTTP method
            if req.method not in self.get_allowed_methods():
                return self._create_error_response(
                    error="Method not allowed",
                    message=f"Method {req.method} not allowed. Allowed: {', '.join(self.get_allowed_methods())}",
                    status_code=405,
                    request_id=request_id
                )
            
            # Process the request (business logic)
            response_data = self.process_request(req)
            
            # Create success response
            response = self._create_success_response(response_data, request_id)
            
            self.logger.info(
                f"✅ [{self.trigger_name}] Request {request_id} completed successfully"
            )
            
            return response
            
        except ValueError as e:
            # Client errors (400)
            self.logger.warning(f"❌ [{self.trigger_name}] Client error: {e}")
            return self._create_error_response(
                error="Bad request",
                message=str(e),
                status_code=400,
                request_id=request_id
            )
            
        except PermissionError as e:
            # Authorization errors (403)
            self.logger.warning(f"🚫 [{self.trigger_name}] Permission denied: {e}")
            return self._create_error_response(
                error="Forbidden", 
                message=str(e),
                status_code=403,
                request_id=request_id
            )
            
        except FileNotFoundError as e:
            # Not found errors (404)
            self.logger.info(f"🔍 [{self.trigger_name}] Not found: {e}")
            return self._create_error_response(
                error="Not found",
                message=str(e),
                status_code=404,
                request_id=request_id
            )

        except Exception as e:
            # Check if it's Azure ResourceNotFoundError (Phase 1/2 validation)
            # This is a client error (bad input), not a server error
            if e.__class__.__name__ == 'ResourceNotFoundError':
                self.logger.info(f"🔍 [{self.trigger_name}] Resource not found (client error): {e}")
                return self._create_error_response(
                    error="Not found",
                    message=str(e),
                    status_code=404,
                    request_id=request_id
                )

            # All other exceptions are internal server errors
            # Internal server errors (500)
            self.logger.error(f"💥 [{self.trigger_name}] Internal error: {e}")
            import traceback
            self.logger.debug(f"📍 Full traceback: {traceback.format_exc()}")
            
            return self._create_error_response(
                error="Internal server error",
                message=str(e),
                status_code=500,
                request_id=request_id,
                include_debug_info=True
            )
    
    # ========================================================================
    # UTILITY METHODS FOR SUBCLASSES
    # ========================================================================
    
    def extract_path_params(self, req: func.HttpRequest, required_params: List[str]) -> Dict[str, str]:
        """
        Extract and validate path parameters.
        
        Args:
            req: HTTP request object
            required_params: List of required parameter names
            
        Returns:
            Dictionary of parameter name -> value
            
        Raises:
            ValueError: If required parameters are missing
        """
        params = {}
        missing_params = []
        
        for param_name in required_params:
            value = req.route_params.get(param_name)
            if not value:
                missing_params.append(param_name)
            else:
                params[param_name] = value
        
        if missing_params:
            raise ValueError(f"Missing required path parameters: {', '.join(missing_params)}")
        
        return params
    
    def extract_query_params(self, req: func.HttpRequest, 
                           required_params: Optional[List[str]] = None,
                           optional_params: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Extract and validate query parameters.
        
        Args:
            req: HTTP request object
            required_params: List of required parameter names
            optional_params: List of optional parameter names
            
        Returns:
            Dictionary of parameter name -> value
            
        Raises:
            ValueError: If required parameters are missing
        """
        params = {}
        required_params = required_params or []
        optional_params = optional_params or []
        missing_params = []
        
        # Extract required parameters
        for param_name in required_params:
            value = req.params.get(param_name)
            if not value:
                missing_params.append(param_name)
            else:
                params[param_name] = value
        
        # Extract optional parameters
        for param_name in optional_params:
            value = req.params.get(param_name)
            if value:
                params[param_name] = value
        
        if missing_params:
            raise ValueError(f"Missing required query parameters: {', '.join(missing_params)}")
        
        return params
    
    def extract_json_body(self, req: func.HttpRequest, required: bool = True) -> Optional[Dict[str, Any]]:
        """
        Extract and parse JSON request body.
        
        Args:
            req: HTTP request object
            required: Whether body is required
            
        Returns:
            Parsed JSON data or None if not required and missing
            
        Raises:
            ValueError: If body is required but missing or invalid JSON
        """
        try:
            body = req.get_json()
            
            if body is None and required:
                raise ValueError("Request body is required")
            
            return body
            
        except ValueError as e:
            if "JSON" in str(e):
                raise ValueError(f"Invalid JSON in request body: {e}")
            raise  # Re-raise other ValueErrors
    
    def validate_required_fields(self, data: Dict[str, Any], required_fields: List[str]) -> None:
        """
        Validate that required fields are present in data.
        
        Args:
            data: Data dictionary to validate
            required_fields: List of required field names
            
        Raises:
            ValueError: If required fields are missing
        """
        missing_fields = [field for field in required_fields if field not in data or data[field] is None]
        
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
    
    # ========================================================================
    # PRIVATE INFRASTRUCTURE METHODS
    # ========================================================================
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID for tracing."""
        
        return str(uuid.uuid4())[:8]
    
    def _create_success_response(self, data: Dict[str, Any], request_id: str) -> func.HttpResponse:
        """Create standardized success response."""
        response_data = {
            **data,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return func.HttpResponse(
            json.dumps(response_data, default=str),
            status_code=200,
            mimetype="application/json",
            headers={"X-Request-ID": request_id}
        )
    
    def _create_error_response(self, error: str, message: str, status_code: int, 
                             request_id: str, include_debug_info: bool = False) -> func.HttpResponse:
        """Create standardized error response."""
        response_data = {
            "error": error,
            "message": message,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if include_debug_info:
            # Add debug information for 500 errors
            response_data["debug"] = {
                "trigger_name": self.trigger_name,
                "python_version": __import__("sys").version.split()[0]
            }
        
        return func.HttpResponse(
            json.dumps(response_data),
            status_code=status_code,
            mimetype="application/json",
            headers={"X-Request-ID": request_id}
        )


# ============================================================================
# SPECIALIZED BASE CLASSES FOR COMMON PATTERNS
# ============================================================================

class JobManagementTrigger(BaseHttpTrigger):
    """Base class for job-related HTTP triggers (submit, status, etc.)"""
    
    def __init__(self, trigger_name: str):
        super().__init__(trigger_name)
        
        # Lazy-load repository to avoid circular dependencies
        self._job_repository = None
    
    @property
    def job_repository(self):
        """Lazy-loaded job repository."""
        # This needs to be fixeds so we don't rely on lazy loads
        if self._job_repository is None:
            from infrastructure import RepositoryFactory
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']
            self._job_repository = job_repo
        return self._job_repository
    
    def validate_job_id(self, job_id: str) -> str:
        """
        Validate job ID format.
        
        Args:
            job_id: Job ID to validate
            
        Returns:
            Validated job ID
            
        Raises:
            ValueError: If job ID format is invalid
        """
        if not job_id:
            raise ValueError("job_id is required")
        
        if len(job_id) != 64:
            raise ValueError("job_id must be 64 characters (SHA256 hash)")
        
        if not all(c in '0123456789abcdef' for c in job_id.lower()):
            raise ValueError("job_id must be a valid hexadecimal hash")
        
        return job_id


class SystemMonitoringTrigger(BaseHttpTrigger):
    """Base class for system monitoring triggers (health, metrics, etc.)"""
    
    def __init__(self, trigger_name: str):
        super().__init__(trigger_name)
    
    def get_system_timestamp(self) -> str:
        """Get standardized system timestamp."""
        return datetime.now(timezone.utc).isoformat()
    
    def check_component_health(self, component_name: str, check_function) -> Dict[str, Any]:
        """
        Standard pattern for checking component health.
        
        Args:
            component_name: Name of the component
            check_function: Function that returns health status
            
        Returns:
            Health check result dictionary
        """
        try:
            result = check_function()
            return {
                "component": component_name,
                "status": "healthy",
                "details": result,
                "checked_at": self.get_system_timestamp()
            }
        except Exception as e:
            return {
                "component": component_name, 
                "status": "unhealthy",
                "error": str(e),
                "checked_at": self.get_system_timestamp()
            }