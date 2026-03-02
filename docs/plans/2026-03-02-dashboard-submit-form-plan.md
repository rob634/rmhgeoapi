# Dashboard Submit Form — GREENFIELD Pipeline Execution Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run the 7-agent GREENFIELD pipeline (S→A→C→O→M→B→V) with narrow scope to produce a deployable submit form AND validate the pipeline at constrained scale.

**Architecture:** Single-method replacement in `web_dashboard/panels/platform.py`. The Builder replaces `_render_submit()` (~70-line stub) with a complete file-browser-based submission form (~180 lines), adds 3 HTMX fragment methods (~180 lines), updates the fragment dispatch dict, and adds ~10 lines to `web_dashboard/__init__.py` for processing option restructuring.

**Tech Stack:** Python 3.12, Azure Functions, HTMX 1.9.12, no JavaScript

**Spec Document:** `docs/plans/2026-03-02-dashboard-submit-form-design.md`

**Pipeline Reference:** `docs/agent_review/agents/GREENFIELD_AGENT.md`

---

## Pre-Flight

Before starting, verify the spec and current code state:

```bash
# Confirm spec exists
cat docs/plans/2026-03-02-dashboard-submit-form-design.md | head -5

# Confirm current submit stub is what we expect to replace
grep -n "_render_submit" web_dashboard/panels/platform.py

# Confirm fragment dispatch dict (we'll add 3 entries)
grep -n "render_fragment" web_dashboard/panels/platform.py | head -5

# Confirm action proxy location
grep -n "_handle_action\|po_\|processing_options" web_dashboard/__init__.py
```

**Expected**: Spec exists, `_render_submit` at line 511, fragment dispatch at line 75, no `po_` handling in `__init__.py` yet.

---

### Task 1: Dispatch Agents A + C + O (Parallel)

**Purpose:** Get three independent perspectives on the spec before any code is written.

**Step 1: Read the spec**

Read the full spec at `docs/plans/2026-03-02-dashboard-submit-form-design.md`. Extract:
- **Tier 1** (System Context): Everything in "## Tier 1: System Context" — this goes to A, C, and O.
- **Tier 2** (Design Constraints): Everything in "## Tier 2: Design Constraints" — this is HELD BACK from A, C, O. Only M and B see this.

**Step 2: Dispatch 3 agents in parallel**

Launch all three as `Agent` tool calls in a **single message** (parallel execution). Each agent receives the Tier 1 spec ONLY.

**Agent A (Advocate) prompt:**

```
You are Agent A — the Advocate.

You receive a spec for a subsystem that does not exist yet. Your job is to design
the best possible architecture for this subsystem.

You are optimistic. Assume the spec is complete and correct. Design for the spec
as written.

## Your Task

Produce these sections:

COMPONENT DESIGN
- List every component or module this subsystem needs.
- For each: its single responsibility, what it depends on, what depends on it.

INTERFACE CONTRACTS
- For each component: exact function signatures, parameter types, return types.
- For boundaries between components: who calls whom, with what data.

DATA FLOW
- Trace the path of data from entry to exit.
- Identify every transformation, validation, and storage step.
- Note where data is copied vs referenced.

GOLDEN PATH
- Walk through the complete happy path from start to finish.
- Be specific: "User sends X, component A does Y, passes Z to component B..."

STATE MANAGEMENT
- All mutable state: where it lives, who writes it, who reads it.
- State transitions: what events cause state changes.

EXTENSION POINTS
- Where can new behavior be added without modifying existing code?
- What patterns enable this (registry, plugin, strategy, event)?

DESIGN RATIONALE
- For each major design decision: what you chose, what you rejected, and why.

## Rules
- Design for simplicity. Choose the simplest approach that satisfies the spec.
- Do not add features or capabilities beyond what the spec requires.
- Do not address failure modes, operational concerns, or edge cases.
  Other agents are handling those independently. You do not know what they
  are looking at.
- Be specific enough that a developer could start coding from your design.

## Spec
[PASTE TIER 1 HERE]
```

