"""
Poison Queue Monitoring HTTP Trigger - System Monitoring

Concrete implementation of poison queue monitoring endpoint using BaseHttpTrigger.
Handles detection and processing of poison messages in Azure Storage Queues.

Usage:
    GET /api/monitor/poison - Check poison message status
    POST /api/monitor/poison - Process poison messages
    
Response:
    {
        "poison_messages_found": 5,
        "jobs_marked_failed": 3,
        "tasks_marked_failed": 2,
        "processed_at": "ISO-8601",
        "messages": [...],
        "request_id": "uuid",
        "timestamp": "ISO-8601"
    }

Author: Azure Geospatial ETL Team
"""

from typing import Dict, Any, List

import azure.functions as func
from trigger_http_base import SystemMonitoringTrigger


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