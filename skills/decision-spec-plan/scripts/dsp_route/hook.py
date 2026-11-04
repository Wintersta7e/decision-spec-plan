"""`route_state.py --hook`: every hook event of a session `--activate` registered, dispatched to
the check or report it calls for.

It runs on every tool call of every session, most with no route, so each branch imports only the
modules it uses: a module is a few milliseconds to load from a slow mount, and importing them all
up front made the no-route call 70% slower."""

import contextlib
import io
import json
import pathlib
import sys
import time

from .common import (
    EXEC,
    REGISTRY,
    RETURNS,
    SCRIPT,
    SKILL,
    SKILL_DIR,
    checked,
    deny,
    emit,
    load_json,
    parser,
)

THROTTLE_S = 20
# The agent types only the route dispatches (agents/dsp-*.md), bare or plugin-qualified.
ROUTE_AGENTS = ("dsp-deep", "dsp-mechanical")


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
    session read them. After an AskUserQuestion, unthrottled, PostToolUse tallies whether each
    answer took the recommended option, and says so past TAKE_RATE of the last TAKE_WINDOW.
    After the lead's own edit of the repository once the phase has a Stage 5 budget, unthrottled,
    it says at the second and every tenth after that execution is a fresh group's (F68).
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
            f"`python3 {SCRIPT} <planning-dir> --phase <P> --repo "
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
    entry = load_json(entry_path)
    if name in ("SubagentStop", "TeammateIdle"):
        from .jobs import own_wait

        try:
            return own_wait(event, session)
        except Exception:  # noqa: BLE001 — a broken check never holds an agent
            return 0
    if name == "PreToolUse":
        from .gate_log import gate_log_edit
        from .outward import outward

        if how := checked(gate_log_edit, event):
            return deny(
                f"{how}: a gate log holds only what the gate printed — it is the evidence a "
                "push and a lane return are judged on. Re-run the gate through the runner, "
                "which writes every line the push check reads (`<skill-dir>/scripts/gate.py "
                "<planning-dir> <name> -- '<gate>'`), or copy a real run's output in. A gate "
                "that cannot pass goes "
                "back to the lead and the user: escalating is a success, an edited log is not "
                "(F97)."
            )
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
            from .agent import agent_pre

            return checked(agent_pre, event, session, entry) or 0
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
    if name == "PostToolUse" and event.get("tool_name") in (
        "Edit",
        "Write",
        "MultiEdit",
        "NotebookEdit",
    ):
        from .lead_edits import lead_edits

        if line := checked(lead_edits, event, session, entry):
            emit(name, line)
            return 0
    if name == "PostToolUse" and event.get("tool_name") == "AskUserQuestion":
        from .inject import took

        if line := checked(took, event, entry):
            emit(name, line)
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
    from .inject import budget_line, skill_changes, stage_docs
    from .report import HANDOFFS, report

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
        base = pathlib.Path(a.planning_dir)
        handoff = " and ".join(
            str(base / n) for n in HANDOFFS if (base / n).exists()
        ) or str(base / HANDOFFS[0])
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
        # a flag is indented two spaces; a lane's or a file's line four
        cleared = sum(
            1
            for ln in before - set(now_lines)
            if ln.startswith("  ") and not ln.startswith("    ")
        )
        delta = (
            f"route_state.py (hook) — changed between {since} and "
            f"{time.strftime('%m-%d %H:%M')}:\n"
            + "\n".join(new)
            + (f"\n  ({cleared} earlier flags cleared)" if cleared else "")
        )
    if note or delta:
        emit(name, (note + delta).rstrip())
    return 0
