# repositories/ vs infrastructure/ - Duplicate Analysis

**Date**: 4 OCT 2025
**Critical Finding**: `repositories/` folder appears to be DUPLICATE/LEGACY

---

## 🚨 Key Discovery

### Both folders contain IDENTICAL file structure:
```
repositories/               infrastructure/
├── __init__.py            ├── __init__.py
├── base.py                ├── base.py
├── blob.py                ├── blob.py
├── factory.py             ├── factory.py
├── interface_repository.py├── interface_repository.py (with IQueueRepository)
├── jobs_tasks.py          ├── jobs_tasks.py
├── postgresql.py          ├── postgresql.py
├── queue.py               ├── queue.py
├── service_bus.py         ├── service_bus.py
└── vault.py               └── vault.py
```

**10 identical file names, but contents DIFFER!**

---

## 📊 Import Analysis

### Active Code (7 imports) - Uses `infrastructure/`:
```python
./core/state_manager.py:      from infrastructure import RepositoryFactory, StageCompletionRepository
./core/machine.py:            from infrastructure import RepositoryFactory
./function_app.py:            from infrastructure import RepositoryFactory
./function_app.py:            from infrastructure import PostgreSQLRepository
./services/container_list.py: from infrastructure.blob import BlobRepository
./services/container_summary.py: from infrastructure.blob import BlobRepository
./services/service_blob.py:   from infrastructure import RepositoryFactory
```

### Archive/Legacy Code (5 imports) - Uses `repositories/`:
```python
./archive/controller_stac_setup.py:  from repositories import RepositoryFactory
./archive/controller_service_bus_container.py: from repositories.factory import RepositoryFactory
./archive/controller_base.py:        from repositories import RepositoryFactory
./archive/controller_base.py:        from repositories import StageCompletionRepository
./local/test_local_database.py:      from repositories import RepositoryFactory
```

---

## 🔍 Critical Findings

### 1. Active Code Uses `infrastructure/`
**All production code imports from `infrastructure/`:**
- Core orchestration (machine.py, state_manager.py)
- Main entry point (function_app.py)
- Services (container_list.py, container_summary.py, service_blob.py)

### 2. Only Archive Uses `repositories/`
**Only legacy/archived code imports from `repositories/`:**
- Archived controllers (controller_base.py, controller_stac_setup.py)
- One local test file (test_local_database.py)

### 3. Cross-Dependency! ⚠️
**repositories/ imports FROM infrastructure/**:
```python
repositories/queue.py:        from infrastructure.interface_repository import IQueueRepository
repositories/service_bus.py:  from infrastructure.interface_repository import IQueueRepository
```

**This means `repositories/` is DEPENDENT on `infrastructure/`!**

---

## 🎯 Conclusion: repositories/ is LEGACY

### Evidence:
1. ✅ **Active code uses `infrastructure/`** (7 imports)
2. ✅ **Only archive code uses `repositories/`** (4 imports)
3. ✅ **`repositories/` depends on `infrastructure/`** (imports interfaces from it)
4. ✅ **Files differ** (not exact copies, likely outdated versions)
5. ✅ **One local test file** uses repositories/ (test_local_database.py - can be updated)

### Recommendation: DELETE `repositories/` folder

---

## 📋 Migration Required

### Before Deletion, Update:
1. **local/test_local_database.py**
   ```python
   # CHANGE:
   from repositories import RepositoryFactory

   # TO:
   from infrastructure import RepositoryFactory
   ```

### Archive References (Already in archive/):
- No changes needed - archive code can remain as-is

---

## 🚀 Execution Plan

### Step 1: Update local test file
```bash
sed -i '' 's/from repositories/from infrastructure/g' local/test_local_database.py
```

### Step 2: Test import
```bash
python3 -c "from infrastructure import RepositoryFactory; print('✅ Import works')"
```

### Step 3: Delete repositories/ folder
```bash
rm -rf repositories/
```

**Result**: 13 → 12 root folders

---

## 📊 Expected Impact

### Before:
- 2 duplicate repository folders (confusing)
- Legacy code uses old `repositories/`
- Active code uses new `infrastructure/`

### After:
- 1 repository folder (`infrastructure/`)
- Clear single source of truth
- No confusion about which to use

### Folder Count:
- **Before**: 13 root folders
- **After**: 12 root folders
- **Reduction**: 1 folder (duplicate eliminated)

---

## ✅ Verification Steps

After deletion:
1. Check no active code imports from repositories/
   ```bash
   grep -r "from repositories" --include="*.py" . | grep -v "__pycache__" | grep -v "archive"
   # Should return ONLY local/test_local_database.py (which we'll update first)
   ```

2. Verify infrastructure/ has all necessary files
   ```bash
   ls infrastructure/
   # Should have: __init__.py, base.py, blob.py, factory.py, interface_repository.py,
   #              jobs_tasks.py, postgresql.py, queue.py, service_bus.py, vault.py
   ```

3. Test imports work
   ```bash
   python3 -c "from infrastructure import RepositoryFactory; print('✅')"
   ```

---

## 🎯 Final Answer

**Q: Is repositories/ being used?**

**A: NO - It's legacy code!**
- Active production code uses `infrastructure/`
- Only archived code uses `repositories/`
- `repositories/` even imports FROM `infrastructure/` (depends on it!)
- Safe to delete after updating 1 local test file

**Action: Delete `repositories/` folder (after updating local/test_local_database.py)**
