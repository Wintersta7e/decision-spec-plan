#!/usr/bin/env python3
"""One screen of a decision-spec-plan round's state, for the lead's in-flight block.

Reports, never rules. Expected files come from the round's own indexes: the decision index's
`D<n>` rows and the plan index's plan ids; one not written yet is listed as pending. For each
file that exists it flags the ends a lead must not misread (F38): empty, an unpaired code fence,
written in the last two minutes. With --repo it also reads git: each lane checkpoint's
`Final SHA:` line, whether the main branch contains it (by ancestry, or by patch for a rebased
lane), and a lane branch that moved past a merged checkpoint (F41); each lane not merged gets a
line with its commits since the main branch, the gate log at its SHA, their trailers and what its
worktree left uncommitted — the check of a group's return (F80). A lane is any
`lanes/*-checkpoint.md` but another phase's `p<Q>-…`. Every gate log's last `exit=`
line is reported; a log without one is still running or was piped. A HANDOFF.md over 40 KB and an
unmerged lane's checkpoint over 35 lines are flagged (F76), and its rulings file over 12 KB (F67).
With --repo, the decision index's `> **Base**: `<ref>` at `<sha>`` and `> **Assumes**: `<ref>` at
`<sha>`` lines are checked against the refs as of the last fetch: a base that moved, an assumed
ref that moved or merged into the base, a ref gone (F91).

Usage:
    route_state.py <planning-dir> --phase P [--repo DIR] [--main BRANCH] [--sections 38-48 | 38-]
        [--spec-dir DIR] [--all] [--activate [--rung S|M|L] [--ci-harness LABEL] [--sins on|off]]
    route_state.py --budget LABEL --estimate M --groups N

--main defaults to the repository's default branch. --sections `38-` counts every section from
§38 on (a phase whose last section is not known yet). --all lists every file with its size, age
and last line. Exit 0 on a report, 2 when the planning dir does not exist.

--activate also writes the arguments to <git-common-dir>/dsp-route-<id>.json, one per planning dir,
which marks the repository as running that route (push_guard.py then holds pushes to gated commits;
two routes in one repository keep separate phases, budgets and spend, F93), and registers this session
in ~/.claude/dsp-routes/<session-id>.json, which `route_state.py --hook` reads: after the lead's
tool calls (PostToolUse, at most every 20 s) and on an agent's return as a prompt
(UserPromptSubmit) it puts what changed in the report into the lead's context, with the skill's
files changed since the session read them (F78), and after a compaction or a resume
(SessionStart) the whole report and what to re-read. Re-run with --activate at each phase and in
each new lead session; delete the marker to end the route. `--ci-harness <label>` names a suite CI
runs that the local full gate does not; push_guard.py then also wants, per pushed commit, a gate
log whose first 20 lines hold `harness=<label>` (F90).

--budget records a Stage 5 wave's estimate in M units (costs.md) and the `exec-` agents it covers
in the marker (execution.md). Registered for PreToolUse (Agent|Bash), the hook then holds the
lead's dispatch of an `exec-` agent until the phase has a budget recorded in this session and the
user has answered after it here — or answered an AskUserQuestion earlier in the turn that records
it, so ask, then record, and the one answer is enough (F93) — and again once the dispatches since it pass 125% of its agents or the spend since it 125% of
its estimate (F74). A session whose transcript holds no prompt the user typed (headless
`claude -p`) has no answer to wait for, so the hold lets its dispatches through: record the budget
anyway and report it at the end. Inside an `exec-` agent it tells a group past 200k tokens of context to finish
its task and return (F75), and holds a `git commit` while its own lane's rulings file changed after
the agent last read it (F59). In a session with no active route it holds
a `dsp-deep` or `dsp-mechanical` dispatch until the route is activated (F79). On a route activated
with `--rung S` it refuses the lead's dispatch of an agent whose name or description says harvest:
at S the lead harvests itself (F87). While a route is
active it asks the user before the lead's `gh pr close|merge`, `gh issue close|delete`, `gh release
create|delete|edit|upload`, `gh repo delete|archive|rename`, a `gh api` write, `--delete-branch`
or a remote branch delete by `git push`, and refuses them inside a route agent (F81). A check
that fails lets the call through. Registered for SubagentStop and TeammateIdle, it sends an agent
that ends its turn while its own background shell or monitor runs back to wait on it, twice at
most per job: nothing wakes it when the job ends (F92). It holds the lead's `exec-` dispatch while
`decision_check.py` fails on the phase — one whose index did not exist at its first --activate —
and a `verify-` agent whose prompt is not the file `decision_check.py --verifier` wrote.

Registration: the plugin's `hooks/hooks.json` runs `route_state.py --hook` under SessionStart
matcher `compact|resume`, PostToolUse matcher `*`, UserPromptSubmit, PreToolUse matcher
`Agent|Bash`, SubagentStop, TeammateIdle.
"""

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import time

import shell_cmd

MARKER = "dsp-route.json"
REGISTRY = pathlib.Path.home() / ".claude" / "dsp-routes"
PROJECTS = pathlib.Path.home() / ".claude" / "projects"
SKILL_DIR = pathlib.Path(__file__).resolve().parents[1]
SKILL = SKILL_DIR / "SKILL.md"
# How an agent's return opens the lead's turn as a prompt. A teammate's message does not fire
# UserPromptSubmit (measured, Claude Code 2.1.296-2.1.299); the lead's next tool call reports it.
RETURNS = ("<agent-message", "<teammate-message", "<task-notification")
FRESH_S = 120
THROTTLE_S = 20
# Stage 5 agents are named `exec-<plan-id>-<group>` (execution.md); an agent's id is `a<name>-<hash>`.
EXEC = "exec-"
# The agent types only the route dispatches (agents/dsp-*.md), bare or plugin-qualified.
ROUTE_AGENTS = ("dsp-deep", "dsp-mechanical")
SLACK = 1.25
JOB_WAITS = 2
CONTEXT_STOP = 200_000
HANDOFF_MAX = 40_000
CHECKPOINT_MAX = 35
RULINGS_MAX = 12_000
# The tools whose input naming a rulings file counts as the agent reading it.
READS = ("Read", "Bash", "Grep")
# Git commands that make a commit: one made before the agent re-reads a ruling skips it (F59).
COMMITTING = {"commit", "merge", "cherry-pick", "revert", "am", "pull", "rebase"}
# Outward actions on the hosted repository: the lead asks the user each time and a route agent
# never runs one (F81). Each noun and verb may have any options between them, as gh accepts. A
# false match only asks.
GH_ACTIONS = {
    "pr": {"close", "merge"},
    "issue": {"close", "delete"},
    "release": {"create", "delete", "edit", "upload"},
    "repo": {"delete", "archive", "rename"},
}


def bash_commands(command):
    """Each `git` and `gh` command the Bash command runs, from that word on (`sudo git commit`),
    read as bash reads it (shell_cmd.py): regexes over the text missed wrapped and quoted forms and
    backtracked for 36 s on a long line. None when a part cannot be read — a script or stdin fed
    to a shell, a computed `bash -c` or `eval`, a computed command name or git subcommand — or
    the reader fails on it (nesting too deep): the caller then reads the bare text."""
    try:
        found = shell_cmd.events(command)
    except Exception:  # noqa: BLE001 — unreadable text falls back to the text check
        return None
    out = []
    for kind, c in found:
        if kind == "opaque" or (kind == "cmd" and c.words and not c.words[0].static):
            return None
        for i, w in enumerate(c.argv if kind == "cmd" else []):
            if os.path.basename(w) in ("gh", "git"):
                cmd = shell_cmd.Cmd([], c.words[i:])
                if (g := shell_cmd.git_args(cmd)) and g[1] is None:
                    return None
                out.append(cmd)
    return out


