# Agent Review System

Multi-agent adversarial pipelines for code review, design, hardening, and live API testing.

## Directory Structure

```
docs/agent_review/
├── README.md              This file
├── AGENT_RUNS.md          Run log — every pipeline execution with parameters, results, and token usage
├── agents/                Pipeline definitions — agent roles, flow, and instructions
│   ├── COMPETE_AGENT.md       Adversarial review (Omega → Alpha + Beta → Gamma → Delta)
│   ├── GREENFIELD_AGENT.md    Design-then-build (S → A+C+O → M → B → V)
│   ├── REFLEXION_AGENT.md     Kludge hardening (R → F → P → J)
│   ├── SIEGE_AGENT.md         Sequential smoke test (Sentinel → Cartographer → Lancer → Auditor → Scribe)
│   ├── WAR_AGENT.md           Red vs Blue state divergence (Strategist → Blue + Red → Oracle → Coroner)
│   ├── TOURNAMENT_AGENT.md    Full-spectrum adversarial (General → Pathfinder + Saboteur → Inspector + Provocateur → Tribunal)
│   └── AGENT_METRICS.md       Instrumentation guide for token/quality tracking
└── agent_docs/            Run outputs — full reports from each pipeline execution
    ├── PENDING_ITEMS.md               Consolidated pending items across all runs
    ├── REVIEW_SUMMARY.md              Master summary of all COMPETE reviews (Runs 1-6)
    ├── UNPUBLISH_SUBSYSTEM_REVIEW.md  COMPETE: Unpublish subsystem (Run 9)
    ├── GREENSIGHT_PIPELINE.md         GREENFIELD: VirtualiZarr pipeline (Run 8)
    ├── GREENFIELD_ZARR_UNPUBLISH.md   GREENFIELD: Zarr unpublish (Run 10)
    └── MEDIATOR_RESOLUTION.md         GREENFIELD: Approval conflict guard — M agent output (Run 7)
```

## Pipelines

### COMPETE (Adversarial Review)

Reviews existing code for architecture and correctness problems using information asymmetry between agents.

| Agent | Role |
|-------|------|
| Omega | Splits review into two asymmetric scopes |
| Alpha | Architecture and design review |
| Beta  | Correctness and reliability review (parallel with Alpha) |
| Gamma | Finds contradictions and blind spots between Alpha and Beta |
| Delta | Produces final prioritized, actionable report |

**Best for**: 5-20 file subsystems. Post-feature or architecture review sprints.

### GREENFIELD (Design-then-Build)

Designs and builds new code from intent. Stress-tests the design adversarially before any code is written.

| Agent | Role |
|-------|------|
| S | Formalizes intent into a spec (inline, no subagent) |
| A | Designs the system optimistically (parallel with C and O) |
| C | Finds what the spec does not cover (parallel with A and O) |
| O | Assesses operational and infrastructure reality (parallel with A and C) |
| M | Resolves conflicts between A, C, and O |
| B | Writes the code from M's resolved spec |
| V | Reverse-engineers the code blind (no spec) and compares to S's original |

**Best for**: New subsystems and features. When design must survive contact with reality before committing to code.

### REFLEXION (Kludge Hardening)

Hardens working-but-fragile code with minimal, surgical patches that preserve happy-path behavior.

| Agent | Role |
|-------|------|
| R | Reverse-engineers what the code does (gets NO documentation) |
| F | Finds every way the code can fail |
| P | Writes minimal patches for each fault |
| J | Judges each patch and plans deployment |

**Best for**: 1-5 files. Pre-deployment hardening or debugging recurring failures.

---

### Live API Testing Pipelines

The following three pipelines test the **running deployed system** with real HTTP requests, unlike the code-review pipelines above.

### SIEGE (Sequential Smoke Test)

Fast linear verification of core API workflows. No information asymmetry — pure speed.

| Agent | Role |
|-------|------|
| Sentinel | Defines campaign (test data, endpoints) |
| Cartographer | Probes every endpoint, maps API surface |
| Lancer | Executes canonical lifecycle sequences |
| Auditor | Queries DB/STAC, compares actual vs expected |
| Scribe | Synthesizes final report |

**Best for**: Post-deployment smoke test. "Did that deploy break anything?"

### WARGAME (Red vs Blue State Divergence)

Red attacks while Blue establishes ground truth on the same dataset namespace. Oracle catches state divergences.

| Agent | Role |
|-------|------|
| Strategist | Defines campaign, splits into Red + Blue briefs |
| Blue | Executes golden-path lifecycles (parallel with Red) |
| Red | Executes adversarial attacks on same namespace (parallel with Blue) |
| Oracle | Compares Blue's expected state vs actual, finds cross-contamination |
| Coroner | Root-cause analysis, reproduction scripts |

**Best for**: Pre-release state integrity. Chaining from COMPETE findings.

### TOURNAMENT (Full-Spectrum Adversarial)

Maximum-coverage adversarial testing: 4 specialists in 2 phases + synthesis Tribunal.

| Agent | Role |
|-------|------|
| General | Defines campaign, writes 4 specialist briefs |
| Pathfinder | Golden-path executor (Phase 1, parallel with Saboteur) |
| Saboteur | Adversarial attacker on same namespace (Phase 1, parallel with Pathfinder) |
| Inspector | State auditor — gets Pathfinder's checkpoints but NOT Saboteur's log (Phase 2) |
| Provocateur | Input validation tester — gets endpoint list only (Phase 2, parallel with Inspector) |
| Tribunal | Synthesizes all findings, correlates Inspector divergences with Saboteur attacks |

**Best for**: Full adversarial regression before QA handoff.

### Pipeline Selection Guide

| Scenario | Pipeline | Cost |
|----------|----------|------|
| Post-deployment smoke test | SIEGE | ~200K tokens |
| Pre-release state check | WARGAME | ~350K tokens |
| Full adversarial regression | TOURNAMENT | ~500K tokens |
| After COMPETE found bugs | WARGAME | Target Red at flagged subsystem |
| Before QA handoff | TOURNAMENT | Maximum coverage |

**Chaining**: SIEGE (cheap) → WARGAME (focused) → TOURNAMENT (thorough).

## How to Read AGENT_RUNS.md

Each run entry contains:
- **Run number and date**
- **Pipeline type** (COMPETE, GREENFIELD, REFLEXION, SIEGE, WARGAME, or TOURNAMENT)
- **Scope** — what subsystem or feature was reviewed/built
- **Parameters** — files reviewed, scope splits, design constraints
- **Result** — verdict, fix count, severity breakdown
- **Token usage** — per-agent breakdown and total
- **Commit** — resulting code commit (if applicable)
