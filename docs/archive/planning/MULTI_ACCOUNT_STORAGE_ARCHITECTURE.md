# Multi-Account Storage Architecture

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Three-account storage pattern for trust zone separation (Bronze/Silver/SilverExternal)

---

## 🎯 Executive Summary

### The Problem
Single flat storage account (rmhazuregeo) with folder-based organization creates:
- ❌ No security boundaries between untrusted user uploads and trusted processed data
- ❌ Folder permissions workarounds instead of container-level IAM
- ❌ Cannot implement different lifecycle policies per data purpose
- ❌ No path to airgapped external environments

### The Solution
**Three storage accounts with flat namespace containers** (trust zone separation):

```
┌─────────────────────────────────────────────────────────────────┐
│ BRONZE (Untrusted Zone) - rmhgeo-bronze                        │
│ Purpose: Raw user uploads ("unwashed masses dump zone")        │
│ Security: Write-only for users, Read-only for ETL              │
│ Containers: bronze-vectors, bronze-rasters, bronze-misc        │
└─────────────────────────────────────────────────────────────────┘
                               ↓
                       ETL Validation & Processing
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ SILVER (Trusted Zone) - rmhgeo-silver                          │
│ Purpose: Processed data + REST API serving                     │
│ Security: ETL read-write, REST API read-only                   │
│ Containers: silver-cogs, silver-vectors, silver-mosaicjson     │
└─────────────────────────────────────────────────────────────────┘
                               ↓
                       Optional One-Way Sync
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ SILVER EXTERNAL (Airgapped Zone) - rmhgeo-silverext           │
│ Purpose: Replicated data for secure/isolated environment       │
│ Security: No internet access, ETL push-only                    │
│ Containers: silverext-cogs, silverext-vectors, silverext-*     │
└─────────────────────────────────────────────────────────────────┘
```

### Current State (29 OCT 2025)
**All three "accounts" simulated in single `rmhazuregeo` account via container prefixes:**
- `bronze-vectors`, `bronze-rasters` (simulate Bronze account)
- `silver-cogs`, `silver-vectors`, `silver-mosaicjson` (simulate Silver account)
- `silverext-cogs`, `silverext-vectors` (simulate SilverExternal account)

### Future State (When Ready for Production)
**Three separate Azure Storage Accounts:**
- `rmhgeo-bronze` (untrusted VNET, public upload)
- `rmhgeo-silver` (trusted VNET, private)
- `rmhgeo-silverext` (airgapped VNET, no internet)

**Migration:** Just change `account_name` in config → **zero code changes needed**!

---

## 🏗️ Architecture Principles

### 1. Trust Zones vs Data Tiers

**IMPORTANT: This is NOT Bronze→Silver→Gold data lifecycle!**

| Concept | Bronze/Silver/Gold (Data Lifecycle) | Bronze/Silver/SilverExternal (Trust Zones) |
|---------|-------------------------------------|---------------------------------------------|
| **Purpose** | Data maturity stages | Security boundaries |
| **Flow** | Bronze→Silver→Gold (progressive refinement) | Bronze→Silver→SilverExternal (validation + sync) |
| **Example** | Raw CSV → Parquet → Published Dataset | Untrusted Upload → Validated COG → Airgapped Replica |
| **Security** | Same security level | Different security zones |

**Our Architecture:**
- **Bronze** = Untrusted input zone (users can write garbage, malformed files)
- **Silver** = Trusted output zone (ETL validated, served to APIs)
- **SilverExternal** = Airgapped replica (one-way sync for secure environments)

### 2. Network Boundaries (Future State)

```
Internet
   ↓
┌─────────────────┐
│ BRONZE (Public) │ ← Users upload via HTTPS
│ rmhgeo-bronze   │ ← Write-only access
└────────┬────────┘
         ↓ (ETL reads via private endpoint)
┌─────────────────┐
│ SILVER (Private)│ ← ETL writes
│ rmhgeo-silver   │ ← REST APIs read
└────────┬────────┘
         ↓ (One-way sync via private endpoint)
┌─────────────────┐
│ SILVEREXT (Air  │ ← No internet access
│ gapped VNET)    │ ← Push-only from Silver
│ rmhgeo-silverext│
└─────────────────┘
```

### 3. Flat Namespace Benefits

**Why Containers Instead of Folders?**

| Feature | Folders (ADLS Gen2) | Containers (Flat) |
|---------|---------------------|-------------------|
| **Permissions** | Complex ACLs | Native IAM at container level |
| **Lifecycle Policies** | Not supported | Container-level policies |
| **Monitoring** | Folder-level metrics hard | Native container metrics |
| **Cost** | +$0.065/TB/month overhead | No overhead |
| **List Performance** | Recursive traversal slow | Fast container-level listing |
| **Backup/Replication** | Complex folder sync | Simple container copy |
| **Azure Native** | ADLS Gen2 lock-in | Standard blob storage |

