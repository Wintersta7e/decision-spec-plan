# SPDX-License-Identifier: MIT
"""--activate: record a round's arguments where the hooks and push_guard.py see them."""

import json
import os
import pathlib
import re
import sys
import time
from collections.abc import Mapping

from .common import (
    LEDGER_CHECKS,
    MARKER,
    REGISTRY,
    RegistryEntry,
    RouteArgs,
    StrPath,
    ago,
    as_dict,
    checked,
    load_json,
    marker_path,
    route_args,
    routes,
)
from .transcript import session_transcripts, shape_line

RUNNER = re.compile(r"\b(?:windows|macos)-(?:latest|\d[\w.-]*)\b")


def foreign_runners(repo: StrPath) -> list[str]:
    """Return the CI runners on an OS other than this host's, named in the workflows.

    The local full gate never runs what they test (F90).
    """
    host = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    found: set[str] = set()
    for f in pathlib.Path(repo).glob(".github/workflows/*.y*ml"):
        found |= {m[0] for m in RUNNER.finditer(f.read_text(errors="replace"))}
    return sorted(r for r in found if not r.startswith(host))


def _marker_args(
    a: RouteArgs, prev: RouteArgs | None, planning: str, main: str
) -> list[str]:
    """Return the arguments the marker records, the previous marker's filling gaps.

    A re-activation that leaves out the route's repo, main branch, spec dir or (in the
    same phase) sections keeps them: execution.md's `--activate --sins on` names none
    of them.
    """
    same_phase = prev is not None and prev.phase == a.phase
    repo_arg = a.repo or (prev.repo if prev else None)
    sections = a.sections or (prev.sections if prev and same_phase else None)
    spec_dir = a.spec_dir or (prev.spec_dir if prev else None)
    args = [
        planning,
        "--phase",
        a.phase,
        "--main",
        a.main or (prev.main if prev else None) or main,
    ]
    if repo_arg:
        args += ["--repo", str(pathlib.Path(repo_arg).resolve())]
    if sections:
        args += ["--sections", sections]
    if spec_dir:
        args += ["--spec-dir", str(pathlib.Path(spec_dir).resolve())]
    return args


def _kept_fields(
    a: RouteArgs,
    old: Mapping[str, object],
    marker: dict[str, object],
    *,
    same_phase: bool,
) -> None:
    """Carry the fields a re-activation keeps from the old marker into the new one."""
    # A re-activation keeps the phase's rung (execution.md's `--activate --sins on`
    # names none), budgets --budget recorded here before they moved to the planning
    # dir, and the CI harness, a fact about the repository's CI rather than the round.
    if rung := a.rung or (old.get("rung") if same_phase else None):
        marker["rung"] = rung
    if budgets := old.get("budgets"):
        marker["budgets"] = budgets
    if asks := old.get("asks"):  # the answer tally spans the route (F89)
        marker["asks"] = asks
    harness = a.ci_harness or old.get("ci_harness")
    if harness and harness != "none":
        marker["ci_harness"] = harness
    elif a.ci_harness == "none" or (not a.ci_harness and old.get("ci_none")):
        marker["ci_none"] = True  # the answer: the local gate covers what CI runs
    if (a.sins or old.get("sins")) == "on":
        marker["sins"] = "on"


def _bound(value: object) -> dict[str, int]:
    """Return a ledger: {phase or round: bound} and `<phase>#checks`."""
    return {k: v for k, v in (as_dict(value) or {}).items() if isinstance(v, int)}


def _ledger(a: RouteArgs, old: Mapping[str, object], planning: str) -> dict[str, int]:
    """Return the decision ledger the marker and the registry entry record.

    The decision ledger (decision_check.py) binds a phase whose index did not exist
    when the phase was first activated: an index written before the check keeps its
    old format.
    """
    ledger = _bound(old.get("ledger"))
    # A route ended (its marker deleted) and begun again: its sessions' registry
    # entries keep it.
    kept: dict[str, int] = {}
    for f in REGISTRY.glob("*.json"):
        entry = load_json(f)
        if entry.get("planning_dir") == planning:
            for phase, bound in _bound(entry.get("ledger")).items():
                kept[phase] = kept.get(phase, False) or bound
    for phase, bound in kept.items():
        _ = ledger.setdefault(phase, bound)
    index = pathlib.Path(planning) / "decisions" / f"phase{a.phase}" / "00-index.md"
    if a.phase not in ledger:
        # so does a review round's own index (`phase<P>/<round>/00-index.md`); a round
        # written later is bound, absent from the ledger
        for r in sorted(index.parent.glob("*/00-index.md")):
            ledger[f"{a.phase}/{r.parent.name}"] = False
        # the checks the phase is bound under: one added later never holds an index
        # written before it
        ledger[f"{a.phase}#checks"] = LEDGER_CHECKS
    _ = ledger.setdefault(a.phase, not index.exists())
    return ledger


