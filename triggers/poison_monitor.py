# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# CATEGORY: HTTP TRIGGER ENDPOINTS
# PURPOSE: Azure Functions HTTP API endpoint
# EPOCH: Shared by all epochs (API layer)
# TODO: Audit for framework logic that may belong in CoreMachine# PURPOSE: Poison queue monitoring HTTP trigger for detecting and processing failed queue messages
# EXPORTS: PoisonQueueMonitorTrigger (HTTP trigger class for poison queue monitoring)
# INTERFACES: SystemMonitoringTrigger (inherited from trigger_http_base)
# PYDANTIC_MODELS: None directly - uses dict for monitoring results
# DEPENDENCIES: trigger_http_base, poison_queue_monitor (service), typing, azure.functions (implicit)
# SOURCE: HTTP GET/POST requests, Azure Storage poison queues via service layer
# SCOPE: Queue health monitoring - poison message detection, processing, and cleanup
# VALIDATION: Queue existence validation, poison message correlation with jobs/tasks
# PATTERNS: Template Method (implements base class), Observer pattern (monitoring), Command pattern (cleanup)
# ENTRY_POINTS: trigger = PoisonQueueMonitorTrigger(); response = trigger.handle_request(req)
# INDEX: PoisonQueueMonitorTrigger:117, process_request:140, _check_poison_status:200, _process_poison_messages:300
# ============================================================================

"""
Poison Queue Monitor HTTP Trigger - Azure Geospatial ETL Pipeline

HTTP endpoint implementation for poison queue monitoring and cleanup using SystemMonitoringTrigger
pattern. Provides comprehensive poison message detection, processing, and system health monitoring
for the Azure Storage Queue infrastructure supporting the Job→Stage→Task architecture.

Architecture Responsibility:
    This module provides QUEUE HEALTH MONITORING within the Job→Stage→Task architecture:
    - Job Layer: Poison message detection for stuck job processing
    - Task Layer: Failed task identification and cleanup processing
    - Queue Layer: Storage queue health monitoring and poison message management
    - System Layer: Overall pipeline health monitoring and error recovery

Key Features:
- Dual-mode operation (GET for status checking, POST for poison message processing)
- Comprehensive poison message detection across all system queues
- Automatic job and task failure marking for poison messages
- Detailed queue health reporting with per-queue statistics
- Safe poison message cleanup with audit trail and logging
- System health status determination based on poison message counts
- Error recovery mechanisms for queue processing failures

Poison Message Detection:
    Messages become "poison" when they fail processing multiple times:
    - Azure Storage Queues automatically move messages to poison queues after 5 failed attempts
    - PoisonQueueMonitor detects these messages and correlates them with jobs/tasks
    - Jobs and tasks associated with poison messages are marked as FAILED
    - System health status reflects poison message presence

Queue Monitoring Workflow:
    GET Request → Check Poison Status → Queue Analysis
                                    ↓
    Per-Queue Counts → Health Status → Response
    
    POST Request → Process Poison Messages → Job/Task Failure Marking
                                         ↓
    Cleanup Messages → Audit Logging → Recovery Response

Integration Points:
- Uses SystemMonitoringTrigger base class for consistent monitoring patterns
- Integrates with PoisonQueueMonitor utility for queue operations
- Connects to job and task repositories for failure marking
- Provides health status to monitoring dashboards and alerting systems
- Feeds into system recovery procedures and operational workflows

API Endpoints:
    GET /api/monitor/poison
    - Returns current poison message status across all queues
    - Non-destructive operation for health monitoring
    - Provides detailed queue statistics and health assessment
    
    POST /api/monitor/poison  
    - Processes and cleans up poison messages
    - Marks associated jobs and tasks as failed
    - Returns processing results and cleanup statistics

Response Formats:
    GET Response (Status Check):
    {
        "action": "status_check",
        "poison_messages_found": 5,
        "queues_checked": ["geospatial-jobs", "geospatial-tasks"],
        "queue_details": {"geospatial-jobs": {"count": 3}},
        "status": "healthy|attention_needed",
        "last_checked": "2025-01-30T12:34:56.789Z"
    }
    
    POST Response (Process Messages):
    {
        "action": "process_poison_messages",
        "poison_messages_found": 5,
        "jobs_marked_failed": 3,
        "tasks_marked_failed": 2,
        "processed_at": "2025-01-30T12:34:56.789Z",
        "messages": ["Processing details..."],
        "success": true
    }

Monitoring Benefits:
- Early detection of queue processing issues before they impact system performance
- Automated cleanup of poison messages preventing queue bloat and performance degradation
- Clear correlation between poison messages and failed jobs/tasks for debugging
- Health status reporting for operational monitoring and alerting
- Recovery mechanisms maintaining system reliability and availability

Usage Examples:
    # Check poison message status
    GET /api/monitor/poison
    → Returns current queue health without making changes
    
    # Process and cleanup poison messages
    POST /api/monitor/poison
    → Cleans up poison messages and marks associated jobs/tasks as failed
    
    # Automated monitoring (typically called by timer trigger)
    curl -X GET https://app.azurewebsites.net/api/monitor/poison

Author: Azure Geospatial ETL Team
"""