**Agent C (Critic) prompt:**

```
You are Agent C — the Critic.

You receive a spec for a subsystem that does not exist yet. Your job is to find
everything the spec does NOT address — ambiguities, missing edge cases, unstated
assumptions, and scenarios that will surprise the development team.

You are adversarial toward the spec, not toward the developer. Your goal is to
make the spec stronger by finding its weaknesses.

## Your Task

Produce these sections:

AMBIGUITIES
- Places where the spec could be interpreted in more than one way.
- For each: the two or more possible interpretations, and why it matters.

MISSING EDGE CASES
- Scenarios the spec does not address that could realistically occur.
- For each: what happens, how likely it is, and how severe the impact would be.

UNSTATED ASSUMPTIONS
- Things the spec assumes but does not say explicitly.
- For each: rate as SAFE (reasonable assumption) or RISKY (could be wrong).

SPEC GAPS
- Requirements that a production system would need but the spec does not mention.

CONTRADICTIONS
- Places where two parts of the spec disagree or are incompatible.

OPEN QUESTIONS
- Questions that the spec's own "Open Questions" section raised, plus any new
  questions you identified.
- Rank by impact: which questions, if answered wrong, would cause the most damage?

## Rules
- Critique the SPEC, not a design. You have not seen any design.
- Do not propose solutions. Only identify problems.
- Be specific enough to act on.
- Prioritize by impact.

## Spec
[PASTE TIER 1 HERE]
```

**Agent O (Operator) prompt:**

```
You are Agent O — the Operator.

You receive a spec for a subsystem that does not exist yet, along with a description
of the infrastructure it will run on. Your job is to assess the operational reality:
what will this system need to be deployed, monitored, and kept running in production?

## Your Task

Produce these sections:

INFRASTRUCTURE FIT
- How well does this spec fit the described infrastructure?
- Where does the infrastructure impose constraints that the spec does not acknowledge?

DEPLOYMENT REQUIREMENTS
- What does deploying this subsystem require?
- Can this be deployed with zero downtime?

FAILURE MODES
- How will this subsystem fail in production? List realistic scenarios.
- For each: trigger, detection method, blast radius, recovery path.

OBSERVABILITY
- What must be logged for debugging?
- What metrics indicate health?

SCALING BEHAVIOR
- How does this subsystem behave under increasing load?

OPERATIONAL HANDOFF
- What does a new operator need to know to maintain this system?

## Rules
- Do not design the system.
- Focus on what happens AFTER the code is written.
- Use the infrastructure profile to be specific.

## Spec
[PASTE TIER 1 HERE]

## Infrastructure Profile
- Azure Functions consumption plan, Python 3.12
- Dashboard served from /api/dashboard on the Orchestrator app (rmhazuregeoapi)
- HTMX 1.9.12 loaded in dashboard shell
- Fragment responses target specific <div> elements via hx-target
- Action proxy at /api/dashboard?action=submit|validate translates form-encoded to JSON
- Blob storage in bronze zone (rmhazuregeobronze) — hundreds of files per container
- API endpoints for containers and blobs already exist
```

**Step 3: Save outputs**

Save each agent's output to:
- `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_ADVOCATE.md`
- `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_CRITIC.md`
- `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_OPERATOR.md`

**Step 4: Commit**

```bash
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_ADVOCATE.md
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_CRITIC.md
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_OPERATOR.md
git commit -m "GREENFIELD submit: A+C+O agent outputs"
```

---

### Task 2: Quality Gate on A + C + O

**Purpose:** Verify all three agents produced structured, role-appropriate outputs before dispatching M.

**Step 1: Verify section coverage**

Read all three output files. Check:

