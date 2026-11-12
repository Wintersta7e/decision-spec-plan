# SPDX-License-Identifier: MIT
"""What the parts of route_state.py share.

The route's marker and the session registry, git, the arguments a marker records, the
hook's output, and the narrowing of parsed JSON to typed values.
"""

import argparse
import contextlib
import contextvars
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Generator, Mapping
from typing import Literal, NotRequired, TypedDict, TypeVar, TypeVarTuple, cast

MARKER = "dsp-route.json"
REGISTRY = pathlib.Path.home() / ".claude" / "dsp-routes"
# The entry point the messages name: hooks.json and the docs call it, never this
# package.
SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "route_state.py"
SKILL_DIR = SCRIPT.parents[1]
SKILL = SKILL_DIR / "SKILL.md"
# How an agent's return opens the lead's turn as a prompt. A teammate's message does not
# fire UserPromptSubmit (measured, Claude Code 2.1.296-2.1.299); the lead's next tool
# call reports it.
RETURNS = ("<agent-message", "<teammate-message", "<task-notification")
# Stage 5 agents are named `exec-<plan-id>-<group>` (execution.md); an agent's id is
# `a<name>-<hash>`.
EXEC = "exec-"
SLACK = 1.25
# the decision_check version a phase is bound under; 2 added the decisions table's
# Serves column
LEDGER_CHECKS = 2
PLAN_ID = re.compile(r"p\d+-\d+[a-z]?(?=-|$)")
# The route's budgets live in its planning dir, which a hand-over carries: kept per lead
# session in the marker, both were asked again after a lead moved to another machine
# (F74).
BUDGETS = "route-budget.json"
# How long a reader waits before reading a missing marker once more: on drvfs a reader
# of an os.replace'd file saw it briefly missing (1 FileNotFoundError and 2 OSError in
# about 8,100 reads), and a missed read there splits a live run.
ABSENT_RETRY_S = 0.02

StrPath = str | os.PathLike[str]
T = TypeVar("T")
Ts = TypeVarTuple("Ts")


class Budget(TypedDict):
    """One record of the route's budget file, as `--budget` writes it."""

    label: str
    estimate: float
    phase: str
    at: str
    session: str
    groups: NotRequired[int]
    base: NotRequired[str]
    moved: NotRequired[list[str]]
    answered: NotRequired[str]


class PreviousRoute(TypedDict):
    """A route a session left, as its registry entry lists it."""

    marker: str
    planning_dir: str
    # None for an entry written before run ids
    run: str | None


class RegistryEntry(TypedDict):
    """A registered session's entry in REGISTRY, as `--activate` writes it."""

    marker: str
    planning_dir: str
    activated: float
    ledger: dict[str, int]
    skill_seen: NotRequired[float]
    # each skill file's text, as the session's last change check hashed it
    skill_digests: NotRequired[dict[str, str]]
    # the marker's run id and arguments when the session activated it
    run: NotRequired[str]
    args: NotRequired[list[str]]
    # the routes the session left, newest first
    previous: NotRequired[list[PreviousRoute]]


class RouteArgs(argparse.Namespace):
    """The route's arguments, as parser() parses them.

    One attribute per dest of parser() (`help` stores none). Each value is the option's
    default: argparse leaves a value the namespace already has until the option is
    given, and checks the required ones (planning_dir, --phase) itself.
    """

    planning_dir: str = ""
    phase: str = ""
    repo: str | None = None
    main: str | None = None
    sections: str | None = None
    spec_dir: str | None = None
    all: bool = False
    rung: Literal["S", "M", "L"] | None = None
    sins: Literal["on", "off"] | None = None
    ci_harness: str | None = None
    activate: bool = False


def parse_json(text: str | bytes) -> object:
    """Parse JSON text into an untyped value, for the caller to narrow."""
    return cast("object", json.loads(text))


