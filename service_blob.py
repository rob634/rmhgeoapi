# ============================================================================
# CLAUDE CONTEXT - SERVICE
# ============================================================================
# PURPOSE: Blob storage service implementing task handlers for container operations
# EXPORTS: Task handlers registered with @TaskRegistry decorators for blob operations
# INTERFACES: TaskRegistry pattern with handler functions returning dicts
# PYDANTIC_MODELS: BlobMetadata, ContainerSummary, OrchestrationData from schema_blob
# DEPENDENCIES: repository_factory (BlobRepository), task_factory (TaskRegistry, TaskContext), schema_blob
# SOURCE: Task parameters from queue messages via TaskHandlerFactory
# SCOPE: Task-level business logic for container analysis and metadata extraction
# VALIDATION: Parameter validation within handler functions, size limit checks
# PATTERNS: Registry pattern (TaskRegistry), Factory pattern, Dynamic orchestration pattern
# ENTRY_POINTS: Handlers auto-registered via @TaskRegistry decorators
# INDEX: analyze_and_orchestrate:100, extract_metadata:250, summarize_container:400
# ============================================================================

"""
Blob Storage Service - Task Handler Implementation

Service layer implementation for blob storage operations within the
Job→Stage→Task architecture. Implements the "Analyze & Orchestrate" pattern
for dynamic task generation based on container content.

Key Handlers:
- analyze_and_orchestrate: Stage 1 orchestrator for dynamic task creation
- extract_metadata: Stage 2 processor for individual file metadata
- summarize_container: Single-stage container summary operation

Architecture Position:
    - Job Layer: Container controllers orchestrate stages
    - Stage Layer: Creates parallel tasks for execution  
    - Task Layer: THIS MODULE - Business logic execution
    - Repository Layer: BlobRepository handles Azure Storage

Dynamic Orchestration Pattern:
    Stage 1: Single orchestrator analyzes container
    Stage 2: N parallel tasks process individual files
    Stage 3: Optional aggregation of results

Author: Robert and Geospatial Claude Legion
Date: 9 December 2025
"""

# ============================================================================
# IMPORTS - Top of file for fail-fast behavior
# ============================================================================

# Standard library imports
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional

# Application imports - Core dependencies
from task_factory import TaskContext
from repositories import RepositoryFactory
from util_logger import LoggerFactory, ComponentType

# Application imports - Blob schemas
from schema_blob import (
    BlobMetadata,
    ContainerSummary,
    ContainerInventory,
    OrchestrationData,
    FileFilter,
    FileSizeCategory,
    MetadataLevel,
    ContainerSizeLimits
)

# Application imports - Orchestration schemas
from schema_orchestration import (
    FileOrchestrationItem,
    create_file_orchestration_items
)

