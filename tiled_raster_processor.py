"""
Tiled Raster Processing Service - Orchestrates parallel processing of raster tiles

Implements fan-out pattern for processing large rasters as tiles in parallel.
Each tile is processed as a separate task, allowing concurrent processing
across multiple Azure Function workers.

Key Features:
    - Accepts tile definitions from PostGIS tiling service
    - Creates parallel tasks for each tile
    - Tracks task completion and updates job status
    - Supports prepare_for_cog and cog_conversion operations
    - Handles up to 35 tiles (typical for large rasters)

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
import json
import hashlib
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import base64

from services import BaseProcessingService
from repositories import StorageRepository, JobRepository, TaskRepository
from config import Config
from logger_setup import create_buffered_logger
from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential

logger = create_buffered_logger(__name__)


class TiledRasterProcessor(BaseProcessingService):
    """
    Service to process large rasters as tiles in parallel.
    
    Creates individual tasks for each tile, enabling concurrent processing
    across multiple Azure Function workers. Monitors task completion and
    updates job status accordingly.
    """
    
    def __init__(self):
        """Initialize the tiled raster processor with required repositories"""
        self.logger = create_buffered_logger(
            name=f"{__name__}.TiledRasterProcessor",
            capacity=100,
            flush_level=logging.INFO
        )
        self.storage_repo = StorageRepository()
        self.job_repo = JobRepository()
        self.task_repo = TaskRepository()
        
        # Initialize queue service for sending task messages
        account_url = Config.get_storage_account_url('queue')
        self.queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return ["process_tiled_raster", "prepare_tiled_cog", "create_tiled_cog"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str, 
                tiles: Optional[List[Dict[str, Any]]] = None,
                **kwargs) -> Dict:
        """
        Process a large raster as tiles in parallel.
        
        Args:
            job_id: Unique job identifier
            dataset_id: Container name (e.g., 'rmhazuregeobronze')
            resource_id: Path to source raster file
            version_id: Version identifier for outputs
            operation_type: Type of operation ('process_tiled_raster', etc.)
            tiles: List of tile definitions (if provided directly)
            tiling_plan_id: ID of tiling plan in PostGIS (alternative to tiles)
            stac_id: STAC ID to lookup tiling plan (alternative to tiles)
            **kwargs: Additional parameters to pass to tasks
            
        Returns:
            Dict with processing results and task information
        """
        self.logger.info(f"Starting tiled raster processing for {resource_id}")
        
        # Extract parameters from kwargs
        tiling_plan_id = kwargs.get('tiling_plan_id')
        stac_id = kwargs.get('stac_id')
        
        # Get tiles from various sources
        if not tiles:
            # Try to get tiles from database
            if tiling_plan_id or stac_id or resource_id:
                from get_tiling_plan import TilingPlanService
                tiling_service = TilingPlanService()
                
                # Try different methods to get the tiling plan
                plan = None
                if tiling_plan_id:
                    self.logger.info(f"Fetching tiling plan by ID: {tiling_plan_id}")
                    plan = tiling_service.get_tiling_plan(job_id=tiling_plan_id)
                elif stac_id:
                    self.logger.info(f"Fetching tiling plan by STAC ID: {stac_id}")
                    plan = tiling_service.get_tiling_plan(stac_id=stac_id)
                elif resource_id:
                    self.logger.info(f"Fetching tiling plan for file: {resource_id}")
                    plan = tiling_service.get_plan_for_file(resource_id)
                
                if plan and plan.get('tiles'):
                    tiles = plan['tiles']
                    self.logger.info(f"Retrieved {len(tiles)} tiles from database")
                    # Update the tiling plan status
                    tiling_service.update_plan_status(
                        plan['job_id'], 
                        'processing'
                    )
                else:
                    self.logger.warning("No tiling plan found in database")
        
        self.logger.info(f"Job {job_id}: Creating tasks for {len(tiles) if tiles else 0} tiles")
        
        if not tiles:
            return {
                "status": "failed",
                "message": "No tiles provided for processing",
                "error": "tiles parameter is required or no tiling plan found"
            }
        
        # Determine the actual processing operation for each tile
        tile_operation = self._determine_tile_operation(operation_type)
        
        try:
            # Create tasks for each tile
            created_tasks = []
            skipped_tasks = []
            errors = []
            
            for tile_info in tiles:
                try:
                    tile_id = tile_info.get('tile_id', tile_info.get('id'))
                    if not tile_id:
                        errors.append({
                            "tile": tile_info,
                            "error": "No tile_id found in tile definition"
                        })
                        continue
                    
                    # Generate task ID based on parameters
                    task_params = {
                        "parent_job_id": job_id,
                        "dataset_id": dataset_id,
                        "resource_id": resource_id,
                        "tile_id": tile_id,
                        "operation_type": tile_operation
                    }
                    param_str = json.dumps(task_params, sort_keys=True)
                    task_id = hashlib.sha256(param_str.encode()).hexdigest()
                    
                    # Check if task already exists
                    existing_task = self.task_repo.get_task(task_id)
                    
                    if existing_task and existing_task.get('status') in ['completed', 'processing', 'queued']:
                        self.logger.debug(f"Task already exists for tile {tile_id}, status: {existing_task.get('status')}")
                        skipped_tasks.append({
                            "tile_id": tile_id,
                            "reason": f"Task already {existing_task.get('status')}",
                            "task_id": task_id
                        })
                        continue
                    
                    # Create the task data
                    task_data = {
                        'operation_type': tile_operation,
                        'dataset_id': dataset_id,
                        'resource_id': resource_id,
                        'version_id': f"{version_id}_tile_{tile_id}" if version_id else f"tile_{tile_id}",
                        'tile_id': tile_id,
                        'processing_extent': tile_info.get('processing_extent'),
                        'priority': 1,  # All tiles same priority for now
                        **kwargs  # Pass through any additional parameters
                    }
                    
                    # Create task in table storage
                    task_created = self.task_repo.create_task(task_id, job_id, task_data)
                    
                    if task_created:
                        # Queue the task for processing
                        queue_message = {
                            "task_id": task_id,
                            "parent_job_id": job_id,
                            "job_id": task_id,  # Each task can be treated as a job too
                            "operation_type": tile_operation,
                            "dataset_id": dataset_id,
                            "resource_id": resource_id,
                            "version_id": f"{version_id}_tile_{tile_id}" if version_id else f"tile_{tile_id}",
                            "processing_extent": tile_info.get('processing_extent'),
                            "tile_id": tile_id,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            **kwargs
                        }
                        
                        # Send to tasks queue for parallel processing
                        tasks_queue = self.queue_service.get_queue_client("geospatial-tasks")
                        
                        # Encode message to Base64 as expected by Azure Functions
                        message_json = json.dumps(queue_message)
                        encoded_message = base64.b64encode(message_json.encode('utf-8')).decode('ascii')
                        tasks_queue.send_message(encoded_message)
                        
                        # Update task status to queued
                        self.task_repo.update_task_status(task_id, "queued")
                        
                        created_tasks.append({
                            "task_id": task_id,
                            "tile_id": tile_id,
                            "extent": tile_info.get('processing_extent')
                        })
                        
                        self.logger.info(f"Queued task for tile {tile_id} (task_id: {task_id[:8]}...)")
                    
                except Exception as e:
                    self.logger.error(f"Error creating task for tile {tile_id}: {str(e)}")
                    errors.append({
                        "tile_id": tile_id,
                        "error": str(e)
                    })
            
            # Update job with task information
            self.job_repo.update_job_metadata(job_id, {
                "total_tasks": len(tiles),
                "tasks_created": len(created_tasks),
                "tasks_skipped": len(skipped_tasks),
                "task_errors": len(errors)
            })
            
            # Prepare result summary
            result = {
                "status": "completed" if created_tasks else "failed",
                "message": f"Created {len(created_tasks)} tasks for parallel tile processing",
                "summary": {
                    "source_file": resource_id,
                    "total_tiles": len(tiles),
                    "tasks_created": len(created_tasks),
                    "tasks_skipped": len(skipped_tasks),
                    "errors": len(errors),
                    "tile_operation": tile_operation
                }
            }
            
            # Add sample information to avoid exceeding storage limits
            if created_tasks:
                result["sample_tasks"] = [
                    {"tile_id": t["tile_id"], "task_id": t["task_id"][:8] + "..."} 
                    for t in created_tasks[:5]
                ]
                
            if errors:
                result["sample_errors"] = errors[:5]
                
            if len(created_tasks) > 5:
                result["note"] = f"Showing sample of {len(created_tasks)} created tasks"
            
            self.logger.info(
                f"Tiled processing orchestration complete: {len(created_tasks)} tasks created, "
                f"{len(skipped_tasks)} skipped, {len(errors)} errors"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in tiled raster processing: {str(e)}")
            return {
                "status": "failed",
                "message": f"Tiled raster processing failed: {str(e)}",
                "error": str(e)
            }
    
    def _determine_tile_operation(self, job_operation: str) -> str:
        """
        Determine the operation type for individual tile tasks
        
        Args:
            job_operation: The parent job operation type
            
        Returns:
            The operation type for tile tasks
        """
        operation_mapping = {
            'process_tiled_raster': 'prepare_for_cog',
            'prepare_tiled_cog': 'prepare_for_cog',
            'create_tiled_cog': 'cog_conversion'
        }
        
        return operation_mapping.get(job_operation, 'prepare_for_cog')
    
    def check_completion(self, job_id: str) -> Dict:
        """
        Check if all tasks for a job have completed
        
        Args:
            job_id: The parent job ID
            
        Returns:
            Dict with completion status and statistics
        """
        try:
            # Get all tasks for this job
            tasks = self.task_repo.get_tasks_for_job(job_id)
            
            if not tasks:
                return {
                    "all_completed": False,
                    "total_tasks": 0,
                    "completed": 0,
                    "failed": 0,
                    "processing": 0,
                    "queued": 0
                }
            
            # Count task statuses
            status_counts = {
                'completed': 0,
                'failed': 0,
                'processing': 0,
                'queued': 0,
                'pending': 0
            }
            
            for task in tasks:
                status = task.get('status', 'unknown')
                if status in status_counts:
                    status_counts[status] += 1
            
            # Check if all tasks are done (completed or failed)
            total_tasks = len(tasks)
            done_tasks = status_counts['completed'] + status_counts['failed']
            all_completed = done_tasks == total_tasks
            
            result = {
                "all_completed": all_completed,
                "total_tasks": total_tasks,
                "completed": status_counts['completed'],
                "failed": status_counts['failed'],
                "processing": status_counts['processing'],
                "queued": status_counts['queued'],
                "pending": status_counts['pending'],
                "completion_percentage": (done_tasks / total_tasks * 100) if total_tasks > 0 else 0
            }
            
            # If all completed successfully, mark job as completed
            if all_completed and status_counts['failed'] == 0:
                self.job_repo.update_job_status(job_id, 'completed')
                self.logger.info(f"Job {job_id} completed: all {total_tasks} tasks finished successfully")
            elif all_completed and status_counts['failed'] > 0:
                self.job_repo.update_job_status(job_id, 'completed_with_errors')
                self.logger.warning(f"Job {job_id} completed with errors: {status_counts['failed']} of {total_tasks} tasks failed")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error checking task completion for job {job_id}: {str(e)}")
            return {
                "all_completed": False,
                "error": str(e)
            }