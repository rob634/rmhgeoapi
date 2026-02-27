"""
Kludge Hardener Pipeline — Reference Implementation
=====================================================
Adversarial code review for existing systems that are "trucking along
but break sometimes." Four agents reverse-engineer, fault-inject,
patch, and judge — without rewriting your code.

NOTE: This script requires an Anthropic API key (not included with Max plan).
The PREFERRED execution path is via Claude Code subagents — see:
    docs_claude/AGENT_PLAYBOOKS.md

That playbook contains the same agent prompts and pipeline flow, designed
to be executed by Claude Code using the Task tool. No API key needed.

This .py file is kept as a reference implementation for the agent architecture
and system prompts. If you get an API key, it also works standalone:

    pip install anthropic rich
    export ANTHROPIC_API_KEY=sk-ant-...
    python adversarial.py --code myfile.py
    python adversarial.py --code src/ --glob "*.py" \\
        --context "Azure Functions ETL with Service Bus" \\
        --focus "concurrency,error-handling,retry"
"""

import argparse
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

# ─── Agent Definitions ──────────────────────────────────────────────

AGENTS = {
    "reverse":  {"symbol": "R", "name": "Reverse",  "role": "Reverse Engineer",  "color": "cyan"},
    "fault":    {"symbol": "F", "name": "Fault",    "role": "Fault Injector",    "color": "red"},
    "patch":    {"symbol": "P", "name": "Patch",    "role": "Patch Author",      "color": "green"},
    "judge":    {"symbol": "J", "name": "Judge",    "role": "Patch Judge",       "color": "yellow"},
}

REVERSE_SYSTEM = """You are Agent R — a reverse engineering specialist.

You receive source code WITH NO CONTEXT about what it's supposed to do.
Your job is to produce a detailed analysis:

1. **INFERRED SPEC**: What does this code actually do? Write the spec someone SHOULD
   have written before building this. Be precise about inputs, outputs, side effects.

2. **ASSUMED INVARIANTS**: What must be true for this code to work correctly?
   List every assumption — env vars exist, services are reachable, data is shaped
   a certain way, timing constraints, ordering dependencies.

3. **IMPLICIT CONTRACTS**: What contracts exist between functions/modules that
   aren't enforced in code? E.g., "function A must be called before function B"
   or "this dict must contain key X by the time it reaches line Y."

4. **BRITTLENESS MAP**: Rate each component/function on a brittleness scale:
   - 🟢 SOLID: Handles its own errors, clear contracts, no hidden state
   - 🟡 FRAGILE: Works but depends on implicit assumptions
   - 🔴 BRITTLE: Will break under non-trivial perturbation

5. **STATE ANALYSIS**: Map all mutable state — globals, class attributes, caches,
   database connections, file handles. For each: who writes it, who reads it,
   what happens if it's stale or missing?

Be thorough. Every gap between what the code assumes and what it enforces is a
potential failure mode."""

FAULT_SYSTEM = """You are Agent F — a chaos engineer and fault injection specialist.

You receive:
- Source code
- An inferred spec and brittleness analysis from Agent R

Your job: systematically enumerate failure scenarios. For EACH scenario:

1. **FAULT**: What goes wrong? (e.g., "Database connection drops mid-transaction")
2. **TRIGGER**: What real-world condition causes this? (e.g., "Azure PG maintenance window")
3. **BLAST RADIUS**: What breaks downstream? Does it cascade?
4. **CURRENT BEHAVIOR**: What does the code actually do when this happens RIGHT NOW?
   Read the code carefully — does it catch this? Silently swallow it? Crash?
5. **SEVERITY**: CRITICAL (data loss/corruption), HIGH (service outage), MEDIUM (degraded),
   LOW (cosmetic/logged)
6. **LIKELIHOOD**: How often would this realistically occur in production?

Categories to systematically explore:
- **Network**: Connection drops, timeouts, DNS failures, TLS cert expiry
- **Dependencies**: Service Bus unavailable, queue full, message too large
- **Database**: Connection pool exhaustion, lock contention, deadlocks, advisory lock orphans
- **Concurrency**: Race conditions, double-processing, lost updates, stale reads
- **Resources**: Memory pressure, disk full, file descriptor exhaustion, CPU throttling
- **Data**: Malformed input, encoding issues, null where unexpected, schema drift
- **Time**: Clock skew, timezone bugs, DST transitions, timeout races
- **Infrastructure**: Container restart mid-operation, cold start, host recycling
- **Auth**: Token expiry mid-batch, credential rotation, permission changes

For each category, generate at least one scenario IF the code interacts with that domain.
Skip categories that are genuinely not relevant.

Output as a structured list. Prioritize by SEVERITY × LIKELIHOOD.
Be specific to THIS code — no generic advice."""

