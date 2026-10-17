#!/usr/bin/env python3
"""Cost of a decision-spec-plan run, read from Claude Code's session transcripts.

Prints the lead's and every subagent's cost with turns and mean/max context per turn, so a gate can
report what the round cost and which agent ran long. Units are Opus-input-equivalent tokens: cache
read x0.1, 5-minute cache write x1.25, 1-hour cache write x2, output x5; Sonnet x0.6, Haiku x0.2.
Output is a lower bound: transcripts store thinking redacted and streamed snapshots undercount it.

Usage:
    usage_report.py [session-id] [--project-dir DIR] [--since ISO-TIMESTAMP] [--top N]

Without a session id it reports the newest session of the project whose directory is the current
working directory, which is the running lead's own. `--since` counts only records at or after the
timestamp (e.g. the skill's start). Sessions a hook or plugin started through the Agent SDK in the
project or one of its worktrees (entrypoint `sdk-*`, e.g. a security review of every commit) are
counted too, from the same time on: 53 and 87 of them cost two runs 3.0M each in a day, uncounted.
Exit 0 on a report, 2 when no transcript is found.
"""

import argparse
import datetime
import json
import pathlib
import re
import statistics
import sys

WEIGHTS = {"input": 1.0, "write_5m": 1.25, "write_1h": 2.0, "read": 0.1, "output": 5.0}
MODEL_FACTOR = {"sonnet": 0.6, "haiku": 0.2}
LONG_TURNS = 150
LONG_CONTEXT = 300_000
ENTRYPOINT = re.compile(r'"entrypoint":"([^"]*)"')


def model_factor(model):
    for name, factor in MODEL_FACTOR.items():
        if name in (model or ""):
            return factor
    return 1.0


def scan(path, since):
    """One transcript: weighted units, per-turn context sizes, model, first and last timestamp."""
    seen = set()
    units = 0.0
    contexts = []
    model = None
    first = last = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            stamp = record.get("timestamp")
            if since and stamp and stamp < since:
                continue
            message = record.get("message")
            if record.get("type") != "assistant" or not isinstance(message, dict):
                continue
            usage = message.get("usage")
            key = (message.get("id"), record.get("requestId"))
            if not usage or key in seen or message.get("model") == "<synthetic>":
                continue
            seen.add(key)
            model = message.get("model") or model
            first = first or stamp
            last = stamp or last
            write_all = usage.get("cache_creation_input_tokens", 0) or 0
            write_1h = (usage.get("cache_creation") or {}).get(
                "ephemeral_1h_input_tokens", 0
            ) or 0
            read = usage.get("cache_read_input_tokens", 0) or 0
            fresh = usage.get("input_tokens", 0) or 0
            out = usage.get("output_tokens", 0) or 0
            units += model_factor(model) * (
                WEIGHTS["input"] * fresh
                + WEIGHTS["write_5m"] * (write_all - write_1h)
                + WEIGHTS["write_1h"] * write_1h
                + WEIGHTS["read"] * read
                + WEIGHTS["output"] * out
            )
            contexts.append(fresh + write_all + read)
    return {
        "units": units,
        "contexts": contexts,
        "model": model,
        "first": first,
        "last": last,
    }


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


def sdk_sessions(project, lead_path, since):
    """Sessions with an `sdk-*` entrypoint in the project dir or a worktree's (`<project>-*`)."""
    floor = epoch(since)
    rows = []
    for directory in [project, *sorted(project.parent.glob(project.name + "-*"))]:
        for path in sorted(directory.glob("*.jsonl")):
            if path == lead_path or (floor and path.stat().st_mtime < floor):
                continue
            if entrypoint(path).startswith("sdk"):
                row = scan(path, since)
                if row["contexts"]:
                    rows.append(row)
    return rows


def route_cost(lead_path, since):
    """(lead, agents, sdk sessions) of a lead session from `since` on — each a scan() row."""
    lead = scan(lead_path, since)
    agents = []
    floor = epoch(since)
    for path in sorted(
        (lead_path.parent / lead_path.stem / "subagents").glob("agent-*.jsonl")
    ):
        if floor and path.stat().st_mtime < floor:
            continue
        meta_path = path.with_name(path.stem + ".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        row = scan(path, since)
        if row["contexts"]:
            row["label"] = meta.get("description") or meta.get("agentType") or path.stem
            agents.append(row)
    sdk = sdk_sessions(lead_path.parent, lead_path, since or lead["first"])
    return lead, agents, sdk


def describe(row):
    turns = len(row["contexts"])
    mean = statistics.mean(row["contexts"]) if turns else 0
    peak = max(row["contexts"]) if turns else 0
    flag = " LONG" if turns > LONG_TURNS or mean > LONG_CONTEXT else ""
    return f"{row['units'] / 1e6:6.1f}M  turns={turns:4d}  mean={mean / 1e3:4.0f}k  max={peak / 1e3:4.0f}k{flag}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session", nargs="?")
    parser.add_argument("--project-dir", type=pathlib.Path)
    parser.add_argument("--since", type=timestamp)
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()

    project = args.project_dir or (
        pathlib.Path.home()
        / ".claude"
        / "projects"
        / re.sub(r"[^A-Za-z0-9]", "-", str(pathlib.Path.cwd()))
    )
    if args.session:
        lead_path = project / f"{args.session}.jsonl"
    else:
        candidates = sorted(project.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        lead_path = candidates[-1] if candidates else project / "missing.jsonl"
    if not lead_path.exists():
        print(f"no transcript at {lead_path}", file=sys.stderr)
        return 2

    lead, agents, sdk = route_cost(lead_path, args.since)
    agent_units = sum(a["units"] for a in agents)
    sdk_units = sum(s["units"] for s in sdk)
    total = lead["units"] + agent_units + sdk_units
    print(f"session {lead_path.stem}  {lead['first'] or '-'} .. {lead['last'] or '-'}")
    print(
        f"total {total / 1e6:.1f}M = lead {lead['units'] / 1e6:.1f}M + {len(agents)} agents "
        f"{agent_units / 1e6:.1f}M + {len(sdk)} hook sessions {sdk_units / 1e6:.1f}M"
    )
    print(f"lead   {describe(lead)}")
    for row in sorted(agents, key=lambda a: -a["units"])[: args.top]:
        print(
            f"agent  {describe(row)}  {str(row['model'])[:18]:18s}  {row['label'][:60]}"
        )
    if len(agents) > args.top:
        print(f"... {len(agents) - args.top} more agents")
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
