"""
Poison Queue Monitor - Detects messages in poison queues and marks corresponding jobs/tasks as failed
Runs on a timer trigger to periodically check for poisoned messages
"""
import json
import base64
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential

from config import Config
from repositories import JobRepository, TaskRepository
from logger_setup import logger


class PoisonQueueMonitor:
    """
    Monitor poison queues and update job/task status accordingly
    Azure automatically moves messages to poison queue after max dequeue attempts
    """
    
    def __init__(self):
        # Initialize queue service
        account_url = Config.get_storage_account_url('queue')
        self.queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        
        # Initialize repositories
        self.job_repo = JobRepository()
        self.task_repo = TaskRepository()
        
        # Define poison queue mappings
        self.poison_queues = {
            "geospatial-jobs-poison": "jobs",
            "geospatial-tasks-poison": "tasks"
        }
        
    def check_poison_queues(self, process_all: bool = False) -> Dict:
        """
        Check all poison queues and process any messages found
        
        Args:
            process_all: If True, process and delete messages. If False, just peek.
        
        Returns:
            Summary of processed poison messages with detailed error capture
        """
        summary = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "poison_messages_found": 0,
            "jobs_marked_failed": 0,
            "tasks_marked_failed": 0,
            "errors": [],
            "messages": [],  # Detailed message information for debugging
            "error_patterns": {},  # Common error types for analysis
            "queue_stats": {}  # Per-queue statistics
        }
        
        for poison_queue_name, entity_type in self.poison_queues.items():
            try:
                logger.info(f"Checking poison queue: {poison_queue_name}")
                
                # Get poison queue client
                poison_queue = self.queue_service.get_queue_client(poison_queue_name)
                
                # Initialize queue stats
                queue_stats = {
                    "queue_name": poison_queue_name,
                    "entity_type": entity_type,
                    "message_count": 0,
                    "messages_processed": 0,
                    "exists": False
                }
                
                # Check if queue exists (it's created automatically when messages fail)
                try:
                    properties = poison_queue.get_queue_properties()
                    message_count = properties.get("approximate_message_count", 0)
                    queue_stats["message_count"] = message_count
                    queue_stats["exists"] = True
                    logger.info(f"Poison queue {poison_queue_name} has approximately {message_count} messages")
                except Exception as e:
                    # Queue doesn't exist yet (no failures)
                    logger.debug(f"Poison queue {poison_queue_name} does not exist (no failures yet)")
                    summary["queue_stats"][poison_queue_name] = queue_stats
                    continue
                
                # Process messages in batches
                total_processed = 0
                batch_size = 32
                max_messages_to_process = 500 if process_all else 32  # Limit processing
                
                while total_processed < max_messages_to_process:
                    # Use receive_messages if processing all, peek if just checking
                    if process_all:
                        # Receive messages (removes them from queue after processing)
                        messages = poison_queue.receive_messages(
                            messages_per_page=batch_size,
                            visibility_timeout=60  # 60 seconds to process
                        )
                    else:
                        # Just peek at messages (doesn't remove them)
                        messages = poison_queue.peek_messages(max_messages=batch_size)
                        # Peek always returns the same messages, so only do one batch
                    
                    messages = list(messages)  # Convert to list to check if empty
                    if not messages:
                        break  # No more messages
                    
                    for message in messages:
                        try:
                            summary["poison_messages_found"] += 1
                            total_processed += 1
                            queue_stats["messages_processed"] += 1
                            
                            # Decode message content
                            message_content = self._decode_message(message.content)
                            
                            # Capture detailed message information for debugging
                            message_info = {
                                "queue": poison_queue_name,
                                "entity_type": entity_type,
                                "dequeue_count": getattr(message, 'dequeue_count', 'unknown'),
                                "inserted_on": getattr(message, 'inserted_on', None),
                                "expires_on": getattr(message, 'expires_on', None),
                                "content": message_content,
                                "message_id": getattr(message, 'id', 'unknown'),
                                "pop_receipt": getattr(message, 'pop_receipt', 'unknown')[:20] if hasattr(message, 'pop_receipt') else 'unknown'
                            }
                            
                            # Convert datetime objects to strings for JSON serialization
                            if message_info["inserted_on"]:
                                message_info["inserted_on"] = message_info["inserted_on"].isoformat()
                            if message_info["expires_on"]:
                                message_info["expires_on"] = message_info["expires_on"].isoformat()
                            
                            summary["messages"].append(message_info)
                            
                            # Analyze error patterns
                            error_type = self._analyze_error_pattern(message_content)
                            if error_type not in summary["error_patterns"]:
                                summary["error_patterns"][error_type] = 0
                            summary["error_patterns"][error_type] += 1
                            
                            if entity_type == "jobs":
                                # Extract job_id and mark as failed
                                job_id = message_content.get("job_id")
                                if job_id:
                                    self._mark_job_failed(job_id, message, message_content)
                                    summary["jobs_marked_failed"] += 1
                                    logger.info(f"Marked job {job_id} as failed (poison queue, dequeue_count: {message_info['dequeue_count']})")
                                    
                            elif entity_type == "tasks":
                                # Extract task_id and mark as failed
                                task_id = message_content.get("task_id")
                                if task_id:
                                    self._mark_task_failed(task_id, message, message_content)
                                    summary["tasks_marked_failed"] += 1
                                    logger.info(f"Marked task {task_id} as failed (poison queue, dequeue_count: {message_info['dequeue_count']})")
                            
                            # Delete message if we received it (not peeked)
                            if process_all and hasattr(message, 'delete'):
                                poison_queue.delete_message(message)
                                logger.debug(f"Deleted poison message after processing")
                            
                        except Exception as e:
                            error_msg = f"Error processing poison message: {str(e)}"
                            logger.error(error_msg)
                            summary["errors"].append(error_msg)
                    
                    # If just peeking, only do one batch
                    if not process_all:
                        break
                
                # Add queue stats to summary
                summary["queue_stats"][poison_queue_name] = queue_stats
                
            except Exception as e:
                error_msg = f"Error checking poison queue {poison_queue_name}: {str(e)}"
                logger.error(error_msg)
                summary["errors"].append(error_msg)
                # Still add queue stats even if error occurred
                if poison_queue_name not in summary["queue_stats"]:
                    summary["queue_stats"][poison_queue_name] = queue_stats
        
        logger.info(f"Poison queue check complete: {summary['poison_messages_found']} messages found, "
                   f"{summary['jobs_marked_failed']} jobs failed, {summary['tasks_marked_failed']} tasks failed")
        
        return summary
    
    def _analyze_error_pattern(self, message_content: Dict) -> str:
        """
        Analyze poison queue message to identify common error patterns.
        
        Args:
            message_content: Decoded message content
            
        Returns:
            Error pattern category for analysis
        """
        try:
            # Look for common error indicators in the message
            if not message_content:
                return "decode_error"
            
            # Check for specific operation types that commonly fail
            operation_type = message_content.get("operation_type") or message_content.get("task_type")
            if operation_type:
                return f"{operation_type}_failure"
            
            # Check for parameter issues
            if "dataset_id" not in message_content:
                return "missing_dataset_id"
            if "resource_id" not in message_content:
                return "missing_resource_id"
            
            # Check message age - old messages might indicate timeout issues
            if "inserted_on" in message_content:
                return "timeout_failure"
            
            return "unknown_failure"
            
        except Exception:
            return "analysis_error"
    
    def _decode_message(self, content: str) -> Dict:
        """
        Decode queue message content (handles Base64 encoding)
        
        Args:
            content: Raw message content from queue
            
        Returns:
            Decoded message as dictionary
        """
        try:
            # Try direct JSON parse first
            return json.loads(content)
        except:
            try:
                # Try Base64 decode then JSON parse
                decoded = base64.b64decode(content).decode('utf-8')
                return json.loads(decoded)
            except Exception as e:
                logger.error(f"Failed to decode message: {e}")
                return {}
    
    def _mark_job_failed(self, job_id: str, message, message_content: Dict):
        """
        Mark a job as failed due to poison queue with enhanced error capture
        
        Args:
            job_id: Job identifier
            message: Poison queue message for context
            message_content: Decoded message content for analysis
        """
        try:
            # Get current job status
            job_status = self.job_repo.get_job_status(job_id)
            
            if job_status and job_status.status != "failed":
                # Calculate failure details
                dequeue_count = getattr(message, 'dequeue_count', 'unknown')
                inserted_on = getattr(message, 'inserted_on', None)
                expires_on = getattr(message, 'expires_on', None)
                
                error_message = (
                    f"Job moved to poison queue after {dequeue_count} dequeue attempts. "
                    f"Maximum retry limit exceeded. "
                    f"Inserted: {inserted_on}, Expires: {expires_on}"
                )
                
                # Update job status to failed
                self.job_repo.update_job_status(job_id, "failed", error_message)
                
                # Store poison queue metadata
                result_data = {
                    "poison_queue": True,
                    "dequeue_count": dequeue_count,
                    "moved_to_poison": datetime.now(timezone.utc).isoformat(),
                    "original_error": job.get("error_message", "Unknown error caused max retries")
                }
                
                self.job_repo.update_job_result(job_id, result_data)
                
                logger.warning(f"Job {job_id} marked as failed - moved to poison queue after {dequeue_count} attempts")
                
        except Exception as e:
            logger.error(f"Error marking job {job_id} as failed: {e}")
    
    def _mark_task_failed(self, task_id: str, message, message_content: Dict):
        """
        Mark a task as failed due to poison queue with enhanced error capture
        
        Args:
            task_id: Task identifier
            message: Poison queue message for context
            message_content: Decoded message content for analysis
        """
        try:
            # Get current task status
            task = self.task_repo.get_task(task_id)
            
            if task and task.get("status") != "failed":
                # Calculate failure details
                dequeue_count = getattr(message, 'dequeue_count', 'unknown')
                
                error_message = (
                    f"Task moved to poison queue after {dequeue_count} dequeue attempts. "
                    f"Maximum retry limit exceeded."
                )
                
                # Update task status to failed
                self.task_repo.update_task_status(task_id, "failed", metadata={'error_message': error_message})
                
                # Also update parent job if all tasks are complete/failed
                parent_job_id = task.get("parent_job_id")
                if parent_job_id:
                    self._check_parent_job_completion(parent_job_id)
                
                logger.warning(f"Task {task_id} marked as failed - moved to poison queue after {dequeue_count} attempts")
                
        except Exception as e:
            logger.error(f"Error marking task {task_id} as failed: {e}")
    
    def _check_parent_job_completion(self, job_id: str):
        """
        Check if all tasks for a parent job are complete and update job status
        
        Args:
            job_id: Parent job identifier
        """
        try:
            # Get all tasks for this job
            tasks = self.task_repo.get_tasks_for_job(job_id)
            
            if not tasks:
                return
            
            # Count task statuses
            total = len(tasks)
            completed = sum(1 for t in tasks if t.get("status") == "completed")
            failed = sum(1 for t in tasks if t.get("status") == "failed")
            
            # If all tasks are done (completed or failed)
            if completed + failed == total:
                if failed > 0:
                    # Mark parent job as partially failed
                    error_msg = f"{failed} of {total} tasks failed (moved to poison queue)"
                    self.job_repo.update_job_status(
                        job_id, 
                        "partial_failure",
                        error_message=error_msg
                    )
                    logger.info(f"Parent job {job_id} marked as partial_failure: {failed}/{total} tasks failed")
                else:
                    # All tasks completed successfully
                    self.job_repo.update_job_status(job_id, "completed")
                    logger.info(f"Parent job {job_id} marked as completed: all {total} tasks succeeded")
                    
        except Exception as e:
            logger.error(f"Error checking parent job {job_id} completion: {e}")
    
    def cleanup_old_poison_messages(self, days_to_keep: int = 7) -> int:
        """
        Remove old messages from poison queues after a retention period
        
        Args:
            days_to_keep: Number of days to retain poison messages
            
        Returns:
            Number of messages cleaned up
        """
        cleaned = 0
        
        for poison_queue_name in self.poison_queues.keys():
            try:
                poison_queue = self.queue_service.get_queue_client(poison_queue_name)
                
                # Get all messages (up to 32 at a time)
                messages = poison_queue.receive_messages(messages_per_page=32)
                
                for message in messages:
                    # Check message age
                    if hasattr(message, 'inserted_on') and message.inserted_on:
                        age_days = (datetime.now(timezone.utc) - message.inserted_on).days
                        
                        if age_days > days_to_keep:
                            # Delete old message
                            poison_queue.delete_message(message)
                            cleaned += 1
                            logger.info(f"Cleaned up old poison message (age: {age_days} days)")
                            
            except Exception as e:
                logger.error(f"Error cleaning poison queue {poison_queue_name}: {e}")
        
        return cleaned


