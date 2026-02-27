# Agent Playbooks — Multi-Agent Code Review

**Last Updated**: 26 FEB 2026 (v2 — incorporated Browser Claude feedback)

Two adversarial multi-agent pipelines that Claude Code executes using the Task tool with subagents. No API key required — runs entirely within Claude Code.

---

## When to Use Which

| Pipeline | Use When | Agents | Output |
|----------|----------|--------|--------|
| **Adversarial Review** | Reviewing a subsystem for architecture + correctness issues | Omega → Alpha + Beta (parallel) → Gamma → Delta | Prioritized findings with severity calibration |
| **Kludge Hardener** | Hardening working-but-fragile code with surgical patches | R → F → P → J (sequential) | Approved patches with implementation plan |

**Adversarial Review** is broader — it finds problems across design and correctness.
**Kludge Hardener** is narrower — it finds failure modes and writes specific fixes.

---

## Pipeline 1: Adversarial Review

### Flow

```
Code files
    │
    Omega (Claude plays this role)
    Partition review into two asymmetric scopes
    │
    ┌───────────┴───────────┐
    Alpha (Task, parallel)   Beta (Task, parallel)
    Architecture lens        Correctness lens
    └───────────┬───────────┘
                │
    Gamma (Task)
    Find contradictions, blind spots,
    and where both missed something
                │
    Delta (Task)
    Synthesize into prioritized
    actionable report
```

### Step-by-Step Execution

#### Step 1: Gather Code
Read all files in the target subsystem. Use the Explore agent if needed to find the full file inventory.

#### Step 2: Play Omega
Claude plays Omega directly (no subagent needed). Partition the review scope into two asymmetric lenses that create productive tension:

| Agent | Lens | Sees | Doesn't See |
|-------|------|------|-------------|
| Alpha | Architecture & Design | Composition, contracts, coupling, layering, extension points | Race conditions, edge cases, data integrity |
| Beta | Correctness & Reliability | Race conditions, error recovery, atomicity, state machine holes | Design intent, architectural rationale |

The information asymmetry is the key insight: each agent catches different blind spots, and their disagreements reveal the most interesting bugs.

**Omega also prepares Gamma's focus list**: Note which files you assign to Alpha and Beta. After their reviews return, identify files that neither reviewer cited heavily — these are Gamma's priority targets for blind spot hunting.

**Dry Run option**: To sanity-check the partition before burning tokens, stop after this step and show the user the proposed Alpha/Beta scopes and file assignments. Only dispatch after confirmation.

#### Step 3: Dispatch Alpha + Beta in Parallel
Use two Task tool calls in a single message (parallel execution):

**Alpha prompt template:**
```
You are Claude Alpha — an Architecture Reviewer in an adversarial code review pipeline.

You are reviewing [SUBSYSTEM DESCRIPTION]. You have been given ONLY the architecture
and design lens. You have NOT been given correctness/edge-case concerns — another
reviewer is handling that independently.

## YOUR REVIEW SCOPE (Architecture & Design ONLY)
1. Composition vs Inheritance
2. Separation of Concerns
3. Contract Design
4. State Machine Design (if applicable)
5. Extension Points
6. Layering Violations
7. Registry/Plugin Patterns
8. Error Handling Architecture

## FILES TO READ
[List exact file paths]

## OUTPUT FORMAT
- STRENGTHS: What's architecturally sound (cite files/lines)
- CONCERNS: Issues ranked HIGH/MEDIUM/LOW with file, line range, impact
- ASSUMPTIONS: Design assumptions that may or may not hold
- RECOMMENDATIONS: Specific actionable improvements

DO NOT evaluate correctness, race conditions, or edge cases.
```

