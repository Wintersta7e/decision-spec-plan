# SPDX-License-Identifier: MIT
"""SubagentStop and TeammateIdle: an agent ending its turn is sent back to its jobs.

An agent that ends its turn while its own background shell or monitor runs is sent back
to wait on it, since nothing wakes it when the job ends (F92).
"""

import json
import pathlib
import re
import sys
from collections.abc import Mapping

from .common import REGISTRY, as_dict, as_list, load_json
from .transcript import agent_transcript, started_jobs, tasks_dir

JOB_WAITS = 2


def _running(tasks: object) -> set[str]:
    """Return the ids of the shells and monitors a `background_tasks` list says run."""
    running: set[str] = set()
    for item in as_list(tasks) or []:
        t = as_dict(item) or {}
        if t.get("type") in ("shell", "monitor") and t.get("status") == "running":
            running.add(str(t.get("id")))
    return running


def _exited(log: pathlib.Path) -> bool:
    """Return whether a job's output file ends `[exited with code N]` or `[killed]`."""
    try:
        with log.open("rb") as fh:
            _ = fh.seek(max(0, log.stat().st_size - 200))
            tail = fh.read().decode("utf-8", "replace").strip().splitlines()
    except OSError:
        tail = []
    return bool(tail and re.fullmatch(r"\[(exited with code -?\d+|killed)\]", tail[-1]))


def own_jobs(event: Mapping[str, object], session: str) -> list[tuple[str, str, str]]:
    """Return the background jobs an agent ending its turn left running.

    Each as (id, what, log).

    Only the jobs the agent's own transcript started count: SubagentStop's
    `background_tasks` lists every job of the session, a neighbour teammate's too — a
    plan author was sent back twice to wait on another's probe. A job listed there runs
    while its status says so. TeammateIdle lists none: a job runs until its task
    notification (one with a `<status>`) or the agent's TaskStop of it reaches the
    transcript, or its output file ends `[exited with code N]` or `[killed]` — a monitor
    writes no file until its first line of output.
    """
    transcript = agent_transcript(event, session, str(event.get("agent_id") or ""))
    if transcript is None:
        return []
    jobs, ended, tasks = started_jobs(transcript)
    if "background_tasks" in event:
        running = _running(event["background_tasks"])
        return [(j, what or "", log or "") for j, what, log in jobs if j in running]
    out: list[tuple[str, str, str]] = []
    for job, what, path in jobs:
        if job in ended:
            continue
        log = pathlib.Path(path) if path else None
        if log is None:
            if tasks is None:
                tasks = tasks_dir(transcript, session)
            log = tasks / f"{job}.output"
        if not _exited(log):
            out.append((job, what or "", str(log)))
    return out


def _count(counts: Mapping[str, object], key: str) -> int:
    """Return how often an agent was already sent back to wait on a job."""
    n = counts.get(key, 0)
    return n if isinstance(n, int) else 0


def own_wait(event: Mapping[str, object], session: str) -> int:
    """Send an agent back to wait on its own running job, at most JOB_WAITS times (F92).

    Returns:
        The hook's exit code: 2 when the agent is sent back, else 0.
    """
    agent = str(event.get("agent_id") or "")
    sent = REGISTRY / f"{session}.waits.json"
    counts = load_json(sent) if sent.exists() else {}
    jobs = [
        j
        for j in own_jobs(event, session)
        if _count(counts, f"{agent}:{j[0]}") < JOB_WAITS
    ]
    if not jobs:
        return 0
    for job in jobs:
        counts[f"{agent}:{job[0]}"] = _count(counts, f"{agent}:{job[0]}") + 1
    _ = sent.write_text(json.dumps(counts))
    what = "; ".join(
        f"`{' '.join(w.split())[:160]}` ({j}{', output ' + log if log else ''})"
        for j, w, log in jobs
    )
    print(
        f"route_state.py (hook): your own background job is still running — {what} — "
        "and nothing wakes you when it ends: of 81 turns agents ended this way, none "
        "woke, and each sat until the lead noticed, the longest 6 h 44 min (F92). Wait "
        "for it in the foreground now: Bash `until grep -q '^exit=' <its log> || tail "
        "-n1 <its output> | grep -Eq '^\\[(exited|killed)'; do sleep 20; done` with "
        "timeout 240000 — under the prompt cache's 5 minutes — repeated until it ends; "
        "then finish your task and return. If it already ended, carry on.",
        file=sys.stderr,
    )
    return 2
