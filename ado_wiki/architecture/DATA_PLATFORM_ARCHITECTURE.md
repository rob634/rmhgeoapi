# Geospatial Data Platform Architecture

## Document Structure

1. **Part 1: Terminology Framework** - Microsoft Azure Cloud Adoption Framework terminology for data systems
2. **Part 2: Architecture Overview** - How the geospatial platform implements each layer
3. **Part 3: Technical Reference** - Detailed guidance on Azure storage features and appropriate usage

---

# Part 1: Terminology Framework

This section defines terminology consistent with Microsoft's Cloud Adoption Framework for Azure.

## Data Governance

**Microsoft Definition:** *"A framework of policies, processes, roles, and technical controls that ensures your organization's data is secure, trustworthy, and used responsibly throughout its lifecycle."*

Data governance addresses:

- **Data Classification** - Categorizing data by confidentiality and sensitivity (e.g., Public, Official Use Only)
- **Data Ownership** - Assigning accountability for data assets
- **Data Lifecycle Management** - Policies for retention, archival, and disposal
- **Data Quality Standards** - Defining what makes data "approved for release"
- **Policy Definition and Enforcement** - Rules governing data access and usage
- **Data Lineage** - Tracking data origins and transformations

Data governance is primarily organizational and policy work. Technology supports it but does not replace it.

---

## Data Management

**Microsoft Definition:** The operational implementation of governance policies through technology.

Microsoft's Cloud Adoption Framework describes the "Data Management Landing Zone" as the environment providing:

- **Data Cataloging and Discovery** - Making data findable
- **Metadata Management** - Tracking what exists, where it lives, what version is current
- **Master Data Management** - Ensuring consistency of core data entities
- **Data Quality Enforcement** - Implementing validation and standards
- **Access Control Implementation** - Enforcing governance-defined permissions

---

## Data Integration

**Microsoft Definition:** Moving and transforming data between systems.

Microsoft positions Azure Data Factory in this layer:

- **Orchestrating Data Movement** - Scheduled and triggered transfers between data stores
- **ETL/ELT Workflows** - Extract, transform, load pipelines
- **Transformation Pipelines** - Format conversion, validation, enrichment
- **Cross-Boundary Data Movement** - Secure transfer between security domains

---

## Data Cataloging and Discovery

**Microsoft Definition:** Making data findable through standardized metadata.

Microsoft Purview serves this function for enterprise data estates. For geospatial data, STAC (SpatioTemporal Asset Catalog) provides equivalent capabilities:

- **Unified View of Data Assets** - Single interface to discover available data
- **Search and Browse** - Find datasets by theme, location, time, keywords
- **Metadata Standards** - Consistent description of data characteristics
- **Business Glossary** - Common vocabulary for data terminology

---

## Summary: The Data Hierarchy

| Layer | Focus | Key Questions |
|-------|-------|---------------|
| **Data Governance** | Policy and accountability | Who owns this? Who can access it? How long do we keep it? |
| **Data Management** | Operational implementation | Where does it live? What version is current? Is it valid? |
| **Data Integration** | Movement and transformation | How does data flow between systems? What transformations occur? |
| **Data Cataloging** | Discovery and findability | What data exists? How do I find what I need? |

---

# Part 2: Geospatial Platform Architecture

This section maps the geospatial data platform components to Microsoft's data terminology framework.

## Architecture by Data Layer

### Data Governance Implementation

| Governance Concern | Implementation |
|--------------------|----------------|
| Data Classification | Two-tier: Public, Official Use Only (OUO) |
| Data Ownership | Dataset ownership tracked in catalog metadata |
| Lifecycle Management | Retention policies enforced via Azure lifecycle management |
| Quality Standards | Validation rules in ETL pipeline; approval workflow before release |
| Policy Enforcement | RBAC for access control; security boundaries via service permissions |
| Lineage Tracking | Source, transformation steps, and outputs recorded in PostgreSQL |

### Data Management Implementation