def _print_guards(marker: Mapping[str, object], repo_arg: str | None) -> list[str]:
    """Print the push holds the marker turns on; return the CI's foreign runners."""
    if "ci_harness" in marker:
        harness = marker["ci_harness"]
        print(
            f"CI harness {harness}: push_guard.py also holds every push until a gate "
            f"log with `harness={harness}` passed on that commit (`--ci-harness none` "
            "clears it)"
        )
    if "sins" in marker:
        print(
            "sins on: push_guard.py also holds every push until a seven-sins verdict "
            "covers it (references/sins/lead.md; `--sins off` clears it)"
        )
    unanswered = "ci_harness" not in marker and "ci_none" not in marker
    foreign = foreign_runners(repo_arg) if unanswered and repo_arg else []
    if foreign:
        print(
            f"CI runs on {', '.join(foreign)}, which this host is not: the local full "
            "gate never runs what it tests. Activate again with --ci-harness <label> "
            "(each push then needs that suite's gate log, run where it can run: "
            "execution.md) or --ci-harness none when the local gate covers it (F90)"
        )
    return foreign


def _register(
    session: str, path: pathlib.Path, planning: str, ledger: dict[str, int]
) -> None:
    """Register this session's entry in REGISTRY."""
    REGISTRY.mkdir(parents=True, exist_ok=True)
    entry_path = REGISTRY / f"{session}.json"
    old = load_json(entry_path)
    # When this session last read the skill's files: a re-activation is no re-read.
    seen = old.get("skill_seen", old.get("activated", time.time()))
    entry: RegistryEntry = {
        "marker": str(path),
        "planning_dir": planning,
        "activated": time.time(),
        "ledger": ledger,
    }
    entry["skill_seen"] = seen if isinstance(seen, int | float) else time.time()
    _ = entry_path.write_text(json.dumps(entry) + "\n")
    print(f"hooks registered for session {session}")


def _print_other_routes(session: str, path: pathlib.Path) -> None:
    """Print each other route on this account, with when its lead was last active."""
    # Activity = the newest write to any registered lead's transcript for that route; a
    # route restarted in a new session has two registry entries.
    latest: dict[str, float] = {}
    for sid, e in routes(session):
        if e["marker"] == str(path):
            continue
        seen = [p.stat().st_mtime for p in session_transcripts(sid)]
        seen = seen or [pathlib.Path(e["marker"]).stat().st_mtime]
        latest[e["planning_dir"]] = max(*seen, latest.get(e["planning_dir"], 0))
    for planning_dir, t in latest.items():
        print(
            f"other route on this account: {planning_dir} (lead last active "
            f"{ago(time.time() - t)} ago) — it shares the weekly and second-model quota"
        )


def activate(a: RouteArgs, main: str) -> int:
    """Record this round's arguments where the hooks and push_guard.py find them.

    Returns:
        The exit code: 2 outside a repository, 1 with no session to register or a CI
        runner this host is not, else 0.
    """
    # Absolute paths, so the hook resolves them from any working directory.
    planning = str(pathlib.Path(a.planning_dir).resolve())
    repo = pathlib.Path(a.repo or a.planning_dir).resolve()
    path = marker_path(repo, planning)
    if path is None:
        print(f"--activate: {a.repo or a.planning_dir} is not inside a git repository")
        return 2
    # A route activated before markers were per planning dir moves to its own.
    legacy = path.with_name(MARKER)
    old = load_json(path)
    if not old and load_json(legacy).get("planning_dir") == planning:
        old = load_json(legacy)
        legacy.unlink()
    prev = route_args(old) if old.get("args") else None
    same_phase = prev is not None and prev.phase == a.phase
    args = _marker_args(a, prev, planning, main)
    marker: dict[str, object] = {
        "args": args,
        "planning_dir": planning,
        "activated": time.time(),
    }
    _kept_fields(a, old, marker, same_phase=same_phase)
    ledger = _ledger(a, old, planning)
    marker["ledger"] = ledger
    _ = path.write_text(json.dumps(marker) + "\n")
    print(f"route active: {path}")
    import push_guard  # only --activate needs it: the hook runs on every tool call

    print(push_guard.install_hook(repo))
    foreign = _print_guards(marker, a.repo or (prev.repo if prev else None))
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        print(
            "--activate: CLAUDE_CODE_SESSION_ID is unset, so no session is registered "
            "and the state hook stays silent; push_guard.py is active"
        )
        return 1
    _register(session, path, planning, ledger)
    # The hooks read the transcript and let a call through on a shape they cannot
    # find: said here, a format change is a line at activation rather than gates
    # silently off.
    if line := checked(shape_line, session):
        print(line)
    _print_other_routes(session, path)
    return 1 if foreign else 0
