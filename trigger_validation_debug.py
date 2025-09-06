# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Advanced validation debugging trigger for TaskRecord errors
# SOURCE: Azure Functions HTTP trigger for development debugging
# SCOPE: Development-specific diagnostic endpoint  
# VALIDATION: Bypasses normal flow to test validation in isolation
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
from validator_schema import SchemaValidator
from schema_core import TaskRecord

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
        
        # Test 2: SchemaValidator validation  
        logger.error("🔬 TEST 2: SchemaValidator.validate_task_record()")
        try:
            validator_task = SchemaValidator.validate_task_record(request_body, strict=True)
            logger.error(f"✅ VALIDATOR SUCCESS: {validator_task.task_id}")
            validator_success = True
            validator_error = None
        except Exception as validator_exc:
            logger.error(f"❌ VALIDATOR FAILED: {type(validator_exc).__name__}: {validator_exc}")
            validator_success = False  
            validator_error = str(validator_exc)
        
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