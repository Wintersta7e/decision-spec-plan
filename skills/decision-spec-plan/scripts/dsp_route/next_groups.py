# SPDX-License-Identifier: MIT
"""--next: the Agent call of each lane that can take a task group now (execution.md).

A lane takes one when every plan it waits for is merged, no `exec-<plan-id>-` agent of
it is out, its gate is not red or running, and its plan has a task left: from the
checkpoint's `Next task:` line, or the plan's first task before any checkpoint. Each
call names the phase's group brief, which carries the standing rules; a brief with an
unfilled `ADAPT` slot prints no call. The lead sends each call as printed and writes
only its rulings; every other lane gets a line saying why it takes none (F48, F102).
"""

import json
import os
import pathlib
import re
import time
from typing import TYPE_CHECKING

from .common import EXEC, RouteArgs, as_dict
from .transcript import read_records, session_transcripts, subagent_transcripts

if TYPE_CHECKING:
    from .report import Lane, State

AGENT_TYPE = "decision-spec-plan:dsp-deep"
OUT_MIN = 30  # an unfinished agent unwritten this long counts as gone, not out
NEXT = re.compile(r"^Next task:\s*(\d+|none)\b", re.MULTILINE | re.IGNORECASE)
ADAPT = "\u2039ADAPT"  # the brief templates' slot, `<ADAPT` in angle quotes
TASK = re.compile(r"^#{2,3} Task (\d+)\b", re.MULTILINE)
WINDOWS_DRIVE = re.compile(r"/mnt/[a-z]/")  # how WSL mounts a Windows drive


def _agents(session: str) -> dict[str, float | None]:
    """Return each of the lead's `exec-` agents: minutes since its last write if out."""
    out: dict[str, float | None] = {}
    for lead in session_transcripts(session):
        for path, _, name in subagent_transcripts(lead, None):
            if not name.startswith(EXEC):
                continue
            ended = False
            for r in read_records(path):
                message = as_dict(r.get("message"))
                if r.get("type") == "assistant" and message is not None:
                    ended = message.get("stop_reason") == "end_turn"
            age = (time.time() - path.stat().st_mtime) / 60
            out[name] = None if ended or age > OUT_MIN else age
    return out


def _tasks(plan: pathlib.Path) -> list[int]:
    """Return the plan's task numbers in order."""
    try:
        return [int(m[1]) for m in TASK.finditer(plan.read_text(errors="replace"))]
    except OSError:
        return []


def _start(checkpoint: pathlib.Path, tasks: list[int]) -> int | str | None:
    """Return the first task the next group takes; None: no task left; str: why not."""
    if not checkpoint.exists():
        return tasks[0] if tasks else None
    m = NEXT.search(checkpoint.read_text(errors="replace"))
    if m is None:
        return (
            f"{checkpoint.name} has no `Next task: <n>` line — add the task the next "
            "group starts from (the group brief asks each group for it)"
        )
    return None if m[1].lower() == "none" else int(m[1])


def lane_dir(top: pathlib.Path, plan: str) -> pathlib.Path:
    """Return where `execution.md` puts a new lane worktree of the repo at top.

    Beside the repo, or under `~/dsp-worktrees` when the repo is on a Windows drive:
    WSL ran the same tests 3.7 times slower from `/mnt/<drive>`.
    """
    if WINDOWS_DRIVE.match(f"{top}/"):
        return pathlib.Path.home() / "dsp-worktrees" / f"{top.name}-{plan}"
    return top.with_name(f"{top.name}-{plan}")


def _worktree(state: "State", lane: "Lane", repo: str) -> str:
    """Return the lane's worktree, or where a new one goes."""
    g = state["git"]
    facts = g["lanes"].get(lane["id"]) if g else None
    if facts and facts["worktree"] and facts["worktree"]["path"]:
        return facts["worktree"]["path"]
    return str(lane_dir(pathlib.Path(repo).resolve(), lane["plan"]))


def _why_not(
    lane: "Lane | None", waits: list[str], merged: set[str], out: list[str]
) -> str | None:
    """Return why the lane takes no group now, None when it takes one."""
    if lane and lane["state"] == "merged":
        return "merged"
    if left := [w for w in waits if w not in merged]:
        return f"waits for {', '.join(left)}"
    if out:
        return f"out: {', '.join(out)}"
    state = lane["state"] if lane else "queued"
    return {
        "red": "red gate at its SHA — rule it before another group (dsp-deep's "
        "no-progress rule)",
        "gating": "its gate log has no `exit=` yet",
        "ready": "green gate — merged by the wave's integrator (prompts.md §5) once "
        "every lane of the wave is ready",
    }.get(state)


