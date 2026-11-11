# SPDX-License-Identifier: MIT
"""Claude Code's session transcripts, read for the hooks.

The only module that knows where they live and the shape of their JSONL records — record
types, `message.content` tool_use and tool_result blocks, `usage`, timestamps,
`origin.kind`, `toolUseResult`, task notifications, agent transcripts and their meta
files. usage_report.py prices them.
"""

import datetime as dt
import json
import os
import pathlib
import re
import tempfile
from collections.abc import Callable, Container, Iterable, Iterator, Mapping
from typing import TypedDict

from .common import REGISTRY, StrPath, as_dict, as_list, git, load_json, parse_json

PROJECTS = pathlib.Path.home() / ".claude" / "projects"
# How close a figure in an answer must be to the estimate to name it.
FIGURE_TOLERANCE = 1e-9
# How much of an agent transcript's end context() reads for its latest turn.
TAIL_BYTES = 262_144

Record = dict[str, object]
# (id, what it runs, output file or None for a monitor) of a background job
Job = tuple[str, str | None, str | None]


class Request(TypedDict):
    """One API request of a transcript, as requests() yields it."""

    stamp: str | None
    model: str | None
    effort: str | None
    fresh: int
    write_all: int
    write_1h: int
    read: int
    out: int
    gap: float
    waited: bool


def _text(value: object) -> str | None:
    """Return value when it is a string, else None."""
    return value if isinstance(value, str) else None


def _tokens(usage: Mapping[str, object], key: str) -> int:
    """Return a `usage` token count, 0 when it is missing or no number."""
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def now() -> str:
    """Return UTC in the transcripts' format, so the two compare as strings."""
    stamp = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


