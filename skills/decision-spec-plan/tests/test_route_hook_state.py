"""`route_state.py --hook`'s state report: who it speaks to, the user's answers it tallies, pending
decisions, deltas on an agent's return, and the SessionStart re-read after a compaction or
resume."""

import json
import re
import unittest

import support
from support import RS, ev, jline


def askq(answer, recommended="Keep it (Recommended)"):
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


def pending_state(cls):
    """The pending section's steps: an old-format index with D2 unwritten, the phase unbound,
    and one report the next delta compares against."""
    d = cls.P / "decisions/phase1"
    cls.write(d / "00-index.md", "| D1 | a |\n| D2 | b |\n")
    cls.write(d / "D1-a.md", "ruling\n")
    cls.edit_marker(lambda m: m.setdefault("ledger", {}).__setitem__("1", False))
    for f in (cls.HOME / ".claude/dsp-routes").glob("*.checked"):
        f.unlink()


class StateHook(support.Route):
    """The state hook: who it speaks to."""

    def test_who_it_speaks_to(self):
        self.hook("report", ev("PostToolUse", "s1", '"tool_name":"Agent"'))
        self.hook("silent", ev("PostToolUse", "s1", '"tool_name":"Read"'))  # throttled
        self.unthrottle()
        self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read"')
        )  # nothing changed
        self.hook(
            "silent", ev("PostToolUse", "s1", '"tool_name":"Read","agent_id":"a1"')
        )
        self.hook(
            "silent", ev("PostToolUse", "s2", '"tool_name":"Read"')
        )  # never activated
        self.hook(
            "silent",
            ev("UserPromptSubmit", "s1", '"prompt":"what is left on the todo?"'),
        )
        self.hook(
            "silent",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<task-notification>\n<task-id>x</task-id>"',
            ),
        )


class Answers(support.Route):
    """The user's answers: nine in ten taking the recommendation stop telling the lead anything
    (F89)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the state hook section's report: the next tool calls are throttled
        cls.py(
            RS, "--hook", input=ev("PostToolUse", "s1", '"tool_name":"Agent"') + "\n"
        )

    def test_answer_tally(self):
        out = ""
        for answer in ["Drop it"] + ["Keep it (Recommended)"] * 8:
            out += self.hook_out(askq(answer)).out
        asks = self.marker().get("asks", [])
        self.ok(
            "answers are tallied, and fewer than ten say nothing",
            out == "" and len(asks) == 9,
            f"{out} {json.dumps(asks)}",
        )
        self.hook(
            "/took your recommendation in 9 of their last 10 answers/",
            askq("Keep it (Recommended)"),
        )
        self.hook(
            "silent", askq("Keep it", "Keep it")
        )  # no option recommended: not tallied
        self.hook("/9 of their last 10/", askq("Drop it"))
        self.hook("silent", askq("Drop it"))
        # the tally spans the route: a phase's re-activation (Stage 5's `--sins on`) keeps it
        n = len(self.marker()["asks"])
        self.activate_route()
        asks = self.marker().get("asks", [])
        self.ok(
            "a re-activation keeps the answer tally", len(asks) == n, json.dumps(asks)
        )


class Pending(support.Route):
    """Pending, not missing: index rows without files."""

    def test_pending_not_missing(self):
        pending_state(self)
        self.hook(
            r"/decisions  1 D files \(2 in the index; pending D2\)/",
            ev("PostToolUse", "s1", '"tool_name":"Agent"'),
        )
        try:
            ctx = json.loads(self.last)["hookSpecificOutput"]["additionalContext"]
            clean = re.search("missing|written [0-9]+s ago", ctx) is None
        except (ValueError, KeyError, TypeError):
            clean = False
        self.ok("no missing / freshness flags in a hook report", clean, self.last)


class Deltas(support.Route):
    """Deltas on an agent's return, by prompt or by the next tool call."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the state the pending section leaves, its report included
        pending_state(cls)
        cls.py(
            RS, "--hook", input=ev("PostToolUse", "s1", '"tool_name":"Agent"') + "\n"
        )

    def test_deltas(self):
        P = self.P
        self.write(
            P / "lanes/p1-01-checkpoint.md", f"- [x] done\nFinal SHA: {self.MAIN}\n"
        )
        self.hook(
            "/lanes      1 checkpoints/",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<teammate-message teammate_id=\"g1\">done</teammate-message>"',
            ),
        )
        self.hook(
            "silent",
            ev(
                "UserPromptSubmit",
                "s1",
                r'"prompt":"<agent-message from=\"a1\">\n[Subagent hand-back] done"',
            ),
        )
        self.write(P / "decisions/phase1/D2-b.md", "ruling\n")
        self.unthrottle()
        self.hook(
            r"/changed between .*\n.*2 D files \(2 in the index\)/",
            ev("PostToolUse", "s1", '"tool_name":"Bash"'),
        )


class SessionStart(support.Route):
    """SessionStart after a compaction and a resume."""

    def test_session_start(self):
        self.hook(
            r"/Re-read .*HANDOFF.md[\s\S]*\nroute state ·/",
            ev("SessionStart", "s1", '"source":"compact"'),
        )
        self.hook(
            "/Read .*SKILL.md in full/", ev("SessionStart", "s1", '"source":"resume"')
        )
        self.hook("silent", ev("SessionStart", "s1", '"source":"startup"'))
        self.hook("silent", ev("SessionStart", "s2", '"source":"compact"'))


if __name__ == "__main__":
    unittest.main()