def makes_commit(command):
    cmds = bash_commands(command)
    if cmds is None:
        return bool(re.search(rf"\b({'|'.join(COMMITTING)})\b", command))
    return any((g := shell_cmd.git_args(c)) and g[1] in COMMITTING for c in cmds)


def outward_cmd(cmd):
    """Whether cmd, a command from a `gh` or `git` word on, is an outward action."""
    argv = cmd.argv
    if "--delete-branch" in argv:
        return True
    if cmd.name == "gh":
        rest = argv[1:]
        if any(
            w in GH_ACTIONS and GH_ACTIONS[w] & set(rest[i + 1 :])
            for i, w in enumerate(rest)
        ):
            return True
        if "api" not in rest:
            return False
        # `gh api` that writes: a method other than GET, or a field (which makes it a POST)
        after = rest[rest.index("api") + 1 :] + [""]
        for i, w in enumerate(after[:-1]):
            if m := re.fullmatch(r"(?:-X|--method)=?(.*)", w):
                if (m[1] or after[i + 1]).upper() in ("POST", "PATCH", "PUT", "DELETE"):
                    return True
            elif re.match(r"-[fF]|--(?:field|raw-field|input)\b", w):
                return True
        return False
    # remote refs deleted by `git push`: --delete, -d (alone or grouped), --prune, --mirror, or a
    # refspec with no source (`:<ref>`, `+:<ref>`)
    g = shell_cmd.git_args(cmd)
    return (
        bool(g)
        and g[1] == "push"
        and any(
            w in ("--delete", "--prune", "--mirror")
            or re.fullmatch(r"-[a-zA-Z]*d[a-zA-Z]*|\+?:.+", w)
            for w in (a.text for a in g[2])
        )
    )


def outward_in(command):
    cmds = bash_commands(command)
    if cmds is None:
        return bool(re.search(r"\b(gh|push)\b", command))
    return any(outward_cmd(c) for c in cmds)


PLAN_ID = re.compile(r"p\d+-\d+[a-z]?(?=-|$)")
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
FINAL_SHA = re.compile(
    r"^\W*Final SHA:\W*([0-9a-f]{7,40})\b", re.MULTILINE | re.IGNORECASE
)
MERGED = re.compile(
    r"^\W*Merged\s+\W*([\w.-]+?)\W+([0-9a-f]{7,40})\W+(?:→|->)\W*([0-9a-f]{7,40})\b",
    re.MULTILINE,
)
# The decision index's header: `> **Base**: `main` at `<sha>`` and one `> **Assumes**: `<ref>` at
# `<sha>`` per unmerged branch the round builds on (templates.md §1).
BASE = re.compile(
    r"^>?\s*\*\*(Base|Assumes)\*\*:\s*`([^`]+)`\s+at\s+`([0-9a-f]{7,40})`", re.MULTILINE
)


