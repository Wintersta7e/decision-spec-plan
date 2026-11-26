# SPDX-License-Identifier: MIT
"""`route_state.py --activate`'s transcript shape check, run as the hooks run.

It runs as a subprocess with HOME pointed at a throwaway directory, so no real session
or registry is read.

Each test also checks the quiet side: a transcript carrying every shape the hooks read
prints nothing, so a check that flags everything fails here too.
"""

import copy
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from typing import Required, TypedDict

from typing_extensions import override

from dsp_route import transcript

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "route_state.py"
SESSION = "s-shape"
PREFIX = "transcript format:"


class _Message(TypedDict, total=False):
    """A record's message, as the lead's transcript holds it."""

    role: Required[str]
    content: Required[str | list[dict[str, object]]]
    id: str
    model: str
    stop_reason: str
    usage: dict[str, int]


class _Record(TypedDict, total=False):
    """One record of the lead's transcript."""

    type: Required[str]
    entrypoint: Required[str]
    timestamp: Required[str]
    message: Required[_Message]
    requestId: str
    origin: dict[str, str]
    toolUseResult: dict[str, bool]


def lead_records() -> list[_Record]:
    """A lead's transcript at --activate.

    The user's prompt, the skill's load and its result, then the --activate call itself,
    whose result is not written yet.
    """

    def assistant(n: int, call: dict[str, object], stamp: str) -> _Record:
        return {
            "type": "assistant",
            "entrypoint": "cli",
            "timestamp": stamp,
            "requestId": f"r{n}",
            "message": {
                "id": f"m{n}",
                "role": "assistant",
                "model": "claude-test",
                "stop_reason": "tool_use",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 20,
                    "output_tokens": 5,
                },
                "content": [call],
            },
        }

    return [
        {
            "type": "user",
            "entrypoint": "cli",
            "timestamp": "2026-11-01T10:00:00.000Z",
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": "use dsp on the export bug"},
        },
        assistant(
            1,
            {
                "type": "tool_use",
                "id": "t1",
                "name": "Skill",
                "input": {"skill": "decision-spec-plan"},
            },
            "2026-11-01T10:00:05.000Z",
        ),
        {
            "type": "user",
            "entrypoint": "cli",
            "timestamp": "2026-11-01T10:00:06.000Z",
            "toolUseResult": {"success": True},
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
                ],
            },
        },
        assistant(
            2,
            {
                "type": "tool_use",
                "id": "t2",
                "name": "Bash",
                "input": {
                    "command": "python3 route_state.py .plan --phase 1 --activate"
                },
            },
            "2026-11-01T10:01:00.000Z",
        ),
    ]


@dataclasses.dataclass(frozen=True)
class _Fixture:
    """One test's throwaway HOME, its repository, environment and lead transcript."""

    home: pathlib.Path
    repo: pathlib.Path
    env: dict[str, str]
    transcript: pathlib.Path


