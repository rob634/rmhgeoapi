# Pipeline Instrumentation Guide

## Overview

This document describes how to instrument the adversarial agent pipelines (Greenfield, Adversarial Review, Reflexion, etc.) to capture token usage and output quality metrics per agent per run. The goal is to answer two questions:

1. **How does token use scale** with task complexity (small feature vs. full project review)?
2. **How well does the instruction set scale** — does output quality degrade as scope increases?

---

## Part 1: Token Usage Tracking

### The Problem

Claude Code tracks token usage per session, but a single pipeline run dispatches 5–7 agents sequentially and in parallel. You need per-agent granularity to understand where tokens are actually going.

### Approach: Wrapper Script + Structured Log

Add a `run_agent.sh` wrapper that captures Claude Code's token output for each agent invocation and appends it to a structured JSONL log file.

#### `run_agent.sh`

```bash
#!/bin/bash
# Usage: ./run_agent.sh <pipeline> <run_id> <agent> <prompt_file> <output_file>
#
# Example:
#   ./run_agent.sh greenfield run_001 agent_a prompts/agent_a.md outputs/agent_a.md

PIPELINE="$1"
RUN_ID="$2"
AGENT="$3"
PROMPT_FILE="$4"
OUTPUT_FILE="$5"
LOG_FILE="metrics/token_log.jsonl"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

mkdir -p metrics outputs

# Run Claude Code and capture both output and token usage
# The --output-format json flag gives structured output including token counts
START_TIME=$(date +%s%N)

claude -p "$(cat "$PROMPT_FILE")" --output-format json > "/tmp/claude_raw_${AGENT}.json" 2>&1

END_TIME=$(date +%s%N)
ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))

# Extract token usage from Claude Code's JSON output
# Claude Code reports: input_tokens, output_tokens, cache_read, cache_write
INPUT_TOKENS=$(jq -r '.usage.input_tokens // .input_tokens // "unknown"' "/tmp/claude_raw_${AGENT}.json")
OUTPUT_TOKENS=$(jq -r '.usage.output_tokens // .output_tokens // "unknown"' "/tmp/claude_raw_${AGENT}.json")
CACHE_READ=$(jq -r '.usage.cache_read_input_tokens // .cache_read // 0' "/tmp/claude_raw_${AGENT}.json")
CACHE_WRITE=$(jq -r '.usage.cache_creation_input_tokens // .cache_write // 0' "/tmp/claude_raw_${AGENT}.json")

# Extract the actual response text and save to output file
jq -r '.result // .content // .text // .' "/tmp/claude_raw_${AGENT}.json" > "$OUTPUT_FILE"

# Calculate output file size (proxy for response complexity)
OUTPUT_BYTES=$(wc -c < "$OUTPUT_FILE")
OUTPUT_LINES=$(wc -l < "$OUTPUT_FILE")

# Append structured log entry
cat >> "$LOG_FILE" << EOF
{"timestamp":"${TIMESTAMP}","pipeline":"${PIPELINE}","run_id":"${RUN_ID}","agent":"${AGENT}","input_tokens":${INPUT_TOKENS},"output_tokens":${OUTPUT_TOKENS},"cache_read":${CACHE_READ},"cache_write":${CACHE_WRITE},"total_tokens":$((INPUT_TOKENS + OUTPUT_TOKENS)),"elapsed_ms":${ELAPSED_MS},"output_bytes":${OUTPUT_BYTES},"output_lines":${OUTPUT_LINES}}
EOF

echo "  ${AGENT}: ${INPUT_TOKENS} in / ${OUTPUT_TOKENS} out / ${ELAPSED_MS}ms"
```

#### What This Captures Per Agent Call

| Field | What It Tells You |
|-------|------------------|
| `input_tokens` | Size of the prompt (spec + agent instructions + any context) |
| `output_tokens` | How much the agent generated |
| `cache_read` | Prompt caching hits (shared prefix across A/C/O) |
| `cache_write` | New cache entries created |
| `total_tokens` | Billing-relevant total |
| `elapsed_ms` | Wall clock time |
| `output_bytes` / `output_lines` | Output complexity proxy |

### Per-Run Summary

Add a summary step at the end of each pipeline run:

