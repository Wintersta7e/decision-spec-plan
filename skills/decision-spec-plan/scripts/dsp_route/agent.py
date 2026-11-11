# SPDX-License-Identifier: MIT
"""The PreToolUse checks inside an `exec-` agent: the context stop and a held commit.

The context stop (F75), and a commit held while its own lane's rulings file changed
after it last read it (F59).
"""

import pathlib
import re
from collections.abc import Mapping

from .commands import makes_commit
from .common import EXEC, PLAN_ID, REGISTRY, RegistryEntry, as_dict, deny, emit
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


def agent_pre(event: Mapping[str, object], session: str, entry: RegistryEntry) -> int:
    """Run the checks inside an `exec-` agent: the context stop and a held commit.

    The context stop (F75) and a commit held for a ruling (F59).

    Returns:
        The hook's exit code, always 0.
    """
    agent = str(event["agent_id"])
    transcript = agent_transcript(event, session, agent)
    if transcript is None:
        return 0
    name = agent_name(transcript)
    # An agent's id is `a<name>-<hash>` when the meta file lacks the name.
    name = str(name or re.sub(r"-[0-9a-f]{8,}$", "", agent.removeprefix("a")))
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
