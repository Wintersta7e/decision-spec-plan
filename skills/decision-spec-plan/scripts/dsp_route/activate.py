"""--activate: record a round's arguments where the hooks and push_guard.py find them."""

import json
import os
import pathlib
import re
import sys
import time

from .common import (
    LEDGER_CHECKS,
    REGISTRY,
    ago,
    checked,
    load_json,
    marker_path,
    parser,
    routes,
)
from .transcript import session_transcripts, shape_line

RUNNER = re.compile(r"\b(?:windows|macos)-(?:latest|\d[\w.-]*)\b")


def foreign_runners(repo):
    """The CI runners on an OS other than this host's, named in the repo's workflows: the local
    full gate never runs what they test (F90)."""
    host = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    found = set()
    for f in pathlib.Path(repo).glob(".github/workflows/*.y*ml"):
        found |= {m[0] for m in RUNNER.finditer(f.read_text(errors="replace"))}
    return sorted(r for r in found if not r.startswith(host))


def activate(a, main):
    """Record this round's arguments where the hooks and push_guard.py find them."""
    # Absolute paths, so the hook resolves them from any working directory.
    planning = str(pathlib.Path(a.planning_dir).resolve())
    repo = pathlib.Path(a.repo or a.planning_dir).resolve()
    path = marker_path(repo, planning)
    if path is None:
        print(f"--activate: {a.repo or a.planning_dir} is not inside a git repository")
        return 2
    # A route activated before markers were per planning dir moves to its own.
    legacy = marker_path(repo)
    assert legacy is not None  # the same repository path just resolved
    old = load_json(path)
    if not old and load_json(legacy).get("planning_dir") == planning:
        old = load_json(legacy)
        legacy.unlink()
    # A re-activation that leaves out the route's repo, main branch, spec dir or (in the same
    # phase) sections keeps them: execution.md's `--activate --sins on` names none of them.
    prev = parser().parse_args(old["args"]) if old.get("args") else None
    same_phase = prev is not None and prev.phase == a.phase
    repo_arg = a.repo or (prev and prev.repo)
    sections = a.sections or (prev.sections if prev and same_phase else None)
    spec_dir = a.spec_dir or (prev and prev.spec_dir)
    args = [
        planning,
        "--phase",
        a.phase,
        "--main",
        a.main or (prev and prev.main) or main,
    ]
    if repo_arg:
        args += ["--repo", str(pathlib.Path(repo_arg).resolve())]
    if sections:
        args += ["--sections", sections]
    if spec_dir:
        args += ["--spec-dir", str(pathlib.Path(spec_dir).resolve())]
    marker = {"args": args, "planning_dir": planning, "activated": time.time()}
    # A re-activation keeps the phase's rung (execution.md's `--activate --sins on` names none),
    # budgets --budget recorded here before they moved to the planning dir, and the CI harness, a
    # fact about the repository's CI rather than the round.
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
    # The decision ledger (decision_check.py) binds a phase whose index did not exist when the
    # phase was first activated: an index written before the check keeps its old format.
    ledger = dict(old.get("ledger") or {})
    # A route ended (its marker deleted) and begun again: its sessions' registry entries keep it.
    kept = {}
    for f in REGISTRY.glob("*.json"):
        entry = load_json(f)
        if entry.get("planning_dir") == planning:
            for phase, bound in (entry.get("ledger") or {}).items():
                kept[phase] = kept.get(phase, False) or bound
    for phase, bound in kept.items():
        ledger.setdefault(phase, bound)
    index = pathlib.Path(planning) / "decisions" / f"phase{a.phase}" / "00-index.md"
    if a.phase not in ledger:
        # so does a review round's own index (`phase<P>/<round>/00-index.md`); a round written
        # later is bound, absent from the ledger
        for r in sorted(index.parent.glob("*/00-index.md")):
            ledger[f"{a.phase}/{r.parent.name}"] = False
        # the checks the phase is bound under: one added later never holds an index written
        # before it
        ledger[f"{a.phase}#checks"] = LEDGER_CHECKS
    ledger.setdefault(a.phase, not index.exists())
    marker["ledger"] = ledger
    path.write_text(json.dumps(marker) + "\n")
    print(f"route active: {path}")
    import push_guard  # only --activate needs it: the hook runs on every tool call

    print(push_guard.install_hook(repo))
    if "ci_harness" in marker:
        print(
            f"CI harness {harness}: push_guard.py also holds every push until a gate log with "
            f"`harness={harness}` passed on that commit (`--ci-harness none` clears it)"
        )
    if "sins" in marker:
        print(
            "sins on: push_guard.py also holds every push until a seven-sins verdict covers it "
            "(references/sins/lead.md; `--sins off` clears it)"
        )
    unanswered = "ci_harness" not in marker and "ci_none" not in marker
    if foreign := unanswered and repo_arg and foreign_runners(repo_arg):
        print(
            f"CI runs on {', '.join(foreign)}, which this host is not: the local full gate "
            "never runs what it tests. Activate again with --ci-harness <label> (each push then "
            "needs that suite's gate log, run where it can run: execution.md) or --ci-harness "
            "none when the local gate covers it (F90)"
        )
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        print(
            "--activate: CLAUDE_CODE_SESSION_ID is unset, so no session is registered and the "
            "state hook stays silent; push_guard.py is active"
        )
        return 1
    REGISTRY.mkdir(parents=True, exist_ok=True)
    entry_path = REGISTRY / f"{session}.json"
    old = load_json(entry_path)
    entry = {
        "marker": str(path),
        "planning_dir": planning,
        "activated": time.time(),
        "ledger": ledger,
    }
    # When this session last read the skill's files: a re-activation is no re-read.
    entry["skill_seen"] = old.get("skill_seen", old.get("activated", time.time()))
    entry_path.write_text(json.dumps(entry) + "\n")
    print(f"hooks registered for session {session}")
    # The hooks read the transcript and let a call through on a shape they cannot find: said
    # here, a format change is a line at activation rather than gates silently off.
    if line := checked(shape_line, session):
        print(line)
    # Activity = the newest write to any registered lead's transcript for that route; a route
    # restarted in a new session has two registry entries.
    latest = {}
    for sid, e in routes(session):
        if e["marker"] == str(path):
            continue
        seen = [p.stat().st_mtime for p in session_transcripts(sid)]
        seen = seen or [pathlib.Path(e["marker"]).stat().st_mtime]
        latest[e["planning_dir"]] = max(max(seen), latest.get(e["planning_dir"], 0))
    for planning_dir, t in latest.items():
        print(
            f"other route on this account: {planning_dir} (lead last active "
            f"{ago(time.time() - t)} ago) — it shares the weekly and second-model quota"
        )
    return 1 if foreign else 0