```bash
#!/bin/bash
# summarize_run.sh <run_id>
RUN_ID="$1"
LOG_FILE="metrics/token_log.jsonl"

echo "=== Run Summary: ${RUN_ID} ==="
echo ""

# Per-agent breakdown
echo "Agent Breakdown:"
grep "\"run_id\":\"${RUN_ID}\"" "$LOG_FILE" | \
  jq -r '[.agent, .input_tokens, .output_tokens, .total_tokens, .elapsed_ms] | @tsv' | \
  column -t -N "AGENT,INPUT,OUTPUT,TOTAL,MS"

echo ""

# Run totals
echo "Run Totals:"
grep "\"run_id\":\"${RUN_ID}\"" "$LOG_FILE" | \
  jq -s '{
    total_input: (map(.input_tokens) | add),
    total_output: (map(.output_tokens) | add),
    total_tokens: (map(.total_tokens) | add),
    total_cache_read: (map(.cache_read) | add),
    total_elapsed_ms: (map(.elapsed_ms) | add),
    agent_count: length
  }'
```

### Cross-Run Comparison

After multiple runs, you can compare scaling:

```bash
# Compare token usage across runs
cat metrics/token_log.jsonl | \
  jq -s 'group_by(.run_id) | map({
    run_id: .[0].run_id,
    pipeline: .[0].pipeline,
    total_tokens: (map(.total_tokens) | add),
    agent_count: length,
    heaviest_agent: (sort_by(.total_tokens) | last | {agent: .agent, tokens: .total_tokens})
  })'
```

---

## Part 2: Output Quality Metrics

### The Problem

"Was the output good?" is subjective unless you define what good means. The pipeline structure gives you two built-in quality signals:

1. **V's spec diff** (Greenfield) — gaps between what S specified and what V inferred from the code
2. **Section completeness** — did each agent produce all required sections?

### Approach: Structured Quality Scores Per Agent

Add a scoring step after each pipeline run that extracts quality signals from the agent outputs themselves. This can be done by Claude Code as a final analysis step.

#### Quality Rubric (append to pipeline markdown)

Add this section to the end of each pipeline's markdown file:

```markdown
## Step 9: Quality Metrics

After the pipeline completes, produce a quality report as a JSON object.
Save to `metrics/quality_{run_id}.json`.

### Agent Section Completeness

For each agent, check whether all required sections are present and non-trivial
(more than 3 sentences). Score each section as:
- 2 = present and substantive
- 1 = present but thin (under 3 sentences or generic)
- 0 = missing

### Spec Fidelity (from V's analysis)

From V's output in Step 6 and the Spec Diff in Step 7:
- `matches_count`: Number of MATCHES (spec requirements V correctly inferred)
- `gaps_count`: Number of GAPS (spec requirements not reflected in code)
- `extras_count`: Number of EXTRAS (code behavior not in spec)
- `fidelity_score`: matches / (matches + gaps)  — ratio of spec coverage
- `scope_creep_score`: extras / (matches + extras) — ratio of unspecified behavior

### Conflict Resolution Quality (from M's output)

- `conflicts_found`: Number of explicit conflicts M identified between A, C, O
- `conflicts_resolved`: Number with clear resolution (not "TBD" or "deferred")
- `design_tensions`: Number of Tier 2 tensions noted
- `concerns_dropped`: Number of C's concerns not addressed in M's resolved spec
  (should be 0; if >0, M failed its job)

### Produce This JSON

{
  "run_id": "...",
  "pipeline": "greenfield",
  "timestamp": "...",
  "task_description": "one-line summary of what was built",
  "task_complexity": "small | medium | large",

  "section_completeness": {
    "S": {"purpose": 2, "boundaries": 2, "contracts": 2, ...},
    "A": {"component_design": 2, "interface_contracts": 1, ...},
    "C": {"ambiguities": 2, "missing_edge_cases": 2, ...},
    "O": {"infrastructure_fit": 2, "failure_modes": 2, ...},
    "M": {"conflicts_found": 2, "resolved_spec": 2, ...},
    "V": {"inferred_purpose": 2, "concerns": 2, ...}
  },
  "section_completeness_score": 0.0-1.0,

  "spec_fidelity": {
    "matches": 12,
    "gaps": 2,
    "extras": 1,
    "fidelity_score": 0.857,
    "scope_creep_score": 0.077
  },

  "conflict_resolution": {
    "conflicts_found": 8,
    "conflicts_resolved": 8,
    "design_tensions": 2,
    "concerns_dropped": 0
  },

  "v_verdict": "PRODUCTION READY | NEEDS MINOR WORK | NEEDS SIGNIFICANT WORK",

  "token_summary": {
    "total_tokens": 0,
    "by_agent": {"S": 0, "A": 0, "C": 0, "O": 0, "M": 0, "B": 0, "V": 0}
  }
}
```

