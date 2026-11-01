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
import datetime
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys

WEIGHTS = {"input": 1.0, "write_5m": 1.25, "write_1h": 2.0, "output": 5.0}
# (model family, price against Opus 5.5, cache read against the model's input); Opus otherwise.
MODELS = (("haiku", 0.025, 0.1), ("sonnet", 0.5, 0.05))
OPUS = (1.0, 0.05)
HAIKU_LONG = 100_000
CACHE_LIFE = 300  # seconds: the default prompt-cache lifetime
LONG_TURNS = 150
LONG_CONTEXT = 300_000
ENTRYPOINT = re.compile(r'"entrypoint":"([^"]*)"')
CWD = re.compile(r'"cwd":"([^"]*)"')
# route_state.py's session registry: one entry per route lead
REGISTRY = pathlib.Path.home() / ".claude" / "dsp-routes"
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


def human(record):
    """A prompt the user typed or queued, or their answer to AskUserQuestion."""
    if record.get("isMeta") or record.get("isCompactSummary"):
        return False
    result = record.get("toolUseResult")
    if isinstance(result, dict) and "answers" in result:
        return True
    attachment = record.get("attachment")
    origin = record.get("origin") or (
        attachment.get("origin") if isinstance(attachment, dict) else None
    )
    return isinstance(origin, dict) and origin.get("kind") == "human"


def scan(path, since, until=None):
    """One transcript: weighted units, per-turn context sizes, model, first and last timestamp."""
    seen = set()
    units = idle = 0.0
    contexts = []
    model = None
    efforts = []
    first = last = previous = None
    asked = False  # the user prompted or answered since the last request
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            stamp = record.get("timestamp")
            message = record.get("message")
            if record.get("type") != "assistant" or not isinstance(message, dict):
                asked = asked or human(record)
                continue
            usage = message.get("usage")
            key = (message.get("id"), record.get("requestId"))
            if not usage or key in seen or message.get("model") == "<synthetic>":
                continue
            seen.add(key)
            now, before = epoch(stamp), epoch(previous)
            gap = now - before if now is not None and before is not None else 0
            previous = stamp or previous
            waited, asked = asked, False
            if stamp and ((since and stamp < since) or (until and stamp > until)):
                continue
            model = message.get("model") or model
            if record.get("effort") and record["effort"] not in efforts:
                efforts.append(record["effort"])
            first = first or stamp
            last = stamp or last
            write_all = usage.get("cache_creation_input_tokens", 0) or 0
            write_1h = (usage.get("cache_creation") or {}).get(
                "ephemeral_1h_input_tokens", 0
            ) or 0
            read = usage.get("cache_read_input_tokens", 0) or 0
            fresh = usage.get("input_tokens", 0) or 0
            out = usage.get("output_tokens", 0) or 0
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
            if waited and gap >= CACHE_LIFE and write_all > read:
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
    seen = set()
    context = 0
    first_edit = None
    commits = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            stamp = record.get("timestamp")
            if stamp and ((since and stamp < since) or (until and stamp > until)):
                continue
            message = record.get("message")
            if record.get("type") != "assistant" or not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if usage and message.get("model") != "<synthetic>":
                context = sum(
                    usage.get(k, 0) or 0
                    for k in (
                        "input_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    )
                )
            for block in message.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("id") in seen:
                    continue
                seen.add(block.get("id"))
                if block.get("name") in EDITS and first_edit is None:
                    first_edit = context
                command = (block.get("input") or {}).get("command")
                if block.get("name") == "Bash" and COMMIT.search(str(command or "")):
                    commits += 1
    return {"first_edit": first_edit, "commits": commits}


def epoch(stamp):
    """Seconds since the epoch of an ISO timestamp (UTC when it names no zone), or None."""
    try:
        moment = datetime.datetime.fromisoformat(stamp)
    except (AttributeError, TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.timestamp()


def timestamp(text):
    """`--since` in the transcripts' format (UTC, milliseconds, `Z`): scan() compares the two as strings."""
    seconds = epoch(text)
    if seconds is None:
        raise ValueError(text)
    moment = datetime.datetime.fromtimestamp(seconds, datetime.UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def entrypoint(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _, line in zip(range(20), fh):
            if m := ENTRYPOINT.search(line):
                return m.group(1)
    return ""


def common_dir(path):
    """The git common dir of the first `cwd` a transcript records, or None (gone, or no repo)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _, line in zip(range(20), fh):
            if m := CWD.search(line):
                r = subprocess.run(
                    [
                        "git",
                        "-C",
                        m.group(1),
                        "rev-parse",
                        "--path-format=absolute",
                        "--git-common-dir",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return r.stdout.strip() if r.returncode == 0 else None
    return None


def sdk_sessions(project, lead_path, since, until):
    """Sessions with an `sdk-*` entrypoint in the project dir or a worktree's (`<project>-*`).

    A route's lead (registered by `route_state.py --activate`) is a lead even when headless
    (`sdk-cli`). A `<project>-*` dir counts only for the sessions that ran in the lead's
    repository: one named alike, or whose repository is unknown, is another project — counted,
    its headless sessions held a route's wave over a budget it had not spent."""
    floor = epoch(since)
    rows = []
    repo = common_dir(lead_path)
    for directory in [project, *sorted(project.parent.glob(project.name + "-*"))]:
        for path in sorted(directory.glob("*.jsonl")):
            if path == lead_path or (floor and path.stat().st_mtime < floor):
                continue
            if (REGISTRY / f"{path.stem}.json").exists():
                continue
            if directory != project and (repo is None or common_dir(path) != repo):
                continue
            if entrypoint(path).startswith("sdk"):
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
    floor = epoch(since)
    for path in sorted(
        (lead_path.parent / lead_path.stem / "subagents").glob("agent-*.jsonl")
    ):
        if floor and path.stat().st_mtime < floor:
            continue
        meta_path = path.with_name(path.stem + ".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        row = scan(path, since, until)
        if row["contexts"]:
            row["label"] = meta.get("description") or meta.get("agentType") or path.stem
            row["name"] = str(meta.get("name") or meta.get("agentType") or "")
            row["path"] = path
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
        span = ((epoch(row["last"]) or 0) - (epoch(row["first"]) or 0)) / 60
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
    parser.add_argument("--since", type=timestamp)
    parser.add_argument("--until", type=timestamp)
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--groups", action="store_true")
    args = parser.parse_args()

    # --project-dir is the transcript dir, or the project itself (a lead passed that, live)
    project = args.project_dir
    if not (project and any(project.glob("*.jsonl"))):
        project = (
            pathlib.Path.home()
            / ".claude"
            / "projects"
            / re.sub(
                r"[^A-Za-z0-9]", "-", str((project or pathlib.Path.cwd()).resolve())
            )
        )
    # Without a session id, the running session's own if it is in this project: the newest
    # transcript may be a hook's or another lead's.
    own = project / f"{os.environ.get('CLAUDE_CODE_SESSION_ID')}.jsonl"
    if args.session:
        lead_path = project / f"{args.session}.jsonl"
    elif os.environ.get("CLAUDE_CODE_SESSION_ID") and own.exists():
        lead_path = own
    else:
        candidates = sorted(project.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        lead_path = candidates[-1] if candidates else project / "missing.jsonl"
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