**Container Naming Convention:**
```
{zone}-{purpose}

Examples:
- bronze-vectors     (Bronze zone, vector data)
- silver-cogs        (Silver zone, Cloud Optimized GeoTIFFs)
- silverext-vectors  (SilverExternal zone, vectors)
```

---

## 📐 Configuration Architecture

### Storage Account Configuration Model

```python
# config.py

from pydantic import BaseModel, Field
from typing import Optional

class StorageAccountConfig(BaseModel):
    """
    Configuration for a single storage account with purpose-specific containers.

    Design: Currently all three "accounts" use rmhazuregeo, but container
    names are prefixed to simulate separation (bronze-*, silver-*, silverext-*).

    Future: Each account will be a separate Azure Storage Account with
    independent networking, access policies, and lifecycle rules.
    """
    account_name: str = Field(
        description="Azure Storage Account name"
    )

    container_prefix: str = Field(
        description="Prefix for containers in this account (e.g., 'bronze', 'silver')"
    )

    # Purpose-specific containers (flat namespace within account)
    vectors: str = Field(description="Vector data container (Shapefiles, GeoJSON, GeoPackage)")
    rasters: str = Field(description="Raster data container (GeoTIFF, raw rasters)")
    cogs: str = Field(description="Cloud Optimized GeoTIFFs (analysis + visualization tiers)")
    tiles: str = Field(description="Raster tiles (temporary or permanent)")
    mosaicjson: str = Field(description="MosaicJSON metadata files")
    stac_assets: str = Field(description="STAC asset files (thumbnails, metadata)")
    misc: str = Field(description="Miscellaneous files (logs, reports)")
    temp: str = Field(description="Temporary processing files (auto-cleanup)")

    # Optional: Connection override (for airgapped external)
    connection_string: Optional[str] = Field(
        default=None,
        description="Override connection string for isolated networks"
    )

    def get_container(self, purpose: str) -> str:
        """
        Get fully qualified container name.

        Args:
            purpose: Data purpose (vectors, rasters, cogs, tiles, etc.)

        Returns:
            Container name with account prefix

        Example:
            bronze_account.get_container("vectors") → "bronze-vectors"
            silver_account.get_container("cogs") → "silver-cogs"

        Raises:
            ValueError: If purpose is unknown
        """
        if not hasattr(self, purpose):
            raise ValueError(
                f"Unknown container purpose: {purpose}. "
                f"Valid options: vectors, rasters, cogs, tiles, mosaicjson, "
                f"stac_assets, misc, temp"
            )
        return getattr(self, purpose)


class MultiAccountStorageConfig(BaseModel):
    """
    Multi-account storage configuration for trust zones.

    Current State (29 OCT 2025):
    - All three "accounts" use rmhazuregeo storage account
    - Containers are prefixed to simulate account separation:
      - bronze-vectors, bronze-rasters (simulates Bronze account)
      - silver-cogs, silver-vectors (simulates Silver account)
      - silverext-cogs, silverext-vectors (simulates SilverExternal account)

    Future State (When Ready for Production):
    - Bronze: Separate storage account (rmhgeo-bronze) in untrusted VNET
    - Silver: Separate storage account (rmhgeo-silver) in trusted VNET
    - SilverExternal: Separate storage account in airgapped VNET (no internet)

    Migration Path:
    - Change bronze.account_name to new account → zero code changes
    - Change silver.account_name to new account → zero code changes
    - Container names stay the same (bronze-vectors, silver-cogs, etc.)
    """

    # BRONZE: Untrusted raw data zone
    bronze: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name="rmhazuregeo",  # CURRENT: Shared account
            # account_name="rmhgeo-bronze",  # FUTURE: Separate account
            container_prefix="bronze",
            vectors="bronze-vectors",
            rasters="bronze-rasters",
            misc="bronze-misc",
            temp="bronze-temp",
            # Not used in Bronze (no processed outputs):
            cogs="bronze-notused",
            tiles="bronze-notused",
            mosaicjson="bronze-notused",
            stac_assets="bronze-notused"
        )
    )

    # SILVER: Trusted processed data + REST API serving
    silver: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name="rmhazuregeo",  # CURRENT: Shared account
            # account_name="rmhgeo-silver",  # FUTURE: Separate account
            container_prefix="silver",
            vectors="silver-vectors",
            rasters="silver-rasters",
            cogs="silver-cogs",
            tiles="silver-tiles",
            mosaicjson="silver-mosaicjson",
            stac_assets="silver-stac-assets",
            misc="silver-misc",
            temp="silver-temp"
        )
    )

    # SILVER EXTERNAL: Airgapped secure environment replica
    silverext: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name="rmhazuregeo",  # CURRENT: Shared account (not used yet)
            # account_name="rmhgeo-silverext",  # FUTURE: External airgapped account
            container_prefix="silverext",
            vectors="silverext-vectors",
            rasters="silverext-rasters",
            cogs="silverext-cogs",
            tiles="silverext-tiles",
            mosaicjson="silverext-mosaicjson",
            stac_assets="silverext-stac-assets",
            misc="silverext-misc",
            temp="silverext-temp",
            # Optional: Connection string for airgapped network
            connection_string=None  # Set when deploying to external environment
        )
    )

    def get_account(self, zone: str) -> StorageAccountConfig:
        """
        Get storage account config by trust zone.

        Args:
            zone: Trust zone ("bronze", "silver", "silverext")

        Returns:
            StorageAccountConfig for that zone

        Example:
            storage.get_account("bronze").get_container("vectors")
            → "bronze-vectors"

        Raises:
            ValueError: If zone is unknown
        """
        if zone == "bronze":
            return self.bronze
        elif zone == "silver":
            return self.silver
        elif zone == "silverext":
            return self.silverext
        else:
            raise ValueError(
                f"Unknown storage zone: {zone}. "
                f"Valid options: bronze, silver, silverext"
            )


class AppConfig(BaseSettings):
    """Application configuration with multi-account storage."""

    # Multi-account storage configuration
    storage: MultiAccountStorageConfig = Field(
        default_factory=MultiAccountStorageConfig,
        description="Multi-account storage configuration for trust zones"
    )

    # DEPRECATED: Old single-account fields (backward compatibility)
    bronze_container_name: str = Field(
        default="rmhazuregeobronze",
        deprecated=True,
        description="DEPRECATED: Use storage.bronze.get_container('rasters') instead"
    )

    silver_container_name: str = Field(
        default="rmhazuregeosilver",
        deprecated=True,
        description="DEPRECATED: Use storage.silver.get_container('cogs') instead"
    )

    gold_container_name: str = Field(
        default="rmhazuregeogold",
        deprecated=True,
        description="DEPRECATED: Gold tier not used in trust zone pattern"
    )
```