| Management Function | Implementation |
|--------------------|----------------|
| Catalog Database | PostgreSQL tables tracking datasets, versions, status, lineage |
| Metadata Management | STAC-compliant metadata for all geospatial assets |
| Version Tracking | Immutable artifacts at version-specific paths; catalog tracks current/superseded status |
| Quality Enforcement | Automated validation during ETL (CRS verification, format validation, schema checks) |
| Access Control | Azure RBAC + Managed Identities; SAS tokens for time-limited access |

### Data Integration Implementation

| Integration Function | Implementation |
|---------------------|----------------|
| Internal ETL | Azure Functions processing pipeline (validation, transformation, COG generation) |
| Cross-Boundary Movement | Azure Data Factory for internal → external storage transfers |
| Orchestration | Service Bus for job queuing; PostgreSQL for state management |
| Transformation | Format conversion (to COG, GeoParquet); reprojection; tiling |

### Data Cataloging Implementation

| Cataloging Function | Implementation |
|--------------------|----------------|
| Discovery API | STAC API (stac-fastapi with pgstac backend) |
| Search Capabilities | Spatial, temporal, and keyword search via STAC |
| Metadata Standard | STAC specification for geospatial; OGC standards for services |
| Asset Access | Direct links to COGs and vector data via OGC APIs |

---

## Component Mapping

| Component | Data Layer | Function |
|-----------|------------|----------|
| PostgreSQL metadata tables | Data Management | Track releases, versions, status, lineage |
| STAC API | Data Cataloging | Standardized discovery and metadata access |
| Azure Functions ETL | Data Integration | Process, transform, validate, publish |
| Azure Data Factory | Data Integration | Cross-boundary data movement with audit trail |
| TiTiler | Data Serving | Serve raster data via OGC APIs |
| pg_featureserv / OGC Features API | Data Serving | Serve vector data via OGC API - Features |
| Blob Storage | Infrastructure | Store artifacts (COGs, GeoParquet) |
| RBAC + Managed Identity | Data Governance | Enforce access policies |

---

## Security Boundary Architecture

A critical architectural decision: **separation of internal and external data environments** enforced through service permissions, not just policy.