def describe(path):
    """(problems, size, age, last line) of one artefact."""
    text = path.read_text(errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    age = time.time() - path.stat().st_mtime
    problems = []
    if not lines:
        problems.append("empty")
    if sum(1 for ln in text.split("\n") if ln.lstrip().startswith("```")) % 2:
        problems.append("unpaired ``` fence")
    if age < FRESH_S:
        problems.append(f"written {int(age)}s ago — still being written?")
    return problems, len(text.encode()), age, (lines[-1].strip() if lines else "")


def ago(seconds):
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def pending(names):
    names = list(names)
    return " ".join(names[:8]) + (f" +{len(names) - 8}" if len(names) > 8 else "")


def git(repo, *args):
    r = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    return r.returncode, r.stdout.strip()


class Report:
    def __init__(self, show_all, fresh=True):
        self.show_all, self.fresh, self.lines, self.flags = show_all, fresh, [], []

    def file(self, path, base):
        problems, size, age, last = describe(path)
        if not self.fresh:
            problems = [p for p in problems if not p.startswith("written ")]
        rel = path.relative_to(base) if path.is_relative_to(base) else path
        for p in problems:
            self.flags.append(f"{p:<34} {rel}  ends: {last[:70]!r}")
        if self.show_all:
            self.lines.append(
                f"    {rel!s:<48} {size / 1024:6.1f} KB {ago(age):>5}  {last[:60]!r}"
            )
        return problems

    def flag(self, text):
        self.flags.append(text)


def parser():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
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
        help=f"also write these arguments to <git-common-dir>/{MARKER} and register this session",
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
    old = load_json(path)
    if not old and load_json(legacy).get("planning_dir") == planning:
        old = load_json(legacy)
        legacy.unlink()
    args = [planning, "--phase", a.phase, "--main", main]
    if a.repo:
        args += ["--repo", str(pathlib.Path(a.repo).resolve())]
    if a.sections:
        args += ["--sections", a.sections]
    if a.spec_dir:
        args += ["--spec-dir", str(pathlib.Path(a.spec_dir).resolve())]
    marker = {"args": args, "planning_dir": planning, "activated": time.time()}
    # A re-activation keeps the phase's rung (execution.md's `--activate --sins on` names none),
    # the waves' recorded budgets (--budget) and the CI harness, a fact about the repository's CI
    # rather than the round.
    same_phase = old.get("args") and parser().parse_args(old["args"]).phase == a.phase
    if rung := a.rung or (old.get("rung") if same_phase else None):
        marker["rung"] = rung
    if budgets := old.get("budgets"):
        marker["budgets"] = budgets
    harness = a.ci_harness or old.get("ci_harness")
    if harness and harness != "none":
        marker["ci_harness"] = harness
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
    ledger.setdefault(a.phase, not index.exists())
    marker["ledger"] = ledger
    path.write_text(json.dumps(marker) + "\n")
    print(f"route active: {path}")
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
    # Activity = the newest write to any registered lead's transcript for that route; a route
    # restarted in a new session has two registry entries.
    latest = {}
    for sid, e in routes(session):
        if e["marker"] == str(path):
            continue
        seen = [p.stat().st_mtime for p in PROJECTS.glob(f"*/{sid}.jsonl")]
        seen = seen or [pathlib.Path(e["marker"]).stat().st_mtime]
        latest[e["planning_dir"]] = max(max(seen), latest.get(e["planning_dir"], 0))
    for planning_dir, t in latest.items():
        print(
            f"other route on this account: {planning_dir} (lead last active "
            f"{ago(time.time() - t)} ago) — it shares the weekly and second-model quota"
        )
    return 0


def budget(argv):
    """--budget: append a wave's estimate to the marker of this session's route."""
    ap = argparse.ArgumentParser(
        prog="route_state.py --budget",
        description="Record a Stage 5 wave's estimate (execution.md).",
    )
    ap.add_argument("--budget", required=True, metavar="LABEL", help="the wave")
    ap.add_argument(
        "--estimate", type=float, required=True, help="M units, priced per costs.md"
    )
    ap.add_argument(
        "--groups",
        type=int,
        required=True,
        help="the exec- agents it covers: task groups, fix groups, the integrator",
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
    phase = parser().parse_args(marker["args"]).phase
    record = {
        "label": a.budget,
        "estimate": a.estimate,
        "groups": a.groups,
        "phase": phase,
        "at": now(),
        "session": session,
    }
    if answered := answered_this_turn(session, a.estimate):
        record["answered"] = answered
    marker.setdefault("budgets", []).append(record)
    path.write_text(json.dumps(marker) + "\n")
    print(
        f"budget recorded: {a.budget} — {a.estimate:g}M, {a.groups} exec- agents, phase "
        f"{phase}, at {record['at']}"
    )
    then = (
        f"again past {a.estimate * SLACK:.3g}M spent or {int(a.groups * SLACK)} exec- "
        "dispatches from now."
    )
    if answered:
        print(
            f"The user answered your question at {answered}, earlier in this turn: that answer "
            f"stands for this figure, so the hook lets exec- dispatches through, and holds them "
            + then
        )
    else:
        print(
            "Tell the user this figure and wait for their answer: the hook holds every exec- "
            "dispatch until they answer, and " + then
        )
    return 0


def answered_this_turn(session, estimate):
    """When the user answered an AskUserQuestion in the lead's current turn that names the
    figure (`<estimate>M`), else None.

    Why: a lead that asked "raise the budget to 45M?" and recorded it after the answer was held
    for a second answer, and that question sat 1 h 52 min while finished groups waited (F93)."""
    answered = None
    for path in PROJECTS.glob(f"*/{session}.jsonl"):
        for r in read_records(path):
            message = r.get("message")
            result = r.get("toolUseResult")
            if r.get("type") == "assistant" and isinstance(message, dict):
                if message.get("stop_reason") == "end_turn":
                    answered = None
            elif isinstance(result, dict) and "answers" in result:
                figures = re.findall(r"(\d+(?:\.\d+)?)\s*M\b", json.dumps(result))
                if any(abs(float(f) - estimate) < 1e-9 for f in figures):
                    answered = r.get("timestamp")
    return answered


def now():
    """UTC in the transcripts' format, so the two compare as strings."""
    stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


def epoch(stamp):
    try:
        return datetime.datetime.fromisoformat(stamp).timestamp()
    except (AttributeError, ValueError):
        return None


def read_records(path):
    """Each JSON object of a transcript."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def tool_uses(record, kind="tool_use"):
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == kind]


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


def leads(event, marker):
    """The route's lead transcripts: this session's and any other session registered to it."""
    found = []
    own = pathlib.Path(event.get("transcript_path") or "")
    if own.suffix == ".jsonl" and own.is_file():
        found.append(own.resolve())
    for sid, e in routes():
        if e.get("marker") == str(marker):
            found += [p.resolve() for p in PROJECTS.glob(f"*/{sid}.jsonl")]
    return list(dict.fromkeys(found))


def since_budget(paths, since, current, own):
    """(the user answered in this session's transcript `own`, other `exec-` dispatches in all of
    these transcripts) from `since` on. An answer in another lead session never counts (F74)."""
    answered = ever = False
    sent, refused = set(), set()
    for path in paths:
        for r in read_records(path):
            is_human = path == own and r.get("type") != "assistant" and human(r)
            ever = ever or is_human
            if (r.get("timestamp") or "") < since:
                continue
            answered = answered or is_human
            for block in tool_uses(r):
                name = str((block.get("input") or {}).get("name") or "")
                if block.get("name") == "Agent" and name.startswith(EXEC):
                    sent.add(block.get("id"))
            # A dispatch the hook or the user refused gets an error result and starts no agent: a
            # wave of one was held at its only dispatch after one early refusal.
            for block in tool_uses(r, "tool_result"):
                if block.get("is_error"):
                    refused.add(block.get("tool_use_id"))
    sent -= refused
    sent.discard(current)
    # No prompt of the user's anywhere means the transcript format changed: never hold on it.
    return answered or not ever, len(sent)


def spend(paths, since):
    """Units these leads, their agents and the hook sessions beside them spent from `since` on."""
    import usage_report

    total, projects = 0.0, set()
    for path in paths:
        lead, agents, sdk = usage_report.route_cost(path, since)
        total += lead["units"] + sum(a["units"] for a in agents)
        if path.parent not in projects:
            projects.add(path.parent)
            total += sum(s["units"] for s in sdk)
    return total


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


def outward(event, entry):
    """The outward action an active route's Bash command takes on the hosted repository, if any."""
    marker = entry.get("marker")
    if event.get("tool_name") != "Bash" or not (
        marker and pathlib.Path(marker).exists()
    ):
        return None
    command = str((event.get("tool_input") or {}).get("command") or "")
    return " ".join(command.split())[:120] if outward_in(command) else None


def unrouted(event, entry_path):
    """The lead dispatching a route agent (`dsp-deep`, `dsp-mechanical`) with no active route:
    the skill was never loaded or the route ended, and every hook is off (F79)."""
    if event.get("agent_id") or event.get("tool_name") != "Agent":
        return False
    kind = str((event.get("tool_input") or {}).get("subagent_type") or "")
    if kind.rpartition(":")[2] not in ROUTE_AGENTS:
        return False
    marker = load_json(entry_path).get("marker")
    return not (marker and pathlib.Path(marker).exists())


def s_harvester(event, entry):
    """The lead dispatching a harvester on a rung-S route, where it harvests itself (F87)."""
    if event.get("tool_name") != "Agent":
        return False
    dispatch = event.get("tool_input") or {}
    text = f"{dispatch.get('name') or ''} {dispatch.get('description') or ''}"
    rung = load_json(pathlib.Path(entry["marker"])).get("rung")
    return rung == "S" and "harvest" in text.lower()


def ledger_hold(event, entry):
    """Why the lead's `exec-` or `verify-` dispatch is held by the decision ledger, if it is."""
    import decision_check

    marker = json.loads(pathlib.Path(entry["marker"]).read_text())
    phase = parser().parse_args(marker["args"]).phase
    d = pathlib.Path(entry["planning_dir"]) / "decisions" / f"phase{phase}"
    tool_input = event.get("tool_input") or {}
    script = pathlib.Path(decision_check.__file__).resolve()
    if str(tool_input.get("name") or "").startswith("verify-"):
        prompt = str(tool_input.get("prompt") or "").strip()
        reviews = pathlib.Path(entry["planning_dir"]) / "reviews"
        files = [*d.glob("verify/*.prompt.md"), *reviews.glob("*/verify/*.prompt.md")]
        written = {p.read_text(errors="replace").strip() for p in files}
        if prompt not in written:
            return (
                "a verifier's prompt is the file `decision_check.py --verifier R<n> --sha "
                "<commit>` wrote, unchanged: the finding and the commit, with no SETTLED list, "
                f"rationale or reviewer name ({script}; failure-modes F86)."
            )
        return None
    if not (marker.get("ledger") or {}).get(phase) or not (d / "00-index.md").exists():
        return None
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = decision_check.main([str(d), "--rung", marker.get("rung") or "M"])
    if code == 1:
        return (
            f"the decision ledger fails `{script} {d}` — fix each line, then dispatch:\n"
            + out.getvalue().strip()
        )
    return None


def gate_dispatch(event, entry):
    """The lead dispatching an `exec-` agent: held until the wave's budget is recorded and
    answered, and once the wave runs more than 25% over it (execution.md, F74); an allowed one
    gets its ETA (F83)."""
    path = pathlib.Path(entry["marker"])
    marker = json.loads(path.read_text())
    phase = parser().parse_args(marker["args"]).phase
    budgets = [b for b in marker.get("budgets", []) if b.get("phase") == phase]
    record = (
        f'`python3 {pathlib.Path(__file__).resolve()} --budget "<wave>" --estimate <M> '
        "--groups <exec- agents>`"
    )
    if not budgets:
        return deny(
            f"phase {phase} has no Stage 5 budget. Price the wave per costs.md (its exec- "
            "agents × the task-group median, the lead per group, a seven-sins review at L's "
            f"phase end), record it with {record}, tell the user the figure and wait "
            "for their answer (execution.md)."
        )
    b = budgets[-1]
    paths = leads(event, path)
    own = pathlib.Path(event.get("transcript_path") or "").resolve()
    answered, sent = since_budget(paths, b["at"], event.get("tool_use_id"), own)
    head = (
        f"budget '{b['label']}' ({b['estimate']:g}M, {b['groups']} exec- agents, "
        f"recorded {b['at']})"
    )
    # Why: "read the handoff and proceed" in a new session once counted as the answer to the
    # previous session's figure, which this session never told the user.
    if b.get("session") != event.get("session_id"):
        return deny(
            f"{head} was recorded in another lead session. Price the remaining work, record it "
            f"from this session with {record}, tell the user the figure and wait for their "
            "answer (F74)."
        )
    if not (answered or b.get("answered")):
        return deny(
            f"{head}: the user has not answered since it was recorded. Tell them the "
            "figure and wait for their answer before dispatching."
        )
    over = (
        f"Record the remaining work's figure with {record}, tell the user what ran over "
        "and why, and wait for their answer (F74)."
    )
    if sent + 1 > int(b["groups"] * SLACK):
        return deny(
            f"{head}: this would be exec- dispatch {sent + 1} since — more than 25% over. "
            + over
        )
    used = spend(paths, b["at"])
    if used > b["estimate"] * 1e6 * SLACK:
        return deny(
            f"{head}: {used / 1e6:.1f}M spent since — more than 25% over. " + over
        )
    emit("PreToolUse", eta(paths, str((event.get("tool_input") or {}).get("name"))))
    return 0


def lane_of(name):
    found = PLAN_ID.search(name)
    return found and found.group(0)


def eta(paths, name):
    """The `exec-` dispatch `name`'s ETA: the median minutes of the route's finished agents of its
    kind — integrators (`exec-wave*`) or task groups — its lane's first (F83)."""
    wave = name.startswith(EXEC + "wave")
    kind = "integrator" if wave else "task group"
    spans = []
    for path in paths:
        for meta in (path.parent / path.stem / "subagents").glob("agent-*.meta.json"):
            agent = str(load_json(meta).get("name") or "")
            if not agent.startswith(EXEC) or agent.startswith(EXEC + "wave") != wave:
                continue
            first = last = None
            for r in read_records(
                meta.with_name(meta.name[: -len(".meta.json")] + ".jsonl")
            ):
                first = first or r.get("timestamp")
                message = r.get("message")
                if r.get("type") == "assistant" and isinstance(message, dict):
                    # Finished: its last turn ended with no tool call pending.
                    last = (
                        r.get("timestamp")
                        if message.get("stop_reason") == "end_turn"
                        else None
                    )
            if first and last:
                spans.append((lane_of(agent), (epoch(last) - epoch(first)) / 60))
    route = [m for _, m in spans]
    if not route:
        return (
            f"ETA {name}: none yet — no {kind} of this route has finished. Tell the user so with "
            "this dispatch (F83)."
        )
    lane = lane_of(name)
    mine = [m for own, m in spans if lane and own == lane]
    n = len(mine or route)
    finished = f"{n} finished {kind}{'' if n == 1 else 's'}"
    source = (
        f"lane {lane}'s {finished} (the route's {len(route)}: {statistics.median(route):.0f} min)"
        if mine
        else f"the route's {finished}"
    )
    return (
        f"ETA {name}: about {statistics.median(mine or route):.0f} min, the median of {source}. "
        "Tell the user with this dispatch: this ETA and, for a lane, this × its groups left (F83)."
    )


def notified(record):
    """The ids of the background jobs a task notification in this record reports ended: one with a
    `<status>` (a monitor's event in between has none)."""
    attachment = record.get("attachment")
    attachment = attachment if isinstance(attachment, dict) else {}
    origin = record.get("origin") or attachment.get("origin")
    if not (isinstance(origin, dict) and origin.get("kind") == "task-notification"):
        return set()
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    text = str(attachment.get("prompt") or "") + json.dumps(content)
    return {
        m.group(1)
        for block in re.findall(
            r"<task-notification>(.*?)</task-notification>", text, re.DOTALL
        )
        if "<status>" in block and (m := re.search(r"<task-id>(\w+)</task-id>", block))
    }


def own_jobs(event, session):
    """The background shells and monitors an agent ending its turn left running: (id, what, log).

    Only the jobs the agent's own transcript started count: SubagentStop's `background_tasks`
    lists every job of the session, a neighbour teammate's too — a plan author was sent back twice
    to wait on another's probe. A job listed there runs while its status says so. TeammateIdle
    lists none: a job runs until its task notification (one with a `<status>`) or the agent's
    TaskStop of it reaches the transcript, or its output file ends `[exited with code N]` or
    `[killed]` — a monitor writes no file until its first line of output.
    """
    transcript = agent_transcript(event, session, event.get("agent_id") or "")
    if transcript is None:
        return []
    calls, stops, ended, jobs, tasks = {}, {}, set(), [], None
    for r in read_records(transcript):
        ended |= notified(r)
        message = r.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            arg = c.get("input") or {}
            if c.get("type") == "tool_use" and c.get("name") in ("Bash", "Monitor"):
                calls[c.get("id")] = arg.get("command") or arg.get("description")
            elif c.get("type") == "tool_use" and c.get("name") == "TaskStop":
                stops[c.get("id")] = arg.get("task_id") or arg.get("shell_id")
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in stops:
                if not c.get("is_error"):
                    ended.add(str(stops[c["tool_use_id"]]))
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                text = json.dumps(c.get("content"))
                # The id Claude Code records with a result that started a job: an output that
                # quotes another job's start message (a file or transcript read back) starts none.
                job = r"\w+"
                if "toolUseResult" in r:
                    result = r["toolUseResult"]
                    if not isinstance(result, dict):
                        continue
                    own = result.get("backgroundTaskId") or result.get("taskId")
                    if not own:
                        continue
                    job = re.escape(str(own))
                # run_in_background, or a foreground command moved there at its timeout
                if m := re.search(
                    rf"(?:in background with ID: |moved to the background \(ID: )({job})\)?\. "
                    r"Output is being written to: (\S+?\.output)",
                    text,
                ):
                    tasks = pathlib.Path(m.group(2)).parent
                    jobs.append((m.group(1), calls[c["tool_use_id"]], m.group(2)))
                elif m := re.search(rf"Monitor started \(task ({job})", text):
                    jobs.append((m.group(1), calls[c["tool_use_id"]], None))
    if "background_tasks" in event:
        running = {
            str(t.get("id"))
            for t in event["background_tasks"] or []
            if t.get("type") in ("shell", "monitor") and t.get("status") == "running"
        }
        return [(j, what or "", log or "") for j, what, log in jobs if j in running]
    out = []
    for job, what, path in jobs:
        if job in ended:
            continue
        log = pathlib.Path(path) if path else None
        if log is None:
            # A monitor's output sits beside the shells', mostly in
            # /tmp/claude-<uid>/<project>/<session>/tasks — one team's sat under another id.
            if tasks is None:
                tasks = pathlib.Path(
                    f"/tmp/claude-{os.getuid()}/{transcript.parents[2].name}/{session}/tasks"
                )
            log = tasks / f"{job}.output"
        try:
            with log.open("rb") as fh:
                fh.seek(max(0, log.stat().st_size - 200))
                tail = fh.read().decode("utf-8", "replace").strip().splitlines()
        except OSError:
            tail = []
        if not (
            tail and re.fullmatch(r"\[(exited with code -?\d+|killed)\]", tail[-1])
        ):
            out.append((job, what or "", str(log)))
    return out


def own_wait(event, session):
    """Send an agent back to wait on its own running job, at most JOB_WAITS times a job (F92)."""
    agent = str(event.get("agent_id") or "")
    sent = REGISTRY / f"{session}.waits.json"
    counts = load_json(sent) if sent.exists() else {}
    jobs = [
        j
        for j in own_jobs(event, session)
        if counts.get(f"{agent}:{j[0]}", 0) < JOB_WAITS
    ]
    if not jobs:
        return 0
    for job in jobs:
        counts[f"{agent}:{job[0]}"] = counts.get(f"{agent}:{job[0]}", 0) + 1
    sent.write_text(json.dumps(counts))
    what = "; ".join(
        f"`{' '.join(w.split())[:160]}` ({j}{', output ' + log if log else ''})"
        for j, w, log in jobs
    )
    print(
        f"route_state.py (hook): your own background job is still running — {what} — and "
        "nothing wakes you when it ends: of 81 turns agents ended this way, none woke, and each "
        "sat until the lead noticed, the longest 6 h 44 min (F92). Wait for it in the foreground "
        "now: Bash `until grep -q '^exit=' <its log>; do sleep 20; done` with timeout 600000, "
        "repeated until it ends (a job with no such log: its output file ends `[exited with "
        "code N]`); then finish your task and return. If it already ended, carry on.",
        file=sys.stderr,
    )
    return 2


def agent_transcript(event, session, agent):
    name = f"agent-{agent}.jsonl"
    given = pathlib.Path(event.get("transcript_path") or "")
    candidates = [given] if given.name == name else []
    if given.suffix == ".jsonl":
        candidates.append(given.parent / given.stem / "subagents" / name)
    candidates += PROJECTS.glob(f"*/{session}/subagents/{name}")
    return next((p for p in candidates if p.is_file()), None)


def context(transcript):
    """Tokens of context of an agent's latest turn."""
    with open(transcript, "rb") as fh:
        fh.seek(max(0, transcript.stat().st_size - 262_144))
        lines = fh.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        message = r.get("message") if isinstance(r, dict) else None
        if (
            r.get("type") == "assistant"
            and isinstance(message, dict)
            and message.get("usage")
            and message.get("model") != "<synthetic>"
        ):
            usage = message["usage"]
            return sum(
                usage.get(k, 0) or 0
                for k in (
                    "input_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                )
            )
    return 0


def dispatch_text(transcript):
    """The prompt an agent was dispatched with: its transcript's first user record."""
    for r in read_records(transcript):
        if r.get("type") == "user":
            content = (r.get("message") or {}).get("content")
            if isinstance(content, list):
                content = " ".join(
                    str(b.get("text") or "") for b in content if isinstance(b, dict)
                )
            return str(content or "")
    return ""


def own_rulings(planning, name, dispatch):
    """The lane rulings files that are this `exec-` agent's: its name opens with the lane's name or
    plan id (`exec-p4-09-n` → `p4-09-ui-truth-rulings.md`), or its dispatch prompt names the file."""
    group = name.removeprefix(EXEC)
    own = []
    for f in sorted((planning / "lanes").glob("*-rulings.md")):
        lane = f.name.removesuffix("-rulings.md")
        ids = [lane] + ([m.group(0)] if (m := PLAN_ID.match(lane)) else [])
        if f.name in dispatch or any(
            group == i or group.startswith(i + "-") for i in ids
        ):
            own.append(f)
    return own


def unread_rulings(transcript, planning, name):
    """The agent's own rulings files that changed after its last read of them. Only its own: a
    listing of `lanes/` in its transcript once made every lane's file count as its (F59)."""
    files = own_rulings(planning, name, dispatch_text(transcript))
    last = {}
    for r in read_records(transcript) if files else ():
        # An api-request-blob record repeats an earlier tool_use with no timestamp; letting it
        # overwrite would erase the read the timestamped record already counted.
        stamp = epoch(r.get("timestamp") or "")
        if stamp is None:
            continue
        for block in tool_uses(r):
            said = json.dumps(block.get("input"))
            for f in files:
                if block.get("name") in READS and f.name in said:
                    last[f] = stamp
    return [f for f in files if last.get(f, 0) < f.stat().st_mtime]


def agent_pre(event, session, entry):
    """Inside an `exec-` agent: the context stop (F75) and a commit held for a ruling (F59)."""
    agent = event["agent_id"]
    transcript = agent_transcript(event, session, agent)
    if transcript is None:
        return 0
    name = load_json(transcript.with_name(transcript.stem + ".meta.json")).get("name")
    # An agent's id is `a<name>-<hash>` when the meta file lacks the name.
    name = str(name or re.sub(r"-[0-9a-f]{8,}$", "", agent.removeprefix("a")))
    if not name.startswith(EXEC):
        return 0
    command = str((event.get("tool_input") or {}).get("command") or "")
    if event.get("tool_name") == "Bash" and makes_commit(command):
        stale = unread_rulings(transcript, pathlib.Path(entry["planning_dir"]), name)
        if stale:
            return deny(
                f"re-read {', '.join(str(f) for f in stale)} before you commit: the lead "
                "added a ruling after your last read. Apply each entry you have not applied "
                "and name its id in your checkpoint, then commit (execution.md, F59)."
            )
    size = context(transcript)
    stamp = REGISTRY / f"{session}.{agent}.stop"
    if size >= CONTEXT_STOP and not stamp.exists():
        stamp.touch()
        emit(
            "PreToolUse",
            f"route_state.py (hook): your context is {size // 1000}k tokens. Finish the task "
            "you are on — its commit and its gate — then overwrite the lane checkpoint "
            "(current state, orientation map, `Final SHA:`) and reply; do not start another "
            "task (execution.md, F75).",
        )
    return 0


def skill_changes(entry_path, entry):
    """The skill's files written since this session last read them; marks them read."""
    seen = entry.get("skill_seen", entry.get("activated", 0))
    files = [SKILL, *sorted((SKILL_DIR / "references").rglob("*.md"))]
    changed = [f for f in files if f.stat().st_mtime > seen]
    if changed:
        entry["skill_seen"] = max(f.stat().st_mtime for f in changed)
        entry_path.write_text(json.dumps(entry) + "\n")
    return [str(f.relative_to(SKILL_DIR)) for f in changed]


def stage_docs(a, rung):
    """(stage, the lead documents it reads) going by which of the phase's files exist."""
    base, p = pathlib.Path(a.planning_dir), a.phase
    sins = ", references/sins/lead.md" if rung == "L" else ""
    dec = base / "decisions" / f"phase{p}"
    if any((base / "lanes").glob(f"p{p}-*")) or lane_checkpoints(base / "lanes", p):
        return 5, "references/execution.md" + sins
    if any(
        not f.name.startswith(f"p{p}-00") for f in (base / "plans").glob(f"p{p}-*.md")
    ):
        return 4, "references/templates.md §4, references/briefs/plan-brief.md"
    if any((base / "reconcile").glob(f"p{p}-*.md")):
        return 3, "references/briefs/reconcile-brief.md" + sins
    if (dec / "00-arbiter.md").exists():
        return 2, "references/templates.md §3, references/briefs/spec-brief.md"
    if dec.is_dir():
        return 1, "references/templates.md §1-2, references/briefs/decision-brief.md"
    return 0, "references/prompts.md §0"


def budget_line(marker, phase):
    budgets = [b for b in marker.get("budgets", []) if b.get("phase") == phase]
    if not budgets:
        return []
    b = budgets[-1]
    line = f"budget     {b['label']} · {b['estimate']:g}M · {b['groups']} exec- agents"
    return [f"{line} · since {b['at'][:16]}Z"]


def emit(name, text):
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}
        )
    )


