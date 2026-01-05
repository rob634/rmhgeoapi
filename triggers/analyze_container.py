# ============================================================================
# CONTAINER ANALYSIS HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET /api/containers/analyze
# PURPOSE: On-demand analysis of list_container_contents job results
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: AnalyzeContainerTrigger, analyze_container_trigger
# DEPENDENCIES: azure.functions, services.container_analysis
# ============================================================================
"""
Container Analysis HTTP Trigger.

On-demand analysis of list_container_contents job results.

Exports:
    AnalyzeContainerTrigger: HTTP trigger class for container analysis
    analyze_container_trigger: Singleton instance of AnalyzeContainerTrigger
"""

import azure.functions as func
import json
from typing import Dict, Any, List
from datetime import datetime, timezone

from triggers.http_base import BaseHttpTrigger
from util_logger import LoggerFactory, ComponentType
from services.container_analysis import analyze_container_job

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AnalyzeContainerTrigger")


class AnalyzeContainerTrigger(BaseHttpTrigger):
    """
    HTTP trigger for container analysis endpoint.

    Analyzes completed list_container_contents jobs to provide insights
    into file types, patterns, duplicates, and storage usage.
    """

    def __init__(self):
        """Initialize the trigger."""
        super().__init__(trigger_name="analyze_container")

    def get_allowed_methods(self) -> List[str]:
        """Return allowed HTTP methods."""
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle GET request for container analysis.

        URL: /api/analysis/container/{job_id}?save=true

        Args:
            req: HTTP request with job_id route parameter

        Query Parameters:
            save: If 'true', save results to blob storage (default: false)

        Returns:
            Dictionary with analysis results (to be serialized by base class)

        Raises:
            ValueError: If job_id is missing or invalid
            FileNotFoundError: If job doesn't exist
        """
        # Extract job_id from route
        job_id = req.route_params.get('job_id')

        if not job_id:
            raise ValueError("Missing job_id parameter")

        # Check save parameter
        save_param = req.params.get('save', 'false').lower()
        save_to_blob = save_param in ('true', '1', 'yes')

        logger.info(f"🔍 Analyzing container job: {job_id[:16]}... (save={save_to_blob})")

        # Run analysis (will raise ValueError if job not found)
        results = analyze_container_job(job_id, save_to_blob=save_to_blob)

        logger.info(f"✅ Analysis complete: {results['summary']['total_files']:,} files analyzed")

        # Return results dict (base class will serialize to JSON)
        return results


# ============================================================================
# TRIGGER INSTANCE - For registration in function_app.py
# ============================================================================

analyze_container_trigger = AnalyzeContainerTrigger()
