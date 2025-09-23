# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: One-time STAC database setup controller for PgSTAC installation
# EXPORTS: STACSetupController - Manages PgSTAC schema installation workflow
# INTERFACES: BaseController - Implements abstract controller methods
# PYDANTIC_MODELS: WorkflowDefinition, StageDefinition, TaskDefinition
# DEPENDENCIES: pypgstac for database migrations
# SOURCE: Triggered via HTTP endpoint for one-time setup
# SCOPE: Database schema creation - run once per environment
# VALIDATION: Verifies PgSTAC installation success
# PATTERNS: Controller pattern for job orchestration
# ENTRY_POINTS: JobFactory.create_controller("stac_setup")
# INDEX:
#   - Line 20: Class definition
#   - Line 35: Workflow definition
#   - Line 55: Parameter validation
#   - Line 70: Task creation logic
#   - Line 120: Result aggregation
# ============================================================================

from typing import Dict, List, Any, Optional
from datetime import datetime
import hashlib
import json

from controller_base import BaseController
from schema_base import WorkflowDefinition, StageDefinition, TaskDefinition, TaskResult
from util_logger import LoggerFactory, ComponentType
from repositories import RepositoryFactory

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, __name__)


class STACSetupController(BaseController):
    """
    One-time STAC database setup controller.

    Manages the installation and configuration of PgSTAC in PostgreSQL.
    This should be run once per environment to set up the STAC infrastructure.

    Stages:
    1. Install PgSTAC schema and functions
    2. Configure roles and permissions
    3. Verify installation and create initial collection
    """

    # Workflow definition with 3 stages
    workflow = WorkflowDefinition(
        job_type="stac_setup",
        description="Install and configure PgSTAC database for STAC catalog operations",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="install_pgstac",
                task_type="install_pgstac",
                description="Install PgSTAC schema, tables, and functions",
                max_parallel_tasks=1,  # Must be sequential
                timeout_seconds=300
            ),
            StageDefinition(
                stage_number=2,
                stage_name="configure_roles",
                task_type="configure_pgstac_roles",
                description="Set up database roles and permissions",
                max_parallel_tasks=1,
                timeout_seconds=60
            ),
            StageDefinition(
                stage_number=3,
                stage_name="verify_installation",
                task_type="verify_pgstac_installation",
                description="Verify installation and create Bronze collection",
                max_parallel_tasks=1,
                timeout_seconds=60
            )
        ],
        total_stages=3
    )

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate STAC setup parameters.

        Args:
            parameters: Raw job parameters

        Returns:
            Validated parameters with defaults
        """
        # Add defaults
        validated = {
            "pgstac_version": parameters.get("pgstac_version", "0.8.5"),
            "create_bronze_collection": parameters.get("create_bronze_collection", True),
            "bronze_collection_id": parameters.get("bronze_collection_id", "rmhazure-bronze"),
            "bronze_collection_title": parameters.get("bronze_collection_title", "RMH Azure Bronze Tier"),
            "bronze_collection_description": parameters.get("bronze_collection_description",
                "Raw geospatial data ingested into Azure Storage Bronze tier"),
            "drop_existing": parameters.get("drop_existing", False),  # Safety flag
            "run_migrations": parameters.get("run_migrations", True)
        }

        # Validate version format
        version = validated["pgstac_version"]
        if not version or not isinstance(version, str):
            raise ValueError("pgstac_version must be a valid version string")

        # Safety check for production
        if validated["drop_existing"]:
            logger.warning("⚠️ drop_existing=True - This will DELETE all existing STAC data!")

        return validated

    def create_stage_tasks(self,
                          stage_number: int,
                          job_id: str,
                          job_parameters: Dict[str, Any],
                          stage_parameters: Optional[Dict[str, Any]] = None) -> List[TaskDefinition]:
        """
        Create tasks for each stage of STAC setup.

        Args:
            stage_number: Current stage (1-3)
            job_id: Unique job identifier
            job_parameters: Validated job parameters
            stage_parameters: Parameters from previous stage

        Returns:
            List of tasks for the stage
        """
        tasks = []

        if stage_number == 1:
            # Stage 1: Install PgSTAC
            task_id = self.generate_task_id(job_id, stage_number, "install-pgstac")
            tasks.append(TaskDefinition(
                task_id=task_id,
                parent_job_id=job_id,
                job_type="stac_setup",
                task_type="install_pgstac",
                stage=stage_number,
                task_index="0",
                parameters={
                    "pgstac_version": job_parameters["pgstac_version"],
                    "drop_existing": job_parameters["drop_existing"],
                    "run_migrations": job_parameters["run_migrations"]
                },
                metadata={
                    "description": "Install PgSTAC schema and functions",
                    "critical": True
                }
            ))

        elif stage_number == 2:
            # Stage 2: Configure roles
            task_id = self.generate_task_id(job_id, stage_number, "configure-roles")
            tasks.append(TaskDefinition(
                task_id=task_id,
                parent_job_id=job_id,
                job_type="stac_setup",
                task_type="configure_pgstac_roles",
                stage=stage_number,
                task_index="0",
                parameters={
                    "roles": ["pgstac_admin", "pgstac_ingest", "pgstac_read"],
                    "app_user": "rob634"  # From config in production
                },
                metadata={
                    "description": "Configure database roles and permissions"
                }
            ))

        elif stage_number == 3:
            # Stage 3: Verify and create initial collection
            task_id = self.generate_task_id(job_id, stage_number, "verify-install")

            # Check if we should create Bronze collection
            create_collection = job_parameters.get("create_bronze_collection", True)

            tasks.append(TaskDefinition(
                task_id=task_id,
                parent_job_id=job_id,
                job_type="stac_setup",
                task_type="verify_pgstac_installation",
                stage=stage_number,
                task_index="0",
                parameters={
                    "create_collection": create_collection,
                    "collection_id": job_parameters["bronze_collection_id"],
                    "collection_title": job_parameters["bronze_collection_title"],
                    "collection_description": job_parameters["bronze_collection_description"],
                    "test_queries": [
                        "SELECT pgstac.get_version()",
                        "SELECT count(*) FROM pgstac.collections",
                        "SELECT pgstac.search('{}') LIMIT 1"
                    ]
                },
                metadata={
                    "description": "Verify PgSTAC installation and create initial collection"
                }
            ))

        return tasks

    def aggregate_stage_results(self,
                               stage_number: int,
                               task_results: List[TaskResult]) -> Dict[str, Any]:
        """
        Aggregate results from completed stage tasks.

        Args:
            stage_number: Completed stage number
            task_results: Results from all tasks in the stage

        Returns:
            Aggregated results to pass to next stage
        """
        if not task_results:
            return {"status": "no_results"}

        # Since each stage has only one task, get the first result
        result = task_results[0]

        if stage_number == 1:
            # Installation results
            return {
                "installation_success": result.success,
                "pgstac_version": result.result_data.get("version_installed"),
                "migration_count": result.result_data.get("migrations_applied", 0),
                "tables_created": result.result_data.get("tables_created", []),
                "functions_created": result.result_data.get("functions_created", [])
            }

        elif stage_number == 2:
            # Role configuration results
            return {
                "roles_configured": result.success,
                "roles_created": result.result_data.get("roles_created", []),
                "permissions_granted": result.result_data.get("permissions_granted", [])
            }

        elif stage_number == 3:
            # Verification results
            return {
                "verification_success": result.success,
                "pgstac_version": result.result_data.get("pgstac_version"),
                "collection_count": result.result_data.get("collection_count", 0),
                "bronze_collection_created": result.result_data.get("collection_created", False),
                "test_results": result.result_data.get("test_results", {})
            }

        return {"stage": stage_number, "success": all(r.success for r in task_results)}

    def should_advance_stage(self,
                           current_stage: int,
                           stage_results: Dict[str, Any]) -> bool:
        """
        Determine if workflow should advance to next stage.

        Args:
            current_stage: Current stage number
            stage_results: Results from current stage

        Returns:
            True if should advance, False to stop
        """
        # For STAC setup, only advance if current stage was successful
        if current_stage == 1:
            # Must successfully install PgSTAC to continue
            return stage_results.get("installation_success", False)
        elif current_stage == 2:
            # Must configure roles to continue
            return stage_results.get("roles_configured", False)
        elif current_stage == 3:
            # Final stage - no advancement needed
            return False

        return True

    def generate_final_result(self, job_id: str, all_stage_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate final job result after all stages complete.

        Args:
            job_id: Job identifier
            all_stage_results: Results from all stages

        Returns:
            Final job result summary
        """
        # Extract results from each stage
        stage1 = all_stage_results.get("1", {})
        stage2 = all_stage_results.get("2", {})
        stage3 = all_stage_results.get("3", {})

        # Determine overall success
        success = (
            stage1.get("installation_success", False) and
            stage2.get("roles_configured", False) and
            stage3.get("verification_success", False)
        )

        return {
            "job_id": job_id,
            "job_type": "stac_setup",
            "success": success,
            "pgstac_version": stage3.get("pgstac_version", "unknown"),
            "installation_summary": {
                "tables_created": stage1.get("tables_created", []),
                "functions_created": stage1.get("functions_created", []),
                "migrations_applied": stage1.get("migration_count", 0)
            },
            "roles_summary": {
                "roles_created": stage2.get("roles_created", []),
                "permissions_granted": stage2.get("permissions_granted", [])
            },
            "verification_summary": {
                "collection_count": stage3.get("collection_count", 0),
                "bronze_collection_created": stage3.get("bronze_collection_created", False),
                "test_results": stage3.get("test_results", {})
            },
            "message": "✅ PgSTAC installation complete!" if success else "❌ PgSTAC installation failed",
            "timestamp": datetime.utcnow().isoformat()
        }


# Register with JobRegistry using decorator
from schema_base import JobRegistry

@JobRegistry.instance().register(
    job_type="stac_setup",
    workflow=STACSetupController.workflow,
    description="One-time PgSTAC database installation and configuration",
    max_parallel_tasks=1,
    timeout_minutes=10
)
class _RegisteredSTACSetupController(STACSetupController):
    """Registration wrapper for STACSetupController"""
    pass