# SIEGE-DAG Run 6

**Date**: 03 APR 2026
**Version**: v0.10.9.16 (all 3 apps)
**Environment**: Fresh schema rebuild + app restart
**Operator**: Claude Opus 4.6 (SIEGE-DAG agent)
**Status**: BLOCKED — Brain release lifecycle commits not persisting to DB

---

## Changes Since Run 5 (v0.10.9.13 → v0.10.9.16)

| Change | Impact on SIEGE |
|--------|-----------------|
| Pyramid removal from zarr workflow | D3/D4: output is flat `.zarr` not `_pyramid.zarr` |
| Zarr datetime "0" fix (D4/DF-STAC-6) | D4: should now pass STAC materialization |
| Rechunk URL `.zarr` suffix fix (C-2) | D4: register should find the store |
| Zarr xarray URL injection (C-3) | D3/D4: STAC items should have TiTiler URLs |
| Services block gated on approval | ALL: services=null until approved |
| macOS __MACOSX resource fork filtering | D2: if test files have macOS artifacts |
| Tile handler VRT→GTiff fix | D5: multiband tiling should work (was broken) |
| Vector indexes/temporal_property support | D2: new capabilities available |
| Raster collection workflow (new) | Not tested in SIEGE yet |
| Unified STAC lifecycle (structural + approved) | D1/D3/D4/D5: STAC inserted pre-gate (state 2) |
| Approval gate added to zarr workflow | D3/D4: workflow now pauses at gate |
| Vector optional STAC (`create_stac`) | D2: can test with create_stac=true |
| D6 revoke→unpublish fix (Release fallback) | D6: should now complete cleanly |
| D7 vector unpublish release revoke fix | D7: was FAIL in Run 5, should now PASS |
| Epoch 4 `ddh:status='approved'` stamp | All approval paths now consistent |
| Reject STAC cleanup (state 2 items) | D11: structural STAC should be deleted on reject |

---

## Results Summary

| Metric | Value |
|--------|-------|
| Total sequences | 19 |
| Submitted | 4 (D1-D4) |
| Reached gate | 4/4 |
| Approved | 0/4 — **BLOCKED** |
| **Status** | **BLOCKED on release lifecycle bug** |

---

## Blocking Issue: Brain Release Lifecycle Commits Not Persisting

### Symptom

All 4 workflows (D1 raster, D2 vector, D3 netcdf, D4 zarr) complete to `awaiting_approval` correctly. The DAG Brain logs show successful `UPDATE ... SET processing_status = 'completed'` with `conn.commit()` and `cur.rowcount > 0`. But the actual DB value remains `pending`. Approval is blocked because the approval guard requires `processing_status = 'completed'`.

### Evidence

**Brain Docker logs** (from `/tmp/brain_logs/LogFiles/2026_04_04_*.log`):

```
00:45:54 | Updating processing status for 1f8da2030e0ba06d... to processing
00:45:54 | Updated processing status for 1f8da2030e0ba06d... to processing
00:45:54 | Release lifecycle: 1f8da2030e0ba06d → PROCESSING
00:46:45 | Updating processing status for 1f8da2030e0ba06d... to completed
00:46:45 | Updated processing status for 1f8da2030e0ba06d... to completed
00:46:45 | Updating physical outputs for 1f8da2030e0ba06d... (1 fields)
00:46:45 | Updated physical outputs for 1f8da2030e0ba06d...
00:46:45 | Release lifecycle: 1f8da2030e0ba06d → COMPLETED (at gate)
```

All 4 releases show the same pattern — "Updated" logged (requires `rowcount > 0`) but DB shows `pending`.

**Direct DB query** (via psql as rob634):

```sql
SELECT release_id, processing_status FROM app.asset_releases ORDER BY created_at DESC LIMIT 4;
-- ALL show processing_status = 'pending'
```

**Manual UPDATE works**:

```sql
UPDATE app.asset_releases SET processing_status = 'completed'
WHERE release_id = '1f8da2030e0ba06df290b94a9b82647e';
-- UPDATE 1 (persists correctly)
```

**Python simulation works** (same psycopg3 + ProcessingStatus enum + sql.SQL pattern):

