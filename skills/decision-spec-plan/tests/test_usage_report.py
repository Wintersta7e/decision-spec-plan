"""usage_report.py: --since and --until, --project-dir, units by model, efforts, --groups, the
measured group fit --budget prints, and which transcripts are a route's lead, agents and hook
sessions."""

import datetime
import json
import re
import shutil
import unittest

import support
from support import RS, crec, human, jline, peer, sent, ts, used

UR = support.SCRIPTS / "usage_report.py"


def rec(offset, request, model, tokens, entrypoint=""):
    r = {
        "type": "assistant",
        "timestamp": ts(offset),
        "requestId": request,
        "message": {
            "id": request,
            "model": model,
            "content": [],
            "usage": {"cache_read_input_tokens": tokens},
        },
    }
    if entrypoint:
        r["entrypoint"] = entrypoint
    return jline(r)


def erec(offset, request, effort):
    r = {
        "type": "assistant",
        "timestamp": ts(offset),
        "requestId": request,
        "message": {
            "id": request,
            "model": "claude-sonnet-5-5",
            "content": [],
            "usage": {"input_tokens": 1000},
        },
    }
    if effort:
        r["effort"] = effort
    return jline(r)


def grec(offset, request, tokens, content=()):
    return jline(
        {
            "type": "assistant",
            "timestamp": ts(offset),
            "requestId": request,
            "message": {
                "id": request,
                "model": "claude-opus-5-5",
                "content": list(content),
                "usage": {"cache_read_input_tokens": tokens},
            },
        }
    )


def tool(tool_id, name, command=""):
    return [
        {"type": "tool_use", "id": tool_id, "name": name, "input": {"command": command}}
    ]


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


def auq(offset, question):
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


FIT_READS_NO_SDK = """import sys; sys.path.insert(0, sys.argv[1])
from dsp_route import budget, transcript
def read(*a): raise SystemExit("sdk sessions read")
transcript.sdk_transcripts = read
print(budget.measured_fit("g1")[1])"""


