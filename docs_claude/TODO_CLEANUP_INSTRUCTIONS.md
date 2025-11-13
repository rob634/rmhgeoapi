# TODO.md Cleanup - Manual Instructions

**Date**: 11 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Step-by-step instructions for moving completed October items from TODO.md to HISTORY.md

---

## 🎯 Summary

Move **6 completed sections** from TODO.md (lines 3761-5320) to HISTORY.md.

**Why Manual**: TODO.md is 69,429 tokens - too large for automated editing. These instructions guide manual cleanup.

---

## 📋 Sections to Move (with exact line numbers)

### Section 1: Platform Infrastructure-as-Code Migration
- **Start Line**: 3761
- **Header**: `## ✅ COMPLETED: Platform Infrastructure-as-Code Migration (29 OCT 2025)`
- **End Line**: ~4025 (before "Platform Table Renaming")
- **Size**: ~265 lines
- **Date**: 29 OCT 2025

### Section 2: Platform Table Renaming
- **Start Line**: 4026
- **Header**: `## ✅ COMPLETED: Platform Table Renaming (api_requests + orchestration_jobs) (29 OCT 2025)`
- **End Line**: ~4209 (before "Platform SQL Composition")
- **Size**: ~184 lines
- **Date**: 29 OCT 2025

### Section 3: Platform SQL Composition Refactoring
- **Start Line**: 4210
- **Header**: `## ✅ COMPLETED: Platform SQL Composition Refactoring (29 OCT 2025)`
- **End Line**: ~4440 (before next major section)
- **Size**: ~231 lines
- **Date**: 29 OCT 2025

### Section 4: Task ID Architecture Fix
- **Start Line**: ~4943
- **Header**: `## ✅ COMPLETED: Task ID Architecture Fix + CoreMachine Validation (22 OCT 2025)`
- **End Line**: ~5059 (before "Output Folder Control")
- **Size**: ~117 lines
- **Date**: 22 OCT 2025

### Section 5: Output Folder Control
- **Start Line**: ~5060
- **Header**: `## ✅ COMPLETED: Output Folder Control + Vendor Delivery Discovery (20 OCT 2025)`
- **End Line**: ~5178 (before "Logger Standardization")
- **Size**: ~119 lines
- **Date**: 20 OCT 2025

### Section 6: Logger Standardization
- **Start Line**: ~5179
- **Header**: `## ✅ COMPLETED: Logger Standardization (18-19 OCT 2025)`
- **End Line**: ~5254 (before next major section)
- **Size**: ~76 lines
- **Date**: 18-19 OCT 2025

---

## 🛠️ Step-by-Step Cleanup Process

### Step 1: Open Files in Editor

```bash
# Open both files side-by-side in your preferred editor
code docs_claude/TODO.md docs_claude/HISTORY.md
# OR
vim -O docs_claude/TODO.md docs_claude/HISTORY.md
```

### Step 2: Find Insert Point in HISTORY.md

**Location**: After "8 NOV 2025: Raster Pipeline Parameterization" section

**Current HISTORY.md structure**:
```
## 11 NOV 2025: Critical Job Status Bug Fix - QUEUED → FAILED Transition ✅

## 10 NOV 2025: TiTiler URL Generation Fix - Single COG Visualization Working ✅

## 8 NOV 2025: Raster Pipeline Parameterization - `in_memory` and `maxzoom` ✅
<-- INSERT HERE -->

## 7 NOV 2025: Vector Ingest Pipeline Validated Production-Ready 🎉

## 30 OCT 2025: OGC Features API Integration + First Web App! 🎉
```

### Step 3: Copy Sections from TODO.md to HISTORY.md

**Order** (chronological, most recent first):
1. Platform Infrastructure-as-Code (29 OCT) - from TODO line 3761
2. Platform Table Renaming (29 OCT) - from TODO line 4026
3. Platform SQL Composition (29 OCT) - from TODO line 4210
4. Task ID Architecture (22 OCT) - from TODO line ~4943
5. Output Folder Control (20 OCT) - from TODO line ~5060
6. Logger Standardization (18-19 OCT) - from TODO line ~5179

**In HISTORY.md**, insert them in this order (after 8 NOV section):
```markdown
## 8 NOV 2025: Raster Pipeline Parameterization - `in_memory` and `maxzoom` ✅

---

## 29 OCT 2025: Platform Infrastructure-as-Code Migration ✅
[Paste content from TODO.md line 3761]

---

## 29 OCT 2025: Platform Table Renaming (api_requests + orchestration_jobs) ✅
[Paste content from TODO.md line 4026]

---

## 29 OCT 2025: Platform SQL Composition Refactoring ✅
[Paste content from TODO.md line 4210]

---

## 22 OCT 2025: Task ID Architecture Fix + CoreMachine Validation ✅
[Paste content from TODO.md line ~4943]

---

## 20 OCT 2025: Output Folder Control + Vendor Delivery Discovery ✅
[Paste content from TODO.md line ~5060]

---

## 18-19 OCT 2025: Logger Standardization ✅
[Paste content from TODO.md line ~5179]

---

## 7 NOV 2025: Vector Ingest Pipeline Validated Production-Ready 🎉
```

### Step 4: Delete Sections from TODO.md

**Delete these sections** (in TODO.md):
- Lines 3761-~4025 (Platform Infrastructure-as-Code)
- Lines 4026-~4209 (Platform Table Renaming)
- Lines 4210-~4440 (Platform SQL Composition)
- Lines ~4943-~5059 (Task ID Architecture)
- Lines ~5060-~5178 (Output Folder Control)
- Lines ~5179-~5254 (Logger Standardization)

