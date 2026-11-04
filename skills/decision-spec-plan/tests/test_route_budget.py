"""The Stage 5 budget hold on the lead's `exec-` dispatches (F74, F93), its ETA (F83), the rung-S
harvester refusal (F87), and the hook's gates on a route of its own."""

import json
import shutil
import time
import unittest

import support
from support import (
    RS,
    SCRIPTS,
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


def creq(offset, request, fresh, write, read):
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


def uprompt(offset, kind):
    """A user record: the user's prompt, or an agent's return."""
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "origin": {"kind": kind},
            "message": {"role": "user", "content": "x"},
        }
    )


def endturn(offset):
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


def auq(offset, question="Raise the budget to 50M?"):
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


def refused(offset, tool_id):
    return jline(
        {
            "type": "user",
            "timestamp": ts(offset),
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "is_error": True,
                        "content": "held",
                    }
                ],
            },
        }
    )


SPEND = """import pathlib, sys; sys.path.insert(0, sys.argv[1]); from dsp_route import holds as r
s = lambda f: r.spend([pathlib.Path(sys.argv[2], f)], sys.argv[3])
print(s("gap.jsonl") == s("none.jsonl") < s("busy.jsonl") == s("ret.jsonl"))"""


class Budget(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the rung S the sins section's re-activations left
        cls.activate_route("--rung", "S")
        # the old-format index of the pending section, unbound by the ledger, and its D files
        d = cls.P / "decisions/phase1"
        cls.write(d / "00-index.md", "| D1 | a |\n| D2 | b |\n")
        cls.write(d / "D1-a.md", "ruling\n")
        cls.write(d / "D2-b.md", "ruling\n")
        cls.edit_marker(lambda m: m["ledger"].__setitem__("1", False))
        # the --main section's s9: the route of s1 restarted as another lead session
        reg = cls.HOME / ".claude/dsp-routes"
        shutil.copy(reg / "s1.json", reg / "s9.json")
        cls.touch(cls.HOME / ".claude/projects/p/s9.jsonl", -300)

    def dispatch(self, name, tool_id):
        return ev(
            "PreToolUse",
            "s1",
            f'"tool_name":"Agent","tool_input":{{"name":"{name}"}},'
            f'"tool_use_id":"{tool_id}","transcript_path":"{self.LEAD}"',
        )

    def harvester(self, name, description):
        return ev(
            "PreToolUse",
            "s1",
            '"tool_name":"Agent","tool_input":{"subagent_type":"dsp-deep",'
            f'"name":"{name}","description":"{description}"}}',
        )

    def budget(self, *args, session="s1", merge=False):
        return self.py(RS, "--budget", *args, session=session, merge=merge)

    def test_budget_hold_and_eta(self):
        T, HOME, R, P, LEAD = self.T, self.HOME, self.R, self.P, self.LEAD
        S9 = HOME / ".claude/projects/p/s9.jsonl"
        self.write(LEAD, human(-3600) + "\n")
        self.hook(
            "deny:phase 1 has no Stage 5 budget", self.dispatch("exec-p1-01-a", "t1")
        )
        self.hook("silent", self.dispatch("plan-p1-01", "t1"))
        self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s2",
                '"tool_name":"Agent","tool_input":{"name":"exec-p1-01-a"}',
            ),
        )

        # rung S: the lead harvests itself, so a harvester dispatch is refused (F87)
        self.activate_route("--rung", "S")
        self.hook(
            "deny:rung S has no harvester.*re-announce it at M",
            self.harvester("h1", "MR Harvest h1 runtime"),
        )
        self.hook(
            "deny:rung S has no harvester", self.harvester("harvest-code", "code facts")
        )
        self.hook("silent", self.harvester("s-review", "S review of the plan"))
        # ...but a task group whose work names a harvest, or a review of harvested findings, is
        # no harvester
        self.hook(
            "deny:has no Stage 5 budget",
            self.harvester("exec-p1-01-a", "Fix harvest-date parsing in crop importer"),
        )
        self.hook(
            "silent",
            self.harvester(
                "review-1e", "Second-model review of harvested findings fallback"
            ),
        )
        self.activate_route("--rung", "M")
        self.hook("silent", self.harvester("h1", "MR Harvest h1 runtime"))
        self.activate_route()

        r = self.budget("w1", "--estimate", "10", "--groups", "4", session="s2")
        self.ok("--budget without a registered session: exit 2", r.code == 2, r.out)
        # the planning dir may be named, as leads did (live, 3 refusals); another route's is
        # refused
        r = self.budget("w1", T, "--estimate", "10", "--groups", "4", merge=True)
        self.ok(
            "--budget naming another planning dir records nothing",
            r.code == 2
            and support.grep(r.out, "not this session's route")
            and self.marker().get("budgets") in (None, False),
            r.out,
        )
        # so may the phase and repository, as a lead passed them from --activate (live)
        for flags in ("--phase 2", f"--repo {T}"):
            r = self.budget(
                "w1", *flags.split(), "--estimate", "10", "--groups", "4", merge=True
            )
            self.ok(
                f"--budget {flags} of another route records nothing",
                r.code == 2
                and support.grep(r.out, "not this session's route")
                and self.marker().get("budgets") in (None, False),
                r.out,
            )
        r = self.budget(
            "w1", P, "--phase", "1", "--repo", R, "--estimate", "10", "--groups", "4"
        )
        last = (self.marker().get("budgets") or [{}])[-1]
        self.ok(
            "--budget records the wave in the marker and prints the question to ask",
            r.code == 0
            and last.get("label") == "w1"
            and last.get("groups") == 4
            and last.get("phase") == "1"
            and support.grep(r.out, "past 12.5M spent or 5 exec- dispatches")
            and support.grep(
                r.out, 'Ask exactly: "Wave w1: 10M for 4 exec- agents', F=True
            ),
            r.out,
        )
        self.hook("deny:has not answered", self.dispatch("exec-p1-01-a", "t1"))
        self.append(LEAD, peer(1))
        self.hook("deny:has not answered", self.dispatch("exec-p1-01-a", "t1"))
        self.append(S9, human(1))  # an answer in another lead session of the route
        self.hook("deny:has not answered", self.dispatch("exec-p1-01-a", "t1"))
        self.append(LEAD, human(1))
        self.hook(
            "/^ETA exec-p1-01-a: none yet — no task group of this route has finished/",
            self.dispatch("exec-p1-01-a", "t1"),
        )
        self.activate_route()
        self.ok(
            "a re-activation keeps the budgets",
            len(self.marker().get("budgets", [])) == 1,
        )
        self.unthrottle()
        self.hook(
            "/budget     w1 · 10M · 4 exec- agents/",
            ev("PostToolUse", "s1", '"tool_name":"Agent"'),
        )
        for i in range(1, 5):
            self.append(LEAD, sent(2, f"t{i}", f"exec-p1-0{i}-a"))
        # its own call is not counted twice
        self.hook("/^ETA exec-p1-04-a/", self.dispatch("exec-p1-04-a", "t4"))
        self.hook(
            "/^ETA exec-p1-05-a/", self.dispatch("exec-p1-05-a", "t5")
        )  # 5 = 4 × 1.25
        self.append(LEAD, sent(2, "t5", "exec-p1-05-a"))
        self.hook(
            "deny:this would be exec- dispatch 6 since — more than 25% over",
            self.dispatch("exec-p1-06-a", "t6"),
        )
        self.budget("w2", "--estimate", "0.01", "--groups", "9")
        self.append(LEAD, human(1))
        self.append(LEAD, used(2, "u1", 11000))
        self.hook("/^ETA exec-p1-06-a/", self.dispatch("exec-p1-06-a", "t6"))
        self.append(LEAD, used(2, "u2", 2000))
        self.hook(
            "deny:budget .w2. .*0.0M spent since — more than 25% over",
            self.dispatch("exec-p1-06-a", "t6"),
        )  # the spend
        # a lead's prompt rewritten after it sat idle past the cache's life is the wait's cost,
        # not the wave's (F93)
        IW = T / "idle"
        IW.mkdir()
        head = [creq(-9000, "i1", 1000, 0, 0), creq(-8940, "i2", 0, 1000, 100000)]
        tail = [creq(-4000, "i3", 0, 100000, 0), creq(-3990, "i4", 0, 500, 100000)]
        self.append(IW / "gap.jsonl", *head, uprompt(-4010, "human"), *tail)
        # the same gap ended by a task group's return is the wave's own cost
        self.append(IW / "ret.jsonl", *head, uprompt(-4010, "task-notification"), *tail)
        self.append(IW / "none.jsonl", *head, creq(-3990, "i4", 0, 500, 100000))
        self.append(
            IW / "busy.jsonl",
            *head,
            creq(-8900, "i3", 0, 100000, 0),
            creq(-3990, "i4", 0, 500, 100000),
        )
        out = self.run_(
            [support.PY, "-c", SPEND, SCRIPTS, IW, ts(-10000)], merge=True
        ).out
        self.ok(
            "budget spend: a rewrite after waiting for the user is not the wave's; one after a "
            "group's return or no gap is",
            out == "True",
            out,
        )
        # a budget another lead session recorded, answered there, is not this session's (F74)
        self.budget("w3", "--estimate", "50", "--groups", "9", session="s9")
        self.append(S9, human(2))
        self.append(LEAD, human(2))
        self.hook(
            "deny:recorded in another lead session", self.dispatch("exec-p1-07-a", "t7")
        )
        self.budget("w3", "--estimate", "50", "--groups", "9")
        self.append(LEAD, human(3))
        self.hook("/^ETA exec-p1-07-a/", self.dispatch("exec-p1-07-a", "t7"))
        # asked first, recorded after the answer in the same turn: that one answer is enough
        # (F93); a prompt that opened the turn, or an answer in an earlier turn, is not
        time.sleep(4)  # past the answers stamped up to 3 s ahead above
        self.append(LEAD, endturn(-2))
        self.append(LEAD, human(-1))
        self.budget("w4", "--estimate", "50", "--groups", "9")
        self.hook("deny:has not answered", self.dispatch("exec-p1-07-a", "t7"))
        # an answer to another question in the turn is no answer to the figure
        self.append(LEAD, auq(-1, "Which lane runs first, p1-01 or p1-02?"))
        out = self.budget("w4b", "--estimate", "50", "--groups", "9").out
        self.ok(
            "--budget: an answer to another question does not approve the figure",
            support.grep(out, "Tell the user this figure"),
            out,
        )
        # a non-ASCII sign before the figure
        self.append(LEAD, auq(-1, "Wave w5: ≈50M for 9 exec- agents — go ahead?"))
        out = self.budget("w5", "--estimate", "50", "--groups", "9").out
        self.ok(
            "--budget after an answer in the turn says so",
            support.grep(out, "answered your question at .*earlier in this turn"),
            out,
        )
        self.hook("/^ETA exec-p1-07-a/", self.dispatch("exec-p1-07-a", "t7"))
        self.append(LEAD, endturn(0))
        self.budget("w6", "--estimate", "50", "--groups", "9")
        self.hook("deny:has not answered", self.dispatch("exec-p1-07-a", "t7"))
        self.append(LEAD, human(3))
        # an allowed dispatch's ETA: the median minutes of the route's finished agents of its
        # kind, its lane's first (F83)
        EA = HOME / ".claude/projects/p/s1/subagents"
        EA.mkdir(parents=True)

        def fin(agent, name, start, end, stop, start_stamp=None):
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
            self.write(
                EA / f"agent-{agent}.jsonl", jline(first) + "\n" + jline(last) + "\n"
            )
            self.write(
                EA / f"agent-{agent}.meta.json",
                f'{{"name":"{name}","agentType":"dsp-deep"}}\n',
            )

        fin("f1", "exec-p1-08-a", -7200, -6600, "end_turn")  # 10 min
        fin("f2", "exec-p1-08-b", -6000, -4200, "end_turn")  # 30 min
        fin("f3", "exec-p1-09-a", -7200, -3600, "end_turn")  # 60 min
        fin("f4", "exec-p1-08-c", -5400, -60, "tool_use")  # still running
        fin("f5", "exec-wave1", -3000, 4200, "end_turn")  # 120 min, an integrator
        self.hook(
            r"/^ETA exec-p1-08-d: about 20 min, the median of lane p1-08.s 2 finished task "
            r"groups \(the route.s 3: 30 min\)/",
            self.dispatch("exec-p1-08-d", "t8"),
        )
        self.hook(
            r"/^ETA exec-p1-10-a: about 30 min, the median of the route.s 3 finished task "
            r"groups\. Tell the user/",
            self.dispatch("exec-p1-10-a", "t9"),
        )
        self.hook(
            r"/^ETA exec-wave2: about 120 min, the median of the route.s 1 finished integrator\./",
            self.dispatch("exec-wave2", "t10"),
        )
        # a finished agent whose start time does not parse (a non-ISO string, a number) is no
        # span: it once raised, and the dispatch went out with no ETA at all
        fin("f6", "exec-p1-11-a", -600, -60, "end_turn", start_stamp="soon")
        fin("f7", "exec-p1-12-a", -600, -60, "end_turn", start_stamp=123)
        self.hook(
            r"/^ETA exec-p1-10-a: about 30 min, the median of the route.s 3 finished task "
            r"groups\./",
            self.dispatch("exec-p1-10-a", "t11"),
        )
        for f in EA.glob("agent-f[67].*"):
            f.unlink()