def hook():
    """The hooks, for a session `--activate` registered.

    PreToolUse holds the lead's `exec-` dispatches to the recorded budget, gives each one it
    allows an ETA from the route's finished groups and, inside an `exec-`
    agent, applies the context stop and the rulings check; it asks the user before the lead's
    outward action on the hosted repository and refuses an agent's. The other events put the round's state
    into the lead's context, never a subagent's or teammate's (agent_id): PostToolUse checks at
    most every THROTTLE_S and, like an agent's return as a prompt, injects only the lines that
    changed since the last injection — nothing when none did. SessionStart (compact, resume)
    injects the whole report and what to re-read. Each names the skill's files changed since the
    session read them.
    """
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    session = event.get("session_id") or ""
    entry_path = REGISTRY / f"{session}.json"
    name = event.get("hook_event_name", "")
    if session and name == "PreToolUse" and unrouted(event, entry_path):
        return deny(
            "this session has no active decision-spec-plan route, so the route's budget gate, "
            "push review and state reports are all off; dsp-deep and dsp-mechanical serve only "
            "that route. Load the decision-spec-plan skill with the Skill tool and follow "
            "SKILL.md — the rung announcement with its cost, then "
            f"`python3 {pathlib.Path(__file__).resolve()} <planning-dir> --phase <P> --repo "
            "<repo> --activate --rung <S|M|L>` — before you dispatch (F79)."
        )
    if not session or not entry_path.exists():
        return 0
    entry = load_json(entry_path)
    if name in ("SubagentStop", "TeammateIdle"):
        try:
            return own_wait(event, session)
        except Exception:  # noqa: BLE001 — a broken check never holds an agent
            return 0
    if name == "PreToolUse":
        if act := checked(outward, event, entry):
            if event.get("agent_id"):
                return deny(
                    f"`{act}` acts on the hosted repository, and a route agent never runs "
                    "one: name it in your return and the lead asks the user (F81)."
                )
            return deny(
                f"`{act}` acts on the hosted repository: the user approves it here, each "
                "time — an earlier answer authorizes only what it named (F81).",
                "ask",
            )
        if event.get("agent_id"):
            return checked(agent_pre, event, session, entry) or 0
        if checked(s_harvester, event, entry):
            return deny(
                "rung S has no harvester: read the diff, the ticket and the code yourself "
                "(SKILL.md, Stage 0). At S a harvest cost 2–8× the review it fed, and the "
                "reviews without one needed no correction (F87). A question only an agent "
                "can answer means the round is not S: re-announce it at M."
            )
        dispatch = event.get("tool_input")
        agent_name = (
            str(dispatch.get("name") or "") if isinstance(dispatch, dict) else ""
        )
        if event.get("tool_name") != "Agent":
            return 0
        if agent_name.startswith((EXEC, "verify-")) and (
            held := checked(ledger_hold, event, entry)
        ):
            return deny(held)
        if agent_name.startswith(EXEC):
            return checked(gate_dispatch, event, entry) or 0
        return 0
    if event.get("agent_id"):
        return 0
    if name == "SessionStart" and event.get("source") not in ("compact", "resume"):
        return 0
    if name == "UserPromptSubmit":
        head = (event.get("prompt") or "").strip()[:500]
        if not any(t in head for t in RETURNS):
            return 0
    if name == "PostToolUse":
        stamp = REGISTRY / f"{session}.checked"
        if stamp.exists() and time.time() - stamp.stat().st_mtime < THROTTLE_S:
            return 0
        stamp.touch()
    try:
        path = pathlib.Path(entry["marker"])
        marker = json.loads(path.read_text())
        a = parser().parse_args(marker["args"])
    except (OSError, ValueError, KeyError):
        return 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(a, fresh=False, extra=budget_line(marker, a.phase))
    text = buf.getvalue().rstrip()
    body = text.partition("\n")[2]
    last = path.with_suffix(".last")
    old = last.read_text() if last.exists() else None
    since = (
        time.strftime("%m-%d %H:%M", time.localtime(last.stat().st_mtime))
        if old
        else ""
    )
    last.write_text(body)
    changed = skill_changes(entry_path, entry)
    note = (
        f"decision-spec-plan changed since this session read it: {', '.join(changed)} (in "
        f"{SKILL_DIR}). The skill text in your context is the old one — Read SKILL.md in full, "
        "then each changed file your current stage uses, before the next action (F78).\n"
        if changed
        else ""
    )

    if name == "SessionStart":
        stage, docs = stage_docs(a, marker.get("rung"))
        handoff = f"{a.planning_dir}/HANDOFF.md"
        where = f"for Stage {stage} (going by the planning dir) {docs}, in {SKILL_DIR}"
        reread = (
            f"Read {SKILL} in full — a resumed session has no skill text — then {handoff} "
            f"and, {where}"
            if event.get("source") == "resume"
            else f"Re-read {handoff} and, {where} (the skill text is re-attached; if it ends "
            f"truncated, Read {SKILL} in full)"
        )
        emit(
            name,
            f"{note}decision-spec-plan route active. Before the next action: {reread}.\n"
            f"route_state.py (hook) — the in-flight block's state:\n{text}",
        )
        return 0
    if old == body:
        delta = ""
    elif old is None:
        delta = f"route_state.py (hook) — the in-flight block's state:\n{text}"
    else:
        before = set(old.splitlines())
        now_lines = body.splitlines()
        new = [ln for ln in now_lines if ln not in before]
        cleared = sum(1 for ln in before - set(now_lines) if ln.startswith("  "))
        delta = (
            f"route_state.py (hook) — changed between {since} and "
            f"{time.strftime('%m-%d %H:%M')}:\n"
            + "\n".join(new)
            + (f"\n  ({cleared} earlier flags cleared)" if cleared else "")
        )
    if note or delta:
        emit(name, (note + delta).rstrip())
    return 0