PATCH_SYSTEM = """You are Agent P — a surgical patch author for production systems.

You receive:
- Source code (the working kludge)
- Fault scenarios from Agent F (what can break)

Your PRIME DIRECTIVE: **Minimal targeted patches. Do NOT rewrite.**

The code is in production and working. Your patches must:
1. Fix exactly ONE fault scenario each
2. Not change happy-path behavior
3. Be as small as possible — prefer adding a try/except over restructuring
4. Include the exact code location (function name + approximate line context)

For each fault scenario, produce a patch:

```
FAULT: [which scenario this addresses]
LOCATION: [function/method name and context]
BEFORE: [relevant code snippet as-is]
AFTER: [patched code snippet]
RATIONALE: [why this specific fix, not a bigger refactor]
RISK: [what could go wrong with this patch]
```

Patch strategies to prefer (in order):
1. **Guard clauses**: Early returns on bad state
2. **Try/except with specific exceptions**: Not bare except
3. **Retry with backoff**: For transient network/service failures
4. **Circuit breakers**: For dependency failures that won't self-heal
5. **Timeouts**: For operations that could hang
6. **Fallback values**: For non-critical data that can degrade gracefully
7. **Idempotency guards**: For operations that might double-execute
8. **Resource cleanup**: Finally blocks, context managers, __del__ safety

Strategies to AVOID:
- Full rewrites of working functions
- Changing function signatures (breaks callers)
- Adding new dependencies unless absolutely necessary
- "While we're here" improvements unrelated to fault scenarios
- Premature abstraction

If a fault scenario requires a larger architectural change to fix properly,
say so explicitly and describe the change, but still provide the minimal
patch as a stopgap with a clear TODO comment."""

JUDGE_SYSTEM = """You are Agent J — the final judge of proposed patches.

You receive:
- Original source code
- Fault scenarios
- Proposed patches from Agent P

For EACH patch, evaluate:

1. **CORRECTNESS**: Does it actually fix the fault scenario? Walk through the
   failure path with the patch applied.
2. **SAFETY**: Does it change happy-path behavior? Could it introduce new bugs?
   Does it handle the patched exception correctly or just swallow it?
3. **SCOPE**: Is the patch minimal? Could it be smaller?
4. **CONFLICTS**: Does it conflict with any other proposed patch?
5. **VERDICT**: APPROVE, APPROVE WITH MODIFICATIONS, or REJECT

For approved patches, output the final version with any modifications.
For rejected patches, explain exactly why and whether an alternative exists.

After evaluating all patches individually, produce:

## IMPLEMENTATION PLAN
An ordered list of patches to apply, grouped into:
- **Phase 1 — Quick Wins**: Low-risk patches that fix high-severity faults. Apply today.
- **Phase 2 — Careful Changes**: Medium-risk patches needing testing. Apply this sprint.
- **Phase 3 — Architectural**: Changes that need design review. Backlog with context.

## RESIDUAL RISKS
Fault scenarios that NO patch adequately addresses. These need architectural work.

## MONITORING RECOMMENDATIONS
For each approved patch, what should you monitor to verify it's working?
Specific log lines, metrics, or alerts to add."""


# ─── Pipeline ───────────────────────────────────────────────────────

