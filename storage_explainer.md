# Geospatial Data Storage Architecture: Versioning and Release Management

## Overview

This document clarifies the distinction between infrastructure-level storage features and application-level data management, with specific guidance on patterns appropriate for cloud-native geospatial systems.

---

## Storage-Level Features

### Blob Versioning

**What it is:** A storage account setting that automatically preserves previous versions of blobs when overwritten or deleted.

**Availability:** Standard Blob Storage and ADLS Gen2 (does not require hierarchical namespace)

**Appropriate uses:**
- Recovery from accidental deletion or overwrite
- Compliance requirements for point-in-time file state verification
- Safety net during ETL development and testing

**Not appropriate for:**
- Tracking semantic dataset releases (v1.0, v2.0, v2.1)
- Understanding what changed between versions (only captures that bytes differ)
- Concurrent editing workflows
- Release management or data governance

**Cost consideration:** Storage costs accrue for every historical version retained.

---

### Soft Delete

**What it is:** A retention period during which deleted blobs can be recovered before permanent deletion.

**Appropriate uses:**
- Grace period for accidental deletion recovery
- Additional safety layer for compliance

**Not appropriate for:**
- Version control
- Release management
- Audit trails with business context

---

### Snapshots

**What it is:** Manually-triggered, point-in-time read-only copies of blobs.

**Appropriate uses:**
- Backup before high-risk operations
- Preserving known-good state during migrations

**Not appropriate for:**
- Automated version tracking
- Release management
- Change auditing

---

## Azure Data Lake Storage Gen2 (ADLS Gen2)

### What It Is

ADLS Gen2 is Azure GPv2 Blob Storage with Hierarchical Namespace (HNS) enabled. That is the primary technical distinction. Same storage infrastructure, same redundancy options, same blob types, same pricing model.

| Feature | GPv2 Standard Blob | ADLS Gen2 (GPv2 + HNS) |
|---------|-------------------|------------------------|
| Blob versioning | ✓ | ✓ |
| Soft delete | ✓ | ✓ |
| Lifecycle management | ✓ | ✓ |
| RBAC | ✓ | ✓ |
| Hierarchical Namespace | ✗ | ✓ |
| POSIX ACLs | ✗ | ✓ |
| Atomic directory operations | ✗ | ✓ |

---

### Hierarchical Namespace (HNS)

**What it is:** A storage account configuration that enables true directory operations. With HNS, directories are real objects rather than virtual prefixes.

**Appropriate uses:**
- Atomic directory operations (rename a folder without corrupting state mid-operation)
- Improved performance for analytics engines (Spark, Databricks) that list and scan many files
- Workloads that require filesystem semantics for compatibility

**Not appropriate for:**
- HTTP-based API serving (no performance benefit)
- CDN-cached content delivery
- Workloads that access individual blobs by direct URL
- Justification for POSIX ACLs when RBAC would suffice

**Important:** HNS is a storage account-level setting. You cannot mix HNS and non-HNS containers in the same account. Plan storage account topology accordingly.

**Key clarification:** HNS is a **performance and operations feature**, not a security feature. Enabling HNS does not require using POSIX ACLs.

---

### POSIX ACLs

**What it is:** Fine-grained, filesystem-style permission controls (owner/group/other with read/write/execute) available only on HNS-enabled storage accounts.

**Appropriate uses:**
- Analytics platforms that mount storage as a filesystem (Databricks, HDInsight)
- Scenarios requiring per-directory or per-file permission inheritance
- Compatibility with tools expecting traditional filesystem permissions
- Multi-tenant environments where teams access storage via mounted paths

**Not appropriate for:**
- REST API access patterns (applications calling storage via HTTPS)
- Browser-based downloads or web application serving
- Service-to-service authentication (use managed identities + RBAC)
- Any scenario where the consumer is an application, not a mounted filesystem

**Critical distinction:** 
- **POSIX ACLs** secure access for *mounted filesystems* (user navigates directories interactively)
- **RBAC + SAS tokens** secure access for *API requests* (application requests specific blob via HTTPS)

These are different access patterns requiring different security models. Applying POSIX ACLs to API-serving architectures creates friction without security benefit.

---

### Access Pattern Summary