def main():
    argv = sys.argv[1:]
    if "--hook" in argv:
        return hook()
    if "--budget" in argv:
        return budget(argv)
    a = parser().parse_args()
    code = report(a)
    if code == 0 and a.activate:
        code = activate(a, a.main or (default_branch(a.repo) if a.repo else "main"))
    return code


def lane_checkpoints(lanes, phase):
    """Every lane checkpoint but another phase's: `p<P>-<id>-…` and lanes named any other way."""
    return [
        c
        for c in sorted(lanes.glob("*-checkpoint.md"))
        if not ((m := re.match(r"p(\d+)-", c.name)) and m.group(1) != phase)
    ]


def gate_logs(lanes, phase):
    """(log, the commit and dirty count of its first `sha=` line within 20 lines, its last `exit=`
    or None) for each full gate log but another phase's — the lines push_guard.py reads. A log
    whose first 20 lines name a CI harness ran only that suite: no full gate."""
    out = []
    # Line by line: a whole log read at once raised ENOMEM on a large one. Lines end at `\n`
    # only, as push_guard.py reads them: a progress bar's `\r` before `exit=` is no line break.
    for log in sorted(lanes.glob("*-gate*.log")):
        if (m := re.match(r"p(\d+)-", log.name)) and m.group(1) != phase:
            continue
        first, last, harness = "", None, False
        with log.open(errors="replace", newline="\n") as f:
            for n, ln in enumerate(f):
                if n < 20 and not first and ln.startswith("sha="):
                    first = ln
                harness |= n < 20 and ln.startswith("harness=")
                if m := re.fullmatch(r"exit=(\d+)\s*", ln):
                    last = m.group(1)
        if harness:
            continue
        head = re.fullmatch(r"sha=([0-9a-f]{40}) dirty=(\d+)\s*", first)
        sha, dirty = head.groups() if head else ("", "")
        out.append((log, sha, dirty, last))
    return out


