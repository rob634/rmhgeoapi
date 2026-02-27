# Submit Workflow Adversarial Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 5 bugs identified by the adversarial review of `/api/platform/submit` (see `docs/agent_review/SUBMISSION.md`).

**Architecture:** All fixes are surgical — model guard, repository UPDATE, trigger one-liner, and error message sanitization. No new modules, no new patterns. TDD: write the failing test first, then fix.

**Tech Stack:** Python 3.12, Pydantic, psycopg2, pytest. Tests are pure unit tests — no DB, no mocks for Tasks 1-3.

---

## Baseline

All 26 existing tests pass:

```bash
conda run -n azgeo pytest tests/unit/test_models_asset.py tests/unit/test_models_release.py -v
```

---

### Task 1: Block overwrite while PROCESSING (FIX 4)

**Files:**
- Modify: `core/models/asset.py:643-645`
- Test: `tests/unit/test_models_asset.py`

**Why first:** This is a pure model method with no dependencies — easiest to TDD. FIX 2/3 depend on this guard being correct.

**Step 1: Write the failing tests**

Add to `tests/unit/test_models_asset.py`:

```python
class TestReleaseCanOverwrite:
    """Tests for AssetRelease.can_overwrite() state guard."""

    def test_pending_review_and_pending_allows_overwrite(self):
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.PENDING_REVIEW,
            processing_status=ProcessingStatus.PENDING
        ))
        assert release.can_overwrite() is True

    def test_rejected_and_pending_allows_overwrite(self):
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.REJECTED,
            processing_status=ProcessingStatus.PENDING
        ))
        assert release.can_overwrite() is True

    def test_rejected_and_failed_allows_overwrite(self):
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.REJECTED,
            processing_status=ProcessingStatus.FAILED
        ))
        assert release.can_overwrite() is True

    def test_pending_review_and_processing_blocks_overwrite(self):
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.PENDING_REVIEW,
            processing_status=ProcessingStatus.PROCESSING
        ))
        assert release.can_overwrite() is False

    def test_approved_blocks_overwrite(self):
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.APPROVED,
            processing_status=ProcessingStatus.COMPLETED
        ))
        assert release.can_overwrite() is False

    def test_revoked_blocks_overwrite(self):
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.REVOKED,
        ))
        assert release.can_overwrite() is False
```

Imports needed at top of file (add `AssetRelease, ApprovalState, ProcessingStatus` to existing import):

```python
from core.models.asset import Asset, AssetRelease, ApprovalState, ProcessingStatus
from tests.factories.model_factories import make_asset, make_asset_release
```

**Step 2: Run tests to verify the PROCESSING test fails**

```bash
conda run -n azgeo pytest tests/unit/test_models_asset.py::TestReleaseCanOverwrite -v
```

Expected: `test_pending_review_and_processing_blocks_overwrite` FAILS (returns True, expected False). Other tests pass.

**Step 3: Implement the fix**

In `core/models/asset.py`, replace lines 643-645:

```python
# BEFORE:
def can_overwrite(self) -> bool:
    """Check if this release can be overwritten with new data."""
    return self.approval_state in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED)

# AFTER:
def can_overwrite(self) -> bool:
    """Check if this release can be overwritten with new data."""
    if self.approval_state not in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED):
        return False
    if self.processing_status == ProcessingStatus.PROCESSING:
        return False
    return True
```

**Step 4: Update error message in asset_service.py**

In `services/asset_service.py`, line 296, update the error message:

```python
# BEFORE:
"pending_review or rejected",

# AFTER:
"pending_review or rejected (and not actively processing)",
```

**Step 5: Run tests to verify all pass**

```bash
conda run -n azgeo pytest tests/unit/test_models_asset.py::TestReleaseCanOverwrite -v
```

Expected: All 6 PASS.

**Step 6: Commit**

