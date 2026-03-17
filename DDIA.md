# DDIA Concepts Applied to DDHGeo/Chimera Platform

## Architectural Principles & DDIA Mapping

### 1. Single Database as Source of Truth

**Principle:** All platform state exists in one PostgreSQL database (one schema). Applications are stateless — they read from Postgres, do work, then update Postgres.

**DDIA Concepts:**
- **Shared-everything architecture** — the deliberate inverse of shared-nothing. Trades horizontal scalability for dramatically simplified consistency guarantees.
- **MVCC (Multi-Version Concurrency Control)** — Postgres handles concurrent reads and writes natively. Readers never block writers, writers never block readers. Conflicting writes are resolved through transaction isolation levels.
- **Advisory locks** — application-level coordination for cases where row-level locking is insufficient (e.g., barrier synchronization in fan-in). Forces sequential execution to prevent race conditions.
- **CAP theorem positioning** — single node means no partition tolerance concern, so consistency and availability come free within that node's uptime.

**Explicit tradeoff:** The platform scales as far as Postgres allows. Vertical scaling on Azure has a comically large ceiling. Correctness is chosen over speed — upper limits manifest as longer job times, not increased concurrency complexity.

**Scaling frontiers:**
- Hardware behind the DB server (generous in Azure, wallet-limited not hardware-limited)
- Lock contention — degrades with contention *density* (concurrent writes to the same rows), not raw connection count. Low double-digit concurrent writes to the same table is nothing for Postgres.

---

### 2. Postgres-as-Queue: Eliminating the Message Broker

**Principle:** The database table *is* the queue. Three apps communicate exclusively through Postgres — no message broker, no second coordination system. Gateway writes job records, orchestrator polls and dispatches task records, workers poll and execute.

**Architecture:**
- **Gateway Function App** → writes job records to Postgres
- **Orchestrator (polling loop)** → reads job table, resolves DAG, writes task records
- **Worker (polling loop)** → reads task table (`SELECT ... WHERE status = 'pending' FOR UPDATE SKIP LOCKED`), executes work, updates task status

**DDIA Concepts:**
- **Elimination of the dual-write problem** — with Service Bus, updating Postgres AND sending a message were not atomic. State lived across two systems that could disagree. With Postgres-only coordination, every state transition is a single transaction. The system's truth lives in exactly one place.
- **`FOR UPDATE SKIP LOCKED`** — Postgres's native mechanism for queue-like behavior. Workers claim pending tasks atomically without blocking each other. Equivalent to Service Bus message locking but fully transactional.
- **Removal of a SPOF** — Service Bus was a second single point of failure alongside Postgres. Removing it means one failure domain instead of two.
- **Schema enforcement at the storage layer** — Service Bus messages had no broker-level schema enforcement ("complete anarchy"). Database columns and constraints enforce schema natively.