### Usage Examples

```python
from config import get_config

config = get_config()

# Access Bronze containers
bronze_vectors = config.storage.bronze.get_container("vectors")
# → "bronze-vectors"

bronze_rasters = config.storage.bronze.get_container("rasters")
# → "bronze-rasters"

# Access Silver containers
silver_cogs = config.storage.silver.get_container("cogs")
# → "silver-cogs"

silver_mosaicjson = config.storage.silver.get_container("mosaicjson")
# → "silver-mosaicjson"

# Access SilverExternal containers (future)
ext_cogs = config.storage.silverext.get_container("cogs")
# → "silverext-cogs"

# Get account by zone
bronze_account = config.storage.get_account("bronze")
print(bronze_account.account_name)  # → "rmhazuregeo" (current)
print(bronze_account.vectors)       # → "bronze-vectors"
```

---

## 🔧 BlobRepository Multi-Account Implementation

### Multi-Instance Singleton Pattern

**Problem:** Need separate connection pools for Bronze/Silver/SilverExternal accounts.

**Solution:** One singleton instance **per storage account** (not globally singular).

```python
# infrastructure/blob.py

class BlobRepository(IBlobRepository):
    """
    Multi-account blob repository with trust zone awareness.

    Supports three storage accounts (currently simulated in one):
    - Bronze: Untrusted raw data
    - Silver: Trusted processed data + API serving
    - SilverExternal: Airgapped secure environment

    Design: Multi-instance singleton - one instance per storage account.
    This allows separate connection pools for each trust zone.
    """

    _instances: Dict[str, 'BlobRepository'] = {}  # One instance per account

    def __new__(cls, account_name: str = None, *args, **kwargs):
        """
        Multi-account singleton pattern.

        Creates one singleton instance PER storage account.
        This allows separate connection pools for Bronze/Silver/SilverExternal.

        Args:
            account_name: Storage account name (defaults to Silver)

        Returns:
            BlobRepository singleton for that account
        """
        if account_name is None:
            from config import get_config
            account_name = get_config().storage.silver.account_name  # Default to Silver

        if account_name not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[account_name] = instance

        return cls._instances[account_name]

    def __init__(self, account_name: str = None, connection_string: Optional[str] = None):
        """
        Initialize blob repository for specific storage account.

        Args:
            account_name: Storage account name (defaults to Silver)
            connection_string: Optional connection string for airgapped accounts
        """
        # Prevent re-initialization of existing instance
        if hasattr(self, '_initialized') and self._initialized:
            return

        from config import get_config
        config = get_config()

        # Determine which account we're connecting to
        self.account_name = account_name or config.storage.silver.account_name

        # Use connection string if provided (for airgapped SilverExternal)
        if connection_string:
            logger.info(f"Initializing BlobRepository with connection string for {self.account_name}")
            self.blob_service = BlobServiceClient.from_connection_string(connection_string)
        else:
            # Use DefaultAzureCredential (for Bronze/Silver)
            self.account_url = f"https://{self.account_name}.blob.core.windows.net"
            logger.info(f"Initializing BlobRepository with DefaultAzureCredential for {self.account_name}")
            self.credential = DefaultAzureCredential()
            self.blob_service = BlobServiceClient(
                account_url=self.account_url,
                credential=self.credential
            )

        # Cache container clients
        self._container_clients: Dict[str, ContainerClient] = {}

        # Pre-cache containers for THIS account
        self._pre_cache_containers(config)

        self._initialized = True
        logger.info(f"✅ BlobRepository initialized for account: {self.account_name}")

    def _pre_cache_containers(self, config: AppConfig):
        """
        Pre-cache container clients based on account name.

        Determines which trust zone (bronze/silver/silverext) this instance
        represents and caches appropriate containers.
        """
        # Determine which account we are
        if self.account_name == config.storage.bronze.account_name:
            zone_config = config.storage.bronze
            logger.debug("Pre-caching BRONZE containers")
        elif self.account_name == config.storage.silver.account_name:
            zone_config = config.storage.silver
            logger.debug("Pre-caching SILVER containers")
        elif self.account_name == config.storage.silverext.account_name:
            zone_config = config.storage.silverext
            logger.debug("Pre-caching SILVER EXTERNAL containers")
        else:
            logger.warning(f"Unknown account {self.account_name}, skipping pre-cache")
            return

        # Cache all containers for this zone
        containers_to_cache = [
            zone_config.vectors,
            zone_config.rasters,
            zone_config.cogs,
            zone_config.tiles,
            zone_config.mosaicjson,
            zone_config.stac_assets,
            zone_config.misc,
            zone_config.temp
        ]

        for container in containers_to_cache:
            if "notused" in container:
                continue  # Skip unused containers (e.g., bronze-cogs)

            try:
                self._get_container_client(container)
                logger.debug(f"Pre-cached container: {container}")
            except Exception as e:
                logger.warning(f"Could not pre-cache container {container}: {e}")

    @classmethod
    def for_zone(cls, zone: str) -> 'BlobRepository':
        """
        Get BlobRepository instance for a trust zone.

        This is the RECOMMENDED factory method for multi-account access.

        Args:
            zone: Trust zone ("bronze", "silver", "silverext")

        Returns:
            BlobRepository connected to that zone's storage account

        Example:
            # ETL reads from Bronze
            bronze_repo = BlobRepository.for_zone("bronze")
            raw_data = bronze_repo.read_blob("bronze-rasters", "user_upload.tif")

            # ETL writes to Silver
            silver_repo = BlobRepository.for_zone("silver")
            silver_repo.write_blob("silver-cogs", "processed.tif", cog_data)

            # Future: Sync to SilverExternal
            ext_repo = BlobRepository.for_zone("silverext")
            ext_repo.write_blob("silverext-cogs", "processed.tif", cog_data)
        """
        from config import get_config
        config = get_config()

        zone_config = config.storage.get_account(zone)

        return cls(
            account_name=zone_config.account_name,
            connection_string=zone_config.connection_string
        )
```