from typing import Dict, Any, List

import azure.functions as func
from .http_base import SystemMonitoringTrigger


class PoisonQueueMonitorTrigger(SystemMonitoringTrigger):
    """Poison queue monitoring HTTP trigger implementation."""
    
    def __init__(self):
        super().__init__("poison_queue_monitor")
    
    def get_allowed_methods(self) -> List[str]:
        """Poison queue monitoring supports GET and POST."""
        return ["GET", "POST"]
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process poison queue monitoring request.
        
        Args:
            req: HTTP request (GET=check status, POST=process poison messages)
            
        Returns:
            Poison queue monitoring response data
        """
        if req.method == "GET":
            return self._check_poison_status()
        elif req.method == "POST":
            return self._process_poison_messages()
    
    def _check_poison_status(self) -> Dict[str, Any]:
        """
        Check current poison message status without processing.
        
        Returns:
            Status information about poison messages
        """
        self.logger.info("🔍 Checking poison queue status")
        
        try:
            # Import poison queue monitor
            from poison_queue_monitor import PoisonQueueMonitor
            
            monitor = PoisonQueueMonitor()
            
            # Get poison message counts
            poison_counts = monitor.get_poison_message_counts()
            
            return {
                "action": "status_check",
                "poison_messages_found": poison_counts.get("total_poison_messages", 0),
                "queues_checked": poison_counts.get("queues_checked", []),
                "queue_details": poison_counts.get("queue_details", {}),
                "last_checked": self.get_system_timestamp(),
                "status": "healthy" if poison_counts.get("total_poison_messages", 0) == 0 else "attention_needed"
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error checking poison queue status: {e}")
            raise
    
    def _process_poison_messages(self) -> Dict[str, Any]:
        """
        Process and clean up poison messages.
        
        Returns:
            Processing results
        """
        self.logger.info("🧹 Processing poison messages")
        
        try:
            # Import poison queue monitor
            from poison_queue_monitor import PoisonQueueMonitor
            
            monitor = PoisonQueueMonitor()
            
            # Process poison messages
            processing_result = monitor.process_poison_messages()
            
            # Log results
            jobs_failed = processing_result.get("jobs_marked_failed", 0)
            tasks_failed = processing_result.get("tasks_marked_failed", 0)
            messages_found = processing_result.get("poison_messages_found", 0)
            
            self.logger.info(
                f"✅ Poison message processing complete: "
                f"{messages_found} messages, {jobs_failed} jobs failed, {tasks_failed} tasks failed"
            )
            
            return {
                "action": "process_poison_messages",
                "poison_messages_found": messages_found,
                "jobs_marked_failed": jobs_failed,
                "tasks_marked_failed": tasks_failed,
                "processed_at": self.get_system_timestamp(),
                "messages": processing_result.get("messages", []),
                "success": True
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error processing poison messages: {e}")
            return {
                "action": "process_poison_messages",
                "success": False,
                "error": str(e),
                "processed_at": self.get_system_timestamp()
            }


# Create singleton instance for use in function_app.py
poison_monitor_trigger = PoisonQueueMonitorTrigger()