- **A** must have: COMPONENT DESIGN, INTERFACE CONTRACTS, DATA FLOW, GOLDEN PATH, STATE MANAGEMENT, EXTENSION POINTS, DESIGN RATIONALE.
- **C** must have: AMBIGUITIES, MISSING EDGE CASES, UNSTATED ASSUMPTIONS, SPEC GAPS, CONTRADICTIONS, OPEN QUESTIONS.
- **O** must have: INFRASTRUCTURE FIT, DEPLOYMENT REQUIREMENTS, FAILURE MODES, OBSERVABILITY, SCALING BEHAVIOR, OPERATIONAL HANDOFF.

**Step 2: Verify role boundaries**

- A did NOT address failure modes (only happy path design) — if A discusses failures, note for M.
- C did NOT propose solutions (only identified problems) — if C proposes designs, note for M.
- O did NOT design architecture (only operational concerns) — if O designs components, note for M.

**Step 3: Decision**

- If all three produced structured outputs with correct sections: proceed to Task 3.
- If any agent returned unstructured prose or skipped sections: re-dispatch that agent with format instructions emphasized.

---

### Task 3: Dispatch Agent M (Mediator)

**Purpose:** Resolve conflicts between A, C, O and produce the final resolved spec that B will code from.

**Step 1: Prepare M's input**

M receives EVERYTHING:
1. Original Tier 1 spec
2. Tier 2 Design Constraints (M sees these for the first time)
3. Agent A's full design
4. Agent C's full critique
5. Agent O's full assessment

**Step 2: Dispatch M**

Use `Agent` tool with `subagent_type="general-purpose"`. M runs sequentially (not parallel — it needs all three inputs).

**Agent M (Mediator) prompt:**

```
You are Agent M — the Mediator.

You have three independent analyses of a spec for a subsystem that does not exist yet:

- Agent A (Advocate) designed the system optimistically, assuming the spec is correct.
- Agent C (Critic) found everything the spec does not address.
- Agent O (Operator) assessed what it takes to deploy and run this in production.

These three agents worked independently. They did not see each other's output.
Their analyses will conflict. Your job is to resolve those conflicts and produce
a final spec that the Builder agent can code against.

You also have DESIGN CONSTRAINTS — settled architectural decisions from the existing
system that the new component must follow. A, C, and O did not see these constraints.
Where their proposals conflict with these constraints, enforce the constraints but
NOTE THE TENSION.

## Your Task

Produce these sections:

CONFLICTS FOUND
- Where A's design violates O's infrastructure constraints.
- Where C's edge cases require changes to A's design.
- Where O's operational requirements add complexity A did not anticipate.

DESIGN TENSIONS
- Where an agent's unconstrained proposal conflicts with a Tier 2 Design Constraint.
  For each: what the agent proposed, what the existing constraint requires, which
  one you enforced.

RESOLVED SPEC
- The final, unified spec. Organize by component. For each:
  - Responsibility (one sentence)
  - Interface (function signatures with types)
  - Error handling strategy
  - Integration notes (which existing BasePanel utilities to use)
- This must be detailed enough to code from without follow-up questions.
- IMPORTANT: The resolved spec MUST produce code for these exact methods in
  web_dashboard/panels/platform.py:
  1. _render_submit(request) -> str — complete form HTML (~180 lines)
  2. _fragment_submit_containers(request) -> str — container dropdown options
  3. _fragment_submit_files(request) -> str — blob table with click-to-select
  4. _fragment_submit_options(request) -> str — type-specific processing fields
  Plus: fragment dispatch dict additions (3 entries) and po_* restructuring
  in web_dashboard/__init__.py (~10 lines in _handle_action).

DEFERRED DECISIONS
- Issues that are real but do not need to be solved in the first version.

RISK REGISTER
- Residual risks. For each: description, likelihood, impact, mitigation.

## Rules
- Every resolution must explain the tradeoff.
- If A's design and O's constraints are incompatible, prefer O's constraints.
- If A's design and a Design Constraint are incompatible, enforce the constraint
  but record the tension.
- If C raised a concern neither A nor O addressed, you must address it.
- The RESOLVED SPEC must be self-contained.

## Original Spec (Tier 1)
[PASTE TIER 1 FROM docs/plans/2026-03-02-dashboard-submit-form-design.md]

## Tier 2 Design Constraints
[PASTE TIER 2 FROM docs/plans/2026-03-02-dashboard-submit-form-design.md]

## Agent A's Design (Advocate)
[PASTE FROM docs/agent_review/agent_docs/GREENFIELD_SUBMIT_ADVOCATE.md]

## Agent C's Analysis (Critic)
[PASTE FROM docs/agent_review/agent_docs/GREENFIELD_SUBMIT_CRITIC.md]

## Agent O's Assessment (Operator)
[PASTE FROM docs/agent_review/agent_docs/GREENFIELD_SUBMIT_OPERATOR.md]
```

