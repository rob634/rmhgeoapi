# ============================================================================
# CLAUDE CONTEXT - CORE UTILITIES
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core utilities extracted from schema_base.py
# CATEGORY: UTILITIES
# PURPOSE: Core utility functions and exceptions
# EXPORTS: generate_job_id, SchemaValidationError
# INTERFACES: None
# PYDANTIC_MODELS: None
# DEPENDENCIES: hashlib, json, typing
# SOURCE: Extracted from schema_base.py
# SCOPE: Core utility functions
# VALIDATION: None
# PATTERNS: Utility functions pattern
# ENTRY_POINTS: from core.utils import generate_job_id, SchemaValidationError
# ============================================================================

"""
Core utility functions and exceptions.

Extracted from schema_base.py for Epoch 4 architecture.
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
