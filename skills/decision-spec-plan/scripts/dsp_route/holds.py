"""The PreToolUse holds on the lead's dispatches in an active route: a harvester at rung S (F87),
the decision ledger, and the Stage 5 budget with each allowed dispatch's ETA (F74, F83). The hold
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
    deny,
    emit,
    load_json,
    parser,
    routes,
)
from .transcript import (
    event_transcript,
    finished_spans,
    session_transcripts,
    since_budget,
)

# The agents a Stage 5 budget prices: task groups and integrators, a test verifier, the seven sins
# at the phase's end (`<sin>-<review name>`, sins/lead.md).
WAVE_AGENT = re.compile(
    rf"{EXEC}|verify-|(?:pride|greed|lust|envy|gluttony|wrath|sloth)-"
)


def leads(event, marker):
    """The route's lead transcripts: this session's and any other session registered to it."""
    own = event_transcript(event)
    found = [own] if own else []
    for sid, e in routes():
        if e.get("marker") == str(marker):
            found += [p.resolve() for p in session_transcripts(sid)]
    return list(dict.fromkeys(found))


def spend(paths, since):
    """Units these leads, their wave's agents (WAVE_AGENT) and the hook sessions beside them spent
    from `since` on — but a lead's prompt written again after it sat idle past the cache's life:
    that is the wait for the user's answer, and one such rewrite after a 3 h wait tipped a wave
    over (F93). Another phase's harvest and decision round in the same lead session, and re-plan
    agents, are not the wave's: they made 8 of 20 over-budget holds false (F74)."""
    import usage_report

    total, projects = 0.0, set()
    for path in paths:
        lead, agents, sdk = usage_report.route_cost(path, since)
        total += lead["units"] - lead["idle"]
        total += sum(a["units"] for a in agents if WAVE_AGENT.match(a["name"]))
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
    """The lead dispatching an `exec-` agent: held until the wave's budget is recorded and
    answered, and once the wave runs more than 25% over it (execution.md, F74); an allowed one
    gets its ETA (F83)."""
    path = pathlib.Path(entry["marker"])
    marker = json.loads(path.read_text())
    phase = parser().parse_args(marker["args"]).phase
    budgets = [b for b in marker.get("budgets", []) if b.get("phase") == phase]
    record = (
        f'`python3 {SCRIPT} --budget "<wave>" --estimate <M> --groups <exec- agents>`'
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
