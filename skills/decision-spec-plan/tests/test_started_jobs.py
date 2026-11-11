# SPDX-License-Identifier: MIT
"""started_jobs counts a background job once, from the record Claude Code wrote for it.

Claude Code also writes `api-request-blob` records that repeat a request's tool results
without their `toolUseResult`. Read as results of their own, a command that only printed
a job's start message (a test fixture, a transcript read back) started a job, and a real
job was counted twice.
"""

import json
import tempfile
import unittest
from pathlib import Path

from dsp_route import transcript

START = (
    "Command running in background with ID: {job}. Output is being written to: "
    "/t/tasks/{job}.output. You will be notified when it completes."
)


def call(use_id: str, command: str) -> dict[str, object]:
    """Return the assistant record of a Bash call."""
    return {
        "type": "assistant",
        "timestamp": "2026-11-11T13:30:00.000Z",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": use_id,
                    "name": "Bash",
                    "input": {"command": command},
                }
            ],
        },
    }


def result(use_id: str, text: str, outcome: dict[str, object]) -> dict[str, object]:
    """Return the user record of a tool result, with its toolUseResult."""
    return {
        "type": "user",
        "timestamp": "2026-11-11T13:30:01.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": use_id, "content": text}
            ],
        },
        "toolUseResult": outcome,
    }


def blob(use_id: str, text: str) -> dict[str, object]:
    """Return an api-request-blob record repeating a tool result."""
    return {
        "type": "api-request-blob",
        "sessionId": "s1",
        "agentId": "a1",
        "hash": "h1",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": use_id, "content": text}
            ],
        },
    }


class RepeatedResults(unittest.TestCase):
    """An api-request-blob record never starts a job."""

    def jobs(self, *records: dict[str, object]) -> list[transcript.Job]:
        """Return the jobs started_jobs finds in a transcript of these records."""
        with tempfile.TemporaryDirectory(prefix="dsp-test-") as tmp:
            path = Path(tmp) / "agent-a1.jsonl"
            _ = path.write_text("".join(json.dumps(r) + "\n" for r in records))
            return transcript.started_jobs(path)[0]

    def test_printed_start_message_starts_none(self) -> None:
        """A foreground command whose output quotes a start message started no job."""
        printed = f"fixture line: {START.format(job='bsh1')}"
        outcome: dict[str, object] = {"stdout": printed, "stderr": ""}
        assert (
            self.jobs(call("t1", "cat test_fixture.py"), result("t1", printed, outcome))
            == []
        )
        assert (
            self.jobs(
                call("t1", "cat test_fixture.py"),
                result("t1", printed, outcome),
                blob("t1", printed),
            )
            == []
        )

    def test_real_job_counted_once(self) -> None:
        """A job that ran in the background is one job, repeated or not."""
        started = START.format(job="bsh9")
        outcome: dict[str, object] = {"stdout": "", "backgroundTaskId": "bsh9"}
        records = (
            call("t2", "npm test"),
            result("t2", started, outcome),
            blob("t2", started),
        )
        assert self.jobs(*records) == [("bsh9", "npm test", "/t/tasks/bsh9.output")]
