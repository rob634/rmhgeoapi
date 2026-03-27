# COMPETE Run 56: STAC Consolidated Builders and Materialization Path

**Date**: 26 MAR 2026
**Version**: v0.10.6.3
**Pipeline**: COMPETE (Adversarial Code Review)
**Scope**: STAC consolidated builders (post-consolidation review) and materialization path
**Split**: B (Internal vs External)

---

## Omega Decision

**Split B (Internal vs External)** chosen because this subsystem sits between internal STAC building logic and external pgSTAC/TiTiler systems. The productive tension: Alpha focuses on whether builders produce correct, complete STAC metadata; Beta focuses on whether the materialization path correctly writes to pgSTAC and satisfies TiTiler's rendering contract.

### File Assignments

**Alpha (Internal Logic and Invariants)**:
- `services/stac/stac_item_builder.py`
- `services/stac/stac_collection_builder.py`
- `services/stac/stac_preview.py`
- `services/stac_renders.py`
- `core/models/stac.py`
- `services/stac/handler_materialize_item.py` (internal data reading)
- `services/stac/handler_materialize_collection.py` (internal logic)
- `services/raster/handler_persist_app_tables.py` (caller)
- `services/raster/handler_persist_tiled.py` (caller)
- `services/zarr/handler_register.py` (caller)

**Beta (External Interfaces and Boundaries)**:
- `services/stac_materialization.py`
- `infrastructure/pgstac_repository.py`
- `services/pgstac_search_registration.py`
- `services/stac/handler_materialize_item.py` (pgSTAC write)
- `services/stac/handler_materialize_collection.py` (pgSTAC write + search registration)

---

## Alpha Review (Internal Logic and Invariants)

### STRENGTHS

1. **Pure function design in builders** (`stac_item_builder.py`, `stac_collection_builder.py`, `stac_preview.py`): All three builder functions are pure -- no I/O, no side effects, dict in/dict out. This makes them independently testable and composable per Principle 6.

2. **Single canonical builder** (`stac_item_builder.py:15-157`): One `build_stac_item()` replaces what was previously multiple builder paths. The consolidation comment at `stac_collection.py:273-274` confirms the old `build_raster_stac_collection()` was deleted. All callers (`handler_persist_app_tables.py:205-222`, `handler_persist_tiled.py:93-122`, `handler_register.py:167-192`) correctly use the canonical builder.

3. **Extension URLs from single source** (`core/models/stac.py:53-57`): All STAC extension URLs and STAC_VERSION are defined once and imported by the builder. No hardcoded URLs in builder code.

4. **Correct STAC datetime handling** (`stac_item_builder.py:63-71`): The three-branch logic (range, single, sentinel) covers the STAC spec requirement. The sentinel `0001-01-01T00:00:00Z` at line 12 is correctly tagged with `geoetl:temporal_source=unknown`.

5. **Render delegation is clean** (`stac_item_builder.py:160-178`): `_compute_renders()` correctly converts from `raster_bands` format to the flat `band_stats` format that `build_renders()` expects.

6. **Handler return contract compliance**: Both `handler_materialize_item.py` and `handler_materialize_collection.py` consistently return `{"success": True/False, ...}` on every code path (Standard 3.2).

### CONCERNS

**HIGH-1: `start_datetime` without `end_datetime` (or vice versa) silently falls through to sentinel**
- File: `services/stac/stac_item_builder.py`, lines 63-71
- The STAC spec requires both or neither. If only `start_datetime` is provided, it falls to the sentinel branch, silently discarding the valid temporal data. Violates Principle 1.

**HIGH-2: `_compute_renders` crash on None statistics values**
- File: `services/stac/stac_item_builder.py`, lines 168-177 and `services/stac_renders.py`, lines 92-94
- If `raster_bands[N].statistics` lacks `min`/`max` keys, the `.get("min")` returns `None`. In `build_renders` at line 93, `int(bs["statistics"]["maximum"] * 1.1)` crashes with `TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'`.

