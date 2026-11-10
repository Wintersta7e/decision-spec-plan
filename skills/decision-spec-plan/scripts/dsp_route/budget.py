"""--budget: record the route's estimate, which the hook then holds the lead's `exec-` dispatches
to (execution.md, F74)."""

import argparse
import datetime
import os
import pathlib
import re

from .common import BUDGETS, REGISTRY, SLACK, checked, load_json, parser, save_budget
from .transcript import answered_this_turn, now, project_sessions, session_transcripts

# --budget sizes groups by the project's task groups of this many days back
FIT_DAYS = 14


def measured_fit(session):
    """usage_report's group line over this project's task groups of the last FIT_DAYS, and the
    commits it says fit a group: (None, None) with no measured group."""
    import usage_report

    lead = next(iter(session_transcripts(session)), None)
    if lead is None:
        return None, None
    floor = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=FIT_DAYS)
    since = floor.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    agents = []
    for path in project_sessions(lead, floor.timestamp()):
        agents += usage_report.subagents(path, since)
    lines = usage_report.group_lines(agents, since)
    m = lines and re.search(r"about (\d+) commits? fits? under", lines[-1])
    return (lines[-1], int(m[1])) if m else (None, None)


def budget(argv):
    """--budget: append the route's estimate to its planning dir's budget file."""
    ap = argparse.ArgumentParser(
        prog="route_state.py --budget",
        description="Record the route's estimate: the lead, every review and agent of the "
        "stages left (execution.md).",
    )
    ap.add_argument(
        "--budget", required=True, metavar="LABEL", help="the route, or the work left"
    )
    ap.add_argument(
        "--estimate", type=float, required=True, help="M units, priced per costs.md"
    )
    ap.add_argument(
        "--groups",
        type=int,
        help="optional: the exec- agents it covers (task groups, fix groups, integrators), "
        "checked with --tasks against the project's measured group fit",
    )
    ap.add_argument(
        "--tasks",
        type=int,
        help="optional: the plan tasks its task groups carry",
    )
    ap.add_argument(
        "planning_dir", nargs="?", help="optional: this session's route's planning dir"
    )
    ap.add_argument("--phase", help="optional: this session's route's phase")
    ap.add_argument("--repo", help="optional: this session's route's repository")
    ap.add_argument(
        "--base",
        choices=("pin", "catch-up", "merge"),
        help="the user's answer when what the round was planned on moved (F91): pin the "
        "recorded base, catch up to the moves seen now, or merge the base into each lane",
    )
    a = ap.parse_args(argv)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    entry = load_json(REGISTRY / f"{session}.json") if session else {}
    path = pathlib.Path(entry.get("marker", ""))
    marker = load_json(path) if entry else {}
    if not marker.get("args"):
        print(
            "--budget: no route is registered for this session — run route_state.py "
            "--activate first"
        )
        return 2
    own = pathlib.Path(entry.get("planning_dir", "")).resolve()
    if a.planning_dir and pathlib.Path(a.planning_dir).resolve() != own:
        print(f"--budget: {a.planning_dir} is not this session's route ({own})")
        return 2
    route = parser().parse_args(marker["args"])
    phase = route.phase
    repo = a.repo and str(pathlib.Path(a.repo).resolve())
    for flag, given, have in (
        ("--phase", a.phase, phase),
        ("--repo", repo, route.repo),
    ):
        if given and have and given != have:
            print(f"--budget: {flag} {given} is not this session's route ({have})")
            return 2
    record = {
        "label": a.budget,
        "estimate": a.estimate,
        "phase": phase,
        "at": now(),
        "session": session,
    }
    if a.groups is not None:
        record["groups"] = a.groups
    from .report import round_moved

    moved = checked(round_moved, own, route) or []
    if a.base:
        record["base"], record["moved"] = a.base, moved
    if answered := answered_this_turn(session, a.estimate):
        record["answered"] = answered
    save_budget(own, marker, record)
    print(
        f"budget recorded: {a.budget} — {a.estimate:g}M, phase {phase}, at {record['at']}, in "
        f"{own / BUDGETS}"
    )
    # sized by count, one route's groups ran 5 -> 11 where its own measure fit two commits (F60)
    line, fit = checked(measured_fit, session) or (None, None)
    if line and fit is not None:  # measured_fit gives both or neither
        print(f"measured on this project: {line.partition('; ')[2] or line}")
        need = -(-a.tasks // max(fit, 1)) if a.tasks else 0
        if a.groups is not None and need > a.groups:
            print(
                f"{a.tasks} tasks need at least {need} task groups, not {a.groups}: size each "
                f"group to {max(fit, 1)} tasks, re-price, and record the figure again "
                "(execution.md)."
            )
    if moved and not a.base:
        print(
            "What the round was planned on moved, as of the last fetch (F91):\n"
            + "\n".join(f"  {ln}" for ln in moved)
            + "\nAsk with this figure: pin the recorded base, catch up (re-check each ruling on "
            "the moved ref and re-plan, priced) or track by merge — the hook holds exec- "
            "dispatches until you record the answer with --base pin|catch-up|merge."
        )
    then = (
        f"again once the route's spend from now passes {a.estimate * SLACK:.3g}M; a new lead "
        "session of the route keeps this figure and its answer."
    )
    if answered:
        print(
            f"The user answered your question at {answered}, earlier in this turn: that answer "
            f"stands for this figure, so the hook lets exec- dispatches through, and holds them "
            + then
        )
    elif marker.get("rung") == "S":
        print(
            "At S, tell the user this figure with the plan and go on: the hook does not wait "
            "for an answer, and holds exec- dispatches " + then
        )
    else:
        print(
            "Tell the user this figure and wait for their answer: the hook holds every exec- "
            "dispatch until they answer, and " + then
        )
        # the figure asked is the figure recorded: an ask of 0.5M against a record of 0.8M
        # was no answer to it, and cost a second ask (F93)
        print(
            f"Ask exactly: \"{a.budget}: {a.estimate:g}M for phase {phase}'s work left — the "
            'lead, its reviews and agents — go ahead?", with the strongest reason against it '
            "and an option to run less."
        )
    return 0