**Step 3: Save output**

Save to `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_MEDIATOR.md`.

**Step 4: Quality gate**

Verify M's output has:
- CONFLICTS FOUND with explicit A-vs-O, C-vs-A, and O-vs-A tensions
- DESIGN TENSIONS section (even if empty)
- RESOLVED SPEC with function signatures, error handling, and integration notes
- All concerns from C were addressed (not silently dropped)
- All Tier 2 Design Constraints reflected in RESOLVED SPEC

**Step 5: Commit**

```bash
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_MEDIATOR.md
git commit -m "GREENFIELD submit: M mediator resolved spec"
```

---

### Task 4: Dispatch Agent B (Builder)

**Purpose:** Write the actual production code from M's resolved spec.

**Step 1: Prepare B's input**

B receives:
1. M's RESOLVED SPEC section (the primary input)
2. Tier 2 Design Constraints (for reference)
3. M's RISK REGISTER (for awareness)
4. M's DESIGN TENSIONS (for awareness)

B does NOT receive: A, C, or O outputs. B does NOT receive the original Tier 1 spec.

**Step 2: Dispatch B**

Use `Agent` tool with `subagent_type="general-purpose"`.

**CRITICAL**: Give B access to the codebase so it can READ existing files for context.

**Agent B (Builder) prompt:**

```
You are Agent B — the Builder.

You receive a resolved spec for a subsystem. The spec has been through adversarial
review: an architect designed it, a critic stress-tested it, an operator assessed it,
and a mediator resolved all conflicts.

Your job is to write the code.

## Context: Existing Code You Must Read

IMPORTANT: Before writing any code, you MUST read these files to understand the
existing patterns and utilities:

1. web_dashboard/panels/platform.py — your PRIMARY file. Read the ENTIRE file.
   You are REPLACING the _render_submit() method (lines 511-582) and ADDING
   3 new fragment methods. You are also adding 3 entries to the render_fragment()
   dispatch dict (around line 76).

2. web_dashboard/base_panel.py — read lines 1-200 for utility method signatures.
   You MUST use these utilities, not reimplement them:
   - self.call_api(request, path, params) -> (ok, data)
   - self.data_table(headers, rows, row_attrs) -> str
   - self.select_filter(name, label, options, selected) -> str
   - self.error_block(message, retry_url) -> str
   - self.empty_block(message) -> str
   - self.status_badge(status) -> str
   - self.data_type_badge(data_type) -> str
   - self.format_date(iso_str) -> str
   - self.truncate_id(full_id, length) -> str

3. web_dashboard/__init__.py — read lines 305-395 to understand the action proxy.
   You will add ~10 lines of po_* field restructuring to _handle_action().

## Output Format

You MUST produce your output as TWO clearly separated code blocks:

### BLOCK 1: platform.py changes

Produce the complete replacement code for these sections:
- The REPLACEMENT for _render_submit() (currently lines 511-582)
- THREE new methods: _fragment_submit_containers(), _fragment_submit_files(),
  _fragment_submit_options()
- The UPDATED render_fragment() dispatch dict (add 3 entries)

Format: Show each method as a complete, copy-pasteable Python method.

### BLOCK 2: __init__.py changes

Produce the po_* field restructuring code to add inside _handle_action(),
right before the API call (before line 358).

Format: Show the exact code block to insert, with surrounding context lines
so the insertion point is clear.

## Requirements

TRACEABILITY
- Every function must have a docstring that states which spec requirement
  it implements.

CODE ORGANIZATION
- All methods go in the PlatformPanel class in platform.py.
- Follow the existing code style exactly (f-strings, html_module.escape(),
  BasePanel utility calls).

INTEGRATION
- Use self.call_api() for all API calls.
- Use self.data_table() for blob listing table.
- Use self.select_filter() for container dropdown.
- Use self.error_block() and self.empty_block() for error/empty states.
- Use html_module.escape() for ALL dynamic content.

SECURITY
- No JavaScript. No onclick handlers. No <script> tags. HTMX attributes only.
- All dynamic content escaped with html_module.escape().

## Rules
- Implement what the spec says. Do not add features beyond the spec.
- Write code that matches the existing style in platform.py exactly.
- The total output should be ~370 lines of new/replacement code.

## Resolved Spec
[PASTE M's RESOLVED SPEC section from GREENFIELD_SUBMIT_MEDIATOR.md]

## Tier 2 Design Constraints
[PASTE TIER 2 FROM docs/plans/2026-03-02-dashboard-submit-form-design.md]

## Risk Register
[PASTE M's RISK REGISTER section]

## Design Tensions
[PASTE M's DESIGN TENSIONS section]
```

