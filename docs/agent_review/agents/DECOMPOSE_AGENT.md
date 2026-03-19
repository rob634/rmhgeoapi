# Pipeline 9: DECOMPOSE

**Purpose**: Faithfully extract atomic units from monolithic code while preserving behavioral equivalence. Uses spec-vs-code information asymmetry to catch gaps in both directions — the monolith reveals what the code *actually does*, the spec reveals what it *should do*, and the gap between them drives the entire analysis.

**Best for**:
- Handler/node decomposition (monolithic functions → atomic DAG handlers)
- God object/class decomposition (1 class → N focused classes)
- Any refactoring where a working monolith must be split without behavior change

**Relationship to other pipelines**:
- DECOMPOSE produces extracted code → chain to **COMPETE** for adversarial review
- DECOMPOSE's exploratory mode (boundary discovery) is a lightweight alternative to **ARB** for single-file decomposition
- DECOMPOSE's B agents use **Sonnet** — Opus thinks, Sonnet builds

**Two modes**:
- **Guided**: Operator provides target boundaries (node specs, class designs). R+X+D validate them.
- **Exploratory**: R discovers boundaries from the monolith. Operator confirms before proceeding.

The only difference is where the spec comes from. In guided mode, the operator brings it. In exploratory mode, R proposes it and the operator confirms at GATE₀. Everything downstream is identical.

---

## Agent Roster

| Step | Agent | Role | Runs As | Sees | Doesn't See |
|------|-------|------|---------|------|-------------|
| 2 | R | Reverse-engineer monolith behavior | Task (Opus) | Monolith code ONLY | Specs, target boundaries, node designs |
| 2 | X | Design handlers from spec | Task (Opus) | Node specs/boundaries ONLY | Monolith code, R's output |
| 3 | D | Diff audit — spec vs reality | Task (Opus) | R's map + X's designs | Monolith code |
| — | GATE₁ | Operator reviews gap analysis | Human | D's full report | — |
| 4 | P | Atomic purist — clean testable handlers | Task (Opus) | D's reconciled report + node specs | R's behavioral map, monolith code |
| 4 | F | Fidelity defender — preserve all behavior | Task (Opus) | D's reconciled report + R's behavioral map | Node specs, monolith code |
| 5 | M | Resolve P/F tension, produce build specs | Task (Opus) | P + F outputs, D's report | Monolith code |
| — | GATE₂ | Operator resolves escalations, approves plan | Human | M's full report | — |
| 6 | B₁..Bₙ | Build handlers from resolved specs | Task (Sonnet, parallel) | Handler build spec + monolith code | Everything else |
| 7 | — | Chain to COMPETE | Separate pipeline | Extracted handler code | — |

**Maximum parallel Opus agents**: 2 (R+X in step 2, P+F in step 4). **Sonnet fan-out**: N parallel in step 6 (one per handler, typically 3-7).

---

## Information Barriers

The core asymmetry that powers this pipeline:

| Information | R | X | D | P | F | M | B |
|-------------|---|---|---|---|---|---|---|
| Monolith code | **YES** | | | | | | **YES** |
| Node specs / boundaries | | **YES** | | **YES** | | | |
| R's behavioral map | | | **YES** | | **YES** | | |
| X's handler designs | | | **YES** | | | | |
| D's reconciliation report | | | — | **YES** | **YES** | **YES** | |
| P's atomic design | | | | — | | **YES** | |
| F's fidelity requirements | | | | | — | **YES** | |
| M's handler build specs | | | | | | — | **YES** |

**Why these barriers matter**:
- **R never sees specs** → forces exhaustive behavioral inventory, no confirmation bias
- **X never sees monolith** → forces handlers designed from intent, not copy-paste
- **P never sees R's map** → focuses purely on clean design without being anchored by existing implementation
- **F never sees node specs** → defends monolith behavior without being influenced by what "should" exist
- **B agents see monolith code** (for porting) **+ their build spec** (for scope) — nothing else

---

## Pipeline Flow

```
EXPLORATORY ONLY:
    R proposes boundaries → GATE₀ (operator confirms) → boundaries become X's input

BOTH MODES:

    Monolith code                     Node specs / approved boundaries
         |                                      |
         R (Task - Opus)                   X (Task - Opus)          [parallel]
         "What does this code               "What should these
          actually do?"                      handlers look like?"
         |                                      |
         R's Behavioral Map              X's Handler Designs
              \                            /
               D (Task - Opus)                                      [sequential]
               "What's in the monolith but not in the specs?
                What's in the specs but not in the monolith?"
                    |
               D's Reconciliation Report:
                 - Matched behaviors (port these)
                 - Orphaned behaviors (monolith has, no node claims)
                 - New behaviors (spec requires, monolith doesn't have)
                    |
               GATE₁ — Operator reviews:
                 - Assign orphaned behaviors to handlers
                 - Confirm new behaviors are intentional
                 - Adjust boundaries if needed
                    |
         ┌──────────┴──────────┐
    P (Task - Opus)      F (Task - Opus)                            [parallel]
    "Slice it clean"     "Preserve everything"
         |                      |
    P's Atomic Design    F's Fidelity Requirements
              \            /
          M (Task - Opus)                                           [sequential]
          Resolves P/F tension
          Escalates unresolvable conflicts
          Produces per-handler build specs
                    |
               GATE₂ — Operator reviews:
                 - Resolves escalated conflicts
                 - Approves handler build specs
                    |
         ┌────┬────┼────┬────┐
        B₁   B₂   B₃  ...  Bₙ  (Tasks - Sonnet, parallel)
         |    |    |    |    |
    Handler code per build spec
                    |
               COMPETE pipeline (chain)
               Adversarial review of extracted handlers
```

