# Pipeline Instrumentation Guide

## Overview

This document describes how to capture token usage and output quality metrics per agent per pipeline run. The goal is to answer two questions:

1. **How does token use scale** with task complexity (small feature vs. full project review)?
2. **How well does the instruction set scale** — does output quality degrade as scope increases?

**Last Updated**: 03 MAR 2026

---

## Part 1: Token Usage Tracking

### How Pipelines Actually Run

All agent pipelines run inside a single Claude Code interactive session. The operator (Robert) plays the first agent (Sentinel/Omega/Strategist/etc.) directly, then dispatches each subsequent agent via the **Agent tool** as a Task subagent.

Each Agent tool invocation returns per-agent usage metadata in the result:

```
<usage>total_tokens: 85094
tool_uses: 9
duration_ms: 79563</usage>
```

This is the **primary data source** for token tracking. No wrapper scripts are needed.

### What's Available Per Agent

| Field | Source | What It Tells You |
|-------|--------|------------------|
| `total_tokens` | Agent tool `<usage>` | Combined input + output tokens for the agent's full execution |
| `tool_uses` | Agent tool `<usage>` | Number of tool calls the agent made (file reads, searches, HTTP calls) |
| `duration_ms` | Agent tool `<usage>` | Wall clock time for the agent's execution |

**Note**: The Agent tool reports `total_tokens` (combined), not split into input/output. For parallel agents (e.g., Alpha + Beta in COMPETE, A + C + O in GREENFIELD), each agent's usage is reported independently.

### What's NOT Available Per Agent

| Field | Why Not | Workaround |
|-------|---------|------------|
| `input_tokens` vs `output_tokens` | Agent tool reports combined total only | Estimate: agents that read more code have higher input ratio; agents that generate reports have higher output ratio |
| `cache_read` / `cache_write` | Not broken out in Agent tool results | Session-level caching is automatic; parallel agents sharing the same codebase context benefit from cache hits, but this isn't quantified per agent |
| Output size (bytes/lines) | Agent output is returned as text, not measured | Count lines in the saved report file after the run |

### Where Token Data Is Recorded

**Primary log**: `docs/agent_review/AGENT_RUNS.md`

Each run entry (Run 9+) includes a **Token Usage** table:

```markdown
**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Alpha | Data Integrity | 81,312 | 4m 36s |
| Beta | Flow Control | 114,589 | 4m 19s |
| Gamma | Contradictions | 82,310 | 3m 57s |
| Delta | Final Report | 68,445 | 3m 25s |
| **Total** | | **346,656** | **~16m 17s** |
```

**Recording protocol** (for the operator running the pipeline):

1. After each Agent tool call completes, copy `total_tokens` and `duration_ms` from the `<usage>` block.
2. Convert `duration_ms` to human-readable format (e.g., 276000 → 4m 36s).
3. For inline agents (Sentinel/Omega/etc. played by Claude directly), record "—" for tokens and "inline" for duration.
4. Sum all agent tokens for the run total.
5. Record in the AGENT_RUNS.md entry for that run.

### Historical Data

| Run Range | Token Data? | Notes |
|-----------|------------|-------|
| Runs 1–8 | No | Pre-instrumentation; no per-agent tracking |
| Runs 9–27 | Yes | Instrumented total: ~4,743,688 tokens across 19 runs |
| Run 28+ | Yes | Current standard |

### Token Benchmarks by Pipeline (from actual runs)

| Pipeline | Runs | Agents | Avg Tokens/Run | Range | Heaviest Agent |
|----------|------|--------|---------------|-------|----------------|
| **COMPETE** | 9 (Runs 1-6, 9, 12) | 4 (Alpha+Beta parallel, Gamma, Delta) | ~340K (instrumented runs) | 337K–347K | Beta (correctness reviewer) |
| **GREENFIELD** | 3 (Runs 7, 8, 10) | 6 (A+C+O parallel, M, B, V) | ~631K (Run 10) | — | B (builder, 7-8 min) |
| **REFLEXION** | 4 (Runs 14-17) | 4 (R→F→P→J sequential) | ~153K | 51K–279K | F (fault injector) |
| **SIEGE** | 9 (Runs 11, 13, 18-26) | 4 (Cartographer→Lancer→Auditor→Scribe) | ~230K | 179K–251K | Lancer (lifecycle execution) |
| **TOURNAMENT** | 1 (Run 27) | 5 (Pathfinder+Saboteur parallel, Inspector+Provocateur parallel, Tribunal) | ~580K | — | Saboteur |
| **WARGAME** | 0 | — | — | — | — |
| **ADVOCATE** | 0 | — | — | — | — |
| **OBSERVATORY** | 0 | — | — | — | — |

---

## Part 2: Output Quality Metrics

### The Problem

"Was the output good?" is subjective unless you define what good means. Each pipeline has different quality signals.

### Pipeline-Specific Quality Rubrics

#### GREENFIELD Quality Signals

