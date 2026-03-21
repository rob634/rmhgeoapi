# ============================================================================
# CLAUDE CONTEXT - ACLED API REPOSITORY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - ACLED conflict data API access
# PURPOSE: OAuth 2.0 authenticated access to ACLED API with pagination and dedup
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: ACLEDRepository
# DEPENDENCIES: infrastructure.api_repository, pandas, config, logging
# ============================================================================

import logging
import os
import time
from typing import Any, Dict, Generator, Optional, Set

import pandas as pd
import requests

from infrastructure.api_repository import APIRepository

logger = logging.getLogger(__name__)


class ACLEDRepository(APIRepository):
    """
    Authenticated client for the ACLED conflict event API.

    Implements OAuth 2.0 password grant with automatic token refresh.
    Provides paginated fetch and diff-against-existing-table logic for
    incremental sync into a PostGIS Silver table.

    Credentials are read from environment variables:
        ACLED_USERNAME — registered ACLED account email
        ACLED_PASSWORD — registered ACLED account password

    Raises ValueError on construction if either variable is missing.
    """

    BASE_URL = "https://acleddata.com"
    TOKEN_URL = f"{BASE_URL}/oauth/token"
    API_URL = f"{BASE_URL}/api/acled"

    # Ordered column list matching ops.acled_new schema (Dec 2025 API revision)
    COLUMNS = [
        "event_id_cnty", "event_date", "year", "time_precision",
        "disorder_type", "event_type", "sub_event_type",
        "actor1", "assoc_actor_1", "inter1",
        "actor2", "assoc_actor_2", "inter2",
        "interaction", "civilian_targeting", "iso",
        "region", "country", "admin1", "admin2", "admin3",
        "location", "latitude", "longitude", "geo_precision",
        "source", "source_scale", "notes", "fatalities",
        "tags", "timestamp",
    ]

    def __init__(self) -> None:
        """
        Initialise repository and validate credentials from environment.

        Raises:
            ValueError: If ACLED_USERNAME or ACLED_PASSWORD are not set.
        """
        super().__init__(base_url=self.BASE_URL, timeout=60, max_retries=3)

        self._username = os.environ.get("ACLED_USERNAME")
        self._password = os.environ.get("ACLED_PASSWORD")

        if not self._username:
            raise ValueError(
                "ACLED_USERNAME environment variable is required but not set."
            )
        if not self._password:
            raise ValueError(
                "ACLED_PASSWORD environment variable is required but not set."
            )

        self._access_token: Optional[str] = None
        self._refresh_token_value: Optional[str] = None
        self._token_expiry: Optional[float] = None

        # Suppress SSL warnings for this session only (verify=False required
        # for corporate proxy environments). Does NOT affect other HTTP clients.
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        logger.info("ACLEDRepository initialised for user=%s", self._username)

    # ------------------------------------------------------------------
    # APIRepository abstract interface
    # ------------------------------------------------------------------

    def authenticate(self) -> None:
        """
        Acquire initial OAuth 2.0 tokens using password grant.

        Stores access token, refresh token, and expiry on the instance.
        Sets self._authenticated = True on success.

        Raises:
            requests.HTTPError: If the token endpoint returns a non-2xx response.
            ValueError: If the response does not contain an access_token.
        """
        logger.info("Authenticating with ACLED API (password grant)...")

        response = self._session.post(
            self.TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "username": self._username,
                "password": self._password,
                "grant_type": "password",
                "client_id": "acled",
            },
            verify=False,
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()

        if "access_token" not in token_data:
            raise ValueError(
                f"ACLED token response missing access_token. Response: {token_data}"
            )

        self._store_tokens(token_data)
        self._authenticated = True
        logger.info(
            "ACLED authentication successful. Token valid for ~%dh.",
            int((self._token_expiry - time.time()) / 3600),
        )

    def refresh_token(self) -> None:
        """
        Refresh the OAuth access token using the stored refresh token.

        Falls back to a full re-authentication if no refresh token is
        available or if the refresh request fails.
        """
        if not self._refresh_token_value:
            logger.warning("No refresh token stored — falling back to full authenticate()")
            self.authenticate()
            return

        logger.info("Refreshing ACLED OAuth token...")

        try:
            response = self._session.post(
                self.TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "refresh_token": self._refresh_token_value,
                    "grant_type": "refresh_token",
                    "client_id": "acled",
                },
                verify=False,
                timeout=30,
            )
            response.raise_for_status()
            token_data = response.json()

            if "access_token" not in token_data:
                logger.warning(
                    "Refresh response missing access_token — falling back to authenticate()"
                )
                self.authenticate()
                return

            self._store_tokens(token_data)
            logger.info("ACLED token refresh successful.")

        except requests.RequestException as exc:
            logger.warning(
                "Token refresh request failed (%s) — falling back to authenticate()", exc
            )
            self.authenticate()

    def get_auth_headers(self) -> dict:
        """
        Return the Authorization header for the current access token.

        Checks token expiry first; refreshes proactively if expired.

        Returns:
            dict: {"Authorization": "Bearer <token>"}

        Raises:
            RuntimeError: If called before authenticate() has succeeded.
        """
        if not self._access_token:
            raise RuntimeError(
                "get_auth_headers() called before authenticate(). "
                "This should not happen — APIRepository calls _ensure_authenticated() first."
            )

        if self._token_expiry and time.time() >= self._token_expiry:
            logger.info("ACLED token expired — refreshing proactively.")
            self.refresh_token()

        return {"Authorization": f"Bearer {self._access_token}"}

    # ------------------------------------------------------------------
    # ACLED-specific fetch methods
    # ------------------------------------------------------------------

    def fetch_page(self, page: int, limit: int = 5000) -> Optional[pd.DataFrame]:
        """
        Fetch a single page of ACLED events from the API.

        Args:
            page:  1-based page number.
            limit: Records per page (ACLED hard cap is 5000).

        Returns:
            DataFrame with COLUMNS columns, or None if the page is empty.

        Raises:
            requests.HTTPError: On non-transient HTTP errors from the API.
        """
        logger.debug("Fetching ACLED page=%d limit=%d", page, limit)

        response = self.get(
            f"{self.API_URL}/read",
            params={"limit": min(limit, 5000), "page": page},
            verify=False,
        )
        data = response.json()

        records = data.get("data") if isinstance(data, dict) else data
        if not records:
            logger.debug("Page %d returned no data — end of results.", page)
            return None

        df = pd.json_normalize(records)

        # Ensure all expected columns are present (API may omit sparse fields)
        for col in self.COLUMNS:
            if col not in df.columns:
                df[col] = None

        df = df[self.COLUMNS]
        logger.info("ACLED page=%d fetched %d records.", page, len(df))
        return df

    def fetch_pages(
        self,
        max_pages: int = 0,
        limit: int = 5000,
    ) -> Generator[pd.DataFrame, None, None]:
        """
        Generator that yields one DataFrame per page of ACLED results.

        Args:
            max_pages: Maximum number of pages to fetch. 0 means unlimited
                       (continue until an empty page is returned).
            limit:     Records per page (passed to fetch_page).

        Yields:
            pd.DataFrame: One page of events with COLUMNS columns.
        """
        page = 1
        while True:
            if max_pages and page > max_pages:
                logger.info("Reached max_pages=%d — stopping pagination.", max_pages)
                break

            df = self.fetch_page(page=page, limit=limit)
            if df is None or df.empty:
                logger.info("Empty page at page=%d — pagination complete.", page)
                break

            yield df
            page += 1

    def fetch_and_diff(
        self,
        max_pages: int,
        batch_size: int,
        target_schema: str,
        target_table: str,
    ) -> dict:
        """
        Fetch ACLED pages and diff against existing PostGIS table rows.

        Loads the existing event_id_cnty set from the target table, then
        pages through the API collecting only events not already present.
        Also captures raw JSON responses for downstream persistence.

        Args:
            max_pages:     Pages to process (0 = unlimited).
            batch_size:    Records per API page (max 5000).
            target_schema: PostGIS schema containing the target table.
            target_table:  Table name to diff against (e.g. "acled_new").

        Returns:
            dict with keys:
                new_events (list[dict]):    New records not yet in the table.
                raw_responses (list[dict]): Full API response dicts, one per page.
                metadata (dict): {
                    pages_processed (int),
                    total_fetched (int),
                    duplicates_skipped (int),
                    new_count (int),
                    db_max_timestamp (int | None),
                }

        Raises:
            psycopg.Error: On database connectivity or query failure.
            requests.HTTPError: On non-transient ACLED API errors.
        """
        existing_ids, db_max_timestamp = self._load_existing_ids(
            target_schema, target_table
        )
        logger.info(
            "Loaded %d existing event IDs from %s.%s (max_timestamp=%s).",
            len(existing_ids),
            target_schema,
            target_table,
            db_max_timestamp,
        )

        new_events: list = []
        raw_responses: list = []
        pages_processed = 0
        total_fetched = 0
        duplicates_skipped = 0

        for df in self.fetch_pages(max_pages=max_pages, limit=batch_size):
            pages_processed += 1
            total_fetched += len(df)

            # Capture raw records before filtering
            raw_responses.append(df.to_dict(orient="records"))

            # Diff — keep only events not yet in the Silver table
            new_mask = ~df["event_id_cnty"].isin(existing_ids)
            page_dupes = int((~new_mask).sum())
            duplicates_skipped += page_dupes

            new_df = df[new_mask]
            if not new_df.empty:
                page_new = new_df.to_dict(orient="records")
                new_events.extend(page_new)
                # Update local set so intra-run dupes across pages are caught too
                existing_ids.update(new_df["event_id_cnty"].tolist())

            logger.info(
                "Page %d: fetched=%d new=%d dupes=%d (running new=%d)",
                pages_processed,
                len(df),
                len(new_df),
                page_dupes,
                len(new_events),
            )

        metadata = {
            "pages_processed": pages_processed,
            "total_fetched": total_fetched,
            "duplicates_skipped": duplicates_skipped,
            "new_count": len(new_events),
            "db_max_timestamp": db_max_timestamp,
        }

        logger.info(
            "fetch_and_diff complete: pages=%d fetched=%d new=%d dupes=%d",
            pages_processed,
            total_fetched,
            len(new_events),
            duplicates_skipped,
        )

        return {
            "new_events": new_events,
            "raw_responses": raw_responses,
            "metadata": metadata,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_tokens(self, token_data: dict) -> None:
        """Parse a token response dict and update instance token state."""
        self._access_token = token_data["access_token"]
        self._refresh_token_value = token_data.get(
            "refresh_token", self._refresh_token_value
        )
        expires_in = token_data.get("expires_in", 86400)
        # 5-minute buffer to proactively refresh before hard expiry
        self._token_expiry = time.time() + expires_in - 300

    def _load_existing_ids(
        self, schema: str, table: str
    ) -> tuple[Set[str], Optional[int]]:
        """
        Query the target PostGIS table for all existing event IDs and the
        maximum timestamp value (used by callers for incremental context).

        Args:
            schema: Database schema name.
            table:  Table name.

        Returns:
            Tuple of (set of event_id_cnty strings, max timestamp int or None).

        Raises:
            psycopg.Error: On any database error.
        """
        import psycopg
        from psycopg import sql
        from infrastructure.db_auth import ManagedIdentityAuth
        from infrastructure.db_connections import ConnectionManager

        auth = ManagedIdentityAuth()
        manager = ConnectionManager(auth)

        existing_ids: Set[str] = set()
        db_max_timestamp: Optional[int] = None

        query = sql.SQL(
            "SELECT event_id_cnty, MAX(timestamp) OVER () AS max_ts FROM {}.{}"
        ).format(sql.Identifier(schema), sql.Identifier(table))

        try:
            with manager.get_connection() as conn:
                with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    cur.execute(query)
                    rows = cur.fetchall()
                    if rows:
                        for row in rows:
                            existing_ids.add(row["event_id_cnty"])
                        db_max_timestamp = rows[0]["max_ts"]
        except psycopg.errors.UndefinedTable:
            # Table does not yet exist — treat as empty; downstream handler creates it
            logger.warning(
                "Table %s.%s does not exist — treating as empty for diff.",
                schema,
                table,
            )

        return existing_ids, db_max_timestamp
