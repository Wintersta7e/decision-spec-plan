"""A gate log holds only what the gate printed: `route_state.py --hook` denies a lead's or an
agent's write of one (F97), while a gate's own output, redirected or copied, passes."""

import subprocess
import time
import unittest

import support
from support import RS, ev, jline, used


def leadbash(session, command):
    """A lead's Bash call, the command put into the JSON text as is."""
    return ev(
        "PreToolUse",
        session,
        f'"tool_name":"Bash","tool_input":{{"command":"{command}"}}',
    )


def leadcmd(command):
    """A lead's Bash call, the command JSON-quoted (`jq --arg`)."""
    return jline(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "cwd": "/tmp",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


DENY = "deny:a gate log holds only what the gate printed"


class GateLogWrites(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.GL = f"{cls.P}/lanes/p1-01-gate.log"
        # agent x1, the exec- agent section 1438 left in the lead's subagents: past the context
        # stop, and told of it once already
        sub = cls.HOME / ".claude/projects/p/s1/subagents"
        cls.write(
            sub / "agent-x1.meta.json",
            '{"name":"exec-p1-01-b","agentType":"dsp-deep"}\n',
        )
        cls.write(
            sub / "agent-x1.jsonl",
            jline(
                {
                    "type": "user",
                    "timestamp": support.ts(-60),
                    "message": {
                        "role": "user",
                        "content": f"Rulings file: {cls.P}/lanes/p1-01-rulings.md",
                    },
                }
            )
            + "\n"
            + used(-50, "a1", 150000)
            + "\n"
            + used(-40, "a2", 210000)
            + "\n",
        )
        cls.touch(cls.HOME / ".claude/dsp-routes/s1.x1.stop")

    def sub(self, s):
        return (
            s.replace("{GL}", self.GL)
            .replace("{P}", str(self.P))
            .replace("{T}", str(self.T))
        )

    def inagent(self, agent, command):
        return ev(
            "PreToolUse",
            "s1",
            f'"agent_id":"{agent}","tool_name":"Bash","tool_input":{{"command":"{command}"}},'
            f'"transcript_path":"{self.LEAD}"',
        )

    def gl(self, tool, path):
        return ev(
            "PreToolUse",
            "s1",
            f'"tool_name":"{tool}","tool_input":{{"file_path":"{path}"}}',
        )

    def test_gate_log_writes(self):
        GL, P, T, sub = self.GL, self.P, self.T, self.sub
        # a lead sed -i'd one and wrote `exit=0` into another, and two pushes went out on them
        self.hook(DENY, self.gl("Write", GL))
        self.hook(DENY, self.gl("Edit", GL))
        self.hook("silent", self.gl("Write", f"{P}/lanes/p1-01-rulings.md"))
        for c in (
            "sed -i 's/dirty=1/dirty=0/' {GL}",
            r"echo \"exit=0\" >> {GL}",
            r"printf 'sha=abc dirty=0\\nexit=0\\n' > {GL}",
            r"cat > {GL} <<EOF\nsha=abc dirty=0\nEOF",
            "{ echo sha=abc dirty=0; true; echo exit=0; } > {GL}",
            "perl -pi -e s/1/0/ {GL}",
            r"{ echo \"sha=$(git rev-parse HEAD) dirty=0\"; make test; echo \"exit=$?\"; } > {GL}",
        ):
            self.hook(DENY, leadbash("s1", sub(c)))
        self.hook(DENY, self.inagent("x1", f"sed -i s/1/0/ {GL}"))
        # a log named from the lanes directory, as the live edit was: by the command's `cd` or
        # its cwd
        self.hook(DENY, leadbash("s1", f"cd {P}/lanes && sed -i s/1/0/ p1-01-gate.log"))
        self.hook(
            DENY,
            ev(
                "PreToolUse",
                "s1",
                f'"cwd":"{P}/lanes","tool_name":"Bash","tool_input":'
                '{"command":"echo exit=0 >> p1-01-gate.log"}',
            ),
        )
        self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s1",
                f'"cwd":"{T}","tool_name":"Bash","tool_input":'
                '{"command":"echo exit=0 >> p1-01-gate.log"}',
            ),
        )
        # the same claims through a variable, tee, an interpreter, a printf format or another
        # edit tool
        self.hook(DENY, self.gl("MultiEdit", GL))
        self.hook(DENY, self.gl("NotebookEdit", GL))
        for c in (
            "L={GL}; echo exit=0 > $L",
            "echo exit=0 | tee {GL}",
            r"tee {GL} <<EOF\nexit=0\nEOF",
            r"python3 -c \"open('{GL}','w').write('exit=0')\"",
            r"python3 - <<EOF\nopen('{GL}','a').write('exit=0')\nEOF",
            r"printf 'exit=%d\\n' 0 >> {GL}",
            (
                r"python3 - <<EOF\np='{GL}'\ns=open(p).read().replace('exit=1','exit=0')"
                r"\nopen(p,'w').write(s)\nEOF"
            ),
        ):
            self.hook(DENY, leadbash("s1", sub(c)))
        # code that writes a handoff whose text quotes a gate log and its claims (live, 50 times)
        for c in (
            r"printf 'exit=%s\\n' $? >> {GL}",
            "python3 tools/summarize.py {GL}",
            "make gate 2>&1 | tee {GL}",
            (
                r"python3 - <<EOF\np='HANDOFF.md'\ns=open(p).read()+'gate lanes/p1-01-gate.log "
                r"sha=abc1234 dirty=0 exit=0'\nopen(p,'w').write(s)\nEOF"
            ),
        ):
            self.hook("silent", leadbash("s1", sub(c)))
        # a function the command names `ex` that reads two logs (live)
        self.hook(
            "silent",
            leadbash(
                "s1",
                f"cd {P}/lanes && ex(){{ grep ok $1 | sort; }}; ex a-gate.log > /tmp/b.txt; "
                "ex p1-01-gate.log",
            ),
        )
        # a status the shell computed is the gate's; so is a marker for a step that failed
        # before it
        for c in (
            (
                r"{ echo \"sha=$(git rev-parse HEAD) dirty=$(git status --porcelain | grep -c .)\"; "
                r"make test; echo \"exit=$?\"; } > {GL} 2>&1"
            ),
            "cargo build > /tmp/b.txt; echo release=$? > {GL}",
            r"grep -q '^exit=' {GL} || echo \"exit=PRE-$?\" >> {GL}; rg -q 'exit=0' {GL}",
            r"tools/full-gate.sh /tmp/s > {P}/lanes/deps-1-gate.log 2>&1; echo \"gate exit=$?\"",
            "cp /tmp/gate-final.txt {P}/lanes/p1-01-gate-neutral.log",
            "tail -3 {GL}; rg exit= {GL}; sed -n 1p {GL}",
        ):
            self.hook("silent", leadbash("s1", sub(c)))
        # a claim spelled into another file in the same command, or a perl flag with an `i` in it,
        # writes no log; Python that names the log in the text it writes to the handoff writes
        # none either
        recipe = sub(
            '{ echo "sha=$(git rev-parse HEAD) dirty=$(git status --porcelain '
            '--untracked-files=no | grep -c .)"; make check; echo "exit=$?"; } > {GL} 2>&1'
        )
        for c in (
            recipe
            + sub(
                r"; printf 'Gate: %s (exit=0)\n' {GL} > {P}/lanes/p1-01-checkpoint.md"
            ),
            recipe
            + sub("; tail -1 {GL} | grep -q exit=0 && echo 'gate green (exit=0)'"),
            sub("perl -Mstrict -ne 'print if /exit=/' {GL}"),
            sub(
                "python3 - <<'EOF'\n"
                'log = "{GL}"\n'
                "last = open(log).read().splitlines()[-1]\n"
                'open(".plan/HANDOFF.md", "a").write(f"- gate: {log} ends {last} '
                '(exit=0 expected)\\n")\n'
                "EOF"
            ),
            sub(
                "python3 -c \"import pathlib; h=pathlib.Path('.plan/HANDOFF.md'); "
                "h.write_text(h.read_text() + '- gate: ' + '{GL}' + ' exit=0')\""
            ),
        ):
            self.hook("silent", leadcmd(c))
        # ...while a claim a loop or an `if` prints into the log is still held, and a log a
        # Python write opens through a pathlib receiver
        for c in (
            "for f in a; do echo exit=0; done > {GL}",
            "if true; then echo exit=0; fi >> {GL}",
            "python3 -c \"import pathlib; pathlib.Path('{GL}').open('a').write('exit=0')\"",
        ):
            self.hook(DENY, leadcmd(sub(c)))
        # the hold names the gate runner, which writes every line the push check reads
        self.hook(
            "deny:scripts/gate\\.py <planning-dir> <name> -- ",
            leadcmd(f"sed -i s/1/0/ {GL}"),
        )
        # reads on the hosted repository are no actions: a GET with fields, a graphql query, a
        # list whose label is a verb; a mutation still asks
        for c in (
            "gh api -X GET search/issues -f q='repo:o/r is:pr is:open'",
            "gh api graphql -f query='{ viewer { login } }'",
            "gh issue list --label delete --state open",
        ):
            self.hook("silent", leadcmd(c))
        self.hook(
            "ask:gh api graphql",
            leadcmd(
                'gh api graphql -f query=\'mutation { closeIssue(input:{issueId:"x"}) '
                "{ clientMutationId } }'"
            ),
        )
        # a commit message that mentions a gh action, next to a command the reader cannot follow
        # or a script it runs, runs no gh
        self.write(T / "msg/scripts/check.sh", "#!/bin/bash\nexit 0\n")
        self.chmod_x(T / "msg/scripts/check.sh")
        for c in (
            '$PY -m pytest -q && git commit -qm "docs: gh release create needs a tag"',
            (
                "\"$(git rev-parse --show-toplevel)\"/scripts/test.sh && git commit -qF - <<'EOF'\n"
                "fix(release): stop gh pr merge before checks\nEOF"
            ),
            (
                f'cd {T}/msg && ./scripts/check.sh && git commit -qam "ci: check.sh blocks gh pr '
                'merge on red"'
            ),
        ):
            self.hook("silent", leadcmd(c))
        self.hook("ask:gh pr merge", leadcmd("G=gh; $G pr merge 5"))
        # the value is split into words as bash splits it: a name holding the subcommand, or
        # none at all
        self.hook("ask:gh pr merge", leadcmd("G='gh pr merge'; $G 5"))
        self.hook("ask:gh pr merge", leadcmd("E=; $E gh pr merge 5"))
        for c in (
            "IFS=,; G=gh,pr,merge; $G 5",
            "export IFS=,; G=gh,pr,merge; $G 5",
            "read IFS; G=gh:pr:merge; $G 5",
            "IFS=,; unset IFS; G='gh pr merge'; $G 5",
            "IFS=:; export IFS=,; G=gh,pr,merge; $G 5",
            "IFS=x; G=ghxprxmerge; $G 5",
        ):
            self.hook("ask:gh pr merge", leadcmd(c))
        # ...but a name set more than once, in a loop or from a command's output is read from the
        # whole text, and a computed graphql query may be a mutation
        for c in (
            "X=$(echo gh); $X pr merge 5",
            "if true; then G=gh; else G=echo; fi; $G pr merge 5",
            "for G in gh; do $G pr merge 5; done",
            'gh api graphql -f query="$Q"',
        ):
            self.hook("ask:acts on the hosted repository", leadcmd(c))
        # a write helper's file argument is read whole, nested calls and all; PHP's fopen and an
        # os.open with write flags are opens too
        for c in (
            "node -e \"require('fs').writeFileSync(require('path').resolve('{GL}'), 'exit=0')\"",
            "php -r \"fwrite(fopen('{GL}','w'), 'exit=0');\"",
            "python3 -c \"import os; os.write(os.open('{GL}', os.O_WRONLY), b'exit=0')\"",
        ):
            self.hook(DENY, leadcmd(sub(c)))
        # a line of many calls is read in linear time
        start = int(time.monotonic())
        try:
            out = self.py(
                RS,
                "--hook",
                input=leadcmd('python3 -c "# gate exit=0 ' + "open(" * 20000 + '"')
                + "\n",
                merge=True,
                timeout=20,
            ).out
        except subprocess.TimeoutExpired:
            out = "timed out after 20 s"
        took = int(time.monotonic()) - start
        self.ok(
            f"20,000 calls on one interpreter line are read in {took} s", took < 5, out
        )
        for long in ("gh pr x " * 1000, "git x push y " * 1000):
            start = int(time.monotonic())
            try:
                r = self.py(
                    RS,
                    "--hook",
                    input=leadbash("s1", long) + "\n",
                    merge=True,
                    timeout=20,
                )
                code, out = r.code, r.out
            except subprocess.TimeoutExpired:
                code, out = 124, "timed out after 20 s"
            took = int(time.monotonic()) - start
            self.ok(
                f"a {len(long)}-byte command line is read in {took} s",
                code == 0 and out == "" and took < 2,
                f"{took} s, {out}",
            )
        self.hook(
            "deny:a route agent never runs one", self.inagent("x1", "gh pr close 5")
        )
        self.hook("silent", leadbash("s2", "gh pr close 5"))  # a session with no route


if __name__ == "__main__":
    unittest.main()