WAVE_SPEND = """import pathlib, sys; sys.path.insert(0, sys.argv[1]); from dsp_route import holds as r
print(int(r.spend([pathlib.Path(sys.argv[2])], sys.argv[3])))"""


class WaveSpend(support.Sandbox):
    """A budget's spend is the lead's and the wave's agents' — not another phase's decision round
    or a re-plan run in the same lead session."""

    def test_spend_counts_only_the_waves_agents(self):
        lead = self.T / "p" / "s1.jsonl"
        self.write(lead, used(-50, "l1", 100) + "\n")
        agents = lead.parent / "s1" / "subagents"

        def agent(name, tokens):
            self.write(agents / f"agent-{name}.jsonl", used(-40, name, tokens) + "\n")
            self.write(agents / f"agent-{name}.meta.json", jline({"name": name}) + "\n")

        def spend():
            out = self.run_([support.PY, "-c", WAVE_SPEND, SCRIPTS, lead, ts(-100)]).out
            return int(out)

        for name, tokens in (
            ("exec-p8-01-a", 1000),
            ("verify-R1", 20),
            ("wrath-p8-push1", 300),
        ):
            agent(name, tokens)
        wave = spend()
        self.ok("the lead and the wave's agents count", wave == 1420, wave)
        # live: a phase-9 harvest and decision round tipped phase 8's wave over; re-plan agents
        # tipped another
        for name in ("harvest-code-p9", "dec-p9-D1", "plan-p1-03"):
            agent(name, 5000)
        self.ok("other agents of the session do not count", spend() == wave, spend())