class ActivateShapeCheck(unittest.TestCase):
    """--activate's transcript shape check on transcripts each missing one shape."""

    _fx: _Fixture | None = None

    @override
    def setUp(self) -> None:
        """Create HOME and a repository with one commit, and name the transcript."""
        tmp = tempfile.TemporaryDirectory()  # under $TMPDIR when it is set
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        home = root / "home"
        home.mkdir()
        repo = root / "repo"
        # no user or system git config: their hooks and identity are not this test's
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        for args in (
            ["init", "-q", "-b", "main", str(repo)],
            ["-C", str(repo), "commit", "-q", "--allow-empty", "-m", "one"],
        ):
            _ = subprocess.run([*git, *args], env=env, check=True)
        (repo / ".plan" / "decisions" / "phase1").mkdir(parents=True)
        transcript = home / ".claude" / "projects" / "p" / f"{SESSION}.jsonl"
        self._fx = _Fixture(home, repo, env, transcript)

    @property
    def fx(self) -> _Fixture:
        """The fixture setUp created."""
        if self._fx is None:
            self.fail("setUp did not run")
        return self._fx

    def activate(self, records: list[_Record] | None = None) -> tuple[int, list[str]]:
        """(exit status, the shape check's lines) of --activate with this transcript."""
        fx = self.fx
        if records is None:
            fx.transcript.unlink(missing_ok=True)
        else:
            fx.transcript.parent.mkdir(parents=True, exist_ok=True)
            _ = fx.transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
        env = {**fx.env, "CLAUDE_CODE_SESSION_ID": SESSION}
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(fx.repo / ".plan"),
                "--phase",
                "1",
                "--repo",
                str(fx.repo),
                "--activate",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if "hooks registered for session" not in r.stdout:
            self.fail(r.stdout + r.stderr)
        return r.returncode, [
            ln for ln in r.stdout.splitlines() if ln.startswith(PREFIX)
        ]

    def assert_flags(self, records: list[_Record], *checks: str) -> str:
        """A full transcript is quiet; records gets one line naming each of checks.

        --activate exits as it does with the full one.
        """
        quiet_code, quiet = self.activate(lead_records())
        if quiet != []:
            self.fail(f"{quiet!r} != []")
        code, lines = self.activate(records)
        if len(lines) != 1:
            self.fail(f"{len(lines)} != 1 : {lines!r}")
        for check in checks:
            if check not in lines[0]:
                self.fail(f"{check!r} not found in {lines[0]!r}")
        if code != quiet_code:
            self.fail(f"{code} != {quiet_code}")
        return lines[0]

    def test_no_transcript_yet_is_quiet(self) -> None:
        """No transcript is quiet; one without usage turns off the budget hold."""
        code, lines = self.activate(None)
        assert (code, lines) == (0, [])
        broken = lead_records()
        for r in broken:
            _ = r["message"].pop("usage", None)
        _ = self.assert_flags(broken, "the budget hold")

    def test_no_reply_yet_is_quiet(self) -> None:
        """No reply yet is quiet; a reply under a renamed type turns its checks off."""
        # --activate typed by the user (`!`) before the model's first reply
        assert self.activate(lead_records()[:1])[1] == []
        # a reply under a renamed record type is a reply: every check reading it is off
        records = lead_records()
        for r in records:
            if r["type"] == "assistant":
                r["type"] = "model"
        _ = self.assert_flags(records, "the budget hold", "ETAs", "the context stop")

    def test_usage_missing_turns_off_spend_and_context_stop(self) -> None:
        """Without usage the budget hold and the context stop are off."""
        records = lead_records()
        for r in records:
            _ = r["message"].pop("usage", None)
        line = self.assert_flags(records, "the budget hold", "the context stop")
        assert "usage" in line

    def test_message_id_missing_turns_off_spend(self) -> None:
        """Without message ids the budget hold is off."""
        # usage_report counts each (message.id, requestId) once: without the id every
        # turn after the first would count as the first
        records = lead_records()
        for r in records:
            _ = r["message"].pop("id", None)
        _ = self.assert_flags(records, "the budget hold")

    def test_unparseable_timestamps_turn_off_etas(self) -> None:
        """Unparseable timestamps turn off ETAs, the rulings check and the hold."""
        records = lead_records()
        for r in records:
            r["timestamp"] = "yesterday"
        _ = self.assert_flags(records, "ETAs", "the rulings check", "the budget hold")

    def test_stop_reason_missing_turns_off_etas(self) -> None:
        """Without stop_reason ETAs are off."""
        records = lead_records()
        for r in records:
            _ = r["message"].pop("stop_reason", None)
        _ = self.assert_flags(records, "ETAs")

    def test_tool_use_blocks_renamed(self) -> None:
        """Renamed tool_use blocks turn off the checks that read calls."""
        records = lead_records()
        for r in records:
            content = r["message"]["content"] if r["type"] == "assistant" else []
            for block in content:
                assert isinstance(block, dict), block
                block["type"] = "tool_call"
        _ = self.assert_flags(
            records, "the budget hold", "the rulings check", "the own-jobs wait"
        )

    def test_tool_result_missing_after_an_earlier_call(self) -> None:
        """A call whose result never came is a gap."""
        records = [r for r in lead_records() if "toolUseResult" not in r]
        _ = self.assert_flags(records, "the own-jobs wait", "the budget hold")

    def test_activate_as_the_first_call_has_no_result_to_check(self) -> None:
        """--activate as the first call is quiet; after an unanswered call it is not."""
        first = [lead_records()[0], lead_records()[3]]
        assert self.activate(first)[1] == []
        # the same call after one whose result never came is a gap
        records = [r for r in lead_records() if "toolUseResult" not in r]
        _ = self.assert_flags(records, "the own-jobs wait")

    def test_tool_use_result_missing(self) -> None:
        """A tool result without toolUseResult turns off the own-jobs wait."""
        records = lead_records()
        _ = records[2].pop("toolUseResult")
        _ = self.assert_flags(records, "the own-jobs wait", "--budget")

    def test_human_prompt_missing_in_an_interactive_session(self) -> None:
        """No typed prompt is a gap interactively, none headless."""
        records = copy.deepcopy(lead_records())
        _ = records[0].pop("origin")
        _ = self.assert_flags(records, "the budget hold")
        # a headless session has no typed prompt to find
        for r in records:
            r["entrypoint"] = "sdk-cli"
        assert self.activate(records)[1] == []

    def test_several_gaps_share_one_line(self) -> None:
        """Several gaps are named on one line, each once."""
        records = lead_records()
        for r in records:
            _ = r["message"].pop("usage", None)
            _ = r["message"].pop("stop_reason", None)
        line = self.assert_flags(records, "ETAs", "the context stop")
        assert line.count("the budget hold") == 1


