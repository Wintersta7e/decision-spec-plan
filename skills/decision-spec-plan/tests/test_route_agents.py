"""The hook inside a route's agents: an exec- agent's context stop (F75) and its commit held for an
unread ruling (F59), and an agent sent back to wait on its own background job (F92)."""

import json
import os
import unittest

import support
from support import call, ev, human, jline, notice, ts, used


class Route(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the lead transcript the budget section began, the hooks' transcript_path
        cls.write(cls.LEAD, human(-3600) + "\n")
        cls.SUB = cls.HOME / ".claude/projects/p/s1/subagents"
        cls.SUB.mkdir(parents=True)


class ExecAgent(Route):
    def inagent(self, agent, command):
        return ev(
            "PreToolUse",
            "s1",
            f'"agent_id":"{agent}","tool_name":"Bash","tool_input":{{"command":"{command}"}},'
            f'"transcript_path":"{self.LEAD}"',
        )

    def test_context_stop_and_rulings_hold(self):
        T, P, SUB = self.T, self.P, self.SUB
        rulings = P / "lanes/p1-01-rulings.md"
        self.write(
            SUB / "agent-x1.meta.json",
            '{"name":"exec-p1-01-b","agentType":"dsp-deep"}\n',
        )
        self.write(
            SUB / "agent-y1.meta.json",
            '{"name":"pride-p1-push1","agentType":"dsp-deep"}\n',
        )
        first = {
            "type": "user",
            "timestamp": ts(-60),
            "message": {"role": "user", "content": f"Rulings file: {rulings}"},
        }
        self.write(SUB / "agent-x1.jsonl", jline(first) + "\n")
        self.append(SUB / "agent-x1.jsonl", used(-50, "a1", 150000))
        (SUB / "agent-y1.jsonl").write_bytes((SUB / "agent-x1.jsonl").read_bytes())
        self.hook("silent", self.inagent("x1", "ls"))
        self.append(SUB / "agent-x1.jsonl", used(-40, "a2", 210000))
        self.append(SUB / "agent-y1.jsonl", used(-40, "a2", 210000))
        self.hook(
            "/your context is 210k tokens. Finish the task/", self.inagent("x1", "ls")
        )
        self.hook("silent", self.inagent("x1", "ls"))  # told once
        self.hook("silent", self.inagent("y1", "ls"))  # not an exec- agent
        self.hook(
            "silent", self.inagent("x1", "git commit -m x")
        )  # no rulings file yet
        self.write(rulings, "R1 use the old API\n")
        self.hook(
            r"deny:re-read .*p1-01-rulings.md \(.*\) before you commit",
            self.inagent("x1", "git -C /w commit -m x"),
        )
        # the text says which: a file the agent never read is not one changed "after your last
        # read" (live); a fast-forward makes no commit of the agent's
        self.hook(
            r"deny:p1-01-rulings.md \(you have not read it\) before you commit",
            self.inagent("x1", "git commit -m x"),
        )
        self.hook("silent", self.inagent("x1", "git merge --ff-only exec-p1-01-a"))
        self.hook("silent", self.inagent("x1", "git status"))
        self.hook("silent", self.inagent("y1", "git commit -m x"))
        read = {
            "type": "assistant",
            "timestamp": ts(30),
            "message": {
                "id": "r1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "r1",
                        "name": "Read",
                        "input": {"file_path": str(rulings)},
                    }
                ],
            },
        }
        self.append(SUB / "agent-x1.jsonl", jline(read))
        self.hook("silent", self.inagent("x1", "git commit -m x"))
        # the transcript repeats a tool_use in an untimestamped api-request-blob record; the
        # read still counts
        blob = {
            "type": "api-request-blob",
            "agentId": "x1",
            "hash": "h1",
            "sessionId": "s1",
            "message": read["message"],
        }
        self.append(SUB / "agent-x1.jsonl", jline(blob))
        self.hook("silent", self.inagent("x1", "git commit -m x"))
        self.touch(rulings, 120)
        self.hook(
            r"deny:re-read .*p1-01-rulings.md \(the lead changed it after your last read\)",
            self.inagent("x1", "git commit -m x"),
        )
        # every form that makes a commit, read as bash reads it: a regex missed each of these
        held = "deny:re-read .*p1-01-rulings.md"
        self.hook(held, self.inagent("x1", "git -C '/a b/wt' commit -m x"))
        self.hook(held, self.inagent("x1", "git --no-pager commit -m x"))
        self.hook(held, self.inagent("x1", "git merge --no-ff lane"))
        self.hook(held, self.inagent("x1", "git cherry-pick abc123"))
        self.hook("silent", self.inagent("x1", "git log --grep 'commit'"))
        self.hook(held, self.inagent("x1", "sudo git commit -m x"))
        self.hook(held, self.inagent("x1", "git $'commit' -m x"))
        self.hook(held, self.inagent("x1", "X='git commit -m x'; bash -c $X"))
        self.hook(held, self.inagent("x1", r"bash <<EOF\ngit commit -m x\nEOF"))
        self.hook(held, self.inagent("x1", "git merge --ff-only --no-ff lane"))
        self.hook("silent", self.inagent("x1", "git merge --no-ff --ff-only lane"))
        # a script it runs is read where the command's `cd` left it, by path too, and as it will
        # be written
        scripts = T / "scripts"
        self.write(scripts / "commit.sh", "git commit -m x\n")
        self.chmod_x(scripts / "commit.sh")
        self.hook(held, self.inagent("x1", f"cd {scripts} && bash commit.sh"))
        self.hook(held, self.inagent("x1", f"{scripts}/commit.sh"))
        self.write(scripts / "w.sh", "ls\n")
        self.hook(
            held,
            self.inagent(
                "x1", f"printf 'git commit -m x' >{scripts}/w.sh; bash {scripts}/w.sh"
            ),
        )
        # only the agent's own lane file holds its commit: a `lanes/` listing once named every
        # lane's (F59)
        cat = {
            "type": "assistant",
            "timestamp": ts(200),
            "message": {
                "id": "r2",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "r2",
                        "name": "Bash",
                        "input": {"command": f"cat {rulings}"},
                    }
                ],
            },
        }
        self.append(SUB / "agent-x1.jsonl", jline(cat))
        self.write(P / "lanes/p1-02-rulings.md", "R1 another lane's ruling\n")
        self.touch(P / "lanes/p1-02-rulings.md", 300)
        listing = "\n".join(sorted(os.listdir(P / "lanes")))
        result = {
            "type": "user",
            "timestamp": ts(210),
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "l1", "content": listing}
                ],
            },
        }
        self.append(SUB / "agent-x1.jsonl", jline(result))
        self.hook("silent", self.inagent("x1", "git commit -m x"))
        # the lane's archive of applied rulings never holds a commit
        self.write(P / "lanes/p1-01-rulings-archive.md", "R0 applied\n")
        self.touch(P / "lanes/p1-01-rulings-archive.md", 300)
        self.hook("silent", self.inagent("x1", "git commit -m x"))
        # a lane file named by plan id, never in the transcript: the dispatch points at a brief
        self.write(
            SUB / "agent-z1.meta.json",
            '{"name":"exec-p1-03-c","agentType":"dsp-deep"}\n',
        )
        brief = {
            "type": "user",
            "timestamp": ts(-60),
            "message": {
                "role": "user",
                "content": "Read your brief first: /w/dispatch-p1-03-c.md",
            },
        }
        self.write(SUB / "agent-z1.jsonl", jline(brief) + "\n")
        self.write(P / "lanes/p1-03-wide-rulings.md", "R1 wide\n")
        self.hook(
            "deny:re-read .*p1-03-wide-rulings.md",
            self.inagent("z1", "git commit -m x"),
        )