**Beta prompt template:**
```
You are Claude Beta — a Correctness and Reliability Reviewer in an adversarial
code review pipeline.

You are reviewing [SUBSYSTEM DESCRIPTION]. You have been given ONLY the correctness
and reliability lens. You have NOT been given architecture/design concerns — another
reviewer is handling that independently.

## YOUR REVIEW SCOPE (Correctness & Reliability ONLY)
1. Race Conditions
2. State Machine Completeness
3. Error Recovery
4. Idempotency
5. Data Integrity
6. Timeout Handling
7. Connection/Resource Exhaustion
8. Exception Swallowing
9. Atomicity of Multi-Step Operations
10. State Transition Gaps

## FILES TO READ
[List exact file paths]

## OUTPUT FORMAT
- VERIFIED SAFE: Patterns confirmed correct (cite files/lines)
- BUGS: Confirmed/likely bugs ranked CRITICAL/HIGH/MEDIUM with scenario + impact
- RISKS: Issues dependent on runtime conditions
- EDGE CASES: Scenarios that may not be handled

DO NOT evaluate architecture, design patterns, or code style.
```

#### Step 3.5: Quality Gate
Before dispatching Gamma, verify Alpha and Beta outputs follow the output format (STRENGTHS/CONCERNS/ASSUMPTIONS/RECOMMENDATIONS for Alpha; VERIFIED SAFE/BUGS/RISKS/EDGE CASES for Beta). If either agent returned unstructured prose instead of the requested sections, re-dispatch with the format instructions emphasized.

#### Step 4: Dispatch Gamma
After Alpha and Beta complete, dispatch Gamma with BOTH reviews:

**Gamma prompt template:**
```
You are Claude Gamma — the Adversarial Contradiction Finder in a code review pipeline.

You have received TWO independent reviews of the same codebase. The reviews were
conducted with information asymmetry — neither reviewer saw the other's scope:
- Alpha reviewed ONLY architecture and design
- Beta reviewed ONLY correctness and reliability

Your job is to find where they DISAGREE, where they BOTH MISSED something,
and where one reviewer's finding undermines the other's conclusions.

## ALPHA'S REVIEW:
[Paste Alpha output]

## BETA'S REVIEW:
[Paste Beta output]

## GAMMA'S PRIORITY FILES
[List files that neither Alpha nor Beta cited heavily — these are where blind spots hide.
Omega identifies these by comparing cited files against the full file list.]

## YOUR TASK
Produce:
1. CONTRADICTIONS — Where Alpha and Beta disagree or have incompatible conclusions
2. AGREEMENT REINFORCEMENT — Where both independently found the same issue (highest confidence)
3. BLIND SPOTS — Prioritize reading the GAMMA'S PRIORITY FILES above to find issues neither caught
4. SEVERITY RECALIBRATION — Re-rank ALL findings on a unified scale

For EVERY finding (yours and theirs), tag confidence level:
- CONFIRMED: You read the code and verified the issue exists
- PROBABLE: Strongly suggested by code patterns but not fully traced
- SPECULATIVE: Plausible based on reviews but not verified against code

Look specifically for: security issues, concurrency gaps, silent data loss,
configuration-dependent failures, logging that leaks sensitive data.
```

#### Step 5: Dispatch Delta
Delta gets everything and synthesizes the final report:

**Delta prompt template:**
```
You are Claude Delta — the Lead Architect and Final Arbiter.

You have the FULL picture: two independent reviews plus Gamma's adversarial analysis.

Produce a FINAL ACTIONABLE REPORT with exactly these sections:
- EXECUTIVE SUMMARY (3-5 sentences)
- TOP 5 FIXES (What, Why, Where, How, Effort, Risk)
- ACCEPTED RISKS (real but not worth fixing now, with rationale)
- ARCHITECTURE WINS (what's genuinely well-done — preserve these)

CRITICAL CONSTRAINT: For every fix, include the exact file path, function name, and
line range. Do not give abstract recommendations — be surgical. A developer should be
able to open the file and navigate directly to the issue.

Prioritize CONFIRMED findings over PROBABLE over SPECULATIVE (use Gamma's confidence tags).

[Paste Gamma's recalibrated findings]

Read [KEY FILES] to confirm recommendations.
Keep concise — write for a senior developer who knows the codebase.
```