**What was gained by removing Service Bus:**
- No poison message problem (malformed rows can't exist if schema constraints are correct)
- No message serialization/deserialization boundary
- No eventual consistency between two coordination systems
- Janitor/anti-entropy process becomes unnecessary — there's no second system to drift out of sync with
- Pydantic schema-as-code story simplifies: no Service Bus serialization methods, just SQL composition

**What was lost:**
- Push-based wake-up (workers must poll). Mitigated by the polling orchestrator design — this was already the direction of travel.

**Historical note:** The original architecture used Azure Service Bus with job and task queues. This was a useful abstraction during early development, enabling flexible architecture changes. It was removed when the logical conclusion of "this is a single-database platform" made the broker a contradiction rather than an asset.

---

### 3. Idempotent Tasks with Checkpoint-Based Resumability

**Principle:** Jobs can resume from intermediate data after failures. Tasks won't rerun if already completed successfully (unless `force=True`). Each task is an atomic operation.

**DDIA Concepts:**
- **Idempotency** — running the same operation twice produces the same result. The "skip if already completed" check.
- **Crash recovery / fault tolerance through replayability** — picking up where you left off using intermediate state.
- **Checkpointing** — task-level state records in Postgres serve as a checkpoint log.
- **Saga-like semantics** — a long-running process broken into idempotent steps, resumable from the last successful checkpoint. Simpler than a full saga because no compensating transactions are needed.

---

### 4. Derived Data & the Medallion Architecture

**Principle:** Bronze (raw input) → ETL pipeline → Silver (COGs in storage, PostGIS tables). Silver is derived data that can be regenerated from bronze at any time. Future gold layer (geoparquet aggregations) follows the same principle.

**DDIA Concepts:**
- **Derived data** — silver has no independent authority. Bronze is the source of truth; the pipeline is a materialized computation over it.
- **Data lineage and reproducibility** — the pipeline is a deterministic function: `f(bronze) → silver`. Preserving inputs, transformation logic, and outputs separately enables re-derivation.
- **Materialized views** — gold layer is explicitly a materialized view for a specific analytical purpose.

---

### 5. Eventual Consistency at Every Serving Layer

**Principle:** Silver data is served read-only through TiTiler (rasters) and TiPG (vectors) via REST APIs. An external service layer with CDN adds additional caching.

**DDIA Concepts:**
- **Eventual consistency** — accepted at three tiers:
  1. **Bronze → Silver lag** — silver is stale until the pipeline reruns. Bounded by pipeline execution time.
  2. **Silver → Service layer** — effectively zero lag since TiTiler/TiPG read directly from storage/database.
  3. **Service layer → CDN** — bounded by cache TTL.
- **Read replicas** — TiTiler/TiPG are conceptually read replicas. Stateless, no write path, no conflicts. They serve whatever version of the data currently exists.
- **Appropriate consistency guarantees** — geospatial data (flood maps, climate rasters, vector tiles) has no real-time requirement. Users getting 10-minute-old data is perfectly acceptable.

---

### 6. State Machine Orchestration with Fan-Out/Fan-In

**Principle:** Job message → orchestrator dispatches N parallel tasks → workers execute and update own task records → last task to complete triggers next stage via advisory lock check → orchestrator advances to next stage or closes job.

**DDIA Concepts:**
- **Dataflow graph** — the pipeline is a directed graph of operations.
- **Fan-out** — orchestrator dispatches N parallel tasks from one job message.
- **Fan-in / barrier synchronization** — last completing task checks `sum(active_tasks) > 0` under advisory lock to prevent double-triggering of the next stage.
- **Stateless orchestrator** — intelligence lives in the state machine encoded in job/task records plus message flow. Any orchestrator instance can handle any message.

---

### 7. Pydantic as Canonical Schema (Schema-as-Code)

**Principle:** Pydantic objects are the single source of truth for the data model. Specific methods handle serialization across the Python ↔ SQL boundary (via `sql.SQL` composition and Postgres functions). All DDL is derived from Pydantic definitions.

**DDIA Concepts:**
- **Single source of truth with derived representations** — SQL DDL and runtime objects are all derived from one canonical definition.
- **Schema divergence prevention** — without this, the same entity is defined independently in Python and SQL, and they drift. This is a distributed consistency problem applied to code rather than data.

---

### 8. Anti-Entropy / Compensating Processes (Historical)

**Principle:** Under the original Service Bus architecture, a timer-triggered "janitor" process ran periodically to detect and fix inconsistent states (stuck jobs, orphaned tasks, state mismatches between Postgres and queue contents).

**DDIA Concepts:**
- **Anti-entropy mechanism** — same principle as Dynamo's read repair or Kafka's log compaction. Inconsistency is expected; a background process corrects it.
- **Compensating process** — not a band-aid on bad design, but a core architectural pattern. Any system with two coordination mechanisms (database + message queue) will have windows of inconsistency. The janitor closes those windows.

**Current status:** With the move to Postgres-only coordination, the separate janitor is largely unnecessary. The polling orchestrator inherently reconciles state on every loop iteration — if a task is stuck, the next poll detects it. Anti-entropy is now embedded in the orchestration loop rather than being a separate process.

---

### 9. Backpressure & Connection Pool Management

**Principle:** All platform consumers — TiPG, TiTiler/pgSTAC, Gateway, Orchestrator, Workers — share one Postgres instance. Connection count must be explicitly managed to prevent resource starvation cascades.

**Origin lesson:** TiPG runaway queries (full directory scans) consumed the connection pool, starving orchestration and write operations, causing a failure cascade across the entire platform.

**DDIA Concepts:**
- **Backpressure** — the system must regulate the rate at which consumers demand resources from Postgres. Without explicit limits, Postgres accepts connections until it falls over.
- **Noisy neighbor problem** — in shared-everything architecture, one misbehaving consumer can poison the shared resource for all others.
- **Resource contention as the cost of shared-everything** — distributed architectures trade consistency problems for independence. Shared-everything trades independence for resource contention. Resource contention is solvable with configuration (connection pool segmentation) rather than fundamental redesign.

**Mitigation:** Connection pool segmentation — each app gets a defined max connection count, and the sum stays under Postgres's limit. TiPG going haywire can only exhaust *its* allocation, not starve the orchestrator.

---

### 10. Deterministic Identity & Anti-Corruption Layer

**Principle:** External B2B applications (e.g., DDH with DatasetID/ResourceID hierarchy) have their own identity schemes. The platform abstracts these into a deterministic UUID via `sha256(B2B_identifier + sort(platform_refs))`. Identity (Asset) is separated from lifecycle (Release).

**DDIA Concepts:**
- **Deterministic / content-addressable identifiers** — the hash function is a pure function of business inputs. Same inputs always produce the same UUID. Idempotency is guaranteed at the identity level before task status is even checked.
- **Anti-corruption layer** (DDD term, applicable to DDIA boundary discussions) — the platform doesn't model upstream domain structures. It digests them. DDH has hierarchical IDs; a future B2B app might have flat IDs. The platform doesn't care — everything becomes a hash.
- **Identity/lifecycle separation** — Asset (what it is, immutable deterministic identity) vs Release (what's happening to it, mutable state machine: submitted → processing → pending-approval → approved). Multiple releases can reference the same Asset without identity confusion.

**Data model note:** STAC metadata provides the flexible envelope for upstream metadata structures. The platform normalizes identity while accommodating arbitrary metadata schemas.

---

## Proposed Architectural Evolution

### Current State (QA)
- Orchestrator: Azure Function App, reactive (triggered by Service Bus messages)
- Coordination: Split across Postgres (state) and Service Bus (message flow)
- Janitor: Separate timer-triggered function for state reconciliation

### Target State (Dev → Production)
- **Service Bus removed entirely** — Postgres is the sole coordination mechanism. Three apps (Gateway, Orchestrator, Worker) communicate exclusively through database tables.
- **DAG-based task graph** — tasks are nodes with dependency edges, composable into complex pipelines. Reusable operations ("build COG", "reproject raster", "netcdf to zarr") assembled declaratively.
- **Polling-based orchestrator** — reads Postgres directly to resolve "what has all dependencies met but hasn't run yet?" and dispatches those tasks via row insertion.
- **Merged orchestrator + janitor** — polling loop inherently reconciles state. No separate anti-entropy process needed.
- **Connection pool segmentation** — each app has explicit connection limits to prevent noisy-neighbor cascades.

### Migration Strategy
- **Separation of concerns:** change the orchestration model (message-driven → DAG polling) and the execution model (Function App → Docker) as independent steps.
- **Phase 1:** Build DAG resolution logic as a pure Python module. Test inside a Function App timer trigger in dev. Proves orchestration logic independent of execution environment.
- **Phase 2:** Move proven DAG module into long-running Docker app with polling loop. Now only changing where the code runs, not what it does.
- **QA environment:** remains on current Service Bus architecture untouched during migration.

---

## Key Vocabulary Reference

| Term | Meaning in This Architecture |
|------|------------------------------|
| MVCC | Postgres concurrent access without lock contention for reads |
| Advisory lock | Application-level coordination for barrier synchronization |
| `FOR UPDATE SKIP LOCKED` | Postgres-native queue semantics — atomic task claiming without blocking |
| Idempotency | Tasks produce same result on re-execution; skip if complete |
| Checkpointing | Task state records in Postgres enabling crash recovery |
| Derived data | Silver/gold layers regenerable from bronze source of truth |
| Eventual consistency | Acceptable staleness at ETL, service, and CDN layers |
| Fan-out / fan-in | Parallel task dispatch and barrier-synchronized completion |
| Anti-entropy | Reconciliation of inconsistent state (now embedded in orchestrator loop) |
| Schema-as-code | Pydantic as single source for all schema representations |
| Backpressure | Regulating consumer demand on shared Postgres via connection pool limits |
| Noisy neighbor | One consumer exhausting shared resources, starving others |
| Deterministic ID | `sha256(identifier + sort(refs))` — content-addressable, idempotent identity |
| Anti-corruption layer | Abstracting upstream B2B identity schemes into platform-native UUIDs |
| Identity vs lifecycle | Asset (immutable hash ID) vs Release (mutable state machine) |
| Execution model | Where/how code runs (Function App vs Docker) |
| Orchestration model | How "what runs next" decisions are made (reactive vs polling) |
| Dual-write problem | (Historical) Non-atomic updates across Postgres and Service Bus — eliminated by removing Service Bus |