| Signal | Source | Metric |
|--------|--------|--------|
| **Spec fidelity** | V's spec diff (Step 7) | `matches / (matches + gaps)` — ratio of spec coverage |
| **Scope creep** | V's spec diff (Step 7) | `extras / (matches + extras)` — ratio of unspecified behavior |
| **Conflict resolution** | M's output | Conflicts found vs resolved; concerns dropped (should be 0) |
| **Builder completeness** | B's code output | Did B produce all components in M's resolved spec, or did later components become stubs? |
| **Section completeness** | All agents | Per-section score: 2 = substantive, 1 = thin, 0 = missing |

**Known scaling issue** (Run 19): Builder output budget collapse on large specs. B exhausts output capacity and later components degrade to stubs. Watch for this on `large` complexity runs.

#### COMPETE Quality Signals

| Signal | Source | Metric |
|--------|--------|--------|
| **Blind spot discovery** | Gamma's output | Findings that Alpha missed AND Beta missed — Gamma's unique contribution |
| **Asymmetry effectiveness** | Gamma's contradictions | Count of productive contradictions (Alpha and Beta disagree, both partially right) |
| **Actionability** | Delta's Top 5 Fixes | Each fix has WHAT/WHY/WHERE/HOW/EFFORT/RISK — score completeness |
| **False positive rate** | Post-run verification | Findings that turned out to be non-issues when code was actually tested |

#### REFLEXION Quality Signals

| Signal | Source | Metric |
|--------|--------|--------|
| **R accuracy** | Reflexion check | Does R's inferred purpose match actual intent? Gaps reveal misleading code or missing docs |
| **Fault coverage** | F's output | How many of 9 fault categories were tested? (Network, Dependencies, Database, Concurrency, Resources, Data, Time, Infrastructure, Authentication) |
| **Patch surgical-ness** | P's patches | Do patches touch ONLY the fault? No happy-path changes, no rewrites, no signature changes |
| **Fix rate** | Post-deployment | Patches that actually fixed the bug vs introduced new issues |

#### SIEGE Quality Signals

| Signal | Source | Metric |
|--------|--------|--------|
| **Sequence pass rate** | Scribe's summary | Passed sequences / total sequences (target: 100%) |
| **Regression detection** | Cross-run comparison | Did previously-passing sequences regress? |
| **Service URL integrity** | Auditor's probes | Do rendered outputs (TiTiler, TiPG, xarray) actually work? |
| **State divergence count** | Auditor's output | Expected vs actual state mismatches (target: 0) |

#### TOURNAMENT Quality Signals

| Signal | Source | Metric |
|--------|--------|--------|
| **Pathfinder pass rate** | Pathfinder output | Golden-path sequences that completed successfully |
| **Saboteur block rate** | Saboteur output | Attacks that were correctly rejected / total attacks |
| **Inspector divergences** | Inspector output | Unexplained state differences from Pathfinder's checkpoints |
| **Provocateur validation gaps** | Provocateur output | Invalid inputs that got through / total invalid inputs tested |
| **Unique findings per agent** | Tribunal scoreboard | Findings only discoverable through one agent's lens |

#### OBSERVATORY Quality Signals

| Signal | Source | Metric |
|--------|--------|--------|
| **Coverage score** | Assessor's matrix | Systems scoring >= 2 on Detection + Diagnosis / total systems |
| **az CLI gap count** | Assessor's gap analysis | Operations still requiring az CLI |
| **Incident scenario readiness** | Assessor's scenario grading | Scenarios diagnosable via API-only / total scenarios |
| **Endpoint quality** | Cartographer's probes | Average completeness + actionability + freshness across all probed endpoints |

### Section Completeness Scoring (All Pipelines)

For each agent's output, check whether all required sections are present and non-trivial (more than 3 sentences):

- **2** = present and substantive
- **1** = present but thin (under 3 sentences or generic)
- **0** = missing

### Complexity Classification

Tag complexity **before** the run starts. Do not change it after seeing results.

| Complexity | Indicators |
|-----------|-----------|
| **small** | Single endpoint, 1-2 files, <300 lines of output code, spec fits in one screen |
| **medium** | 2-4 endpoints or components, 3-5 files, 300-1000 lines, multiple integration points |
| **large** | Full subsystem, 5+ files, 1000+ lines, multiple downstream services, auth/security concerns |

---

## Part 3: Aggregation and Analysis

### Cross-Run Comparison (from AGENT_RUNS.md)

Since all token data lives in `AGENT_RUNS.md` as markdown tables, cross-run analysis is done by reading the tables. Key comparisons:

**Token scaling by pipeline**:
- REFLEXION is cheapest (~150K avg) — sequential, focused scope
- COMPETE is mid-range (~340K) — parallel asymmetric review
- SIEGE is mid-range (~230K) — sequential endpoint probing
- GREENFIELD is most expensive (~630K) — 7 agents, Builder generates code
- TOURNAMENT is expensive (~580K) — 5 agents, heavy adversarial testing