**HIGH-3: `metadata_source` variable assigned but never used**
- File: `services/stac/handler_materialize_item.py`, lines 66, 76, 89
- Dead code that also violates Principle 11 (traceability) -- handler doesn't report which source it read from.

**MEDIUM-1: No bbox validation in `build_stac_item`**
- File: `services/stac/stac_item_builder.py`, line 53
- No length check, no inversion check. `[0, 0, 0, 0]` fallback in `handler_persist_tiled.py:113` produces degenerate point geometry.

**MEDIUM-2: `stac_item_builder.py` missing standard file header**
- File: `services/stac/stac_item_builder.py`, lines 1-9
- Standard 8.2 violation. Compare with `stac_collection_builder.py` which has the correct header.

**MEDIUM-3: `materialize_collection` caller works around `build_stac_collection` temporal limitation**
- File: `services/stac_materialization.py`, lines 477-488
- The caller passes only `temporal_start` then manually patches `temporal_end` afterward. Fragile pattern.

**MEDIUM-4: Shallow copy in `handler_materialize_item.py:105`**
- `dict(stac_item_json)` creates shallow copy; nested dicts are shared. Inconsistent with `copy.deepcopy` used in `stac_materialization.py:153`.

**LOW-1: Duplicate `_SENTINEL_DATETIME` constant**
- File: `stac_preview.py:24` and `stac_item_builder.py:12` -- DRY violation.

**LOW-2: Multi-band non-multispectral falls through silently**
- File: `services/stac_renders.py`, lines 80-142 -- returns `None` implicitly for unrecognized multi-band types.

### ASSUMPTIONS

1. All callers pass bbox as exactly 4-element list.
2. `raster_bands` statistics keys are consistently `min`/`max`/`mean`/`stddev`.
3. Sentinel datetime `0001-01-01T00:00:00Z` is handled by all downstream consumers.
4. Zarr handler's post-hoc mutation of `stac_item_json` (`handler_register.py:195-202`) is safe because dict is not yet shared.

### RECOMMENDATIONS

1. Add explicit validation for partial datetime ranges in `build_stac_item` -- raise `ValueError` if only one of `start_datetime`/`end_datetime` is provided.
2. Validate bbox length and bounds in `build_stac_item`.
3. Add standard file header to `stac_item_builder.py`.
4. Use `copy.deepcopy` in `handler_materialize_item.py:105`.
5. Extract `_SENTINEL_DATETIME` to `core/models/stac.py`.
6. Include `metadata_source` in the handler success result dict.

---

## Beta Review (External Interfaces and Boundaries)

### VERIFIED SAFE

1. **Upsert pattern throughout** (`pgstac_repository.py:132-135`, `295-303`): Both `insert_collection` and `insert_item` use pgSTAC's native `upsert_collection`/`upsert_item` functions. This is idempotent and handles duplicates gracefully. Confirmed safe for concurrent and retry scenarios.

2. **Collection-before-item ordering** (`stac_materialization.py:177-195` and `pgstac_repository.py:271-275`): The repository's `insert_item` verifies collection existence before insertion. The materializer also ensures collection existence at step 5. Belt-and-suspenders approach is correct for pgSTAC's partitioning requirement.

3. **B2C sanitization always runs before pgSTAC write** (`stac_materialization.py:157`): `sanitize_item_properties` strips `geoetl:*` and `processing:*` before every pgSTAC upsert. Confirmed on all code paths: `materialize_to_pgstac:157`, `materialize_item:314`, `_materialize_tiled_items:376`, `_materialize_zarr_item:909`.

4. **SQL parameterization in pgstac_repository.py**: All SQL uses `%s` parameterization. No f-string SQL found in the repository. Standard 1.2 verified.

5. **Dictionary cursor access** (`pgstac_repository.py`): All result access uses `result['key']` pattern (dict access), not positional tuple access. Standard 6.1 verified.

6. **Search registration hash compatibility** (`pgstac_search_registration.py:118`): SHA256 hash uses `sort_keys=True` and compact separators `(',',':')`, matching TiTiler's internal hashing algorithm. Verified compatible.

### FINDINGS