def _prompt(fields: dict[str, str], tasks: list[int], *, last: bool) -> str:
    """Return the group's dispatch prompt."""
    f = fields
    lines = [
        f"You are task group {f['name']} of lane {f['plan']}, phase {f['phase']}.",
        (
            f"Brief: {f['brief']} — read it first; with dsp-deep's rules it is your "
            "whole standing brief."
        ),
        f"Plan: {f['plan_path']}. Your tasks: {', '.join(map(str, tasks))}."
        + (
            " They include the plan's last: run its final gate task as the brief says."
            if last
            else ""
        ),
        f"Worktree: {f['worktree']} (branch {f['plan']}).",
        f"Checkpoint: {f['checkpoint']} — "
        + (
            "the previous group's; open what its map names before you explore."
            if f["has_checkpoint"]
            else "none yet; you write the first."
        ),
        f"Rulings: {f['rulings']} — "
        + ("" if f["has_rulings"] else "none yet; ")
        + "re-read it before each task and each commit.",
    ]
    return "\n".join(lines)


def _call(
    a: RouteArgs,
    state: "State",
    lane: "Lane",
    agents: dict[str, float | None],
) -> str:
    """Return the lane's Agent call and ETA, or the line saying why it has none."""
    from .holds import eta

    base = pathlib.Path(a.planning_dir).resolve()
    plan = lane["plan"]
    rel = state["plans"]["files"].get(plan.split("-", 1)[1])
    if rel is None:
        return f"{plan}: no plan file"
    tasks = _tasks(base / rel)
    checkpoint = base / "lanes" / f"{lane['id']}-checkpoint.md"
    start = _start(checkpoint, tasks)
    if isinstance(start, str):
        return f"{plan}: {start}"
    if start is None or start not in tasks:
        return f"{plan}: no task left — its final gate's log decides the lane"
    i = tasks.index(start)
    group = tasks[i : i + a.group_size]
    done = [
        int(m[1]) for n in agents if (m := re.fullmatch(rf"{EXEC}{plan}-g(\d+)", n))
    ]
    name = f"{EXEC}{plan}-g{max(done, default=0) + 1}"
    worktree = _worktree(state, lane, a.repo or ".")
    rulings = base / "lanes" / f"{lane['id']}-rulings.md"
    span = f"task {group[0]}" if len(group) == 1 else f"tasks {group[0]}-{group[-1]}"
    fields = {
        "name": name,
        "plan": plan,
        "phase": a.phase,
        "brief": str(base / f"GROUP-BRIEF-p{a.phase}.md"),
        "plan_path": str(base / rel),
        "worktree": worktree,
        "checkpoint": str(checkpoint),
        "has_checkpoint": "1" if checkpoint.exists() else "",
        "rulings": str(rulings),
        "has_rulings": "1" if rulings.exists() else "",
    }
    call = {
        "name": name,
        "subagent_type": AGENT_TYPE,
        "run_in_background": True,
        "description": f"{plan} {span}",
        "prompt": _prompt(fields, group, last=tasks[-1] in group),
    }
    g = state["git"]
    main = (g["main_sha"] if g else None) or "<main-sha>"
    first = (
        ""
        if pathlib.Path(worktree).exists()
        else f"  first: `git worktree add {worktree} -b {plan} {main}`, the "
        "project's install inside it, and the preflight check (execution.md)\n"
    )
    paths = session_transcripts(os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    return (
        f"{plan}: {name}, {span} of {len(tasks)}\n{first}"
        f"  {eta(paths, name, a.planning_dir)}\n"
        f"  {json.dumps(call, ensure_ascii=False)}"
    )


def next_groups(a: RouteArgs) -> int:
    """Print each lane's Agent call or why it takes none; 2 without a usable brief."""
    brief = pathlib.Path(a.planning_dir) / f"GROUP-BRIEF-p{a.phase}.md"
    if not brief.exists() or ADAPT in brief.read_text(errors="replace"):
        print(
            f"--next: {brief} is missing or keeps an {ADAPT} slot: copy "
            "references/briefs/group-brief.md there and fill it first"
        )
        return 2
    from .report import collect

    state = collect(a, write_cache=False)
    if state is None:
        print(f"no planning dir at {a.planning_dir}")
        return 2
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    agents = _agents(session) if session else {}
    lanes = {ln["plan"]: ln for ln in state["lanes"] if ln["id"] == ln["plan"]}
    merged = {p for p, ln in lanes.items() if ln["state"] == "merged"}
    lines: list[str] = []
    for i in state["plans"]["index_ids"]:
        plan = f"p{a.phase}-{i}"
        lane = lanes.get(plan)
        out = [
            f"{n} (written {age:.0f} min ago)"
            for n, age in agents.items()
            if age is not None and n.startswith(f"{EXEC}{plan}-")
        ]
        waits = w["waits_for"] if (w := state["waves"].get(plan)) else []
        if why := _why_not(lane, waits, merged, out):
            lines.append(f"{plan}: {why}")
        else:
            lines.append(_call(a, state, lane, agents) if lane else f"{plan}: no lane")
    if not session:
        lines.append("(no CLAUDE_CODE_SESSION_ID: agents out are not known)")
    print("\n".join(lines) if lines else "no plan in the plan index")
    return 0
