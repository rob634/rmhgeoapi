"""
Standalone Azure Functions App - no local imports
"""
import json
import logging
import azure.functions as func

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize function app
app = func.FunctionApp()

@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Simple health check endpoint"""
    logger.info("Health check endpoint called")
    return func.HttpResponse(
        json.dumps({
            "status": "healthy",
            "message": "Azure Functions working - no local imports"
        }),
        status_code=200,
        mimetype="application/json"
    )

logger.info("Standalone function app initialized")