### Factory Pattern Update

```python
# infrastructure/factory.py

class RepositoryFactory:
    """Repository factory with multi-account support."""

    @staticmethod
    def create_blob_repository(zone: str = "silver") -> BlobRepository:
        """
        Create blob repository for specific trust zone.

        Args:
            zone: Trust zone ("bronze", "silver", "silverext")
                  Default: "silver" (backward compatible)

        Returns:
            BlobRepository singleton for that zone

        Example:
            # ETL reads from Bronze
            bronze_repo = RepositoryFactory.create_blob_repository("bronze")
            data = bronze_repo.read_blob("bronze-rasters", "user_upload.tif")

            # ETL writes to Silver
            silver_repo = RepositoryFactory.create_blob_repository("silver")
            silver_repo.write_blob("silver-cogs", "processed.tif", cog_data)

            # Future: ETL syncs to SilverExternal
            ext_repo = RepositoryFactory.create_blob_repository("silverext")
            ext_repo.write_blob("silverext-cogs", "processed.tif", cog_data)
        """
        return BlobRepository.for_zone(zone)

    # Backward compatibility
    @staticmethod
    def create_repositories() -> Dict[str, Any]:
        """
        Create all repositories (backward compatible).

        Returns dict with 'blob_repo' defaulting to Silver zone.
        """
        return {
            'job_repo': JobRepository(...),
            'task_repo': TaskRepository(...),
            'blob_repo': BlobRepository.for_zone("silver")  # Default to Silver
        }
```