class UsageReport(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reg = cls.HOME / ".claude/dsp-routes"
        # the --main section's s9 copy of the route, and the lead transcripts the budget and
        # two-routes sections wrote: the lead's own records, in the order they were written
        shutil.copy(reg / "s1.json", reg / "s9.json")
        p = cls.HOME / ".claude/projects/p"
        cls.write(p / "s9.jsonl", "")
        cls.append(p / "s9.jsonl", human(1), human(2), used(2, "u9", 5000000))
        cls.write(cls.LEAD, "")
        cls.append(
            cls.LEAD,
            human(-3600),
            peer(1),
            human(1),
            *(sent(2, f"t{i}", f"exec-p1-0{i}-a") for i in range(1, 5)),
            sent(2, "t5", "exec-p1-05-a"),
            human(1),
            used(2, "u1", 11000),
            used(2, "u2", 2000),
            human(2),
            human(3),
            endturn(-2),
            human(-1),
            auq(-1, "Which lane runs first, p1-01 or p1-02?"),
            auq(-1, "Wave w5: ≈50M for 9 exec- agents — go ahead?"),
            endturn(0),
            human(3),
        )
        cls.write(p / "s5.jsonl", human(1) + "\n")

    def usage(self, *args, merge=True, **kw):
        return self.py(UR, *args, merge=merge, **kw)

    def test_usage_report(self):
        T, HOME, P = self.T, self.HOME, self.P
        pdir = HOME / ".claude/projects/p"
        r = self.usage("s1", "--project-dir", pdir)
        self.ok(
            "usage_report without --since",
            r.code == 0 and support.grep(r.out, "^lead .*turns=   2"),
            r.out,
        )
        z = ts(-600)
        o = (
            datetime.datetime.fromisoformat(z)
            .astimezone(datetime.timezone(datetime.timedelta(hours=2)))
            .isoformat()
        )

        def lead_line(since):
            out = self.usage(
                "s1", "--project-dir", pdir, "--since", since, merge=False
            ).out
            return "\n".join(ln for ln in out.split("\n") if ln.startswith("lead"))

        a, b = lead_line(z), lead_line(o)
        self.ok(
            f"usage_report --since {o} counts as {z}",
            a == b and support.grep(a, "turns=   2"),
            f"{a} | {b}",
        )
        r = self.usage("s1", "--project-dir", pdir, "--since", "yesterday")
        self.ok(
            "usage_report refuses an unparseable --since",
            r.code == 2 and support.grep(r.out, "argument --since"),
            r.out,
        )
        # --project-dir naming the project itself, as a lead did (live)
        D = T / "proj.x"
        D.mkdir()
        S = HOME / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(D))
        S.mkdir(parents=True)
        shutil.copy(self.LEAD, S)
        r = self.usage("s1", "--project-dir", D)
        self.ok(
            "usage_report --project-dir of the project reads its transcripts",
            r.code == 0 and support.grep(r.out, "^lead .*turns=   2"),
            r.out,
        )
        self.rm(D, S)
        # the units by model, and hook sessions counted only up to the round's last record or
        # --until
        U = HOME / ".claude/projects/u"
        U.mkdir(parents=True)
        self.append(
            U / "u1.jsonl",
            rec(-100, "q1", "claude-opus-5-5", 10000000),
            rec(-90, "q2", "claude-sonnet-5-5", 20000000),
            rec(-50, "q3", "claude-haiku-5-5", 24000000),
        )
        self.append(
            U / "u2.jsonl",
            rec(-60, "k1", "claude-opus-5-5", 4000000, "sdk-ts"),
            rec(100, "k2", "claude-opus-5-5", 10000000, "sdk-ts"),
        )
        out = self.usage("u1", "--project-dir", U).out
        self.ok(
            "usage_report: units by model, hook sessions up to the round's end",
            support.grep(
                out, "^total 1.5M = lead 1.3M + 0 agents 0.0M + 1 hook sessions 0.2M"
            ),
            out,
        )
        out = self.usage("u1", "--project-dir", U, "--until", ts(-55)).out
        self.ok(
            "usage_report --until",
            support.grep(
                out, "^total 1.2M = lead 1.0M + 0 agents 0.0M + 1 hook sessions 0.2M"
            ),
            out,
        )
        # each agent's effort as its requests record it, a change mid-run included
        self.append(U / "u3.jsonl", erec(-30, "e0", "xhigh"))
        sub = U / "u3/subagents"
        sub.mkdir(parents=True)
        self.append(
            sub / "agent-ax.jsonl",
            erec(-20, "e1", "high"),
            erec(-10, "e2", "xhigh"),
            erec(-5, "e3", "high"),
        )
        self.append(sub / "agent-ay.jsonl", erec(-20, "e4", ""))
        out = self.usage("u3", "--project-dir", U).out
        self.ok(
            "usage_report prints each agent's effort",
            support.grep(out, "^lead .* effort xhigh$")
            and support.grep(out, "^agent .*claude-sonnet-5-5 *high/xhigh  *agent-ax$")
            and support.grep(out, "^agent .*claude-sonnet-5-5 *-  *agent-ay$"),
            out,
        )
        # --groups: a task group's context at its first edit, its peak and commits, and how many
        # commits fit under the 200k stop (F60, F75); an integrator is not a task group
        GP = HOME / ".claude/projects/g"
        g1 = GP / "g1/subagents"
        g1.mkdir(parents=True)
        self.append(GP / "g1.jsonl", grec(-700, "l1", 1000))
        commit = tool("t2", "Bash", "git add a && git commit -m x")
        self.append(
            g1 / "agent-e1.jsonl",
            grec(-600, "e1", 30000),
            grec(-500, "e2", 80000, tool("t1", "Edit")),
            grec(-400, "e3", 120000, commit),
            grec(-400, "e3", 120000, commit),  # a streamed copy
            grec(-300, "e4", 160000, tool("t3", "Bash", "git -C /w commit -m y")),
            grec(-240, "e5", 190000, tool("t4", "Bash", "git log")),
        )
        self.write(
            g1 / "agent-e1.meta.json",
            '{"name":"exec-p1-01-a","agentType":"dsp-deep"}\n',
        )
        self.append(
            g1 / "agent-e2.jsonl",
            grec(-200, "w1", 50000, tool("t5", "Write")),
            grec(-100, "w2", 60000, tool("t6", "Bash", "git commit -m m")),
        )
        self.write(
            g1 / "agent-e2.meta.json", '{"name":"exec-wave1","agentType":"dsp-deep"}\n'
        )
        out = self.usage("g1", "--project-dir", GP, "--groups").out
        self.ok(
            "usage_report --groups",
            support.grep(
                out,
                "^group  exec-p1-01-a .*first-edit=  80k  peak= 190k  commits= 2  "
                "per-commit=  55k +6 min",
                E=True,
            )
            and support.grep(
                out,
                "^groups 1: median 6 min, 0.0M; first edit at 80k, +55k context per commit: "
                "about 2 commits fit under 200k",
            )
            and not support.grep(out, "exec-wave1"),
            out,
        )
        # a turn after a gap past the cache's 5 minutes that writes the whole prompt again: a
        # 10-minute wait loop cost 38.0M of one window's agent spend so (F92)
        rewrite = json.loads(grec(-1300, "r2", 0))
        rewrite["message"]["usage"] = {"cache_creation_input_tokens": 100000}
        self.append(
            g1 / "agent-e3.jsonl",
            grec(-1700, "r1", 90000, tool("t7", "Edit")),
            jline(rewrite),
            grec(-1250, "r3", 100000),
        )
        self.write(
            g1 / "agent-e3.meta.json",
            '{"name":"exec-p1-02-a","agentType":"dsp-deep"}\n',
        )
        out = self.usage("g1", "--project-dir", GP, "--groups").out
        self.ok(
            "usage_report counts the cache rewrites after a gap past 5 minutes",
            support.grep(out, "^group  exec-p1-02-a .* rewrites=1$")
            and support.grep(out, "^group  exec-p1-01-a .* rewrites=0$")
            and support.grep(
                out, "^cache +0.1M  1 agent turns wrote the whole prompt", E=True
            ),
            out,
        )
        (g1 / "agent-e3.jsonl").unlink()
        (g1 / "agent-e3.meta.json").unlink()
        # --budget prints that measure where the lead prices the wave (F60, F75)
        m = self.marker()
        m["budgets"] = []
        self.write(T / "gm.json", json.dumps(m))
        reg = HOME / ".claude/dsp-routes/g1.json"
        self.write(
            reg, jline({"marker": str(T / "gm.json"), "planning_dir": str(P)}) + "\n"
        )

        def budget(*args):
            return self.py(RS, "--budget", *args, session="g1", merge=True).out

        out = budget("wg", "--estimate", "5", "--groups", "3", "--tasks", "9")
        self.ok(
            "--budget prints the project's measured group fit and the groups the tasks need",
            support.grep(out, "about 2 commits fit under 200k")
            and support.grep(out, "9 tasks need at least 5 task groups, not 3"),
            out,
        )
        out = budget("wg2", "--estimate", "5", "--groups", "6", "--tasks", "9")
        self.ok(
            "--budget with enough groups only prints the fit",
            support.grep(out, "about 2 commits fit")
            and not support.grep(out, "need at least"),
            out,
        )
        # the fit reads task groups only: a scan of every hook session per transcript took 54 s
        out = self.run_(
            [support.PY, "-c", FIT_READS_NO_SDK, support.SCRIPTS], merge=True
        ).out
        self.ok("--budget's fit never reads the hook sessions", out == "2", out)
        reg.unlink()


