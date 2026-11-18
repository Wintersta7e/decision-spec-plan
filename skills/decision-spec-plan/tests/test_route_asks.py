# SPDX-License-Identifier: MIT
"""The ask list: each user message to the lead owed a line in `<planning-dir>/asks.md`.

UserPromptSubmit numbers it; an `exec-` dispatch and the lead's Stop wait on its line,
and PreCompact keeps the unlisted ones verbatim (F105).
"""

import json
import unittest

import support
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


if __name__ == "__main__":
    _ = unittest.main()