logger = LoggerFactory.create_logger(ComponentType.SERVICE, __name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_blob_extension(blob_name: str) -> str:
    """Extract file extension from blob name"""
    if '.' in blob_name:
        return blob_name.rsplit('.', 1)[-1].lower()
    return 'no_extension'


def parse_folder_path(blob_name: str) -> str:
    """Extract folder path from blob name"""
    if '/' in blob_name:
        return '/'.join(blob_name.split('/')[:-1])
    return ''


# ============================================================================
# HANDLER METADATA FOR EXPLICIT REGISTRATION
# ============================================================================
# Static metadata for TaskCatalog registration during migration from decorators

ANALYZE_ORCHESTRATE_INFO = {
    'task_type': 'analyze_and_orchestrate',
    'description': 'Analyze container contents and generate dynamic orchestration tasks',
    'timeout_seconds': 120,
    'max_retries': 2,
    'required_services': ['BlobRepository'],
    'stage': 1,
    'features': ['dynamic_orchestration', 'container_analysis', 'task_generation']
}

EXTRACT_METADATA_INFO = {
    'task_type': 'extract_metadata',
    'description': 'Extract metadata from individual blob files',
    'timeout_seconds': 60,
    'max_retries': 3,
    'required_services': ['BlobRepository'],
    'stage': 2,
    'features': ['parallel_execution', 'metadata_extraction', 'file_processing']
}

SUMMARIZE_CONTAINER_INFO = {
    'task_type': 'summarize_container',
    'description': 'Generate comprehensive statistics and summary for storage container',
    'timeout_seconds': 300,
    'max_retries': 2,
    'required_services': ['BlobRepository'],
    'stage': 1,
    'features': ['container_statistics', 'file_distribution', 'size_analysis']
}

CREATE_FILE_INDEX_INFO = {
    'task_type': 'create_file_index',
    'description': 'Create searchable index of files in container',
    'timeout_seconds': 180,
    'max_retries': 2,
    'required_services': ['BlobRepository'],
    'stage': 1,
    'features': ['file_indexing', 'search_preparation', 'metadata_collection']
}

# ============================================================================
# STAGE 1: ANALYZE AND ORCHESTRATE HANDLER
# ============================================================================

def create_orchestration_handler():
    """
    Factory for analyze_and_orchestrate task handler.
    
    This handler implements the "Analyze & Orchestrate" pattern where
    Stage 1 analyzes the container and determines what Stage 2 tasks
    to create dynamically based on actual content.
    
    Returns:
        Handler function that analyzes container and prepares orchestration data
    """
    def handle_orchestration(params: Dict[str, Any], context: TaskContext) -> Dict[str, Any]:
        """
        Analyze container and prepare for dynamic task generation.
        
        Args:
            params: Task parameters
                - container: Container name to analyze
                - filter: Optional search term filter
                - prefix: Optional path prefix
                - max_files: Maximum files to process (default: 2500)
                - metadata_level: Level of metadata extraction (basic/standard/full)
            context: Task context (not used for Stage 1)
            
        Returns:
            OrchestrationData as dict for controller to create Stage 2 tasks
        """
        try:
            # Extract parameters
            container = params['container']
            filter_term = params.get('filter', None)
            prefix = params.get('prefix', '')
            max_files = params.get('max_files', 2500)
            # Keep metadata_level as string for consistency
            metadata_level = params.get('metadata_level', 'standard')
            
            # Get limits
            limits = ContainerSizeLimits()
            hard_limit = limits.HARD_LIMIT
            
            logger.info(f"Analyzing container '{container}' with prefix='{prefix}', max_files={max_files}")
            
            # Get blob repository
            blob_repo = RepositoryFactory.create_blob_repository()
            
            # List blobs with hard limit + 1 to detect overflow
            blobs = blob_repo.list_blobs(
                container=container,
                prefix=prefix,
                limit=hard_limit + 1
            )
            
            blob_count = len(blobs)
            logger.info(f"Found {blob_count} blobs in container '{container}'")
            
            # Check for overflow
            if blob_count > hard_limit:
                error_msg = (
                    f"Container '{container}' has {blob_count} files (limit: {hard_limit}). "
                    f"This exceeds single-function capacity. "
                    f"Consider: 1) Using a more specific prefix filter, "
                    f"2) Processing a subfolder, or "
                    f"3) Waiting for multi-stage orchestration support."
                )
                logger.error(error_msg)
                raise NotImplementedError(error_msg)
            
            # Apply additional filtering if specified
            filtered_blobs = []

            for blob in blobs[:max_files]:  # Respect max_files limit
                # Apply filter term if specified
                if filter_term and filter_term.lower() not in blob['name'].lower():
                    continue

                # Add to filtered list for processing
                # The repository returns 'name' field which is the full path
                # FileOrchestrationItem expects 'path' field for the full path
                # and 'name' field for just the filename
                filtered_blobs.append({
                    'path': blob['name'],  # Full path from repository
                    'name': blob['name'].split('/')[-1],  # Just filename for display
                    'size': blob.get('size', 0),
                    'last_modified': blob.get('last_modified'),
                    'content_type': blob.get('content_type'),
                    'etag': blob.get('etag'),
                    'metadata': blob.get('metadata', {})
                })

            # Convert to FileOrchestrationItem objects with deterministic IDs
            files_to_process = create_file_orchestration_items(
                files=filtered_blobs,
                container=container
            )
            
            logger.info(f"Selected {len(files_to_process)} files for processing after filtering")
            
            # Calculate estimated duration
            estimated_duration = len(files_to_process) * 0.5  # ~0.5 seconds per file
            
            # Create orchestration data with FileOrchestrationItem objects
            orchestration = OrchestrationData(
                total_files=blob_count,
                files_to_process=len(files_to_process),
                files=files_to_process,  # Now these are FileOrchestrationItem objects
                batch_size=100,  # Could be dynamic based on file sizes
                estimated_duration_seconds=estimated_duration,
                filter_applied=filter_term,
                prefix_applied=prefix if prefix else None,
                overflow_detected=blob_count > max_files,
                overflow_message=f"Showing first {max_files} of {blob_count} files" if blob_count > max_files else None,
                metadata_level=metadata_level  # Pass through for Stage 2 parameters
            )
            
            # Return orchestration data for controller
            return orchestration.to_stage_result()
            
        except Exception as e:
            logger.error(f"Orchestration failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    return handle_orchestration


# ============================================================================
# STAGE 2: EXTRACT METADATA HANDLER
# ============================================================================

def create_metadata_handler():
    """
    Factory for extract_metadata task handler.
    
    Creates a handler for extracting metadata from individual files.
    This is typically used in Stage 2 after orchestration, with one
    task per file for parallel processing.
    
    Returns:
        Handler function that extracts file metadata
    """
    def handle_metadata(params: Dict[str, Any], context: TaskContext) -> Dict[str, Any]:
        """
        Extract metadata for a single file.
        
        Args:
            params: Task parameters
                - container: Container name
                - file_path: Path to the file
                - file_size: Size of the file (from orchestration)
                - metadata_level: Level of extraction (basic/standard/full)
            context: Task context (no predecessor for Stage 2)
            
        Returns:
            BlobMetadata as dict stored in task.result_data
        """
        try:
            # Extract parameters
            container = params['container']
            file_path = params['file_path']
            file_size = params.get('file_size', 0)
            # Keep metadata_level as string and convert to enum for comparison
            metadata_level = params.get('metadata_level', 'standard')
            
            logger.debug(f"Extracting metadata for {container}/{file_path}")
            
            # Get blob repository
            blob_repo = RepositoryFactory.create_blob_repository()
            
            # Get detailed properties based on metadata level
            if metadata_level == 'basic' or metadata_level == MetadataLevel.BASIC.value:
                # Just use what we already have from orchestration
                metadata = BlobMetadata(
                    name=file_path,
                    size=file_size,
                    last_modified=datetime.fromisoformat(params.get('last_modified', datetime.utcnow().isoformat())),
                    extension=parse_blob_extension(file_path),
                    folder_path=parse_folder_path(file_path)
                )
            else:
                # Get full properties from Azure
                props = blob_repo.get_blob_properties(container, file_path)
                
                metadata = BlobMetadata(
                    name=props['name'],
                    size=props['size'],
                    last_modified=datetime.fromisoformat(props['last_modified']),
                    content_type=props.get('content_type'),
                    etag=props.get('etag'),
                    metadata=props.get('metadata', {}),
                    extension=parse_blob_extension(props['name']),
                    folder_path=parse_folder_path(props['name'])
                )
                
                # For FULL level, could add more analysis here
                if metadata_level == 'full' or metadata_level == MetadataLevel.FULL.value:
                    # Could read file headers, extract EXIF, etc.
                    pass
            
            logger.debug(f"Successfully extracted metadata for {file_path}")
            
            # Return metadata for storage in task.result_data
            result = metadata.to_task_result()
            result['success'] = True
            result['extraction_level'] = str(metadata_level)  # Ensure it's a string
            
            return result
            
        except Exception as e:
            logger.error(f"Metadata extraction failed for {params.get('file_path', 'unknown')}: {e}")
            return {
                "success": False,
                "error": str(e),
                "file_path": params.get('file_path', 'unknown'),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    return handle_metadata


# ============================================================================
# SINGLE STAGE: SUMMARIZE CONTAINER HANDLER
# ============================================================================

def create_summary_handler():
    """
    Factory for summarize_container task handler.
    
    Creates a handler for generating container summary statistics.
    This can be a single-stage job for small containers or part
    of a multi-stage workflow for large containers.
    
    Returns:
        Handler function that generates container summary
    """
    def handle_summary(params: Dict[str, Any], context: TaskContext) -> Dict[str, Any]:
        """
        Generate summary statistics for a container.
        
        Args:
            params: Task parameters
                - container: Container name
                - prefix: Optional path prefix filter
                - max_files: Maximum files to analyze (default: 2500)
            context: Task context (could have predecessor for multi-stage)
            
        Returns:
            ContainerSummary as dict with statistics
        """
        try:
            # Extract parameters
            container = params['container']
            prefix = params.get('prefix', '')
            max_files = params.get('max_files', 2500)
            
            logger.info(f"Summarizing container '{container}' with prefix='{prefix}'")
            
            # Get blob repository
            blob_repo = RepositoryFactory.create_blob_repository()
            
            # Check for predecessor data (multi-stage scenario)
            if context.has_predecessor():
                # Could aggregate from previous parallel analysis
                predecessor_data = context.get_predecessor_result()
                logger.debug("Using predecessor data for aggregation")
                # For now, proceed with direct analysis
            
            # List blobs
            blobs = blob_repo.list_blobs(
                container=container,
                prefix=prefix,
                limit=max_files
            )
            
            # Calculate statistics
            total_size = 0
            largest_file = None
            largest_size = 0
            size_distribution = {cat.value: 0 for cat in FileSizeCategory}
            type_distribution = {}
            
            for blob in blobs:
                size = blob['size']
                name = blob['name']
                
                # Track total size
                total_size += size
                
                # Track largest file
                if size > largest_size:
                    largest_size = size
                    largest_file = name
                
                # Categorize by size
                if size < 1024 * 1024:
                    size_distribution[FileSizeCategory.TINY.value] += 1
                elif size < 10 * 1024 * 1024:
                    size_distribution[FileSizeCategory.SMALL.value] += 1
                elif size < 100 * 1024 * 1024:
                    size_distribution[FileSizeCategory.MEDIUM.value] += 1
                elif size < 1024 * 1024 * 1024:
                    size_distribution[FileSizeCategory.LARGE.value] += 1
                else:
                    size_distribution[FileSizeCategory.HUGE.value] += 1
                
                # Track file types
                ext = parse_blob_extension(name)
                type_distribution[ext] = type_distribution.get(ext, 0) + 1
            
            # Create summary
            summary = ContainerSummary(
                container_name=container,
                file_count=len(blobs),
                total_size=total_size,
                largest_file_name=largest_file,
                largest_file_size=largest_size,
                size_distribution=size_distribution,
                type_distribution=type_distribution,
                prefix_filter=prefix if prefix else None
            )
            
            logger.info(f"Container summary complete: {len(blobs)} files, {total_size / (1024*1024):.2f} MB total")
            
            # Return summary
            result = summary.to_human_readable()
            result['success'] = True
            
            return result
            
        except Exception as e:
            logger.error(f"Container summary failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "container": params.get('container', 'unknown'),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    return handle_summary


# ============================================================================
# STAGE 3: CREATE INDEX HANDLER (Optional)
# ============================================================================

def create_index_handler():
    """
    Factory for create_file_index task handler.
    
    Creates an index mapping file names to task IDs after
    Stage 2 metadata extraction is complete.
    
    Returns:
        Handler function that creates file index
    """
    def handle_index(params: Dict[str, Any], context: TaskContext) -> Dict[str, Any]:
        """
        Create index of files to task IDs.
        
        Args:
            params: Task parameters
                - container: Container name
                - job_id: Parent job ID
                - stage_2_task_count: Number of Stage 2 tasks
            context: Task context
            
        Returns:
            Index mapping file paths to task IDs
        """
        try:
            container = params['container']
            job_id = params['job_id']
            task_count = params.get('stage_2_task_count', 0)
            
            logger.info(f"Creating file index for {task_count} files in job {job_id}")
            
            # In a real implementation, would query task repository
            # For now, return a placeholder
            index = {
                "container": container,
                "job_id": job_id,
                "task_count": task_count,
                "index_created": datetime.utcnow().isoformat(),
                "success": True
            }
            
            return index
            
        except Exception as e:
            logger.error(f"Index creation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    return handle_index


# ============================================================================
# TEMPLATE NOTES
# ============================================================================

"""
Key Patterns Demonstrated:

1. Analyze & Orchestrate Pattern:
   - Stage 1 analyzes data and determines work
   - Returns orchestration data for dynamic task creation
   - Controller uses this to create Stage 2 tasks

2. Parallel Processing Pattern:
   - Each file gets its own task in Stage 2
   - Tasks execute independently in parallel
   - Results stored in task.result_data

3. Container Size Limits:
   - Hard limit of 5000 files enforced
   - Clear error messages for overflow
   - Suggestions for handling large containers

4. Metadata Levels:
   - Basic: Just size and name
   - Standard: Include Azure properties
   - Full: Could include content analysis

5. Error Handling:
   - Consistent error format with timestamps
   - Detailed logging for debugging
   - Success flags in all responses
"""