```
┌─────────────────────────────────────────────────────────────────┐
│                     INTERNAL ENVIRONMENT                        │
│                                                                 │
│   Azure Functions ETL                                           │
│   ├── Has: Read/Write to internal storage                      │
│   ├── Has: Read/Write to PostgreSQL                            │
│   └── Does NOT have: Write access to external storage          │
│                                                                 │
│   Internal Blob Storage                                         │
│   └── Contains: All data during processing (Public + OUO)      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Azure Data Factory
                              │ (ONLY service with cross-boundary write)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     EXTERNAL ENVIRONMENT                        │
│                                                                 │
│   External Blob Storage                                         │
│   └── Contains: Only Public data for external APIs             │
│                                                                 │
│   External APIs (TiTiler, OGC Features, STAC)                  │
│   └── Serve: Public data to external consumers                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Why Azure Data Factory for Cross-Boundary Movement

**Architectural enforcement:** The ETL application physically cannot write OUO data to external storage because it lacks credentials. This is not policy compliance—it is structural impossibility.

**Audit trail:** Azure Data Factory provides automatic logging per Microsoft's security guidance:
- What was copied (source, destination, bytes)
- When the transfer occurred
- What triggered the pipeline
- Success or failure status
- Full integration with Azure Monitor

**Microsoft alignment:** This follows Microsoft's guidance for Data Factory:
> *"With Data Factory, you create data-driven workflows to orchestrate movement of data between supported data stores... You can also monitor and manage workflows by using SDKs and Azure Monitor."*

**Appropriate use:** ADF is designed for orchestrated, auditable data movement between stores. This is not over-engineering—it is using the correct tool for high-risk data transfers where compliance and audit trails are mandatory.

---

## Release Management Pattern

Release management is a **Data Governance** concern implemented through **Data Management** tooling.

### Pattern: Immutable Artifacts with Catalog-Based Versioning

This is the industry-standard pattern used by NASA, USGS, Planet, and other major geospatial data providers.

**Storage structure:**
```
/datasets/fathom/rwanda/v1.0/flood_depth.tif
/datasets/fathom/rwanda/v2.0/flood_depth.tif
/datasets/fathom/rwanda/v2.1/flood_depth.tif
```

Each version is a distinct, immutable object at a unique path. Versions are never overwritten.

**Catalog metadata:**

| Field | Example | Purpose |
|-------|---------|---------|
| dataset_id | fathom-rwanda | Identifies the dataset |
| version | 2.1 | Semantic version |
| storage_path | /datasets/fathom/rwanda/v2.1/ | Location of artifacts |
| status | current | Release status |
| release_date | 2025-01-10 | When published |
| supersedes | 2.0 | Previous version |
| approved_by | DEC Data Team | Governance approval |
| changelog | Updated flood depth model | What changed |

**Why this pattern:**

| Requirement | Solution |
|-------------|----------|
| What version is current? | Query catalog: `WHERE status = 'current'` |
| What changed between versions? | Changelog in metadata |
| Roll back to previous version | Update catalog pointer; previous artifacts still exist |
| Audit trail | Database records with approval, timestamp, user |
| Reproducibility | STAC items link to exact blob paths |

This pattern provides **semantic versioning with business context** — the catalog tracks not just that something changed, but what the change means, who approved it, and why it matters.

---

# Part 3: Technical Reference

This section provides detailed guidance on Azure storage features, appropriate usage, and common misconceptions.

## Storage-Level Data Protection Features

These features exist at the **infrastructure layer** for disaster recovery and compliance. They do not replace application-level data management or governance.

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

**Version identifier:** Timestamp (e.g., `2025-01-09T14:32:17Z`) — not a semantic version

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

## Data Platform Technologies

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

### Azure Data Factory

**What it is:** Azure's managed data integration service for orchestrating data movement and transformation.

**Appropriate uses:**
- Bulk data transfers between storage accounts or external sources
- Scheduled/triggered data movement (not user-initiated)
- Cross-security-boundary data movement requiring audit trails
- Managed connectors to external systems (S3, SFTP, etc.)
- Copy activities with automatic retry, checkpointing for large transfers
- Enterprise compliance requirements for data movement tracking

**Audit capabilities:**
- Automatic logging of every pipeline run
- Source and destination tracking
- Trigger identification
- Success/failure status
- Integration with Azure Monitor

**Not appropriate for:**
- User-initiated uploads (use application APIs)
- Complex transformation logic (better in code you control)
- Real-time/streaming (use Event Hubs)

**Architecture note:** ADF is appropriate when data movement crosses security boundaries and requires compliance-grade audit trails. The geospatial platform uses ADF specifically for internal → external storage transfers where the consequence of error (OUO data exposed publicly) requires architectural safeguards beyond policy.

---

## Technology Comparison Summary

| Layer | Technology | Tracks | Answers |
|-------|------------|--------|---------|
| Infrastructure | Blob Versioning | Write operations | "What was here before this file was overwritten?" |
| Infrastructure | Soft Delete | Deleted objects | "Can we recover this deleted file?" |
| Data Platform | Delta Lake | Table transactions | "What did this table look like at transaction N?" |
| Data Integration | Azure Data Factory | Data movement operations | "What was transferred, when, by what trigger, did it succeed?" |
| Data Management | Catalog + Metadata | Intentional releases | "What is the authoritative current release and what is its lineage?" |

---

## References

- [Microsoft Cloud Adoption Framework - Data Governance](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/scenarios/cloud-scale-analytics/govern)
- [Azure Data Factory Security Considerations](https://learn.microsoft.com/en-us/azure/data-factory/data-movement-security-considerations)
- [Azure Blob Versioning Documentation](https://learn.microsoft.com/en-us/azure/storage/blobs/versioning-overview)
- [STAC Specification](https://stacspec.org/)
- [Cloud-Optimized GeoTIFF](https://www.cogeo.org/)
- [Delta Lake Documentation](https://delta.io/)