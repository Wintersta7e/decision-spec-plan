# SPDX-License-Identifier: MIT
"""The PreToolUse checks inside a route's agents: `exec-` and `hunt-`.

Inside an `exec-` agent the context stop (F75), and a commit held while its own lane's
rulings file changed after it last read it (F59); inside a `hunt-` agent the find-only
hold and its shell run with the route's repository read-only (F109).
"""

import json
import os
import pathlib
import shlex
import subprocess
from collections.abc import Mapping

from .commands import makes_commit, writes_git_config
from .common import (
    EDITS,
    EXEC,
    HUNT,
    PLAN_ID,
    REGISTRY,
    RegistryEntry,
    as_dict,
    deny,
    emit,
    id_name,
    load_json,
    route_args,
)
from .transcript import agent_name, agent_transcript, context, dispatch_text, last_reads

CONTEXT_STOP = 200_000
# The tools whose input naming a rulings file counts as the agent reading it.
READS = ("Read", "Bash", "Grep")
# How long bubblewrap's probe may take before the hook counts it as unable to run.
PROBE_S = 10


def own_rulings(planning: pathlib.Path, name: str, dispatch: str) -> list[pathlib.Path]:
    """Return the lane rulings files that are this `exec-` agent's.

    Its name opens with the lane's name or plan id (`exec-p4-09-n` →
    `p4-09-ui-truth-rulings.md`), or its dispatch prompt names the file.
    """
    group = name.removeprefix(EXEC)
    own: list[pathlib.Path] = []
    for f in sorted((planning / "lanes").glob("*-rulings.md")):
        lane = f.name.removesuffix("-rulings.md")
        ids = [lane, *([m.group(0)] if (m := PLAN_ID.match(lane)) else [])]
        if f.name in dispatch or any(
            group == i or group.startswith(i + "-") for i in ids
        ):
            own.append(f)
    return own


def unread_rulings(
    transcript: pathlib.Path, planning: pathlib.Path, name: str
) -> list[tuple[pathlib.Path, bool]]:
    """Return (file, read before) for each own rulings file changed since it was read.

    Each of the agent's own rulings files that changed after its last read of them, or
    that it never read. Only its own: a listing of `lanes/` in its transcript once made
    every lane's file count as its (F59).
    """
    files = own_rulings(planning, name, dispatch_text(transcript))
    last = last_reads(transcript, files, READS) if files else {}
    return [(f, f in last) for f in files if last.get(f, 0) < f.stat().st_mtime]


def _route_repo(entry: RegistryEntry) -> pathlib.Path:
    """Return the route's repository: the marker's `--repo`, else the common dir's."""
    marker_file = pathlib.Path(entry["marker"])
    marker = load_json(marker_file)
    # the marker sits in the repository's git common dir
    repo = (route_args(marker).repo if "args" in marker else None) or (
        marker_file.parent.parent
    )
    return pathlib.Path(repo).resolve()


def _git_configs() -> tuple[pathlib.Path, pathlib.Path]:
    """Return the global git config file and git's XDG config dir, resolved."""
    home = pathlib.Path.home()
    xdg = pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return (home / ".gitconfig").resolve(), (xdg / "git").resolve()


def _held_path(path: pathlib.Path, entry: RegistryEntry) -> bool:
    """Return whether a hunter may not write path.

    One inside the route's repository and outside its planning dir, or a global git
    config (`~/.gitconfig`, `$XDG_CONFIG_HOME/git/`), where a hooks path or an alias
    reaches every repository.
    """
    gitconfig, xdg_git = _git_configs()
    if path == gitconfig or path.is_relative_to(xdg_git):
        return True
    planning = pathlib.Path(entry["planning_dir"]).resolve()
    return path.is_relative_to(_route_repo(entry)) and not path.is_relative_to(planning)


def hunt_hold(event: Mapping[str, object], entry: RegistryEntry) -> str | None:
    """Return what a `hunt-` agent's call does that its find-only brief rules out.

    A commit, a git config write or an inline alias (writes_git_config) in a Bash call;
    a file an edit tool writes that _held_path holds: an edit runs in the harness, out
    of bubblewrap's reach. None for any other call: the rest of a hunter's shell runs
    with the route's repository read-only (bounded). Hunters under a find-only brief
    committed, changed the hooks path and wrote outside their clone (F109); a refusal
    names the rule, where a read-only file system only fails.
    """
    tool_input = as_dict(event.get("tool_input")) or {}
    cwd = event.get("cwd")
    here = cwd if isinstance(cwd, str) else None
    tool = event.get("tool_name")
    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if makes_commit(command, here):
            return "a commit"
        if writes_git_config(command, here):
            return "a git config write or an inline alias"
        return None
    if tool not in EDITS:
        return None
    raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    path = (pathlib.Path(here or ".") / raw).resolve() if raw else None
    if path is not None and _held_path(path, entry):
        return f"a write of {path}"
    return None