**CRITICAL-1: `_inject_xarray_urls` signature mismatch causes TypeError**
- File: `services/stac_materialization.py`, line 175 vs line 991
- Scenario: When `materialize_to_pgstac` is called with `zarr_prefix` argument, line 175 calls `self._inject_xarray_urls(item, zarr_prefix)` with 2 positional args. But the method signature at line 991 is `def _inject_xarray_urls(self, stac_item_json: dict) -> None:` -- only 1 parameter.
- Impact: `TypeError: _inject_xarray_urls() takes 2 positional arguments but 3 were given`. Any zarr materialization through the Epoch 5 `materialize_to_pgstac` path crashes. Note: The Epoch 4 path at line 912 calls `self._inject_xarray_urls(stac_item_json)` with 1 arg -- that path works.

**HIGH-1: `get_collection` returns None on DB error, triggering spurious collection auto-create**
- File: `infrastructure/pgstac_repository.py`, lines 344-346 and `services/stac_materialization.py`, line 178
- Scenario: If the database connection fails or times out during `get_collection`, the method catches the exception, logs it, and returns `None`. The caller at `materialize_to_pgstac:178` interprets `None` as "collection doesn't exist" and auto-creates a new one. A transient DB error can cause a redundant collection upsert with placeholder extent data.
- Impact: Violates Principle 1 (silent accommodation). The upsert is idempotent so no data corruption, but it masks the real error and wastes a write cycle.

**HIGH-2: Non-transactional collection-create + item-upsert in `materialize_to_pgstac`**
- File: `services/stac_materialization.py`, lines 177-195
- Scenario: Steps 5 and 6 are separate database connections (each `insert_collection` and `insert_item` call opens/closes its own connection). If the process crashes between step 5 (collection created) and step 6 (item upserted), an empty collection shell remains in pgSTAC.
- Impact: Orphaned empty collections. The `materialize_release` method at lines 535-561 has cleanup logic (ADV-17) for this scenario, but `materialize_to_pgstac` (the Epoch 5 path used by DAG handlers) does not.

**HIGH-3: `_is_vector_release` fallback heuristic masks errors**
- File: `services/stac_materialization.py`, lines 860-869
- Scenario: If the `asset_repo.get_by_id()` call fails (DB error), the fallback checks `not release.blob_path and not release.stac_item_json`. A raster release with a transient DB error and no cached stac_item_json would be misclassified as vector and skipped.
- Impact: Raster data silently not materialized to STAC. Violates Principle 1.

**MEDIUM-1: Exception swallowing in `_inject_titiler_urls`**
- File: `services/stac_materialization.py`, lines 988-989
- Scenario: If `config.titiler_base_url` is not set or URL construction fails, the exception is caught and logged as warning. The STAC item goes to pgSTAC without TiTiler URLs.
- Impact: Items in pgSTAC lack visualization links. TiTiler can still serve them via direct query, but discovery is degraded. The "non-fatal" classification is debatable -- for B2C consumers, missing visualization links may be a significant usability failure.

**MEDIUM-2: `compute_collection_extent` reads bbox from `content` JSONB, not from `bbox` column**
- File: `infrastructure/pgstac_repository.py`, lines 728-742
- Scenario: pgSTAC stores bbox in a dedicated column AND in the content JSONB. The method reads from `content->'bbox'` which could diverge from the actual geometry column if items were inserted/updated via different paths.
- Impact: Collection extent could be incorrect if content JSONB bbox doesn't match the actual geometry. Low probability since upsert_item maintains both, but worth noting.

**MEDIUM-3: Search registration only for multi-item collections**
- File: `services/stac/handler_materialize_collection.py`, lines 67-84
- Scenario: Search registration only triggers when `item_count > 1`. Single-item collections get no search registered. If a collection starts with 1 item and later grows, the search is registered on the next `materialize_collection` call.
- Impact: TiTiler mosaic preview not available for single-item collections until a second item is added. By design (single COG uses direct item URL), but the transition from single to multi-item may have a gap.

### RISKS

