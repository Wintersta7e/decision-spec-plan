# SPDX-License-Identifier: MIT
"""The PreToolUse checks inside a route's agents: `exec-` and `hunt-`.

Inside an `exec-` agent the context stop (F75), and a commit held while its own lane's
rulings file changed after it last read it (F59); inside a `hunt-` agent the find-only
hold (F109).
"""

import pathlib
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


def hunt_hold(event: Mapping[str, object], entry: RegistryEntry) -> str | None:
    """Return what a `hunt-` agent's call does that its find-only brief rules out.

    A commit, a git config write or an inline alias (writes_git_config), or an edit
    inside the route's repository and outside its planning dir; None for any other
    call. Hunters under a find-only brief committed, changed the hooks path and wrote
    outside their clone (F109). A backstop against a slip, not a sandbox.
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
    raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if tool not in EDITS or not raw:
        return None
    path = (pathlib.Path(here or ".") / raw).resolve()
    marker_file = pathlib.Path(entry["marker"])
    marker = load_json(marker_file)
    # the marker sits in the repository's git common dir
    repo = (route_args(marker).repo if "args" in marker else None) or (
        marker_file.parent.parent
    )
    planning = pathlib.Path(entry["planning_dir"]).resolve()
    if path.is_relative_to(pathlib.Path(repo).resolve()) and not path.is_relative_to(
        planning
    ):
        return f"an edit of {path}"
    return None


def agent_pre(event: Mapping[str, object], session: str, entry: RegistryEntry) -> int:
    """Run the checks inside a route's agent.

    Inside an `exec-` agent the context stop (F75) and a commit held for a ruling
    (F59); inside a `hunt-` agent the find-only hold (hunt_hold) alone.

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
    if name.startswith(HUNT) and (act := hunt_hold(event, entry)):
        return deny(
            f"{act} is refused: a hunter is find-only (references/briefs/"
            "hunt-brief.md, F109), and its fix goes to a task group after the "
            "user's triage."
        )
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
