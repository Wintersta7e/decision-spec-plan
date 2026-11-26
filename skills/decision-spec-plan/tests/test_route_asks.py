# SPDX-License-Identifier: MIT
"""The ask list: each user message to the lead owed a line in `<planning-dir>/asks.md`.

UserPromptSubmit numbers it; an `exec-` dispatch and the lead's Stop wait on its line,
and PreCompact keeps the unlisted ones verbatim (F105).
"""

import json
import re
import shutil
import unittest

from typing_extensions import override

import support
from dsp_route.common import is_return
from support import RS, ev

EXEC_DISPATCH = ev(
    "PreToolUse",
    "s1",
    '"tool_name":"Agent","tool_input":{"name":"exec-p1-01-g1","prompt":"x"}',
)


class Asks(support.Route):
    """Two user messages and an agent's return to the lead of s1's route."""

    def prompt(self, text: str, agent: str = "") -> str:
        """The hook's output on a UserPromptSubmit of text, by agent when given."""
        extra = f',"agent_id":"{agent}"' if agent else ""
        return self.hook_out(
            ev("UserPromptSubmit", "s1", f'"prompt":{json.dumps(text)}{extra}')
        ).out

    def test_asks_listed(self) -> None:
        """Unlisted messages hold the dispatch and the Stop, and survive compaction."""
        out = self.prompt("fix all of the issues, and the comment in the first MR")
        self.ok(
            "a user message is numbered and its line asked for",
            support.hook_matches("/user message Msg1.*asks.md/", out),
            out,
        )
        out = self.prompt("<task-notification> agent a1 finished")
        self.ok("an agent's return is no user message", "Msg2" not in out, out)
        self.ok("a teammate's prompt is not the user's", self.prompt("x", "t1") == "")
        _ = self.prompt("also bump nothing")
        out = self.hook_out(EXEC_DISPATCH).out
        self.ok(
            "an exec- dispatch waits on both messages, quoted",
            support.hook_matches("deny:F105", out)
            and "Msg1: fix all of the issues" in out
            and "Msg2: also bump nothing" in out,
            out,
        )
        stop = self.hook_out(ev("Stop", "s1")).out
        self.ok(
            "the lead's Stop is sent back",
            '"decision": "block"' in stop and "Msg2" in stop,
            stop,
        )
        again = self.hook_out(ev("Stop", "s1", '"stop_hook_active":true')).out
        self.ok("only once: a continued Stop ends", again == "", again)
        kept = self.hook_out(ev("PreCompact", "s1", '"trigger":"auto"')).out
        self.ok(
            "PreCompact tells the summary to keep them verbatim",
            kept.startswith("Keep these user messages verbatim")
            and "Msg1: fix all of the issues, and the comment in the first MR" in kept,
            kept,
        )
        _ = self.write(self.P / "asks.md", "| Msg1 | fix every issue: p1-01 |\n")
        out = self.hook_out(EXEC_DISPATCH).out
        self.ok(
            "a listed message no longer holds; the unlisted one still does",
            "Msg1:" not in out and "Msg2: also bump nothing" in out,
            out,
        )
        _ = self.write(self.P / "asks.md", "- Msg2 | not an ask\n", mode="a")
        out = self.hook_out(EXEC_DISPATCH).out
        self.ok("all listed: no F105 hold", "F105" not in out, out)
        self.ok("all listed: Stop ends", self.hook_out(ev("Stop", "s1")).out == "")
        self.ok(
            "all listed: PreCompact adds nothing",
            self.hook_out(ev("PreCompact", "s1", '"trigger":"auto"')).out == "",
        )
        # the session's route on another planning dir owes nothing for these messages
        _ = self.write(self.P / "asks.md", "")
        other = self.R / ".plan2"
        (other / "decisions/phase1").mkdir(parents=True)
        r = self.py(
            RS, other, "--phase", "1", "--repo", self.R, "--sections", "1-",
            "--activate", session="s1", merge=True,
        )  # fmt: skip
        out = self.hook_out(EXEC_DISPATCH).out
        self.ok(
            "another route's messages are not owed",
            r.code == 0 and "F105" not in out,
            (r.out, out),
        )