1. **Connection pool exhaustion under concurrent materialization**: Each `PgStacRepository` method opens a new connection via `_get_connection()`. If multiple DAG handlers materialize items concurrently (fan-out), each opens multiple connections (get_collection + insert_collection + collection_exists + insert_item). With 24 tiles, that's potentially 96+ sequential connections.

2. **pgSTAC function behavior on schema changes**: The repository calls pgSTAC functions (`upsert_collection`, `upsert_item`) directly. If pgSTAC is upgraded and these functions change signature, the code silently breaks with cryptic database errors.

3. **TiTiler URL injection depends on config availability**: `_inject_titiler_urls` at line 938-940 imports and calls `get_config()`. In Docker worker context, config initialization may differ from Function App context. If `titiler_base_url` is not set, URLs are silently omitted.

### EDGE CASES

1. **Empty `stac_item_json` in cog_metadata** (`handler_materialize_item.py:74`): The check `cog_metadata.get("stac_item_json")` is truthy-based. An empty dict `{}` would pass this check, leading to a STAC item with no properties, no assets, and no geometry being upserted to pgSTAC. Likelihood: LOW. Severity: MEDIUM.

2. **Concurrent first-item materialization for same collection**: Two workers simultaneously materialize the first item for a collection. Both see `get_collection` return None. Both auto-create the collection. The second upsert wins with its bbox. The first item's bbox is used for the collection, then overwritten by the second. Likelihood: LOW (DAG serializes per-collection). Severity: LOW (upsert is idempotent).

3. **`search_registration` failure leaves collection without search_id**: The search registration at `handler_materialize_collection.py:81-84` catches exceptions and logs a warning. If pgSTAC searches table is corrupted, tiled collections will have no mosaic preview URL, but no retry mechanism exists. Likelihood: LOW. Severity: MEDIUM.

4. **`compute_collection_extent` with sentinel datetimes**: If all items use sentinel datetime `0001-01-01T00:00:00Z`, the temporal extent will be `["0001-01-01T00:00:00Z", "0001-01-01T00:00:00Z"]`. TiTiler may render this correctly but STAC clients could misinterpret the temporal range. Likelihood: MEDIUM. Severity: LOW.

---

## Gamma Analysis (Contradictions, Blind Spots, Agreement)

### Priority Files (under-cited by Alpha and Beta)
- `services/stac/stac_preview.py` -- minimal coverage by either reviewer
- `services/stac/__init__.py` -- not reviewed
- `core/models/stac.py` -- Alpha cited constants but neither reviewed the Pydantic models

### CONTRADICTIONS

1. **Alpha MEDIUM-4 vs Beta's upsert safety**: Alpha flagged the shallow copy in `handler_materialize_item.py:105` as dangerous. However, Beta confirmed that `materialize_to_pgstac` at line 153 performs `copy.deepcopy`. The shallow copy is therefore redundant-but-not-harmful -- the materializer's deep copy is the effective barrier. The real risk is if someone calls `materialize_to_pgstac` without passing through the materializer. **Resolution**: Alpha's concern is valid as a defense-in-depth issue but not currently exploitable. MEDIUM is appropriate.

### AGREEMENT REINFORCEMENT

1. **Both identified Principle 1 violations in error masking**: Alpha flagged silent datetime fallthrough (HIGH-1). Beta flagged `get_collection` returning None on error (HIGH-1) and `_is_vector_release` fallback (HIGH-3). All three are instances of the same pattern: silent accommodation that masks failures. **Confidence: CONFIRMED.**

2. **Both noted the importance of the upsert pattern**: Alpha's STRENGTH-1 (pure functions) and Beta's VERIFIED SAFE-1 (upsert idempotency) converge on the same conclusion: the consolidation is architecturally sound. The write path is correct by construction.

### BLIND SPOTS

**BLIND-1: `_inject_xarray_urls` signature mismatch is the highest-severity finding (CRITICAL)**
- File: `services/stac_materialization.py`, line 175 vs 991
- Beta found this. Alpha would not have seen it (external interface). This is a crash bug on the Epoch 5 zarr materialization path. **Confidence: CONFIRMED** -- traced both call sites (line 175: 2 args, line 912: 1 arg, definition at 991: 1 param).

