"""What the parts of route_state.py share: the route's marker and the session registry, git, the
arguments a marker records, and the hook's output."""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess

MARKER = "dsp-route.json"
REGISTRY = pathlib.Path.home() / ".claude" / "dsp-routes"
# The entry point the messages name: hooks.json and the docs call it, never this package.
SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "route_state.py"
SKILL_DIR = SCRIPT.parents[1]
SKILL = SKILL_DIR / "SKILL.md"
# How an agent's return opens the lead's turn as a prompt. A teammate's message does not fire
# UserPromptSubmit (measured, Claude Code 2.1.296-2.1.299); the lead's next tool call reports it.
RETURNS = ("<agent-message", "<teammate-message", "<task-notification")
# Stage 5 agents are named `exec-<plan-id>-<group>` (execution.md); an agent's id is `a<name>-<hash>`.
EXEC = "exec-"
SLACK = 1.25
# the decision_check version a phase is bound under; 2 added the decisions table's Serves column
LEDGER_CHECKS = 2
PLAN_ID = re.compile(r"p\d+-\d+[a-z]?(?=-|$)")
# The route's budgets live in its planning dir, which a hand-over carries: kept per lead session in
# the marker, both were asked again after a lead moved to another machine (F74).
BUDGETS = "route-budget.json"


def budgets(planning_dir, marker, phase):
    """The phase's recorded budgets, oldest first: the planning dir's, else a marker's from
    before they moved there."""
    found = load_json(pathlib.Path(planning_dir) / BUDGETS).get(
        "budgets"
    ) or marker.get("budgets", [])
    return [b for b in found if b.get("phase") == phase]


def save_budget(planning_dir, marker, record):
    """Append or update (by its `at`) one budget record in the planning dir's file."""
    path = pathlib.Path(planning_dir) / BUDGETS
    found = load_json(path).get("budgets") or list(marker.get("budgets", []))
    found = [b for b in found if b.get("at") != record["at"]] + [record]
    found.sort(key=lambda b: b.get("at") or "")
    path.write_text(json.dumps({"budgets": found}, indent=1) + "\n")


def ago(seconds):
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def git(repo, *args):
    r = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    return r.returncode, r.stdout.strip()


def parser(description=None):
    """The route's arguments; route_state.py passes its docstring, the --help leads read."""
    ap = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("planning_dir")
    ap.add_argument("--phase", required=True)
    ap.add_argument("--repo")
    ap.add_argument(
        "--main", help="the main branch (default: the repository's default)"
    )
    ap.add_argument(
        "--sections", help="the phase's spec sections, e.g. 38-48, or 38- for §38 on"
    )
    ap.add_argument(
        "--spec-dir", help="where the spec sections live (default <planning-dir>/spec)"
    )
    ap.add_argument("--all", action="store_true")
    ap.add_argument(
        "--rung",
        choices=("S", "M", "L"),
        help="with --activate: the route's rung",
    )
    ap.add_argument(
        "--sins",
        choices=("on", "off"),
        help="with --activate: on — push_guard.py holds each push until a seven-sins verdict "
        "covers it: at rung L for the phase's last push, at any rung when the user asked for "
        "the review. Kept across re-activations; `off` clears it",
    )
    ap.add_argument(
        "--ci-harness",
        metavar="LABEL",
        help="with --activate: a suite CI runs that the local full gate does not (another "
        "database, container tests); push_guard.py then also requires a gate log with "
        "`harness=<LABEL>` for each pushed commit. Kept across re-activations; `none` clears it",
    )
    ap.add_argument(
        "--activate",
        action="store_true",
        help="also write these arguments to <git-common-dir>/dsp-route-<id>.json (one per "
        "planning dir) and register this session",
    )
    return ap


def marker_path(directory, planning=None):
    """The route's marker, one per planning dir (`planning`), else the old one per repository.

    Why: two routes in one repository shared one marker, so the second's --activate replaced the
    first's phase and budgets and the hold counted both routes' spend: three false holds in one
    lane (F93)."""
    rc, common = git(
        directory, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    if rc != 0 or not common:
        return None
    if planning is None:
        return pathlib.Path(common) / MARKER
    slug = hashlib.sha1(planning.encode()).hexdigest()[:10]
    return pathlib.Path(common) / f"dsp-route-{slug}.json"


def default_branch(repo):
    """origin's HEAD, else the main worktree's branch, else main or master, whichever exists."""
    rc, ref = git(
        repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
    )
    if rc == 0 and "/" in ref:
        return ref.split("/", 1)[1]
    rc, wt = git(repo, "worktree", "list", "--porcelain")
    for line in wt.split("\n\n")[0].splitlines():
        if line.startswith("branch refs/heads/"):
            return line.removeprefix("branch refs/heads/")
    # a detached main worktree
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")[0] == 0:
            return name
    return "main"


def routes(skip_session=None):
    """(session id, registry entry) of every registered session whose marker still exists."""
    out = []
    for f in sorted(REGISTRY.glob("*.json")):
        try:
            entry = json.loads(f.read_text())
        except ValueError:
            continue
        # A `<session>.waits.json` sidecar has no marker, and Path("") is "." (always exists).
        marker = entry.get("marker")
        if f.stem != skip_session and marker and pathlib.Path(marker).exists():
            out.append((f.stem, entry))
    return out


def load_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def checked(check, *args):
    """`check(*args)`, or None when it fails: a broken check never blocks the call, nor skips the
    checks after it — a ledger check that raised once let a dispatch past the budget hold."""
    try:
        return check(*args)
    except (Exception, SystemExit):  # noqa: BLE001
        return None


def deny(reason, decision="deny"):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": f"route_state.py (hook): {reason}",
                }
            }
        )
    )
    return 0


def emit(name, text):
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}
        )
    )