class HardeningPipeline:
    def __init__(self, model: str = "claude-sonnet-4-5-20250514"):
        self.client = anthropic.Anthropic()
        self.model = model
        self.outputs: dict[str, str] = {}
        self.timings: dict[str, float] = {}

    def call_agent(self, system: str, user_msg: str, agent_key: str) -> str:
        a = AGENTS[agent_key]
        console.print()
        console.rule(f"[{a['color']}]{a['symbol']} {a['name']} — {a['role']}[/]")

        with console.status(f"[{a['color']}]{a['name']} analyzing...[/]", spinner="dots"):
            t0 = time.time()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            elapsed = time.time() - t0

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        self.outputs[agent_key] = text
        self.timings[agent_key] = elapsed

        preview = text[:600] + ("..." if len(text) > 600 else "")
        console.print(Panel(
            preview,
            title=f"[{a['color']}]{a['symbol']} {a['name']} — {a['role']} ✓[/]",
            subtitle=f"{len(text)} chars · {elapsed:.1f}s · {response.usage.input_tokens}↓ {response.usage.output_tokens}↑",
            border_style=a["color"],
            padding=(1, 2),
        ))
        return text

    def run(self, code: str, context: str = "", focus: str = "", output_dir: str | None = None):
        """Execute the full hardening pipeline."""

        # Show code stats
        lines = code.count("\n") + 1
        chars = len(code)
        console.print()
        console.print(Panel(
            f"[dim]{lines} lines · {chars:,} chars[/]\n\n"
            + (code[:800] + "\n..." if len(code) > 800 else code),
            title="[bold]Code Under Review[/]",
            border_style="white",
            padding=(1, 2),
        ))

        if context:
            console.print(f"[dim]Context: {context}[/]")
        if focus:
            console.print(f"[dim]Focus areas: {focus}[/]")

        t_start = time.time()

        # Build context suffix for agents that get it
        context_block = ""
        if context:
            context_block += f"\n\nADDITIONAL CONTEXT (from the developer):\n{context}"
        if focus:
            context_block += f"\n\nFOCUS AREAS (prioritize these):\n{focus}"

        # ── Phase 1: Reverse engineer (no context — that's the point) ──
        reverse_out = self.call_agent(
            REVERSE_SYSTEM,
            f"Analyze this code:\n\n```\n{code}\n```",
            "reverse",
        )

        # ── Phase 2: Fault injection ────────────────────────────────
        fault_out = self.call_agent(
            FAULT_SYSTEM,
            (
                f"SOURCE CODE:\n```\n{code}\n```\n\n"
                f"{'━' * 60}\n\n"
                f"REVERSE ENGINEERING ANALYSIS:\n{reverse_out}"
                f"{context_block}"
            ),
            "fault",
        )

        # ── Phase 3: Patch authoring ────────────────────────────────
        patch_out = self.call_agent(
            PATCH_SYSTEM,
            (
                f"SOURCE CODE:\n```\n{code}\n```\n\n"
                f"{'━' * 60}\n\n"
                f"FAULT SCENARIOS:\n{fault_out}"
            ),
            "patch",
        )

        # ── Phase 4: Judge ──────────────────────────────────────────
        judge_out = self.call_agent(
            JUDGE_SYSTEM,
            (
                f"ORIGINAL SOURCE CODE:\n```\n{code}\n```\n\n"
                f"{'━' * 60}\n\n"
                f"FAULT SCENARIOS:\n{fault_out}\n\n"
                f"{'━' * 60}\n\n"
                f"PROPOSED PATCHES:\n{patch_out}"
            ),
            "judge",
        )

        total = time.time() - t_start

        # ── Summary ─────────────────────────────────────────────────
        console.print()
        console.rule("[bold]Hardening Complete[/]")
        console.print()

        table = Table(show_header=True, header_style="bold", border_style="dim")
        table.add_column("Agent", style="bold")
        table.add_column("Time", justify="right")
        table.add_column("Output", justify="right")

        for key in ["reverse", "fault", "patch", "judge"]:
            a = AGENTS[key]
            t = self.timings.get(key, 0)
            c = len(self.outputs.get(key, ""))
            table.add_row(
                f"[{a['color']}]{a['symbol']} {a['name']}[/]",
                f"{t:.1f}s",
                f"{c:,} chars",
            )

        console.print(table)
        console.print(f"\n  [bold]Total wall time: {total:.1f}s[/]")

        # ── Save outputs ────────────────────────────────────────────
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            for key in ["reverse", "fault", "patch", "judge"]:
                a = AGENTS[key]
                (out / f"{key}_output.md").write_text(
                    f"# {a['symbol']} {a['name']} — {a['role']}\n\n{self.outputs[key]}\n"
                )

            # Composite report
            report_parts = [
                "# Kludge Hardener Report",
                f"\nAnalyzed {lines} lines of code in {total:.1f}s\n",
                "---\n",
                f"## R — Reverse Engineering Analysis\n\n{reverse_out}\n",
                "---\n",
                f"## F — Fault Scenarios\n\n{fault_out}\n",
                "---\n",
                f"## P — Proposed Patches\n\n{patch_out}\n",
                "---\n",
                f"## J — Patch Verdicts & Implementation Plan\n\n{judge_out}\n",
            ]
            (out / "HARDENING_REPORT.md").write_text("\n".join(report_parts))

            console.print(f"\n  [dim]Outputs saved to {out}/[/]")
            console.print(f"  [dim]  HARDENING_REPORT.md ← full report[/]")
            console.print(f"  [dim]  {{reverse,fault,patch,judge}}_output.md ← agent traces[/]")

        console.print()