```python
# Exact same code as ReleaseRepository.update_processing_status — works locally
cur.execute(UPDATE ... SET processing_status = %s WHERE release_id = %s, (ProcessingStatus.COMPLETED, rid))
conn.commit()
# rowcount=1, value persists
```

### Ruled Out

| Hypothesis | Status | Evidence |
|------------|--------|----------|
| Wrong release_id | RULED OUT | `workflow_runs.release_id` matches `asset_releases.release_id` for all 4 |
| Enum type mismatch | RULED OUT | Column is `app.processing_status` enum, Python `str` enum serializes correctly |
| Missing permissions | RULED OUT | `rmhpgflexadmin` has full INSERT/SELECT/UPDATE/DELETE on table |
| Wrong database/schema | RULED OUT | Both apps configured with same host/db/schema |
| Read-only transaction | RULED OUT | `default_transaction_read_only = off`, role has full privileges |
| Silent exception | RULED OUT | No warnings/errors in Brain logs around release updates |
| Connection pool reset | RULED OUT | `conn.commit()` runs before pool return; committed data persists across resets |

### Remaining Hypotheses

1. **Managed Identity token stale/invalid** — The Brain authenticates via Managed Identity (`rmhpgflexadmin`). If the token expired or became invalid after the schema rebuild, the connection pool may have created connections that appear functional (pass SELECT queries for workflow task polling) but silently fail on writes. psycopg3 pool connections are reused — if the initial auth succeeds but the token expires mid-session, writes might be silently rejected by the PostgreSQL server.

2. **Ghost connection** — The connection pool returns a connection where `commit()` is a no-op because the underlying TCP connection was severed (Azure PG Flex can drop idle connections). psycopg3 may not detect this if the pool's `check` callback only runs on checkout.

3. **WAL/replication lag** — Unlikely for a single-server Azure Flex, but possible if there's a read replica involved.

### Recommended Investigation

Enable PostgreSQL statement logging temporarily:

```sql
ALTER SYSTEM SET log_statement = 'all';
SELECT pg_reload_conf();
```

Then restart Brain, submit one workflow, and check `pg_stat_activity` or Azure PG logs for:
- Whether the Brain's UPDATE statements appear at all
- Whether COMMIT follows the UPDATE
- Whether the session user is `rmhpgflexadmin` as expected

### Historical Context

This issue did NOT exist in Run 5 (v0.10.9.13, 01 APR 2026). The Brain successfully updated `processing_status` to `completed` in that run, enabling approval. The code path (`_handle_release_lifecycle` → `ReleaseRepository.update_processing_status`) is unchanged between v0.10.9.13 and v0.10.9.16. The schema rebuild + restart sequence is also identical.

The only difference is the **unified STAC lifecycle changes** which added structural STAC nodes between `persist` and `approval_gate`. These nodes run on the **Worker** (not the Brain). The Brain only runs the orchestrator — it should not be affected by workflow YAML changes that add pre-gate nodes. But the timing of the gate transition may have changed, which could interact with connection pool lifetime or token refresh timing.

---

## Sequence Results (Partial)

| Seq | Name | Workflow | Result | Notes |
|-----|------|----------|--------|-------|
| D1 | Raster Lifecycle | process_raster | **BLOCKED** | Reached gate. processing_status=pending. Cannot approve. |
| D2 | Vector Lifecycle | vector_docker_etl | **BLOCKED** | Same issue. |
| D3 | NetCDF Lifecycle | ingest_zarr (NC) | **BLOCKED** | Same issue. Zarr approval gate is new (v0.10.9.16). |
| D4 | Native Zarr Lifecycle | ingest_zarr (Zarr) | **BLOCKED** | Same issue. |
| D5-D19 | — | — | **NOT STARTED** | Blocked on D1-D4 approval. |

---

## Positive Observations

Despite the blocking issue, several improvements are confirmed:

1. **All 4 workflows reach `awaiting_approval`** — the structural STAC lifecycle, approval gate in zarr, and conditional vector nodes all work correctly from a workflow execution perspective.
2. **Services block correctly gated** — `services: null` for all `pending_review` items (verified).
3. **DAG submit message correct** — "DAG workflow created" (not "CoreMachine job").
4. **Zarr approval gate works** — D3 and D4 pause at gate (new feature, first test).
5. **Pre-flight validation works** — D2 initial submit with wrong blob path correctly rejected before workflow creation.