class HookSessions(support.Sandbox):
    """A route's other headless lead is a lead, a project named alike is not a worktree, and with
    no session id the running session's own transcript."""

    def test_leads_and_hook_sessions(self):
        T, HOME = self.T, self.HOME
        W = self.init_repo(T / "tab")
        self.git("-C", W, "worktree", "add", "-q", T / "tab-p1-01", "-b", "p1-01")
        self.git("init", "-q", "-b", "main", T / "tab-v2")
        UP = HOME / ".claude/projects"
        for d in ("-t-tab", "-t-tab-p1-01", "-t-tab-v2"):
            (UP / d).mkdir(parents=True)
        self.append(
            UP / "-t-tab/lead.jsonl",
            crec(-100, "a1", 1000000, str(W)),
            crec(-50, "a2", 1000000, str(W)),
        )
        self.append(
            UP / "-t-tab/lead2.jsonl", crec(-80, "b1", 5000000, str(W), "sdk-cli")
        )
        self.write(HOME / ".claude/dsp-routes/lead2.json", "{}\n")
        self.append(
            UP / "-t-tab-p1-01/hook.jsonl",
            crec(-80, "c1", 2000000, str(T / "tab-p1-01"), "sdk-ts"),
        )
        self.append(
            UP / "-t-tab-v2/other.jsonl",
            crec(-80, "d1", 7000000, str(T / "tab-v2"), "sdk-py"),
        )
        self.touch(UP / "-t-tab/lead.jsonl", -60)
        out = self.py(UR, "lead", "--project-dir", UP / "-t-tab", merge=True).out
        self.ok(
            "usage_report: hook sessions are neither a route's lead nor another project",
            support.grep(
                out, "^total 4.0M = lead 2.0M + 0 agents 0.0M + 1 hook sessions 2.0M"
            ),
            out,
        )
        out = self.py(
            UR, "--project-dir", UP / "-t-tab", session="lead", merge=True
        ).out
        self.ok(
            "usage_report without a session id reports the running session",
            support.grep(out, "^session lead "),
            out,
        )
        (HOME / ".claude/dsp-routes/lead2.json").unlink()


if __name__ == "__main__":
    unittest.main()
