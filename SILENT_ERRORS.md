# SILENT_ERRORS.md - Exception Handling Violations

**Created**: 23 DEC 2025
**Last Updated**: 23 DEC 2025
**Purpose**: Working document for fixing silent exception patterns
**Principle**: Every `except` block MUST log the exception. No silent failures.

---

## Status Summary

| Category | Total | Fixed | Remaining |
|----------|-------|-------|-----------|
| CRITICAL (bare `except: pass`) | 6 | 6 | 0 |
| HIGH (silent fallback) | 2 | 2 | 0 |
| MEDIUM (`except ValueError: pass`) | 6 | 6 | 0 |
| BONUS (found during review) | 7 | 7 | 0 |
| **TOTAL** | **21** | **21** | **0** |

---

## First Principles Rule

```python
# NEVER DO THIS
except:
    pass

except Exception:
    return fallback_value

except ValueError:
    pass  # "Will be caught later"

# ALWAYS DO THIS
except SpecificException as e:
    logger.error(f"Context about what failed: {e}")
    raise  # or return explicit error
```

---

## CRITICAL: Bare `except:` + `pass` - ALL FIXED

### Promote Workflow - FIXED

| File | Line | Status |
|------|------|--------|
| `triggers/promote.py` | 380-381 | ✅ Fixed - Added `(ValueError, TypeError)` + debug logging |

### Database Infrastructure - FIXED

| File | Line | Status |
|------|------|--------|
| `infrastructure/postgresql.py` | 618-619 | ✅ Fixed - Added `(IndexError, ValueError)` + debug logging |
| `infrastructure/postgresql.py` | 640-641 | ✅ Fixed - Added `(IndexError, ValueError)` + debug logging |

### Service Bus Infrastructure - FIXED

| File | Line | Status |
|------|------|--------|
| `infrastructure/service_bus.py` | 377-378 | ✅ Fixed - Added `Exception` + debug logging |

### Raster Validation Workflow - FIXED

| File | Line | Status |
|------|------|--------|
| `services/raster_validation.py` | 871-872 | ✅ Fixed - Added logger + `(IndexError, AttributeError)` |
| `services/raster_validation.py` | 890-893 | ✅ Fixed - Added `Exception` + debug logging |
| `services/raster_validation.py` | 914-917 | ✅ Fixed - Added `Exception` + debug logging |
| `services/raster_validation.py` | 930-931 | ✅ Fixed - Added `Exception` + debug logging |

---

## HIGH: Silent Fallbacks - ALL FIXED

### Promote/STAC Workflow - FIXED

| File | Line | Status |
|------|------|--------|
| `services/promote_service.py` | 498-508 | ✅ Fixed - Now uses `get_item_by_id` standalone function, checks for error in result |

### H3 Workflow - FIXED (No Fallback Design)

| File | Line | Status |
|------|------|--------|
| `jobs/bootstrap_h3_land_grid_pyramid.py` | 155-160 | ✅ Fixed - Now raises `ValueError` if no system dataset, NO FALLBACK |

---

## BONUS: Additional Fixes (Found During Review)

| File | Line | Status |
|------|------|--------|
| `infrastructure/duckdb.py` | 628-629 | ✅ Fixed - Added `Exception` + debug logging |
| `triggers/health.py` | 629-630 | ✅ Fixed - Added `Exception` + debug logging |
| `triggers/health.py` | 636-637 | ✅ Fixed - Added `Exception` + debug logging |
| `triggers/health.py` | 647-648 | ✅ Fixed - Added `Exception` + debug logging |
| `triggers/admin/servicebus.py` | 530-531 | ✅ Fixed - Added `Exception` + debug logging (2 occurrences) |
| `triggers/admin/db_tables.py` | 406-407 | ✅ Fixed - Added `(json.JSONDecodeError, TypeError)` + debug logging |

---

## MEDIUM: `except ValueError: pass` - ALL FIXED

### OGC Features API - FIXED (OGC Spec Compliant)

Per OGC API Features Core spec requirement `/req/core/query-param-invalid`:
"Server SHALL respond with status code 400 if request URI includes a query parameter with an INVALID value"

| File | Line | Context | Status |
|------|------|---------|--------|
| `ogc_features/triggers.py` | 459-460 | `limit` param parsing | ✅ Fixed - Returns 400 `InvalidParameterValue` |
| `ogc_features/triggers.py` | 465-466 | `offset` param parsing | ✅ Fixed - Returns 400 `InvalidParameterValue` |
| `ogc_features/triggers.py` | 474-475 | `bbox` param parsing | ✅ Fixed - Returns 400 `InvalidParameterValue` |
| `ogc_features/triggers.py` | 492-493 | `precision` param parsing | ✅ Fixed - Returns 400 `InvalidParameterValue` |
| `ogc_features/triggers.py` | 498-499 | `simplify` param parsing | ✅ Fixed - Returns 400 `InvalidParameterValue` |

**Implementation:**
- Added `InvalidParameterError` exception class with OGC spec reference
- `_parse_query_parameters()` raises on invalid values
- Caller catches and returns OGC-compliant 400 response:
```json
{
  "code": "InvalidParameterValue",
  "description": "Invalid value 'abc' for parameter 'limit': must be a positive integer"
}
```

### Validators - FIXED

| File | Line | Context | Status |
|------|------|---------|--------|
| `infrastructure/validators.py` | 760-761 | `max_size_mb` env var parsing | ✅ Fixed - Raises `ValueError` with clear message |

---

## ACCEPTABLE: Logging Infrastructure (util_logger.py)

The following patterns in `util_logger.py` are **ACCEPTABLE** because:
1. Logging failure should not crash the application
2. These are for optional debug/telemetry features
3. They degrade gracefully without masking business logic errors

---

## Verification

After all fixes, run:
```bash
# Should return 0 results for bare except
grep -rn "except:\s*$" --include="*.py" | grep -v SILENT_ERRORS

# Check for except + pass patterns
grep -rn "except.*:\s*$" --include="*.py" -A1 | grep -E "pass|continue" | grep -v SILENT_ERRORS
```

---

## Related Documentation

- `docs_claude/ARCHITECTURE_REFERENCE.md` - Error Handling Strategy section
- `core/errors.py` - ErrorCode and ErrorClassification enums