### Complexity Classification

To make cross-run comparisons meaningful, classify each run's complexity:

| Complexity | Indicators |
|-----------|-----------|
| **small** | Single endpoint, 1-2 files, <300 lines of output code, spec fits in one screen |
| **medium** | 2-4 endpoints or components, 3-5 files, 300-1000 lines, multiple integration points |
| **large** | Full subsystem, 5+ files, 1000+ lines, multiple downstream services, auth/security concerns |

This is a judgment call — tag it when you create the run, not after. Your "build this 500-line feature" is medium. Your "review this entire fucking project" is large.

---

## Part 3: Aggregation and Analysis

### After 5+ Runs: Scaling Analysis

```bash
# Token scaling by complexity
cat metrics/quality_*.json | \
  jq -s 'group_by(.task_complexity) | map({
    complexity: .[0].task_complexity,
    runs: length,
    avg_tokens: (map(.token_summary.total_tokens) | add / length),
    avg_fidelity: (map(.spec_fidelity.fidelity_score) | add / length),
    avg_completeness: (map(.section_completeness_score) | add / length)
  })'
```

### What You're Looking For

**Token scaling (Question 1):**
- Does total token usage scale linearly with complexity, or worse?
- Which agent is the token hog? (Probably B, but M might surprise you)
- Do A/C/O stay proportional, or does one blow up on large tasks?
- How much does prompt caching save when A/C/O share the same spec prefix?

**Quality scaling (Question 2):**
- Does `fidelity_score` drop as complexity increases? If so, the pipeline instructions don't scale.
- Does `scope_creep_score` increase with complexity? B is adding stuff the spec didn't ask for.
- Does `concerns_dropped` increase? M is overwhelmed and silently dropping C's findings.
- Does V's verdict correlate with complexity? If large tasks always "NEED SIGNIFICANT WORK," the pipeline needs a decomposition step.

### Red Flags to Watch For

| Signal | What It Means |
|--------|--------------|
| `fidelity_score` < 0.7 | More than 30% of the spec isn't in the code. Pipeline is losing information. |
| `scope_creep_score` > 0.2 | B is freelancing. M's resolved spec may not be specific enough. |
| `concerns_dropped` > 0 | M is failing. C's work is being wasted. |
| Agent O token count >> A or C | O is generating generic cloud advice instead of specific operational assessment. Tighten the infra profile. |
| V verdict doesn't match fidelity score | V is being too generous or too harsh. Calibrate V's prompt. |
| M token count > B token count | M is over-elaborating. The resolved spec is too verbose for B to follow. |

---

## Part 4: Pipeline Instructions Integration

### Where to Add These Instructions

Add the following to the END of each pipeline markdown file, after the last step:

```markdown
## Instrumentation

Every pipeline run MUST produce two artifacts in the `metrics/` directory:

1. `metrics/token_log.jsonl` — Append one line per agent invocation (see instrumentation guide).
2. `metrics/quality_{run_id}.json` — Quality assessment produced as the final step.

### Run ID Convention

Run IDs follow the format: `{pipeline}_{YYYYMMDD}_{seq}`
Example: `greenfield_20260228_001`

### How to Tag Complexity

Before starting Step 1, classify the task:
- **small**: Single component, <300 lines expected, 1-2 integration points
- **medium**: Multiple components, 300-1000 lines, 3+ integration points
- **large**: Full subsystem, 1000+ lines, auth/security/multi-service

Record this in the quality JSON. Do not change it after seeing the results.
```

### For Claude Code Specifically

When running these pipelines in Claude Code, the key integration point is capturing
token usage from each `claude` CLI invocation. Claude Code's `--output-format json`
flag provides structured output including token counts. The wrapper script above
handles this extraction.

If running agents as Task subagents within a single Claude Code session,
the session-level token tracking captures totals but not per-agent breakdown.
The wrapper script approach gives you the granularity you need.