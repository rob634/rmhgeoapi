# Pipeline 7: FORGE (Iterative Implement/Review)

**Purpose**: Produce new code from a spec through recursive implement/review cycles with aggressive critique and converging quality.

**Best for**: New features or subsystems where you want real code out the other end, reviewed aggressively, without the full GREENFIELD ceremony.

**Cost**: ~100-150K tokens per cycle. Typical run: 3 cycles (~350-450K tokens).

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| Claude Prime | Orchestrate cycles, scope implementer briefs, gate termination | Orchestrator (not a subagent) | Everything |
| Implementer | Write code from a narrow scoped brief | Subagent (new each cycle) | Spec + Prime's brief + target files |
| Reviewer | Aggressively critique all accumulated code | Subagent (new each cycle) | Spec + constitution_scope + all code + all critiques |

**Maximum parallel agents**: 0 (strictly sequential — implementer then reviewer)

---

## Flow

```
Spec + Constitution Scope
    |
    Prime (Claude plays this role)
    Writes initial brief from spec
    |
    Implementer (Subagent)         [cycle 1]
    Writes code from brief
    |
    Reviewer (Subagent)            [cycle 1]
    Aggressive critique
    |
    Prime reads critique
    |
    +-- CRITICAL/HIGH remain? ---> Scope next cycle, GOTO Implementer
    |
    +-- Only MEDIUM/LOW? -------> Surface to Robert
    |
    +-- max_cycles reached? -----> Surface to Robert
```

---

## Inputs

Before starting, confirm these with the operator:

| Input | Required | Notes |
|-------|----------|-------|
| `spec` | Yes | What to build — any format |
| `constitution_scope` | Yes | Scoped review framework — can add or relax constraints |
| `target_files` | Yes | New files or existing files (additive only) |
| `max_cycles` | No | Default 5 |

---

## Information Asymmetry Rules

These are hard rules. Do not deviate.

### Implementer sees:
- The spec (or relevant excerpt)
- Prime's scoped brief for this cycle (cherry-picked findings, not full critique)
- Target files if adding to existing code

### Implementer does NOT see:
- Full critique history from any previous cycle
- The constitution_scope document
- Previous cycle code
- Prime's scoping rationale

### Reviewer sees:
- The spec (full)
- The constitution_scope document (explicit — review against it)
- ALL code from the current cycle AND all previous cycles
- ALL previous cycle critiques

### Reviewer does NOT see:
- Prime's scoping decisions or implementer briefs
- What Prime chose to include or exclude from the implementer's brief

### Why this matters:
- The implementer receives constitutional thinking implicitly through Prime's brief language. Prime is constitution-bound by its repo context, so briefs naturally reflect constitutional principles without the implementer seeing the document.
- The reviewer is the external auditor — it checks against standards the implementer was never handed directly.
- Fresh agents each cycle prevent anchoring, blind spot compounding, and politeness drift.

---

## Operator Warning: Prime Context Bias

Claude Prime's context at run time influences scoping judgment. A Prime that just debugged a storage issue will unconsciously weight storage-related critique higher.

**This is sometimes desirable** — domain-aware scoping.
**This is sometimes a blind spot** — over-indexing on recent work.

Operators should note Prime's prior context in the run summary. Consider whether it helps or hurts for this spec.

---

## Step 1: Setup

1. Read the spec.
2. Read the constitution_scope.
3. Confirm target files with the operator.
4. Create the run directory:
   ```
   docs/agent_review/forge_runs/run_NNN/
   ```