```bash
git add core/models/asset.py services/asset_service.py tests/unit/test_models_asset.py
git commit -m "Fix can_overwrite() to block overwrite while PROCESSING

Adversarial review FIX 4: can_overwrite() only checked approval_state,
allowing overwrite while a job is actively PROCESSING. Old job's side
effects (blob writes, PostGIS inserts) would contaminate new release.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Reset approval_state and clear job_id on overwrite (FIX 2 + FIX 3)

**Files:**
- Modify: `infrastructure/release_repository.py:909-948` (`update_overwrite` method)
- Test: `tests/unit/test_models_release.py` (new test class for overwrite SQL contract)

**Why combined:** Both fixes touch the same UPDATE statement. Testing the SQL itself requires a DB, so we test the contract at the model level — verify the factory can represent the "stale after overwrite" state, then the integration fix is in the SQL.

**Step 1: Write the contract test**

Add to `tests/unit/test_models_release.py`:

```python
class TestOverwriteResetContract:
    """Verify that overwrite resets all lifecycle fields.

    These tests validate the contract: after overwrite, a release must
    have PENDING processing, PENDING_REVIEW approval, and no stale job_id.
    The actual SQL is in release_repository.update_overwrite().
    """

    def test_rejected_release_fields_that_must_reset(self):
        """Document the fields that update_overwrite MUST reset."""
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.REJECTED,
            processing_status=ProcessingStatus.FAILED,
            job_id="stale-job-abc123",
        ))
        # Pre-conditions: stale state
        assert release.approval_state == ApprovalState.REJECTED
        assert release.processing_status == ProcessingStatus.FAILED
        assert release.job_id == "stale-job-abc123"

        # Contract: after overwrite these must be reset to:
        expected_approval = ApprovalState.PENDING_REVIEW
        expected_processing = ProcessingStatus.PENDING
        expected_job_id = None

        # These are the values update_overwrite SQL must SET
        assert expected_approval == ApprovalState.PENDING_REVIEW
        assert expected_processing == ProcessingStatus.PENDING
        assert expected_job_id is None
```

Add `ProcessingStatus` to the import line:

```python
from core.models.asset import AssetRelease, ApprovalState, ProcessingStatus
```

**Step 2: Run test to verify it passes (contract test, not behavior)**

```bash
conda run -n azgeo pytest tests/unit/test_models_release.py::TestOverwriteResetContract -v
```

Expected: PASS (this documents the contract).

**Step 3: Implement the SQL fix**

In `infrastructure/release_repository.py`, replace the `update_overwrite` method (lines 909-948):

```python
# BEFORE (lines 927-941):
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET revision = %s,
                            processing_status = %s,
                            processing_started_at = NULL,
                            processing_completed_at = NULL,
                            last_error = NULL,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (revision, ProcessingStatus.PENDING, release_id)
                )

# AFTER:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET revision = %s,
                            processing_status = %s,
                            approval_state = %s,
                            rejection_reason = NULL,
                            reviewer = NULL,
                            reviewed_at = NULL,
                            job_id = NULL,
                            processing_started_at = NULL,
                            processing_completed_at = NULL,
                            last_error = NULL,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (revision, ProcessingStatus.PENDING, ApprovalState.PENDING_REVIEW, release_id)
                )
```

Add `ApprovalState` to the imports at the top of `release_repository.py` if not already present:

```python
from core.models.asset import ApprovalState, ProcessingStatus
```

**Step 4: Run all tests**

```bash
conda run -n azgeo pytest tests/unit/test_models_release.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add infrastructure/release_repository.py tests/unit/test_models_release.py
git commit -m "Fix update_overwrite to reset approval_state, job_id, and reviewer fields

Adversarial review FIX 2+3: update_overwrite() only reset processing_status
but left approval_state as REJECTED and stale job_id intact. Rejected
releases that were resubmitted via overwrite would never re-enter the
approval queue, and the stale job_id caused incorrect release lookups.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Fix config NameError in submit.py (FIX 1)

**Files:**
- Modify: `triggers/platform/submit.py:168`

**Why separate:** One-line fix. No unit test needed — the function signature of `translate_to_coremachine` already has `cfg=None` default. The NameError is self-evident from reading the code.