def epoch(stamp: object) -> float | None:
    """Return the epoch seconds of an ISO timestamp (UTC when zoneless), or None."""
    if not isinstance(stamp, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.timestamp()


def timestamp(text: str) -> str:
    """Return `--since` in the transcripts' format (UTC, milliseconds, `Z`).

    requests() compares the two as strings.
    """
    seconds = epoch(text)
    if seconds is None:
        raise ValueError(text)
    moment = dt.datetime.fromtimestamp(seconds, dt.UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def session_transcripts(session: str) -> list[pathlib.Path]:
    """Return the lead transcripts of a session id, one per project it ran in."""
    return list(PROJECTS.glob(f"*/{session}.jsonl"))


def read_records(path: StrPath) -> Iterator[Record]:
    """Return each JSON object of a transcript."""
    with pathlib.Path(path).open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = as_dict(parse_json(line))
            except ValueError:
                continue
            if record is not None:
                yield record


def tool_uses(record: Mapping[str, object], kind: str = "tool_use") -> list[Record]:
    """Return the content blocks of a record's message of one type (tool_use)."""
    message = as_dict(record.get("message"))
    content = as_list(message.get("content")) if message is not None else None
    if content is None:
        return []
    return [
        b
        for item in content
        if (b := as_dict(item)) is not None and b.get("type") == kind
    ]


def human(record: Mapping[str, object]) -> bool:
    """Return whether a record is a prompt the user typed or queued, or their answer.

    An answer is one to AskUserQuestion.
    """
    if record.get("isMeta") or record.get("isCompactSummary"):
        return False
    result = as_dict(record.get("toolUseResult"))
    if result is not None and "answers" in result:
        return True
    attachment = as_dict(record.get("attachment"))
    origin = as_dict(
        record.get("origin")
        or (attachment.get("origin") if attachment is not None else None)
    )
    return origin is not None and origin.get("kind") == "human"


def requests(
    path: StrPath, since: str | None, until: str | None = None
) -> Iterator[Request]:
    """Return each API request a transcript records in [since, until].

    Once per (message id, request id) since streamed snapshots repeat it: its timestamp,
    model, effort and token counts, the seconds since the request before it and whether
    the user prompted or answered in between — both measured against every request, in
    the span or not.
    """
    seen: set[tuple[object, object]] = set()
    previous: object = None
    asked = False  # the user prompted or answered since the last request
    for record in read_records(path):
        raw = record.get("timestamp")
        message = as_dict(record.get("message"))
        if record.get("type") != "assistant" or message is None:
            asked = asked or human(record)
            continue
        usage = as_dict(message.get("usage"))
        key = (message.get("id"), record.get("requestId"))
        if not usage or key in seen or message.get("model") == "<synthetic>":
            continue
        seen.add(key)
        at, before = epoch(raw), epoch(previous)
        gap = at - before if at is not None and before is not None else 0
        previous = raw or previous
        waited, asked = asked, False
        stamp = _text(raw)
        if stamp and ((since and stamp < since) or (until and stamp > until)):
            continue
        yield {
            "stamp": stamp,
            "model": _text(message.get("model")),
            "effort": _text(record.get("effort")),
            "fresh": _tokens(usage, "input_tokens"),
            "write_all": _tokens(usage, "cache_creation_input_tokens"),
            "write_1h": _tokens(
                as_dict(usage.get("cache_creation")) or {}, "ephemeral_1h_input_tokens"
            ),
            "read": _tokens(usage, "cache_read_input_tokens"),
            "out": _tokens(usage, "output_tokens"),
            "gap": gap,
            "waited": waited,
        }


def tool_calls(
    path: StrPath, since: str | None, until: str | None = None
) -> Iterator[tuple[int, str | None, Record]]:
    """Return (context, name, input) of each tool call a transcript records in a span.

    The span is [since, until], once per call id: context is the prompt's tokens at the
    latest request by then.
    """
    seen: set[object] = set()
    context = 0
    for record in read_records(path):
        stamp = _text(record.get("timestamp"))
        if stamp and ((since and stamp < since) or (until and stamp > until)):
            continue
        message = as_dict(record.get("message"))
        if record.get("type") != "assistant" or message is None:
            continue
        usage = as_dict(message.get("usage"))
        if usage and message.get("model") != "<synthetic>":
            context = sum(
                _tokens(usage, k)
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
            yield context, _text(block.get("name")), as_dict(block.get("input")) or {}


ENTRYPOINT = re.compile(r'"entrypoint":"([^"]*)"')
CWD = re.compile(r'"cwd":"([^"]*)"')


def entrypoint(path: StrPath) -> str:
    """Return how a session was started (`cli`, `sdk-*`), from its first lines."""
    with pathlib.Path(path).open(encoding="utf-8", errors="replace") as fh:
        for _, line in zip(range(20), fh, strict=False):
            if m := ENTRYPOINT.search(line):
                return m[1]
    return ""


def common_dir(path: StrPath) -> str | None:
    """Return the git common dir of the first `cwd` a transcript records, or None.

    None when it is gone or in no repository.
    """
    with pathlib.Path(path).open(encoding="utf-8", errors="replace") as fh:
        for _, line in zip(range(20), fh, strict=False):
            if m := CWD.search(line):
                rc, out = git(
                    m[1],
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                )
                return out if rc == 0 else None
    return None


def event_transcript(event: Mapping[str, object]) -> pathlib.Path | None:
    """Return the transcript file a hook event names, resolved, or None."""
    path = pathlib.Path(_text(event.get("transcript_path")) or "")
    return path.resolve() if path.suffix == ".jsonl" and path.is_file() else None


def find_lead(project: pathlib.Path | None, session: str | None) -> pathlib.Path:
    """Return the lead transcript usage_report.py reports.

    `project` is the transcript dir or the project's own directory (a lead passed that,
    live), None for the working directory's; without a session id, the running
    session's own if it is in this project: the newest transcript may be a hook's or
    another lead's.
    """
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


def project_sessions(lead: pathlib.Path, after: float) -> list[pathlib.Path]:
    """Return the transcripts of `lead`'s project last written at or after `after`."""
    return [p for p in lead.parent.glob("*.jsonl") if p.stat().st_mtime >= after]


def subagent_transcripts(
    lead: pathlib.Path, since: str | None
) -> Iterator[tuple[pathlib.Path, str, str]]:
    """Return (path, label, name) of each subagent transcript of a lead's since `since`.

    The label is its description or type, the name the one it was dispatched with.
    """
    floor = epoch(since)
    for path in sorted((lead.parent / lead.stem / "subagents").glob("agent-*.jsonl")):
        if floor and path.stat().st_mtime < floor:
            continue
        meta_path = path.with_name(path.stem + ".meta.json")
        meta = (
            as_dict(parse_json(meta_path.read_text())) or {}
            if meta_path.exists()
            else {}
        )
        label = meta.get("description") or meta.get("agentType") or path.stem
        yield path, str(label), str(meta.get("name") or meta.get("agentType") or "")


def sdk_transcripts(
    project: pathlib.Path, lead: pathlib.Path, since: str | None
) -> Iterator[pathlib.Path]:
    """Return sessions with an `sdk-*` entrypoint in the project dir or a worktree's.

    A worktree's is `<project>-*`. A route's lead (registered by `route_state.py
    --activate`) is a lead even when headless (`sdk-cli`). A `<project>-*` dir counts
    only for the sessions that ran in the lead's repository: one named alike, or whose
    repository is unknown, is another project — counted, its headless sessions held a
    route's wave over a budget it had not spent.
    """
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


# The checks that read each record shape, named as --activate reports them. Each fails
# open on a shape it cannot find, so a format change turns them off without a word
# (shape_line).
BUDGET, EARLIER, ETAS = "the budget hold", "--budget's earlier-answer credit", "ETAs"
CONTEXT, RULINGS, JOBS = "the context stop", "the rulings check", "the own-jobs wait"
SHAPES: dict[str, tuple[str, ...]] = {
    "parseable timestamps": (BUDGET, ETAS, RULINGS, EARLIER),
    "tool_use blocks": (BUDGET, RULINGS, JOBS),
    "tool_result blocks": (BUDGET, JOBS),
    "usage": (BUDGET, CONTEXT),
    "message ids": (BUDGET,),
    "stop_reason": (ETAS, EARLIER),
    "toolUseResult": (JOBS, EARLIER),
    "prompts marked origin.kind human": (BUDGET,),
}


def _reply_shapes(
    record: Record, message: Record, calls: dict[object, object]
) -> set[str]:
    """Return the SHAPES keys an assistant record shows; its calls go in calls by id."""
    found: set[str] = set()
    latest = message.get("id")
    if epoch(record.get("timestamp")) is not None:
        found.add("parseable timestamps")
    usage = as_dict(message.get("usage"))
    if usage is not None and "input_tokens" in usage:
        found.add("usage")
    if latest:
        found.add("message ids")
    if "stop_reason" in message:
        found.add("stop_reason")
    for block in tool_uses(record):
        if (
            block.get("id")
            and block.get("name")
            and isinstance(block.get("input"), dict)
        ):
            found.add("tool_use blocks")
            calls[block["id"]] = latest
    return found


def shape_gaps(path: StrPath) -> list[str]:
    """Return the SHAPES keys a lead transcript lacks.

    A shape only some records show is wanted only where one is due: a tool result once
    a call before the latest turn exists (the --activate call itself has none yet), a
    call and toolUseResult once a tool result does, and a typed prompt unless the
    session is headless (an `sdk-*` entrypoint), which types none. Nothing is due before
    the model's first reply (an --activate the user typed with `!`), found by the API's
    role rather than the record type, so a renamed type still counts as a reply.
    """
    found: set[str] = set()
    calls: dict[object, object] = {}
    results: set[object] = set()
    latest: object = None
    headless, resulted, replied = False, False, False
    for r in read_records(path):
        headless = headless or str(r.get("entrypoint") or "").startswith("sdk")
        if human(r):
            found.add("prompts marked origin.kind human")
        message = as_dict(r.get("message"))
        replied = replied or (
            message is not None and message.get("role") == "assistant"
        )
        if r.get("type") == "assistant" and message is not None:
            latest = message.get("id")
            found |= _reply_shapes(r, message, calls)
        ids = {b.get("tool_use_id") for b in tool_uses(r, "tool_result")}
        results |= ids
        resulted = resulted or bool(ids)
        if ids and "toolUseResult" in r:
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


def shape_line(session: str) -> str | None:
    """Return the line --activate prints when the session's transcript lacks a shape.

    It names the checks that are off; None when the transcript has every shape the hooks
    read or does not exist yet.
    """
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
        f"transcript format: {path.name} has no {', '.join(gaps)}, so these checks are "
        f"off: {', '.join(off)} — Claude Code changed its transcript; update the plugin"
    )


def skill_loaded(transcript_path: StrPath) -> bool:
    """Return whether the transcript at `transcript_path` loaded the skill."""
    try:
        text = pathlib.Path(transcript_path).read_text(errors="replace")
    except OSError:
        text = ""
    # every load, by the Skill tool or a slash command, injects the skill's base
    # directory
    return bool(
        re.search(
            r'"skill":\s*"(?:[\w-]+:)?decision-spec-plan"'
            r"|Base directory for this skill: \S*decision-spec-plan",
            text,
        )
    )


def answered_this_turn(session: str, estimate: float) -> str | None:
    """Return when the user answered an AskUserQuestion naming the figure, else None.

    The answer is one in the lead's current turn that names `<estimate>M`.

    Why: a lead that asked "raise the budget to 45M?" and recorded it after the answer
    was held for a second answer, and that question sat 1 h 52 min while finished groups
    waited (F93).
    """
    answered = None
    for path in session_transcripts(session):
        for r in read_records(path):
            message = as_dict(r.get("message"))
            result = as_dict(r.get("toolUseResult"))
            if r.get("type") == "assistant" and message is not None:
                if message.get("stop_reason") == "end_turn":
                    answered = None
            elif result is not None and "answers" in result:
                # unescaped: `≈5M` dumped as `≈5M` read as 22485M
                figures = [
                    m[1]
                    for m in re.finditer(
                        r"(\d+(?:\.\d+)?)\s*M\b", json.dumps(result, ensure_ascii=False)
                    )
                ]
                if any(abs(float(f) - estimate) < FIGURE_TOLERANCE for f in figures):
                    answered = _text(r.get("timestamp"))
    return answered


def answered_since(paths: Iterable[pathlib.Path], since: str) -> str | None:
    """Return when the user first prompted or answered from `since` on, else None.

    In these transcripts of the lead session that recorded a budget. An answer in
    another lead session never counts: "read the handoff and proceed" there once
    approved a figure that session never told (F74). No prompt of the user's anywhere
    (headless `claude -p`, or a changed transcript format) answers at `since`: the hold
    never waits on it.
    """
    ever = False
    for path in paths:
        for r in read_records(path):
            if r.get("type") == "assistant" or not human(r):
                continue
            ever = True
            stamp = _text(r.get("timestamp"))
            if (stamp or "") >= since:
                return stamp or since
    return None if ever else since


def finished_spans(
    paths: Iterable[pathlib.Path], want: Callable[[str], bool]
) -> list[tuple[str, float]]:
    """Return (name, minutes) of each finished agent of these lead transcripts.

    Each agent whose name `want` accepts: from its first record to its last turn that
    ended with no tool call pending.
    """
    spans: list[tuple[str, float]] = []
    for path in paths:
        for meta in (path.parent / path.stem / "subagents").glob("agent-*.meta.json"):
            agent = str(load_json(meta).get("name") or "")
            if not want(agent):
                continue
            first: object = None
            last: object = None
            for r in read_records(
                meta.with_name(meta.name[: -len(".meta.json")] + ".jsonl")
            ):
                first = first or r.get("timestamp")
                message = as_dict(r.get("message"))
                if r.get("type") == "assistant" and message is not None:
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


def ended_run(paths: Iterable[pathlib.Path], name: str) -> tuple[str, str] | None:
    """Return (timestamp, reason) when agent `name`'s run ended, else None.

    Ended: its last idle notice in these lead transcripts says so (`completedStatus:
    failed`) and no agent of that name was dispatched after it. A notice with only
    `idleReason: failed` is an agent stopped at a limit that a message resumes: all
    seven such agents messaged did.
    """
    tag = f'<teammate-message teammate_id="{name}"'
    ended: tuple[str, str] | None = None
    dispatched = ""
    for path in paths:
        for r in read_records(path):
            for block in tool_uses(r):
                if (as_dict(block.get("input")) or {}).get("name") == name:
                    dispatched = max(dispatched, _text(r.get("timestamp")) or "")
            message = as_dict(r.get("message"))
            content = message.get("content") if message is not None else None
            if not (isinstance(content, str) and tag in content):
                continue
            body = content.partition(tag)[2].partition(">")[2]
            try:
                notice = as_dict(parse_json(body.partition("</teammate-message>")[0]))
            except ValueError:
                continue
            if notice is None or notice.get("type") != "idle_notification":
                continue
            stamp = str(notice.get("timestamp") or r.get("timestamp") or "")
            if ended and stamp < ended[0]:
                continue
            ran_out = notice.get("completedStatus") == "failed"
            ended = (stamp, str(notice.get("failureReason") or "")) if ran_out else None
    return ended if ended and ended[0] > dispatched else None


def notified(record: Mapping[str, object]) -> set[str]:
    """Return the ids of the background jobs a task notification here reports ended.

    One with a `<status>` (a monitor's event in between has none).
    """
    attachment = as_dict(record.get("attachment")) or {}
    origin = as_dict(record.get("origin") or attachment.get("origin"))
    if origin is None or origin.get("kind") != "task-notification":
        return set()
    message = as_dict(record.get("message"))
    content = message.get("content") if message is not None else None
    text = str(attachment.get("prompt") or "") + json.dumps(content)
    return {
        m[1]
        for block in re.finditer(
            r"<task-notification>(.*?)</task-notification>", text, re.DOTALL
        )
        if "<status>" in block[1]
        and (m := re.search(r"<task-id>(\w+)</task-id>", block[1]))
    }


def _started_job(record: Record, block: Record, what: str | None) -> Job | None:
    """Return the job a tool result block of record says its call started, or None."""
    text = json.dumps(block.get("content"))
    # The id Claude Code records with a result that started a job: an output that
    # quotes another job's start message (a file or transcript read back) starts none.
    job = r"\w+"
    if "toolUseResult" in record:
        result = as_dict(record["toolUseResult"])
        if result is None:
            return None
        own = result.get("backgroundTaskId") or result.get("taskId")
        if not own:
            return None
        job = re.escape(str(own))
    # run_in_background, or a foreground command moved there at its timeout
    if m := re.search(
        rf"(?:in background with ID: |moved to the background \(ID: )({job})\)?\. "
        r"Output is being written to: (\S+?\.output)",
        text,
    ):
        return m[1], what, m[2]
    if m := re.search(rf"Monitor started \(task ({job})", text):
        return m[1], what, None
    return None


def started_jobs(
    transcript: StrPath,
) -> tuple[list[Job], set[str], pathlib.Path | None]:
    """Return the background shells and monitors an agent's transcript started.

    Returns (jobs, ended, tasks): jobs as (id, what, output file or None for a monitor),
    the ids a task notification or a TaskStop of its own ended, and the directory a
    shell's output was written to (None when no shell started).
    """
    calls: dict[object, str | None] = {}
    stops: dict[object, object] = {}
    ended: set[str] = set()
    jobs: list[Job] = []
    # An api-request-blob record repeats earlier results without their toolUseResult:
    # read as its own, a printed start message started a job, and a real one twice.
    written = (
        r for r in read_records(transcript) if r.get("type") != "api-request-blob"
    )
    for r in written:
        ended |= notified(r)
        message = as_dict(r.get("message"))
        content = as_list(message.get("content")) if message is not None else None
        for item in content or []:
            c = as_dict(item)
            if c is None:
                continue
            arg = as_dict(c.get("input")) or {}
            kind, use_id = c.get("type"), c.get("tool_use_id")
            if kind == "tool_use" and c.get("name") in ("Bash", "Monitor"):
                calls[c.get("id")] = _text(arg.get("command")) or _text(
                    arg.get("description")
                )
            elif kind == "tool_use" and c.get("name") == "TaskStop":
                stops[c.get("id")] = arg.get("task_id") or arg.get("shell_id")
            elif kind == "tool_result" and use_id in stops:
                if not c.get("is_error"):
                    ended.add(str(stops[use_id]))
            elif kind == "tool_result" and use_id in calls:
                job = _started_job(r, c, calls[use_id])
                if job is not None:
                    jobs.append(job)
    outputs = [output for _, _, output in jobs if output is not None]
    return jobs, ended, pathlib.Path(outputs[-1]).parent if outputs else None


def tasks_dir(transcript: pathlib.Path, session: str) -> pathlib.Path:
    """Return where an agent's monitors write their output when no shell of its said.

    A monitor's output sits beside the shells', mostly in
    <temp root>/claude-<uid>/<project>/<session>/tasks — one team's sat under another
    id. Claude Code's temp root is $CLAUDE_CODE_TMPDIR, else the system temp dir
    ($TMPDIR, else /tmp): a fixed /tmp missed both.
    """
    return pathlib.Path(
        os.environ.get("CLAUDE_CODE_TMPDIR") or tempfile.gettempdir(),
        f"claude-{os.getuid()}",
        transcript.parents[2].name,
        session,
        "tasks",
    )


def agent_transcript(
    event: Mapping[str, object], session: str, agent: str
) -> pathlib.Path | None:
    """Return the transcript of agent id `agent` of a session, or None.

    The hook event's own transcript when it is the agent's, else one under it or under
    any project's dir of the session.
    """
    name = f"agent-{agent}.jsonl"
    given = pathlib.Path(_text(event.get("transcript_path")) or "")
    candidates = [given] if given.name == name else []
    if given.suffix == ".jsonl":
        candidates.append(given.parent / given.stem / "subagents" / name)
    candidates += PROJECTS.glob(f"*/{session}/subagents/{name}")
    return next((p for p in candidates if p.is_file()), None)


def agent_name(transcript: pathlib.Path) -> str | None:
    """Return the name an agent was dispatched with, from its meta file, or None."""
    meta = load_json(transcript.with_name(transcript.stem + ".meta.json"))
    return _text(meta.get("name"))


def context(transcript: pathlib.Path) -> int:
    """Return the tokens of context of an agent's latest turn."""
    with transcript.open("rb") as fh:
        _ = fh.seek(max(0, transcript.stat().st_size - TAIL_BYTES))
        lines = fh.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            r = as_dict(parse_json(line))
        except ValueError:
            continue
        message = as_dict(r.get("message")) if r is not None else None
        usage = as_dict(message.get("usage")) if message is not None else None
        if (
            r is not None
            and r.get("type") == "assistant"
            and message is not None
            and usage
            and message.get("model") != "<synthetic>"
        ):
            return sum(
                _tokens(usage, k)
                for k in (
                    "input_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                )
            )
    return 0


def dispatch_text(transcript: StrPath) -> str:
    """Return the prompt an agent was dispatched with: its first user record's."""
    for r in read_records(transcript):
        if r.get("type") == "user":
            content = (as_dict(r.get("message")) or {}).get("content")
            blocks = as_list(content)
            if blocks is not None:
                content = " ".join(
                    str(b.get("text") or "")
                    for item in blocks
                    if (b := as_dict(item)) is not None
                )
            return str(content or "")
    return ""


def last_reads(
    transcript: StrPath, files: Iterable[pathlib.Path], tools: Container[object]
) -> dict[pathlib.Path, float]:
    """Return {file: when the agent last named it in a call of one of `tools`}."""
    last: dict[pathlib.Path, float] = {}
    for r in read_records(transcript):
        # An api-request-blob record repeats an earlier tool_use with no timestamp;
        # letting it overwrite would erase the read the timestamped record already
        # counted.
        stamp = epoch(r.get("timestamp") or "")
        if stamp is None:
            continue
        for block in tool_uses(r):
            said = json.dumps(block.get("input"))
            for f in files:
                if block.get("name") in tools and f.name in said:
                    last[f] = stamp
    return last