**Step 3: Save output**

Save to `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_BUILDER.md`.

**Step 4: Commit**

```bash
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_BUILDER.md
git commit -m "GREENFIELD submit: B builder code output"
```

---

### Task 5: Dispatch Agent V (Validator)

**Purpose:** Reverse-engineer B's code without seeing the spec, then compare.

**Step 1: Extract B's code only**

From `GREENFIELD_SUBMIT_BUILDER.md`, extract ONLY the Python code blocks.
V receives NO spec, NO context, NO agent outputs.

**Step 2: Dispatch V**

Use `Agent` tool with `subagent_type="general-purpose"`.

**Agent V (Validator) prompt:**

```
You are Agent V — the Validator.

You receive source code with NO external context. You have not been told what this
code is for, what system it belongs to, or what its requirements are.

A spec exists for this code, but you have not seen it. Your analysis will be
compared against that spec to find gaps.

## Your Task

Produce these sections:

INFERRED PURPOSE
- What does this code do? Describe it as if explaining to a new team member.

INFERRED CONTRACTS
- For each interface: what it accepts, what it returns, what it promises.

INFERRED INVARIANTS
- What must be true for this code to work correctly?

INFERRED BOUNDARIES
- What is in scope for this code? What does it explicitly NOT do?

CONCERNS
- Anything that seems incomplete, inconsistent, or unclear.
- Anything that looks like it was intended to handle a specific scenario
  but might not handle it correctly.
- XSS vectors, injection risks, missing escaping.

QUALITY ASSESSMENT
- Is the code self-documenting?
- Are error handling patterns consistent?
- Rate overall: PRODUCTION READY / NEEDS MINOR WORK / NEEDS SIGNIFICANT WORK

## Rules
- Work ONLY from the code. Do not guess about external context.
- Be specific. Cite function names and line references.

## Code
[PASTE ONLY THE CODE BLOCKS FROM GREENFIELD_SUBMIT_BUILDER.md — NO SPEC OR CONTEXT]
```

**Step 3: Save output**

Save to `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_VALIDATOR.md`.

**Step 4: Commit**

```bash
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_VALIDATOR.md
git commit -m "GREENFIELD submit: V validator blind review"
```

---

### Task 6: Spec Diff (Claude — No Subagent)

**Purpose:** Compare V's inferences against S's original spec to find gaps.