| Access Pattern | Recommended Storage | Auth Model |
|----------------|---------------------|------------|
| Analytics platform mounting storage (Spark/Databricks) | ADLS Gen2 (HNS) | RBAC or POSIX ACLs |
| REST API serving (TiTiler, STAC, OGC APIs) | GPv2 Standard Blob | RBAC + Managed Identity |
| Browser downloads | Either | Short-lived SAS tokens |
| CDN-cached public data | GPv2 Standard Blob | Anonymous read or SAS |

Different access patterns can use different storage accounts optimized for their requirements.

---

## Data Platform Features

### Delta Lake

**What it is:** An open-source storage format that adds ACID transaction capabilities to Parquet files through transaction logs.

**Azure context:** Delta Lake is primarily used via Azure Databricks or Azure Synapse Analytics. Databricks (the company) created Delta Lake and their Azure integration is tightly coupled with ADLS Gen2. Delta tables are stored as Parquet files + transaction logs in blob storage, but require Spark-based compute to read/write effectively.

**Appropriate uses:**
- Petabyte-scale tables with frequent row-level updates
- Concurrent read/write workloads from multiple compute clusters
- Streaming and batch data landing in the same tables simultaneously
- Time-travel queries for ML reproducibility

**Not appropriate for:**
- File-based workflows (upload, store, serve)
- Raster data (COGs, GeoTIFFs)
- Datasets published as immutable releases
- Workloads without concurrent writers or row-level updates
- Scenarios where data is written once and read via HTTP APIs

**Cost consideration:** 
- Delta Lake format is open source (free)
- Effective use requires Azure Databricks (~$3,000-10,000+/month for meaningful usage) or Synapse Spark pools
- For comparison: PostgreSQL + Standard Blob Storage serves file-based workflows at ~$100-200/month

**The key question:** Does the workload involve concurrent writers updating the same tables, or frequent row-level modifications to massive datasets? If not, Delta Lake adds cost and complexity without corresponding benefit.

---

## Cloud-Native Geospatial Pattern

### Immutable Artifacts with Catalog-Based Release Management

This is the standard pattern used by NASA, USGS, Planet, and other major geospatial data providers.

**Architecture:**

```
/datasets/fathom/rwanda/v1.0/flood_depth.tif
/datasets/fathom/rwanda/v2.0/flood_depth.tif
/datasets/fathom/rwanda/v2.1/flood_depth.tif
```

Each version is a distinct, immutable object at a unique path.

**Metadata management:**

| Field | Example | Purpose |
|-------|---------|---------|
| dataset_id | fathom-rwanda | Identifies the dataset |
| version | 2.1 | Semantic version |
| storage_path | /datasets/fathom/rwanda/v2.1/ | Location of artifacts |
| status | current | Release status |
| release_date | 2025-01-10 | When published |
| supersedes | 2.0 | Previous version |
| changelog | Updated flood depth model | What changed |

**Discovery:** STAC (SpatioTemporal Asset Catalog) provides standardized metadata and search capabilities.

**Why this pattern:**

| Requirement | Solution |
|-------------|----------|
| What version is current? | Query catalog: `status = 'current'` |
| What changed between versions? | Changelog in metadata |
| Roll back to previous version | Update catalog pointer |
| Audit trail | Database records with approval, timestamp, user |
| Reproducibility | STAC items link to exact blob paths |

---

## Comparison Summary

| Layer | Technology | Tracks | Answers |
|-------|------------|--------|---------|
| Infrastructure | Blob Versioning | Write operations | "What was here before this file was overwritten?" |
| Infrastructure | Soft Delete | Deleted objects | "Can we recover this deleted file?" |
| Data Platform | Delta Lake | Table transactions | "What did this table look like at transaction N?" |
| Data Governance | Catalog + Metadata | Intentional releases | "What is the authoritative current release and what is its lineage?" |

---

## Architecture Decision

For geospatial data storage, we implement:

- **Immutable artifacts** stored at version-specific paths
- **ETL pipeline** manages publishing new versions as distinct objects
- **Catalog database** tracks release metadata, status, and lineage
- **STAC API** provides standardized discovery and access
- **Blob versioning** enabled as infrastructure-level recovery mechanism (not for release management)

This aligns with industry-standard cloud-native geospatial practices and provides clear separation between infrastructure-level data protection and application-level data governance.

---

## References

- [STAC Specification](https://stacspec.org/)
- [Cloud-Optimized GeoTIFF](https://www.cogeo.org/)
- [Azure Blob Versioning Documentation](https://learn.microsoft.com/en-us/azure/storage/blobs/versioning-overview)
- [Delta Lake Documentation](https://delta.io/)