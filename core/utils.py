# ============================================================================
# CORE UTILITY FUNCTIONS
# ============================================================================
# STATUS: Core - Job ID generation and validation utilities
# PURPOSE: Deterministic job ID generation and schema validation exceptions
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Core Utility Functions and Exceptions.

Provides deterministic job ID generation and validation exceptions.

Exports:
    generate_job_id: Generate deterministic job ID from type and parameters
    SchemaValidationError: Exception for schema validation errors
"""

import hashlib
import json
from typing import Dict, Any, Optional


def generate_job_id(job_type: str, parameters: Dict[str, Any]) -> str:
    """
    Generate deterministic job ID from job type and parameters.
    SHA256 hash ensures idempotency - same inputs always produce same ID.

    Args:
        job_type: Type of job (e.g., "hello_world", "process_raster")
        parameters: Job parameters dictionary

    Returns:
        64-character SHA256 hash as job ID

    Example:
        >>> generate_job_id("hello_world", {"message": "test"})
        'a1b2c3d4...'  # Always the same for same inputs
    """
    # Sort parameters to ensure consistent hash
    sorted_params = json.dumps(parameters, sort_keys=True)
    hash_input = f"{job_type}:{sorted_params}"
    return hashlib.sha256(hash_input.encode()).hexdigest()


class SchemaValidationError(Exception):
    """Custom exception for schema validation errors."""

    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        self.field = field
        self.value = value
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        if self.field:
            return f"Schema validation error in field '{self.field}': {self.message}"
        return f"Schema validation error: {self.message}"