**BLIND-2: `stac_preview.py` builds items without render extension or projection**
- File: `services/stac/stac_preview.py`, lines 28-55
- Neither reviewer deeply analyzed preview items. The preview builder produces minimal items with no `properties.renders`, no `proj:epsg`, and no `raster:bands`. TiTiler can still serve these (it reads COG headers directly), but the items will not have auto-rendering via the render extension. This is by design (preview items are replaced at approval time), but the gap should be documented.
- **Confidence: CONFIRMED** -- read file, verified no render/projection properties.

**BLIND-3: No validation of `stac_item_json` structure before pgSTAC write**
- File: `services/stac_materialization.py:195` (upsert call)
- Neither reviewer flagged that `materialize_to_pgstac` does not validate the STAC item structure before writing to pgSTAC. `core/models/stac.py` has `STACItemCore` Pydantic model (line 311) specifically for validation, but it is never called in the materialization path. A malformed item (missing `type`, `geometry`, or `bbox`) would be passed to pgSTAC's `upsert_item`, which may silently accept it or crash with an unhelpful error.
- **Confidence: PROBABLE** -- `STACItemCore` exists and is exported but grep shows no import in materialization code.

**BLIND-4: `services/stac/__init__.py` is a single comment line**
- File: `services/stac/__init__.py`, line 1: `# STAC composable handlers (v0.10.6)`
- Neither reviewer flagged that the `services/stac/` package has no exports, no `__all__`, and no handler registration. Handlers `stac_materialize_item` and `stac_materialize_collection` must be registered in `services/__init__.py` -> `ALL_HANDLERS`. Standard 4.2 requires explicit handler registration.
- **Confidence: PROBABLE** -- did not verify `services/__init__.py` registration.

**BLIND-5: Orphaned old builder still called by Epoch 4 code**
- File: `core/models/unified_metadata.py:1362` -- `to_stac_item()` method still exists and is called by `services/service_stac_metadata.py:589` and `services/handler_process_raster_complete.py:1858-1861`. These are Epoch 4 paths marked with `TODO(v0.11.0)` comments. Not a bug (Epoch 4 is frozen per Standard 5.4), but the consolidation is incomplete until v0.11.0 removes these paths.
- **Confidence: CONFIRMED** -- grep verified both call sites and the TODO comments.

### SEVERITY RECALIBRATION

| ID | Source | Original | Recalibrated | Confidence | Rationale |
|----|--------|----------|-------------|------------|-----------|
| Beta-C1 | `_inject_xarray_urls` signature mismatch | CRITICAL | **CRITICAL** | CONFIRMED | Crash bug on zarr Epoch 5 path |
| Alpha-H1 | Partial datetime silently drops to sentinel | HIGH | **HIGH** | CONFIRMED | Principle 1 violation, data loss |
| Alpha-H2 | `_compute_renders` crash on None stats | HIGH | **MEDIUM** | PROBABLE | Only triggers if stats keys missing; callers typically provide valid stats |
| Alpha-H3 | `metadata_source` dead code | HIGH | **LOW** | CONFIRMED | Dead code, no functional impact |
| Beta-H1 | `get_collection` returns None on DB error | HIGH | **HIGH** | CONFIRMED | Silent accommodation, Principle 1 |
| Beta-H2 | Non-transactional collection+item | HIGH | **MEDIUM** | CONFIRMED | Idempotent upsert mitigates; orphan is recoverable |
| Beta-H3 | `_is_vector_release` fallback heuristic | HIGH | **HIGH** | CONFIRMED | Silent data loss path |
| Alpha-M1 | No bbox validation | MEDIUM | **MEDIUM** | CONFIRMED | Degenerate geometry possible |
| Alpha-M2 | Missing file header | MEDIUM | **LOW** | CONFIRMED | Formatting only |
| Alpha-M4 | Shallow copy | MEDIUM | **LOW** | CONFIRMED | Materializer deep copies anyway |
| Beta-M1 | TiTiler URL exception swallowing | MEDIUM | **MEDIUM** | CONFIRMED | B2C usability impact |
| BLIND-3 | No STAC validation before pgSTAC write | NEW | **MEDIUM** | PROBABLE | `STACItemCore` exists but unused |
| BLIND-5 | Orphaned `to_stac_item()` in Epoch 4 | NEW | **LOW** | CONFIRMED | By design, frozen per Standard 5.4 |

