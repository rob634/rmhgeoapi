# ============================================================================
# CLAUDE CONTEXT - ARTIFACT SERVICE
# ============================================================================
# STATUS: Service - Artifact registry business logic
# PURPOSE: Manage artifact lifecycle with supersession tracking
# CREATED: 20 JAN 2026
# LAST_REVIEWED: 21 JAN 2026
# ============================================================================
"""
Artifact Service - Internal Asset Tracking Business Logic.

Provides business logic for artifact registry operations:
- Artifact creation with automatic revision tracking
- Client reference lookups (any client schema)
- Supersession management for overwrites
- Lineage queries (history, chain traversal)

Design Decisions (20 JAN 2026):
    - STAC Item Handling: Delete old, create new with same ID
    - COG Blob Handling: Overwrite blob in place
    - Revision Numbering: Global monotonic (never resets)
    - Content Hash: Hash output COG after creation
    - Cleanup Timing: Synchronous
    - API Response: artifact_id is INTERNAL ONLY

Usage:
    from services.artifact_service import ArtifactService

    service = ArtifactService()

    # Create new artifact
    artifact = service.create_artifact(
        storage_account="rmhstorage123",
        container="silver-cogs",
        blob_path="flood-2024/site-a.tif",
        client_type="ddh",
        client_refs={"dataset_id": "flood-2024", "resource_id": "site-a", "version_id": "v1.0"},
        stac_collection_id="flood-2024",
        stac_item_id="site-a-v1.0",
        source_job_id="abc123...",
        overwrite=False
    )

    # Lookup by client refs
    artifact = service.get_by_client_refs("ddh", {"dataset_id": "flood-2024", ...})

    # Get full history
    history = service.get_history("ddh", {"dataset_id": "flood-2024", ...})

Exports:
    ArtifactService: Artifact business logic service
    ArtifactExistsError: Raised when artifact exists and overwrite=False
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4

from infrastructure.artifact_repository import ArtifactRepository
from core.models.artifact import Artifact, ArtifactStatus

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "artifact")


class ArtifactExistsError(Exception):
    """Raised when artifact already exists and overwrite=False."""

    def __init__(self, artifact_id: UUID, client_type: str, client_refs: Dict[str, Any]):
        self.artifact_id = artifact_id
        self.client_type = client_type
        self.client_refs = client_refs
        super().__init__(
            f"Artifact already exists for {client_type}:{client_refs}. "
            f"Use overwrite=True to replace. Existing artifact_id: {artifact_id}"
        )


class ArtifactService:
    """
    Service for managing the artifact registry.

    Provides:
    - Artifact creation with automatic revision tracking
    - Client reference lookups (any client schema)
    - Supersession management for overwrites
    - Lineage queries (history, chain traversal)
    """

    def __init__(self):
        """Initialize with repository dependency."""
        self._repo = ArtifactRepository()

    # =========================================================================
    # CREATION
    # =========================================================================

    def create_artifact(
        self,
        storage_account: str,
        container: str,
        blob_path: str,
        client_type: str,
        client_refs: Dict[str, Any],
        stac_collection_id: Optional[str] = None,
        stac_item_id: Optional[str] = None,
        source_job_id: Optional[str] = None,
        source_task_id: Optional[str] = None,
        content_hash: Optional[str] = None,
        size_bytes: Optional[int] = None,
        content_type: Optional[str] = None,
        blob_version_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        overwrite: bool = False
    ) -> Artifact:
        """
        Create a new artifact record.

        If overwrite=True and existing artifact found:
        - Mark old artifact as superseded
        - Create new artifact with supersedes link
        - Increment revision number

        Args:
            storage_account: Azure storage account name
            container: Blob container name
            blob_path: Path within container
            client_type: Client identifier (e.g., 'ddh', 'data360')
            client_refs: Client-specific reference IDs as dict
            stac_collection_id: STAC collection ID (if cataloged)
            stac_item_id: STAC item ID (if cataloged)
            source_job_id: CoreMachine job that created this
            source_task_id: CoreMachine task that created this
            content_hash: SHA256 of file content
            size_bytes: File size
            content_type: MIME type
            blob_version_id: Azure Blob Storage version ID (if versioning enabled)
            metadata: Additional metadata
            overwrite: If True, supersede existing artifact

        Returns:
            Created artifact with artifact_id

        Raises:
            ArtifactExistsError: If artifact exists and overwrite=False
        """
        logger.info(f"Creating artifact for {client_type}:{client_refs} (overwrite={overwrite})")

        # Check for existing artifact
        existing = self._repo.get_active_by_client_refs(client_type, client_refs)

        if existing and not overwrite:
            logger.warning(f"Artifact already exists: {existing.artifact_id}")
            raise ArtifactExistsError(existing.artifact_id, client_type, client_refs)

        # Compute revision number (global monotonic - never resets)
        max_revision = self._repo.get_max_revision(client_type, client_refs)
        new_revision = max_revision + 1

        # Create new artifact
        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id=uuid4(),
            content_hash=content_hash,
            storage_account=storage_account,
            container=container,
            blob_path=blob_path,
            size_bytes=size_bytes,
            content_type=content_type,
            blob_version_id=blob_version_id,
            stac_collection_id=stac_collection_id,
            stac_item_id=stac_item_id,
            client_type=client_type,
            client_refs=client_refs,
            source_job_id=source_job_id,
            source_task_id=source_task_id,
            supersedes=existing.artifact_id if existing else None,
            superseded_by=None,
            revision=new_revision,
            status=ArtifactStatus.ACTIVE,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
            deleted_at=None
        )

        # Persist new artifact
        created = self._repo.create(artifact)
        logger.info(f"Created artifact {created.artifact_id} (revision {new_revision})")

        # If overwriting, mark old artifact as superseded
        if existing:
            self._repo.update_status(
                existing.artifact_id,
                ArtifactStatus.SUPERSEDED,
                superseded_by=created.artifact_id
            )
            logger.info(f"Marked artifact {existing.artifact_id} as superseded by {created.artifact_id}")

        return created

    # =========================================================================
    # LOOKUP
    # =========================================================================

    def get_by_id(self, artifact_id: UUID) -> Optional[Artifact]:
        """
        Get artifact by internal UUID.

        Args:
            artifact_id: Internal artifact identifier

        Returns:
            Artifact if found, None otherwise
        """
        return self._repo.get_by_id(artifact_id)

    def get_by_client_refs(
        self,
        client_type: str,
        client_refs: Dict[str, Any],
        include_superseded: bool = False
    ) -> Optional[Artifact]:
        """
        Get artifact by client reference.

        Args:
            client_type: Client identifier
            client_refs: Client-specific reference dict
            include_superseded: If True, return even if superseded

        Returns:
            Active artifact, or None if not found
        """
        if include_superseded:
            # Return most recent regardless of status
            all_artifacts = self._repo.get_all_by_client_refs(client_type, client_refs)
            return all_artifacts[0] if all_artifacts else None
        else:
            return self._repo.get_active_by_client_refs(client_type, client_refs)

    def get_by_stac(
        self,
        collection_id: str,
        item_id: str
    ) -> Optional[Artifact]:
        """
        Reverse lookup: Get artifact that created this STAC item.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID

        Returns:
            Artifact if found, None otherwise
        """
        return self._repo.get_by_stac(collection_id, item_id)

    def get_by_job(self, job_id: str) -> List[Artifact]:
        """
        Get all artifacts created by a job.

        Args:
            job_id: CoreMachine job ID

        Returns:
            List of artifacts created by this job
        """
        return self._repo.get_by_job(job_id)

    # =========================================================================
    # LINEAGE / HISTORY
    # =========================================================================

    def get_history(
        self,
        client_type: str,
        client_refs: Dict[str, Any]
    ) -> List[Artifact]:
        """
        Get full history of artifacts for client refs.

        Returns all revisions (active + superseded) ordered by revision desc.

        Args:
            client_type: Client identifier
            client_refs: Client-specific reference dict

        Returns:
            List of artifacts ordered by revision descending
        """
        return self._repo.get_all_by_client_refs(client_type, client_refs)

    def get_supersession_chain(
        self,
        artifact_id: UUID,
        direction: str = "both"
    ) -> List[Artifact]:
        """
        Traverse supersession chain from an artifact.

        Args:
            artifact_id: Starting artifact
            direction:
                - "forward": What replaced this? (follow superseded_by)
                - "backward": What did this replace? (follow supersedes)
                - "both": Full chain

        Returns:
            List of artifacts in the chain
        """
        chain = []
        artifact = self._repo.get_by_id(artifact_id)

        if not artifact:
            return chain

        # Backward traversal (what did this replace?)
        if direction in ("backward", "both"):
            current = artifact
            while current.supersedes:
                prev = self._repo.get_by_id(current.supersedes)
                if prev:
                    chain.insert(0, prev)
                    current = prev
                else:
                    break

        # Add the starting artifact
        chain.append(artifact)

        # Forward traversal (what replaced this?)
        if direction in ("forward", "both"):
            current = artifact
            while current.superseded_by:
                next_artifact = self._repo.get_by_id(current.superseded_by)
                if next_artifact:
                    chain.append(next_artifact)
                    current = next_artifact
                else:
                    break

        return chain

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def mark_deleted(
        self,
        artifact_id: UUID,
        hard_delete: bool = False
    ) -> bool:
        """
        Delete an artifact.

        Args:
            artifact_id: Artifact to delete
            hard_delete: If True, remove from DB. If False, soft delete.

        Returns:
            True if artifact was deleted, False if not found
        """
        if hard_delete:
            # Hard delete not implemented - would need separate method
            logger.warning("Hard delete not implemented, using soft delete")

        return self._repo.update_status(artifact_id, ArtifactStatus.DELETED)

    def mark_archived(self, artifact_id: UUID) -> bool:
        """
        Mark artifact as archived (moved to archive storage).

        Args:
            artifact_id: Artifact to archive

        Returns:
            True if artifact was archived, False if not found
        """
        return self._repo.update_status(artifact_id, ArtifactStatus.ARCHIVED)

    # =========================================================================
    # DUPLICATE DETECTION
    # =========================================================================

    def find_duplicates(self, content_hash: str) -> List[Artifact]:
        """
        Find artifacts with same content hash (potential duplicates).

        Useful for detecting "no actual change" overwrites.

        Args:
            content_hash: SHA256 of file content

        Returns:
            List of artifacts with matching content hash
        """
        return self._repo.find_by_content_hash(content_hash)

    def check_duplicate_content(
        self,
        client_type: str,
        client_refs: Dict[str, Any],
        content_hash: str
    ) -> Optional[Artifact]:
        """
        Check if an overwrite would have identical content.

        If content hash matches existing active artifact, returns it
        to allow short-circuiting redundant processing.

        Args:
            client_type: Client identifier
            client_refs: Client-specific reference dict
            content_hash: SHA256 of new content

        Returns:
            Existing artifact if content matches, None otherwise
        """
        existing = self._repo.get_active_by_client_refs(client_type, client_refs)
        if existing and existing.content_hash == content_hash:
            logger.info(f"Content unchanged for {client_type}:{client_refs} (hash match)")
            return existing
        return None

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_stats(self, client_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get artifact statistics.

        Args:
            client_type: Optional filter by client type

        Returns:
            Statistics dictionary with counts and totals
        """
        return self._repo.get_stats(client_type)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ArtifactService',
    'ArtifactExistsError',
]