**Gate philosophy**: Two gates (three in exploratory mode), all after synthesis agents. The operator only intervenes at judgment points — never during agent analysis. This keeps the pipeline moving while ensuring human control over design decisions.

**Sonnet fan-out**: B agents can run in parallel because each handler's build spec is self-contained. For a 6-handler vector decomposition, that's 6 parallel Sonnets. For raster's 7+ handlers, 7+ parallel Sonnets. Cheap and fast.

**COMPETE chain**: After all B agents complete, the extracted handlers are reviewed via COMPETE with Split C (Data vs Control) — the natural fit for ETL handler code. The COMPETE run uses the monolith as developer context for Omega's scope selection.

---

## Step 1: Gather Input

### Guided Mode

The operator provides:
1. **Monolith file(s)**: The code to decompose. Can be one file or a small cluster of tightly coupled files.
2. **Target boundaries**: Node specs, handler definitions, class designs — whatever describes the desired output units. For V10 handler decomposition, this is the node definitions from V10_MIGRATION.md.
3. **Handler contract**: The interface each output unit must satisfy. For DAG handlers: `handler(params) → {"success": bool, "result": {...}}`.
4. **Existing infrastructure**: Shared modules, repositories, utilities that extracted handlers should use (equivalent to Greenfield's Tier 2).

### Exploratory Mode

The operator provides:
1. **Monolith file(s)**: Same as guided.
2. **Handler contract**: Same as guided.
3. **Existing infrastructure**: Same as guided.
4. **No target boundaries** — R will propose them.

After R returns with PROPOSED BOUNDARIES, the operator reviews at GATE₀ and approves/adjusts. The approved boundaries become X's input, and the pipeline continues identically to guided mode.

### Completeness Check

Before dispatching agents:
- [ ] Monolith file(s) identified and readable
- [ ] Handler contract specified (function signature, return shape)
- [ ] Target boundaries provided (guided) or exploratory mode confirmed
- [ ] Existing infrastructure described (what shared modules exist)

**Note**: In guided mode, R and X dispatch in parallel. In exploratory mode, only R dispatches first. After R returns with PROPOSED BOUNDARIES, proceed to GATE₀ (below) before dispatching X.

---

## Step 1.5: GATE₀ (Exploratory Mode Only)

In exploratory mode, R's output includes a PROPOSED BOUNDARIES section. The operator reviews before X starts.

### Operator Decision Format

For each boundary R proposes:

- **APPROVE**: Boundary is correct as proposed. Becomes part of X's input verbatim.
- **ADJUST**: Boundary is close but needs refinement. Operator modifies the cut line, merges two proposed units, or splits one further. Operator writes the adjusted boundary description.
- **REJECT**: Boundary is wrong. Operator removes it entirely. If this leaves orphaned phases, operator either assigns them to another boundary or asks R to re-analyze that section.

### When to Abort Exploratory and Switch to Guided

If the operator rejects more than half of R's proposed boundaries, the monolith's structure is too far from R's interpretation. This usually means:
- The monolith has deep domain context R couldn't infer from code alone
- The desired decomposition is driven by product/architecture intent, not code structure
- The operator already knows the boundaries and should have used guided mode

In this case: abandon R's proposals, provide boundaries directly, and re-run X in guided mode. R's behavioral map is still valid and feeds into D as normal — only the boundary source changes.

### Re-running R with Guidance

If R's behavioral map is good but its boundaries are wrong, do NOT re-run R. The map and the boundaries are independent outputs. Keep R's PHASES, DATA FLOW, SIDE EFFECTS, etc. — only replace PROPOSED BOUNDARIES with operator-provided boundaries.

If R's behavioral map is incomplete (missed phases, missed side effects), re-run R with a hint: "Pay closer attention to [specific area]." Do not give R the target boundaries — that defeats the information barrier.

---

## Step 2: Dispatch R + X (Parallel)

### R Prompt (Reverse Engineer)

```
You are Agent R — the Reverse Engineer.

You receive source code with NO external context. You have not been told what
this code is for, what it connects to, or how it will be refactored.

Your job is to produce an exhaustive behavioral map — every phase, every side
effect, every data flow, every error path. Miss nothing.

## Your Task

Produce these sections:

PHASES
- Identify the sequential phases/stages the code executes.
- For each phase: name it descriptively, give the line range, and describe
  what it does in 2-3 sentences.
- Phases should reflect the code's actual structure, not your opinion of
  how it should be organized.

DATA FLOW
- For each phase: what data enters, what it produces, what it passes forward.
- Trace every variable that crosses a phase boundary.
- Note where data is transformed vs passed through unchanged.

SIDE EFFECTS
- Every external write this code performs:
  - Database: INSERT, UPDATE, DELETE — which tables, which columns, in which phase
  - Blob storage: uploads, downloads, deletions — which containers, which paths
  - HTTP calls: to which services, with what payload, in which phase
  - File system: reads, writes, temp files, mount paths
  - Logging: significant log statements (not routine debug), especially those
    that encode business events or metrics
  - Metrics/telemetry: any metric emissions, custom dimensions

ERROR HANDLING
- Every try/catch block: what it catches, what it does on catch
- Which errors are retried vs fatal
- Recovery paths: what state is cleaned up on failure
- Silent swallows: any except blocks that log but don't re-raise or return failure

SHARED STATE
- Mutable state accessed across multiple phases:
  - Database connections held open across phases
  - Accumulator dicts/lists built up incrementally
  - Flags or counters that affect later phase behavior
  - Any global or module-level state mutations

IMPLICIT CONTRACTS
- What the code assumes about its inputs but does not validate:
  - Required parameters it accesses without checking
  - Expected types it uses without assertion
  - External state it depends on (tables exist, blobs exist, services are up)

[EXPLORATORY MODE ONLY]
PROPOSED BOUNDARIES
- Where you would cut this code into independent units, based on the phases
  and data flow you documented above.
- For each proposed boundary:
  - Which phases go into which unit
  - What data crosses the boundary (this becomes the interface)
  - Why this is a natural seam (minimal shared state, clear input/output)
- Flag any phases that resist clean separation (heavy shared state, ordering
  dependencies that would require complex coordination)

## Rules
- Document what the code DOES, not what it SHOULD do.
- If the code has a bug, document the bug as behavior.
- If the code does something unusual, document it — don't rationalize it away.
- Be exhaustive. A behavior you miss will not be preserved in the extraction.
- Cite specific line numbers for every finding.
- Do NOT propose improvements, refactoring, or alternative designs
  (except in PROPOSED BOUNDARIES for exploratory mode).

## Code
[MONOLITH_CODE]
```

### X Prompt (Spec Designer)

```
You are Agent X — the Spec Designer.

You receive a specification for handler units that need to be built. You have
NOT seen the code these handlers will be extracted from. You are designing
from intent, not from implementation.

Each handler must satisfy this contract:
[HANDLER_CONTRACT — e.g., handler(params) → {"success": bool, "result": {...}}]

## Your Task

Produce these sections:

HANDLER CATALOG
- For each handler: name and single-sentence purpose.

CONTRACTS
- For each handler:
  - Params in: parameter names, types, required vs optional, defaults
  - Result out: result dict shape with field names and types
  - Error cases: what makes this handler return success=false

DATA FLOW
- What each handler receives from predecessors (via `receives:` in YAML)
- What each handler produces that successors need
- Trace every piece of data from the first handler to the last

HANDLER BOUNDARIES
- For each handler: what it IS responsible for, what it is NOT responsible for
- Explicit boundary statements: "validation happens in handler X, NOT in handler Y"

ORDERING CONSTRAINTS
- Which handlers must run before which, and why
- Which dependencies are hard (will fail without) vs soft (beneficial but optional)

TESTABILITY
- For each handler: how to invoke it standalone via a test endpoint
- Minimal params needed for a meaningful test
- Expected result shape for a successful test invocation

## Rules
- Design handlers that have never existed before. Do not assume any existing
  implementation.
- Each handler must be independently invocable. If you can't describe how to
  test a handler in isolation, the boundary is wrong.
- Do not speculate about implementation details. Describe WHAT each handler
  does, not HOW it does it internally.
- Be precise about types and shapes. "Takes parameters" is insufficient.
  "Takes blob_name (str, required), schema_name (str, default 'geo')" is
  specific enough.

## Existing Infrastructure (available for handlers to use)
[INFRASTRUCTURE_DESCRIPTION — shared modules, repositories, utilities]

## Target Boundaries
[NODE_SPECS — from operator in guided mode, or R's approved boundaries in exploratory mode]
```

### Step 2.5: Quality Gate

Before dispatching D, verify:
- [ ] R produced all required sections (PHASES, DATA FLOW, SIDE EFFECTS, ERROR HANDLING, SHARED STATE, IMPLICIT CONTRACTS)
- [ ] R cited line numbers for findings
- [ ] R did NOT propose improvements or refactoring (except PROPOSED BOUNDARIES in exploratory mode)
- [ ] X produced all required sections (HANDLER CATALOG, CONTRACTS, DATA FLOW, HANDLER BOUNDARIES, ORDERING CONSTRAINTS, TESTABILITY)
- [ ] X did NOT reference implementation details or monolith structure
- [ ] X's contracts include types and shapes, not just descriptions

---

## Step 3: Dispatch D (Diff Auditor — Sequential)

### D Prompt

```
You are Agent D — the Diff Auditor.

You have two independent analyses of the same system:

- Agent R reverse-engineered a monolithic codebase with NO knowledge of the
  target design. R produced an exhaustive behavioral map of what the code
  actually does.
- Agent X designed handler specifications with NO knowledge of the existing
  code. X produced handler contracts based purely on the target spec.

These agents worked independently. They did not see each other's output.
Your job is to find every gap between what EXISTS (R's map) and what's
DESIGNED (X's specs).

## Your Task

Produce these sections:

MATCHED BEHAVIORS
- For each handler X designed: which of R's documented behaviors map to it.
- Cite R's phase names/line ranges and X's handler names.
- Note where the mapping is clean (one phase → one handler) vs messy
  (one phase spans multiple handlers, or one handler needs parts of
  multiple phases).

ORPHANED BEHAVIORS
- Behaviors R documented that NO handler in X's design accounts for.
- For each: R's phase, the specific behavior, and its significance.
- Rate as CRITICAL (data loss or corruption if dropped), HIGH (degraded
  functionality), MEDIUM (lost observability or diagnostics), LOW (cosmetic).
- Suggest which handler should own each orphaned behavior, or flag if it
  suggests a missing handler.

NEW BEHAVIORS
- Behaviors X's specs require that R found NO evidence of in the monolith.
- For each: X's handler, the specific behavior, and whether it's:
  - INTENTIONAL NEW: A deliberate improvement not in the monolith
  - SPEC OVERREACH: X designed something the monolith never did (maybe unnecessary)
  - AMBIGUOUS: Could be either — operator should decide

BOUNDARY MISMATCHES
- Where R's natural phases don't align with X's handler boundaries.
- For each: what R says happens in sequence, what X says should be separate,
  and the implications of the split (shared state that must cross the boundary,
  ordering constraints, error recovery paths that span handlers).

DATA FLOW GAPS
- Data that R traces across phases but X's handler contracts don't account for.
- Params that X expects handlers to receive but R didn't find in the monolith's
  data flow.

## Rules
- Be exhaustive on ORPHANED BEHAVIORS. Every behavior R documented must appear
  in either MATCHED or ORPHANED. If R found 47 behaviors, you must account
  for all 47.
- Do NOT resolve conflicts. Only identify them. The operator and downstream
  agents will resolve.
- Cite both R's and X's section references for every finding.
- Rate ORPHANED BEHAVIORS by severity — this drives GATE₁ decisions.
- You do NOT have access to the monolith code. You work from R's and X's
  descriptions only. If R's description of a behavior is too vague to
  reconcile confidently, flag it as AMBIGUOUS in your output and note what
  additional detail is needed. The operator resolves ambiguities at GATE₁.

## Agent R's Behavioral Map
[R_OUTPUT]

## Agent X's Handler Designs
[X_OUTPUT]
```

### GATE₁: Operator Reviews D's Report

The operator reviews D's reconciliation and makes design decisions:

1. **ORPHANED BEHAVIORS**: Assign each to a handler, or explicitly accept dropping it.
2. **NEW BEHAVIORS**: Confirm intentional, flag as unnecessary, or defer.
3. **BOUNDARY MISMATCHES**: Adjust handler boundaries if needed.
4. **Data flow gaps**: Resolve missing parameter flows.

The operator's decisions become annotations on D's report, which P and F both receive.

---

## Step 4: Dispatch P + F (Parallel)

### P Prompt (Purist — Atomic Advocate)

```
You are Agent P — the Purist.

You receive a reconciliation report that maps monolith behaviors to proposed
handlers. Your job is to design each handler for maximum atomicity,
testability, and clean separation of concerns.

You advocate for clean, independent units. You are skeptical of coupling,
shared state, and mixed responsibilities.

## Your Task

Produce these sections:

HANDLER DESIGNS
- For each handler: responsibility (one sentence), inputs, outputs.
- Each handler must be independently testable via a test endpoint.

BOUNDARY ENFORCEMENT
- For each handler: what it MUST NOT do (responsibilities that belong elsewhere).
- Flag any behavior from D's report that mixes concerns — suggest which handler
  should own each part.

SHARED STATE ELIMINATION
- For every piece of shared state D's report identified:
  propose how to eliminate it at the handler boundary.
- Options: pass as parameter, compute independently, accept as received value
  from predecessor.

COUPLING WARNINGS
- Where D's report shows tight coupling between handlers.
- For each: what the coupling is, why it's a problem for testability,
  and how to break it.

CONTRACT STRICTNESS
- For each handler: what should happen when inputs are invalid?
- Where should validation live? (Principle: validate at the boundary,
  trust internally.)

## Rules
- Design for testability above all. If a handler can't be tested in isolation
  with synthetic params, the boundary is wrong.
- Do not defend the monolith's structure. If the monolith mixes concerns,
  separate them.
- Do not write code. Produce designs and contracts only.
- Be specific about types, parameter names, and result shapes.

## D's Reconciliation Report (with operator annotations)
[D_OUTPUT_WITH_GATE1_ANNOTATIONS]

## Node Specs
[NODE_SPECS]
```

### F Prompt (Faithful — Fidelity Defender)

```
You are Agent F — the Faithful.

You receive a reconciliation report that maps monolith behaviors to proposed
handlers. You also have the reverse engineer's exhaustive behavioral map of
what the monolith actually does.

Your job is to defend every behavior the monolith has. This code runs in
production. Every line exists for a reason — even the ones that look wrong.

You are adversarial toward simplification, not toward the developer.

## Your Task

Produce these sections:

BEHAVIOR PRESERVATION REQUIREMENTS
- For each handler: the complete list of behaviors from R's map that MUST
  be preserved. Not "should" — MUST.
- Include: main logic, error handling, logging, side effects, cleanup.
- Rate each behavior: CRITICAL (handler is broken without it),
  IMPORTANT (degraded without it), DEFENSIVE (handles edge case that
  may not occur often but protects production).

COUPLING THAT MUST SURVIVE
- Shared state or ordering dependencies between phases that exist for a reason.
- For each: what the coupling is, what breaks without it, and a specific
  scenario where removing it causes failure.
- Example: "The DB connection is held open across table creation and chunk
  insertion because transaction isolation requires it — splitting into
  separate connections would allow partial writes."

ERROR RECOVERY PATHS
- For each handler: what error recovery the monolith performs in this phase.
- Which catch blocks are load-bearing (actually recover or clean up)
  vs ceremonial (log and re-raise).
- Cross-handler recovery: where the monolith's error handling in phase N
  cleans up work done in phase N-1.

SUBTLE BEHAVIORS
- Things that look unnecessary but aren't:
  - Ordering that matters ("metadata commit BEFORE TiPG refresh")
  - Defensive checks ("verify row count after insertion")
  - Fallback logic ("try X, if that fails, try Y")
  - Performance guards ("chunk size limits", "connection reuse")
- For each: what happens if the extracted handler omits this.

RISK REGISTER
- For each handler: what could go wrong if the extraction is done carelessly.
- Rate by likelihood x impact.
- Specific scenarios, not general warnings.

## Rules
- Defend every behavior R documented. If R found it, assume it matters
  until proven otherwise.
- Be specific about consequences. "This might break" is insufficient.
  "Omitting the row count cross-check allows silent data loss when
  chunk insertion silently skips rows due to constraint violations" is
  specific enough.
- Do not propose clean designs or simplifications. That is another agent's job.
- Do not write code. Produce requirements only.
- Cite R's line numbers and phase names for every requirement.

## D's Reconciliation Report (with operator annotations)
[D_OUTPUT_WITH_GATE1_ANNOTATIONS]

## Agent R's Behavioral Map
[R_OUTPUT]
```

### Step 4.5: Quality Gate

Before dispatching M, verify:
- [ ] P produced all sections (HANDLER DESIGNS, BOUNDARY ENFORCEMENT, SHARED STATE ELIMINATION, COUPLING WARNINGS, CONTRACT STRICTNESS)
- [ ] F produced all sections (BEHAVIOR PRESERVATION REQUIREMENTS, COUPLING THAT MUST SURVIVE, ERROR RECOVERY PATHS, SUBTLE BEHAVIORS, RISK REGISTER)
- [ ] P did NOT defend the monolith's structure
- [ ] F did NOT propose simplifications or clean designs
- [ ] Both cited D's report references

---

## Step 5: Dispatch M (Resolver — Sequential)

### M Prompt

```
You are Agent M — the Resolver.

You have two independent analyses of how to extract handlers from a monolith:

- Agent P (Purist) designed each handler for maximum atomicity and testability.
  P is skeptical of coupling and mixed responsibilities.
- Agent F (Faithful) documented every behavior that must be preserved.
  F defends the monolith's production-proven logic.

These agents worked independently. They will conflict. Your job is to resolve
those conflicts and produce a per-handler build specification that a developer
can code against.

You do NOT write code. You produce implementation plans.

## Your Task

Produce these sections:

CONFLICTS RESOLVED
- Where P's clean design would drop behavior F requires.
  For each: what P proposed, what F defended, your resolution, and the tradeoff.
- Where F's preservation requirements would undermine P's testability goals.
  For each: what F requires, why P objects, your resolution.
- Every resolution must explain the tradeoff. Do not silently drop a concern.

ESCALATED
- Conflicts you cannot resolve — design decisions that require operator judgment.
- For each:
  - What P wants and why
  - What F wants and why
  - Why you can't resolve it (legitimate competing concerns)
  - The two options and consequences of each
- These go to the operator at GATE₂.

HANDLER BUILD SPECS
- For EACH handler, a complete build specification:

  HANDLER: [name]
  PURPOSE: [one sentence]
  PARAMS: [name: type, required/optional, default]
  RETURNS: [result dict shape]
  BEHAVIORS TO PORT:
    - [behavior from F's list, with R's line range reference]
    - [behavior from F's list, with R's line range reference]
  NEW BEHAVIORS:
    - [behavior not in monolith, from D's report or P's design]
  ERROR HANDLING:
    - [specific catch/recovery from F's error recovery paths]
  SIDE EFFECTS:
    - [DB writes, blob operations, HTTP calls — from R's side effects list]
  SHARED STATE RESOLUTION:
    - [how P's elimination proposal is implemented, or why F's coupling is preserved]
  SUBTLE BEHAVIORS TO PRESERVE:
    - [from F's subtle behaviors list — things the builder must not forget]
  TESTING:
    - [from P's testability requirements — how to verify via test endpoint]

DEPENDENCY MAP
- Handler execution order with explicit data flow between them.
- What each handler passes to the next (parameter names and shapes).

RISK REGISTER
- Residual risks after all conflicts resolved.
- For each: description, likelihood, impact, mitigation.

## Rules
- Prefer F's preservation requirements when in doubt. The monolith works.
  A clean design that drops behavior is worse than a slightly coupled
  design that preserves it.
- Prefer P's boundaries when the coupling F defends can be replaced by
  parameter passing without behavior change.
- The HANDLER BUILD SPECS must be detailed enough that a developer (or a
  Sonnet agent) can write the handler code without asking follow-up questions.
- Every behavior from F's BEHAVIOR PRESERVATION REQUIREMENTS must appear in
  exactly one handler's BEHAVIORS TO PORT. Account for all of them.
- Do NOT write code. Produce specifications only.

## Agent P's Analysis (Purist)
[P_OUTPUT]

## Agent F's Analysis (Faithful)
[F_OUTPUT]

## D's Reconciliation Report (with operator annotations)
[D_OUTPUT_WITH_GATE1_ANNOTATIONS]
```

### GATE₂: Operator Reviews M's Report

The operator:
1. **Resolves ESCALATED conflicts** — makes the design calls M couldn't
2. **Reviews HANDLER BUILD SPECS** — confirms completeness and accuracy
3. **Approves the build plan** — green-lights B agent dispatch

M's HANDLER BUILD SPECS (with operator's escalation resolutions applied) become the work orders for B agents.

