# SPDX-License-Identifier: MIT
"""`route_state.py --hook`: every hook event of a session `--activate` registered.

Each event is dispatched to the check or report it calls for. It runs on every tool
call of every session, most with no route, so each branch imports only the modules it
uses: a module is a few milliseconds to load from a slow mount, and importing them all
up front made the no-route call 70% slower.
"""

import contextlib
import io
import os
import pathlib
import sys
import time
from collections.abc import Mapping
from typing import cast

from .common import (
    EXEC,
    REGISTRY,
    SCRIPT,
    SKILL,
    SKILL_DIR,
    RegistryEntry,
    RouteArgs,
    as_dict,
    checked,
    deny,
    emit,
    is_return,
    load_json,
    parse_json,
    route_args,
)

THROTTLE_S = 20
# The agent types only the route dispatches (agents/dsp-*.md), bare or plugin-qualified.
ROUTE_AGENTS = ("dsp-deep", "dsp-mechanical")
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def unrouted(event: Mapping[str, object], entry_path: pathlib.Path) -> bool:
    """Return whether the lead dispatches a route agent with no active route (F79).

    A `dsp-deep` or `dsp-mechanical` agent: the skill was never loaded or the route
    ended, and every hook is off.
    """
    if event.get("agent_id") or event.get("tool_name") != "Agent":
        return False
    tool_input = as_dict(event.get("tool_input")) or {}
    kind = str(tool_input.get("subagent_type") or "")
    if kind.rpartition(":")[2] not in ROUTE_AGENTS:
        return False
    marker = load_json(entry_path).get("marker")
    return not (marker and pathlib.Path(str(marker)).exists())


def _outward(event: Mapping[str, object], act: str) -> int:
    """Refuse an agent's outward action; ask the user about the lead's (F81)."""
    if event.get("agent_id"):
        return deny(
            f"`{act}` acts on the hosted repository or a registry, and a route agent "
            "never runs one: name it in your return and the lead asks the user (F81)."
        )
    return deny(
        f"`{act}` acts on the hosted repository or a registry: the user approves it "
        "here, each time — an earlier answer authorizes only what it named, and a "
        "standing 'later' rules it out until they lift it (F81).",
        "ask",
    )


def _lead_dispatch(event: Mapping[str, object], entry: RegistryEntry) -> int:
    """Run the lead's PreToolUse holds: a dead recipient, rung S, ledger and budget."""
    from .holds import dead_recipient, gate_dispatch, ledger_hold, s_harvester

    if dead := checked(dead_recipient, event, entry):
        return deny(dead)
    if checked(s_harvester, event, entry):
        return deny(
            "rung S has no harvester: read the diff, the ticket and the code yourself "
            "(SKILL.md, Stage 0). At S a harvest cost 2–8× the review it fed, and the "
            "reviews without one needed no correction (F87). A question only an agent "
            "can answer means the round is not S: re-announce it at M."
        )
    dispatch = as_dict(event.get("tool_input"))
    agent_name = str(dispatch.get("name") or "") if dispatch is not None else ""
    if event.get("tool_name") != "Agent":
        return 0
    if agent_name.startswith((EXEC, "verify-")) and (
        held := checked(ledger_hold, event, entry)
    ):
        return deny(held)
    if agent_name.startswith(EXEC):
        return checked(gate_dispatch, event, entry) or 0
    return 0


def _review(event: Mapping[str, object], entry: RegistryEntry) -> int | None:
    """Return the deny of a review post the route holds, else None (F104)."""
    from .holds import review_hold, unrecorded_review
    from .outward import review_post

    if not (post := checked(review_post, event, entry)):
        return None
    act, shaped = post
    if held := checked(review_hold, entry):
        return deny(f"`{act}` posts a review comment; {held}")
    if shaped and (why := checked(unrecorded_review, entry)):
        return deny(f"`{act}` posts a review; {why}")
    return None