def monitor_poison_queues() -> Dict:
    """
    Main entry point for poison queue monitoring
    Can be called from timer trigger or on-demand
    
    Returns:
        Summary of monitoring results
    """
    monitor = PoisonQueueMonitor()
    return monitor.check_poison_queues()


class PoisonQueueDashboard:
    """
    Production-ready poison queue dashboard with analytics and alerting
    """
    
    def __init__(self):
        self.monitor = PoisonQueueMonitor()
    
    def get_health_status(self) -> Dict:
        """
        Get comprehensive health status of poison queues for production monitoring
        
        Returns:
            Health status with alerts and recommendations
        """
        summary = self.monitor.check_poison_queues(process_all=False)
        
        # Calculate health metrics
        total_poison_messages = summary["poison_messages_found"]
        health_status = "healthy"
        alerts = []
        recommendations = []
        
        # Define alert thresholds
        if total_poison_messages > 50:
            health_status = "critical"
            alerts.append(f"High poison message count: {total_poison_messages}")
            recommendations.append("Investigate task processing issues immediately")
        elif total_poison_messages > 10:
            health_status = "warning"
            alerts.append(f"Elevated poison message count: {total_poison_messages}")
            recommendations.append("Review task processing errors")
        
        # Analyze error patterns
        dominant_errors = []
        if summary["error_patterns"]:
            sorted_patterns = sorted(summary["error_patterns"].items(), key=lambda x: x[1], reverse=True)
            for pattern, count in sorted_patterns[:3]:
                dominant_errors.append({"pattern": pattern, "count": count})
                if count > 5:
                    recommendations.append(f"Address {pattern} errors affecting {count} tasks")
        
        return {
            "overall_health": health_status,
            "timestamp": summary["checked_at"],
            "total_poison_messages": total_poison_messages,
            "queues": summary["queue_stats"],
            "alerts": alerts,
            "recommendations": recommendations,
            "dominant_error_patterns": dominant_errors,
            "error_distribution": summary["error_patterns"]
        }
    
    def get_detailed_analysis(self) -> Dict:
        """
        Get detailed analysis of poison queue messages for debugging
        
        Returns:
            Detailed analysis with message samples and trends
        """
        summary = self.monitor.check_poison_queues(process_all=False)
        
        # Sample messages for analysis
        sample_messages = summary["messages"][:10]  # First 10 messages
        
        # Analyze task types
        task_type_failures = {}
        operation_failures = {}
        
        for msg in summary["messages"]:
            content = msg.get("content", {})
            task_type = content.get("task_type") or content.get("operation_type", "unknown")
            
            if task_type not in task_type_failures:
                task_type_failures[task_type] = 0
            task_type_failures[task_type] += 1
            
            # Track specific operation failures
            operation = content.get("operation_type", "unknown")
            if operation not in operation_failures:
                operation_failures[operation] = 0
            operation_failures[operation] += 1
        
        return {
            "timestamp": summary["checked_at"],
            "total_messages_analyzed": len(summary["messages"]),
            "sample_messages": sample_messages,
            "task_type_failures": task_type_failures,
            "operation_failures": operation_failures,
            "error_patterns": summary["error_patterns"],
            "queue_details": summary["queue_stats"],
            "analysis_notes": [
                "Sample messages show actual poison queue content",
                "Task type failures indicate which operations are problematic", 
                "Error patterns help identify root causes",
                "Queue details show message counts and processing stats"
            ]
        }