---

## 💼 Job & Handler Patterns

### Job Parameter Pattern (Multi-Zone Aware)

```python
# jobs/process_raster.py

class ProcessRasterJob(JobBase):
    """
    Process raster from Bronze → Silver (with optional SilverExternal sync).

    Data Flow:
    1. Read raw raster from Bronze (untrusted zone)
    2. Validate and extract tiles
    3. Convert to COG in Silver (trusted zone)
    4. Optionally sync to SilverExternal (airgapped zone)
    """

    job_type: str = "process_raster"

    stages: List[Dict[str, Any]] = [
        {"number": 1, "name": "validate", "task_type": "validate_raster", "parallelism": "single"},
        {"number": 2, "name": "tiling_scheme", "task_type": "generate_tiling_scheme", "parallelism": "single"},
        {"number": 3, "name": "extract_tiles", "task_type": "extract_tile", "parallelism": "fan_out"},
        {"number": 4, "name": "create_cogs", "task_type": "create_cog", "parallelism": "fan_out"}
    ]

    @staticmethod
    def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
        from config import get_config
        config = get_config()

        if stage == 1:
            # Stage 1: Validate raster in BRONZE (untrusted zone)
            return [{
                "task_id": f"{job_id[:8]}-s1-validate",
                "task_type": "validate_raster",
                "parameters": {
                    # Trust zone (not just container name!)
                    "source_zone": "bronze",

                    # Container from config
                    "source_container": config.storage.bronze.get_container("rasters"),

                    # Blob path
                    "blob_name": job_params["blob_name"]
                }
            }]

        elif stage == 2:
            # Stage 2: Generate tiling scheme (read from Bronze)
            return [{
                "task_id": f"{job_id[:8]}-s2-tiling",
                "task_type": "generate_tiling_scheme",
                "parameters": {
                    "source_zone": "bronze",
                    "source_container": config.storage.bronze.rasters,
                    "blob_name": job_params["blob_name"]
                }
            }]

        elif stage == 3:
            # Stage 3: Extract tiles → SILVER temp (trusted zone)
            tiles = previous_results[0]["result"]["tiles"]
            return [
                {
                    "task_id": f"{job_id[:8]}-s3-tile-{tile['x']}-{tile['y']}",
                    "task_type": "extract_tile",
                    "parameters": {
                        # Input from Bronze
                        "source_zone": "bronze",
                        "source_container": config.storage.bronze.rasters,

                        # Output to Silver temp
                        "output_zone": "silver",
                        "output_container": config.storage.silver.temp,

                        "tile": tile,
                        "blob_name": job_params["blob_name"]
                    }
                }
                for tile in tiles
            ]

        elif stage == 4:
            # Stage 4: Convert tiles to COGs → SILVER cogs (final output)
            tiles = previous_results  # All tile results from Stage 3
            return [
                {
                    "task_id": f"{job_id[:8]}-s4-cog-{i}",
                    "task_type": "create_cog",
                    "parameters": {
                        # Input from Silver temp
                        "source_zone": "silver",
                        "source_container": config.storage.silver.temp,

                        # Output to Silver cogs (REST API serving)
                        "output_zone": "silver",
                        "output_container": config.storage.silver.cogs,

                        "tile_path": tile["result"]["temp_path"],

                        # Optional: Sync to external (future enhancement)
                        "sync_to_external": job_params.get("sync_external", False)
                    }
                }
                for i, tile in enumerate(tiles)
            ]
```

### Handler Pattern (Multi-Zone Read/Write)

