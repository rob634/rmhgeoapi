# ============================================================================
# CLAUDE CONTEXT - ARTIFACT REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Artifact registry CRUD operations
# PURPOSE: Database operations for app.artifacts table
# CREATED: 20 JAN 2026
# LAST_REVIEWED: 21 JAN 2026
# ============================================================================
"""
Artifact Repository - Internal Asset Tracking.

Provides CRUD operations for the artifact registry table.
Supports client-agnostic tracking with supersession lineage.

Architecture:
    - Single table (app.artifacts)
    - UUID primary key (artifact_id) - internal, never derived from client params
    - JSONB client_refs for flexible client schema support
    - Supersession tracking for overwrite lineage

Methods:
    create(artifact) - Insert new artifact record
    get_by_id(artifact_id) - Lookup by internal UUID
    get_active_by_client_refs(client_type, client_refs) - Find active artifact
    get_all_by_client_refs(client_type, client_refs) - Full history
    get_max_revision(client_type, client_refs) - For computing next revision
    get_by_stac(collection_id, item_id) - Reverse lookup from STAC
    get_by_job(job_id) - Find artifacts created by job
    update_status(artifact_id, status, superseded_by) - Update lifecycle state
    find_by_content_hash(content_hash) - Duplicate detection

Exports:
    ArtifactRepository: Artifact CRUD repository
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from uuid import UUID
from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository
from core.models.artifact import Artifact, ArtifactStatus

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "artifact")


class ArtifactRepository(PostgreSQLRepository):
    """
    Repository for artifact registry CRUD operations.

    Uses app.artifacts table for internal asset tracking.
    All queries use psycopg.sql composition for safety.

    Table: app.artifacts
        artifact_id UUID PRIMARY KEY  -- Internal identifier
        content_hash VARCHAR(64)      -- SHA256 of output file
        storage_account VARCHAR(64) NOT NULL
        container VARCHAR(64) NOT NULL
        blob_path TEXT NOT NULL
        client_type VARCHAR(50) NOT NULL
        client_refs JSONB NOT NULL    -- Flexible client parameter storage
        supersedes UUID               -- Previous artifact this replaced
        superseded_by UUID            -- Artifact that replaced this
        revision INTEGER NOT NULL     -- Monotonic counter per client_refs
        status artifact_status NOT NULL
        ...
    """

    def __init__(self):
        super().__init__()
        # Schema deployed centrally via POST /api/dbadmin/maintenance?action=ensure&confirm=yes

    def create(self, artifact: Artifact) -> Artifact:
        """
        Insert new artifact record.

        Args:
            artifact: Artifact model with all required fields

        Returns:
            Artifact with database-assigned values
        """
        with self._error_context("artifact creation", str(artifact.artifact_id)):
            query = sql.SQL("""
                INSERT INTO {}.artifacts (
                    artifact_id, content_hash, storage_account, container, blob_path,
                    size_bytes, content_type, blob_version_id, stac_collection_id, stac_item_id,
                    client_type, client_refs, source_job_id, source_task_id,
                    supersedes, superseded_by, revision, status, metadata,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
            """).format(sql.Identifier(self.schema_name))

            params = (
                str(artifact.artifact_id),
                artifact.content_hash,
                artifact.storage_account,
                artifact.container,
                artifact.blob_path,
                artifact.size_bytes,
                artifact.content_type,
                artifact.blob_version_id,
                artifact.stac_collection_id,
                artifact.stac_item_id,
                artifact.client_type,
                json.dumps(artifact.client_refs),
                artifact.source_job_id,
                artifact.source_task_id,
                str(artifact.supersedes) if artifact.supersedes else None,
                str(artifact.superseded_by) if artifact.superseded_by else None,
                artifact.revision,
                artifact.status.value if isinstance(artifact.status, ArtifactStatus) else artifact.status,
                json.dumps(artifact.metadata),
                artifact.created_at or datetime.now(timezone.utc),
                artifact.updated_at or datetime.now(timezone.utc),
                artifact.deleted_at,
            )

            row = self._execute_query(query, params, fetch='one')
            return self._row_to_artifact(row)

    def get_by_id(self, artifact_id: UUID) -> Optional[Artifact]:
        """
        Get artifact by internal UUID.

        Args:
            artifact_id: Internal artifact identifier

        Returns:
            Artifact if found, None otherwise
        """
        with self._error_context("artifact lookup by id", str(artifact_id)):
            query = sql.SQL("""
                SELECT * FROM {}.artifacts WHERE artifact_id = %s
            """).format(sql.Identifier(self.schema_name))

            row = self._execute_query(query, (str(artifact_id),), fetch='one')
            return self._row_to_artifact(row) if row else None

    def get_active_by_client_refs(
        self,
        client_type: str,
        client_refs: Dict[str, Any]
    ) -> Optional[Artifact]:
        """
        Get active artifact by client references using JSONB containment.

        Args:
            client_type: Client identifier (e.g., 'ddh', 'data360')
            client_refs: Client-specific reference dict

        Returns:
            Active artifact if found, None otherwise
        """
        with self._error_context("artifact lookup by client refs", f"{client_type}:{client_refs}"):
            query = sql.SQL("""
                SELECT * FROM {}.artifacts
                WHERE client_type = %s
                  AND client_refs @> %s::jsonb
                  AND status = 'active'
                LIMIT 1
            """).format(sql.Identifier(self.schema_name))

            row = self._execute_query(
                query,
                (client_type, json.dumps(client_refs)),
                fetch='one'
            )
            return self._row_to_artifact(row) if row else None

    def get_all_by_client_refs(
        self,
        client_type: str,
        client_refs: Dict[str, Any]
    ) -> List[Artifact]:
        """
        Get all artifacts (any status) by client references.

        Returns full history including superseded artifacts.

        Args:
            client_type: Client identifier
            client_refs: Client-specific reference dict

        Returns:
            List of artifacts ordered by revision descending
        """
        with self._error_context("artifact history lookup", f"{client_type}:{client_refs}"):
            query = sql.SQL("""
                SELECT * FROM {}.artifacts
                WHERE client_type = %s
                  AND client_refs @> %s::jsonb
                ORDER BY revision DESC
            """).format(sql.Identifier(self.schema_name))

            rows = self._execute_query(
                query,
                (client_type, json.dumps(client_refs)),
                fetch='all'
            )
            return [self._row_to_artifact(row) for row in rows]

    def get_max_revision(
        self,
        client_type: str,
        client_refs: Dict[str, Any]
    ) -> int:
        """
        Get highest revision number for client refs.

        Used to compute next revision number for overwrites.

        Args:
            client_type: Client identifier
            client_refs: Client-specific reference dict

        Returns:
            Maximum revision number, or 0 if no artifacts exist
        """
        with self._error_context("max revision lookup", f"{client_type}:{client_refs}"):
            query = sql.SQL("""
                SELECT COALESCE(MAX(revision), 0) as max_rev
                FROM {}.artifacts
                WHERE client_type = %s
                  AND client_refs @> %s::jsonb
            """).format(sql.Identifier(self.schema_name))

            row = self._execute_query(
                query,
                (client_type, json.dumps(client_refs)),
                fetch='one'
            )
            return row['max_rev'] if row else 0

    def get_by_stac(
        self,
        collection_id: str,
        item_id: str
    ) -> Optional[Artifact]:
        """
        Reverse lookup: Get artifact that created a STAC item.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID

        Returns:
            Artifact if found, None otherwise
        """
        with self._error_context("artifact lookup by STAC", f"{collection_id}/{item_id}"):
            query = sql.SQL("""
                SELECT * FROM {}.artifacts
                WHERE stac_collection_id = %s
                  AND stac_item_id = %s
                ORDER BY revision DESC
                LIMIT 1
            """).format(sql.Identifier(self.schema_name))

            row = self._execute_query(query, (collection_id, item_id), fetch='one')
            return self._row_to_artifact(row) if row else None

    def get_by_job(self, job_id: str) -> List[Artifact]:
        """
        Get all artifacts created by a job.

        Args:
            job_id: CoreMachine job ID

        Returns:
            List of artifacts created by this job
        """
        with self._error_context("artifact lookup by job", job_id):
            query = sql.SQL("""
                SELECT * FROM {}.artifacts
                WHERE source_job_id = %s
                ORDER BY created_at
            """).format(sql.Identifier(self.schema_name))

            rows = self._execute_query(query, (job_id,), fetch='all')
            return [self._row_to_artifact(row) for row in rows]

    def update_status(
        self,
        artifact_id: UUID,
        status: ArtifactStatus,
        superseded_by: Optional[UUID] = None
    ) -> bool:
        """
        Update artifact status and optional superseded_by link.

        Args:
            artifact_id: Artifact to update
            status: New status
            superseded_by: Optional UUID of artifact that replaced this one

        Returns:
            True if artifact was updated, False if not found
        """
        with self._error_context("artifact status update", str(artifact_id)):
            if superseded_by:
                query = sql.SQL("""
                    UPDATE {}.artifacts
                    SET status = %s, superseded_by = %s, updated_at = NOW()
                    WHERE artifact_id = %s
                    RETURNING artifact_id
                """).format(sql.Identifier(self.schema_name))
                params = (
                    status.value if isinstance(status, ArtifactStatus) else status,
                    str(superseded_by),
                    str(artifact_id)
                )
            else:
                query = sql.SQL("""
                    UPDATE {}.artifacts
                    SET status = %s, updated_at = NOW()
                    WHERE artifact_id = %s
                    RETURNING artifact_id
                """).format(sql.Identifier(self.schema_name))
                params = (
                    status.value if isinstance(status, ArtifactStatus) else status,
                    str(artifact_id)
                )

            row = self._execute_query(query, params, fetch='one')
            return row is not None

    def find_by_content_hash(self, content_hash: str) -> List[Artifact]:
        """
        Find artifacts with same content hash (potential duplicates).

        Args:
            content_hash: SHA256 hash of file content

        Returns:
            List of artifacts with matching content hash
        """
        with self._error_context("artifact content hash lookup", content_hash[:16]):
            query = sql.SQL("""
                SELECT * FROM {}.artifacts
                WHERE content_hash = %s
                ORDER BY created_at DESC
            """).format(sql.Identifier(self.schema_name))

            rows = self._execute_query(query, (content_hash,), fetch='all')
            return [self._row_to_artifact(row) for row in rows]

    def get_stats(self, client_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get artifact statistics.

        Args:
            client_type: Optional filter by client type

        Returns:
            Statistics dictionary with counts and totals
        """
        with self._error_context("artifact stats", client_type or "all"):
            if client_type:
                query = sql.SQL("""
                    SELECT
                        COUNT(*) as total_artifacts,
                        COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                        COUNT(CASE WHEN status = 'superseded' THEN 1 END) as superseded,
                        COUNT(CASE WHEN status = 'deleted' THEN 1 END) as deleted,
                        COALESCE(SUM(size_bytes), 0) as total_size_bytes
                    FROM {}.artifacts
                    WHERE client_type = %s
                """).format(sql.Identifier(self.schema_name))
                row = self._execute_query(query, (client_type,), fetch='one')
            else:
                query = sql.SQL("""
                    SELECT
                        COUNT(*) as total_artifacts,
                        COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                        COUNT(CASE WHEN status = 'superseded' THEN 1 END) as superseded,
                        COUNT(CASE WHEN status = 'deleted' THEN 1 END) as deleted,
                        COALESCE(SUM(size_bytes), 0) as total_size_bytes
                    FROM {}.artifacts
                """).format(sql.Identifier(self.schema_name))
                row = self._execute_query(query, fetch='one')

            # Get counts by client type
            type_query = sql.SQL("""
                SELECT client_type, COUNT(*) as count
                FROM {}.artifacts
                GROUP BY client_type
            """).format(sql.Identifier(self.schema_name))
            type_rows = self._execute_query(type_query, fetch='all')

            return {
                'total_artifacts': row['total_artifacts'] if row else 0,
                'active': row['active'] if row else 0,
                'superseded': row['superseded'] if row else 0,
                'deleted': row['deleted'] if row else 0,
                'total_size_bytes': row['total_size_bytes'] if row else 0,
                'by_client_type': {r['client_type']: r['count'] for r in type_rows}
            }

    def _row_to_artifact(self, row: Dict[str, Any]) -> Artifact:
        """
        Convert database row to Artifact model.

        Args:
            row: Database row as dict

        Returns:
            Artifact model instance
        """
        return Artifact(
            artifact_id=UUID(row['artifact_id']) if isinstance(row['artifact_id'], str) else row['artifact_id'],
            content_hash=row.get('content_hash'),
            storage_account=row['storage_account'],
            container=row['container'],
            blob_path=row['blob_path'],
            size_bytes=row.get('size_bytes'),
            content_type=row.get('content_type'),
            blob_version_id=row.get('blob_version_id'),
            stac_collection_id=row.get('stac_collection_id'),
            stac_item_id=row.get('stac_item_id'),
            client_type=row['client_type'],
            client_refs=row['client_refs'] if isinstance(row['client_refs'], dict) else json.loads(row['client_refs']),
            source_job_id=row.get('source_job_id'),
            source_task_id=row.get('source_task_id'),
            supersedes=UUID(row['supersedes']) if row.get('supersedes') else None,
            superseded_by=UUID(row['superseded_by']) if row.get('superseded_by') else None,
            revision=row['revision'],
            status=ArtifactStatus(row['status']) if row.get('status') else ArtifactStatus.ACTIVE,
            metadata=row.get('metadata', {}) if isinstance(row.get('metadata'), dict) else json.loads(row.get('metadata', '{}')),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            deleted_at=row.get('deleted_at')
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ArtifactRepository',
]
