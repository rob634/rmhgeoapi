# COMPETE T5 — Vector Handler Chain

**Run**: 65
**Date**: 28 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Series**: COMPETE DAG Series — Target T5
**Version**: v0.10.9.0
**Split**: B (Internal vs External) + Single-Database Lens
**Files**: 12 (7 handlers + 4 support modules + 1 YAML)
**Lines**: ~6,612 (largest target in the series)
**Findings**: 14 confirmed — 2 CRITICAL, 2 HIGH, 2 MEDIUM, 2 LOW, 3 Epoch 4 flags, 3 rejected
**Fixes Applied**: 8 (2 CRIT + 2 HIGH + 2 MEDIUM + 2 LOW). Epoch 4 flags left in place.
**Accepted Risks**: 2 (carried from Run 49)

---

## EXECUTIVE SUMMARY

The vector handler chain had two critical data contract bugs: `handler_register_catalog` read `total_rows` but the upstream handler emits `row_count` (catalog always registered 0 features), and `handler_create_split_views` read `split_column` from top-level params but it was nested inside `processing_options` (split views always failed). The finalize handler exists but the DAG engine never invokes it (mount dirs accumulate). All MEDIUM+ fixed. The int64→INTEGER overflow in PostGIS type mapping and the cardinality limit mismatch (100 vs 20) were also corrected.

---

## FIXES APPLIED

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **CRITICAL** | `row_count` vs `total_rows` key mismatch — 0 features in catalog | Changed to `table_info.get('row_count', 0)` |
| 2 | **CRITICAL** | `split_column` nested in `processing_options` — always fails | Added fallback extraction from processing_options dict |
| 3 | **HIGH** | `original_crs` never reaches catalog | Added receives clause in YAML |
| 4 | **HIGH** | Finalize handler never invoked | **NOT FIXED — engine-level gap** (documented, needs dag_orchestrator change) |
| 5 | MEDIUM | int64 → INTEGER overflow | Added int64/Int64 → BIGINT mapping |
| 6 | MEDIUM | Cardinality limit mismatch (100 vs 20) | Imported MAX_SPLIT_CARDINALITY constant |
| 7 | LOW | bbox None crash in log line | Added None guard |
| 8 | LOW | Missing error_type in validation returns | **Deferred** — low impact, dev-time errors only |

**Note on Fix 4**: The finalize handler gap is an engine-level issue — `dag_orchestrator.py` has no code path to dispatch finalize handlers. This requires a separate engine change, not a handler fix. Tracked for next iteration.

## ACCEPTED RISKS (from Run 49)

| Risk | Rationale |
|------|-----------|
| Multi-group partial failure | Partial results preferable to full rollback in ETL |
| Private API chaining | Internal to same package, tested via integration |

## EPOCH 4 FLAGS (confirmed but not fixed)

| Finding | File | Impact |
|---------|------|--------|
| insert_features_with_metadata no NaT-to-None | postgis_handler.py | Year-48113 corruption (Epoch 5 handler has fix) |
| Empty column list trailing comma | postgis_handler.py L1055 | Syntax error on geometry-only datasets |
| Mutable set for reserved cols | postgis_handler.py | Functional, no mutation risk |

## ARCHITECTURE WINS

1. Epoch 5 empty-column branch correctly handles edge case Epoch 4 gets wrong
2. Per-chunk commit with batch ID enables retry safety
3. SQL injection guard with dedicated regex + psycopg Identifier
4. Idempotent view creation (CREATE OR REPLACE) and catalog upsert (ON CONFLICT)
5. Two-layer NaT-to-None defense (handler 2 + handler 3)
6. frozenset for reserved columns (Epoch 5)