def lane_check(repo, main, full, gates, worktree):
    """What the lead checked by hand on a group's return: the lane's commits since the main branch,
    the gate at its SHA, their trailers, and what its worktree left uncommitted (F80)."""
    parts = [f"{git(repo, 'rev-list', '--count', f'{main}..{full}')[1]} commits"]
    at = [(dirty, code) for _, sha, dirty, code in gates if sha == full]
    if any(at_ == ("0", "0") for at_ in at):
        parts.append("gate exit=0")
    elif at:
        parts.append(f"gate exit={at[-1][1] or 'none yet'} dirty={at[-1][0]}")
    else:
        parts.append("no gate log at this SHA")
    trailers = git(repo, "log", "--format=%(trailers:only,unfold)", f"{main}..{full}")[
        1
    ]
    keys = {}
    for key in (ln.split(":", 1)[0] for ln in trailers.splitlines() if ":" in ln):
        keys[key] = keys.get(key, 0) + 1
    parts.append(
        "trailers "
        + (", ".join(f"{k} ×{n}" for k, n in sorted(keys.items())) or "none")
    )
    if worktree and worktree[1] == full:
        changed = git(worktree[0], "status", "--porcelain", "--untracked-files=no")[1]
        if changed:
            parts.append(f"{len(changed.splitlines())} uncommitted in its worktree")
    return " · ".join(parts)