#### Step 6: Save Results
Write the final report to `ADVERSARIAL_ANALYSIS.md` in the project root.

---

## Pipeline 2: Kludge Hardener

### Flow

```
Working code
    │
    R (Task) — gets NO context (deliberate)
    Reverse-engineer the spec from code alone
    │
    inferred spec + assumptions
    │
    F (Task) — gets R's spec + code + developer context
    Construct chaos scenarios for every assumption
    │
    fault scenarios
    │
    P (Task) — gets code + F's fault scenarios
    Write minimal surgical patches (no rewrites)
    │
    patches
    │
    J (Task) — gets everything
    Evaluate each patch, produce implementation plan
    │
    approved patches + phased plan
```

### Key Design Principle

Agent R gets **NO context** — that's deliberate. The gap between what R thinks the code does and what you intended reveals documentation bugs and implicit assumptions you've internalized but never codified.

### Step-by-Step Execution

#### Step 1: Gather Code
Read all files in the target scope. Concatenate with clear file headers.

#### Step 2: Dispatch R (Reverse Engineer)

**R prompt template:**
```
You are Agent R — a Reverse Engineer.

You receive source code with NO external context. You have not been told what this
code is for, what system it belongs to, or what its requirements are.

Produce:
1. INFERRED PURPOSE — What is this code trying to accomplish?
2. CONTRACTS & INTERFACES — What does it expose? What does it expect from callers?
3. INVARIANTS — What must always be true for this code to work?
4. IMPLICIT ASSUMPTIONS — What does this code assume about its environment that is
   NOT explicitly validated? Rate each: SOLID / FRAGILE / BRITTLE
5. DEPENDENCY MAP — External systems/services. For each: validated? What if unavailable?
6. BRITTLENESS MAP — Rate each component:
   - SOLID: Handles its own errors, clear contracts
   - FRAGILE: Works but depends on implicit assumptions
   - BRITTLE: Will break under non-trivial perturbation
7. STATE ANALYSIS — All mutable state: who writes, who reads, what if stale/missing?

## CODE
[Paste code — NO context about what it does]
```

#### Step 3: Dispatch F (Fault Injector)

**F prompt template:**
```
You are Agent F — a chaos engineer and fault injection specialist.

You receive source code and Agent R's reverse-engineered spec.

Systematically enumerate failure scenarios across these categories:
- Network: Connection drops, timeouts, DNS, TLS
- Dependencies: Service unavailable, queue full, message too large
- Database: Pool exhaustion, lock contention, deadlocks, advisory lock orphans
- Concurrency: Race conditions, double-processing, lost updates, stale reads
- Resources: Memory pressure, disk full, file descriptors, CPU throttling
- Data: Malformed input, encoding, nulls, schema drift
- Time: Clock skew, timezone, DST, timeout races
- Infrastructure: Container restart mid-op, cold start, host recycling
- Auth: Token expiry mid-batch, credential rotation

For each scenario: FAULT, TRIGGER, BLAST RADIUS, CURRENT BEHAVIOR (read the code!),
SEVERITY (CRITICAL/HIGH/MEDIUM/LOW), LIKELIHOOD.

Prioritize by SEVERITY x LIKELIHOOD.

## SOURCE CODE
[Paste code]

## AGENT R's ANALYSIS
[Paste R output]

## DEVELOPER CONTEXT (if provided)
[Paste context and focus areas]
```

#### Step 4: Dispatch P (Patch Author)