---

## Step 6: Dispatch B₁..Bₙ (Builders — Parallel Sonnets)

### B Prompt (one per handler)

```
You are a Builder agent. You write production code from a specification.

You receive:
1. A HANDLER BUILD SPEC — your complete work order. Build exactly what it says.
2. The MONOLITH CODE — the source to port behavior from. Reference the line
   ranges in your build spec.

## Your Task

Write one handler function that:
- Satisfies the handler contract: handler(params) → {"success": bool, "result": {...}}
- Ports all BEHAVIORS TO PORT from the specified monolith line ranges
- Implements all NEW BEHAVIORS described in the spec
- Implements the ERROR HANDLING described in the spec
- Preserves all SUBTLE BEHAVIORS described in the spec
- Uses the shared infrastructure modules described below

## Handler Build Spec
[M's HANDLER BUILD SPEC for this specific handler]

## Monolith Code
[MONOLITH_CODE]

## Existing Infrastructure
[INFRASTRUCTURE_DESCRIPTION — shared modules, repositories, utilities,
import paths, connection patterns]

## Handler Contract
[HANDLER_CONTRACT — function signature, return shape, file naming convention]

## Project Constitution (Build Constraints)
[Paste relevant Constitution sections — at minimum Sections 1 and 3.
These are hard rules the code must not violate: no backward compatibility
fallbacks, no f-string SQL, no catching ContractViolationError, etc.]

## Rules
- Implement what the spec says. Do not add features or optimizations
  the spec does not call for.
- Port code faithfully. If the monolith does something unusual, preserve it
  unless the spec explicitly says not to.
- Follow existing code conventions in the codebase (imports, logging patterns,
  error handling style).
- The handler must be independently testable via POST /api/dag/test/handler/{name}.
- Your code must not introduce Project Constitution violations.
```

