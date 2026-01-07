# ACLED Azure Function App - Complete Build Guide

This document contains all the code and configuration needed to rebuild the ACLED data pipeline as an Azure Function App.

**Author:** World Bank GeoCenter  
**Last Updated:** January 2026

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Database Schema](#database-schema)
4. [Project Structure](#project-structure)
5. [Configuration Files](#configuration-files)
6. [Source Code](#source-code)
7. [Deployment](#deployment)
8. [Usage](#usage)

---

## Overview

The ACLED (Armed Conflict Location & Event Data) pipeline syncs conflict event data from the ACLED API to a PostgreSQL database. It supports:

- **OAuth 2.0 Authentication** with automatic token refresh
- **Two sync modes:**
  - `quick_sync()` - Timestamp-based, fetches only new records (fast, for daily updates)
  - `full_sync()` - Page iteration with deduplication (thorough, for verification)
- **Bulk insert** using PostgreSQL COPY protocol (fastest method)
- **Azure Functions** with timer and HTTP triggers

### Key Features

- ~2.8M conflict event records worldwide
- Daily automated sync via timer trigger
- Manual sync via HTTP endpoint
- Status endpoint for monitoring
- Batch processing for resilience (failures only lose one batch)

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   ACLED API     │────▶│  Azure Function │────▶│   PostgreSQL    │
│  (OAuth 2.0)    │     │    Pipeline     │     │   Database      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                        ┌───────────┐
                        │ Timer     │ Daily @ 6AM UTC
                        │ HTTP      │ On-demand sync
                        │ Status    │ Health check
                        └───────────┘
```

---

## Database Schema

### Table: `ops.acled_new`

> **Note:** The ACLED API changed `inter1`, `inter2`, and `interaction` from INTEGER to VARCHAR (string descriptions like "Protesters", "Rebel group-Civilians"). Use the schema below for new deployments.

```sql
-- Drop if exists (for clean rebuild)
DROP TABLE IF EXISTS ops.acled_new;

-- Create table with correct schema (as of Dec 2025)
CREATE TABLE ops.acled_new (
    event_id_cnty       VARCHAR PRIMARY KEY,
    event_date          VARCHAR,
    year                INTEGER,
    time_precision      INTEGER,
    disorder_type       VARCHAR,
    event_type          VARCHAR,
    sub_event_type      VARCHAR,
    actor1              VARCHAR,
    assoc_actor_1       VARCHAR,
    inter1              VARCHAR,          -- String: "State Forces", "Rebel group", etc.
    actor2              VARCHAR,
    assoc_actor_2       VARCHAR,
    inter2              VARCHAR,          -- String: "Civilians", "Protesters", etc.
    interaction         VARCHAR,          -- String: "State Forces-Civilians", etc.
    civilian_targeting  VARCHAR,
    iso                 INTEGER,
    region              VARCHAR,
    country             VARCHAR,
    admin1              VARCHAR,
    admin2              VARCHAR,
    admin3              VARCHAR,
    location            VARCHAR,
    latitude            NUMERIC,
    longitude           NUMERIC,
    geo_precision       INTEGER,
    source              VARCHAR,
    source_scale        VARCHAR,
    notes               TEXT,             -- TEXT for long descriptions
    fatalities          INTEGER,
    tags                VARCHAR,
    timestamp           BIGINT            -- Unix timestamp: when added to ACLED DB
);

-- Create indexes for common queries
CREATE INDEX idx_acled_new_country ON ops.acled_new(country);
CREATE INDEX idx_acled_new_event_date ON ops.acled_new(event_date);
CREATE INDEX idx_acled_new_year ON ops.acled_new(year);
CREATE INDEX idx_acled_new_timestamp ON ops.acled_new(timestamp);
```

### Column Notes

| Column | Type | Description |
|--------|------|-------------|
| `event_id_cnty` | VARCHAR | Primary key - unique event identifier |
| `timestamp` | BIGINT | Unix timestamp when record was **added to ACLED** (not event date) |
| `inter1`, `inter2` | VARCHAR | Actor type descriptions (changed from INTEGER) |
| `interaction` | VARCHAR | Combined interaction type (e.g., "Rebel group-Civilians") |
| `notes` | TEXT | Long text field for event descriptions |

---

## Project Structure

```
acled/
├── function_app.py      # Azure Function entry point
├── acled_auth.py        # OAuth 2.0 authentication
├── acled_db.py          # Database operations (psycopg v3)
├── acled_pipeline.py    # Main sync pipeline
├── config.py            # Logging configuration
├── requirements.txt     # Python dependencies
├── host.json            # Azure Functions host config
├── local.settings.json  # Local dev settings (secrets)
└── logs/                # Log files directory
```

---

## Configuration Files

### `requirements.txt`

```
# ACLED Data Pipeline Requirements
# DO NOT include azure-functions-worker - managed by Azure

# Azure Functions
azure-functions

# Database
psycopg[binary]>=3.0

# Data Processing
pandas>=2.0

# HTTP Requests
requests>=2.28
```

### `host.json`

```json
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": {
        "isEnabled": true,
        "excludedTypes": "Request"
      }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
```

### `local.settings.json`

> **⚠️ SECRETS - Do not commit to git!**

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    
    "ACLED_USERNAME": "<your-acled-email>",
    "ACLED_PASSWORD": "<your-acled-password>",
    
    "DB_HOST": "<your-postgres-host>",
    "DB_NAME": "<your-database>",
    "DB_USER": "<your-db-user>",
    "DB_PASSWORD": "<your-db-password>",
    "DB_PORT": "5432",
    "DB_SCHEMA": "ops",
    "DB_TABLE": "acled_new"
  }
}
```

---

## Source Code

### `config.py` - Logging Configuration

```python
"""
ACLED Pipeline Configuration
============================
Logging configuration and shared constants.
"""

import logging
import os
import sys
import time


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)


class ColorFormatter(logging.Formatter):
    """Custom formatter to add colors to log messages."""

    def _green(self, string):
        return f"\033[92m{string}\033[0m"

    def _yellow(self, string):
        return f"\033[93m{string}\033[0m"

    def _red(self, string):
        return f"\033[91m{string}\033[0m"

    def _blue(self, string):
        return f"\033[94m{string}\033[0m"

    def format(self, record):
        original_format = self._style._fmt

        if record.levelno == logging.ERROR:
            self._style._fmt = self._red(original_format)
        elif record.levelno == logging.WARNING:
            self._style._fmt = self._yellow(original_format)
        elif record.levelno == logging.INFO:
            self._style._fmt = self._green(original_format)

        result = logging.Formatter.format(self, record)
        self._style._fmt = original_format
        return result


now = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())


def _get_log_file():
    if len(sys.argv) > 1 and "kernel" not in sys.argv[1].lower() and sys.argv[1].endswith(".log"):
        return sys.argv[1]
    return os.path.join(LOG_DIR, f"{now}.log")


current_log_file = _get_log_file()


def _get_logger():
    """Get or create the singleton logger instance."""
    _logger = logging.getLogger("OpsDataPipelineLogger")
    
    # Remove existing handlers to prevent duplicates
    if _logger.handlers:
        _logger.handlers.clear()
    
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False
    
    # Console handler (stdout for Jupyter compatibility)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_format = ColorFormatter("%(asctime)s - %(levelname)s - %(funcName)s - %(message)s",
                                     datefmt="%H:%M:%S")
    console_handler.setFormatter(console_format)
    _logger.addHandler(console_handler)
    
    # File handler
    try:
        file_handler = logging.FileHandler(current_log_file)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter("%(asctime)s - %(levelname)s - %(funcName)s - %(message)s")
        file_handler.setFormatter(file_format)
        _logger.addHandler(file_handler)
    except Exception:
        pass  # Skip file logging if not available
    
    return _logger


logger = _get_logger()
```

---

### `acled_auth.py` - OAuth Authentication

```python
"""
ACLED OAuth Authentication Module
=================================
Handles OAuth 2.0 authentication for the ACLED API.

Usage:
    auth = ACLEDAuth("user@example.com", "password")
    auth.authenticate()
    data = auth.request("read", {"limit": 100})
"""

import os
import time
from typing import Optional
import requests

from config import logger

requests.packages.urllib3.disable_warnings()


class ACLEDAuth:
    """OAuth 2.0 authentication handler for ACLED API."""
    
    BASE_URL = "https://acleddata.com"
    TOKEN_URL = f"{BASE_URL}/oauth/token"
    API_URL = f"{BASE_URL}/api/acled"
    
    def __init__(
        self, 
        username: Optional[str] = None, 
        password: Optional[str] = None
    ):
        """
        Initialize ACLED authentication.
        
        Args:
            username: ACLED account email (or set ACLED_USERNAME env var)
            password: ACLED account password (or set ACLED_PASSWORD env var)
        """
        self.username = username or os.environ.get("ACLED_USERNAME")
        self.password = password or os.environ.get("ACLED_PASSWORD")
        
        if not self.username or not self.password:
            raise ValueError(
                "ACLED credentials required. Provide username/password or set "
                "ACLED_USERNAME and ACLED_PASSWORD environment variables."
            )
        
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry: Optional[float] = None
        
        logger.info(f"ACLEDAuth initialized for {self.username}")
    
    def authenticate(self) -> str:
        """Get initial OAuth token using username/password."""
        logger.info("Authenticating with ACLED API...")
        
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
            "client_id": "acled"
        }
        
        try:
            response = requests.post(
                self.TOKEN_URL, 
                headers=headers, 
                data=data, 
                verify=False,  # Corporate proxy SSL bypass
                timeout=30
            )
            response.raise_for_status()
            token_data = response.json()
            
            if "access_token" not in token_data:
                raise AuthenticationError(f"No access token in response: {token_data}")
            
            self.access_token = token_data["access_token"]
            self.refresh_token = token_data.get("refresh_token")
            
            # Set expiry time (with 5 minute buffer)
            expires_in = token_data.get("expires_in", 86400)
            self.token_expiry = time.time() + expires_in - 300
            
            logger.info(f"Authentication successful. Token expires in {expires_in // 3600} hours")
            return self.access_token
            
        except requests.RequestException as e:
            logger.error(f"Authentication request failed: {e}")
            raise AuthenticationError(f"Failed to authenticate: {e}")
    
    def refresh(self) -> str:
        """Refresh OAuth token using refresh_token."""
        if not self.refresh_token:
            logger.warning("No refresh token available, re-authenticating...")
            return self.authenticate()
        
        logger.info("Refreshing ACLED API token...")
        
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
            "client_id": "acled"
        }
        
        try:
            response = requests.post(
                self.TOKEN_URL,
                headers=headers,
                data=data,
                verify=False,
                timeout=30
            )
            response.raise_for_status()
            token_data = response.json()
            
            if "access_token" not in token_data:
                logger.warning("Refresh failed, re-authenticating...")
                return self.authenticate()
            
            self.access_token = token_data["access_token"]
            self.refresh_token = token_data.get("refresh_token", self.refresh_token)
            
            expires_in = token_data.get("expires_in", 86400)
            self.token_expiry = time.time() + expires_in - 300
            
            logger.info("Token refresh successful")
            return self.access_token
            
        except requests.RequestException as e:
            logger.warning(f"Token refresh failed: {e}, re-authenticating...")
            return self.authenticate()
    
    def get_token(self) -> str:
        """Get valid access token, refreshing if expired."""
        if not self.access_token:
            return self.authenticate()
        
        if self.token_expiry and time.time() >= self.token_expiry:
            logger.info("Token expired, refreshing...")
            return self.refresh()
        
        return self.access_token
    
    def request(
        self, 
        endpoint: str = "read", 
        params: Optional[dict] = None,
        timeout: int = 60
    ) -> dict:
        """
        Make authenticated request to ACLED API.
        
        Args:
            endpoint: API endpoint (default: "read")
            params: Query parameters
            timeout: Request timeout in seconds
        """
        token = self.get_token()
        url = f"{self.API_URL}/{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}
        
        logger.debug(f"API request: {endpoint} with params {params}")
        
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                verify=False,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise APIError(f"API request to {endpoint} failed: {e}")


class AuthenticationError(Exception):
    """Raised when ACLED authentication fails."""
    pass


class APIError(Exception):
    """Raised when ACLED API request fails."""
    pass
```

---

### `acled_db.py` - Database Operations

```python
"""
ACLED Database Module
=====================
PostgreSQL database operations using psycopg (v3).

Features:
    - Bulk insert using COPY protocol (fastest)
    - Connection management (Azure Function compatible)
    - Deduplication support
"""

import os
from io import StringIO
from typing import Optional, Set

import pandas as pd
import psycopg
from psycopg import sql

from config import logger


class ACLEDDatabase:
    """PostgreSQL database handler for ACLED data."""
    
    # ACLED table columns
    COLUMNS = [
        "event_id_cnty", "event_date", "year", "time_precision",
        "disorder_type", "event_type", "sub_event_type",
        "actor1", "assoc_actor_1", "inter1",
        "actor2", "assoc_actor_2", "inter2",
        "interaction", "civilian_targeting", "iso",
        "region", "country", "admin1", "admin2", "admin3",
        "location", "latitude", "longitude", "geo_precision",
        "source", "source_scale", "notes", "fatalities",
        "tags", "timestamp"
    ]
    
    # SQL types for each column (updated for new API schema)
    COLUMN_TYPES = {
        "event_id_cnty": "VARCHAR PRIMARY KEY",
        "event_date": "VARCHAR",
        "year": "INTEGER",
        "time_precision": "INTEGER",
        "disorder_type": "VARCHAR",
        "event_type": "VARCHAR",
        "sub_event_type": "VARCHAR",
        "actor1": "VARCHAR",
        "assoc_actor_1": "VARCHAR",
        "inter1": "VARCHAR",      # Changed from INTEGER
        "actor2": "VARCHAR",
        "assoc_actor_2": "VARCHAR",
        "inter2": "VARCHAR",      # Changed from INTEGER
        "interaction": "VARCHAR", # Changed from INTEGER
        "civilian_targeting": "VARCHAR",
        "iso": "INTEGER",
        "region": "VARCHAR",
        "country": "VARCHAR",
        "admin1": "VARCHAR",
        "admin2": "VARCHAR",
        "admin3": "VARCHAR",
        "location": "VARCHAR",
        "latitude": "NUMERIC",
        "longitude": "NUMERIC",
        "geo_precision": "INTEGER",
        "source": "VARCHAR",
        "source_scale": "VARCHAR",
        "notes": "TEXT",          # Changed from VARCHAR
        "fatalities": "INTEGER",
        "tags": "VARCHAR",
        "timestamp": "BIGINT",
    }
    
    def __init__(
        self,
        config: Optional[dict] = None,
        schema: str = "ops",
        table: str = "acled_new"
    ):
        """
        Initialize database connection configuration.
        
        Args:
            config: Database connection parameters (or use env vars)
            schema: Database schema name
            table: Table name
        """
        if config:
            self.config = config
        else:
            self.config = {
                "host": os.environ.get("DB_HOST"),
                "dbname": os.environ.get("DB_NAME"),
                "user": os.environ.get("DB_USER"),
                "password": os.environ.get("DB_PASSWORD"),
                "port": int(os.environ.get("DB_PORT", 5432)),
            }
        
        self.schema = schema
        self.table = table
        self.full_table_name = f"{schema}.{table}"
        
        logger.info(f"ACLEDDatabase initialized for {self.config.get('host')}/{self.config.get('dbname')}")
    
    def connect(self) -> psycopg.Connection:
        """
        Create new database connection.
        
        Note: Creates fresh connection each time (Azure Function compatible).
              Do NOT use connection pooling in serverless environments.
        """
        try:
            conn = psycopg.connect(**self.config)
            logger.debug(f"Connected to {self.config['host']}/{self.config['dbname']}")
            return conn
        except psycopg.Error as e:
            logger.error(f"Database connection failed: {e}")
            raise DatabaseError(f"Failed to connect to database: {e}")
    
    def table_exists(self) -> bool:
        """Check if ACLED table exists."""
        query = """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            );
        """
        
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (self.schema, self.table))
                exists = cur.fetchone()[0]
        
        return exists
    
    def create_table(self) -> None:
        """Create ACLED table if it doesn't exist."""
        if self.table_exists():
            logger.info(f"Table {self.full_table_name} already exists")
            return
        
        col_defs = [f'"{col}" {self.COLUMN_TYPES[col]}' for col in self.COLUMNS]
        columns_sql = ",\n            ".join(col_defs)
        
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.full_table_name} (
            {columns_sql}
            );
        """
        
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(create_sql)
            conn.commit()
        
        logger.info(f"Created table {self.full_table_name}")
    
    def get_existing_ids(self) -> Set[str]:
        """Get set of all event_id_cnty values for deduplication."""
        query = f"SELECT event_id_cnty FROM {self.full_table_name};"
        
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                ids = {row[0] for row in cur.fetchall()}
        
        logger.info(f"Found {len(ids):,} existing records in {self.full_table_name}")
        return ids
    
    def get_record_count(self) -> int:
        """Get total record count."""
        query = f"SELECT COUNT(*) FROM {self.full_table_name};"
        
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                count = cur.fetchone()[0]
        
        logger.debug(f"Record count: {count:,}")
        return count
    
    def get_latest_timestamp(self) -> Optional[int]:
        """Get most recent timestamp value."""
        query = f"SELECT MAX(timestamp) FROM {self.full_table_name};"
        
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                result = cur.fetchone()[0]
        
        logger.debug(f"Latest timestamp: {result}")
        return result
    
    def bulk_insert(self, df: pd.DataFrame) -> int:
        """
        Bulk insert using PostgreSQL COPY protocol (fastest method).
        
        Args:
            df: DataFrame with columns matching ACLED schema
            
        Returns:
            Number of rows inserted
        """
        if df.empty:
            logger.warning("Empty DataFrame provided")
            return 0
        
        df_ordered = df[self.COLUMNS].copy()
        df_ordered = df_ordered.where(pd.notna(df_ordered), None)
        
        row_count = len(df_ordered)
        logger.info(f"Bulk inserting {row_count:,} rows into {self.full_table_name}")
        
        try:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    columns = ", ".join([f'"{col}"' for col in self.COLUMNS])
                    copy_sql = f"COPY {self.full_table_name} ({columns}) FROM STDIN WITH (FORMAT CSV, NULL '')"
                    
                    buffer = StringIO()
                    df_ordered.to_csv(buffer, index=False, header=False, na_rep='')
                    buffer.seek(0)
                    
                    with cur.copy(copy_sql) as copy:
                        copy.write(buffer.getvalue())
                
                conn.commit()
            
            logger.info(f"Successfully inserted {row_count:,} rows")
            return row_count
            
        except psycopg.Error as e:
            logger.error(f"Bulk insert failed: {e}")
            raise DatabaseError(f"Bulk insert failed: {e}")
    
    def delete_all(self) -> int:
        """Delete all records (TRUNCATE). WARNING: Destructive!"""
        count = self.get_record_count()
        
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {self.full_table_name};")
            conn.commit()
        
        logger.warning(f"Truncated {self.full_table_name}: {count:,} rows deleted")
        return count


class DatabaseError(Exception):
    """Raised when database operations fail."""
    pass
```

---

### `acled_pipeline.py` - Main Pipeline

```python
"""
ACLED Data Pipeline
===================
Main pipeline for syncing ACLED data from API to PostgreSQL.

Two sync modes:
    - quick_sync(): Timestamp-based, fast for daily updates
    - full_sync():  Page iteration, thorough for verification
"""

from datetime import datetime
from typing import Optional, Generator, List

import pandas as pd
import requests

from config import logger
from acled_auth import ACLEDAuth, APIError
from acled_db import ACLEDDatabase

requests.packages.urllib3.disable_warnings()


class ACLEDPipeline:
    """Main ACLED data synchronization pipeline."""
    
    COLUMNS = ACLEDDatabase.COLUMNS
    
    def __init__(self, auth: ACLEDAuth, db: ACLEDDatabase):
        """Initialize with auth and database handlers."""
        self.auth = auth
        self.db = db
        logger.info("ACLEDPipeline initialized")
    
    def fetch_page(self, page: int = 1, limit: int = 5000) -> Optional[pd.DataFrame]:
        """Fetch single page of data from ACLED API."""
        logger.debug(f"Fetching page {page} (limit={limit})")
        
        params = {"limit": min(limit, 5000), "page": page}
        
        try:
            response = self.auth.request("read", params)
            
            if not response.get("data"):
                return None
            
            df = pd.json_normalize(response["data"])
            
            for col in self.COLUMNS:
                if col not in df.columns:
                    df[col] = None
            
            df = df[self.COLUMNS]
            logger.info(f"Page {page}: {len(df):,} records fetched")
            return df
            
        except APIError as e:
            logger.error(f"Failed to fetch page {page}: {e}")
            raise
    
    def fetch_pages(
        self,
        start_page: int = 1,
        end_page: Optional[int] = None,
        limit: int = 5000
    ) -> Generator[pd.DataFrame, None, None]:
        """Generator yielding DataFrames for each page."""
        page = start_page
        
        while True:
            if end_page and page > end_page:
                break
            
            df = self.fetch_page(page=page, limit=limit)
            
            if df is None or df.empty:
                break
            
            yield df
            page += 1
    
    def _insert_batch(self, dfs: list) -> int:
        """Combine DataFrames and bulk insert."""
        if not dfs:
            return 0
        
        combined = pd.concat(dfs, ignore_index=True)
        return self.db.bulk_insert(combined)
    
    def get_status(self) -> dict:
        """Get current database status."""
        count = self.db.get_record_count()
        latest = self.db.get_latest_timestamp()
        
        return {
            "record_count": count,
            "latest_timestamp": latest,
            "latest_date": datetime.fromtimestamp(latest).isoformat() if latest else None,
            "table": self.db.full_table_name
        }
    
    # =========================================================================
    # QUICK SYNC - Timestamp-based (fast, for daily updates)
    # =========================================================================
    
    def quick_sync(
        self,
        batch_size: int = 5000,
        years: Optional[List[int]] = None
    ) -> dict:
        """
        Quick sync using timestamp filtering - fetches only NEW records.
        
        The 'timestamp' field in ACLED indicates when a record was ADDED to
        their database, NOT the event date. This enables efficient incremental sync.
        
        Processes each year as a separate batch for resilience.
        """
        start_time = datetime.now()
        
        logger.info("=" * 60)
        logger.info("ACLED QUICK SYNC Started (timestamp-based)")
        logger.info("=" * 60)
        
        self.auth.get_token()
        
        db_max_ts = self.db.get_latest_timestamp()
        if not db_max_ts:
            logger.warning("Database is empty! Use full_sync() instead.")
            return {"error": "Database empty - use full_sync() for initial load"}
        
        logger.info(f"Database max timestamp: {db_max_ts}")
        logger.info(f"  As datetime: {datetime.fromtimestamp(db_max_ts)}")
        
        if years is None:
            current_year = datetime.now().year
            years = list(range(current_year, current_year - 6, -1))
        
        stats = {
            "mode": "quick_sync",
            "db_max_timestamp": db_max_ts,
            "years_checked": years,
            "records_fetched": 0,
            "records_inserted": 0,
            "records_duplicates": 0,
            "batches_processed": 0,
            "duration_seconds": 0
        }
        
        base_url = "https://acleddata.com/api/acled/read"
        headers = {"Authorization": f"Bearer {self.auth.get_token()}"}
        
        existing_ids = self.db.get_existing_ids()
        logger.info(f"Database has {len(existing_ids):,} existing records")
        
        for year in years:
            # timestamp_where=%3E is URL-encoded ">"
            url = f"{base_url}?limit={batch_size}&year={year}&timestamp={db_max_ts}&timestamp_where=%3E"
            
            logger.info(f"\n--- Processing year {year} ---")
            
            year_records = []
            page = 1
            
            while True:
                page_url = f"{url}&page={page}"
                
                try:
                    response = requests.get(page_url, headers=headers, verify=False, timeout=60)
                    response.raise_for_status()
                    data = response.json()
                    
                    records = data if isinstance(data, list) else data.get("data", [])
                    
                    if not records:
                        break
                    
                    year_records.extend(records)
                    stats["records_fetched"] += len(records)
                    
                    logger.info(f"  Year {year}, page {page}: {len(records)} records")
                    
                    if len(records) < batch_size:
                        break
                    
                    page += 1
                    
                except requests.RequestException as e:
                    logger.error(f"API request failed: {e}")
                    break
            
            if year_records:
                df = pd.json_normalize(year_records)
                
                for col in self.COLUMNS:
                    if col not in df.columns:
                        df[col] = None
                
                df = df[self.COLUMNS]
                
                # Deduplicate
                original_count = len(df)
                df = df[~df["event_id_cnty"].isin(existing_ids)]
                duplicates = original_count - len(df)
                stats["records_duplicates"] += duplicates
                
                if not df.empty:
                    try:
                        inserted = self.db.bulk_insert(df)
                        stats["records_inserted"] += inserted
                        stats["batches_processed"] += 1
                        existing_ids.update(df["event_id_cnty"].tolist())
                        logger.info(f"  ✓ Year {year}: Inserted {inserted:,} records")
                    except Exception as e:
                        logger.error(f"  ✗ Year {year}: Insert failed - {e}")
                        continue
        
        stats["duration_seconds"] = (datetime.now() - start_time).total_seconds()
        
        logger.info("\n" + "=" * 60)
        logger.info("ACLED QUICK SYNC Complete")
        logger.info(f"  Records fetched: {stats['records_fetched']:,}")
        logger.info(f"  Records inserted: {stats['records_inserted']:,}")
        logger.info(f"  Duration: {stats['duration_seconds']:.1f} seconds")
        logger.info("=" * 60)
        
        return stats
    
    # =========================================================================
    # FULL SYNC - Page iteration (complete, thorough)
    # =========================================================================
    
    def full_sync(
        self,
        start_page: int = 1,
        end_page: Optional[int] = None,
        batch_size: int = 20,
        limit: int = 5000,
        deduplicate: bool = True
    ) -> dict:
        """
        Full sync - iterate through ALL API pages with deduplication.
        
        Slower but ensures complete data integrity. Use for:
        - Initial data load
        - Periodic verification
        - Recovery from data gaps
        """
        start_time = datetime.now()
        
        logger.info("=" * 60)
        logger.info("ACLED FULL SYNC Started")
        logger.info("=" * 60)
        
        self.auth.get_token()
        
        existing_ids = self.db.get_existing_ids() if deduplicate else set()
        
        stats = {
            "mode": "full_sync",
            "pages_processed": 0,
            "records_fetched": 0,
            "records_inserted": 0,
            "duration_seconds": 0
        }
        
        batch_dfs = []
        consecutive_no_new = 0
        
        for df in self.fetch_pages(start_page, end_page, limit):
            stats["pages_processed"] += 1
            stats["records_fetched"] += len(df)
            
            if deduplicate and existing_ids:
                new_mask = ~df["event_id_cnty"].isin(existing_ids)
                page_new = new_mask.sum()
                df = df[new_mask]
            else:
                page_new = len(df)
            
            if page_new == 0:
                consecutive_no_new += 1
                if consecutive_no_new >= 3 and deduplicate:
                    logger.info("3 consecutive pages with no new records - stopping")
                    break
            else:
                consecutive_no_new = 0
            
            if not df.empty:
                batch_dfs.append(df)
            
            if len(batch_dfs) >= batch_size:
                inserted = self._insert_batch(batch_dfs)
                stats["records_inserted"] += inserted
                
                if deduplicate:
                    for batch_df in batch_dfs:
                        existing_ids.update(batch_df["event_id_cnty"].tolist())
                
                batch_dfs = []
        
        # Final batch
        if batch_dfs:
            inserted = self._insert_batch(batch_dfs)
            stats["records_inserted"] += inserted
        
        stats["duration_seconds"] = (datetime.now() - start_time).total_seconds()
        
        logger.info("=" * 60)
        logger.info("ACLED FULL SYNC Complete")
        logger.info(f"  Records inserted: {stats['records_inserted']:,}")
        logger.info(f"  Duration: {stats['duration_seconds']:.1f} seconds")
        logger.info("=" * 60)
        
        return stats
    
    # Alias for backward compatibility
    def sync(self, **kwargs) -> dict:
        return self.full_sync(**kwargs)
```

---

### `function_app.py` - Azure Functions Entry Point

```python
"""
ACLED Azure Function App
========================
Azure Functions for automated ACLED data pipeline.

Functions:
    - sync_acled_timer: Daily @ 6AM UTC
    - sync_acled_http: On-demand sync (POST /api/sync)
    - acled_status: Health check (GET /api/status)
"""

import json
import logging
import os

import azure.functions as func

from acled_auth import ACLEDAuth, AuthenticationError
from acled_db import ACLEDDatabase, DatabaseError
from acled_pipeline import ACLEDPipeline

app = func.FunctionApp()


def get_pipeline() -> ACLEDPipeline:
    """Create configured ACLED pipeline from environment variables."""
    auth = ACLEDAuth(
        username=os.environ.get("ACLED_USERNAME"),
        password=os.environ.get("ACLED_PASSWORD")
    )
    
    db = ACLEDDatabase(
        config={
            "host": os.environ.get("DB_HOST"),
            "dbname": os.environ.get("DB_NAME"),
            "user": os.environ.get("DB_USER"),
            "password": os.environ.get("DB_PASSWORD"),
            "port": int(os.environ.get("DB_PORT", 5432))
        },
        schema=os.environ.get("DB_SCHEMA", "ops"),
        table=os.environ.get("DB_TABLE", "acled_new")
    )
    
    return ACLEDPipeline(auth, db)


# =============================================================================
# Timer Trigger - Daily Sync
# =============================================================================

@app.timer_trigger(
    schedule="0 0 6 * * *",  # Daily at 6:00 AM UTC
    arg_name="timer",
    run_on_startup=False
)
def sync_acled_timer(timer: func.TimerRequest) -> None:
    """Daily automated sync of ACLED data."""
    logging.info("ACLED Timer: Starting daily sync")
    
    try:
        pipeline = get_pipeline()
        stats = pipeline.quick_sync()  # Use quick_sync for efficiency
        logging.info(f"ACLED Timer: Complete - {stats['records_inserted']:,} records")
        
    except (AuthenticationError, DatabaseError) as e:
        logging.error(f"ACLED Timer: Failed - {e}")
        raise


# =============================================================================
# HTTP Trigger - Manual Sync
# =============================================================================

@app.route(route="sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def sync_acled_http(req: func.HttpRequest) -> func.HttpResponse:
    """
    On-demand sync endpoint.
    
    POST /api/sync
    Body (optional): {"start_page": 1, "end_page": null, "batch_size": 20}
    """
    logging.info("ACLED HTTP: Manual sync requested")
    
    try:
        body = req.get_json() if req.get_body() else {}
    except ValueError:
        body = {}
    
    try:
        pipeline = get_pipeline()
        stats = pipeline.sync(
            start_page=body.get("start_page", 1),
            end_page=body.get("end_page"),
            batch_size=body.get("batch_size", 20)
        )
        
        return func.HttpResponse(
            json.dumps(stats, indent=2),
            status_code=200,
            mimetype="application/json"
        )
        
    except AuthenticationError as e:
        return func.HttpResponse(
            json.dumps({"error": "Authentication failed", "details": str(e)}),
            status_code=401,
            mimetype="application/json"
        )
        
    except DatabaseError as e:
        return func.HttpResponse(
            json.dumps({"error": "Database error", "details": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# =============================================================================
# HTTP Trigger - Status Check
# =============================================================================

@app.route(route="status", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def acled_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Health check endpoint.
    
    GET /api/status
    Returns: {"record_count": N, "latest_timestamp": T, "latest_date": "...", "table": "..."}
    """
    logging.info("ACLED Status: Checking pipeline")
    
    try:
        pipeline = get_pipeline()
        status = pipeline.get_status()
        
        return func.HttpResponse(
            json.dumps(status, indent=2),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
```

---

## Deployment

### Prerequisites

1. Azure CLI installed and logged in
2. Azure Functions Core Tools installed
3. Python 3.9+ environment

### Steps

```powershell
# 1. Create Azure Function App (if not exists)
az functionapp create \
    --resource-group <your-rg> \
    --consumption-plan-location <region> \
    --runtime python \
    --runtime-version 3.11 \
    --functions-version 4 \
    --name <your-function-app-name> \
    --storage-account <your-storage>

# 2. Configure environment variables
az functionapp config appsettings set \
    --name <your-function-app-name> \
    --resource-group <your-rg> \
    --settings \
    ACLED_USERNAME="<email>" \
    ACLED_PASSWORD="<password>" \
    DB_HOST="<host>" \
    DB_NAME="<dbname>" \
    DB_USER="<user>" \
    DB_PASSWORD="<password>" \
    DB_PORT="5432" \
    DB_SCHEMA="ops" \
    DB_TABLE="acled_new"

# 3. Deploy
func azure functionapp publish <your-function-app-name>
```

### Local Development

```powershell
# Install dependencies
pip install -r requirements.txt

# Run locally
func start
```

---

## Usage

### Jupyter Notebook Usage

```python
from acled_auth import ACLEDAuth
from acled_db import ACLEDDatabase
from acled_pipeline import ACLEDPipeline

# Database config
db_config = {
    "user": "postgres",
    "password": "your-password",
    "host": "your-host",
    "port": 5432,
    "dbname": "your-db"
}

# Initialize pipeline
auth = ACLEDAuth("your-email", "your-password")
db = ACLEDDatabase(db_config, schema="ops", table="acled_new")
pipeline = ACLEDPipeline(auth, db)

# Check status
status = pipeline.get_status()
print(f"Records: {status['record_count']:,}")
print(f"Latest: {status['latest_date']}")

# Quick sync (daily updates)
stats = pipeline.quick_sync()

# Full sync (initial load or verification)
stats = pipeline.full_sync(start_page=1, batch_size=20)
```

### Export to CSV

```python
import psycopg

output_path = r"C:\path\to\acled_export.csv"

with psycopg.connect(**db_config) as conn:
    with conn.cursor() as cur:
        with open(output_path, "wb") as f:
            with cur.copy("COPY ops.acled_new TO STDOUT WITH CSV HEADER") as copy:
                for data in copy:
                    f.write(data)

print(f"Exported to: {output_path}")
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Get record count and latest timestamp |
| `/api/sync` | POST | Trigger manual sync |

---

## Notes

### ACLED API Changes (Dec 2025)

The ACLED API changed several fields from INTEGER to VARCHAR:
- `inter1`: Now returns strings like "State Forces", "Rebel group"
- `inter2`: Now returns strings like "Civilians", "Protesters"  
- `interaction`: Now returns combined strings like "State Forces-Civilians"

Use the `ops.acled_new` table schema (VARCHAR for these fields) for new deployments.

### Timestamp Field

The `timestamp` field indicates when a record was **added to ACLED's database**, NOT the event date. This is crucial for efficient incremental sync - use `quick_sync()` to fetch only records added since the last sync.

### SSL Verification

The code uses `verify=False` for HTTPS requests due to corporate proxy SSL interception. In production, consider configuring proper SSL certificates.