def as_dict(value: object) -> dict[str, object] | None:
    """Return value as a JSON object, or None when it is none."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[object] | None:
    """Return value as a JSON array, or None when it is none."""
    return cast("list[object]", value) if isinstance(value, list) else None


def _budget_list(value: object) -> list[Budget]:
    """Return the budget records of a JSON array, an empty list for anything else."""
    return [cast("Budget", b) for b in as_list(value) or [] if as_dict(b) is not None]


def budgets(
    planning_dir: StrPath, marker: Mapping[str, object], phase: str
) -> list[Budget]:
    """Return the phase's recorded budgets, oldest first.

    The planning dir's, else a marker's from before they moved there.
    """
    found = _budget_list(
        load_json(pathlib.Path(planning_dir) / BUDGETS).get("budgets")
    ) or _budget_list(marker.get("budgets", []))
    return [b for b in found if b.get("phase") == phase]


def save_budget(
    planning_dir: StrPath, marker: Mapping[str, object], record: Budget
) -> None:
    """Append or update (by its `at`) one budget record in the planning dir's file."""
    path = pathlib.Path(planning_dir) / BUDGETS
    found = _budget_list(load_json(path).get("budgets")) or _budget_list(
        marker.get("budgets", [])
    )
    found = [b for b in found if b.get("at") != record["at"]] + [record]
    found.sort(key=lambda b: b.get("at") or "")
    _ = path.write_text(json.dumps({"budgets": found}, indent=1) + "\n")


def is_return(prompt: object) -> bool:
    """Return whether a prompt is an agent's return: its head holds one of RETURNS."""
    return any(t in str(prompt or "").strip()[:500] for t in RETURNS)


def ago(seconds: float) -> str:
    """Return a duration as its largest whole unit: `3d`, `2h`, `5m`, `40s`."""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


GIT_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "GIT_DEADLINE", default=None
)
"""The `time.monotonic()` by which the context's git calls must end; None: no bound."""


class GitDeadlineError(TimeoutError):
    """A git call reached the deadline `git_deadline` set: not started, or stopped."""


@contextlib.contextmanager
def git_deadline(seconds: float) -> Generator[None, None, None]:
    """Bound every `git()` call in the block to end within seconds from now."""
    token = GIT_DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        GIT_DEADLINE.reset(token)