---

## Delta Report (Final Arbiter)

### EXECUTIVE SUMMARY

The STAC consolidation is architecturally sound. The canonical `build_stac_item` and `build_stac_collection` functions are pure, well-structured, and correctly used by all Epoch 5 callers. The materialization path through `STACMaterializer.materialize_to_pgstac()` correctly sanitizes, auto-creates collections, and upserts items. One CRITICAL crash bug exists: the `_inject_xarray_urls` method signature mismatch at `stac_materialization.py:175` will crash all zarr items going through the Epoch 5 `materialize_to_pgstac` path. Three HIGH findings represent Principle 1 (explicit failure) violations where errors are silently accommodated. The Epoch 4 legacy paths (`to_stac_item()`, `_materialize_zarr_item`) are correctly frozen per Standard 5.4 and will be removed at v0.11.0.

### TOP 5 FIXES

#### Fix 1: `_inject_xarray_urls` signature mismatch (CRITICAL)
- **WHAT**: `materialize_to_pgstac` calls `_inject_xarray_urls(item, zarr_prefix)` with 2 args, but the method only accepts 1.
- **WHY**: TypeError crash on every zarr materialization through the Epoch 5 path. Complete blocker for zarr STAC via DAG workflows.
- **WHERE**: `services/stac_materialization.py`, `_inject_xarray_urls`, line 175 (call site) and line 991 (definition).
- **HOW**: Either (a) remove the `zarr_prefix` argument from the call at line 175 (the method extracts the URL from the item's assets internally), or (b) add `zarr_prefix` parameter to the method signature if it's needed for URL construction.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low -- the Epoch 4 call at line 912 already works with 1 arg, confirming the method doesn't need `zarr_prefix`.

#### Fix 2: `get_collection` should raise on DB error, not return None (HIGH)
- **WHAT**: `PgStacRepository.get_collection()` returns `None` on database errors, indistinguishable from "not found."
- **WHY**: A transient DB error causes `materialize_to_pgstac` to auto-create a collection with placeholder extent, masking the real failure. Principle 1 violation.
- **WHERE**: `infrastructure/pgstac_repository.py`, `get_collection`, lines 344-346.
- **HOW**: Remove the `except Exception` block. Let DB errors propagate. The caller (`materialize_to_pgstac`) already has a top-level try/except that will catch and report the error correctly. Alternatively, split into two methods: `get_collection` (raises on error) and `get_collection_or_none` (returns None only for "not found").
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Medium -- callers that rely on None return for error cases must be audited. However, `materialize_to_pgstac` and `materialize_release` both have top-level exception handling.

#### Fix 3: `_is_vector_release` fallback heuristic should raise, not guess (HIGH)
- **WHAT**: When the asset DB lookup fails, the method uses a heuristic (`not blob_path and not stac_item_json`) to guess if a release is vector. This can misclassify raster releases.
- **WHY**: A DB error could cause raster data to be silently skipped from STAC materialization. Principle 1 violation.
- **WHERE**: `services/stac_materialization.py`, `_is_vector_release`, lines 860-869.
- **HOW**: Remove the fallback heuristic. If the DB lookup fails, let the exception propagate or return `False` (assume raster, the common case -- failing to skip a vector release is less harmful than failing to materialize a raster one).
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low -- the worst case is attempting STAC materialization on a vector release, which will fail gracefully (no stac_item_json).

#### Fix 4: Validate partial datetime ranges in `build_stac_item` (HIGH)
- **WHAT**: Providing `start_datetime` without `end_datetime` (or vice versa) silently falls through to sentinel datetime, discarding valid temporal data.
- **WHY**: Principle 1 violation. Callers that make a mistake get no indication their temporal data was dropped.
- **WHERE**: `services/stac/stac_item_builder.py`, `build_stac_item`, lines 63-71.
- **HOW**: Add a guard: `if bool(start_datetime) != bool(end_datetime): raise ValueError("start_datetime and end_datetime must both be provided or both be None")`.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low -- this is input validation on a pure function. If any caller legitimately provides only one, they'll get an explicit error telling them to fix it.

#### Fix 5: Add STAC item validation before pgSTAC write (MEDIUM)
- **WHAT**: `materialize_to_pgstac` does not validate the STAC item structure before upserting to pgSTAC. `STACItemCore` Pydantic model exists but is never used.
- **WHY**: Malformed items (missing geometry, empty properties) could be written to pgSTAC, causing TiTiler rendering failures or silent data corruption. Principle 10 (explicit data contracts).
- **WHERE**: `services/stac_materialization.py`, `materialize_to_pgstac`, between lines 157 and 195 (after sanitize, before upsert).
- **HOW**: Add `from core.models.stac import STACItemCore; STACItemCore(**item)` validation call before the upsert. Catch `ValidationError` and return `{"success": False, "error": "Invalid STAC item: ..."}`.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low -- purely additive validation. The Pydantic model already exists and is tested.

### ACCEPTED RISKS

1. **Non-transactional collection+item write** (Beta-H2): Steps 5 and 6 in `materialize_to_pgstac` are separate DB connections. An orphaned empty collection is possible but recoverable via `action=ensure` or re-materialization. The upsert pattern makes this idempotent. **Revisit if**: concurrent materialization becomes common (e.g., 100+ parallel fan-out tiles).

2. **Preview items lack render extension** (BLIND-2): `build_preview_item` produces minimal items without renders or projection. By design -- they're replaced at approval time. **Revisit if**: preview items become user-visible or TiTiler auto-rendering changes.

3. **Orphaned `to_stac_item()` in Epoch 4** (BLIND-5): `RasterMetadata.to_stac_item()` and `VectorMetadata.to_stac_item()` are still called by Epoch 4 code. Frozen per Standard 5.4. **Revisit**: v0.11.0 when Epoch 4 is retired.

4. **Connection pool pressure from per-operation connections** (Beta Risk 1): Each repository method opens a new connection. With 24-tile fan-out, materialization opens ~96 sequential connections. Acceptable at current scale. **Revisit if**: tile counts exceed 100 or concurrent workflows increase.

5. **Search registration failure is non-fatal** (Beta Edge 3): If pgSTAC searches table is corrupted, tiled collections lose mosaic preview but items are still accessible. The warning log is sufficient. **Revisit if**: mosaic preview becomes a hard requirement for B2C consumers.

### ARCHITECTURE WINS

1. **Pure function builders**: `build_stac_item`, `build_stac_collection`, and `build_preview_item` are all pure functions with no I/O, no side effects, and explicit typed parameters. This is textbook Principle 6 (composable atomic units). Preserve this pattern.

2. **Single write path**: `materialize_to_pgstac()` is the canonical pgSTAC write path for Epoch 5. The 6-step sequence (copy, sanitize, stamp, inject URLs, ensure collection, upsert) is well-ordered and documented. All DAG handlers use this path.

3. **B2C sanitization as structural guarantee**: The `sanitize_item_properties` method is called on every path before pgSTAC write. Internal provenance (`geoetl:*`, `processing:*`) never leaks to consumers. This is the right architectural boundary.

4. **Idempotent upserts**: Using pgSTAC's `upsert_collection`/`upsert_item` functions instead of `create_*` means the entire materialization is safely re-runnable. Job resubmission, crash recovery, and parallel execution all work correctly.

5. **Clean consolidation**: The deletion of `build_raster_stac_collection()` (confirmed at `stac_collection.py:273-274`) and the TODO annotations on Epoch 4 `to_stac_item()` (at `unified_metadata.py:1360`) show a disciplined strangler fig migration. Old code is frozen, not deleted prematurely.
