# SPDX-License-Identifier: MIT
"""--budget: record the route's estimate.

The hook then holds the lead's `exec-` dispatches to it (execution.md, F74).
"""

import argparse
import datetime as dt
import os
import pathlib
import re
from collections.abc import Mapping, Sequence

from .common import (
    BUDGETS,
    REGISTRY,
    SLACK,
    Budget,
    RouteArgs,
    checked,
    load_json,
    route_args,
    save_budget,
)
from .transcript import answered_this_turn, now, project_sessions, session_transcripts

# --budget sizes groups by the project's task groups of this many days back
FIT_DAYS = 14


class BudgetArgs(argparse.Namespace):
    """The arguments of --budget.

    Each value is the option's default: argparse leaves a value the namespace already
    has until the option is given.
    """

    budget: str = ""
    estimate: float = 0.0
    groups: int | None = None
    tasks: int | None = None
    planning_dir: str | None = None
    phase: str | None = None
    repo: str | None = None
    base: str | None = None


def measured_fit(session: str) -> tuple[str | None, int | None]:
    """Return usage_report's group line and the commits it says fit a group.

    Over this project's task groups of the last FIT_DAYS; (None, None) with no measured
    group.
    """
    import usage_report

    lead = next(iter(session_transcripts(session)), None)
    if lead is None:
        return None, None
    floor = dt.datetime.now(dt.UTC) - dt.timedelta(days=FIT_DAYS)
    since = floor.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    agents: list[usage_report.Agent] = []
    for path in project_sessions(lead, floor.timestamp()):
        agents += usage_report.subagents(path, since)
    lines = usage_report.group_lines(agents, since)
    m = re.search(r"about (\d+) commits? fits? under", lines[-1]) if lines else None
    return (lines[-1], int(m[1])) if m else (None, None)


def _args(argv: Sequence[str]) -> BudgetArgs:
    """Return the parsed arguments of --budget."""
    ap = argparse.ArgumentParser(
        prog="route_state.py --budget",
        description="Record the route's estimate: the lead, every review and agent of "
        "the stages left (execution.md).",
    )
    _ = ap.add_argument(
        "--budget", required=True, metavar="LABEL", help="the route, or the work left"
    )
    _ = ap.add_argument(
        "--estimate", type=float, required=True, help="M units, priced per costs.md"
    )
    _ = ap.add_argument(
        "--groups",
        type=int,
        help="optional: the exec- agents it covers (task groups, fix groups, "
        "integrators), checked with --tasks against the project's measured group fit",
    )
    _ = ap.add_argument(
        "--tasks",
        type=int,
        help="optional: the plan tasks its task groups carry",
    )
    _ = ap.add_argument(
        "planning_dir", nargs="?", help="optional: this session's route's planning dir"
    )
    _ = ap.add_argument("--phase", help="optional: this session's route's phase")
    _ = ap.add_argument("--repo", help="optional: this session's route's repository")
    _ = ap.add_argument(
        "--base",
        choices=("pin", "catch-up", "merge"),
        help="the user's answer when what the round was planned on moved (F91): pin "
        "the recorded base, catch up to the moves seen now, or merge the base into "
        "each lane",
    )
    return ap.parse_args(argv, namespace=BudgetArgs())


def _mismatch(a: BudgetArgs, route: RouteArgs) -> str | None:
    """Return the refusal when --phase or --repo names another route, else None."""
    repo = str(pathlib.Path(a.repo).resolve()) if a.repo else a.repo
    for flag, given, have in (
        ("--phase", a.phase, route.phase),
        ("--repo", repo, route.repo),
    ):
        if given and have and given != have:
            return f"--budget: {flag} {given} is not this session's route ({have})"
    return None


def _print_fit(a: BudgetArgs, session: str) -> None:
    """Print the project's measured group fit, and a group count it says is short."""
    # sized by count, one route's groups ran 5 -> 11 where its own measure fit
    # two commits (F60)
    line, fit = checked(measured_fit, session) or (None, None)
    if not line or fit is None:  # measured_fit gives both or neither
        return
    print(f"measured on this project: {line.partition('; ')[2] or line}")
    need = -(-a.tasks // max(fit, 1)) if a.tasks else 0
    if a.groups is not None and need > a.groups:
        print(
            f"{a.tasks} tasks need at least {need} task groups, not {a.groups}: size "
            f"each group to {max(fit, 1)} tasks, re-price, and record the figure again "
            "(execution.md)."
        )


def _print_ask(
    a: BudgetArgs, phase: str, marker: Mapping[str, object], answered: str | None
) -> None:
    """Print what the lead tells the user about the recorded figure."""
    then = (
        f"again once the route's spend from now passes {a.estimate * SLACK:.3g}M; a "
        "new lead session of the route keeps this figure and its answer."
    )
    if answered:
        print(
            f"The user answered your question at {answered}, earlier in this turn: "
            "that answer stands for this figure, so the hook lets exec- dispatches "
            "through, and holds them " + then
        )
    elif marker.get("rung") == "S":
        print(
            "At S, tell the user this figure with the plan and go on: the hook does "
            "not wait for an answer, and holds exec- dispatches " + then
        )
    else:
        print(
            "Tell the user this figure and wait for their answer: the hook holds every "
            "exec- dispatch until they answer, and " + then
        )
        # the figure asked is the figure recorded: an ask of 0.5M against a record of
        # 0.8M was no answer to it, and cost a second ask (F93)
        print(
            f"Ask exactly: \"{a.budget}: {a.estimate:g}M for phase {phase}'s work left "
            '— the lead, its reviews and agents — go ahead?", with the strongest '
            "reason against it and an option to run less."
        )


def budget(argv: Sequence[str]) -> int:
    """--budget: append the route's estimate to its planning dir's budget file.

    Returns:
        The exit code: 2 when the session has no such route, else 0.
    """
    a = _args(argv)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    entry = load_json(REGISTRY / f"{session}.json") if session else {}
    path = pathlib.Path(str(entry.get("marker", "")))
    marker = load_json(path) if entry else {}
    if not marker.get("args"):
        print(
            "--budget: no route is registered for this session — run route_state.py "
            "--activate first"
        )
        return 2
    own = pathlib.Path(str(entry.get("planning_dir", ""))).resolve()
    if a.planning_dir and pathlib.Path(a.planning_dir).resolve() != own:
        print(f"--budget: {a.planning_dir} is not this session's route ({own})")
        return 2
    route = route_args(marker)
    phase = route.phase
    if refusal := _mismatch(a, route):
        print(refusal)
        return 2
    record: Budget = {
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
        f"budget recorded: {a.budget} — {a.estimate:g}M, phase {phase}, at "
        f"{record['at']}, in {own / BUDGETS}"
    )
    _print_fit(a, session)
    if moved and not a.base:
        print(
            "What the round was planned on moved, as of the last fetch (F91):\n"
            + "\n".join(f"  {ln}" for ln in moved)
            + "\nAsk with this figure: pin the recorded base, catch up (re-check each "
            "ruling on the moved ref and re-plan, priced) or track by merge — the hook "
            "holds exec- dispatches until you record the answer with --base "
            "pin|catch-up|merge."
        )
    _print_ask(a, phase, marker, answered)
    return 0
