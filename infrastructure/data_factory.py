"""
Azure Data Factory Repository Implementation.

High-level repository for Azure Data Factory pipeline orchestration.
Enables CoreMachine jobs to trigger ADF pipelines for database-to-database
ETL operations with audit logging.

Key Features:
    - Trigger ADF pipelines with parameters
    - Monitor pipeline execution status
    - Wait for pipeline completion with polling
    - Retrieve activity-level execution details
    - Health check for ADF connectivity

Use Cases:
    - Production data promotion
    - Database-to-database copy with audit trail
    - Scheduled/recurring ETL pipelines

Exports:
    AzureDataFactoryRepository: ADF pipeline orchestration repository
    PipelineRunResult: Pipeline execution result dataclass
    ActivityRunResult: Activity execution result dataclass
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import threading
import time
import logging

from .interface_repository import IDataFactoryRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "AzureDataFactoryRepository")


# ============================================================================
# DATA CLASSES - Pipeline execution results
# ============================================================================

@dataclass
class PipelineRunResult:
    """Result of a pipeline execution."""
    run_id: str
    pipeline_name: str
    status: str  # Queued, InProgress, Succeeded, Failed, Canceling, Cancelled
    message: Optional[str] = None
    start_time: Optional[str] = None  # ISO format
    end_time: Optional[str] = None    # ISO format
    duration_ms: Optional[int] = None
    parameters: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'run_id': self.run_id,
            'pipeline_name': self.pipeline_name,
            'status': self.status,
            'message': self.message,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_ms': self.duration_ms,
            'parameters': self.parameters,
            'output': self.output
        }


@dataclass
class ActivityRunResult:
    """Result of an individual activity within a pipeline."""
    activity_name: str
    activity_type: str
    status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_ms: Optional[int] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'activity_name': self.activity_name,
            'activity_type': self.activity_type,
            'status': self.status,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_ms': self.duration_ms,
            'input': self.input_data,
            'output': self.output_data,
            'error': self.error
        }


# ============================================================================
# AZURE DATA FACTORY REPOSITORY
# ============================================================================

class AzureDataFactoryRepository(IDataFactoryRepository):
    """
    Azure Data Factory repository for pipeline orchestration.

    Follows existing repository patterns:
    - Singleton for credential and client reuse
    - DefaultAzureCredential for seamless auth across environments
    - Structured logging for Application Insights
    - Explicit error handling (no silent fallbacks)

    Configuration (via environment variables or AppConfig):
    - ADF_SUBSCRIPTION_ID: Azure subscription ID
    - ADF_RESOURCE_GROUP: Resource group containing ADF (default: rmhazure_rg)
    - ADF_FACTORY_NAME: Data Factory instance name

    Example:
        from infrastructure import RepositoryFactory

        # Get repository singleton
        adf_repo = RepositoryFactory.create_data_factory_repository()

        # Trigger pipeline
        result = adf_repo.trigger_pipeline(
            pipeline_name="CopyStagingToBusinessData",
            parameters={"table_name": "my_table", "job_id": "abc123"}
        )

        # Wait for completion
        final = adf_repo.wait_for_pipeline_completion(result['run_id'])
        print(f"Pipeline {final['status']}: {final['message']}")
    """

    _instance: Optional['AzureDataFactoryRepository'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """Thread-safe singleton creation."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize ADF client with credential management."""
        if hasattr(self, '_initialized') and self._initialized:
            return

        logger.info("🏭 Initializing AzureDataFactoryRepository")

        try:
            from config import get_config
            config = get_config()

            # Get ADF configuration
            self.subscription_id = config.adf_subscription_id
            self.resource_group = config.adf_resource_group
            self.factory_name = config.adf_factory_name

            logger.debug(f"🔍 ADF Configuration:")
            logger.debug(f"  Subscription ID: {'SET' if self.subscription_id else 'NOT SET'}")
            logger.debug(f"  Resource Group: {self.resource_group}")
            logger.debug(f"  Factory Name: {self.factory_name or 'NOT SET'}")

            # Validate required configuration
            if not self.subscription_id:
                raise ValueError(
                    "ADF_SUBSCRIPTION_ID not configured. "
                    "Set this environment variable to use Azure Data Factory."
                )

            if not self.factory_name:
                raise ValueError(
                    "ADF_FACTORY_NAME not configured. "
                    "Set this environment variable to use Azure Data Factory."
                )

            # Import Azure SDK (deferred import for faster startup when ADF not used)
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.datafactory import DataFactoryManagementClient

            # Create credential using DefaultAzureCredential
            # This works with managed identity in Azure, CLI locally
            logger.info("🔐 Creating DefaultAzureCredential for ADF")
            self.credential = DefaultAzureCredential()

            # Create ADF management client
            logger.info(f"🏭 Creating DataFactoryManagementClient for: {self.factory_name}")
            self.client = DataFactoryManagementClient(
                credential=self.credential,
                subscription_id=self.subscription_id
            )

            self._initialized = True
            logger.info(f"✅ AzureDataFactoryRepository initialized: {self.factory_name}")

        except ImportError as e:
            logger.error(
                f"❌ Azure Data Factory SDK not installed: {e}",
                extra={
                    'error_source': 'infrastructure',
                    'error_type': 'ImportError',
                    'missing_package': 'azure-mgmt-datafactory'
                }
            )
            raise RuntimeError(
                "Azure Data Factory SDK not installed. "
                "Run: pip install azure-mgmt-datafactory"
            )

        except Exception as e:
            logger.error(
                f"❌ Failed to initialize AzureDataFactoryRepository: {e}",
                extra={
                    'error_source': 'infrastructure',
                    'error_type': type(e).__name__
                }
            )
            raise RuntimeError(f"ADF repository initialization failed: {e}")

    @classmethod
    def instance(cls) -> 'AzureDataFactoryRepository':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ========================================================================
    # IDataFactoryRepository Implementation
    # ========================================================================

    def trigger_pipeline(
        self,
        pipeline_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        reference_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trigger an ADF pipeline execution.

        Args:
            pipeline_name: Name of the pipeline to execute
            parameters: Pipeline parameters to pass
            reference_name: Optional correlation ID for logging (usually job_id)

        Returns:
            Dict with run_id, pipeline_name, status
        """
        logger.info(
            f"🚀 Triggering ADF pipeline: {pipeline_name}",
            extra={
                'adf_pipeline': pipeline_name,
                'adf_factory': self.factory_name,
                'reference_name': reference_name,
                'parameters': list(parameters.keys()) if parameters else []
            }
        )

        try:
            # Trigger pipeline run
            run_response = self.client.pipelines.create_run(
                resource_group_name=self.resource_group,
                factory_name=self.factory_name,
                pipeline_name=pipeline_name,
                parameters=parameters or {},
                reference_pipeline_run_id=reference_name
            )

            result = PipelineRunResult(
                run_id=run_response.run_id,
                pipeline_name=pipeline_name,
                status="Queued",
                parameters=parameters
            )

            logger.info(
                f"✅ Pipeline triggered successfully: {pipeline_name}",
                extra={
                    'adf_pipeline': pipeline_name,
                    'adf_run_id': run_response.run_id,
                    'reference_name': reference_name
                }
            )

            return result.to_dict()

        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"❌ Failed to trigger pipeline {pipeline_name}: {e}",
                extra={
                    'error_source': 'infrastructure',
                    'adf_pipeline': pipeline_name,
                    'adf_factory': self.factory_name,
                    'error_type': error_type,
                    'reference_name': reference_name
                }
            )

            # Check for specific error types
            error_msg = str(e).lower()
            if 'not found' in error_msg or '404' in error_msg:
                raise ValueError(f"Pipeline '{pipeline_name}' not found in factory '{self.factory_name}'")
            elif 'unauthorized' in error_msg or '401' in error_msg:
                raise RuntimeError(f"Authentication failed for ADF: {e}")
            elif 'forbidden' in error_msg or '403' in error_msg:
                raise RuntimeError(f"Access denied to ADF factory '{self.factory_name}': {e}")
            else:
                raise RuntimeError(f"Failed to trigger pipeline '{pipeline_name}': {e}")

    def get_pipeline_run_status(self, run_id: str) -> Dict[str, Any]:
        """
        Get current status of a pipeline run.

        Args:
            run_id: Pipeline run ID from trigger_pipeline

        Returns:
            Dict with run status details
        """
        logger.debug(f"📊 Getting status for pipeline run: {run_id[:16]}...")

        try:
            run = self.client.pipeline_runs.get(
                resource_group_name=self.resource_group,
                factory_name=self.factory_name,
                run_id=run_id
            )

            # Calculate duration if we have both timestamps
            duration_ms = None
            if run.run_start and run.run_end:
                delta = run.run_end - run.run_start
                duration_ms = int(delta.total_seconds() * 1000)

            result = PipelineRunResult(
                run_id=run_id,
                pipeline_name=run.pipeline_name,
                status=run.status,
                message=run.message,
                start_time=run.run_start.isoformat() if run.run_start else None,
                end_time=run.run_end.isoformat() if run.run_end else None,
                duration_ms=duration_ms
            )

            logger.debug(
                f"📊 Pipeline {run.pipeline_name} status: {run.status}",
                extra={
                    'adf_run_id': run_id,
                    'adf_status': run.status,
                    'duration_ms': duration_ms
                }
            )

            return result.to_dict()

        except Exception as e:
            logger.error(
                f"❌ Failed to get pipeline run status: {e}",
                extra={
                    'error_source': 'infrastructure',
                    'adf_run_id': run_id,
                    'error_type': type(e).__name__
                }
            )
            raise RuntimeError(f"Failed to get pipeline run status: {e}")

    def wait_for_pipeline_completion(
        self,
        run_id: str,
        timeout_seconds: int = 3600,
        poll_interval_seconds: int = 30
    ) -> Dict[str, Any]:
        """
        Block until pipeline completes or times out.

        Args:
            run_id: Pipeline run ID
            timeout_seconds: Maximum wait time (default: 1 hour)
            poll_interval_seconds: Polling frequency (default: 30 seconds)

        Returns:
            Final pipeline run status

        Raises:
            TimeoutError: If pipeline doesn't complete within timeout
        """
        logger.info(
            f"⏳ Waiting for pipeline completion: {run_id[:16]}...",
            extra={
                'adf_run_id': run_id,
                'timeout_seconds': timeout_seconds,
                'poll_interval_seconds': poll_interval_seconds
            }
        )

        terminal_states = {'Succeeded', 'Failed', 'Cancelled'}
        start_time = time.time()

        while True:
            # Get current status
            result = self.get_pipeline_run_status(run_id)

            # Check if terminal state reached
            if result['status'] in terminal_states:
                logger.info(
                    f"🏁 Pipeline completed: {result['pipeline_name']} - {result['status']}",
                    extra={
                        'adf_run_id': run_id,
                        'adf_status': result['status'],
                        'duration_ms': result.get('duration_ms'),
                        'message': result.get('message')
                    }
                )
                return result

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                logger.error(
                    f"⏰ Pipeline timed out after {timeout_seconds}s: {run_id}",
                    extra={
                        'error_source': 'infrastructure',
                        'adf_run_id': run_id,
                        'timeout_seconds': timeout_seconds,
                        'last_status': result['status']
                    }
                )
                raise TimeoutError(
                    f"Pipeline {run_id} timed out after {timeout_seconds}s. "
                    f"Last status: {result['status']}"
                )

            # Log progress
            logger.debug(
                f"⏳ Pipeline {result['pipeline_name']} status: {result['status']}, "
                f"elapsed: {int(elapsed)}s, waiting {poll_interval_seconds}s..."
            )

            # Wait before next poll
            time.sleep(poll_interval_seconds)

    def get_activity_runs(self, run_id: str) -> List[Dict[str, Any]]:
        """
        Get individual activity runs within a pipeline.

        Args:
            run_id: Pipeline run ID

        Returns:
            List of activity run details
        """
        logger.debug(f"📋 Getting activity runs for: {run_id[:16]}...")

        try:
            from datetime import timedelta

            # Get pipeline run to determine time range
            run = self.client.pipeline_runs.get(
                resource_group_name=self.resource_group,
                factory_name=self.factory_name,
                run_id=run_id
            )

            # Query activity runs
            # Need to provide filter parameters
            filter_params = {
                'lastUpdatedAfter': run.run_start or datetime.now(timezone.utc) - timedelta(days=1),
                'lastUpdatedBefore': datetime.now(timezone.utc) + timedelta(hours=1)
            }

            activities = self.client.activity_runs.query_by_pipeline_run(
                resource_group_name=self.resource_group,
                factory_name=self.factory_name,
                run_id=run_id,
                filter_parameters=filter_params
            )

            results = []
            for activity in activities.value:
                # Calculate duration
                duration_ms = None
                if activity.activity_run_start and activity.activity_run_end:
                    delta = activity.activity_run_end - activity.activity_run_start
                    duration_ms = int(delta.total_seconds() * 1000)

                result = ActivityRunResult(
                    activity_name=activity.activity_name,
                    activity_type=activity.activity_type,
                    status=activity.status,
                    start_time=activity.activity_run_start.isoformat() if activity.activity_run_start else None,
                    end_time=activity.activity_run_end.isoformat() if activity.activity_run_end else None,
                    duration_ms=duration_ms,
                    input_data=activity.input if hasattr(activity, 'input') else None,
                    output_data=activity.output if hasattr(activity, 'output') else None,
                    error=activity.error.get('message') if activity.error else None
                )
                results.append(result.to_dict())

            logger.debug(
                f"📋 Found {len(results)} activity runs for pipeline: {run_id[:16]}...",
                extra={'adf_run_id': run_id, 'activity_count': len(results)}
            )

            return results

        except Exception as e:
            logger.error(
                f"❌ Failed to get activity runs: {e}",
                extra={
                    'error_source': 'infrastructure',
                    'adf_run_id': run_id,
                    'error_type': type(e).__name__
                }
            )
            raise RuntimeError(f"Failed to get activity runs: {e}")

    def list_pipelines(self) -> List[Dict[str, Any]]:
        """
        List all pipelines in the Data Factory.

        Returns:
            List of pipeline info dictionaries
        """
        logger.debug(f"📋 Listing pipelines in factory: {self.factory_name}")

        try:
            pipelines = self.client.pipelines.list_by_factory(
                resource_group_name=self.resource_group,
                factory_name=self.factory_name
            )

            results = []
            for pipeline in pipelines:
                results.append({
                    'name': pipeline.name,
                    'description': pipeline.description,
                    'parameters': {
                        name: {
                            'type': param.type,
                            'default_value': param.default_value
                        }
                        for name, param in (pipeline.parameters or {}).items()
                    } if pipeline.parameters else {}
                })

            logger.info(
                f"📋 Found {len(results)} pipelines in factory: {self.factory_name}",
                extra={'adf_factory': self.factory_name, 'pipeline_count': len(results)}
            )

            return results

        except Exception as e:
            logger.error(
                f"❌ Failed to list pipelines: {e}",
                extra={
                    'error_source': 'infrastructure',
                    'adf_factory': self.factory_name,
                    'error_type': type(e).__name__
                }
            )
            raise RuntimeError(f"Failed to list pipelines: {e}")

    def health_check(self) -> Dict[str, Any]:
        """
        Check ADF connectivity and configuration.

        Returns:
            Dict with health status
        """
        logger.debug(f"🏥 Performing ADF health check for: {self.factory_name}")

        try:
            # Try to list pipelines as a connectivity test
            pipelines = list(self.client.pipelines.list_by_factory(
                resource_group_name=self.resource_group,
                factory_name=self.factory_name
            ))

            result = {
                'status': 'healthy',
                'factory_name': self.factory_name,
                'subscription_id': self.subscription_id[:8] + '...' if self.subscription_id else None,
                'resource_group': self.resource_group,
                'pipeline_count': len(pipelines),
                'pipelines': [p.name for p in pipelines[:10]]  # First 10 only
            }

            logger.info(
                f"✅ ADF health check passed: {self.factory_name}",
                extra={
                    'adf_factory': self.factory_name,
                    'pipeline_count': len(pipelines)
                }
            )

            return result

        except Exception as e:
            result = {
                'status': 'unhealthy',
                'factory_name': self.factory_name,
                'subscription_id': self.subscription_id[:8] + '...' if self.subscription_id else None,
                'resource_group': self.resource_group,
                'error': str(e),
                'error_type': type(e).__name__
            }

            logger.warning(
                f"⚠️ ADF health check failed: {e}",
                extra={
                    'adf_factory': self.factory_name,
                    'error_type': type(e).__name__
                }
            )

            return result


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def get_data_factory_repository() -> AzureDataFactoryRepository:
    """
    Get AzureDataFactoryRepository singleton instance.

    This is the primary entry point for getting the ADF repository.
    Use RepositoryFactory.create_data_factory_repository() for consistency
    with other repositories.

    Returns:
        AzureDataFactoryRepository singleton instance
    """
    return AzureDataFactoryRepository.instance()