def stamp(n: int) -> str:
    """A timestamp n seconds into a fixed minute."""
    return f"2026-01-01T00:00:{n:02d}.000Z"


def text(n: int, said: str) -> dict[str, object]:
    """The lead's text that ends its turn, at stamp(n)."""
    return {
        "type": "assistant",
        "timestamp": stamp(n),
        "message": {
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": said}],
        },
    }


def typed(n: int, prompt: str) -> dict[str, object]:
    """The user's typed prompt, at stamp(n)."""
    return {
        "type": "user",
        "timestamp": stamp(n),
        "origin": {"kind": "human"},
        "message": {"role": "user", "content": prompt},
    }


def asked(n: int, question: str, answer: str) -> dict[str, object]:
    """The user's answer to an AskUserQuestion, at stamp(n)."""
    return {
        "type": "user",
        "timestamp": stamp(n),
        "toolUseResult": {
            "questions": [{"question": question}],
            "answers": {question: answer},
        },
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "q", "content": "ok"}],
        },
    }


class FigureAnswers(unittest.TestCase):
    """An answer covers a budget's figure only when it is about that figure (F74)."""

    def lead(self, records: tuple[dict[str, object], ...]) -> pathlib.Path:
        """A lead transcript of records in a directory removed after the test."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name, "lead.jsonl")
        _ = path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return path

    def turn(self, *records: dict[str, object]) -> str | None:
        """When records' current turn answered `w2`'s 15M, else None."""
        return transcript.turn_answer([self.lead(records)], 15, "w2")

    def since(self, *records: dict[str, object]) -> str | None:
        """When records answered `w2`'s 15M from stamp(5) on, else None."""
        return transcript.answered_since([self.lead(records)], stamp(5), 15, "w2")

    def test_a_typed_go_after_the_stated_figure_answers(self) -> None:
        """A typed go after the stated figure or range answers it."""
        assert self.turn(text(1, "≈14–16M — go ahead?"), typed(2, "go")) == stamp(2)
        assert self.turn(text(1, "w2 at 14-16M?"), typed(2, "go")) == stamp(2)
        assert self.turn(text(1, "15M, go?"), typed(2, "go")) == stamp(2)
        # another figure, or a figure in an id, is not this one
        assert self.turn(text(1, "≈16–18M — go ahead?"), typed(2, "go")) is None
        assert self.turn(text(1, "lane p1-15M?"), typed(2, "go")) is None
        # an agent's return, a peer's message and the limit prompt are no answer
        for prompt in (
            '<teammate-message teammate_id="a">done</teammate-message>',
            '<cross-session-message from="x">done</cross-session-message>',
            "Your claude.ai usage limit has reset. Continue?",
        ):
            assert self.turn(text(1, "15M?"), typed(2, prompt)) is None, prompt
        # only the prompt that opened the current turn
        later = (text(1, "15M?"), typed(2, "go"), text(3, "done"), typed(4, "next"))
        assert self.turn(*later) is None

    def test_only_a_budget_question_answers(self) -> None:
        """A design question's answer that names the number covers nothing."""
        design = "Which design: option A (15M of rework) or option B?"
        assert self.turn(typed(1, "go"), asked(2, design, "Option A, 15M")) is None
        budget = "Raise the budget to 15M?"
        assert self.turn(typed(1, "go"), asked(2, budget, "Yes")) == stamp(2)
        label = "w2: the route's total — go ahead?"
        assert self.turn(typed(1, "go"), asked(2, label, "Yes, ≈14–16M")) == stamp(2)

    def test_the_gate_counts_a_reply_to_the_figure(self) -> None:
        """After the record, a prompt counts only once the figure was told before it."""
        assert self.since(text(6, "the plan is ready"), typed(7, "go")) is None
        assert self.since(text(6, "w2: 15M total?"), typed(7, "go")) == stamp(7)
        # an answer before the record is not this record's
        assert self.since(text(1, "15M?"), typed(2, "go")) is None
        # headless: no prompt of the user's at all passes at the record
        assert self.since(text(6, "running")) == stamp(5)


if __name__ == "__main__":
    _ = unittest.main()
