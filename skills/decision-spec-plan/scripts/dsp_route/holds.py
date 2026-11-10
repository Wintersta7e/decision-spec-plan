"""The PreToolUse holds on the lead's dispatches in an active route: a harvester at rung S (F87),
the decision ledger, and the route's budget with each allowed dispatch's ETA (F74, F83). The hold
on a route agent with no route (F79) is the hook's own: it runs before any route is read."""

import contextlib
import io
import json
import pathlib
import re
import statistics

from .common import (
    EXEC,
    LEDGER_CHECKS,
    PLAN_ID,
    SCRIPT,
    SLACK,
    budgets,
    deny,
    emit,
    load_json,
    parser,
    routes,
    save_budget,
)
from .transcript import (
    answered_since,
    ended_run,
    event_transcript,
    finished_spans,
    session_transcripts,
)

# The phase an agent's name names (`harvest-code-p9`, `exec-p9-01-a`, `dec-p9-D1`): that phase's
# work, not another's budget's.
PHASE_OF = re.compile(r"(?<![A-Za-z0-9])p(\d+)(?=-|$)")


def leads(event, marker):
    """The route's lead transcripts: this session's and any other session registered to it."""
    own = event_transcript(event)
    found = [own] if own else []
    for sid, e in routes():
        if e.get("marker") == str(marker):
            found += [p.resolve() for p in session_transcripts(sid)]
    return list(dict.fromkeys(found))


def dead_recipient(event, entry):
    """The lead's SendMessage to an agent whose run ended: the refusal, else None (F64)."""
    if event.get("tool_name") != "SendMessage":
        return None
    to = str((event.get("tool_input") or {}).get("to") or "")
    ended = to and ended_run(leads(event, pathlib.Path(entry["marker"])), to)
    if not ended:
        return None
    stamp, reason = ended
    return (
        f"{to} stopped for good at {stamp} ({reason or 'its run failed'}): its idle notice "
        "says its run ended, and a message never reaches it — after a spend limit one lead "
        "messaged such an agent twice and reported it running for 20 min. Dispatch a fresh "
        "agent with its brief, told to continue from its file's end (SKILL.md, F64)."
    )


def spend(paths, since, phase):
    """Units these leads, their agents and the hook sessions beside them spent from `since` on: the
    route's budget prices the lead and every review and agent (F74) — but a lead's prompt written
    again after it sat idle past the cache's life: that is the wait for the user's answer, and one
    such rewrite after a 3 h wait tipped a wave over (F93). An agent whose name names another
    phase (`harvest-code-p9`, `exec-p9-01-a`) is that phase's: another phase's harvest and decision
    round in the same lead session made 8 of 20 over-budget holds false (F74)."""
    import usage_report

    total, projects = 0.0, set()
    for path in paths:
        lead, agents, sdk = usage_report.route_cost(path, since)
        total += lead["units"] - lead["idle"]
        total += sum(
            a["units"]
            for a in agents
            if set(PHASE_OF.findall(a["name"])) <= {str(phase)}
        )
        if path.parent not in projects:
            projects.add(path.parent)
            total += sum(s["units"] for s in sdk)
    return total