def _pre_tool_use(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> int:
    """Run the PreToolUse checks of a registered session."""
    from .gate_log import gate_log_edit
    from .outward import outward

    if (refused := _review(event, entry)) is not None:
        return refused
    if how := checked(gate_log_edit, event):
        return deny(
            f"{how}: a gate log holds only what the gate printed — it is the evidence "
            "a push and a lane return are judged on. Re-run the gate through the "
            "runner, which writes every line the push check reads (`<skill-dir>/"
            "scripts/gate.py <planning-dir> <name> -- '<gate>'`), or copy a real run's "
            "output in. A gate that cannot pass goes back to the lead and the user: "
            "escalating is a success, an edited log is not (F97)."
        )
    if act := checked(outward, event, entry):
        return _outward(event, act)
    if event.get("agent_id"):
        from .agent import agent_pre

        return checked(agent_pre, event, session, entry) or 0
    return _lead_dispatch(event, entry)


def _post_tool_use_line(
    event: Mapping[str, object], session: str, entry: RegistryEntry
) -> str | None:
    """Return the unthrottled PostToolUse line: the lead's own edits or the tally."""
    tool = event.get("tool_name")
    if tool in EDITS:
        from .lead_edits import lead_edits

        if line := checked(lead_edits, event, session, entry):
            return line
    if tool == "AskUserQuestion":
        from .inject import took

        return checked(took, event, entry)
    return None


def _claim(session: str) -> bool:
    """Return whether this hook claimed the session's current throttle window.

    The window is the time in THROTTLE_S slices. Its claim file is created exclusively,
    so of parallel hooks exactly one wins it. A claim of the previous window less than
    THROTTLE_S old keeps the gap, and one that cannot be read admits nobody. The claims
    two windows old and older are removed.
    """
    w = int(time.time()) // THROTTLE_S
    here = REGISTRY / f"{session}.{w}.checked"
    if here.exists():
        return False
    try:
        age = time.time() - (REGISTRY / f"{session}.{w - 1}.checked").stat().st_mtime
    except FileNotFoundError:
        age = THROTTLE_S
    except OSError:
        return False
    if age < THROTTLE_S:
        return False
    try:
        os.close(os.open(here, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return False
    for old in REGISTRY.glob(f"{session}.*.checked"):
        mid = old.name[len(session) + 1 : -len(".checked")]
        if mid.isdigit() and int(mid) <= w - 2:
            old.unlink(missing_ok=True)
    return True


def _quiet(name: str, event: Mapping[str, object], session: str) -> bool:
    """Return whether an event of the lead injects no state.

    A SessionStart other than compact and resume, a prompt that is no agent's return,
    and a PostToolUse whose throttle window another hook of the session already claimed.
    """
    if name == "SessionStart" and event.get("source") not in ("compact", "resume"):
        return True
    if name == "UserPromptSubmit" and not is_return(event.get("prompt")):
        return True
    if name == "PostToolUse":
        return not _claim(session)
    return False


def _reread(
    event: Mapping[str, object], a: RouteArgs, marker: Mapping[str, object]
) -> str:
    """Return what a compacted or resumed session re-reads before its next action."""
    from .inject import stage_docs
    from .report import HANDOFFS

    stage, docs = stage_docs(a, marker.get("rung"))
    base = pathlib.Path(a.planning_dir)
    handoff = " and ".join(
        str(base / n) for n in HANDOFFS if (base / n).exists()
    ) or str(base / HANDOFFS[0])
    where = f"for Stage {stage} (going by the planning dir) {docs}, in {SKILL_DIR}"
    return (
        f"Read {SKILL} in full — a resumed session has no skill text — then {handoff} "
        f"and, {where}"
        if event.get("source") == "resume"
        else f"Re-read {handoff} and, {where} (the skill text is re-attached; if it "
        f"ends truncated, Read {SKILL} in full)"
    )


def _delta(old: str | None, body: str, since: str, text: str) -> str:
    """Return the report's lines that changed since the last injection, "" for none."""
    if old == body:
        return ""
    if old is None:
        return f"route_state.py (hook) — the in-flight block's state:\n{text}"
    before = set(old.splitlines())
    now_lines = body.splitlines()
    new = [ln for ln in now_lines if ln not in before]
    # a flag is indented two spaces; a lane's or a file's line four
    cleared = sum(
        1
        for ln in before - set(now_lines)
        if ln.startswith("  ") and not ln.startswith("    ")
    )
    return (
        f"route_state.py (hook) — changed between {since} and "
        f"{time.strftime('%m-%d %H:%M')}:\n"
        + "\n".join(new)
        + (f"\n  ({cleared} earlier flags cleared)" if cleared else "")
    )


def _seed(path: pathlib.Path, last: pathlib.Path) -> pathlib.Path | None:
    """Return the file a session's delta starts from: its own `.last`, else a seed.

    The seed is the newest of the route's shared `.last` and the other sessions' ones,
    so a successor lead hears what changed instead of the whole report again. It is
    only read, never written.
    """
    if last.exists():
        return last
    seeds = [
        p
        for p in (path.with_suffix(".last"), *path.parent.glob(f"{path.stem}.*.last"))
        if p != last and p.exists()
    ]
    return max(seeds, key=lambda p: p.stat().st_mtime, default=None)


def _inject_state(
    name: str,
    event: Mapping[str, object],
    session: str,
    entry_path: pathlib.Path,
    entry: RegistryEntry,
) -> int:
    """Inject the round's state, or the lines of it that changed, into the context."""
    try:
        path = pathlib.Path(entry["marker"])
        marker = as_dict(parse_json(path.read_text())) or {}
        a = route_args(marker)
    except (OSError, ValueError, KeyError):
        return 0
    from .inject import budget_line, skill_changes
    from .report import report

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _ = report(a, fresh=False, extra=budget_line(a.planning_dir, marker, a.phase))
    text = buf.getvalue().rstrip()
    body = text.partition("\n")[2]
    last = path.with_name(f"{path.stem}.{session}.last")
    seed = _seed(path, last)
    old = seed.read_text() if seed else None
    since = (
        time.strftime("%m-%d %H:%M", time.localtime(seed.stat().st_mtime))
        if seed and old
        else ""
    )
    _ = last.write_text(body)
    changed = skill_changes(entry_path, entry)
    note = (
        f"decision-spec-plan changed since this session read it: {', '.join(changed)} "
        f"(in {SKILL_DIR}). The skill text in your context is the old one — Read "
        "SKILL.md in full, then each changed file your current stage uses, before the "
        "next action (F78).\n"
        if changed
        else ""
    )
    if name == "SessionStart":
        emit(
            name,
            f"{note}decision-spec-plan route active. Before the next action: "
            f"{_reread(event, a, marker)}.\n"
            f"route_state.py (hook) — the in-flight block's state:\n{text}",
        )
        return 0
    delta = _delta(old, body, since, text)
    if note or delta:
        emit(name, (note + delta).rstrip())
    return 0


def _agent_stop(event: Mapping[str, object], session: str) -> int:
    """Send an agent ending its turn back to its own running job (F92)."""
    from .jobs import own_wait

    try:
        return own_wait(event, session)
    except Exception:  # noqa: BLE001 — a broken check never holds an agent
        return 0


def _registered(
    name: str, event: Mapping[str, object], session: str, entry_path: pathlib.Path
) -> int:
    """Run the hooks of a session `--activate` registered."""
    # --activate wrote the entry; a check that finds a key missing fails on its own
    entry = cast("RegistryEntry", cast("object", load_json(entry_path)))
    if name in ("SubagentStop", "TeammateIdle"):
        return _agent_stop(event, session)
    if name == "PreToolUse":
        return _pre_tool_use(event, session, entry)
    if event.get("agent_id"):
        return 0
    if name == "PostToolUse" and (line := _post_tool_use_line(event, session, entry)):
        emit(name, line)
        return 0
    if _quiet(name, event, session):
        return 0
    return _inject_state(name, event, session, entry_path, entry)


def hook() -> int:
    """Run the hooks, for a session `--activate` registered.

    PreToolUse holds the lead's `exec-` dispatches to the recorded budget, gives each
    one it allows an ETA from the route's finished groups and, inside an `exec-` agent,
    applies the context stop and the rulings check; it asks the user before the lead's
    outward action on the hosted repository and refuses an agent's, and refuses a review
    comment while the review's decision document fails its check (F104). The other
    events put the round's state into the lead's context, never a subagent's or
    teammate's (agent_id): PostToolUse checks at most every THROTTLE_S and, like an
    agent's return as a prompt, injects only the lines that changed since this session's
    last injection — nothing when none did. SessionStart (compact, resume) injects the
    whole report and what to re-read. Each names the skill's files changed since the
    session read them. After an AskUserQuestion, unthrottled, PostToolUse tallies
    whether each answer took the recommended option, and says so past TAKE_RATE of the
    last TAKE_WINDOW. After the lead's own edit of the repository once the phase has a
    budget, unthrottled, it says at the second and every tenth after that execution is a
    fresh group's (F68).

    Returns:
        The hook's exit code: 2 sends an agent back to its running job, else 0.
    """
    try:
        event = as_dict(parse_json(sys.stdin.read()))
    except ValueError:
        return 0
    if event is None:
        return 0
    session = str(event.get("session_id") or "")
    entry_path = REGISTRY / f"{session}.json"
    name = str(event.get("hook_event_name", ""))
    if session and name == "PreToolUse" and unrouted(event, entry_path):
        return deny(
            "this session has no active decision-spec-plan route, so the route's "
            "budget gate, push review and state reports are all off; dsp-deep and "
            "dsp-mechanical serve only that route. Load the decision-spec-plan skill "
            "with the Skill tool and follow SKILL.md — the rung announcement with its "
            f"cost, then `python3 {SCRIPT} <planning-dir> --phase <P> --repo "
            "<repo> --activate --rung <S|M|L>` — before you dispatch (F79)."
        )
    if (
        name == "UserPromptSubmit"
        and not event.get("agent_id")
        and not entry_path.exists()
    ):
        from .inject import unloaded

        if line := checked(unloaded, event):
            emit(name, line)
            return 0
    if not session or not entry_path.exists():
        return 0
    return _registered(name, event, session, entry_path)
