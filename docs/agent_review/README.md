# Agent Review System

Multi-agent adversarial pipelines for code review, design, and hardening.

## Directory Structure

```
docs/agent_review/
├── README.md              This file
├── AGENT_RUNS.md          Run log — every pipeline execution with parameters, results, and token usage
├── agents/                Pipeline definitions — agent roles, flow, and instructions
│   ├── COMPETE_AGENT.md       Adversarial review (Omega → Alpha + Beta → Gamma → Delta)
│   ├── GREENFIELD_AGENT.md    Design-then-build (S → A+C+O → M → B → V)
│   ├── REFLEXION_AGENT.md     Kludge hardening (R → F → P → J)
│   └── AGENT_METRICS.md       Instrumentation guide for token/quality tracking
└── agent_docs/            Run outputs — full reports from each pipeline execution
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

## How to Read AGENT_RUNS.md

Each run entry contains:
- **Run number and date**
- **Pipeline type** (COMPETE, GREENFIELD, or REFLEXION)
- **Scope** — what subsystem or feature was reviewed/built
- **Parameters** — files reviewed, scope splits, design constraints
- **Result** — verdict, fix count, severity breakdown
- **Token usage** — per-agent breakdown and total
- **Commit** — resulting code commit (if applicable)