**Step 1: Verify the bug exists**

```bash
conda run -n azgeo python -c "
import ast, sys
with open('triggers/platform/submit.py') as f:
    tree = ast.parse(f.read())
# Check that 'config' is not assigned in the module scope
assigns = [n.targets[0].id for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)]
if 'config' in assigns:
    print('SKIP: config is assigned somewhere')
    sys.exit(1)
else:
    print('CONFIRMED: no config variable in module scope')
"
```

**Step 2: Apply the fix**

In `triggers/platform/submit.py`, line 168:

```python
# BEFORE:
job_type, job_params = translate_to_coremachine(platform_req, config)

# AFTER:
job_type, job_params = translate_to_coremachine(platform_req)
```

**Step 3: Run full test suite to verify no regressions**

```bash
conda run -n azgeo pytest tests/unit/ -v
```

Expected: All pass.

**Step 4: Commit**

```bash
git add triggers/platform/submit.py
git commit -m "Fix config NameError that crashes every platform submit

Adversarial review FIX 1 (CRITICAL): submit.py line 168 passed bare
'config' variable to translate_to_coremachine(), but 'config' was never
defined in the module. translate_to_coremachine() already has cfg=None
default that calls get_config() internally.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Sanitize error responses (FIX 5)

**Files:**
- Modify: `triggers/platform/submit.py:379` and `triggers/platform/submit.py:422-424`

**Step 1: Apply the fix at line 379**

```python
# BEFORE (line 378-382):
        except Exception as asset_err:
            logger.error(f"Asset/Release creation failed: {asset_err}", exc_info=True)
            return error_response(
                f"Failed to create asset/release record: {asset_err}",
                "AssetCreationError",
                status_code=500
            )

# AFTER:
        except Exception as asset_err:
            logger.error(f"Asset/Release creation failed: {asset_err}", exc_info=True)
            return error_response(
                "Failed to create asset/release record. Check server logs for details.",
                "AssetCreationError",
                status_code=500
            )
```

**Step 2: Apply the fix at lines 422-424**

```python
# BEFORE (lines 422-424):
    except Exception as e:
        logger.error(f"Platform request failed: {e}", exc_info=True)
        return error_response(str(e), type(e).__name__)

# AFTER:
    except Exception as e:
        logger.error(f"Platform request failed: {e}", exc_info=True)
        return error_response(
            "An internal error occurred. Check server logs for details.",
            "InternalError"
        )
```

**Step 3: Run full test suite**

```bash
conda run -n azgeo pytest tests/unit/ -v
```

Expected: All pass.

**Step 4: Commit**

```bash
git add triggers/platform/submit.py
git commit -m "Sanitize error responses to prevent internal detail leakage

Adversarial review FIX 5 (MEDIUM): catch-all handlers passed raw
exception strings (containing DB hostnames, SQL queries, internal
paths) to HTTP callers. Now returns generic messages; details remain
in server logs via exc_info=True.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Final verification

**Step 1: Run full unit test suite**

```bash
conda run -n azgeo pytest tests/unit/ -v
```

Expected: All pass including the new `TestReleaseCanOverwrite` and `TestOverwriteResetContract` classes.

**Step 2: Update adversarial history**

Add entry to `ADVERSARIAL_ANALYSIS_HISTORY.md`:

```markdown
### 4. Platform Submit Workflow (26 FEB 2026)
- **Scope**: 12 files, ~6,700 LOC — submit endpoint, Asset/Release lifecycle, translation layer
- **Pipeline**: Omega → Alpha + Beta (parallel) → Gamma → Delta
- **Report**: `docs/agent_review/SUBMISSION.md`
- **Fixes found**: 5 (1 critical, 3 high, 1 medium)
- **Fixes applied**: 5/5
```

**Step 3: Commit history update**

```bash
git add ADVERSARIAL_ANALYSIS_HISTORY.md
git commit -m "Update adversarial analysis history with submit workflow review

Co-Authored-By: Claude <noreply@anthropic.com>"
```