def git(repo: StrPath, *args: str, stdin: str | None = None) -> tuple[int, str]:
    """Run git in repo, fed stdin; its exit code and its stripped stdout.

    Under `git_deadline`, a call raises `GitDeadlineError` without spawning git once
    the deadline has passed, and stops a git that outlives it.
    """
    deadline = GIT_DEADLINE.get()
    timeout = None
    if deadline is not None:
        timeout = deadline - time.monotonic()
        if timeout <= 0:
            msg = f"git {' '.join(args)}: deadline passed"
            raise GitDeadlineError(msg)
    try:
        r = subprocess.run(
            [shutil.which("git") or "git", "-C", str(repo), *args],
            input=stdin,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"git {' '.join(args)}: stopped at the deadline"
        raise GitDeadlineError(msg) from e
    return r.returncode, r.stdout.strip()


def parser(description: str | None = None) -> argparse.ArgumentParser:
    """Return the route's arguments; route_state.py passes its docstring as --help."""
    ap = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    _ = ap.add_argument("planning_dir")
    _ = ap.add_argument("--phase", required=True)
    _ = ap.add_argument("--repo")
    _ = ap.add_argument(
        "--main", help="the main branch (default: the repository's default)"
    )
    _ = ap.add_argument(
        "--sections", help="the phase's spec sections, e.g. 38-48, or 38- for §38 on"
    )
    _ = ap.add_argument(
        "--spec-dir", help="where the spec sections live (default <planning-dir>/spec)"
    )
    _ = ap.add_argument("--all", action="store_true")
    _ = ap.add_argument(
        "--rung",
        choices=("S", "M", "L"),
        help="with --activate: the route's rung",
    )
    _ = ap.add_argument(
        "--sins",
        choices=("on", "off"),
        help="with --activate: on — push_guard.py holds each push until a seven-sins "
        "verdict covers it: at rung L for the phase's last push, at any rung when the "
        "user asked for the review. Kept across re-activations; `off` clears it",
    )
    _ = ap.add_argument(
        "--ci-harness",
        metavar="LABEL",
        help="with --activate: a suite CI runs that the local full gate does not "
        "(another database, container tests); push_guard.py then also requires a gate "
        "log with `harness=<LABEL>` for each pushed commit. Kept across "
        "re-activations; `none` clears it",
    )
    _ = ap.add_argument(
        "--activate",
        action="store_true",
        help="also write these arguments to <git-common-dir>/dsp-route-<id>.json (one "
        "per planning dir) and register this session",
    )
    return ap


def route_args(marker: Mapping[str, object]) -> RouteArgs:
    """Return the route's arguments a marker records; KeyError without any."""
    args = as_list(marker["args"]) or []
    return parser().parse_args([str(a) for a in args], namespace=RouteArgs())


def marker_path(directory: StrPath, planning: str | None = None) -> pathlib.Path | None:
    """Return the route's marker, one per planning dir, else the old one per repository.

    Why: two routes in one repository shared one marker, so the second's --activate
    replaced the first's phase and budgets and the hold counted both routes' spend:
    three false holds in one lane (F93).
    """
    rc, common = git(
        directory, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    if rc != 0 or not common:
        return None
    if planning is None:
        return pathlib.Path(common) / MARKER
    slug = hashlib.sha1(planning.encode(), usedforsecurity=False).hexdigest()[:10]
    return pathlib.Path(common) / f"dsp-route-{slug}.json"


def default_branch(repo: StrPath) -> str:
    """Return origin's HEAD, else the main worktree's branch, else main or master."""
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


def routes(skip_session: str | None = None) -> list[tuple[str, RegistryEntry]]:
    """Return (session id, registry entry) of each registered session with a marker."""
    out: list[tuple[str, RegistryEntry]] = []
    for f in sorted(REGISTRY.glob("*.json")):
        try:
            parsed = parse_json(f.read_text())
        except ValueError:
            continue
        entry = as_dict(parsed)
        if entry is None:
            continue
        # A `<session>.waits.json` sidecar has no marker, and Path("") is "." (always
        # exists).
        marker = entry.get("marker")
        if f.stem != skip_session and marker and pathlib.Path(str(marker)).exists():
            out.append((f.stem, cast("RegistryEntry", parsed)))
    return out


def load_json(path: pathlib.Path) -> dict[str, object]:
    """Return the JSON object in a file, or an empty one when it holds none."""
    try:
        return as_dict(parse_json(path.read_text())) or {}
    except (OSError, ValueError):
        return {}


def write_atomic(path: pathlib.Path, text: str) -> None:
    """Replace path's contents with text, so a reader never sees a torn file.

    The text goes to `<name>.<pid>.tmp` beside path, which then replaces path; a failed
    write leaves path untouched and removes the temp file. It raises what the write
    raises.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        _ = tmp.write_text(text)
        _ = tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def checked(check: Callable[[*Ts], T], *args: *Ts) -> T | None:
    """Return `check(*args)`, or None when it fails.

    A broken check never blocks the call, nor skips the checks after it — a ledger check
    that raised once let a dispatch past the budget hold.
    """
    try:
        return check(*args)
    except (Exception, SystemExit):  # noqa: BLE001
        return None


def deny(reason: str, decision: str = "deny") -> int:
    """Print the PreToolUse hook output that denies (or asks about) the call; 0."""
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


def emit(name: str, text: str) -> None:
    """Print the hook output that adds text to the context of hook event `name`."""
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}
        )
    )
