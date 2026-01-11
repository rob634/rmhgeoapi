# ============================================================================
# APPLICATION INSIGHTS LOG EXPORTER
# ============================================================================
# STATUS: Infrastructure - Python-based log export from App Insights to blob
# PURPOSE: Export logs via REST API for debugging opaque QA environments
# LAST_REVIEWED: 10 JAN 2026
# EXPORTS: AppInsightsExporter, export_logs_to_blob, query_logs
# DEPENDENCIES: azure.identity, azure.storage.blob, requests
# ============================================================================
"""
Application Insights Log Exporter.

Provides Python-based log export from Application Insights to blob storage
for debugging in corporate Azure environments where portal access may be
restricted.

Design (F7.12.D):
    - Query App Insights REST API directly
    - Export results to blob storage as JSON Lines
    - Support common query patterns (traces, exceptions, requests)
    - Include timing and metadata in exports

Usage:
    from infrastructure.appinsights_exporter import export_logs_to_blob, query_logs

    # Query logs
    results = query_logs(
        query="traces | where timestamp >= ago(1h) | take 100",
        timespan="PT1H"
    )

    # Export to blob
    export_result = export_logs_to_blob(
        query="traces | where message contains 'SERVICE_LATENCY'",
        timespan="PT24H",
        container="applogs",
        prefix="exports/latency"
    )

Environment Variables:
    APPINSIGHTS_APP_ID: Application Insights application ID (required for queries)
    SILVER_STORAGE_ACCOUNT: Storage account for exports
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class QueryResult:
    """Result of an App Insights query."""
    success: bool
    row_count: int
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    query_duration_ms: float = 0
    error: Optional[str] = None

    def to_records(self) -> List[Dict[str, Any]]:
        """Convert rows to list of dicts."""
        return [dict(zip(self.columns, row)) for row in self.rows]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "row_count": self.row_count,
            "columns": self.columns,
            "query_duration_ms": round(self.query_duration_ms, 2),
            "error": self.error,
        }


@dataclass
class ExportResult:
    """Result of a log export operation."""
    success: bool
    blob_path: Optional[str] = None
    row_count: int = 0
    export_duration_ms: float = 0
    query_duration_ms: float = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "blob_path": self.blob_path,
            "row_count": self.row_count,
            "export_duration_ms": round(self.export_duration_ms, 2),
            "query_duration_ms": round(self.query_duration_ms, 2),
            "error": self.error,
        }


class AppInsightsExporter:
    """
    Export logs from Application Insights to blob storage.

    Uses Azure AD authentication via DefaultAzureCredential.
    """

    # App Insights REST API endpoint
    API_BASE = "https://api.applicationinsights.io/v1/apps"

    # Common query templates
    QUERY_TEMPLATES = {
        "recent_traces": "traces | where timestamp >= ago({timespan}) | order by timestamp desc | take {limit}",
        "recent_errors": "traces | where timestamp >= ago({timespan}) | where severityLevel >= 3 | order by timestamp desc | take {limit}",
        "service_latency": "traces | where timestamp >= ago({timespan}) | where message contains '[SERVICE_LATENCY]' | order by timestamp desc | take {limit}",
        "db_latency": "traces | where timestamp >= ago({timespan}) | where message contains '[DB_LATENCY]' | order by timestamp desc | take {limit}",
        "startup_failures": "traces | where timestamp >= ago({timespan}) | where message contains 'STARTUP_FAILED' | order by timestamp desc | take {limit}",
        "exceptions": "exceptions | where timestamp >= ago({timespan}) | order by timestamp desc | take {limit}",
        "slow_requests": "requests | where timestamp >= ago({timespan}) | where duration > 5000 | order by duration desc | take {limit}",
    }

    def __init__(self, app_id: Optional[str] = None):
        """
        Initialize exporter.

        Args:
            app_id: Application Insights app ID. If not provided,
                   reads from APPINSIGHTS_APP_ID env var.
        """
        self.app_id = app_id or os.environ.get("APPINSIGHTS_APP_ID")
        self._credential = None
        self._blob_client = None

    def _get_credential(self):
        """Get or create Azure credential."""
        if self._credential is None:
            from azure.identity import DefaultAzureCredential
            self._credential = DefaultAzureCredential()
        return self._credential

    def _get_access_token(self) -> str:
        """Get access token for App Insights API."""
        credential = self._get_credential()
        token = credential.get_token("https://api.applicationinsights.io/.default")
        return token.token

    def _get_blob_client(self):
        """Get or create blob service client."""
        if self._blob_client is None:
            from azure.storage.blob import BlobServiceClient

            storage_account = os.environ.get("SILVER_STORAGE_ACCOUNT")
            if not storage_account:
                raise ValueError("SILVER_STORAGE_ACCOUNT not configured")

            account_url = f"https://{storage_account}.blob.core.windows.net"
            credential = self._get_credential()
            self._blob_client = BlobServiceClient(
                account_url=account_url,
                credential=credential
            )
        return self._blob_client

    def query_logs(
        self,
        query: str,
        timespan: str = "PT1H",
        timeout: float = 60.0
    ) -> QueryResult:
        """
        Query Application Insights logs.

        Args:
            query: KQL query string
            timespan: ISO 8601 duration (PT1H = 1 hour, P1D = 1 day)
            timeout: Request timeout in seconds

        Returns:
            QueryResult with rows and metadata
        """
        import requests

        if not self.app_id:
            return QueryResult(
                success=False,
                row_count=0,
                error="APPINSIGHTS_APP_ID not configured"
            )

        start = time.perf_counter()

        try:
            token = self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            url = f"{self.API_BASE}/{self.app_id}/query"
            params = {"timespan": timespan}
            body = {"query": query}

            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=body,
                timeout=timeout
            )

            duration_ms = (time.perf_counter() - start) * 1000

            if response.status_code != 200:
                return QueryResult(
                    success=False,
                    row_count=0,
                    query_duration_ms=duration_ms,
                    error=f"API error {response.status_code}: {response.text[:500]}"
                )

            data = response.json()

            # Parse response
            tables = data.get("tables", [])
            if not tables:
                return QueryResult(
                    success=True,
                    row_count=0,
                    columns=[],
                    rows=[],
                    query_duration_ms=duration_ms,
                )

            table = tables[0]
            columns = [col["name"] for col in table.get("columns", [])]
            rows = table.get("rows", [])

            return QueryResult(
                success=True,
                row_count=len(rows),
                columns=columns,
                rows=rows,
                query_duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return QueryResult(
                success=False,
                row_count=0,
                query_duration_ms=duration_ms,
                error=str(e)
            )

    def export_to_blob(
        self,
        query: str,
        timespan: str = "PT24H",
        container: str = "applogs",
        prefix: str = "exports",
    ) -> ExportResult:
        """
        Export query results to blob storage.

        Args:
            query: KQL query string
            timespan: ISO 8601 duration for query
            container: Blob container name
            prefix: Blob path prefix

        Returns:
            ExportResult with blob path and metadata
        """
        export_start = time.perf_counter()

        # Run query
        query_result = self.query_logs(query, timespan)

        if not query_result.success:
            return ExportResult(
                success=False,
                query_duration_ms=query_result.query_duration_ms,
                error=query_result.error
            )

        if query_result.row_count == 0:
            return ExportResult(
                success=True,
                row_count=0,
                query_duration_ms=query_result.query_duration_ms,
                error="No rows returned"
            )

        # Convert to JSON Lines
        records = query_result.to_records()
        lines = [json.dumps(record, default=str) for record in records]
        content = "\n".join(lines) + "\n"

        # Generate blob name
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        timestamp_str = now.strftime("%Y%m%dT%H%M%SZ")
        blob_name = f"{prefix}/{date_str}/{timestamp_str}.jsonl"

        # Upload to blob
        try:
            blob_client = self._get_blob_client()
            container_client = blob_client.get_container_client(container)

            # Ensure container exists
            try:
                container_client.create_container()
            except Exception:
                pass  # Already exists

            blob = container_client.get_blob_client(blob_name)
            blob.upload_blob(content, overwrite=True)

            export_duration_ms = (time.perf_counter() - export_start) * 1000

            return ExportResult(
                success=True,
                blob_path=f"{container}/{blob_name}",
                row_count=query_result.row_count,
                export_duration_ms=export_duration_ms,
                query_duration_ms=query_result.query_duration_ms,
            )

        except Exception as e:
            export_duration_ms = (time.perf_counter() - export_start) * 1000
            return ExportResult(
                success=False,
                row_count=query_result.row_count,
                export_duration_ms=export_duration_ms,
                query_duration_ms=query_result.query_duration_ms,
                error=str(e)
            )

    def export_template(
        self,
        template_name: str,
        timespan: str = "1h",
        limit: int = 1000,
        container: str = "applogs",
    ) -> ExportResult:
        """
        Export using a predefined query template.

        Args:
            template_name: One of QUERY_TEMPLATES keys
            timespan: Duration without PT prefix (e.g., "1h", "24h", "7d")
            limit: Maximum rows to return
            container: Blob container name

        Returns:
            ExportResult with blob path and metadata
        """
        if template_name not in self.QUERY_TEMPLATES:
            return ExportResult(
                success=False,
                error=f"Unknown template: {template_name}. Available: {list(self.QUERY_TEMPLATES.keys())}"
            )

        template = self.QUERY_TEMPLATES[template_name]
        query = template.format(timespan=timespan, limit=limit)

        # Convert timespan to ISO 8601 format
        iso_timespan = f"PT{timespan.upper()}" if not timespan.startswith("P") else timespan

        return self.export_to_blob(
            query=query,
            timespan=iso_timespan,
            container=container,
            prefix=f"exports/{template_name}",
        )


# ============================================================================
# MODULE-LEVEL FUNCTIONS
# ============================================================================

# Singleton exporter
_exporter: Optional[AppInsightsExporter] = None


def get_exporter() -> AppInsightsExporter:
    """Get singleton exporter instance."""
    global _exporter
    if _exporter is None:
        _exporter = AppInsightsExporter()
    return _exporter


def query_logs(
    query: str,
    timespan: str = "PT1H",
    timeout: float = 60.0
) -> QueryResult:
    """
    Query Application Insights logs (convenience function).

    Args:
        query: KQL query string
        timespan: ISO 8601 duration
        timeout: Request timeout in seconds

    Returns:
        QueryResult with rows and metadata
    """
    return get_exporter().query_logs(query, timespan, timeout)


def export_logs_to_blob(
    query: str,
    timespan: str = "PT24H",
    container: str = "applogs",
    prefix: str = "exports",
) -> ExportResult:
    """
    Export query results to blob storage (convenience function).

    Args:
        query: KQL query string
        timespan: ISO 8601 duration
        container: Blob container name
        prefix: Blob path prefix

    Returns:
        ExportResult with blob path and metadata
    """
    return get_exporter().export_to_blob(query, timespan, container, prefix)


def export_template(
    template_name: str,
    timespan: str = "1h",
    limit: int = 1000,
    container: str = "applogs",
) -> ExportResult:
    """
    Export using predefined template (convenience function).

    Available templates:
        - recent_traces: Recent trace logs
        - recent_errors: Recent error logs (severity >= 3)
        - service_latency: Service latency metrics
        - db_latency: Database latency metrics
        - startup_failures: Startup failure logs
        - exceptions: Exception logs
        - slow_requests: Slow HTTP requests (> 5s)

    Args:
        template_name: Template name from list above
        timespan: Duration (e.g., "1h", "24h")
        limit: Max rows
        container: Blob container

    Returns:
        ExportResult with blob path
    """
    return get_exporter().export_template(template_name, timespan, limit, container)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AppInsightsExporter",
    "QueryResult",
    "ExportResult",
    "get_exporter",
    "query_logs",
    "export_logs_to_blob",
    "export_template",
]
