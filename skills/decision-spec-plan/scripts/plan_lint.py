#!/usr/bin/env python3
"""Structural lint for plan documents.

Checks what makes a plan executable, so a truncated or malformed one fails:
  - at least one task, counting BOTH `## Task` and `### Task` headings (plans use both depths; a
    grep for one depth reports a healthy plan as empty)
  - a column-0 `- Produces` line per task (one shortfall allowed: a final gate task may export
    nothing) and `- Consumes` lines, the machine-readable form a registry extractor needs
  - balanced code fences
  - checkbox steps (`- [ ]` or ticked `- [x]` — an executed plan is still a plan)
  - the required header fields
  - a gate table, `| Gate | Command | Minutes | Runs |`: each gate's measured minutes and where it
    runs — `group` (the task group runs it), `lead` (the lead's background job through gate.py; the
    group reads its log) or `CI` (the project's pipeline; the group reads its run's log). A gate
    over --group-minutes (default 30) never runs in a group: one local three-database gate cost
    12.12M and 553 agent-minutes and never completed

Index files (`00-*.md`, `p<N>-00-*.md`) are skipped: an index is not a plan.

Usage:
    plan_lint.py <plans-dir> [--require '**Goal:**' --require '**Spec:**' ...] [--glob 'p4-*.md']
        [--group-minutes 30]

Exit 0 when every plan is ok, 1 when any has problems, 2 when no plan matched.
"""

import argparse
import pathlib
import re
import sys

DEFAULT_REQUIRED = ["**Goal:**", "**Spec:**", "**Depends on:**"]
RUNS = ("group", "lead", "ci")
GROUP_MINUTES = 30


def cells(line):
    return [c.strip().strip("`*").strip() for c in line.strip().strip("|").split("|")]


def gates(text):
    """[(gate, minutes or None, runs)] of the plan's gate table, or None without one."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        head = [c.lower() for c in cells(line)]
        if not (
            line.lstrip().startswith("|") and {"gate", "minutes", "runs"} <= set(head)
        ):
            continue
        g, m, r = (head.index(k) for k in ("gate", "minutes", "runs"))
        out = []
        for row in lines[i + 1 :]:
            if not row.lstrip().startswith("|"):
                break
            c = cells(row) + [""] * len(head)
            if not "".join(c).strip("-: "):
                continue  # the separator row
            n = re.fullmatch(r"~?(\d+(?:\.\d+)?)\s*(?:min\w*)?", c[m])
            out.append((c[g], float(n[1]) if n else None, c[r].lower()))
        return out
    return None


def gate_problems(text, group_minutes):
    found = gates(text)
    if found is None:
        return ["no gate table (| Gate | Command | Minutes | Runs |)"]
    if not found:
        return ["the gate table lists no gate"]
    problems = []
    for gate, minutes, runs in found:
        if minutes is None:
            problems.append(f"gate '{gate}' has no minutes")
        if runs not in RUNS:
            problems.append(f"gate '{gate}' runs '{runs}', not group, lead or CI")
        elif runs == "group" and minutes and minutes > group_minutes:
            problems.append(
                f"gate '{gate}' takes {minutes:g} min in a group (over {group_minutes:g}): "
                "the lead's background job or CI runs it, and the group reads its log"
            )
    return problems


def lint(text, required, group_minutes=GROUP_MINUTES):
    tasks = len(re.findall(r"^#{2,3} Task ", text, re.MULTILINE))
    produces = len(re.findall(r"^- Produces\b", text, re.MULTILINE))
    consumes = len(re.findall(r"^- Consumes", text, re.MULTILINE))
    steps = len(re.findall(r"^- \[[ xX]\]", text, re.MULTILINE))
    # Indented too: a fence under a `- [ ]` step is one, and a plan cut off inside it is broken.
    fences = len(re.findall(r"^[ \t]*```", text, re.MULTILINE))
    problems = []
    if tasks == 0:
        problems.append("no tasks")
    if fences % 2:
        problems.append(f"unbalanced fences ({fences})")
    if steps == 0:
        problems.append("no checkbox steps")
    if produces == 0:
        problems.append("no column-0 '- Produces' line")
    if tasks and produces and produces < tasks - 1:
        problems.append(f"{tasks} tasks but only {produces} Produces lines")
    for field in required:
        if field not in text:
            problems.append(f"missing {field}")
    problems += gate_problems(text, group_minutes)
    return tasks, produces, consumes, steps, problems


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("plans_dir")
    ap.add_argument("--glob", default="*.md")
    ap.add_argument(
        "--require", action="append", help="header field that must appear (repeatable)"
    )
    ap.add_argument(
        "--group-minutes",
        type=float,
        default=GROUP_MINUTES,
        help="the longest gate a task group runs itself (default 30; the route's group ETA "
        "once one has finished)",
    )
    args = ap.parse_args()
    required = args.require or DEFAULT_REQUIRED

    files = [
        f
        for f in sorted(pathlib.Path(args.plans_dir).glob(args.glob))
        if not re.match(r"(p\d+-)?00-", f.name)
    ]
    if not files:
        print(f"no plans matched {args.glob} in {args.plans_dir}")
        return 2
    print(f"{'plan':<44} {'tasks':>5} {'prod':>5} {'cons':>5} {'steps':>6}  problems")
    print("-" * 96)
    bad = 0
    for f in files:
        tasks, produces, consumes, steps, problems = lint(
            f.read_text(errors="replace"), required, args.group_minutes
        )
        bad += bool(problems)
        print(
            f"{f.name:<44} {tasks:>5} {produces:>5} {consumes:>5} {steps:>6}  "
            f"{'; '.join(problems) if problems else 'ok'}"
        )
    print(f"\n{len(files)} plans, {bad} with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