```python
# services/raster_cog.py

def create_cog(params: dict) -> dict:
    """
    Create COG from tile (Bronze → Silver, optionally → SilverExternal).

    Data Flow:
    1. Read tile from Silver temp (already extracted from Bronze)
    2. Process to COG in-memory (/vsimem/ pattern)
    3. Write to Silver cogs (REST API serving)
    4. Optionally sync to SilverExternal (airgapped replica)
    """
    from infrastructure.factory import RepositoryFactory
    from config import get_config

    config = get_config()

    # Get repository for source zone
    source_zone = params["source_zone"]  # "silver"
    source_repo = RepositoryFactory.create_blob_repository(source_zone)

    # Read tile from Silver temp
    source_container = params["source_container"]  # "silver-temp"
    temp_data = source_repo.read_blob(source_container, params["tile_path"])

    # Process to COG (in-memory /vsimem/ pattern - 30-40% faster)
    cog_data = process_to_cog_vsimem(temp_data)

    # Write to Silver COGs (REST API serving)
    output_zone = params["output_zone"]  # "silver"
    output_repo = RepositoryFactory.create_blob_repository(output_zone)
    output_container = params["output_container"]  # "silver-cogs"
    cog_path = f"cogs/{params['tile_path']}"

    output_repo.write_blob(output_container, cog_path, cog_data)
    logger.info(f"✅ Wrote COG to {output_zone}: {output_container}/{cog_path}")

    # OPTIONAL: Sync to SilverExternal (future enhancement)
    synced_external = False
    if params.get("sync_to_external", False):
        ext_repo = RepositoryFactory.create_blob_repository("silverext")
        ext_container = config.storage.silverext.cogs  # "silverext-cogs"

        ext_repo.write_blob(ext_container, cog_path, cog_data)
        synced_external = True

        logger.info(f"✅ Synced to external: {ext_container}/{cog_path}")

    return {
        "success": True,
        "cog_path": cog_path,
        "zone": output_zone,
        "container": output_container,
        "synced_external": synced_external
    }


def process_to_cog_vsimem(input_data: bytes) -> bytes:
    """
    Process raster tile to COG using /vsimem/ in-memory pattern.

    Pattern:
    1. Download → /vsimem/ (in-memory)
    2. Process → /vsimem/ (in-memory)
    3. Upload from /vsimem/
    4. Cleanup with gdal.Unlink()

    Benefits:
    - 30-40% faster than /vsiaz/ direct access
    - Zero /tmp disk usage (critical for Azure Functions)
    - Memory leak prevention via explicit cleanup
    """
    from osgeo import gdal
    import uuid

    # Generate unique /vsimem/ paths
    input_vsimem = f"/vsimem/input_{uuid.uuid4().hex}.tif"
    output_vsimem = f"/vsimem/output_{uuid.uuid4().hex}.tif"

    try:
        # Write input to /vsimem/
        gdal.FileFromMemBuffer(input_vsimem, input_data)

        # Open input
        src_ds = gdal.Open(input_vsimem)

        # Translate to COG with options
        gdal.Translate(
            output_vsimem,
            src_ds,
            format="COG",
            creationOptions=[
                "COMPRESS=DEFLATE",
                "BLOCKSIZE=512",
                "OVERVIEWS=AUTO"
            ]
        )

        src_ds = None  # Close dataset

        # Read output from /vsimem/
        vsi_file = gdal.VSIFOpenL(output_vsimem, 'rb')
        gdal.VSIFSeekL(vsi_file, 0, 2)  # Seek to end
        size = gdal.VSIFTellL(vsi_file)
        gdal.VSIFSeekL(vsi_file, 0, 0)  # Seek to start
        output_data = gdal.VSIFReadL(1, size, vsi_file)
        gdal.VSIFCloseL(vsi_file)

        return output_data

    finally:
        # Critical: Cleanup /vsimem/ to prevent memory leaks
        gdal.Unlink(input_vsimem)
        gdal.Unlink(output_vsimem)
```

---

## 🚀 Migration Guide

### Phase 1: Add Configuration (Zero Breaking Changes)

**Step 1: Update config.py**

Add `StorageAccountConfig`, `MultiAccountStorageConfig` models (see Configuration Architecture section above).

**Step 2: Keep deprecated fields**

```python
class AppConfig(BaseSettings):
    # NEW
    storage: MultiAccountStorageConfig = Field(default_factory=MultiAccountStorageConfig)

    # OLD (deprecated but functional)
    bronze_container_name: str = Field(default="rmhazuregeobronze", deprecated=True)
    silver_container_name: str = Field(default="rmhazuregeosilver", deprecated=True)
```

**Result:** All existing code continues to work.

---

### Phase 2: Create Containers in Azure

**Create new containers with standardized names:**

```bash
# Bronze containers (untrusted zone)
az storage container create --name bronze-vectors --account-name rmhazuregeo
az storage container create --name bronze-rasters --account-name rmhazuregeo
az storage container create --name bronze-misc --account-name rmhazuregeo
az storage container create --name bronze-temp --account-name rmhazuregeo

# Silver containers (trusted zone)
az storage container create --name silver-vectors --account-name rmhazuregeo
az storage container create --name silver-rasters --account-name rmhazuregeo
az storage container create --name silver-cogs --account-name rmhazuregeo
az storage container create --name silver-tiles --account-name rmhazuregeo
az storage container create --name silver-mosaicjson --account-name rmhazuregeo
az storage container create --name silver-stac-assets --account-name rmhazuregeo
az storage container create --name silver-misc --account-name rmhazuregeo
az storage container create --name silver-temp --account-name rmhazuregeo

# SilverExternal containers (airgapped zone - placeholder for future)
az storage container create --name silverext-vectors --account-name rmhazuregeo
az storage container create --name silverext-cogs --account-name rmhazuregeo
az storage container create --name silverext-mosaicjson --account-name rmhazuregeo
```