# ─── File Loading ───────────────────────────────────────────────────

def load_code(path_str: str, glob_pattern: str | None = None) -> str:
    """Load code from a file or directory."""
    path = Path(path_str)

    if path.is_file():
        return f"# File: {path.name}\n\n{path.read_text()}"

    if path.is_dir():
        pattern = glob_pattern or "*.py"
        files = sorted(path.rglob(pattern))

        if not files:
            console.print(f"[red]No files matching '{pattern}' in {path}[/]")
            sys.exit(1)

        parts = []
        total_lines = 0
        for f in files:
            content = f.read_text()
            total_lines += content.count("\n") + 1
            rel = f.relative_to(path)
            parts.append(f"# ━━━ File: {rel} ━━━\n\n{content}")

        console.print(f"[dim]Loaded {len(files)} files ({total_lines} lines) from {path}/[/]")
        return "\n\n".join(parts)

    console.print(f"[red]{path} not found[/]")
    sys.exit(1)


# ─── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Kludge Hardener — adversarial code review for production systems",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file
  python kludge_hardener.py --code orchestrator.py

  # Directory of Python files
  python kludge_hardener.py --code src/etl/ --glob "*.py"

  # With context and focus areas
  python kludge_hardener.py --code orchestrator.py \\
      --context "Azure Functions ETL with Service Bus orchestration and advisory locks" \\
      --focus "concurrency,lock lifecycle,retry behavior,poison messages"

  # Pipe from stdin
  cat myfile.py | python kludge_hardener.py --code -

  # Custom output dir
  python kludge_hardener.py --code src/ -o ./hardening_results
        """,
    )
    parser.add_argument(
        "--code", required=True,
        help="Path to file or directory to analyze, or '-' for stdin",
    )
    parser.add_argument(
        "--glob", type=str, default=None,
        help="Glob pattern when --code is a directory (default: *.py)",
    )
    parser.add_argument(
        "--context", type=str, default="",
        help="Optional context about what the code does (given to Fault Injector only)",
    )
    parser.add_argument(
        "--focus", type=str, default="",
        help="Comma-separated focus areas to prioritize (e.g., concurrency,retry,auth)",
    )
    parser.add_argument(
        "--output", "-o", type=str, default="./hardening_output",
        help="Directory to save outputs (default: ./hardening_output)",
    )
    parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-5-20250514",
        help="Anthropic model to use",
    )

    args = parser.parse_args()

    # Load code
    if args.code == "-":
        code = sys.stdin.read()
        if not code.strip():
            console.print("[red]No code provided on stdin[/]")
            sys.exit(1)
    else:
        code = load_code(args.code, args.glob)

    # Run
    pipeline = HardeningPipeline(model=args.model)
    pipeline.run(
        code=code,
        context=args.context,
        focus=args.focus,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()