"""`route_state.py --activate`'s transcript shape check, run as the hooks run: a subprocess with
HOME pointed at a throwaway directory, so no real session or registry is read.

Each test also checks the quiet side: a transcript carrying every shape the hooks read prints
nothing, so a check that flags everything fails here too."""

import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "route_state.py"
SESSION = "s-shape"
PREFIX = "transcript format:"


def lead_records():
    """A lead's transcript at --activate: the user's prompt, the skill's load and its result,
    then the --activate call itself, whose result is not written yet."""

    def assistant(n, call, stamp):
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


class ActivateShapeCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()  # under $TMPDIR when it is set
        root = pathlib.Path(self.tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.repo = root / "repo"
        # no user or system git config: their hooks and identity are not this test's
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        for args in (
            ["init", "-q", "-b", "main", str(self.repo)],
            ["-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "one"],
        ):
            subprocess.run([*git, *args], env=self.env, check=True)
        (self.repo / ".plan" / "decisions" / "phase1").mkdir(parents=True)
        self.transcript = self.home / ".claude" / "projects" / "p" / f"{SESSION}.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def activate(self, records=None):
        """(exit status, the shape check's lines) of --activate with this transcript."""
        if records is None:
            self.transcript.unlink(missing_ok=True)
        else:
            self.transcript.parent.mkdir(parents=True, exist_ok=True)
            self.transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
        env = {**self.env, "CLAUDE_CODE_SESSION_ID": SESSION}
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.repo / ".plan"),
                "--phase",
                "1",
                "--repo",
                str(self.repo),
                "--activate",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn("hooks registered for session", r.stdout, r.stdout + r.stderr)
        return r.returncode, [
            ln for ln in r.stdout.splitlines() if ln.startswith(PREFIX)
        ]

    def assert_flags(self, records, *checks):
        """A full transcript is quiet; `records` gets one line naming each of `checks`, and
        --activate exits as it does with the full one."""
        quiet_code, quiet = self.activate(lead_records())
        self.assertEqual(quiet, [])
        code, lines = self.activate(records)
        self.assertEqual(len(lines), 1, lines)
        for check in checks:
            self.assertIn(check, lines[0])
        self.assertEqual(code, quiet_code)
        return lines[0]

    def test_no_transcript_yet_is_quiet(self):
        code, lines = self.activate(None)
        self.assertEqual((code, lines), (0, []))
        broken = lead_records()
        for r in broken:
            r["message"].pop("usage", None)
        self.assert_flags(broken, "the budget hold")

    def test_no_reply_yet_is_quiet(self):
        # --activate typed by the user (`!`) before the model's first reply
        self.assertEqual(self.activate(lead_records()[:1])[1], [])
        # a reply under a renamed record type is a reply: every check reading it is off
        records = lead_records()
        for r in records:
            if r["type"] == "assistant":
                r["type"] = "model"
        self.assert_flags(records, "the budget hold", "ETAs", "the context stop")

    def test_usage_missing_turns_off_spend_and_context_stop(self):
        records = lead_records()
        for r in records:
            r["message"].pop("usage", None)
        line = self.assert_flags(records, "the budget hold", "the context stop")
        self.assertIn("usage", line)

    def test_message_id_missing_turns_off_spend(self):
        # usage_report counts each (message.id, requestId) once: without the id every turn after
        # the first would count as the first
        records = lead_records()
        for r in records:
            r["message"].pop("id", None)
        self.assert_flags(records, "the budget hold")

    def test_unparseable_timestamps_turn_off_etas(self):
        records = lead_records()
        for r in records:
            r["timestamp"] = "yesterday"
        self.assert_flags(records, "ETAs", "the rulings check", "the budget hold")

    def test_stop_reason_missing_turns_off_etas(self):
        records = lead_records()
        for r in records:
            r["message"].pop("stop_reason", None)
        self.assert_flags(records, "ETAs")

    def test_tool_use_blocks_renamed(self):
        records = lead_records()
        for r in records:
            for block in r["message"]["content"] if r["type"] == "assistant" else []:
                block["type"] = "tool_call"
        self.assert_flags(
            records, "the budget hold", "the rulings check", "the own-jobs wait"
        )

    def test_tool_result_missing_after_an_earlier_call(self):
        records = [r for r in lead_records() if "toolUseResult" not in r]
        self.assert_flags(records, "the own-jobs wait", "the budget hold")

    def test_activate_as_the_first_call_has_no_result_to_check(self):
        first = [lead_records()[0], lead_records()[3]]
        self.assertEqual(self.activate(first)[1], [])
        # the same call after one whose result never came is a gap
        records = [r for r in lead_records() if "toolUseResult" not in r]
        self.assert_flags(records, "the own-jobs wait")

    def test_tool_use_result_missing(self):
        records = lead_records()
        records[2].pop("toolUseResult")
        self.assert_flags(records, "the own-jobs wait", "--budget")

    def test_human_prompt_missing_in_an_interactive_session(self):
        records = copy.deepcopy(lead_records())
        records[0].pop("origin")
        self.assert_flags(records, "the budget hold")
        # a headless session has no typed prompt to find
        for r in records:
            r["entrypoint"] = "sdk-cli"
        self.assertEqual(self.activate(records)[1], [])

    def test_several_gaps_share_one_line(self):
        records = lead_records()
        for r in records:
            r["message"].pop("usage", None)
            r["message"].pop("stop_reason", None)
        line = self.assert_flags(records, "ETAs", "the context stop")
        self.assertEqual(line.count("the budget hold"), 1)


if __name__ == "__main__":
    unittest.main()