**Verify containers:**

```bash
az storage container list --account-name rmhazuregeo --output table
```

---

### Phase 3: Update BlobRepository

**Update infrastructure/blob.py:**
1. Change singleton to multi-instance (one per account)
2. Add `for_zone(zone)` class method
3. Update pre-caching logic to use `config.storage`

See BlobRepository Multi-Account Implementation section above for full code.

---

### Phase 4: Update Jobs & Handlers

**Update job parameter schemas:**

```python
# OLD pattern
{
    "blob_name": "17apr2024wv2.tif",
    "container": "rmhazuregeobronze"  # Ambiguous
}

# NEW pattern
{
    "blob_name": "17apr2024wv2.tif",
    "source_zone": "bronze",  # Explicit trust zone
    "source_container": config.storage.bronze.rasters  # "bronze-rasters"
}
```

**Update handlers to use zone-aware repositories:**

```python
# OLD
blob_repo = RepositoryFactory.create_blob_repository()
data = blob_repo.read_blob("rmhazuregeobronze", path)

# NEW
bronze_repo = RepositoryFactory.create_blob_repository("bronze")
data = bronze_repo.read_blob("bronze-rasters", path)
```

---

### Phase 5: Testing Strategy

**Test with simulated three-account setup:**

```python
# All tests pass with single rmhazuregeo account
# (containers are prefixed to simulate separation)

def test_bronze_to_silver_etl():
    """Test ETL flow: Bronze → Silver"""
    from infrastructure.factory import RepositoryFactory
    from config import get_config

    config = get_config()

    # Write test file to Bronze
    bronze_repo = RepositoryFactory.create_blob_repository("bronze")
    bronze_repo.write_blob(
        config.storage.bronze.rasters,
        "test.tif",
        b"fake raster data"
    )

    # Read from Bronze, write to Silver
    silver_repo = RepositoryFactory.create_blob_repository("silver")
    data = bronze_repo.read_blob(config.storage.bronze.rasters, "test.tif")
    silver_repo.write_blob(
        config.storage.silver.cogs,
        "test_cog.tif",
        data
    )

    # Verify
    assert silver_repo.blob_exists(config.storage.silver.cogs, "test_cog.tif")
```

---

### Phase 6: Future - Separate Storage Accounts

**When ready for production:**

1. **Create separate storage accounts:**
```bash
az storage account create --name rmhgeo-bronze --resource-group rmhazure_rg
az storage account create --name rmhgeo-silver --resource-group rmhazure_rg
az storage account create --name rmhgeo-silverext --resource-group rmhazure_rg
```

2. **Update config (ONLY config change needed!):**
```python
bronze: StorageAccountConfig = Field(
    default_factory=lambda: StorageAccountConfig(
        account_name="rmhgeo-bronze",  # ← CHANGE THIS LINE ONLY
        container_prefix="bronze",
        # ... rest unchanged
    )
)
```

3. **Migrate data:**
```bash
# AzCopy container-to-container copy
azcopy copy \
  "https://rmhazuregeo.blob.core.windows.net/bronze-rasters" \
  "https://rmhgeo-bronze.blob.core.windows.net/bronze-rasters" \
  --recursive
```

4. **Zero code changes needed!** All jobs and handlers use config.

---

## 🔒 Security & Access Patterns

### Container-Level IAM Policies

**Bronze (Untrusted Zone):**
```
Users:
- Write-only (upload raw data)
- No read access (privacy)

ETL:
- Read-only
- No delete (audit trail)

REST APIs:
- No access
```

**Silver (Trusted Zone):**
```
Users:
- No access

ETL:
- Read-write (process data)
- Delete temp containers only

REST APIs:
- Read-only (serve data)
```

**SilverExternal (Airgapped Zone):**
```
Users:
- No access

ETL:
- Write-only (one-way sync)
- No delete (immutable)

REST APIs:
- Read-only (in airgapped environment only)
```

### Lifecycle Policies (Per Container)

```python
# Example lifecycle policies

# Bronze: Archive to Cool tier after 90 days
bronze_policy = {
    "rules": [{
        "name": "ArchiveBronzeData",
        "type": "Lifecycle",
        "definition": {
            "filters": {"blobTypes": ["blockBlob"]},
            "actions": {
                "baseBlob": {
                    "tierToCool": {"daysAfterModificationGreaterThan": 90}
                }
            }
        }
    }]
}

# Silver temp: Auto-delete after 7 days
silver_temp_policy = {
    "rules": [{
        "name": "DeleteTempFiles",
        "type": "Lifecycle",
        "definition": {
            "filters": {
                "blobTypes": ["blockBlob"],
                "prefixMatch": ["silver-temp/"]
            },
            "actions": {
                "baseBlob": {
                    "delete": {"daysAfterModificationGreaterThan": 7}
                }
            }
        }
    }]
}
```