**P prompt template:**
```
You are Agent P — a surgical patch author for production systems.

PRIME DIRECTIVE: Minimal targeted patches. Do NOT rewrite.

CONSTRAINTS (non-negotiable):
- NO rewrites. Patch, don't refactor.
- NO signature changes to public methods.
- NO "while we're here" improvements.
- Each patch targets EXACTLY ONE fault.
- Patches must NOT change happy-path behavior.

Preferred strategies (in order):
1. Guard clauses (early returns on bad state)
2. Try/except with specific exceptions
3. Retry with backoff (transient failures)
4. Circuit breakers (dependency failures)
5. Timeouts (operations that could hang)
6. Fallback values (non-critical data)
7. Idempotency guards (double-execute protection)
8. Resource cleanup (finally blocks, context managers)

For each patch: FAULT targeted, LOCATION (file + function), BEFORE snippet,
AFTER snippet, RATIONALE, HAPPY PATH IMPACT (must be NONE or NEGLIGIBLE), RISK.

Suggest grouping into: Quick Wins / Careful Changes / Architectural.
(This is a suggestion for J — J makes the final deployment phasing decision and may override
based on patch conflicts and dependency ordering.)

## SOURCE CODE
[Paste code]

## FAULT SCENARIOS
[Paste F output]
```

#### Step 5: Dispatch J (Judge)

**J prompt template:**
```
You are Agent J — the final judge of proposed patches.

For EACH patch evaluate:
1. CORRECTNESS: Does it actually fix the fault? Walk through the failure path.
2. SAFETY: Does it change happy-path behavior? Could it introduce new bugs?
3. SCOPE: Is it minimal? Could it be smaller?
4. CONFLICTS: Does it conflict with other patches?
5. VERDICT: APPROVE / APPROVE WITH MODIFICATIONS / REJECT

Then produce:
- IMPLEMENTATION PLAN (Phase 1: Quick Wins, Phase 2: Careful Changes, Phase 3: Architectural)
- RESIDUAL RISKS (faults with no approved patch)
- MONITORING RECOMMENDATIONS (what to watch after applying patches)
- KEY INSIGHT (single most important thing this review revealed)

## ORIGINAL CODE
[Paste code]

## FAULT SCENARIOS
[Paste F output]

## PROPOSED PATCHES
[Paste P output]
```

#### Step 6: Save Results
Write the final report to a markdown file. Include all agent outputs for traceability.

---

## Execution Notes

### Subagent Configuration
- Use `subagent_type: "general-purpose"` for all agents
- Alpha and Beta MUST be dispatched in a single message (parallel Task calls)
- All other agents are sequential (each depends on previous output)
- Tell agents which files to read — they have access to the filesystem

### Scoping
- For large subsystems (80+ files), have Claude read the key files and paste relevant
  portions into the prompts rather than asking agents to read everything
- For smaller targets (1-5 files), agents can read the files themselves
- The Kludge Hardener works best on focused targets (1-3 files)
- The Adversarial Review works best on subsystems (5-20 key files)

### Token Efficiency
- The Adversarial Review is heavier (~5 agent calls, parallel Alpha+Beta saves wall time)
- The Kludge Hardener is lighter (~4 sequential agent calls)
- For the Adversarial Review, Gamma is the most expensive call (receives both reviews)
- For the Kludge Hardener, J is most expensive (receives all previous outputs)

### When to Run
- **After completing a major feature**: Adversarial Review on the new subsystem
- **Before deploying to production**: Kludge Hardener on changed files
- **When debugging recurring issues**: Kludge Hardener focused on the problem area
- **During architecture review sprints**: Adversarial Review on each major subsystem

### Chaining Pipelines

The two pipelines complement each other. The natural chain:

```
Adversarial Review (broad)
    │
    identifies "concurrency issues in state_manager.py"
    │
    ▼
Kludge Hardener (focused)
    targets state_manager.py with F focused on concurrency faults
    developer context = the specific findings from the Adversarial Review
```

**Adversarial Review → Kludge Hardener**: Use the Adversarial Review's Top 5 Fixes as developer context for Agent F. Scope the Kludge Hardener to the specific files and fault categories identified. Example: if the review found "non-atomic task creation in `_individual_queue_tasks()`", run the Kludge Hardener on `core/machine.py` with F focused on atomicity and partial-failure scenarios.

**Kludge Hardener → Adversarial Review**: Less common, but useful when hardening patches reveal architectural issues that need broader assessment. If Agent J's residual risks suggest systemic design problems, run an Adversarial Review on the surrounding subsystem.
