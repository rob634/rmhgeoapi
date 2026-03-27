# FORGE Pipeline Design Spec

**Date**: 27 MAR 2026
**Status**: Draft
**Author**: Robert + Claude Prime

---

## Purpose

FORGE is a lightweight recursive agent pipeline that produces new code from a spec through iterative implement/review cycles. Each cycle spawns two fresh subagents — one implements, one aggressively critiques — and Claude Prime orchestrates the information flow between them.

FORGE fills the gap between writing code in a single pass and running the full 6-agent GREENFIELD ceremony. It's designed for features and subsystems where you want real code reviewed aggressively before acceptance, without the overhead of specialized role decomposition.

---

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `spec` | Yes | What to build — natural language, any format |
| `constitution_scope` | Yes | Review framework — a scoped subset/variant of the Constitution with constraints added or relaxed per run |
| `target_files` | Yes | Where code lands — new files or additions to existing files (additive only, never modifying existing lines) |
| `max_cycles` | No | Safety cap, default 5 |

---

## Agent Roles

Two roles, freshly spawned each cycle (no agent persists across cycles):

| Role | Runs As | Sees | Does NOT See |
|------|---------|------|-------------|
| **Implementer** | Subagent (new each cycle) | Spec + Prime's scoped brief + target files (if adding to existing) | Full critique history, constitution_scope, previous cycle code |
| **Reviewer** | Subagent (new each cycle) | Spec + constitution_scope + ALL code (current + previous cycles) + ALL prior critiques | Prime's scoping decisions, implementer's brief |
| **Claude Prime** | Orchestrator (not a subagent) | Everything | N/A — Prime is the omniscient coordinator |

### Information Asymmetry

The asymmetry is deliberate and load-bearing:

- **Implementer stays focused**: Narrow scope, no context overload, no anchoring to previous attempts. Constitutional principles reach the implementer implicitly through Prime's brief language — Prime is constitution-bound by its repo context, so the briefs naturally reflect constitutional thinking without the implementer ever seeing the document.

- **Reviewer has total situational awareness**: Full spec, explicit constitution_scope, all accumulated code, all previous critiques. Catches regressions, spec drift, and compounding issues across cycles.

- **Prime controls information flow**: Can emphasize, de-emphasize, or withhold findings based on judgment. This is a feature — but operators should be aware that Prime's context influences its scoping decisions (see Operator Warning).

### Operator Warning: Prime Context Bias

Claude Prime's context at the time of a run influences its scoping judgment. A Prime that just finished debugging a storage issue will unconsciously weight storage-related critique higher. This is sometimes desirable (domain-aware orchestration) and sometimes a blind spot. Operators should:

1. Be aware of what Prime has been doing before a FORGE run
2. Consider whether Prime's current context helps or hurts for this particular spec
3. Optionally state context bias expectations in the run setup (e.g., "Prime has no prior context on this subsystem" or "Prime just completed the related handler work")

---

## Cycle Flow

```
CYCLE 1:
  Prime → writes initial brief from spec (no prior critique)
  Implementer (subagent) → writes code from brief
  Reviewer (subagent) → aggressive critique against spec + constitution_scope
  Prime → reads critique, checks severities

CYCLE N (N > 1):
  Prime → reads cycle N-1 critique, cherry-picks findings into scoped brief
  Implementer (NEW subagent) → writes code from brief
  Reviewer (NEW subagent) → critiques ALL accumulated code
                             against spec + constitution_scope + ALL prior critiques
  Prime → reads critique, checks severities
```

### Termination

| Condition | Action |
|-----------|--------|
| CRITICAL or HIGH findings remain | Auto-scope next cycle |
| Only MEDIUM/LOW remain | Surface to Robert with summary — Robert decides |
| max_cycles reached | Surface to Robert regardless |
| Robert decides | Run another cycle, accept as-is, or abandon |

The severity gate is mechanical, not vibes-based. The reviewer MUST use the severity scale from the constitution_scope (defaulting to CRITICAL/HIGH/MEDIUM/LOW per the project Constitution).

---

## Reviewer Output Format

Each cycle produces `cycle_N_critique.md`:

```markdown
# FORGE Cycle N Critique

## Summary
[1-2 sentences: overall assessment of this cycle's implementation]

## Findings

### [CRITICAL] Finding title
- **Location**: filename.py:L42-L58
- **Issue**: What's wrong
- **Why it matters**: Spec or constitution_scope reference
- **Suggested fix**: Concrete direction

### [HIGH] Finding title
...

### [MEDIUM] Finding title
...

### [LOW] Finding title
...

## Suggested Next Scope
[Prioritized list of items for the next implementer cycle.
 Reviewer suggests, Prime decides.]

## Residual Risks
[Items reviewer believes are acceptable trade-offs, not bugs.]
```

---

## Output Structure

```
docs/agent_review/forge_runs/
  run_NNN/
    cycle_1_code/              ← implementer output (clean .py files)
    cycle_1_critique.md        ← reviewer output (full aggressive critique)
    cycle_2_code/
    cycle_2_critique.md
    ...
    run_summary.md             ← terminal output
```

**Code stays in the run directory during FORGE.** The operator promotes accepted code to its real location (e.g., `services/`, `jobs/`) after the run completes and is accepted. This keeps the working tree clean during iteration and gives the operator a clear promotion step.

### Run Summary Template

```markdown
# FORGE Run NNN — [Brief description]

**Spec**: [spec reference]
**Constitution Scope**: [what was included/relaxed]
**Cycles**: N
**Prime Context Note**: [what Prime had been working on, if relevant]

## Cycle Log
| Cycle | Implementer Scope | Findings | CRIT | HIGH | MED | LOW |
|-------|-------------------|----------|------|------|-----|-----|
| 1     | [brief]           | N        | ...  | ...  | ... | ... |
| 2     | [brief]           | N        | ...  | ...  | ... | ... |

## Final State
- **Resolved**: [count] findings across [count] cycles
- **Residual**: [MEDIUM/LOW findings accepted by Robert]
- **Files produced**: [list]

## Operator Decision
[Robert's final call: accepted / accepted with notes / abandoned]
```

---

## Pipeline Relationships

| Pipeline | Purpose | FORGE replaces? |
|----------|---------|-----------------|
| **COMPETE** | Find bugs in existing code via adversarial review | No — FORGE builds, COMPETE audits |
| **GREENFIELD** | Design-then-build with 6 specialized roles | Partially — lighter alternative when full ceremony is overkill |
| **REFLEXION** | Harden fragile existing code with surgical patches | No — FORGE is additive-only, REFLEXION modifies |

### Chaining

- FORGE output → COMPETE (adversarial audit of produced code)
- FORGE output → REFLEXION (harden produced code)
- COMPETE findings → FORGE (build the fix as new code)

---

## Cost Estimate

~100-150K tokens per cycle (two subagent spawns + Prime orchestration). A typical 3-cycle run: ~350-450K tokens — comparable to a single COMPETE run but producing actual code.

---

## Implementation

The pipeline is implemented as a markdown playbook at `docs/agent_review/agents/FORGE_AGENT.md`. Claude Prime follows the playbook manually — no automation, no skill. The playbook contains prompt templates for both subagent roles and step-by-step cycle protocol.