---

## 📊 Container Organization Reference

### Container Naming Convention

```
{zone}-{purpose}

Zones:
- bronze     (untrusted input)
- silver     (trusted output)
- silverext  (airgapped replica)

Purposes:
- vectors       (Shapefiles, GeoJSON, GeoPackage)
- rasters       (GeoTIFF, raw rasters)
- cogs          (Cloud Optimized GeoTIFFs)
- tiles         (Raster tiles)
- mosaicjson    (MosaicJSON metadata)
- stac-assets   (STAC thumbnails, metadata)
- misc          (Logs, reports)
- temp          (Temporary files with auto-cleanup)
```

### Complete Container List

| Container | Zone | Purpose | Lifecycle | Access |
|-----------|------|---------|-----------|--------|
| `bronze-vectors` | Bronze | Raw vector uploads | Archive 90d | Users: W, ETL: R |
| `bronze-rasters` | Bronze | Raw raster uploads | Archive 90d | Users: W, ETL: R |
| `bronze-misc` | Bronze | Other raw files | Archive 90d | Users: W, ETL: R |
| `bronze-temp` | Bronze | Temp user uploads | Delete 7d | Users: W, ETL: R |
| `silver-vectors` | Silver | Processed vectors (PostGIS sync) | Keep Hot | ETL: RW, API: R |
| `silver-rasters` | Silver | Validated rasters | Keep Hot | ETL: RW, API: R |
| `silver-cogs` | Silver | Cloud Optimized GeoTIFFs | Keep Hot | ETL: RW, API: R |
| `silver-tiles` | Silver | Raster tiles | Keep Hot | ETL: RW, API: R |
| `silver-mosaicjson` | Silver | MosaicJSON metadata | Keep Hot | ETL: RW, API: R |
| `silver-stac-assets` | Silver | STAC thumbnails | Keep Hot | ETL: RW, API: R |
| `silver-misc` | Silver | Logs, reports | Archive 30d | ETL: RW |
| `silver-temp` | Silver | Processing temp files | Delete 7d | ETL: RW |
| `silverext-cogs` | SilverExternal | COG replicas | Keep Hot | ETL: W, API: R (ext) |
| `silverext-vectors` | SilverExternal | Vector replicas | Keep Hot | ETL: W, API: R (ext) |
| `silverext-mosaicjson` | SilverExternal | MosaicJSON replicas | Keep Hot | ETL: W, API: R (ext) |

---

## 🎓 Key Takeaways

### Why This Architecture?

1. **Trust Zone Separation** - Bronze (untrusted) vs Silver (trusted) vs SilverExternal (airgapped)
2. **Container-Level Security** - Native IAM, not folder ACL workarounds
3. **Flat Namespace Performance** - Fast listing, no recursive traversal
4. **Future-Proof** - Config-driven account separation (zero code changes)
5. **Azure Native** - Standard blob storage, not ADLS Gen2 lock-in

### Migration Benefits

✅ **Zero Breaking Changes** - Deprecated fields work during transition
✅ **Gradual Migration** - Update jobs one-by-one at your own pace
✅ **Testable** - Simulated three-account setup in single account
✅ **Reversible** - Can rollback to old pattern if needed
✅ **Clear Path** - Documented steps from current to future state

### Common Pitfalls to Avoid

❌ **Folder thinking** - Containers are NOT folders, use container-level organization
❌ **ADLS Gen2** - Adds cost and complexity, use standard blob storage
❌ **Hardcoded containers** - Always use `config.storage.{zone}.get_container(purpose)`
❌ **Single repository** - Use `RepositoryFactory.create_blob_repository(zone)` for multi-account
❌ **Premature account separation** - Test thoroughly with simulated setup first

---

## 📚 Related Documentation

- [COREMACHINE_PLATFORM_ARCHITECTURE.md](docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md) - Two-layer architecture
- [SERVICE_BUS_HARMONIZATION.md](docs_claude/SERVICE_BUS_HARMONIZATION.md) - Three-layer config architecture
- [ARCHITECTURE_REFERENCE.md](docs_claude/ARCHITECTURE_REFERENCE.md) - Deep technical specifications
- [config.py](config.py) - Configuration implementation
- [infrastructure/blob.py](infrastructure/blob.py) - BlobRepository implementation
- [infrastructure/factory.py](infrastructure/factory.py) - Repository factory

---

**Last Updated**: 29 OCT 2025
**Status**: Approved for implementation (simulated three-account setup)
**Next Steps**: Implement config changes, create containers, update BlobRepository