def teammate_idle(offset, name, **fields):
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
                f"{jline(body)}\n</teammate-message>\n\nThis came from another Claude session.",
            },
        }
    )


class DeadAgent(support.Route):
    """The lead messaging an agent that stopped for good (F64)."""

    def message(self, to):
        return ev(
            "PreToolUse",
            "s1",
            f'"tool_name":"SendMessage","tool_input":{{"to":"{to}","message":"go on"}},'
            f'"transcript_path":"{self.LEAD}"',
        )

    def test_message_to_a_dead_agent_is_refused(self):
        limit = "You've hit your org's monthly spend limit"
        self.write(LEAD := self.LEAD, human(-3600) + "\n")
        # stopped at the limit, but resumable: seven such agents resumed on a message
        self.append(
            LEAD,
            teammate_idle(-600, "plan-p1-08", idleReason="failed", failureReason=limit),
        )
        self.hook("silent", self.message("plan-p1-08"))
        # its run ended: the one agent whose notice said so never received a message
        self.append(
            LEAD,
            teammate_idle(
                -590,
                "plan-p1-11",
                idleReason="failed",
                completedStatus="failed",
                failureReason=limit,
            ),
        )
        self.hook(
            "deny:plan-p1-11 stopped for good .*spend limit.*fresh",
            self.message("plan-p1-11"),
        )
        self.hook("silent", self.message("plan-p1-08"))
        # dispatched again under its name, it is a live agent
        self.append(LEAD, sent(-300, "t1", "plan-p1-11"))
        self.hook("silent", self.message("plan-p1-11"))


