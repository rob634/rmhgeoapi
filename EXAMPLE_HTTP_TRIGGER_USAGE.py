# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Example code demonstrating HTTP trigger base class usage patterns
# SOURCE: No configuration - provides example implementation patterns and documentation
# SCOPE: Example-specific demonstration of HTTP trigger architecture patterns
# VALIDATION: No validation - example code for documentation and reference purposes
# ============================================================================

"""
EXAMPLE: How to use HTTP Trigger Base Classes

This shows how the new HTTP trigger architecture would be integrated
into function_app.py to replace the existing inline implementations.

BEFORE (Inline in function_app.py):
    @app.route(route="health", methods=["GET"])
    def health_check(req: func.HttpRequest) -> func.HttpResponse:
        # 100+ lines of inline health check logic
        # Error handling scattered throughout
        # No consistent response formatting
        pass

AFTER (Using HTTP Trigger Base Classes):
    @app.route(route="health", methods=["GET"])
    def health_check(req: func.HttpRequest) -> func.HttpResponse:
        return health_check_trigger.handle_request(req)
        
This provides:
- Consistent error handling across all HTTP endpoints
- Standardized request/response patterns
- Proper separation of concerns (HTTP infrastructure vs business logic)
- Reusable validation and parameter extraction
- Structured logging with request tracing
- Type safety and testing support
"""

import azure.functions as func

# Import the concrete trigger implementations
from trigger_health import health_check_trigger
from trigger_submit_job import submit_job_trigger  
from trigger_get_job_status import get_job_status_trigger
from trigger_poison_monitor import poison_monitor_trigger

# ============================================================================
# NEW FUNCTION_APP.PY HTTP ENDPOINTS (Using Base Classes)
# ============================================================================

@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint using HTTP trigger base class."""
    return health_check_trigger.handle_request(req)


@app.route(route="jobs/{job_type}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    return submit_job_trigger.handle_request(req)


@app.route(route="jobs/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """Job status retrieval endpoint using HTTP trigger base class."""
    return get_job_status_trigger.handle_request(req)


@app.route(route="monitor/poison", methods=["GET", "POST"])
def check_poison_queues(req: func.HttpRequest) -> func.HttpResponse:
    """Poison queue monitoring endpoint using HTTP trigger base class."""
    return poison_monitor_trigger.handle_request(req)


# ============================================================================
# BENEFITS OF THIS ARCHITECTURE
# ============================================================================

"""
1. SEPARATION OF CONCERNS:
   - HTTP infrastructure logic in base classes
   - Business logic in concrete trigger classes
   - Azure Functions binding stays minimal

2. CONSISTENCY:
   - All endpoints use same error handling patterns
   - Standardized response formats with request_id, timestamp
   - Consistent logging with request tracing

3. REUSABILITY:
   - Common patterns (parameter extraction, validation) in base classes
   - Specialized base classes for job management vs system monitoring
   - Easy to add new endpoints following same patterns

4. TESTABILITY:
   - HTTP triggers can be unit tested independently 
   - Business logic separated from Azure Functions infrastructure
   - Mock HTTP requests for testing

5. MAINTENANCE:
   - Changes to error handling/response formatting in one place
   - New HTTP endpoints follow established patterns
   - Clear abstraction boundaries

6. TYPE SAFETY:
   - Full type hints throughout
   - Pydantic validation where appropriate  
   - Clear interfaces and contracts

EXAMPLE OF ADDING A NEW HTTP ENDPOINT:

class MyNewTrigger(BaseHttpTrigger):
    def get_allowed_methods(self):
        return ["POST"]
    
    def process_request(self, req):
        # Only business logic here
        # Infrastructure handled by base class
        return {"result": "success"}

@app.route(route="my/endpoint", methods=["POST"])
def my_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    return MyNewTrigger("my_endpoint").handle_request(req)
"""