def s_harvester(event, entry):
    """The lead dispatching a harvester on a rung-S route, where it harvests itself (F87): a
    harvest named in the dispatch, not a task group or verifier whose work names one (`Fix
    harvest-date parsing`) or a review of harvested findings."""
    if event.get("tool_name") != "Agent":
        return False
    dispatch = event.get("tool_input") or {}
    name = str(dispatch.get("name") or "")
    if name.startswith(("exec-", "verify-")):
        return False
    text = f"{name} {dispatch.get('description') or ''}"
    rung = load_json(pathlib.Path(entry["marker"])).get("rung")
    return rung == "S" and bool(
        re.search(r"\bharvest(?:ers?|ing|s)?\b", text, re.IGNORECASE)
    )


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
        # the phase's, a review round's (`<round>/verify/`), a sins run's or its slice's
        files = [
            *d.glob("**/verify/*.prompt.md"),
            *reviews.glob("**/verify/*.prompt.md"),
        ]
        written = {p.read_text(errors="replace").strip() for p in files}
        if prompt not in written:
            return (
                "a verifier's prompt is the file `decision_check.py --verifier R<n> --sha "
                "<commit>` wrote, unchanged: the finding and the commit, with no SETTLED list, "
                f"rationale or reviewer name ({script}; failure-modes F86)."
            )
        return None
    ledger = marker.get("ledger") or {}
    # the phase's index when bound, and each review round's own index unless it predates the
    # phase's first activation
    rounds = [d] if ledger.get(phase) else []
    rounds += [
        i.parent
        for i in sorted(d.glob("*/00-index.md"))
        if ledger.get(f"{phase}/{i.parent.name}", True)
    ]
    held = []
    for r in rounds:
        if not (r / "00-index.md").exists():
            continue
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            legacy = (
                [] if ledger.get(f"{phase}#checks") == LEDGER_CHECKS else ["--legacy"]
            )
            code = decision_check.main(
                [str(r), "--rung", marker.get("rung") or "M", *legacy]
            )
        if code == 1:
            held.append(
                f"the decision ledger fails `{script} {r}` — fix each line, then dispatch:\n"
                + out.getvalue().strip()
            )
    return "\n".join(held) or None


def gate_dispatch(event, entry):
    """The lead dispatching an `exec-` agent: held until the route's budget is recorded and the
    user answered it in the lead session that recorded it — at S, recorded is enough — and once
    the route's spend since passes 125% of it (execution.md, F74); an allowed one gets its ETA
    (F83). One budget a route: a hand-over to a new lead session keeps it (F74)."""
    path = pathlib.Path(entry["marker"])
    marker = json.loads(path.read_text())
    phase = parser().parse_args(marker["args"]).phase
    found = budgets(entry["planning_dir"], marker, phase)
    record = f'`python3 {SCRIPT} --budget "<route>" --estimate <M>`'
    if not found:
        return deny(
            f"phase {phase} has no budget. Price the route's work left per costs.md (the lead, "
            "every review and agent of the stages left, the task groups at the group median, a "
            f"seven-sins review at L's phase end), record it with {record}, tell the user the "
            "figure and wait for their answer — at S, tell them and go on (execution.md)."
        )
    b = found[-1]
    name = str((event.get("tool_input") or {}).get("name") or "")
    if set(PHASE_OF.findall(name)) - {str(phase)}:
        # spend() leaves another phase's agents out, so one dispatched here would run uncounted
        return deny(
            f"{name} names another phase than this route's phase {phase}: activate that phase "
            "(`--activate --phase <P>`) and record its budget first (F74)."
        )
    paths = leads(event, path)
    head = f"budget '{b['label']}' ({b['estimate']:g}M, recorded {b['at']})"
    if not (b.get("answered") or marker.get("rung") == "S"):
        # Only the recording session's transcripts: a new session's "read the handoff and
        # proceed" once approved a figure that session never told the user (F74). A session
        # with no prompt of the user's answers only its own dispatches (headless `claude -p`).
        recorder = b.get("session") or ""
        rec = session_transcripts(recorder)
        answered = rec and answered_since(rec, b["at"])
        if answered == b["at"] and recorder != event.get("session_id"):
            answered = None
        if not answered:
            return deny(
                f"{head}: the user has not answered it in the lead session that recorded it. "
                "Tell them the figure and wait for their answer before dispatching"
                + (
                    f" — or, the user gone from that session, record it again from this one "
                    f"with {record}."
                    if b.get("session") != event.get("session_id")
                    else "."
                )
            )
        if answered != b["at"]:
            # a user's answer is kept with the record, so a hand-over to a new lead session asks
            # nothing again; a headless session's pass is its own and is never kept
            save_budget(entry["planning_dir"], marker, {**b, "answered": answered})
    used = spend(paths, b["at"], phase)
    if used > b["estimate"] * 1e6 * SLACK:
        return deny(
            f"{head}: {used / 1e6:.1f}M spent since — more than 25% over. Record the "
            f"remaining work's figure with {record}, tell the user what ran over and why, and "
            "wait for their answer (F74)."
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
    spans = [
        (lane_of(agent), minutes)
        for agent, minutes in finished_spans(
            paths,
            lambda a: a.startswith(EXEC) and a.startswith(EXEC + "wave") == wave,
        )
    ]
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