PEER = (
    '<cross-session-message from="worker">\nthe gate is green\n</cross-session-message>'
)
LIMIT = "Your claude.ai usage limit has reset. Continue where you left off?"


class Returns(unittest.TestCase):
    """A peer session's message and the usage-limit prompt are no user message."""

    def test_new_prompt_shapes(self) -> None:
        """Both shapes are returns; the user's own text is not."""
        assert is_return(PEER)
        assert is_return(LIMIT)
        assert not is_return("the usage limit has reset, go on")


class AcrossSessions(support.Route):
    """One numbering a planning dir, whichever lead session the user types in (F105)."""

    @override
    def setUp(self) -> None:
        """No log, old log or ask list: the tests share the class's route."""
        reg = self.HOME / ".claude/dsp-routes"
        for f in (reg / f"{self.MK(self.R).stem}.asks", reg / "s1.asks"):
            f.unlink(missing_ok=True)
        _ = self.write(self.P / "asks.md", "")

    def prompt(self, text: str, session: str = "s1") -> str:
        """The hook's output on session's UserPromptSubmit of text."""
        return self.hook_out(
            ev("UserPromptSubmit", session, f'"prompt":{json.dumps(text)}')
        ).out

    def number(self, text: str, session: str = "s1") -> int | None:
        """The Msg number the hook gave session's text, None for none."""
        found = re.search(r"user message Msg(\d+)\b", self.prompt(text, session))
        return int(found[1]) if found else None

    def test_numbered_per_planning_dir(self) -> None:
        """AC-P12-1-5: two sessions share a numbering; peers and limits get none."""
        reg = self.HOME / ".claude/dsp-routes"
        _ = shutil.copy(reg / "s1.json", reg / "s9.json")
        self.ok("a peer's message gets no number", self.number(PEER) is None)
        self.ok("the usage-limit prompt gets no number", self.number(LIMIT) is None)
        got = [self.number("one"), self.number("two", "s9"), self.number("three")]
        self.ok("two sessions number Msg1, Msg2, Msg3", got == [1, 2, 3], got)
        # a Msg line the lead wrote for something else takes its number
        _ = self.write(
            self.P / "asks.md",
            "Msg1 | a\nMsg2 | b\nMsg3 | c\nMsg4 | an answer, wrongly a Msg line\n",
        )
        out = self.prompt("five")
        self.ok(
            "the next message is one past the lead's Msg4, told to use it",
            "user message Msg5." in out
            and support.grep(out, "Use exactly this number")
            and support.grep(out, "is a `U<n>` line", F=True),
            out,
        )
        out = self.hook_out(EXEC_DISPATCH).out
        self.ok(
            "the hold reads the stored numbers",
            "Msg5: five" in out and "Msg4:" not in out and "Msg1:" not in out,
            out,
        )

    def test_old_log_is_copied_once(self) -> None:
        """The session's old per-session rows of this route keep their numbers."""
        reg = self.HOME / ".claude/dsp-routes"
        marker = str(self.MK(self.R))
        rows = [
            {"at": 1, "route": marker, "text": "first"},
            {"at": 2, "route": "<another route>", "text": "elsewhere"},
            {"at": 3, "route": marker, "text": "third"},
        ]
        _ = self.write(reg / "s1.asks", "".join(json.dumps(r) + "\n" for r in rows))
        _ = self.write(self.P / "asks.md", "Msg1 | a\n")
        out = self.hook_out(EXEC_DISPATCH).out
        self.ok(
            "this route's old rows are owed under their old numbers, no other",
            "Msg3: third" in out and "elsewhere" not in out and "Msg1:" not in out,
            out,
        )
        n = self.number("four")
        self.ok("the next message follows them", n == len(rows) + 1, n)
        # copied once: the old log no longer feeds the route's
        _ = self.write(reg / "s1.asks", json.dumps(rows[2]) + "\n", mode="a")
        out = self.hook_out(EXEC_DISPATCH).out
        self.ok("copied once", out.count("Msg3: third") == 1, out)


if __name__ == "__main__":
    _ = unittest.main()
