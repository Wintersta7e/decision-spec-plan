"""Claude Code's session transcripts, read for the hooks: the only module that knows where they
live and the shape of their JSONL records — record types, `message.content` tool_use and
tool_result blocks, `usage`, timestamps, `origin.kind`, `toolUseResult`, task notifications,
agent transcripts and their meta files. usage_report.py prices them."""

import datetime
import json
import os
import pathlib
import re

from .common import EXEC, REGISTRY, git, load_json

PROJECTS = pathlib.Path.home() / ".claude" / "projects"


def now():
    """UTC in the transcripts' format, so the two compare as strings."""
    stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


def epoch(stamp):
    """Seconds since the epoch of an ISO timestamp (UTC when it names no zone), or None."""
    try:
        moment = datetime.datetime.fromisoformat(stamp)
    except (AttributeError, TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return moment.timestamp()


def timestamp(text):
    """`--since` in the transcripts' format (UTC, milliseconds, `Z`): requests() compares the two as strings."""
    seconds = epoch(text)
    if seconds is None:
        raise ValueError(text)
    moment = datetime.datetime.fromtimestamp(seconds, datetime.UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def session_transcripts(session):
    """The lead transcripts of a session id, one per project it ran in."""
    return list(PROJECTS.glob(f"*/{session}.jsonl"))


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


def requests(path, since, until=None):
    """Each API request a transcript records in [since, until], once per (message id, request id)
    since streamed snapshots repeat it: its timestamp, model, effort and token counts, the seconds
    since the request before it and whether the user prompted or answered in between — both
    measured against every request, in the span or not."""
    seen = set()
    previous = None
    asked = False  # the user prompted or answered since the last request
    for record in read_records(path):
        stamp = record.get("timestamp")
        message = record.get("message")
        if record.get("type") != "assistant" or not isinstance(message, dict):
            asked = asked or human(record)
            continue
        usage = message.get("usage")
        key = (message.get("id"), record.get("requestId"))
        if not usage or key in seen or message.get("model") == "<synthetic>":
            continue
        seen.add(key)
        at, before = epoch(stamp), epoch(previous)
        gap = at - before if at is not None and before is not None else 0
        previous = stamp or previous
        waited, asked = asked, False
        if stamp and ((since and stamp < since) or (until and stamp > until)):
            continue
        yield {
            "stamp": stamp,
            "model": message.get("model"),
            "effort": record.get("effort"),
            "fresh": usage.get("input_tokens", 0) or 0,
            "write_all": usage.get("cache_creation_input_tokens", 0) or 0,
            "write_1h": (usage.get("cache_creation") or {}).get(
                "ephemeral_1h_input_tokens", 0
            )
            or 0,
            "read": usage.get("cache_read_input_tokens", 0) or 0,
            "out": usage.get("output_tokens", 0) or 0,
            "gap": gap,
            "waited": waited,
        }


def tool_calls(path, since, until=None):
    """(context, name, input) of each tool call a transcript records in [since, until], once per
    call id: context is the prompt's tokens at the latest request by then."""
    seen = set()
    context = 0
    for record in read_records(path):
        stamp = record.get("timestamp")
        if stamp and ((since and stamp < since) or (until and stamp > until)):
            continue
        message = record.get("message")
        if record.get("type") != "assistant" or not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if usage and message.get("model") != "<synthetic>":
            context = sum(
                usage.get(k, 0) or 0
                for k in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                )
            )
        for block in tool_uses(record):
            if block.get("id") in seen:
                continue
            seen.add(block.get("id"))
            yield context, block.get("name"), block.get("input") or {}


ENTRYPOINT = re.compile(r'"entrypoint":"([^"]*)"')
CWD = re.compile(r'"cwd":"([^"]*)"')


def entrypoint(path):
    """How a session was started (`cli`, `sdk-*`), from its transcript's first lines."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _, line in zip(range(20), fh):
            if m := ENTRYPOINT.search(line):
                return m.group(1)
    return ""


def common_dir(path):
    """The git common dir of the first `cwd` a transcript records, or None (gone, or no repo)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _, line in zip(range(20), fh):
            if m := CWD.search(line):
                rc, out = git(
                    m.group(1),
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                )
                return out if rc == 0 else None
    return None


def event_transcript(event):
    """The transcript file a hook event names, resolved, or None."""
    path = pathlib.Path(event.get("transcript_path") or "")
    return path.resolve() if path.suffix == ".jsonl" and path.is_file() else None


def find_lead(project, session):
    """The lead transcript usage_report.py reports. `project` is the transcript dir or the
    project's own directory (a lead passed that, live), None for the working directory's; without
    a session id, the running session's own if it is in this project: the newest transcript may be
    a hook's or another lead's."""
    if not (project and any(project.glob("*.jsonl"))):
        slug = re.sub(
            r"[^A-Za-z0-9]", "-", str((project or pathlib.Path.cwd()).resolve())
        )
        project = PROJECTS / slug
    own = project / f"{os.environ.get('CLAUDE_CODE_SESSION_ID')}.jsonl"
    if session:
        return project / f"{session}.jsonl"
    if os.environ.get("CLAUDE_CODE_SESSION_ID") and own.exists():
        return own
    candidates = sorted(project.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else project / "missing.jsonl"


def project_sessions(lead, after):
    """The session transcripts of `lead`'s project last written at or after `after` (seconds)."""
    return [p for p in lead.parent.glob("*.jsonl") if p.stat().st_mtime >= after]


def subagent_transcripts(lead, since):
    """(path, label, name) of each subagent transcript of a lead's written since `since`: the label
    is its description or type, the name the one it was dispatched with."""
    floor = epoch(since)
    for path in sorted((lead.parent / lead.stem / "subagents").glob("agent-*.jsonl")):
        if floor and path.stat().st_mtime < floor:
            continue
        meta_path = path.with_name(path.stem + ".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        label = meta.get("description") or meta.get("agentType") or path.stem
        yield path, label, str(meta.get("name") or meta.get("agentType") or "")


def sdk_transcripts(project, lead, since):
    """Sessions with an `sdk-*` entrypoint in the project dir or a worktree's (`<project>-*`).

    A route's lead (registered by `route_state.py --activate`) is a lead even when headless
    (`sdk-cli`). A `<project>-*` dir counts only for the sessions that ran in the lead's
    repository: one named alike, or whose repository is unknown, is another project — counted,
    its headless sessions held a route's wave over a budget it had not spent."""
    floor = epoch(since)
    repo = common_dir(lead)
    for directory in [project, *sorted(project.parent.glob(project.name + "-*"))]:
        for path in sorted(directory.glob("*.jsonl")):
            if path == lead or (floor and path.stat().st_mtime < floor):
                continue
            if (REGISTRY / f"{path.stem}.json").exists():
                continue
            if directory != project and (repo is None or common_dir(path) != repo):
                continue
            if entrypoint(path).startswith("sdk"):
                yield path


# The checks that read each record shape, named as --activate reports them. Each fails open on a
# shape it cannot find, so a format change turns them off without a word (shape_line).
BUDGET, EARLIER, ETAS = "the budget hold", "--budget's earlier-answer credit", "ETAs"
CONTEXT, RULINGS, JOBS = "the context stop", "the rulings check", "the own-jobs wait"
SHAPES = {
    "parseable timestamps": (BUDGET, ETAS, RULINGS, EARLIER),
    "tool_use blocks": (BUDGET, RULINGS, JOBS),
    "tool_result blocks": (BUDGET, JOBS),
    "usage": (BUDGET, CONTEXT),
    "message ids": (BUDGET,),
    "stop_reason": (ETAS, EARLIER),
    "toolUseResult": (JOBS, EARLIER),
    "prompts marked origin.kind human": (BUDGET,),
}


def shape_gaps(path):
    """The SHAPES keys a lead transcript lacks. A shape only some records show is wanted only where
    one is due: a tool result once a call before the latest turn exists (the --activate call
    itself has none yet), a call and toolUseResult once a tool result does, and a typed prompt unless the
    session is headless (an `sdk-*` entrypoint), which types none. Nothing is due before the
    model's first reply (an --activate the user typed with `!`), found by the API's role rather
    than the record type, so a renamed type still counts as a reply."""
    found, calls, results = set(), {}, set()
    latest, headless, resulted, replied = None, False, False, False
    for r in read_records(path):
        headless = headless or str(r.get("entrypoint") or "").startswith("sdk")
        if human(r):
            found.add("prompts marked origin.kind human")
        message = r.get("message")
        replied = replied or (
            isinstance(message, dict) and message.get("role") == "assistant"
        )
        if r.get("type") == "assistant" and isinstance(message, dict):
            latest = message.get("id")
            if epoch(r.get("timestamp")) is not None:
                found.add("parseable timestamps")
            if (
                isinstance(message.get("usage"), dict)
                and "input_tokens" in message["usage"]
            ):
                found.add("usage")
            if latest:
                found.add("message ids")
            if "stop_reason" in message:
                found.add("stop_reason")
            for block in tool_uses(r):
                if (
                    block.get("id")
                    and block.get("name")
                    and isinstance(block.get("input"), dict)
                ):
                    found.add("tool_use blocks")
                    calls[block["id"]] = latest
        ids = {b.get("tool_use_id") for b in tool_uses(r, "tool_result")}
        if ids:
            results |= ids
            resulted = True
            if "toolUseResult" in r:
                found.add("toolUseResult")
    if not replied:
        return []
    earlier = {c for c, turn in calls.items() if turn != latest}
    if not earlier or earlier & results:
        found.add("tool_result blocks")
    if not resulted:
        found |= {"toolUseResult", "tool_use blocks"}
    if headless:
        found.add("prompts marked origin.kind human")
    return [s for s in SHAPES if s not in found]


def shape_line(session):
    """The line --activate prints when this session's transcript lacks a shape the hooks read,
    naming the checks that are off; None when it has them all or does not exist yet."""
    paths = session_transcripts(session)
    if not paths:
        return None
    path = max(paths, key=lambda p: p.stat().st_mtime)
    gaps = shape_gaps(path)
    if not gaps:
        return None
    off = [
        c
        for c in (BUDGET, EARLIER, ETAS, CONTEXT, RULINGS, JOBS)
        if any(c in SHAPES[g] for g in gaps)
    ]
    return (
        f"transcript format: {path.name} has no {', '.join(gaps)}, so these checks are off: "
        f"{', '.join(off)} — Claude Code changed its transcript; update the plugin"
    )


def skill_loaded(transcript_path):
    """Whether the transcript at `transcript_path` loaded the decision-spec-plan skill."""
    try:
        text = pathlib.Path(transcript_path).read_text(errors="replace")
    except OSError:
        text = ""
    # every load, by the Skill tool or a slash command, injects the skill's base directory
    return bool(
        re.search(
            r'"skill":\s*"(?:[\w-]+:)?decision-spec-plan"'
            r"|Base directory for this skill: \S*decision-spec-plan",
            text,
        )
    )


def answered_this_turn(session, estimate):
    """When the user answered an AskUserQuestion in the lead's current turn that names the
    figure (`<estimate>M`), else None.

    Why: a lead that asked "raise the budget to 45M?" and recorded it after the answer was held
    for a second answer, and that question sat 1 h 52 min while finished groups waited (F93)."""
    answered = None
    for path in session_transcripts(session):
        for r in read_records(path):
            message = r.get("message")
            result = r.get("toolUseResult")
            if r.get("type") == "assistant" and isinstance(message, dict):
                if message.get("stop_reason") == "end_turn":
                    answered = None
            elif isinstance(result, dict) and "answers" in result:
                # unescaped: `≈5M` dumped as `≈5M` read as 22485M
                figures = re.findall(
                    r"(\d+(?:\.\d+)?)\s*M\b", json.dumps(result, ensure_ascii=False)
                )
                if any(abs(float(f) - estimate) < 1e-9 for f in figures):
                    answered = r.get("timestamp")
    return answered


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


def finished_spans(paths, want):
    """(name, minutes) of each finished agent of these lead transcripts whose name `want`
    accepts: from its first record to its last turn that ended with no tool call pending."""
    spans = []
    for path in paths:
        for meta in (path.parent / path.stem / "subagents").glob("agent-*.meta.json"):
            agent = str(load_json(meta).get("name") or "")
            if not want(agent):
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
            start, end = epoch(first), epoch(last)
            if start is not None and end is not None:
                spans.append((agent, (end - start) / 60))
    return spans


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


def started_jobs(transcript):
    """The background shells and monitors an agent's transcript started, and those it saw end.

    Returns (jobs, ended, tasks): jobs as (id, what, output file or None for a monitor), the ids
    a task notification or a TaskStop of its own ended, and the directory a shell's output was
    written to (None when no shell started)."""
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
    return jobs, ended, tasks


def tasks_dir(transcript, session):
    """Where an agent's monitors write their output when no shell of its said where.

    A monitor's output sits beside the shells', mostly in
    /tmp/claude-<uid>/<project>/<session>/tasks — one team's sat under another id."""
    return pathlib.Path(
        f"/tmp/claude-{os.getuid()}/{transcript.parents[2].name}/{session}/tasks"
    )


def agent_transcript(event, session, agent):
    name = f"agent-{agent}.jsonl"
    given = pathlib.Path(event.get("transcript_path") or "")
    candidates = [given] if given.name == name else []
    if given.suffix == ".jsonl":
        candidates.append(given.parent / given.stem / "subagents" / name)
    candidates += PROJECTS.glob(f"*/{session}/subagents/{name}")
    return next((p for p in candidates if p.is_file()), None)


def agent_name(transcript):
    """The name an agent was dispatched with, from its transcript's meta file, or None."""
    return load_json(transcript.with_name(transcript.stem + ".meta.json")).get("name")


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


def last_reads(transcript, files, tools):
    """{file: when the agent last named it in a call of one of `tools`} for these files."""
    last = {}
    for r in read_records(transcript):
        # An api-request-blob record repeats an earlier tool_use with no timestamp; letting it
        # overwrite would erase the read the timestamped record already counted.
        stamp = epoch(r.get("timestamp") or "")
        if stamp is None:
            continue
        for block in tool_uses(r):
            said = json.dumps(block.get("input"))
            for f in files:
                if block.get("name") in tools and f.name in said:
                    last[f] = stamp
    return last