**⚠️ Warning**: Line numbers will shift after each deletion. Delete from bottom to top to avoid confusion:
1. Delete Logger Standardization first (line ~5179)
2. Delete Output Folder Control (line ~5060)
3. Delete Task ID Architecture (line ~4943)
4. Delete Platform SQL Composition (line 4210)
5. Delete Platform Table Renaming (line 4026)
6. Delete Platform Infrastructure-as-Code last (line 3761)

### Step 5: Update TODO.md Header

Change:
```markdown
# Active Tasks

**Last Updated**: 11 NOV 2025 (16:00 UTC)
```

To:
```markdown
# Active Tasks

**Last Updated**: 11 NOV 2025 (17:30 UTC) - Moved 6 completed October items to HISTORY.md
```

### Step 6: Verify Changes

**Check TODO.md**:
- [ ] 6 completed sections removed
- [ ] File still has active QA checklist at top
- [ ] Recent completions (11 NOV, 10 NOV) still present
- [ ] All active priorities still present

**Check HISTORY.md**:
- [ ] 6 new sections added in chronological order
- [ ] All sections between "8 NOV" and "7 NOV"
- [ ] Formatting consistent with existing entries

### Step 7: Test File Integrity

```bash
# Check if files are valid markdown
head -50 docs_claude/TODO.md
head -100 docs_claude/HISTORY.md

# Check file sizes
wc -l docs_claude/TODO.md
wc -l docs_claude/HISTORY.md

# Verify no duplicate headers
grep "^## " docs_claude/HISTORY.md | sort | uniq -d
```

---

## 📊 Expected Results

### Before Cleanup:
- **TODO.md**: ~6,900 lines, 69,429 tokens
- **HISTORY.md**: ~1,400 lines

### After Cleanup:
- **TODO.md**: ~6,000 lines, ~64,000 tokens (reduction of ~900 lines, 5,000 tokens)
- **HISTORY.md**: ~2,400 lines (addition of ~1,000 lines)

---

## ✅ Verification Checklist

After completing all steps:

- [ ] TODO.md no longer contains "Platform Infrastructure-as-Code Migration"
- [ ] TODO.md no longer contains "Platform Table Renaming"
- [ ] TODO.md no longer contains "Platform SQL Composition Refactoring"
- [ ] TODO.md no longer contains "Task ID Architecture Fix"
- [ ] TODO.md no longer contains "Output Folder Control"
- [ ] TODO.md no longer contains "Logger Standardization (18-19 OCT)"
- [ ] HISTORY.md has all 6 sections between "8 NOV" and "7 NOV"
- [ ] HISTORY.md sections are in chronological order (most recent first)
- [ ] TODO.md still contains QA Environment Checklist
- [ ] TODO.md still contains active priorities (🔴, 🚀, 🆕)
- [ ] Both files are valid markdown (no syntax errors)

---

## 🔧 Alternative: Use Automated Script

If you prefer, here's a Python script to automate the process:

```python
#!/usr/bin/env python3
"""
Move completed October sections from TODO.md to HISTORY.md
"""

# Define section boundaries (approximate)
SECTIONS_TO_MOVE = [
    # (start_line, end_line, section_name)
    (3761, 4025, "Platform Infrastructure-as-Code"),
    (4026, 4209, "Platform Table Renaming"),
    (4210, 4440, "Platform SQL Composition"),
    (4943, 5059, "Task ID Architecture"),
    (5060, 5178, "Output Folder Control"),
    (5179, 5254, "Logger Standardization"),
]

INSERT_AFTER_LINE_IN_HISTORY = "## 8 NOV 2025: Raster Pipeline Parameterization"

# Read files
with open('docs_claude/TODO.md', 'r') as f:
    todo_lines = f.readlines()

with open('docs_claude/HISTORY.md', 'r') as f:
    history_lines = f.readlines()

# Extract sections from TODO (in reverse order to preserve line numbers)
sections = []
for start, end, name in reversed(SECTIONS_TO_MOVE):
    section = todo_lines[start-1:end]
    sections.insert(0, section)
    print(f"Extracted: {name} ({len(section)} lines)")

# Remove sections from TODO (in reverse order)
for start, end, name in reversed(SECTIONS_TO_MOVE):
    del todo_lines[start-1:end]
    print(f"Deleted from TODO: {name}")

# Find insert point in HISTORY
insert_index = None
for i, line in enumerate(history_lines):
    if INSERT_AFTER_LINE_IN_HISTORY in line:
        # Find end of this section (next ##  or end of file)
        for j in range(i+1, len(history_lines)):
            if history_lines[j].startswith('## '):
                insert_index = j
                break
        if insert_index is None:
            insert_index = len(history_lines)
        break

if insert_index is None:
    print("ERROR: Could not find insert point in HISTORY.md")
    exit(1)

# Insert sections into HISTORY
for section in reversed(sections):
    history_lines[insert_index:insert_index] = section + ['\n---\n\n']

# Write updated files
with open('docs_claude/TODO.md', 'w') as f:
    f.writelines(todo_lines)

with open('docs_claude/HISTORY.md', 'w') as f:
    f.writelines(history_lines)

print(f"\n✅ Cleanup complete!")
print(f"TODO.md: {len(todo_lines)} lines")
print(f"HISTORY.md: {len(history_lines)} lines")
```

**⚠️ Use with caution**: Test on backup copies first!

---

## 📝 Notes

- **Manual is Safer**: Given TODO.md size (69K tokens), manual editing recommended
- **Take Backups**: `cp docs_claude/TODO.md docs_claude/TODO.md.backup`
- **Work Incrementally**: Move one section at a time, verify after each
- **Check Git Diff**: `git diff docs_claude/` to verify changes before committing

---

**Created**: 11 NOV 2025
**Purpose**: Guide manual cleanup of TODO.md (move completed October items to HISTORY.md)
**Estimated Time**: 15-20 minutes for manual cleanup