class WaitsOnItsJob(Route):
    """An agent that ends its turn while its own background job runs is sent back to wait on it:
    nothing wakes a teammate when the job ends (F92)."""

    def test_stop_hook(self):
        T, SUB, LEAD = self.T, self.SUB, self.LEAD
        TASKS = T / "tasks"
        TASKS.mkdir()
        tm = SUB / "agent-aexec-p1-02-a-0123456789abcdef.jsonl"
        self.write(tm, "")
        self.append(
            tm,
            *call(
                "t1",
                "Bash",
                {"command": "npm test", "run_in_background": True},
                f"Command running in background with ID: bsh1. Output is being written to: "
                f"{TASKS}/bsh1.output. You will be notified when it completes.",
            ),
            *call("t2", "Bash", {"command": "ls"}, "a b"),
        )
        idle = ev(
            "TeammateIdle",
            "s1",
            '"teammate_name":"exec-p1-02-a","agent_id":"aexec-p1-02-a-0123456789abcdef",'
            f'"transcript_path":"{LEAD}"',
        )
        self.write(TASKS / "bsh1.output", "running\n")
        self.stophook(2, "npm test.*bsh1.output.*F92", idle)
        self.write(TASKS / "bsh1.output", "running\n\n[exited with code 0]\n")
        self.stophook(0, "^$", idle)
        self.write(TASKS / "bsh1.output", "\n[killed]\n")
        self.stophook(0, "^$", idle)
        self.append(
            tm,
            *call(
                "t3",
                "Monitor",
                {
                    "command": "until grep -q ^exit= g.log; do sleep 20; done",
                    "description": "gate",
                },
                "Monitor started (task bmo1, expires in 30m unless the source ends first).",
            ),
        )
        self.write(TASKS / "bmo1.output", "x\n")
        self.stophook(2, r"until grep -q \^exit= g.log.*F92", idle)
        (TASKS / "bmo1.output").unlink()
        self.append(tm, notice("bmo1", "completed"))
        self.stophook(0, "^$", idle)  # its notification ended it
        self.stophook(
            0,
            "^$",
            ev(
                "TeammateIdle",
                "s1",
                f'"teammate_name":"nobody","agent_id":"anobody-00000000","transcript_path":"{LEAD}"',
            ),
        )
        # a foreground command past its timeout moves to the background without
        # run_in_background
        self.append(
            tm,
            *call(
                "t4",
                "Bash",
                {"command": "npx eslint . > lint.log"},
                "partial output\nCommand did not complete within its 300s timeout and was moved "
                f"to the background (ID: bauto1). Output is being written to: {TASKS}/bauto1."
                "output. You will be notified when it completes.",
            ),
        )
        self.write(TASKS / "bauto1.output", "x\n")
        self.stophook(2, "npx eslint.*bauto1.output.*F92", idle)
        (TASKS / "bauto1.output").unlink()
        # SubagentStop lists every background job of the session, a neighbour teammate's too:
        # only the jobs the stopping agent's own transcript started count, and an agent with no
        # transcript has none.
        tb = SUB / "agent-aexec-p1-02-b-0123456789abcdef.jsonl"
        self.write(tb, "")
        self.append(
            tb,
            *call(
                "u1",
                "Bash",
                {"command": "npm test > gate.log", "run_in_background": True},
                f"Command running in background with ID: bsb1. Output is being written to: "
                f"{TASKS}/bsb1.output. You will be notified when it completes.",
            ),
            *call(
                "u2",
                "Monitor",
                {"command": "tail -f x", "description": "watch"},
                "Monitor started (task bsb2, expires in 30m unless the source ends first).",
            ),
        )

        def bg(task, kind, status):
            return (
                f'"background_tasks":[{{"id":"{task}","type":"{kind}","status":"{status}",'
                '"command":"npm test > gate.log"}]'
            )

        def sub(extra, session="s1"):
            return ev(
                "SubagentStop",
                session,
                '"agent_id":"aexec-p1-02-b-0123456789abcdef","agent_type":"dsp-deep",'
                f'"transcript_path":"{LEAD}",{extra}',
            )

        self.stophook(
            2,
            "npm test > gate.log.*bsb1.output.*F92",
            sub(bg("bsb1", "shell", "running")),
        )
        self.stophook(0, "^$", sub(bg("bsb1", "shell", "completed")))
        self.stophook(0, "^$", sub(bg("bsb1", "subagent", "running")))
        self.stophook(2, "tail -f x.*F92", sub(bg("bsb2", "monitor", "running")))
        self.stophook(
            0, "^$", sub(bg("bother", "shell", "running"))
        )  # a neighbour's job
        self.stophook(
            0,
            "^$",
            ev(
                "SubagentStop",
                "s1",
                f'"agent_id":"a0123456789abcdef",{bg("bsb1", "shell", "running")}',
            ),
        )  # no transcript
        self.stophook(0, "^$", sub(bg("bsb1", "shell", "running"), "s77"))  # no route
        active = f'"stop_hook_active":true,{bg("bsb1", "shell", "running")}'
        self.stophook(2, "F92", sub(active))
        # sent back twice: a hung job is the agent's to report
        self.stophook(0, "^$", sub(active))
        json.loads(sub(active))  # the event stays valid JSON


if __name__ == "__main__":
    unittest.main()
