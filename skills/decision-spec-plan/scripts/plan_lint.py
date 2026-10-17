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

Index files (`00-*.md`, `p<N>-00-*.md`) are skipped: an index is not a plan.

Usage:
    plan_lint.py <plans-dir> [--require '**Goal:**' --require '**Spec:**' ...] [--glob 'p4-*.md']

Exit 0 when every plan is ok, 1 when any has problems, 2 when no plan matched.
"""

import argparse
import pathlib
import re
import sys

DEFAULT_REQUIRED = ["**Goal:**", "**Spec:**", "**Depends on:**"]


def lint(text, required):
    tasks = len(re.findall(r"^#{2,3} Task ", text, re.MULTILINE))
    produces = len(re.findall(r"^- Produces\b", text, re.MULTILINE))
    consumes = len(re.findall(r"^- Consumes", text, re.MULTILINE))
    steps = len(re.findall(r"^- \[[ xX]\]", text, re.MULTILINE))
    fences = text.count("\n```")
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
    return tasks, produces, consumes, steps, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plans_dir")
    ap.add_argument("--glob", default="*.md")
    ap.add_argument(
        "--require", action="append", help="header field that must appear (repeatable)"
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
            f.read_text(errors="replace"), required
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