def base_drift(repo, text):
    """What moved under the round since its decision index recorded the base and the unmerged
    refs it assumes, as of the last fetch: a round planned on them is planned on a past (F91)."""
    rows = BASE.findall(text)
    base_ref = next((ref for kind, ref, _ in rows if kind == "Base"), None)
    out = []
    for kind, ref, sha in rows:
        rc, head = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if rc:
            out.append(
                f"{kind.lower() + ' ref gone':<34} {ref} (recorded at {sha[:9]})"
            )
            continue
        if kind == "Base":
            # templates.md records the local main branch, which a fetch never moves: its
            # upstream does
            rc, up = git(
                repo,
                "rev-parse",
                "--verify",
                "--quiet",
                f"{ref}@{{upstream}}^{{commit}}",
            )
            tips = [("base moved", ref, head)]
            if rc == 0 and up != head:
                tips.append(("base moved upstream", f"{ref}@{{upstream}}", up))
            for label, name, tip in tips:
                if not tip.startswith(sha):
                    rc, n = git(repo, "rev-list", "--count", f"{sha}..{tip}")
                    out.append(
                        f"{label:<34} {name} {n if rc == 0 else '?'} commits past {sha[:9]}"
                    )
            continue
        landed = base_ref and (
            git(repo, "merge-base", "--is-ancestor", head, base_ref)[0] == 0
        )
        if head.startswith(sha):
            if landed:
                out.append(
                    f"{'assumed ref merged':<34} {ref} {sha[:9]} into {base_ref}"
                )
            continue
        out.append(
            f"{'assumed ref moved':<34} {ref} {sha[:9]} → {head[:9]}"
            + (f", merged into {base_ref}" if landed else "")
        )
    return out