### B Quality Gate

After all B agents return:
- [ ] Each handler has the correct function signature
- [ ] Each handler returns `{"success": bool, "result": {...}}`
- [ ] Each handler accounts for all BEHAVIORS TO PORT from its build spec
- [ ] No handler references another handler directly (they communicate via DAG params)

---

## Step 7: Chain to COMPETE

After all handlers are written:

1. Run **COMPETE** on the extracted handler files
2. Use **Split C (Data vs Control)** — natural fit for ETL handler code
3. Provide the monolith as developer context for Omega's scope selection
4. Provide M's HANDLER BUILD SPECS as developer context for what each handler should do

COMPETE catches implementation-level issues the DECOMPOSE pipeline's design-level agents didn't anticipate: race conditions, resource leaks, error masking, logging gaps.

---

## Step 8: Save Results

Write the full pipeline output to `docs/agent_review/agent_docs/DECOMPOSE_[monolith_name].md`.

Include:
- R's behavioral map
- X's handler designs
- D's reconciliation report (with GATE₁ operator annotations)
- P's atomic design and F's fidelity requirements
- M's resolved handler build specs (with GATE₂ escalation resolutions)
- B's generated handler code (file paths)
- COMPETE chain results (if run)

Log the run in `docs/agent_review/AGENT_RUNS.md` with:
- Run number, date, pipeline name (DECOMPOSE)
- Mode (guided or exploratory)
- Monolith file(s) and target handler count
- Token usage per agent
- Outcome: handlers produced, COMPETE findings count