class RouteOfItsOwn(support.Sandbox):
    """The hook on a route of its own (session h1)."""

    def test_route_h1(self):
        T, HOME = self.T, self.HOME
        H = self.init_repo(T / "hk")
        (H / ".plan/lanes").mkdir(parents=True)
        HD = H / ".plan/decisions/phase1"
        HD.mkdir(parents=True)
        HL = HOME / ".claude/projects/hk/h1.jsonl"
        self.write(HL, human(-3600) + "\n")
        self.py(
            RS, H / ".plan", "--phase", "1", "--repo", H, "--activate", session="h1"
        )
        TASKS = T / "tasks"  # the stop hook section's task output dir
        TASKS.mkdir()

        def hdispatch(name, tool_id):
            return ev(
                "PreToolUse",
                "h1",
                f'"tool_name":"Agent","tool_input":{{"name":"{name}"}},'
                f'"tool_use_id":"{tool_id}","transcript_path":"{HL}"',
            )

        def budget(*args):
            self.py(RS, "--budget", *args, session="h1")

        # a dispatch refused before it ran is no dispatch
        budget("hw", "--estimate", "50", "--groups", "1")
        self.append(
            HL, sent(1, "r1", "exec-p1-01-a")
        )  # held: the user had not answered yet
        self.append(HL, refused(1, "r1"))
        self.append(HL, human(2))
        self.hook("/^ETA exec-p1-01-a/", hdispatch("exec-p1-01-a", "r2"))
        self.append(HL, sent(3, "r2", "exec-p1-01-a"))
        self.hook(
            "deny:this would be exec- dispatch 2 since", hdispatch("exec-p1-02-a", "r3")
        )
        # each gate fails on its own: a ledger check that raises still leaves the budget hold
        time.sleep(4)  # past the records stamped up to 3 s ahead above
        budget("hw2", "--estimate", "50", "--groups", "4")
        (HD / "00-index.md").mkdir()
        self.hook("deny:has not answered", hdispatch("exec-p1-02-a", "r3"))
        (HD / "00-index.md").rmdir()
        # an arbiter saved in a Windows code page is read, not raised on
        self.write(HD / "00-index.md", support.decision_index("| S1 | **x** | U2 |"))
        self.write(
            HD / "00-seams.md", "# Seams\n**R1** — the cache is never cleared.\n"
        )
        self.write_bytes(
            HD / "00-arbiter.md",
            b"## Dispositions\n| R | How | Basis |\n|---|---|---|\n| R2 | applied | fixed \x96 see U1 |\n",
        )
        self.hook(
            r"deny:decision ledger fails(.|\n)*R1 has no disposition in 00-arbiter.md",
            hdispatch("exec-p1-02-a", "r3"),
        )
        self.rm(HD / "00-index.md", HD / "00-seams.md", HD / "00-arbiter.md")

        # a teammate's monitor runs, with no output file yet, until its notification or its
        # TaskStop (F92)
        HS = HOME / ".claude/projects/hk/h1/subagents"
        HS.mkdir(parents=True)
        hm = HS / "agent-aexec-p1-03-a-0123456789abcdef.jsonl"
        hidle = ev(
            "TeammateIdle",
            "h1",
            '"teammate_name":"exec-p1-03-a","agent_id":"aexec-p1-03-a-0123456789abcdef",'
            f'"transcript_path":"{HL}"',
        )
        gate = {
            "command": "until grep -q ^exit= g.log; do sleep 20; done",
            "description": "gate",
        }
        self.write(
            hm,
            "\n".join(
                call(
                    "m1",
                    "Monitor",
                    gate,
                    "Monitor started (task hmo1, expires in 30m unless the source ends first).",
                )
            )
            + "\n",
        )
        self.stophook(2, r"until grep -q \^exit= g.log.*F92", hidle)
        self.append(hm, notice("hmo1"))  # an event: still running
        self.stophook(2, r"until grep -q \^exit= g.log.*F92", hidle)
        self.append(
            hm,
            *call(
                "m2",
                "Monitor",
                {"command": "tail -f a.log", "description": "a"},
                "Monitor started (task hmo2, expires in 30m unless the source ends first).",
            ),
        )
        self.append(hm, notice("hmo2", "completed"))
        self.stophook(0, "^$", hidle)
        self.append(
            hm,
            *call(
                "m3",
                "Monitor",
                {"command": "tail -f b.log", "description": "b"},
                "Monitor started (task hmo3, expires in 30m unless the source ends first).",
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

        # a job is the one Claude Code records with the result (toolUseResult), not one its
        # output quotes
        def rcall(tool_id, command, result, use_result):
            a, u = call(tool_id, "Bash", {"command": command}, result)
            rec = json.loads(u)
            rec["toolUseResult"] = use_result
            return [a, jline(rec)]

        self.append(
            hm,
            *rcall(
                "q1",
                "cat notes.md",
                f"Command running in background with ID: hph1. Output is being written to: "
                f"{TASKS}/hph1.output.",
                {"stdout": "quoted"},
            ),
        )
        self.stophook(0, "^$", hidle)
        self.write(TASKS / "hbg1.output", "running\n")
        self.append(
            hm,
            *rcall(
                "q2",
                "npm run gate",
                f"Command running in background with ID: hbg1. Output is being written to: "
                f"{TASKS}/hbg1.output. You will be notified when it completes.",
                {"stdout": "", "backgroundTaskId": "hbg1"},
            ),
        )
        self.stophook(2, "npm run gate.*hbg1.output.*F92", hidle)

        # a project named alike whose sessions ran no one knows where is not the route's spend
        budget("hw3", "--estimate", "1", "--groups", "9")
        self.append(HL, human(1))
        other = json.loads(crec(2, "z1", 3000000, "", "sdk-cli"))
        del other["cwd"]
        self.write(HOME / ".claude/projects/hk-other/o.jsonl", jline(other) + "\n")
        self.hook("/^ETA exec-p1-04-a/", hdispatch("exec-p1-04-a", "r9"))

        # a verifier prompt saved in a Windows code page is read, not raised on: raised, the
        # check let every edited verifier prompt through
        self.write_bytes(
            H / ".plan/reviews/s1/verify/R1.prompt.md",
            b"You decide one claim \x96 R1.\n",
        )
        self.hook(
            "deny:a verifier.s prompt is the file",
            ev(
                "PreToolUse",
                "h1",
                '"tool_name":"Agent","tool_input":{"name":"verify-R1","prompt":"edited"},'
                f'"transcript_path":"{HL}"',
            ),
        )


if __name__ == "__main__":
    unittest.main()
