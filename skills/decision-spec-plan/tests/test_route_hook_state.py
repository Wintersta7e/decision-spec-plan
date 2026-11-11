# SPDX-License-Identifier: MIT
"""`route_state.py --hook`'s state report.

Who it speaks to, the user's answers it tallies, pending decisions, deltas on an agent's
return, and the SessionStart re-read after a compaction or resume.
"""

import json
import re
import unittest
from typing import cast

from typing_extensions import override

import support
from support import RS, ev, jline

ANSWERED = 9  # the answers the tally test gives before the tenth


def askq(answer: str, recommended: str = "Keep it (Recommended)") -> str:
    """A PostToolUse of AskUserQuestion answered with answer."""
    body = jline(
        {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [
                    {
                        "question": "Q?",
                        "options": [{"label": recommended}, {"label": "Drop it"}],
                    }
                ]
            },
            "tool_response": {"answers": {"Q?": answer}},
        }
    )
    return ev("PostToolUse", "s1", body[1:-1])


def _context(out: str) -> str | None:
    """The `additionalContext` a hook printed, or None when out holds none."""
    try:
        data = cast("object", json.loads(out))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    spec = cast("dict[str, object]", data).get("hookSpecificOutput")
    if not isinstance(spec, dict):
        return None
    ctx = cast("dict[str, object]", spec).get("additionalContext")
    return ctx if isinstance(ctx, str) else None


def _unbind(m: support.Marker) -> None:
    """The marker's phase 1 marked as not bound by the decision ledger."""
    m.setdefault("ledger", {})["1"] = False


def pending_state(cls: type[support.Route] | support.Route) -> None:
    """The pending section's steps.

    An old-format index with D2 unwritten, the phase unbound, and one report the next
    delta compares against.
    """
    d = cls.P / "decisions/phase1"
    _ = cls.write(d / "00-index.md", "| D1 | a |\n| D2 | b |\n")
    _ = cls.write(d / "D1-a.md", "ruling\n")
    cls.edit_marker(_unbind)
    for f in (cls.HOME / ".claude/dsp-routes").glob("*.checked"):
        f.unlink()


class StateHook(support.Route):
    """The state hook: who it speaks to."""

    def test_who_it_speaks_to(self) -> None:
        """The lead's session hears the report; agents, others and prompts do not."""
        _ = self.hook("report", ev("PostToolUse", "s1", '"tool_name":"Agent"'))
        _ = self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read"')
        )  # throttled
        self.unthrottle()
        _ = self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read"')
        )  # nothing changed
        _ = self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read","agent_id":"a1"')
        )
        _ = self.hook(
            "silent", ev("PostToolUse", "s2", '"tool_name":"Read"')
        )  # never activated
        _ = self.hook(
            "silent",
            ev("UserPromptSubmit", "s1", '"prompt":"what is left on the todo?"'),
        )
        _ = self.hook(
            "silent",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<task-notification>\n<task-id>x</task-id>"',
            ),
        )


class Answers(support.Route):
    """The user's answers.

    Nine in ten taking the recommendation stop telling the lead anything (F89).
    """

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Run the report that throttles the next tool calls."""
        super().setUpClass()
        # the state hook section's report: the next tool calls are throttled
        _ = cls.py(
            RS, "--hook", input=ev("PostToolUse", "s1", '"tool_name":"Agent"') + "\n"
        )

    def test_answer_tally(self) -> None:
        """Answers are tallied, the tenth tells, and a re-activation keeps them."""
        out = ""
        for answer in ["Drop it"] + ["Keep it (Recommended)"] * 8:
            out += self.hook_out(askq(answer)).out
        asks = self.marker().get("asks", [])
        self.ok(
            "answers are tallied, and fewer than ten say nothing",
            out == "" and len(asks) == ANSWERED,
            f"{out} {json.dumps(asks)}",
        )
        _ = self.hook(
            "/took your recommendation in 9 of their last 10 answers/",
            askq("Keep it (Recommended)"),
        )
        _ = self.hook(
            "silent", askq("Keep it", "Keep it")
        )  # no option recommended: not tallied
        _ = self.hook("/9 of their last 10/", askq("Drop it"))
        _ = self.hook("silent", askq("Drop it"))
        # the tally spans the route: a phase's re-activation (Stage 5's `--sins on`)
        # keeps it
        before = self.marker()
        assert "asks" in before, json.dumps(before)
        n = len(before["asks"])
        _ = self.activate_route()
        asks = self.marker().get("asks", [])
        self.ok(
            "a re-activation keeps the answer tally", len(asks) == n, json.dumps(asks)
        )


class Pending(support.Route):
    """Pending, not missing: index rows without files."""

    def test_pending_not_missing(self) -> None:
        """An index row without its file is pending, and no flag calls it missing."""
        pending_state(self)
        _ = self.hook(
            r"/decisions  1 D files \(2 in the index; pending D2\)/",
            ev("PostToolUse", "s1", '"tool_name":"Agent"'),
        )
        ctx = _context(self.last)
        clean = (
            ctx is not None and re.search("missing|written [0-9]+s ago", ctx) is None
        )
        self.ok("no missing / freshness flags in a hook report", clean, self.last)


class Deltas(support.Route):
    """Deltas on an agent's return, by prompt or by the next tool call."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Leave the pending section's state, its report included."""
        super().setUpClass()
        # the state the pending section leaves, its report included
        pending_state(cls)
        _ = cls.py(
            RS, "--hook", input=ev("PostToolUse", "s1", '"tool_name":"Agent"') + "\n"
        )

    def test_deltas(self) -> None:
        """A teammate's message and the next tool call report what changed."""
        p = self.P
        _ = self.write(
            p / "lanes/p1-01-checkpoint.md", f"- [x] done\nFinal SHA: {self.MAIN}\n"
        )
        _ = self.hook(
            "/lanes      1 checkpoints/",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<teammate-message teammate_id=\"g1\">'
                r'done</teammate-message>"',
            ),
        )
        _ = self.hook(
            "silent",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<agent-message from=\"a1\">\n[Subagent hand-back] done"',
            ),
        )
        _ = self.write(p / "decisions/phase1/D2-b.md", "ruling\n")
        self.unthrottle()
        _ = self.hook(
            r"/changed between .*\n.*2 D files \(2 in the index\)/",
            ev("PostToolUse", "s1", '"tool_name":"Bash"'),
        )


class SessionStart(support.Route):
    """SessionStart after a compaction and a resume."""

    def test_session_start(self) -> None:
        """A compaction re-reads the handoff, a resume the skill; others are silent."""
        _ = self.hook(
            r"/Re-read .*HANDOFF.md[\s\S]*\nroute state ·/",
            ev("SessionStart", "s1", '"source":"compact"'),
        )
        _ = self.hook(
            "/Read .*SKILL.md in full/", ev("SessionStart", "s1", '"source":"resume"')
        )
        _ = self.hook("silent", ev("SessionStart", "s1", '"source":"startup"'))
        _ = self.hook("silent", ev("SessionStart", "s2", '"source":"compact"'))


if __name__ == "__main__":
    _ = unittest.main()