5. Note your current context in the run summary (what you've been working on, if anything).

---

## Step 2: Write the Implementer Brief (Cycle 1)

For the first cycle, the brief comes directly from the spec. Write a focused brief that tells the implementer:

- What to build (derived from spec)
- Where to put it (target files)
- Constraints relevant to the implementation (but NOT the constitution — that's implicit in your language)

**Keep it narrow.** The implementer should be able to hold the entire brief in working memory.

---

## Step 3: Spawn Implementer

Launch a subagent with the Agent tool. Use this prompt structure:

```
You are the Implementer in a FORGE pipeline cycle. Your job is to write code
based on the brief below. Write clean, working code. Additive only — if adding
to existing files, do not modify existing lines.

## Brief
{Prime's scoped brief}

## Spec
{Spec or relevant excerpt}

## Target Files
{File paths and descriptions}

## Instructions
- Write real .py files using the Write tool
- Place files in: docs/agent_review/forge_runs/run_NNN/cycle_N_code/
- Code stays in the run directory during FORGE — the operator promotes accepted code to its real location after the run
- If adding to existing files, read the originals first to understand context, but write your additions as standalone files in the cycle directory
- Focus only on what the brief asks for
- Do not add speculative features beyond the brief
```

---

## Step 4: Spawn Reviewer

After the implementer completes, launch a NEW subagent with the Agent tool. Use this prompt structure:

```
You are the Reviewer in a FORGE pipeline cycle. Your job is to aggressively
critique the implementation against the spec and constitution scope. Be thorough
and adversarial — find every issue. Do not soften findings.

## Spec
{Full spec}

## Constitution Scope
{Full constitution_scope document}

## Code to Review
{List all code files from current cycle AND previous cycles}
Read every file listed above.

## Previous Critiques
{All previous cycle critique files, if any — omit for cycle 1}
Read every critique listed above.

## Instructions
- Read ALL code files thoroughly
- Review against the spec: does the code fulfill the spec?
- Review against the constitution_scope: does the code violate any constraints?
- Check for regressions against previous critiques (if any)
- Use severity scale: CRITICAL / HIGH / MEDIUM / LOW
- For each finding: Location (file:line), Issue, Why it matters, Suggested fix
- Include a "Suggested Next Scope" section — prioritize what the next implementer should tackle
- Include a "Residual Risks" section — trade-offs you consider acceptable
- Write your critique to: docs/agent_review/forge_runs/run_NNN/cycle_N_critique.md
```

---

## Step 5: Read Critique and Decide

After the reviewer completes:

1. Read `cycle_N_critique.md`
2. Count findings by severity
3. Apply the severity gate:

| Condition | Action |
|-----------|--------|
| Any CRITICAL or HIGH findings | Proceed to Step 6 (scope next cycle) |
| Only MEDIUM/LOW findings | Proceed to Step 7 (surface to Robert) |
| max_cycles reached | Proceed to Step 7 regardless |

---

## Step 6: Scope Next Cycle

1. Read the reviewer's "Suggested Next Scope" section
2. Apply your own judgment — you may:
   - Accept the reviewer's priorities as-is
   - Re-prioritize based on your understanding of the spec
   - Combine or split findings into a coherent implementer scope
   - Withhold findings you judge are not actionable yet
3. Write a new implementer brief (as in Step 2, but now informed by critique)
4. Return to Step 3 with the new cycle number

**Remember**: The implementer gets ONLY your scoped brief — not the full critique.

---

## Step 7: Surface to Robert

Present to the operator:
- Cycle count and trajectory (are findings decreasing?)
- Remaining MEDIUM/LOW findings with locations
- Your recommendation: accept, run another cycle, or abandon
- Any residual risks flagged by the reviewer

Wait for Robert's decision:
- **Accept**: Proceed to Step 8
- **Another cycle**: Return to Step 6
- **Abandon**: Write run summary noting abandonment reason

---

## Step 8: Write Run Summary

Write `docs/agent_review/forge_runs/run_NNN/run_summary.md`:

```markdown
# FORGE Run NNN — [Brief description]

**Date**: [DD MMM YYYY]
**Spec**: [spec reference]
**Constitution Scope**: [what was included/relaxed]
**Cycles**: N
**Prime Context Note**: [what Prime had been working on, if relevant]

## Cycle Log
| Cycle | Implementer Scope | Findings | CRIT | HIGH | MED | LOW |
|-------|-------------------|----------|------|------|-----|-----|
| 1     | [brief]           | N        | ...  | ...  | ... | ... |

## Final State
- **Resolved**: [count] findings across [count] cycles
- **Residual**: [MEDIUM/LOW findings accepted by Robert]
- **Files produced**: [list with paths]

## Operator Decision
[Robert's final call: accepted / accepted with notes / abandoned]
```

---

## Pipeline Chaining

| From | To | When |
|------|----|------|
| FORGE output | COMPETE | Adversarial audit of produced code |
| FORGE output | REFLEXION | Harden produced code |
| COMPETE findings | FORGE | Build fixes as new code |