**Token scaling by complexity** (within a pipeline):
- REFLEXION: small scope (1 file) = ~50K (Run 16), medium scope (10 files) = ~280K (Run 15)
- SIEGE: consistent ~180K-250K regardless of pass/fail (endpoint count is fixed)

### What You're Looking For

**Token scaling (Question 1):**
- Does total token usage scale linearly with scope (file count), or worse?
- Which agent is the token hog per pipeline? (See benchmarks table above)
- Do parallel agents (Alpha+Beta, A+C+O) stay proportional, or does one blow up on large tasks?

**Quality scaling (Question 2):**
- Does sequence pass rate drop as the API grows? (SIEGE)
- Does spec fidelity drop as complexity increases? (GREENFIELD)
- Does the number of findings plateau or keep growing with scope? (COMPETE)
- Does patch correctness hold when fault count is high? (REFLEXION)

### Red Flags to Watch For

#### GREENFIELD Red Flags

| Signal | What It Means |
|--------|--------------|
| `fidelity_score` < 0.7 | More than 30% of the spec isn't in the code. Pipeline is losing information. |
| `scope_creep_score` > 0.2 | B is freelancing. M's resolved spec may not be specific enough. |
| `concerns_dropped` > 0 | M is failing. C's work is being wasted. |
| Agent O tokens >> A or C | O is generating generic cloud advice instead of specific operational assessment. |
| M tokens > B tokens | M is over-elaborating. The resolved spec is too verbose for B to follow. |
| B output trails off into stubs | Output budget collapse. Scope is too large for single-pass Builder. |

#### COMPETE Red Flags

| Signal | What It Means |
|--------|--------------|
| Gamma finds 0 contradictions | Alpha/Beta scope split is too clean — not enough overlap to create productive friction. |
| Delta's Top 5 missing HOW or WHERE | Delta is summarizing, not synthesizing. Findings aren't actionable. |
| Alpha and Beta token counts differ by >3x | One scope is much larger than the other. Rebalance the split. |

#### SIEGE Red Flags

| Signal | What It Means |
|--------|--------------|
| Same sequence fails across multiple runs | Persistent bug — REFLEXION or manual fix needed. |
| Lancer tokens >> 100K | Lancer is retrying or polling excessively. Check poll interval. |
| Auditor finds divergences Lancer didn't flag | Lancer's checkpoints are incomplete. |

#### REFLEXION Red Flags

| Signal | What It Means |
|--------|--------------|
| R's inferred purpose is wrong | Code is misleading. This is itself a finding (documentation bug). |
| F tests <5 of 9 fault categories | F is being lazy or the scope is too narrow. |
| P changes function signatures | Violation of hard constraint. Patch must be rejected. |
| J approves everything | J is rubber-stamping. Check J's prompt for rigor. |

#### OBSERVATORY Red Flags

| Signal | What It Means |
|--------|--------------|
| Any system scores 0 on Detection | Blind spot — system failure is invisible. Immediate P0 gap. |
| Cartographer gets errors on >20% of endpoints | Endpoints are broken or misconfigured. Fix before assessing coverage. |
| Surveyor finds systems not in the inventory | Inventory (S1–S12) is stale. Update before continuing. |

---

## Part 4: Pipeline Instructions Integration

### Instrumentation Protocol

Every pipeline run MUST record token usage in `AGENT_RUNS.md`. The recording process:

1. **Before the run**: Assign the next run number (check AGENT_RUNS.md for the latest).
2. **During the run**: After each Agent tool dispatch completes, note the `total_tokens`, `tool_uses`, and `duration_ms` from the `<usage>` block in the result.
3. **After the run**: Add the run entry to AGENT_RUNS.md with:
   - Standard fields (Date, Pipeline, Scope, Verdict, Output file)
   - Token Usage table (per-agent breakdown + total)
   - Finding Summary table (if applicable)

### Run ID Convention

Run IDs in AGENT_RUNS.md are sequential integers: Run 1, Run 2, ... Run 28, etc.

For file-based artifacts, use: `{PIPELINE}_RUN_{N}.md` (e.g., `SIEGE_RUN_9.md`).

### How to Tag Complexity

Before starting Step 1, classify the task:
- **small**: Single component, <300 lines expected, 1-2 integration points
- **medium**: Multiple components, 300-1000 lines, 3+ integration points
- **large**: Full subsystem, 1000+ lines, auth/security/multi-service

Record this in the AGENT_RUNS.md entry. Do not change it after seeing the results.

### Duration Conversion

Convert `duration_ms` from Agent tool output to human-readable format for AGENT_RUNS.md:

| duration_ms | Display |
|-------------|---------|
| 79563 | 1m 20s |
| 276000 | 4m 36s |
| 467000 | 7m 47s |

Formula: `minutes = ms / 60000`, `seconds = (ms % 60000) / 1000`