def bwrap() -> str | None:
    """Return bubblewrap's path where it can create a namespace here, else None.

    Probed with `bwrap --dev-bind / / true` once per hook process (one event): a host
    without unprivileged user namespaces has the binary and cannot run it.
    """
    from shutil import which  # shutil loads bz2, lzma and zlib: the hunter path alone

    path = which("bwrap")
    if path is None:
        return None
    try:
        probe = subprocess.run(
            [path, "--dev-bind", "/", "/", "true"],
            capture_output=True,
            timeout=PROBE_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return path if probe.returncode == 0 else None


def bounded(command: str, entry: RegistryEntry, path: str) -> str:
    """Return command run by bubblewrap at path with the route's repository read-only.

    The whole file system is bound as it is, then the repository and its git common dir
    (where the marker sits, apart from the repository for a linked worktree) read-only,
    the planning dir inside it writable again, and the global git config read-only: a
    hooks path or an alias set there reaches every repository. The command runs as
    `bash -c` in the directory the call runs in; its output and exit status are its own.
    """
    repo = _route_repo(entry)
    common = pathlib.Path(entry["marker"]).resolve().parent
    planning = pathlib.Path(entry["planning_dir"]).resolve()
    args = [path, "--dev-bind", "/", "/", "--ro-bind", str(repo), str(repo)]
    if not common.is_relative_to(repo):
        args += ["--ro-bind", str(common), str(common)]
    if planning.is_relative_to(repo):
        args += ["--bind", str(planning), str(planning)]
    for config in _git_configs():
        args += ["--ro-bind-try", str(config), str(config)]
    return shlex.join([*args, "--", "bash", "-c", command])


def hunter_pre(event: Mapping[str, object], entry: RegistryEntry) -> int:
    """Run the checks inside a `hunt-` agent: hunt_hold, then its shell bounded.

    A Bash call hunt_hold passes is answered with `updatedInput`, the command bounded
    and every other input key kept, where bubblewrap runs (bwrap); where it does not,
    the call passes and the lead's `hunt-` dispatch was told so. Fail closed: a hold or
    a rewrite that raises refuses the call, unlike the hook's other checks.

    Returns:
        The hook's exit code, always 0.
    """
    find_only = (
        "a hunter is find-only (references/briefs/hunt-brief.md, F109), and its fix "
        "goes to a task group after the user's triage."
    )
    try:
        if act := hunt_hold(event, entry):
            return deny(f"{act} is refused: {find_only}")
        if event.get("tool_name") != "Bash" or (path := bwrap()) is None:
            return 0
        tool_input = dict(as_dict(event.get("tool_input")) or {})
        tool_input["command"] = bounded(
            str(tool_input.get("command") or ""), entry, path
        )
    # an unreadable marker's arguments exit in argparse: SystemExit refuses it too
    except (Exception, SystemExit):  # noqa: BLE001 — refused, never let through
        return deny(f"the read-only boundary could not be set up: {find_only}")
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": tool_input,
                }
            }
        )
    )
    return 0


def agent_pre(event: Mapping[str, object], session: str, entry: RegistryEntry) -> int:
    """Run the checks inside a route's agent.

    Inside an `exec-` agent the context stop (F75) and a commit held for a ruling
    (F59); inside a `hunt-` agent hunter_pre alone.

    Returns:
        The hook's exit code, always 0.
    """
    agent = str(event["agent_id"])
    transcript = agent_transcript(event, session, agent)
    if transcript is None:
        return 0
    name = agent_name(transcript)
    # An agent's id is `a<name>-<hash>` when the meta file lacks the name.
    name = str(name or id_name(agent))
    if name.startswith(HUNT):
        return hunter_pre(event, entry)
    if not name.startswith(EXEC):
        return 0
    command = str((as_dict(event.get("tool_input")) or {}).get("command") or "")
    cwd = event.get("cwd")
    if event.get("tool_name") == "Bash" and makes_commit(
        command, cwd if isinstance(cwd, str) else None
    ):
        stale = unread_rulings(transcript, pathlib.Path(entry["planning_dir"]), name)
        if stale:
            why = {
                True: "the lead changed it after your last read",
                False: "you have not read it",
            }
            files = ", ".join(f"{f} ({why[read]})" for f, read in stale)
            return deny(
                f"re-read {files} before you commit. Apply each entry you have not "
                "applied and name its id in your checkpoint, then commit "
                "(execution.md, F59)."
            )
    size = context(transcript)
    stamp = REGISTRY / f"{session}.{agent}.stop"
    if size >= CONTEXT_STOP and not stamp.exists():
        stamp.touch()
        emit(
            "PreToolUse",
            f"route_state.py (hook): your context is {size // 1000}k tokens. Finish "
            "the task you are on — its commit and its gate — then overwrite the lane "
            "checkpoint (current state, orientation map, `Final SHA:`) and reply; do "
            "not start another task (execution.md, F75).",
        )
    return 0
