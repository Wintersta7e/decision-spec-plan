"""`route_state.py --activate` and the hooks before and around it: no route, a prompt naming the
route before its skill loaded, a route agent dispatched with none, and route settings given without
--activate."""

import json
import unittest

import support
from support import RS, ev, jstr


def route_agent(session, kind):
    return ev(
        "PreToolUse",
        session,
        f'"tool_name":"Agent","tool_input":{{"subagent_type":"{kind}","name":"pride-r1"}}',
    )


class NoRouteThenActivate(support.Route):
    activate = False

    def asks(self, prompt, transcript):
        return ev(
            "UserPromptSubmit",
            "s1",
            f'"prompt":{jstr(prompt)},"transcript_path":"{self.T}/{transcript}"',
        )

    def test_no_route_active(self):
        R, P, T = self.R, self.P, self.T
        # no route active: everything passes, the hook is silent
        self.guard(0, R, "git push origin main")
        self.guard(0, R, "git --no-pager push origin main")
        self.guard(0, R, "DSP_SKIP_PUSH_GUARD=1 git push origin main")
        self.hook("silent", ev("PostToolUse", "s1", '"tool_name":"Agent"'))
        # ...but a route agent dispatched with no route means the skill never loaded (F79)
        self.hook(
            "deny:no active decision-spec-plan route.*Skill tool.*--activate --rung",
            route_agent("s1", "dsp-deep"),
        )
        self.hook(
            "deny:no active decision-spec-plan route",
            route_agent("s1", "decision-spec-plan:dsp-mechanical"),
        )
        self.hook("silent", route_agent("s1", "general-purpose"))
        self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s1",
                '"agent_id":"a1","tool_name":"Agent","tool_input":{"subagent_type":"dsp-deep"}',
            ),
        )
        # a prompt naming the route in a session that has not loaded it: the skill first, before
        # any work (one lead did 43 minutes of work after "use dsp" before loading it)
        self.write(
            T / "no-skill.jsonl",
            '{"type":"user","message":{"role":"user","content":"hi"}}\n',
        )
        self.write(
            T / "skill.jsonl",
            '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"k1",'
            '"name":"Skill","input":{"skill":"decision-spec-plan"}}]}}\n',
        )
        self.hook(
            "/decision-spec-plan[^.]*Skill tool[^.]*before any other/",
            self.asks("use dsp to find why the export drops rows", "no-skill.jsonl"),
        )
        self.hook(
            "/Skill tool/",
            self.asks("run this through decision-spec-plan", "no-skill.jsonl"),
        )
        self.hook(
            "silent",
            self.asks("use dsp to find why the export drops rows", "skill.jsonl"),
        )
        self.write(
            T / "slash.jsonl",
            '{"type":"user","message":{"role":"user","content":[{"type":"text","text":'
            '"Base directory for this skill: /x/.claude/skills/decision-spec-plan\\n\\n'
            '# Decision"}]}}\n',
        )
        self.hook("silent", self.asks("now use dsp for the export bug", "slash.jsonl"))
        self.hook(
            "silent",
            self.asks("tune the DSP filter in the audio path", "no-skill.jsonl"),
        )
        self.hook(
            "silent", self.asks("how many dsp-deep agents ran?", "no-skill.jsonl")
        )
        # an agent's return, a path into the skill's own repository or a dsp source dir is not
        # the user naming it
        self.hook(
            "silent",
            self.asks(
                "<task-notification>\n<result>3 bugs in skills/decision-spec-plan/scripts/"
                "route_state.py, use dsp</result>\n</task-notification>",
                "no-skill.jsonl",
            ),
        )
        self.hook(
            "silent",
            self.asks(
                "fix the README typo in /work/decision-spec-plan", "no-skill.jsonl"
            ),
        )
        self.hook(
            "silent",
            self.asks("the clipping bug is in src/dsp/biquad.c", "no-skill.jsonl"),
        )

        r = self.py(RS, P, "--phase", "1", "--repo", R, "--activate", cwd=R)
        self.ok(
            "activate without a session id: marker written, exit 1, says so",
            r.code == 1
            and self.MK(R).is_file()
            and support.grep(r.out, "CLAUDE_CODE_SESSION_ID is unset"),
            r.out,
        )
        self.hook("silent", ev("PostToolUse", "s1", '"tool_name":"Read"'))

        r = self.py(
            RS,
            P,
            "--phase",
            "1",
            "--repo",
            R,
            "--sections",
            "1-",
            "--activate",
            session="s1",
        )
        self.ok(
            "activate registered s1, --main resolved to main",
            (self.HOME / ".claude/dsp-routes/s1.json").is_file()
            and support.grep_file(self.MK(R), '"--main", "main"'),
            r.out,
        )
        m = self.marker()
        self.ok(
            "a phase with no index yet is bound by the decision ledger, under today's checks",
            m.get("ledger", {}).get("1") is True and m["ledger"].get("1#checks") == 2,
            json.dumps(m),
        )
        self.hook("silent", route_agent("s1", "dsp-deep"))
        self.hook(
            "deny:no active decision-spec-plan route", route_agent("s2", "dsp-deep")
        )
        # a route setting given without --activate was dropped in silence (live)
        for flag in ("--rung L", "--sins on", "--ci-harness e2e"):
            r = self.py(
                RS,
                P,
                "--phase",
                "1",
                "--repo",
                R,
                *flag.split(),
                session="s1",
                merge=True,
            )
            self.ok(
                f"{flag} without --activate is refused",
                r.code == 2 and support.grep(r.out, "only with --activate"),
                r.out,
            )


if __name__ == "__main__":
    unittest.main()
