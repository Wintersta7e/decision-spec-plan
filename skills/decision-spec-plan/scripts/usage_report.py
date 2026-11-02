#!/usr/bin/env python3
"""Cost of a decision-spec-plan run, read from Claude Code's session transcripts.

Prints the lead's and every subagent's cost with turns and mean/max context per turn, so a gate can
report what the round cost and which agent ran long, and each one's model and effort (every effort
its requests ran at, `high/xhigh` for a change mid-run), so a role's tier can be judged afterwards. Units are Opus 5.5 input tokens — 1M units is
about $4 at API prices (read 2026-10-17): 5-minute cache write x1.25, 1-hour cache write x2, output
x5, cache read x0.05; Sonnet 5.5 costs x0.5 of that with the same cache-read share, Haiku 5.5 x0.025
(x0.125 for a prompt over 100k tokens) with cache reads at x0.1 of its input. Before 2026-10-17
the units read cache at x0.1 and Sonnet at x0.6 (costs.md has the conversion). Output is a lower
bound: transcripts store thinking redacted and streamed snapshots undercount it.

Usage:
    usage_report.py [session-id] [--project-dir DIR] [--since ISO-TIMESTAMP]
        [--until ISO-TIMESTAMP] [--top N] [--groups]

Without a session id it reports the running session ($CLAUDE_CODE_SESSION_ID) of the project whose
directory is the current working directory, else that project's newest session. `--project-dir`
is the transcript dir (~/.claude/projects/<slug>) or the project's own directory. `--since` and `--until` count only records in
that span (e.g. from the skill's start). Sessions a hook or plugin started through the Agent SDK in
the project or one of its worktrees (entrypoint `sdk-*`, e.g. a security review of every commit) are
counted too, over the same span — up to the last record of the lead or its agents without
`--until`: 53 and 87 of them cost two runs 3.0M each in a day, uncounted.
`--groups` adds a line per Stage 5 task group (`exec-*`, not an integrator `exec-wave*`): its
context at its first edit, its peak, its `git commit` calls, the context each commit added,
minutes and units; then the medians, and how many commits fit between the median first edit and
the 200k stop — the size of the lane's next groups (`execution.md`).
Exit 0 on a report, 2 when no transcript is found.
"""

import argparse
import pathlib
import re
import statistics
import sys

from dsp_route import transcript

WEIGHTS = {"input": 1.0, "write_5m": 1.25, "write_1h": 2.0, "output": 5.0}
# (model family, price against Opus 5.5, cache read against the model's input); Opus otherwise.
MODELS = (("haiku", 0.025, 0.1), ("sonnet", 0.5, 0.05))
OPUS = (1.0, 0.05)
HAIKU_LONG = 100_000
CACHE_LIFE = 300  # seconds: the default prompt-cache lifetime
LONG_TURNS = 150
LONG_CONTEXT = 300_000
EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
COMMIT = re.compile(r"\bgit\b(?:\s+-[Cc]\s+\S+)*\s+commit\b")
# route_state.py's CONTEXT_STOP: a task group past it finishes its task and returns (F75).
CONTEXT_STOP = 200_000


def rates(model, prompt):
    """(price factor, cache-read weight) of one request; a Haiku prompt over 100k costs 5x."""
    for family, factor, read in MODELS:
        if family in (model or ""):
            if family == "haiku" and prompt > HAIKU_LONG:
                factor *= 5
            return factor, read
    return OPUS


def scan(path, since, until=None):
    """One transcript: weighted units, per-turn context sizes, model, first and last timestamp."""
    units = idle = 0.0
    contexts = []
    model = None
    efforts = []
    first = last = None
    for q in transcript.requests(path, since, until):
        stamp = q["stamp"]
        model = q["model"] or model
        if q["effort"] and q["effort"] not in efforts:
            efforts.append(q["effort"])
        first = first or stamp
        last = stamp or last
        fresh, write_all, write_1h = q["fresh"], q["write_all"], q["write_1h"]
        read, out = q["read"], q["out"]
        factor, read_weight = rates(model, fresh + write_all + read)
        writes = factor * (
            WEIGHTS["write_5m"] * (write_all - write_1h)
            + WEIGHTS["write_1h"] * write_1h
        )
        units += writes + factor * (
            WEIGHTS["input"] * fresh + read_weight * read + WEIGHTS["output"] * out
        )
        # past the cache's life the whole prompt is written again: when the user ended the
        # wait, that is the wait's cost; after a task group's return it is the wave's (F93)
        if q["waited"] and q["gap"] >= CACHE_LIFE and write_all > read:
            idle += writes
        contexts.append(fresh + write_all + read)
    return {
        "units": units,
        "idle": idle,
        "contexts": contexts,
        "model": model,
        # every effort its requests ran at, in order: the lead may set it per dispatch
        "effort": "/".join(efforts) or "-",
        "first": first,
        "last": last,
    }


def group_stats(path, since, until=None):
    """A task group's context when it first edits a file, and how many `git commit` calls it ran."""
    first_edit = None
    commits = 0
    for context, name, arg in transcript.tool_calls(path, since, until):
        if name in EDITS and first_edit is None:
            first_edit = context
        if name == "Bash" and COMMIT.search(str(arg.get("command") or "")):
            commits += 1
    return {"first_edit": first_edit, "commits": commits}