def report(a, fresh=True, extra=()):
    base, p = pathlib.Path(a.planning_dir), a.phase
    if not base.is_dir():
        print(f"no planning dir at {base}")
        return 2
    rep = Report(a.all, fresh)
    out = [f"route state · {base} · phase {p} · {time.strftime('%Y-%m-%d %H:%M')}"]
    main = a.main or (default_branch(a.repo) if a.repo else "main")
    if (
        a.repo
        and git(a.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{main}")[0]
    ):
        fallback = default_branch(a.repo)
        rep.flag(f"{'--main ' + main + ' does not exist':<34} using {fallback}")
        main = fallback
    handoff = base / "HANDOFF.md"
    if handoff.exists() and handoff.stat().st_size > HANDOFF_MAX:
        rep.flag(
            f"{'HANDOFF.md over 40 KB':<34} {handoff.stat().st_size / 1024:.0f} KB — move "
            "closed lanes and settled history to HANDOFF-archive.md (F76)"
        )

    dec = base / "decisions" / f"phase{p}"
    index = dec / "00-index.md"
    index_text = index.read_text(errors="replace") if index.exists() else ""
    wanted = sorted(
        set(re.findall(r"^\|\s*\*{0,2}D(\d+)\b", index_text, re.MULTILINE)), key=int
    )
    have = {
        re.match(r"D(\d+)", f.name).group(1): f
        for f in sorted(dec.glob("D*.md"))
        if re.match(r"D\d+", f.name)
    }
    # At rung S the index holds the decisions themselves: no D file follows (templates.md §1).
    route = marker_path(a.repo, str(base.resolve())) if a.repo else None
    rung = a.rung or (load_json(route).get("rung") if route else None)
    waiting = [f"D{n}" for n in wanted if n not in have and rung != "S"]
    markers = headers = 0
    for f in have.values():
        rep.file(f, base)
        text = f.read_text(errors="replace")
        markers += text.count("> **SUPERSEDED BY")
        headers += "> **Read 00-arbiter.md first.**" in text
    fixed = [
        "00-dispatch",
        "00-framing-review",
        "00-seams",
        "00-arbiter",
        "spec-returns",
    ]
    present = " ".join(
        f"{n} {'yes' if (dec / (n + '.md')).exists() else 'no'}" for n in fixed
    )
    out.append(
        f"decisions  {len(have)} D files ({len(wanted)} in the index"
        + (f"; pending {pending(waiting)}" if waiting else "")
        + f") · markers {markers}, header in {headers}/{len(have)} · {present}"
    )
    if a.repo and index.exists():
        for line in base_drift(a.repo, index.read_text(errors="replace")):
            rep.flag(line)

    if a.sections:
        lo, sep, hi = a.sections.replace("–", "-").partition("-")
        first, last = int(lo), (int(hi) if hi else (None if sep else int(lo)))
        spec = [
            f
            for f in sorted(pathlib.Path(a.spec_dir or base / "spec").glob("*.md"))
            if (m := re.match(r"0*(\d+)-", f.name))
            and first <= int(m.group(1)) <= (last if last is not None else 10**6)
        ]
        got = {int(re.match(r"0*(\d+)-", f.name).group(1)) for f in spec}
        for f in spec:
            rep.file(f, base)
        if last is None:
            out.append(f"spec       {len(got)} sections from §{first}")
        else:
            waiting = [f"§{s}" for s in range(first, last + 1) if s not in got]
            out.append(
                f"spec       {len(got)}/{last - first + 1} sections"
                + (f" (pending {pending(waiting)})" if waiting else "")
            )

    rec = sorted((base / "reconcile").glob(f"p{p}-*.md"))
    for f in rec:
        rep.file(f, base)
    out.append(f"reconcile  {len(rec)} files")

    plans_dir = base / "plans"
    pindex = plans_dir / f"p{p}-00-index.md"
    ids = sorted(
        set(re.findall(rf"\bp{p}-(\d+[a-z]?)\b", pindex.read_text(errors="replace")))
        - {"00"}
        if pindex.exists()
        else set()
    )
    plans = {
        re.match(rf"p{p}-(\d+[a-z]?)-", f.name).group(1): f
        for f in sorted(plans_dir.glob(f"p{p}-*.md"))
        if re.match(rf"p{p}-(\d+[a-z]?)-", f.name) and not f.name.startswith(f"p{p}-00")
    }
    waiting = [f"p{p}-{i}" for i in ids if i not in plans]
    manifests_ok = 0
    for i, f in plans.items():
        rep.file(f, base)
        # The layout names manifests by plan id, prompts.md §4 by the plan file's stem.
        m = base / "manifests" / (f.stem + ".json")
        if not m.exists() and (base / "manifests" / f"p{p}-{i}.json").exists():
            m = base / "manifests" / f"p{p}-{i}.json"
        try:
            json.loads(m.read_text())
            manifests_ok += 1
        except FileNotFoundError:
            rep.flag(f"{'no manifest':<34} manifests/{m.name}")
        except ValueError:
            rep.flag(f"{'manifest is not valid JSON':<34} manifests/{m.name}")
    out.append(
        f"plans      {len(plans)} plans ({len(ids)} in the index"
        + (f"; pending {pending(waiting)}" if waiting else "")
        + f") · {manifests_ok} manifests parse"
    )

    lanes = base / "lanes"
    checkpoints = lane_checkpoints(lanes, p)
    gates = gate_logs(lanes, p)
    merged = 0
    worktrees = {}
    if a.repo:
        rc, wt = git(a.repo, "worktree", "list", "--porcelain")
        path = head = None
        for line in wt.splitlines() + [""]:
            if line.startswith("worktree "):
                path = line[9:]
            elif line.startswith("HEAD "):
                head = line[5:]
            elif line.startswith("branch "):
                worktrees[line.removeprefix("branch refs/heads/")] = (path, head)
    # The integrator's record of a lane it rebased or squashed: `Merged <plan-id> <lane> → <main>`.
    records = {}
    for w in sorted(lanes.glob("wave*-integration*.md")):
        for pid, lane_sha, main_sha in MERGED.findall(w.read_text(errors="replace")):
            records[pid] = (lane_sha, main_sha, w.name)
    for c in checkpoints:
        rep.file(c, base)
        plan_id = c.name[: -len("-checkpoint.md")]
        text = c.read_text(errors="replace")
        final = FINAL_SHA.findall(text)
        shas = final or SHA.findall(text)
        sha = shas[-1] if shas else None
        if not final:
            rep.flag(
                f"{'no `Final SHA:` line':<34} lanes/{c.name} (last SHA in the text used)"
            )
        state = "no SHA"
        inside = False
        full = None
        if sha and a.repo:
            rc, full = git(
                a.repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"
            )
            if rc:
                rep.flag(
                    f"{'checkpoint SHA not in the repo':<34} lanes/{c.name} ({sha})"
                )
                state = f"{sha} unknown"
            else:
                inside = git(a.repo, "merge-base", "--is-ancestor", full, main)[0] == 0
                how = ""
                if not inside:
                    # A rebased lane: every commit's patch is already on main.
                    rc, cherry = git(a.repo, "cherry", main, full)
                    inside = rc == 0 and not any(
                        ln.startswith("+") for ln in cherry.splitlines()
                    )
                    how = " (by patch)" if inside else ""
                rec = records.get(plan_id)
                if not inside and rec and full.startswith(rec[0]):
                    inside = (
                        git(a.repo, "merge-base", "--is-ancestor", rec[1], main)[0] == 0
                    )
                    how = f" as {rec[1]} ({rec[2]})" if inside else ""
                merged += inside
                state = f"{sha} {'merged' + how if inside else 'not merged'}"
                if plan_id in worktrees:
                    head = worktrees[plan_id][1]
                    if head != full:
                        ahead = git(a.repo, "rev-list", "--count", f"{full}..{head}")[1]
                        state += f", branch {ahead} ahead"
                        if inside and ahead not in ("", "0"):
                            rep.flag(
                                f"{'lane moved past its merged SHA':<34} {plan_id} ({ahead} commits, F41)"
                            )
        elif sha:
            state = sha
        size = len(text.splitlines())
        # A merged lane has no next group to read its checkpoint (F76).
        if size > CHECKPOINT_MAX and not inside:
            rep.flag(
                f"{f'checkpoint over {CHECKPOINT_MAX} lines':<34} lanes/{c.name} ({size} — "
                "the next group overwrites it with the lane's state and map)"
            )
        # Every group reads its lane's rulings file whole; applied rulings belong in the archive,
        # read only for an id the dispatch names (F67).
        rulings = c.with_name(plan_id + "-rulings.md")
        if not inside and rulings.exists() and rulings.stat().st_size > RULINGS_MAX:
            rep.flag(
                f"{f'rulings over {RULINGS_MAX // 1000} KB':<34} lanes/{rulings.name} "
                f"({rulings.stat().st_size // 1000} KB — between groups, move the applied ones "
                f"to {plan_id}-rulings-archive.md)"
            )
        # Every open lane gets its line, so a group's return changes it and the next injection
        # carries the check the lead used to make by hand (F80).
        if full and not inside:
            state += " · " + lane_check(
                a.repo, main, full, gates, worktrees.get(plan_id)
            )
        if a.all or not inside:
            rep.lines.append(f"    {plan_id:<48} {state}")
    lane_trees = sum(1 for b in worktrees if b != main)
    out.append(
        f"lanes      {len(checkpoints)} checkpoints ({len(ids)} plans)"
        + (
            f" · {merged} merged into {main} · {lane_trees} lane worktrees"
            if a.repo
            else ""
        )
    )

    green = red = running = 0
    for log, _, _, code in gates:
        if code is None:
            running += 1
            rep.flag(f"{'gate log has no exit= line':<34} lanes/{log.name}")
        elif code == "0":
            green += 1
        else:
            red += 1
            rep.flag(f"{'RED exit=' + code:<34} lanes/{log.name}")
    waves = sorted(lanes.glob("wave*-integration.md"))
    for w in waves:
        rep.file(w, base)
    out.append(
        f"gates      {green} green · {red} red · {running} without exit= · {len(waves)} integration files"
    )
    out.extend(extra)

    print("\n".join(out))
    if rep.lines:
        print("\n".join(rep.lines))
    print(f"flags      {len(rep.flags)}")
    for f in rep.flags:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