---

## Scope Guidance

### Recommended Monolith Size Per Run

| Monolith Size | Target Handlers | Recommended Approach |
|---------------|----------------|---------------------|
| < 500 lines | 2-4 handlers | Single DECOMPOSE run — all agents comfortably within budget |
| 500-1,500 lines | 3-6 handlers | Single DECOMPOSE run — sweet spot for the pipeline |
| 1,500-3,000 lines | 5-10 handlers | Single run if handlers are well-bounded. Split if R's map exceeds 20 phases or M's build specs exceed 8 handlers. |
| > 3,000 lines | 8+ handlers | Split into multiple runs. Use R's phases to group into 2-3 DECOMPOSE runs of 4-5 handlers each. |

### When to Split Into Multiple Runs

Split when:
- **R's output is too large**: If R documents more than ~20 distinct phases, D will struggle to reconcile exhaustively. Split the monolith into logical groups (e.g., "data loading phases" and "processing phases") and run DECOMPOSE on each group.
- **M's handler count exceeds 8**: M's HANDLER BUILD SPECS must be detailed. More than 8 specs in a single M output risks the later specs being thin. Split into two runs.
- **B agent output ceiling**: Each Sonnet B agent produces one handler file. If handlers are individually large (> 300 lines each), the B agent may degrade. This is rarely a problem — well-decomposed handlers should be 50-150 lines.