def sdk_sessions(project, lead_path, since, until):
    """The scan() rows of the hook sessions beside a lead (transcript.sdk_transcripts)."""
    rows = []
    for path in transcript.sdk_transcripts(project, lead_path, since):
        row = scan(path, since, until)
        if row["contexts"]:
            rows.append(row)
    return rows


def route_cost(lead_path, since, until=None):
    """(lead, agents, sdk sessions) of a lead session in [since, until] — each a scan() row."""
    lead = scan(lead_path, since, until)
    agents = subagents(lead_path, since, until)
    # Hook sessions go on after the round: without --until, up to its last record.
    end = until or max((r["last"] for r in [lead, *agents] if r["last"]), default=None)
    sdk = sdk_sessions(lead_path.parent, lead_path, since or lead["first"], end)
    return lead, agents, sdk


def subagents(lead_path, since, until=None):
    """The scan() rows of a session's subagents, each with its label, name and path."""
    agents = []
    for path, label, name in transcript.subagent_transcripts(lead_path, since):
        row = scan(path, since, until)
        if row["contexts"]:
            row["label"], row["name"], row["path"] = label, name, path
            agents.append(row)
    return agents


def describe(row):
    turns = len(row["contexts"])
    mean = statistics.mean(row["contexts"]) if turns else 0
    peak = max(row["contexts"]) if turns else 0
    flag = " LONG" if turns > LONG_TURNS or mean > LONG_CONTEXT else ""
    return f"{row['units'] / 1e6:6.1f}M  turns={turns:4d}  mean={mean / 1e3:4.0f}k  max={peak / 1e3:4.0f}k{flag}"


def kilo(tokens):
    return "    -" if tokens is None else f"{tokens / 1e3:4.0f}k"


def group_lines(agents, since, until=None):
    """A line per Stage 5 task group (`exec-*`; an integrator `exec-wave*` is not one), then medians."""
    lines, firsts, growths, minutes, costs = [], [], [], [], []
    for row in sorted(agents, key=lambda a: a["first"] or ""):
        name = row["name"]
        if not name.startswith("exec-") or name.startswith("exec-wave"):
            continue
        stats = group_stats(row["path"], since, until)
        first, commits = stats["first_edit"], stats["commits"]
        peak = max(row["contexts"])
        growth = (peak - first) / commits if first is not None and commits else None
        span = (
            (transcript.epoch(row["last"]) or 0) - (transcript.epoch(row["first"]) or 0)
        ) / 60
        if first is not None:
            firsts.append(first)
        if growth:
            growths.append(growth)
        minutes.append(span)
        costs.append(row["units"])
        lines.append(
            f"group  {name[:32]:32s}  turns={len(row['contexts']):4d}  first-edit={kilo(first)}  "
            f"peak={kilo(peak)}  commits={commits:2d}  per-commit={kilo(growth)}  "
            f"{span:4.0f} min  {row['units'] / 1e6:5.1f}M"
        )
    if not lines:
        return lines
    summary = (
        f"groups {len(lines)}: median {statistics.median(minutes):.0f} min, "
        f"{statistics.median(costs) / 1e6:.1f}M"
    )
    if firsts and growths:
        first, growth = statistics.median(firsts), statistics.median(growths)
        fit = max(0, int((CONTEXT_STOP - first) // growth))
        summary += (
            f"; first edit at {kilo(first).strip()}, +{kilo(growth).strip()} context per commit: "
            f"about {fit} {'commit fits' if fit == 1 else 'commits fit'} under {CONTEXT_STOP // 1000}k"
        )
    return [*lines, summary]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?")
    parser.add_argument("--project-dir", type=pathlib.Path)
    parser.add_argument("--since", type=transcript.timestamp)
    parser.add_argument("--until", type=transcript.timestamp)
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--groups", action="store_true")
    args = parser.parse_args()

    lead_path = transcript.find_lead(args.project_dir, args.session)
    if not lead_path.exists():
        print(f"no transcript at {lead_path}", file=sys.stderr)
        return 2

    lead, agents, sdk = route_cost(lead_path, args.since, args.until)
    agent_units = sum(a["units"] for a in agents)
    sdk_units = sum(s["units"] for s in sdk)
    total = lead["units"] + agent_units + sdk_units
    print(f"session {lead_path.stem}  {lead['first'] or '-'} .. {lead['last'] or '-'}")
    print(
        f"total {total / 1e6:.1f}M = lead {lead['units'] / 1e6:.1f}M + {len(agents)} agents "
        f"{agent_units / 1e6:.1f}M + {len(sdk)} hook sessions {sdk_units / 1e6:.1f}M"
    )
    print(f"lead   {describe(lead)}  effort {lead['effort']}")
    for row in sorted(agents, key=lambda a: -a["units"])[: args.top]:
        print(
            f"agent  {describe(row)}  {str(row['model'])[:18]:18s}  {row['effort']:11s}  "
            f"{row['label'][:60]}"
        )
    if len(agents) > args.top:
        print(f"... {len(agents) - args.top} more agents")
    if args.groups:
        print(
            "\n".join(group_lines(agents, args.since, args.until))
            or "no exec- task groups"
        )
    if sdk:
        print(
            f"hook   {sdk_units / 1e6:6.1f}M  {len(sdk)} sessions a hook or plugin started through "
            "the Agent SDK in this project and its worktrees (entrypoint sdk-*)"
        )
    print(
        f"LONG = more than {LONG_TURNS} turns or a mean context above {LONG_CONTEXT // 1000}k per turn"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
