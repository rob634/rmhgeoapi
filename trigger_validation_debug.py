# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Development-only HTTP trigger for debugging TaskRecord validation errors in isolation
# EXPORTS: main() (Azure Functions entry point for validation debugging)
# INTERFACES: Azure Functions HttpTrigger interface (func.HttpRequest -> func.HttpResponse)
# PYDANTIC_MODELS: TaskRecord (from schema_core) - being validated for debugging
# DEPENDENCIES: azure.functions, util_logger, validator_schema, schema_core, json, logging, traceback
# SOURCE: HTTP POST requests with raw task data JSON for validation testing
# SCOPE: Development debugging - isolated validation testing outside normal workflow
# VALIDATION: TaskRecord schema validation with detailed field-by-field diagnostics
# PATTERNS: Debugging pattern, Diagnostic pattern, Bypass pattern (skips normal workflow)
# ENTRY_POINTS: main(req) called by Azure Functions runtime at POST /api/debug/validation/task
# INDEX: main:31, validation logic:70, diagnostic response:120
# ============================================================================

"""
Advanced validation debugging trigger for TaskRecord validation failures.

This development-only endpoint bypasses normal workflow to test validation 
in complete isolation, providing detailed diagnostics for field-level errors.
"""

import json
import logging
import traceback
from typing import Any, Dict

import azure.functions as func
from util_logger import LoggerFactory
# Removed redundant SchemaValidator - Pydantic does validation automatically
from schema_base import TaskRecord

# Get specialized logger for validation debugging
logger = LoggerFactory.get_logger(LoggerFactory.ComponentType.SERVICE)


def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Debug TaskRecord validation with raw data input.
    
    POST /api/debug/validation/task
    Body: Raw task data JSON for validation testing
    
    Returns detailed field-by-field validation diagnostics.
    """
    logger.error("🔧 VALIDATION DEBUG ENDPOINT TRIGGERED")
    
    try:
        # Parse request body
        try:
            request_body = req.get_json()
            if not request_body:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Request body is required",
                        "example": {
                            "task_id": "debug-task-001",
                            "parent_job_id": "debug-job-001",
                            "task_type": "hello_world_greeting",
                            "status": "pending"
                        }
                    }),
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )
        except Exception as parse_error:
            logger.error(f"❌ Request body parse error: {parse_error}")
            return func.HttpResponse(
                json.dumps({"error": f"Invalid JSON: {parse_error}"}),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )
        
        logger.error(f"📋 DEBUG INPUT RECEIVED: {json.dumps(request_body, indent=2)}")
        
        # Test 1: Direct Pydantic validation bypass
        logger.error("🔬 TEST 1: Direct Pydantic TaskRecord construction")
        try:
            direct_task = TaskRecord(**request_body)
            logger.error(f"✅ DIRECT CONSTRUCTION SUCCESS: {direct_task.task_id}")
            direct_success = True
            direct_error = None
        except Exception as direct_exc:
            logger.error(f"❌ DIRECT CONSTRUCTION FAILED: {type(direct_exc).__name__}: {direct_exc}")
            direct_success = False
            direct_error = str(direct_exc)
        
        # Test 2: Direct Pydantic validation (removed redundant SchemaValidator)
        logger.error("🔬 TEST 2: Direct Pydantic validation")
        # Pydantic already validates - no need for extra wrapper
        validator_success = pydantic_success
        validator_error = pydantic_error
        logger.error(f"📊 Using Pydantic result: success={validator_success}")
        
        # Test 3: Field-by-field analysis
        logger.error("🔬 TEST 3: Field-by-field schema analysis")
        field_analysis = {}
        
        # Get TaskRecord field definitions
        if hasattr(TaskRecord, 'model_fields'):
            expected_fields = TaskRecord.model_fields  # Pydantic v2
        elif hasattr(TaskRecord, '__fields__'):
            expected_fields = TaskRecord.__fields__  # Pydantic v1
        else:
            expected_fields = {}
            
        for field_name, field_info in expected_fields.items():
            is_present = field_name in request_body
            if is_present:
                actual_value = request_body[field_name]
                actual_type = type(actual_value).__name__
                field_analysis[field_name] = {
                    "present": True,
                    "value": str(actual_value),
                    "type": actual_type,
                    "field_info": str(field_info)
                }
            else:
                field_analysis[field_name] = {
                    "present": False,
                    "field_info": str(field_info)
                }
        
        # Check for extra fields
        extra_fields = set(request_body.keys()) - set(expected_fields.keys())
        if extra_fields:
            logger.error(f"⚠️ EXTRA FIELDS FOUND: {extra_fields}")
        
        # Compile results
        debug_results = {
            "timestamp": func.DateTime.utcnow().isoformat(),
            "input_data": request_body,
            "tests": {
                "direct_pydantic": {
                    "success": direct_success,
                    "error": direct_error
                },
                "schema_validator": {
                    "success": validator_success,
                    "error": validator_error
                }
            },
            "field_analysis": field_analysis,
            "extra_fields": list(extra_fields),
            "expected_field_count": len(expected_fields),
            "actual_field_count": len(request_body)
        }
        
        logger.error(f"📊 DEBUG RESULTS: {json.dumps(debug_results, indent=2)}")
        
        return func.HttpResponse(
            json.dumps(debug_results, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )
        
    except Exception as unexpected_error:
        logger.error(f"❌ UNEXPECTED DEBUG ERROR: {type(unexpected_error).__name__}")
        logger.error(f"🔍 Error details: {str(unexpected_error)}")
        logger.error(f"📋 Traceback: {traceback.format_exc()}")
        
        return func.HttpResponse(
            json.dumps({
                "error": "Unexpected debug error",
                "type": type(unexpected_error).__name__,
                "message": str(unexpected_error),
                "traceback": traceback.format_exc()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )