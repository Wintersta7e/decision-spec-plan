# SPDX-License-Identifier: MIT
"""The route's budget hold on the lead's `exec-` dispatches (F74, F93), and its gates.

Also its ETA (F83), the rung-S harvester refusal (F87), and the hook's gates on a route
of its own.
"""

import json
import shutil
import time
import unittest
from pathlib import Path
from typing import cast

from typing_extensions import override

import support
from support import (
    RS,
    SCRIPTS,
    Marker,
    Result,
    call,
    crec,
    ev,
    human,
    jline,
    notice,
    peer,
    sent,
    ts,
    used,
)

REFUSED = 2  # the exit code of a --budget that records nothing
GROUPS = 4  # the task groups the first recorded budget names
ROUTE = 100 + 1000 + 20 + 300  # the lead's tokens and its three route agents'
REVIEWED = ROUTE + 5000 + 5000  # and a review's and a re-plan's


def creq(offset: float, request: str, fresh: int, write: int, read: int) -> str:
    """An assistant turn of request: fresh input, cache-write and cache-read tokens."""
    return jline(
        {
            "type": "assistant",
            "timestamp": ts(offset),
            "requestId": request,
            "message": {
                "id": request,
                "model": "claude-opus-5-5",
                "content": [],
                "usage": {
                    "input_tokens": fresh,
                    "cache_creation_input_tokens": write,
                    "cache_read_input_tokens": read,
                    "output_tokens": 0,
                },
            },
        }
    )


def uprompt(offset: float, kind: str) -> str:
    """A user record: the user's prompt, or an agent's return."""
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "origin": {"kind": kind},
            "message": {"role": "user", "content": "x"},
        }
    )


def endturn(offset: float) -> str:
    """An assistant turn that ends the turn."""
    return jline(
        {
            "type": "assistant",
            "timestamp": ts(offset),
            "message": {
                "id": "e",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "ok"}],
            },
        }
    )


def auq(offset: float, question: str = "Raise the budget to 50M?") -> str:
    """The user's answer Yes to question, asked with AskUserQuestion."""
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "toolUseResult": {
                "questions": [{"question": question}],
                "answers": {question: "Yes"},
            },
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "q", "content": "answered"}
                ],
            },
        }
    )


SPEND = """import pathlib, sys
sys.path.insert(0, sys.argv[1])
from dsp_route import holds as r
s = lambda f: r.spend([pathlib.Path(sys.argv[2], f)], sys.argv[3], "1")
print(s("gap.jsonl") == s("none.jsonl") < s("busy.jsonl") == s("ret.jsonl"))"""


def unbind_phase1(m: Marker) -> None:
    """The ledger's phase 1 marked unbound."""
    m["ledger"]["1"] = False


class Budget(support.Route):
    """The budget hold and the ETA on s1's route at rung S, a lead s9 beside it."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Leave the route as the sins and --main sections do."""
        super().setUpClass()
        # the rung S the sins section's re-activations left
        _ = cls.activate_route("--rung", "S")
        # the old-format index of the pending section, unbound by the ledger, and its D
        # files
        d = cls.P / "decisions/phase1"
        _ = cls.write(d / "00-index.md", "| D1 | a |\n| D2 | b |\n")
        _ = cls.write(d / "D1-a.md", "ruling\n")
        _ = cls.write(d / "D2-b.md", "ruling\n")
        cls.edit_marker(unbind_phase1)
        # the --main section's s9: the route of s1 restarted as another lead session
        reg = cls.HOME / ".claude/dsp-routes"
        _ = shutil.copy(reg / "s1.json", reg / "s9.json")
        cls.touch(cls.HOME / ".claude/projects/p/s9.jsonl", -300)

    def dispatch(self, name: str, tool_id: str) -> str:
        """A PreToolUse of the lead's Agent call that dispatches name."""
        return ev(
            "PreToolUse",
            "s1",
            f'"tool_name":"Agent","tool_input":{{"name":"{name}"}},'
            f'"tool_use_id":"{tool_id}","transcript_path":"{self.LEAD}"',
        )

    def harvester(self, name: str, description: str) -> str:
        """A PreToolUse of a dsp-deep Agent call named name, with its description."""
        return ev(
            "PreToolUse",
            "s1",
            '"tool_name":"Agent","tool_input":{"subagent_type":"dsp-deep",'
            f'"name":"{name}","description":"{description}"}}',
        )

    def budget(self, *args: object, session: str = "s1", merge: bool = False) -> Result:
        """`route_state.py --budget` with args, run by session."""
        return self.py(RS, "--budget", *args, session=session, merge=merge)

    def test_budget_hold_and_eta(self) -> None:
        """A dispatch is held until the user answers its budget, and told its ETA."""
        self.holds_without_a_budget()
        self.records_the_figure()
        self.holds_on_the_spend()
        self.answers_across_sessions()
        self.answers_in_the_turn()
        self.etas_of_finished_agents()

    def holds_without_a_budget(self) -> None:
        """No budget holds an exec- dispatch; rung S refuses a harvester (F87)."""
        _ = self.write(self.LEAD, human(-3600) + "\n")
        _ = self.hook("deny:phase 1 has no budget", self.dispatch("exec-p1-01-a", "t1"))
        _ = self.hook("silent", self.dispatch("plan-p1-01", "t1"))
        _ = self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s2",
                '"tool_name":"Agent","tool_input":{"name":"exec-p1-01-a"}',
            ),
        )

        # rung S: the lead harvests itself, so a harvester dispatch is refused (F87)
        _ = self.activate_route("--rung", "S")
        _ = self.hook(
            "deny:rung S has no harvester.*re-announce it at M",
            self.harvester("h1", "MR Harvest h1 runtime"),
        )
        _ = self.hook(
            "deny:rung S has no harvester", self.harvester("harvest-code", "code facts")
        )
        _ = self.hook("silent", self.harvester("s-review", "S review of the plan"))
        # ...but a task group whose work names a harvest, or a review of harvested
        # findings, is no harvester
        _ = self.hook(
            "deny:has no budget",
            self.harvester("exec-p1-01-a", "Fix harvest-date parsing in crop importer"),
        )
        _ = self.hook(
            "silent",
            self.harvester(
                "review-1e", "Second-model review of harvested findings fallback"
            ),
        )
        _ = self.activate_route("--rung", "M")
        _ = self.hook("silent", self.harvester("h1", "MR Harvest h1 runtime"))
        _ = self.activate_route()

    def records_the_figure(self) -> None:
        """--budget records this route's figure only; the user's answer clears it."""
        root, repo, plan, lead = self.T, self.R, self.P, self.LEAD
        s9 = self.HOME / ".claude/projects/p/s9.jsonl"
        r = self.budget("w1", "--estimate", "10", "--groups", "4", session="s2")
        self.ok(
            "--budget without a registered session: exit 2", r.code == REFUSED, r.out
        )
        # the planning dir may be named, as leads did (live, 3 refusals); another
        # route's is refused
        r = self.budget("w1", root, "--estimate", "10", "--groups", "4", merge=True)
        self.ok(
            "--budget naming another planning dir records nothing",
            r.code == REFUSED
            and support.grep(r.out, "not this session's route")
            and not self.budgets(),
            r.out,
        )
        # so may the phase and repository, as a lead passed them from --activate (live)
        for flags in ("--phase 2", f"--repo {root}"):
            r = self.budget(
                "w1", *flags.split(), "--estimate", "10", "--groups", "4", merge=True
            )
            self.ok(
                f"--budget {flags} of another route records nothing",
                r.code == REFUSED
                and support.grep(r.out, "not this session's route")
                and not self.budgets(),
                r.out,
            )
        r = self.budget(
            "w1",
            plan,
            "--phase",
            "1",
            "--repo",
            repo,
            "--estimate",
            "10",
            "--groups",
            str(GROUPS),
        )
        last = (self.budgets() or [{}])[-1]
        self.ok(
            "--budget records the route's figure in its planning dir and prints the "
            "question",
            r.code == 0
            and last.get("label") == "w1"
            and last.get("groups") == GROUPS
            and last.get("phase") == "1"
            and support.grep(r.out, "spend from now passes 12.5M")
            and support.grep(
                r.out,
                "Ask exactly: \"w1: 10M for phase 1's work left "
                "— the lead, its reviews",
                F=True,
            ),
            r.out,
        )
        _ = self.hook("deny:has not answered", self.dispatch("exec-p1-01-a", "t1"))
        self.append(lead, peer(1))
        _ = self.hook("deny:has not answered", self.dispatch("exec-p1-01-a", "t1"))
        self.append(s9, human(1))  # an answer in another lead session of the route
        _ = self.hook("deny:has not answered", self.dispatch("exec-p1-01-a", "t1"))
        self.append(lead, human(1))
        _ = self.hook(
            "/^ETA exec-p1-01-a: none yet — no task group of this route has finished/",
            self.dispatch("exec-p1-01-a", "t1"),
        )
        _ = self.activate_route()
        self.ok(
            "a re-activation keeps the budget, with the answer the hold saw",
            len(self.budgets()) == 1 and bool(self.budgets()[0].get("answered")),
            self.budgets(),
        )
        self.unthrottle()
        _ = self.hook(
            "/budget     w1 · 10M · 4 exec- agents/",
            ev("PostToolUse", "s1", '"tool_name":"Agent"'),
        )

    def holds_on_the_spend(self) -> None:
        """A budget holds on its spend, never on the count of its dispatches (F74)."""
        lead = self.LEAD
        # no hold on the count of exec- dispatches: the successor of a group the context
        # stop ended is no overrun (F74)
        for i in range(1, 7):
            self.append(lead, sent(2, f"t{i}", f"exec-p1-0{i}-a"))
        _ = self.hook("/^ETA exec-p1-07-a/", self.dispatch("exec-p1-07-a", "t7"))
        _ = self.budget("w2", "--estimate", "0.01", "--groups", "9")
        self.append(lead, human(1))
        self.append(lead, used(2, "u1", 11000))
        _ = self.hook("/^ETA exec-p1-06-a/", self.dispatch("exec-p1-06-a", "t6"))
        self.append(lead, used(2, "u2", 2000))
        _ = self.hook(
            "deny:budget .w2. .*0.0M spent since — more than 25% over",
            self.dispatch("exec-p1-06-a", "t6"),
        )  # the spend
        # a lead's prompt rewritten after it sat idle past the cache's life is the
        # wait's cost, not the wave's (F93)
        idle = self.T / "idle"
        idle.mkdir()
        head = [creq(-9000, "i1", 1000, 0, 0), creq(-8940, "i2", 0, 1000, 100000)]
        tail = [creq(-4000, "i3", 0, 100000, 0), creq(-3990, "i4", 0, 500, 100000)]
        self.append(idle / "gap.jsonl", *head, uprompt(-4010, "human"), *tail)
        # the same gap ended by a task group's return is the wave's own cost
        self.append(
            idle / "ret.jsonl", *head, uprompt(-4010, "task-notification"), *tail
        )
        self.append(idle / "none.jsonl", *head, creq(-3990, "i4", 0, 500, 100000))
        self.append(
            idle / "busy.jsonl",
            *head,
            creq(-8900, "i3", 0, 100000, 0),
            creq(-3990, "i4", 0, 500, 100000),
        )
        out = self.run_(
            [support.PY, "-c", SPEND, SCRIPTS, idle, ts(-10000)], merge=True
        ).out
        self.ok(
            "budget spend: a rewrite after waiting for the user is not the wave's; one "
            "after a group's return or no gap is",
            out == "True",
            out,
        )

    def answers_across_sessions(self) -> None:
        """One budget a route: an answer counts in the lead session that recorded it."""
        home, lead = self.HOME, self.LEAD
        s9 = home / ".claude/projects/p/s9.jsonl"
        # one budget a route: a figure another lead session recorded and its user
        # answered there holds here too — a hand-over asked both budgets again (F74) —
        # but an answer here is no answer to a figure this session never told
        time.sleep(4)  # past the answers stamped up to 3 s ahead above
        _ = self.budget("w3", "--estimate", "50", "--groups", "9", session="s9")
        self.append(lead, human(2))
        _ = self.hook(
            "deny:has not answered it in the lead session that recorded it.*record it "
            "again from this one",
            self.dispatch("exec-p1-07-a", "t7"),
        )
        self.append(s9, human(2))
        _ = self.hook("/^ETA exec-p1-07-a/", self.dispatch("exec-p1-07-a", "t7"))
        # an agent named for another phase is that phase's work, left out of this spend
        _ = self.hook(
            "deny:exec-p9-01-a names another phase than this route's phase 1",
            self.dispatch("exec-p9-01-a", "t7"),
        )
        # a headless lead (no prompt of the user's) passes its own dispatches, never
        # another session's, and its pass is not kept with the record
        s8 = home / ".claude/projects/p/s8.jsonl"
        reg = home / ".claude/dsp-routes"
        _ = shutil.copy(reg / "s1.json", reg / "s8.json")
        _ = self.write(s8, "")
        time.sleep(1)
        _ = self.budget("w3h", "--estimate", "50", "--groups", "9", session="s8")
        _ = self.hook(
            "/^ETA exec-p1-07-a/",
            ev(
                "PreToolUse",
                "s8",
                '"tool_name":"Agent","tool_input":{"name":"exec-p1-07-a"},'
                f'"tool_use_id":"t7","transcript_path":"{s8}"',
            ),
        )
        _ = self.hook("deny:has not answered", self.dispatch("exec-p1-07-a", "t7"))
        self.ok(
            "a headless session's pass is not kept with the budget",
            not self.budgets()[-1].get("answered"),
            self.budgets(),
        )

    def answers_in_the_turn(self) -> None:
        """An answer in the turn approves a figure; at S it is told, not asked."""
        plan, lead = self.P, self.LEAD
        # asked first, recorded after the answer in the same turn: that one answer is
        # enough (F93); a prompt that opened the turn, or an answer in an earlier turn,
        # is not
        time.sleep(4)  # past the answers stamped up to 3 s ahead above
        self.append(lead, endturn(-2))
        self.append(lead, human(-1))
        _ = self.budget("w4", "--estimate", "50", "--groups", "9")
        _ = self.hook("deny:has not answered", self.dispatch("exec-p1-07-a", "t7"))
        # an answer to another question in the turn is no answer to the figure
        self.append(lead, auq(-1, "Which lane runs first, p1-01 or p1-02?"))
        out = self.budget("w4b", "--estimate", "50", "--groups", "9").out
        self.ok(
            "--budget: an answer to another question does not approve the figure",
            support.grep(out, "Tell the user this figure"),
            out,
        )
        # a non-ASCII sign before the figure
        self.append(lead, auq(-1, "Wave w5: ≈50M for 9 exec- agents — go ahead?"))
        out = self.budget("w5", "--estimate", "50", "--groups", "9").out
        self.ok(
            "--budget after an answer in the turn says so",
            support.grep(out, "answered your question at .*earlier in this turn"),
            out,
        )
        _ = self.hook("/^ETA exec-p1-07-a/", self.dispatch("exec-p1-07-a", "t7"))
        self.append(lead, endturn(0))
        _ = self.budget("w6", "--estimate", "50", "--groups", "9")
        _ = self.hook("deny:has not answered", self.dispatch("exec-p1-07-a", "t7"))
        # at S the figure is told with the plan, not asked: 58 of 121 questions in one
        # window were budget asks, 50 approved as offered (F74)
        _ = self.activate_route("--rung", "S")
        out = self.budget("s1-round", "--estimate", "50").out
        self.ok(
            "--budget at S says to tell the figure and go on",
            support.grep(out, "At S, tell the user this figure with the plan and go on")
            and not support.grep(out, "Ask exactly"),
            out,
        )
        _ = self.hook("/^ETA exec-p1-07-a/", self.dispatch("exec-p1-07-a", "t7"))
        # the lane's plan names its gates' minutes: the ETA carries them (F83)
        _ = self.write(
            plan / "plans/p1-07-a.md",
            "## Gates\n| Gate | Command | Minutes | Runs |\n|---|---|---|---|\n"
            "| unit | `npm test` | 3 | group |\n| e2e | `npm run e2e` | 45 | lead |\n",
        )
        _ = self.hook(
            "/^ETA exec-p1-07-a: .* Its plan's gates: 3 min in the group that runs "
            "them, 45 min the lead's or CI's/",
            self.dispatch("exec-p1-07-a", "t7"),
        )
        _ = self.activate_route("--rung", "M")
        _ = self.budget("w6", "--estimate", "50", "--groups", "9")
        self.append(lead, human(3))

    def etas_of_finished_agents(self) -> None:
        """A dispatch's ETA is the median of its kind's finished agents (F83)."""
        # an allowed dispatch's ETA: the median minutes of the route's finished agents
        # of its kind, its lane's first (F83)
        subagents = self.HOME / ".claude/projects/p/s1/subagents"
        subagents.mkdir(parents=True)

        def fin(
            agent: str,
            name: str,
            span: tuple[float, float],
            stop: str,
            start_stamp: str | int | None = None,
        ) -> None:
            start, end = span
            first = {
                "type": "user",
                "timestamp": ts(start) if start_stamp is None else start_stamp,
                "message": {"role": "user", "content": "go"},
            }
            last = {
                "type": "assistant",
                "timestamp": ts(end),
                "message": {
                    "id": "m",
                    "stop_reason": stop,
                    "content": [{"type": "text", "text": "done"}],
                },
            }
            _ = self.write(
                subagents / f"agent-{agent}.jsonl",
                jline(first) + "\n" + jline(last) + "\n",
            )
            _ = self.write(
                subagents / f"agent-{agent}.meta.json",
                f'{{"name":"{name}","agentType":"dsp-deep"}}\n',
            )

        fin("f1", "exec-p1-08-a", (-7200, -6600), "end_turn")  # 10 min
        fin("f2", "exec-p1-08-b", (-6000, -4200), "end_turn")  # 30 min
        fin("f3", "exec-p1-09-a", (-7200, -3600), "end_turn")  # 60 min
        fin("f4", "exec-p1-08-c", (-5400, -60), "tool_use")  # still running
        fin("f5", "exec-wave1", (-3000, 4200), "end_turn")  # 120 min, an integrator
        _ = self.hook(
            r"/^ETA exec-p1-08-d: about 20 min, the median of lane p1-08.s 2 finished "
            r"task groups \(the route.s 3: 30 min\)/",
            self.dispatch("exec-p1-08-d", "t8"),
        )
        _ = self.hook(
            r"/^ETA exec-p1-10-a: about 30 min, the median of the route.s 3 finished "
            r"task groups\. Tell the user/",
            self.dispatch("exec-p1-10-a", "t9"),
        )
        _ = self.hook(
            r"/^ETA exec-wave2: about 120 min, the median of the route.s 1 finished "
            r"integrator\./",
            self.dispatch("exec-wave2", "t10"),
        )
        # a finished agent whose start time does not parse (a non-ISO string, a number)
        # is no span: it once raised, and the dispatch went out with no ETA at all
        fin("f6", "exec-p1-11-a", (-600, -60), "end_turn", start_stamp="soon")
        fin("f7", "exec-p1-12-a", (-600, -60), "end_turn", start_stamp=123)
        _ = self.hook(
            r"/^ETA exec-p1-10-a: about 30 min, the median of the route.s 3 finished "
            r"task groups\./",
            self.dispatch("exec-p1-10-a", "t11"),
        )
        for f in subagents.glob("agent-f[67].*"):
            f.unlink()


ROUTE_SPEND = """import pathlib, sys
sys.path.insert(0, sys.argv[1])
from dsp_route import holds as r
print(int(r.spend([pathlib.Path(sys.argv[2])], sys.argv[3], "8")))"""


class RouteSpend(support.Sandbox):
    """A budget's spend is the lead's and every agent's of the route.

    A review's counts too, but not another phase's harvest or decision round run in the
    same lead session.
    """

    def test_spend_counts_the_routes_agents(self) -> None:
        """The route's agents count, a review and a re-plan too; another phase's not."""
        lead = self.T / "p" / "s1.jsonl"
        _ = self.write(lead, used(-50, "l1", 100) + "\n")
        agents = lead.parent / "s1" / "subagents"

        def agent(name: str, tokens: int) -> None:
            _ = self.write(
                agents / f"agent-{name}.jsonl", used(-40, name, tokens) + "\n"
            )
            _ = self.write(
                agents / f"agent-{name}.meta.json", jline({"name": name}) + "\n"
            )

        def spend() -> int:
            out = self.run_(
                [support.PY, "-c", ROUTE_SPEND, SCRIPTS, lead, ts(-100)]
            ).out
            return int(out)

        for name, tokens in (
            ("exec-p8-01-a", 1000),
            ("verify-R1", 20),
            ("wrath-p8-push1", 300),
        ):
            agent(name, tokens)
        route = spend()
        self.ok("the lead and the route's agents count", route == ROUTE, route)
        # live: a phase-9 harvest and decision round tipped phase 8's wave over
        for name in ("harvest-code-p9", "dec-p9-D1", "plan-p1-03"):
            agent(name, 5000)
        self.ok("another phase's agents do not count", spend() == route, spend())
        # the route's budget prices its reviews and re-plans: overruns of 152–364% came
        # from the work no figure priced (F74)
        agent("review-1e", 5000)
        agent("plan-p8-03", 5000)
        self.ok(
            "a review and a re-plan of the phase count", spend() == REVIEWED, spend()
        )


def teammate_idle(offset: float, name: str, **fields: str) -> str:
    """An agent's idle notice as the lead's transcript carries it: a user record."""
    body = {
        "type": "idle_notification",
        "from": name,
        "timestamp": ts(offset),
        **fields,
    }
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "message": {
                "role": "user",
                "content": "Another Claude session sent a message:\n"
                f'<teammate-message teammate_id="{name}" color="orange">\n'
                f"{jline(body)}\n</teammate-message>\n\n"
                "This came from another Claude session.",
            },
        }
    )


class DeadAgent(support.Route):
    """The lead messaging an agent that stopped for good (F64)."""

    def message(self, to: str) -> str:
        """A PreToolUse of the lead's SendMessage call to agent to."""
        return ev(
            "PreToolUse",
            "s1",
            '"tool_name":"SendMessage",'
            f'"tool_input":{{"to":"{to}","message":"go on"}},'
            f'"transcript_path":"{self.LEAD}"',
        )

    def test_message_to_a_dead_agent_is_refused(self) -> None:
        """A message to an agent whose run ended is refused; one resumable is not."""
        limit = "You've hit your org's monthly spend limit"
        _ = self.write(lead := self.LEAD, human(-3600) + "\n")
        # stopped at the limit, but resumable: seven such agents resumed on a message
        self.append(
            lead,
            teammate_idle(-600, "plan-p1-08", idleReason="failed", failureReason=limit),
        )
        _ = self.hook("silent", self.message("plan-p1-08"))
        # its run ended: the one agent whose notice said so never received a message
        self.append(
            lead,
            teammate_idle(
                -590,
                "plan-p1-11",
                idleReason="failed",
                completedStatus="failed",
                failureReason=limit,
            ),
        )
        _ = self.hook(
            "deny:plan-p1-11 stopped for good .*spend limit.*fresh",
            self.message("plan-p1-11"),
        )
        _ = self.hook("silent", self.message("plan-p1-08"))
        # dispatched again under its name, it is a live agent
        self.append(lead, sent(-300, "t1", "plan-p1-11"))
        _ = self.hook("silent", self.message("plan-p1-11"))


def monitor_call(tool_id: str, inp: dict[str, object], task: str) -> list[str]:
    """A Monitor call and its result: started as task."""
    return call(
        tool_id,
        "Monitor",
        inp,
        f"Monitor started (task {task}, expires in 30m unless the source ends first).",
    )


def bash_call(
    tool_id: str, command: str, result: str, use_result: dict[str, object]
) -> list[str]:
    """A Bash call and its result, which Claude Code records as use_result."""
    a, u = call(tool_id, "Bash", {"command": command}, result)
    rec = cast("dict[str, object]", json.loads(u))
    rec["toolUseResult"] = use_result
    return [a, jline(rec)]


class RouteOfItsOwn(support.Sandbox):
    """The hook on a route of its own (session h1)."""

    @property
    def hk(self) -> Path:
        """The route's repository."""
        return self.T / "hk"

    @property
    def decisions(self) -> Path:
        """The route's decisions directory of phase 1."""
        return self.hk / ".plan/decisions/phase1"

    @property
    def hlead(self) -> Path:
        """The transcript of h1, the route's lead."""
        return self.HOME / ".claude/projects/hk/h1.jsonl"

    @property
    def tasks(self) -> Path:
        """The stop hook section's task output dir."""
        return self.T / "tasks"

    def hdispatch(self, name: str, tool_id: str) -> str:
        """A PreToolUse of h1's Agent call that dispatches name."""
        return ev(
            "PreToolUse",
            "h1",
            f'"tool_name":"Agent","tool_input":{{"name":"{name}"}},'
            f'"tool_use_id":"{tool_id}","transcript_path":"{self.hlead}"',
        )

    def hbudget(self, *args: str) -> None:
        """`route_state.py --budget` with args, run by h1."""
        _ = self.py(RS, "--budget", *args, session="h1")

    def test_route_h1(self) -> None:
        """Each gate of the hook holds on its own on h1's route."""
        hk = self.hk
        _ = self.init_repo(hk)
        (hk / ".plan/lanes").mkdir(parents=True)
        self.decisions.mkdir(parents=True)
        _ = self.write(self.hlead, human(-3600) + "\n")
        _ = self.py(
            RS, hk / ".plan", "--phase", "1", "--repo", hk, "--activate", session="h1"
        )
        self.tasks.mkdir()
        self.budget_and_ledger_holds()
        self.running_monitors_and_jobs()
        self.other_projects_and_prompts()

    def budget_and_ledger_holds(self) -> None:
        """The budget holds on its spend; a raising ledger check still leaves it."""
        decisions, hlead = self.decisions, self.hlead
        # one budget a route, held on its spend, never on its count of exec- dispatches:
        # the successor of a group the context stop ended asked the user again (F74)
        self.hbudget("hw", "--estimate", "50", "--groups", "1")
        self.append(hlead, human(2))
        _ = self.hook("/^ETA exec-p1-01-a/", self.hdispatch("exec-p1-01-a", "r2"))
        self.append(hlead, sent(3, "r2", "exec-p1-01-a"))
        _ = self.hook("/^ETA exec-p1-02-a/", self.hdispatch("exec-p1-02-a", "r3"))
        # each gate fails on its own: a ledger check that raises still leaves the budget
        # hold
        time.sleep(4)  # past the records stamped up to 3 s ahead above
        self.hbudget("hw2", "--estimate", "50", "--groups", "4")
        (decisions / "00-index.md").mkdir()
        _ = self.hook("deny:has not answered", self.hdispatch("exec-p1-02-a", "r3"))
        (decisions / "00-index.md").rmdir()
        # an arbiter saved in a Windows code page is read, not raised on
        _ = self.write(
            decisions / "00-index.md", support.decision_index("| S1 | **x** | U2 |")
        )
        _ = self.write(
            decisions / "00-seams.md", "# Seams\n**R1** — the cache is never cleared.\n"
        )
        _ = self.write_bytes(
            decisions / "00-arbiter.md",
            b"## Dispositions\n| R | How | Basis |\n|---|---|---|\n"
            b"| R2 | applied | fixed \x96 see U1 |\n",
        )
        _ = self.hook(
            r"deny:decision ledger fails(.|\n)*R1 has no disposition in 00-arbiter.md",
            self.hdispatch("exec-p1-02-a", "r3"),
        )
        self.rm(
            decisions / "00-index.md",
            decisions / "00-seams.md",
            decisions / "00-arbiter.md",
        )

    def running_monitors_and_jobs(self) -> None:
        """A teammate's monitor or background job runs until it is seen to end (F92)."""
        tasks = self.tasks
        # a teammate's monitor, with no output file yet, runs until its notification or
        # the call that stops it (F92)
        hsub = self.HOME / ".claude/projects/hk/h1/subagents"
        hsub.mkdir(parents=True)
        hm = hsub / "agent-aexec-p1-03-a-0123456789abcdef.jsonl"
        hidle = ev(
            "TeammateIdle",
            "h1",
            '"teammate_name":"exec-p1-03-a",'
            '"agent_id":"aexec-p1-03-a-0123456789abcdef",'
            f'"transcript_path":"{self.hlead}"',
        )
        gate: dict[str, object] = {
            "command": "until grep -q ^exit= g.log; do sleep 20; done",
            "description": "gate",
        }
        _ = self.write(hm, "\n".join(monitor_call("m1", gate, "hmo1")) + "\n")
        self.stophook(2, r"until grep -q \^exit= g.log.*F92", hidle)
        self.append(hm, notice("hmo1"))  # an event: still running
        self.stophook(2, r"until grep -q \^exit= g.log.*F92", hidle)
        self.append(
            hm,
            *monitor_call(
                "m2", {"command": "tail -f a.log", "description": "a"}, "hmo2"
            ),
        )
        self.append(hm, notice("hmo2", "completed"))
        self.stophook(0, "^$", hidle)
        self.append(
            hm,
            *monitor_call(
                "m3", {"command": "tail -f b.log", "description": "b"}, "hmo3"
            ),
        )
        self.append(
            hm,
            *call(
                "s3",
                "TaskStop",
                {"task_id": "hmo3"},
                '{"message":"Successfully stopped task: hmo3"}',
            ),
        )
        self.stophook(0, "^$", hidle)

        # a job is the one Claude Code records with the result (toolUseResult), not one
        # its output quotes
        self.append(
            hm,
            *bash_call(
                "q1",
                "cat notes.md",
                "Command running in background with ID: hph1. "
                f"Output is being written to: {tasks}/hph1.output.",
                {"stdout": "quoted"},
            ),
        )
        self.stophook(0, "^$", hidle)
        _ = self.write(tasks / "hbg1.output", "running\n")
        self.append(
            hm,
            *bash_call(
                "q2",
                "npm run gate",
                "Command running in background with ID: hbg1. "
                f"Output is being written to: {tasks}/hbg1.output. "
                "You will be notified when it completes.",
                {"stdout": "", "backgroundTaskId": "hbg1"},
            ),
        )
        self.stophook(2, "npm run gate.*hbg1.output.*F92", hidle)

    def other_projects_and_prompts(self) -> None:
        """A project named alike is not the route's spend; a cp1252 prompt is read."""
        hlead = self.hlead
        # a project named alike whose sessions ran no one knows where is not the route's
        # spend
        self.hbudget("hw3", "--estimate", "1", "--groups", "9")
        self.append(hlead, human(1))
        other = cast(
            "dict[str, object]", json.loads(crec(2, "z1", 3000000, "", "sdk-cli"))
        )
        del other["cwd"]
        _ = self.write(
            self.HOME / ".claude/projects/hk-other/o.jsonl", jline(other) + "\n"
        )
        _ = self.hook("/^ETA exec-p1-04-a/", self.hdispatch("exec-p1-04-a", "r9"))

        # a verifier prompt saved in a Windows code page is read, not raised on: raised,
        # the check let every edited verifier prompt through
        _ = self.write_bytes(
            self.hk / ".plan/reviews/s1/verify/R1.prompt.md",
            b"You decide one claim \x96 R1.\n",
        )
        _ = self.hook(
            "deny:a verifier.s prompt is the file",
            ev(
                "PreToolUse",
                "h1",
                '"tool_name":"Agent",'
                '"tool_input":{"name":"verify-R1","prompt":"edited"},'
                f'"transcript_path":"{hlead}"',
            ),
        )


class BaseMoved(support.Sandbox):
    """What the round was planned on moved: a held decision at the budget (F91)."""

    def test_base_moved_is_held_until_decided(self) -> None:
        """A base behind upstream holds dispatches until the user decides."""
        root, home = self.T, self.HOME
        up = self.init_repo(root / "up", commits=("one",))
        clone = root / "clone"
        _ = self.git("clone", "-q", up, clone)
        _ = self.git("-C", clone, "config", "user.email", "t@t")
        _ = self.git("-C", clone, "config", "user.name", "t")
        plan = clone / ".plan"
        _ = self.write(
            plan / "decisions/phase1/00-index.md",
            f"> **Base**: `main` at `{self.rev(clone, 'main')}`\n",
        )
        _ = self.py(
            RS, plan, "--phase", "1", "--repo", clone, "--activate", session="s1"
        )
        lead = home / ".claude/projects/p/s1.jsonl"
        _ = self.write(lead, human(-3600) + "\n")

        def dispatch() -> str:
            return ev(
                "PreToolUse",
                "s1",
                '"tool_name":"Agent","tool_input":{"name":"exec-p1-01-a"},'
                f'"tool_use_id":"t1","transcript_path":"{lead}"',
            )

        def budget(label: str, *extra: str) -> str:
            out = self.py(
                RS,
                "--budget",
                label,
                "--estimate",
                "10",
                *extra,
                session="s1",
                merge=True,
            ).out
            time.sleep(1)
            self.append(lead, human(1))
            return out

        def upstream() -> None:
            _ = self.git("-C", up, "commit", "-q", "--allow-empty", "-m", "theirs")
            _ = self.git("-C", clone, "fetch", "-q")

        _ = budget("w1")
        _ = self.hook("/^ETA exec-p1-01-a/", dispatch())
        # the route's own merge moves only the local base
        _ = self.git("-C", clone, "commit", "-q", "--allow-empty", "-m", "ours")
        _ = self.hook("/^ETA exec-p1-01-a/", dispatch())
        upstream()
        _ = self.hook(
            "deny:(?s)what this round was planned on moved.*base behind upstream "
            "*main lacks 1 commits.*pin.*catch up.*track by merge",
            dispatch(),
        )
        out = budget("w2")
        self.ok(
            "--budget names the move and the choice to ask with the figure",
            support.grep(out, "base behind upstream")
            and support.grep(out, "--base pin|catch-up|merge", F=True),
            out,
        )
        _ = self.hook("deny:base behind upstream", dispatch())
        _ = budget("w3", "--base", "catch-up")
        _ = self.hook("/^ETA exec-p1-01-a/", dispatch())
        # caught up to that move, not to the next one
        upstream()
        _ = self.hook("deny:main lacks 2 commits", dispatch())
        _ = budget("w4", "--base", "pin")
        _ = self.hook("/^ETA exec-p1-01-a/", dispatch())
        # a later figure keeps the user's choice
        upstream()
        _ = budget("w5")
        _ = self.hook("/^ETA exec-p1-01-a/", dispatch())


if __name__ == "__main__":
    _ = unittest.main()