Claude does this directly (no subagent). Read both documents:
1. `docs/plans/2026-03-02-dashboard-submit-form-design.md` (S's spec)
2. `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_VALIDATOR.md` (V's analysis)

Produce:

**MATCHES** — Where V's inferred purpose matches S's spec. These are well-implemented.

**GAPS** — Where S's spec includes something V did not infer from the code. These are either implementation gaps (code doesn't do it) or documentation gaps (code does it but isn't clear).

**EXTRAS** — Where V inferred something NOT in S's spec. Could be scope creep, undocumented behavior, or emergent behavior.

**VERDICT** — Is the code ready to integrate? List specific functions that need revision if any.

Save to `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_SPEC_DIFF.md`.

```bash
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_SPEC_DIFF.md
git commit -m "GREENFIELD submit: spec diff (S vs V)"
```

---

### Task 7: Apply Builder Code to platform.py

**Purpose:** Integrate B's code into the actual codebase.

**Step 1: Read B's output**

Read `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_BUILDER.md` and extract the code blocks.

**Step 2: Update render_fragment() dispatch dict**

In `web_dashboard/panels/platform.py`, add 3 entries to the dispatch dict around line 76:

```python
# In render_fragment() dispatch dict, add:
"submit-containers": self._fragment_submit_containers,
"submit-files": self._fragment_submit_files,
"submit-options": self._fragment_submit_options,
```

**Step 3: Replace _render_submit()**

Replace lines 511-582 in `web_dashboard/panels/platform.py` with B's `_render_submit()` method.

**Step 4: Add fragment methods**

Add B's three new methods after the replaced `_render_submit()`:
- `_fragment_submit_containers()`
- `_fragment_submit_files()`
- `_fragment_submit_options()`

**Step 5: Verify no syntax errors**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "import web_dashboard.panels.platform; print('platform.py imports OK')"
```

Expected: `platform.py imports OK`

---

### Task 8: Apply po_* Restructuring to __init__.py

**Purpose:** Add processing option field restructuring to the action proxy.

**Step 1: Read B's __init__.py changes**

From `GREENFIELD_SUBMIT_BUILDER.md`, extract the `__init__.py` code block.

**Step 2: Add po_* restructuring**

In `web_dashboard/__init__.py`, inside `_handle_action()`, add the po_* field
collection BEFORE the API call (before line 358, after the body is parsed):

```python
# Collect po_* fields into processing_options dict
if action in ("submit", "validate"):
    po_fields = {k[3:]: v for k, v in body.items() if k.startswith("po_") and v}
    for k in list(body):
        if k.startswith("po_"):
            del body[k]
    if po_fields:
        body["processing_options"] = po_fields
```

**Step 3: Verify no syntax errors**

```bash
python -c "import web_dashboard; print('__init__.py imports OK')"
```

Expected: `__init__.py imports OK`

**Step 4: Commit**

```bash
git add web_dashboard/panels/platform.py web_dashboard/__init__.py
git commit -m "feat: replace submit stub with complete file browser form

GREENFIELD pipeline output: file browser, DDH fields, type-specific
processing options, validate/submit with inline results.

Added po_* field restructuring in action proxy for processing_options."
```

---

### Task 9: Smoke Test

**Purpose:** Verify the form renders and fragments respond correctly.

**Step 1: Start local dev server**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
func start
```

**Step 2: Test full page load**

```bash
curl -s http://localhost:7071/api/dashboard?tab=platform&section=submit | head -50
```

Expected: HTML containing `submit-form`, container dropdown area, DDH identifier fields.

**Step 3: Test container fragment**

```bash
curl -s -H "HX-Request: true" \
  "http://localhost:7071/api/dashboard?tab=platform&fragment=submit-containers"
```

Expected: HTML `<option>` elements for container names, or an error block if API is unreachable.

**Step 4: Test options fragment**

```bash
curl -s -H "HX-Request: true" \
  "http://localhost:7071/api/dashboard?tab=platform&fragment=submit-options&data_type=raster"
```

Expected: HTML form fields for raster processing options (po_crs, po_nodata_value, po_band_names).

```bash
curl -s -H "HX-Request: true" \
  "http://localhost:7071/api/dashboard?tab=platform&fragment=submit-options&data_type=vector"
```

Expected: HTML form fields for vector processing options (po_table_name, po_layer_name, po_lat_column, po_lon_column, po_wkt_column).

**Step 5: Verify XSS safety**

```bash
curl -s -H "HX-Request: true" \
  "http://localhost:7071/api/dashboard?tab=platform&fragment=submit-files&container=test%3Cscript%3Ealert(1)%3C/script%3E"
```

Expected: The `<script>` tag should be escaped in the output, not rendered as HTML.

---

### Task 10: Save Pipeline Run Report

**Purpose:** Document the full pipeline run for the agent review log.

**Step 1: Create run report**

Write a summary to `docs/agent_review/agent_docs/GREENFIELD_SUBMIT_RUN_REPORT.md` including:
- Pipeline: GREENFIELD (narrow scope test)
- Agents dispatched: S, A, C, O, M, B, V + Spec Diff
- Scope: 2 files, ~370 lines new code
- Token usage (approximate from each agent)
- Time (wall clock from first dispatch to code applied)
- Verdict from Spec Diff
- Any deviations from the pipeline (re-dispatches, manual fixes)
- Comparison to Run 19 (full dashboard — 9 files, 4,499 lines)

**Step 2: Update AGENT_RUNS.md**

Add the run entry to `docs/agent_review/AGENT_RUNS.md`:

```markdown
| 24 | GREENFIELD | Submit Form (narrow) | 02 MAR 2026 | S+A+C+O+M+B+V | [tokens] | [verdict] |
```

**Step 3: Commit**

```bash
git add docs/agent_review/agent_docs/GREENFIELD_SUBMIT_RUN_REPORT.md
git add docs/agent_review/AGENT_RUNS.md
git commit -m "GREENFIELD submit: pipeline run report (Run 24)"
```

---

## Task Summary

| Task | Type | Agent(s) | Depends On | Est. Lines |
|------|------|----------|------------|------------|
| 1 | Agent dispatch | A + C + O (parallel) | — | ~3 pages each |
| 2 | Quality gate | Claude (manual) | 1 | — |
| 3 | Agent dispatch | M (sequential) | 2 | ~4 pages |
| 4 | Agent dispatch | B (sequential) | 3 | ~370 lines code |
| 5 | Agent dispatch | V (sequential) | 4 | ~2 pages |
| 6 | Spec diff | Claude (manual) | 5 | ~1 page |
| 7 | Code apply | Claude (manual) | 6 | platform.py edits |
| 8 | Code apply | Claude (manual) | 7 | __init__.py edits |
| 9 | Smoke test | Claude (manual) | 8 | — |
| 10 | Documentation | Claude (manual) | 9 | — |

**Estimated total tokens**: ~200K-300K (vs ~550K for Run 19 full dashboard)
**Estimated time**: ~20-30 minutes (vs ~45 min for Run 19)
**Estimated output code**: ~370 lines (vs 4,499 for Run 19)

---

## Success Criteria

1. All 7 agents (S→A→C→O→M→B→V) produce structured, role-appropriate outputs
2. M resolves all A-vs-C-vs-O conflicts explicitly (no silent drops)
3. B produces ~370 lines of code within the safe zone (<3,000 lines)
4. V rates the code PRODUCTION READY or NEEDS MINOR WORK
5. Spec Diff shows no CRITICAL gaps
6. Code imports without errors
7. Submit form renders in browser with container dropdown, file browser, DDH fields
8. Processing options show correct fields for raster vs vector file types
9. Validate and Submit buttons post through action proxy correctly
10. All dynamic content is HTML-escaped (no XSS vectors)
