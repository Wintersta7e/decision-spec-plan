# SPDX-License-Identifier: MIT
"""`route_state.py --activate` and the hooks before and around it.

No route, a prompt naming the route before its skill loaded, a route agent dispatched
with none, and route settings given without --activate.
"""

import json
import unittest
from typing import ClassVar

import support
from support import RS, ev, jstr

CHECKS = 2  # the version of the decision checks a new ledger entry is bound to
USAGE = 2  # route_state.py's exit on a usage error


def route_agent(session: str, kind: str) -> str:
    """A PreToolUse event of session dispatching a route agent of kind."""
    return ev(
        "PreToolUse",
        session,
        f'"tool_name":"Agent",'
        f'"tool_input":{{"subagent_type":"{kind}","name":"pride-r1"}}',
    )


class NoRouteThenActivate(support.Route):
    """The repository of support.Route with no route until the test activates one."""

    activate: ClassVar[bool] = False

    def asks(self, prompt: str, transcript: str) -> str:
        """A UserPromptSubmit event of prompt, its transcript the named file under T."""
        return ev(
            "UserPromptSubmit",
            "s1",
            f'"prompt":{jstr(prompt)},"transcript_path":"{self.T}/{transcript}"',
        )

    def test_no_route_active(self) -> None:
        """The hooks with no route, then --activate and the settings it alone takes."""
        r, p, t = self.R, self.P, self.T
        # no route active: everything passes, the hook is silent
        _ = self.guard(0, r, "git push origin main")
        _ = self.guard(0, r, "git --no-pager push origin main")
        _ = self.guard(0, r, "DSP_SKIP_PUSH_GUARD=1 git push origin main")
        _ = self.hook("silent", ev("PostToolUse", "s1", '"tool_name":"Agent"'))
        # ...but a route agent dispatched with no route means the skill never loaded:
        # F79 records it
        _ = self.hook(
            "deny:no active decision-spec-plan route.*Skill tool.*--activate --rung",
            route_agent("s1", "dsp-deep"),
        )
        _ = self.hook(
            "deny:no active decision-spec-plan route",
            route_agent("s1", "decision-spec-plan:dsp-mechanical"),
        )
        _ = self.hook("silent", route_agent("s1", "general-purpose"))
        _ = self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s1",
                '"agent_id":"a1","tool_name":"Agent",'
                '"tool_input":{"subagent_type":"dsp-deep"}',
            ),
        )
        # a prompt naming the route in a session that has not loaded it: the skill
        # first, before any work (one lead did 43 minutes of work after "use dsp" before
        # loading it)
        _ = self.write(
            t / "no-skill.jsonl",
            '{"type":"user","message":{"role":"user","content":"hi"}}\n',
        )
        _ = self.write(
            t / "skill.jsonl",
            '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"k1",'
            '"name":"Skill","input":{"skill":"decision-spec-plan"}}]}}\n',
        )
        _ = self.hook(
            "/decision-spec-plan[^.]*Skill tool[^.]*before any other/",
            self.asks("use dsp to find why the export drops rows", "no-skill.jsonl"),
        )
        _ = self.hook(
            "/Skill tool/",
            self.asks("run this through decision-spec-plan", "no-skill.jsonl"),
        )
        _ = self.hook(
            "silent",
            self.asks("use dsp to find why the export drops rows", "skill.jsonl"),
        )
        _ = self.write(
            t / "slash.jsonl",
            '{"type":"user","message":{"role":"user","content":[{"type":"text","text":'
            '"Base directory for this skill: /x/.claude/skills/decision-spec-plan\\n\\n'
            '# Decision"}]}}\n',
        )
        _ = self.hook(
            "silent", self.asks("now use dsp for the export bug", "slash.jsonl")
        )
        _ = self.hook(
            "silent",
            self.asks("tune the DSP filter in the audio path", "no-skill.jsonl"),
        )
        _ = self.hook(
            "silent", self.asks("how many dsp-deep agents ran?", "no-skill.jsonl")
        )
        # an agent's return, a path into the skill's own repository or a dsp source dir
        # is not the user naming it
        _ = self.hook(
            "silent",
            self.asks(
                "<task-notification>\n<result>3 bugs in "
                "skills/decision-spec-plan/scripts/"
                "route_state.py, use dsp</result>\n</task-notification>",
                "no-skill.jsonl",
            ),
        )
        _ = self.hook(
            "silent",
            self.asks(
                "fix the README typo in /work/decision-spec-plan", "no-skill.jsonl"
            ),
        )
        _ = self.hook(
            "silent",
            self.asks("the clipping bug is in src/dsp/biquad.c", "no-skill.jsonl"),
        )

        res = self.py(RS, p, "--phase", "1", "--repo", r, "--activate", cwd=r)
        self.ok(
            "activate without a session id: marker written, exit 1, says so",
            res.code == 1
            and self.MK(r).is_file()
            and support.grep(res.out, "CLAUDE_CODE_SESSION_ID is unset"),
            res.out,
        )
        _ = self.hook("silent", ev("PostToolUse", "s1", '"tool_name":"Read"'))

        res = self.py(
            RS,
            p,
            "--phase",
            "1",
            "--repo",
            r,
            "--sections",
            "1-",
            "--activate",
            session="s1",
        )
        self.ok(
            "activate registered s1, --main resolved to main",
            (self.HOME / ".claude/dsp-routes/s1.json").is_file()
            and support.grep_file(self.MK(r), '"--main", "main"'),
            res.out,
        )
        m = self.marker()
        self.ok(
            "a phase with no index yet is bound by the decision ledger, "
            "under today's checks",
            m.get("ledger", {}).get("1") is True
            and m["ledger"].get("1#checks") == CHECKS,
            json.dumps(m),
        )
        _ = self.hook("silent", route_agent("s1", "dsp-deep"))
        _ = self.hook(
            "deny:no active decision-spec-plan route", route_agent("s2", "dsp-deep")
        )
        # a route setting given without --activate was dropped in silence (live)
        for flag in ("--rung L", "--sins on", "--ci-harness e2e"):
            res = self.py(
                RS,
                p,
                "--phase",
                "1",
                "--repo",
                r,
                *flag.split(),
                session="s1",
                merge=True,
            )
            self.ok(
                f"{flag} without --activate is refused",
                res.code == USAGE and support.grep(res.out, "only with --activate"),
                res.out,
            )


if __name__ == "__main__":
    _ = unittest.main()