### How to Split

1. Run R on the full monolith (R's behavioral map benefits from seeing the whole picture)
2. At GATE₁, group D's matched behaviors into run batches (e.g., "Run A: handlers 1-3" and "Run B: handlers 4-6")
3. Run P+F+M+B separately for each batch, using the same R and D outputs
4. Each batch chains to its own COMPETE run

### Monolith Clusters (Multiple Files)

If the monolith is spread across multiple tightly coupled files (e.g., a handler + its helpers + its core module):
- Give R ALL the files as a single code input. R maps the combined behavior.
- X still sees only node specs — doesn't matter how many source files exist.
- B agents receive all source files for porting reference.

If the files are loosely coupled (shared utilities used by many handlers), only give R the primary monolith file. Shared utilities go into the "Existing Infrastructure" description for X and B.

---

## Known Limitations

### Token Budget Estimates

| Agent | Expected Tokens | Notes |
|-------|----------------|-------|
| R | 80-120K | Scales with monolith size. 1,500 lines ≈ 100K tokens. |
| X | 40-60K | Scales with handler count, not monolith size. |
| D | 60-100K | Scales with R's output size. Exhaustive reconciliation is token-heavy. |
| P | 40-60K | Lighter — designs only, no code reading. |
| F | 50-80K | Heavier than P — defends per-behavior, cites extensively. |
| M | 80-120K | Heaviest after R — produces detailed per-handler build specs. |
| B (each) | 30-50K | Sonnet. Scales with handler complexity. Parallel = wall-clock fast. |

**Total per run** (6 handlers): ~450-650K tokens. Roughly 60% Opus, 40% Sonnet (by token count). Cost-weighted heavily toward Opus since Sonnet is ~5x cheaper per token.

### B Agent (Sonnet) Output Ceiling

Sonnet produces reliable code up to ~200-300 lines per handler. Beyond that, quality degrades (incomplete error handling, missing edge cases). Well-decomposed handlers should be 50-150 lines — within Sonnet's comfort zone.

If M's build spec implies a handler exceeding 300 lines, this is a signal that the handler is too large and should be split further. Flag at GATE₂.

### Pipeline Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| R misses a phase | D flags behaviors in X's spec that R didn't map (NEW BEHAVIORS where none were expected) | Re-run R with hint, or operator manually adds missing phase to R's map |
| X designs handlers that don't cover all behavior | D flags ORPHANED BEHAVIORS | Operator assigns orphans at GATE₁ |
| P and F both miss the same issue | COMPETE chain catches it after B builds | Fix in COMPETE's Top 5 Fixes |
| M produces thin build spec for later handlers | B agent produces incomplete handler | B Quality Gate catches it. Re-run that B agent with emphasis on missing behaviors. |
| B (Sonnet) produces buggy code | COMPETE chain, plus test endpoint validation | Fix issues from COMPETE report, re-test via endpoint |
| Operator makes wrong call at GATE₁ | Surfaces at P/F tension or M escalation | Revisit GATE₁ decisions. Pipeline is resumable from any gate. |

### Resumability

The pipeline is resumable from any gate. If GATE₂ reveals a fundamental boundary problem:
1. Adjust boundaries
2. Re-run X with new boundaries (R's behavioral map is still valid)
3. Re-run D, P+F, M from the new X output
4. No need to re-run R

---

## Chaining Patterns

### DECOMPOSE → COMPETE (Primary Chain)

After all B agents complete:

1. **Scope**: All extracted handler files + their shared utilities
2. **Split selection**: Split C (Data vs Control) for ETL handlers. Split A (Design vs Runtime) for God object decompositions.
3. **Developer context for Omega**:
   - The original monolith file (for reference)
   - M's HANDLER BUILD SPECS (what each handler should do)
   - D's ORPHANED/NEW behaviors (areas of elevated risk)
4. **Priority files for Gamma**: Any handler that M flagged in the RISK REGISTER

COMPETE catches what DECOMPOSE's design-level agents can't: implementation bugs, resource leaks, race conditions, logging gaps. DECOMPOSE ensures the *design* is right. COMPETE ensures the *code* is right.

### DECOMPOSE → SIEGE (Post-Deployment Validation)

After COMPETE fixes are applied and handlers are deployed:

1. Deploy handlers to Azure via `deploy.sh`
2. Test each handler individually via `POST /api/dag/test/handler/{name}` using M's TESTING specs
3. Run SIEGE with handler-level test vectors alongside workflow-level sequences
4. Verify that the wrapper handler (monolith calling atomics) produces identical results to the original monolith

### Multiple DECOMPOSE Runs (Iterative Decomposition)

For large monoliths split across multiple runs:

1. **Run 1**: Handlers 1-3. Chain to COMPETE. Deploy + SIEGE.
2. **Run 2**: Handlers 4-6. Same R and D outputs. Chain to COMPETE. Deploy + SIEGE.
3. **Final**: Build wrapper that calls all atomics in sequence. SIEGE regression on the wrapper.

Each run uses the same R behavioral map (R sees the whole monolith once). D's reconciliation is scoped to the current run's handler batch.

### DECOMPOSE (Exploratory) → ARB

For very large systems (not single files but clusters of God objects):

1. Run DECOMPOSE in exploratory mode on each major file
2. R's PROPOSED BOUNDARIES across all files reveal the natural subsystem boundaries
3. Feed these into ARB as the subsystem map
4. ARB sequences the decomposition into phases
5. Each ARB phase executes as a guided DECOMPOSE run

---

## Worked Example: Vector Handler Decomposition

**Monolith**: `services/handler_vector_docker_complete.py` (1,448 lines)
**Target**: 3 remaining handlers — `vector_load_source`, `vector_validate_and_clean`, `vector_create_and_load_tables`
**Mode**: Guided (boundaries from V10_MIGRATION.md)

### What R Would Produce

R reads the 1,448-line monolith and documents:

**PHASES** (R's names, not ours):
1. "Parameter extraction and validation" (lines 58-130)
2. "Source file loading and format conversion" (lines 421-600) — blob download, format detection, GeoDataFrame construction
3. "Geometry validation and cleaning" (lines 247-340 via core.validate_and_prepare) — CRS check, null removal, make_valid, force 2D, geometry type split
4. "Per-table processing loop" (lines 246-335) — iterates geometry groups
5. "Table creation and metadata registration" (lines 605-700) — DDL, register_table_metadata
6. "Chunk upload with checkpoints" (lines 754-850) — batched INSERT, deferred indexes, ANALYZE
7. "Split view creation" (lines 1023-1092) — conditional on split_column parameter
8. "TiPG refresh" (lines 1143-1146) — HTTP call to TiPG service
9. "Result assembly and cleanup" (lines 293-335, 390-420) — mount cleanup, result dict construction

**SIDE EFFECTS** R would catalog: DB table creation, metadata INSERT (two tables), chunk INSERTs, index creation, ANALYZE, split view DDL, catalog INSERTs for views, TiPG HTTP POST, blob download, mount file writes, mount cleanup, checkpoint writes, release_tables INSERT.

**SHARED STATE** R would flag: database connection held across phases 5-7, GeoDataFrame mutated across phases 2-3, checkpoint accumulator list, mount_paths dict.

### What X Would Produce

X reads the V10_MIGRATION.md node definitions and designs:

- `vector_load_source`: params(blob_name, container_name, file_extension, processing_options) → result(intermediate_path, source_metadata)
- `vector_validate_and_clean`: params(processing_options) + receives(source_path) → result(geometry_groups, intermediate_path, split_column_values)
- `vector_create_and_load_tables`: params(table_name, schema_name, processing_options) + receives(geometry_groups, validated_path) → result(tables_created[])

X would design each as independently testable with minimal params.

### What D Would Find

D reconciles R's 9 phases against X's 3 handlers:

- **MATCHED**: R's phases 2→load_source, R's phase 3→validate_and_clean, R's phases 5-6→create_and_load_tables
- **ORPHANED**: R's phase 1 (parameter extraction) — none of X's handlers claim it. R's phase 9 (result assembly) — none of X's handlers claim it. R's "release_tables INSERT" side effect — not in any handler spec.
- **BOUNDARY MISMATCH**: R shows the DB connection is held across phases 5-7 (table creation through split views). X's design puts phases 5-6 in `create_and_load_tables` and phase 7 in a separate `create_split_views` handler. The shared connection must be resolved.

### What Happens at GATE₁

Operator decisions:
- Parameter extraction → each handler validates its own params (standard atomic handler pattern)
- Result assembly → the DAG orchestrator handles this, not a handler. Drop it.
- release_tables INSERT → assign to `create_and_load_tables` (it knows the table results)
- DB connection boundary → P and F will argue about this. Let them.

### What P and F Would Argue About

**P**: "Each handler should open its own DB connection. `create_and_load_tables` commits its transaction. `create_split_views` opens a new connection. Clean boundary, independently testable."

**F**: "The monolith holds one connection across table creation, chunk upload, AND split views because the split views reference the table that was just created. If the connection is split and `create_and_load_tables` commits but `create_split_views` fails, you have tables with no views — an orphaned state the monolith prevents by using one transaction."

**M resolves**: "P is right that separate connections improve testability. F is right that the monolith's single-transaction prevents orphaned state. Resolution: `create_and_load_tables` commits its own transaction (tables must exist before views). `create_split_views` opens its own connection and is idempotent (CREATE OR REPLACE VIEW). If split views fail, re-running the handler creates them. The DAG's retry mechanism handles the failure case F is worried about. Note in SUBTLE BEHAVIORS: split views handler must use CREATE OR REPLACE, not CREATE — this is what makes the split safe."

---

## Design Decisions Log

Decisions made during pipeline design (19 MAR 2026):

1. **Spec-vs-code asymmetry** (not exhaustive-vs-functional): R reads monolith only, X reads specs only. The gap between actual behavior and intended design drives the analysis. Mirrors GREENFIELD's V agent principle.

2. **Two modes, one pipeline**: Guided (operator brings boundaries) and Exploratory (R proposes boundaries). Only the first stage differs — GATE₀ is inserted in exploratory mode. Everything downstream is identical.

3. **Tension resolvers don't write code**: M produces HANDLER BUILD SPECS, not handler code. M can escalate unresolvable conflicts to the operator. This matches GREENFIELD's M and ARB's P pattern.

4. **Sonnet builds, Opus thinks**: B agents are Sonnet for cost efficiency. Each gets a self-contained build spec + monolith code. Parallelizable per handler.

5. **P/F asymmetry**: P sees node specs but not R's behavioral map — designs for atomicity without implementation anchoring. F sees R's behavioral map but not node specs — defends behavior without knowing what "should" exist. Neither sees the monolith code directly.

6. **COMPETE chain**: Extracted handlers go through adversarial review. Split C (Data vs Control) is the default for ETL handlers. The monolith serves as developer context.

---

*Document created: 19 MAR 2026*
*Updated: 19 MAR 2026 — All sections complete. Ready for spec review.*
*Authors: Claude + Robert Harrison*
