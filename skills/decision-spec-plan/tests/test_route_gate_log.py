# SPDX-License-Identifier: MIT
"""A gate log holds only what the gate printed.

`route_state.py --hook` denies a lead's or an agent's write of one (F97), while a gate's
own output, redirected or copied, passes.
"""

import subprocess
import time
import unittest

from typing_extensions import override

import support
from support import RS, ev, jline, used

CALLS_SECONDS = 5  # the most a line of 20,000 interpreter calls may take to read
LINE_SECONDS = 2  # the most a long command line may take to read


def leadbash(session: str, command: str) -> str:
    """A lead's Bash call, the command put into the JSON text as is."""
    return ev(
        "PreToolUse",
        session,
        f'"tool_name":"Bash","tool_input":{{"command":"{command}"}}',
    )


def leadcmd(command: str) -> str:
    """A lead's Bash call, the command JSON-quoted (`jq --arg`)."""
    return ev(
        "PreToolUse",
        "s1",
        f'"tool_name":"Bash","tool_input":{jline({"command": command})}',
    )


DENY = "deny:a gate log holds only what the gate printed"


class GateLogWrites(support.Route):
    """Writes of lane p1-01's gate log GL, by the lead and by agent x1."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Name GL and leave agent x1 past its context stop, told of it once."""
        super().setUpClass()
        cls.GL: str = f"{cls.P}/lanes/p1-01-gate.log"
        # agent x1, the exec- agent section 1438 left in the lead's subagents: past the
        # context stop, and told of it once already
        sub = cls.HOME / ".claude/projects/p/s1/subagents"
        _ = cls.write(
            sub / "agent-x1.meta.json",
            '{"name":"exec-p1-01-b","agentType":"dsp-deep"}\n',
        )
        _ = cls.write(
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

    def sub(self, s: str) -> str:
        """S with {GL}, {P} and {T} filled in."""
        return (
            s.replace("{GL}", self.GL)
            .replace("{P}", str(self.P))
            .replace("{T}", str(self.T))
        )

    def inagent(self, agent: str, command: str) -> str:
        """A Bash call of command by agent in the lead's session."""
        return ev(
            "PreToolUse",
            "s1",
            f'"agent_id":"{agent}","tool_name":"Bash",'
            f'"tool_input":{{"command":"{command}"}},'
            f'"transcript_path":"{self.LEAD}"',
        )

    def gl(self, tool: str, path: str) -> str:
        """A lead's call of an edit tool on path."""
        return ev(
            "PreToolUse",
            "s1",
            f'"tool_name":"{tool}","tool_input":{{"file_path":"{path}"}}',
        )

    def test_gate_log_writes(self) -> None:
        """Writes of a gate log are held; its gate's output and reads pass."""
        self._direct_writes()
        self._quotes_and_computed_status()
        self._hosted_repository()
        self._linear_time()

    def _direct_writes(self) -> None:
        """A write by an edit tool, a redirect, a variable, tee or an interpreter."""
        gl, p, t, sub = self.GL, self.P, self.T, self.sub
        # a lead sed -i'd one and wrote `exit=0` into another, and two pushes went out
        # on them
        _ = self.hook(DENY, self.gl("Write", gl))
        _ = self.hook(DENY, self.gl("Edit", gl))
        _ = self.hook("silent", self.gl("Write", f"{p}/lanes/p1-01-rulings.md"))
        for c in (
            "sed -i 's/dirty=1/dirty=0/' {GL}",
            r"echo \"exit=0\" >> {GL}",
            r"printf 'sha=abc dirty=0\\nexit=0\\n' > {GL}",
            r"cat > {GL} <<EOF\nsha=abc dirty=0\nEOF",
            "{ echo sha=abc dirty=0; true; echo exit=0; } > {GL}",
            "perl -pi -e s/1/0/ {GL}",
            (
                r"{ echo \"sha=$(git rev-parse HEAD) dirty=0\"; make test; "
                r"echo \"exit=$?\"; } > {GL}"
            ),
        ):
            _ = self.hook(DENY, leadbash("s1", sub(c)))
        _ = self.hook(DENY, self.inagent("x1", f"sed -i s/1/0/ {gl}"))
        # a log named from the lanes directory, as the live edit was: by the command's
        # `cd` or its cwd
        _ = self.hook(
            DENY, leadbash("s1", f"cd {p}/lanes && sed -i s/1/0/ p1-01-gate.log")
        )
        _ = self.hook(
            DENY,
            ev(
                "PreToolUse",
                "s1",
                f'"cwd":"{p}/lanes","tool_name":"Bash","tool_input":'
                '{"command":"echo exit=0 >> p1-01-gate.log"}',
            ),
        )
        _ = self.hook(
            "silent",
            ev(
                "PreToolUse",
                "s1",
                f'"cwd":"{t}","tool_name":"Bash","tool_input":'
                '{"command":"echo exit=0 >> p1-01-gate.log"}',
            ),
        )
        # the same claims through a variable, tee, an interpreter, a printf format or
        # another edit tool
        _ = self.hook(DENY, self.gl("MultiEdit", gl))
        _ = self.hook(DENY, self.gl("NotebookEdit", gl))
        for c in (
            "L={GL}; echo exit=0 > $L",
            "echo exit=0 | tee {GL}",
            r"tee {GL} <<EOF\nexit=0\nEOF",
            r"python3 -c \"open('{GL}','w').write('exit=0')\"",
            r"python3 - <<EOF\nopen('{GL}','a').write('exit=0')\nEOF",
            r"printf 'exit=%d\\n' 0 >> {GL}",
            (
                r"python3 - <<EOF\np='{GL}'\n"
                r"s=open(p).read().replace('exit=1','exit=0')"
                r"\nopen(p,'w').write(s)\nEOF"
            ),
        ):
            _ = self.hook(DENY, leadbash("s1", sub(c)))

    def _quotes_and_computed_status(self) -> None:
        """Text quoting a log, a status the shell computed, and claims still held."""
        p, sub = self.P, self.sub
        # code that writes a handoff whose text quotes a gate log and its claims (live,
        # 50 times)
        for c in (
            r"printf 'exit=%s\\n' $? >> {GL}",
            "python3 tools/summarize.py {GL}",
            "make gate 2>&1 | tee {GL}",
            (
                r"python3 - <<EOF\np='HANDOFF.md'\n"
                r"s=open(p).read()+'gate lanes/p1-01-gate.log "
                r"sha=abc1234 dirty=0 exit=0'\nopen(p,'w').write(s)\nEOF"
            ),
        ):
            _ = self.hook("silent", leadbash("s1", sub(c)))
        # a function the command names `ex` that reads two logs (live)
        _ = self.hook(
            "silent",
            leadbash(
                "s1",
                f"cd {p}/lanes && ex(){{ grep ok $1 | sort; }}; "
                "ex a-gate.log > /tmp/b.txt; "
                "ex p1-01-gate.log",
            ),
        )
        # a status the shell computed is the gate's; so is a marker for a step that
        # failed before it
        for c in (
            (
                r"{ echo \"sha=$(git rev-parse HEAD) "
                r"dirty=$(git status --porcelain | grep -c .)\"; "
                r"make test; echo \"exit=$?\"; } > {GL} 2>&1"
            ),
            "cargo build > /tmp/b.txt; echo release=$? > {GL}",
            (
                r"grep -q '^exit=' {GL} || echo \"exit=PRE-$?\" >> {GL}; "
                r"rg -q 'exit=0' {GL}"
            ),
            (
                r"tools/full-gate.sh /tmp/s > {P}/lanes/deps-1-gate.log 2>&1; "
                r"echo \"gate exit=$?\""
            ),
            "cp /tmp/gate-final.txt {P}/lanes/p1-01-gate-neutral.log",
            "tail -3 {GL}; rg exit= {GL}; sed -n 1p {GL}",
        ):
            _ = self.hook("silent", leadbash("s1", sub(c)))
        # a claim spelled into another file in the same command, or a perl flag with an
        # `i` in it, writes no log; Python that names the log in the text it writes to
        # the handoff writes none either
        recipe = sub(
            '{ echo "sha=$(git rev-parse HEAD) dirty=$(git status --porcelain '
            '--untracked-files=no | grep -c .)"; make check; echo "exit=$?"; } '
            "> {GL} 2>&1"
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
            _ = self.hook("silent", leadcmd(c))
        # ...while a claim a loop or an `if` prints into the log is still held, and a
        # log a Python write opens through a pathlib receiver
        for c in (
            "for f in a; do echo exit=0; done > {GL}",
            "if true; then echo exit=0; fi >> {GL}",
            (
                'python3 -c "import pathlib; '
                "pathlib.Path('{GL}').open('a').write('exit=0')\""
            ),
        ):
            _ = self.hook(DENY, leadcmd(sub(c)))

    def _hosted_repository(self) -> None:
        """The gate runner named, reads and messages on the hosted repository."""
        gl, t, sub = self.GL, self.T, self.sub
        # the hold names the gate runner, which writes every line the push check reads
        _ = self.hook(
            "deny:scripts/gate\\.py <planning-dir> <name> -- ",
            leadcmd(f"sed -i s/1/0/ {gl}"),
        )
        # reads on the hosted repository are no actions: a GET with fields, a graphql
        # query, a list whose label is a verb; a mutation still asks
        for c in (
            "gh api -X GET search/issues -f q='repo:o/r is:pr is:open'",
            "gh api graphql -f query='{ viewer { login } }'",
            "gh issue list --label delete --state open",
        ):
            _ = self.hook("silent", leadcmd(c))
        _ = self.hook(
            "ask:gh api graphql",
            leadcmd(
                'gh api graphql -f query=\'mutation { closeIssue(input:{issueId:"x"}) '
                "{ clientMutationId } }'"
            ),
        )
        # a commit message that mentions a gh action, next to a command the reader
        # cannot follow or a script it runs, runs no gh
        _ = self.write(t / "msg/scripts/check.sh", "#!/bin/bash\nexit 0\n")
        self.chmod_x(t / "msg/scripts/check.sh")
        for c in (
            '$PY -m pytest -q && git commit -qm "docs: gh release create needs a tag"',
            (
                '"$(git rev-parse --show-toplevel)"/scripts/test.sh '
                "&& git commit -qF - <<'EOF'\n"
                "fix(release): stop gh pr merge before checks\nEOF"
            ),
            (
                f"cd {t}/msg && ./scripts/check.sh "
                '&& git commit -qam "ci: check.sh blocks gh pr '
                'merge on red"'
            ),
        ):
            _ = self.hook("silent", leadcmd(c))
        _ = self.hook("ask:gh pr merge", leadcmd("G=gh; $G pr merge 5"))
        # the value is split into words as bash splits it: a name holding the
        # subcommand, or none at all
        _ = self.hook("ask:gh pr merge", leadcmd("G='gh pr merge'; $G 5"))
        _ = self.hook("ask:gh pr merge", leadcmd("E=; $E gh pr merge 5"))
        for c in (
            "IFS=,; G=gh,pr,merge; $G 5",
            "export IFS=,; G=gh,pr,merge; $G 5",
            "read IFS; G=gh:pr:merge; $G 5",
            "IFS=,; unset IFS; G='gh pr merge'; $G 5",
            "IFS=:; export IFS=,; G=gh,pr,merge; $G 5",
            "IFS=x; G=ghxprxmerge; $G 5",
        ):
            _ = self.hook("ask:gh pr merge", leadcmd(c))
        # ...but a name set more than once, in a loop or from a command's output is read
        # from the whole text, and a computed graphql query may be a mutation
        for c in (
            "X=$(echo gh); $X pr merge 5",
            "if true; then G=gh; else G=echo; fi; $G pr merge 5",
            "for G in gh; do $G pr merge 5; done",
            'gh api graphql -f query="$Q"',
        ):
            _ = self.hook("ask:acts on the hosted repository", leadcmd(c))
        # a write helper's file argument is read whole, nested calls and all; PHP's
        # fopen and an os.open with write flags are opens too
        for c in (
            (
                "node -e \"require('fs').writeFileSync("
                "require('path').resolve('{GL}'), 'exit=0')\""
            ),
            "php -r \"fwrite(fopen('{GL}','w'), 'exit=0');\"",
            (
                'python3 -c "import os; '
                "os.write(os.open('{GL}', os.O_WRONLY), b'exit=0')\""
            ),
        ):
            _ = self.hook(DENY, leadcmd(sub(c)))

    def _linear_time(self) -> None:
        """Long lines are read in linear time; an agent never acts on the host."""
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
            f"20,000 calls on one interpreter line are read in {took} s",
            took < CALLS_SECONDS,
            out,
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
                code == 0 and out == "" and took < LINE_SECONDS,
                f"{took} s, {out}",
            )
        _ = self.hook(
            "deny:a route agent never runs one", self.inagent("x1", "gh pr close 5")
        )
        _ = self.hook(
            "silent", leadbash("s2", "gh pr close 5")
        )  # a session with no route


class GateLogSpellings(support.Route):
    """A gate log named through `//` or `/./` is the same file and is held alike."""

    def lead(self, tool_input: dict[str, str]) -> str:
        """Return a lead's PreToolUse event for the tool input, as a JSON line.

        Args:
            tool_input: The `tool_input` object; a `command` makes it a Bash call, else
                a Write call.

        Returns:
            The event as `jq -nc` writes it.
        """
        return jline(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s1",
                "cwd": str(self.T),
                "tool_name": "Bash" if "command" in tool_input else "Write",
                "tool_input": tool_input,
            }
        )

    def test_spellings(self) -> None:
        """A doubled slash, a `./` segment or a `cd` to `lanes//` names the log."""
        lanes = f"{self.P}/lanes"
        for command in (
            f"echo exit=0 > {lanes}//p1-01-gate.log",
            "echo exit=0 > lanes//p1-01-gate.log",
            f"echo exit=0 > {lanes}/.//p1-01-gate.log",
            f"cd {lanes}// && echo exit=0 > p1-01-gate.log",
            f"cd {lanes}/ && echo exit=0 > p1-01-gate.log",
            f"echo exit=0 > {lanes}/./p1-01-gate.log",
            f"sed -i s/1/0/ {lanes}//p1-01-gate.log",
            f"echo done; echo exit=0 | tee {lanes}//p1-01-gate.log",
        ):
            _ = self.hook(DENY, self.lead({"command": command}))
        _ = self.hook(DENY, self.lead({"file_path": f"{lanes}//p1-01-gate.log"}))
        _ = self.hook("silent", self.lead({"file_path": f"{lanes}//p1-01-rulings.md"}))


if __name__ == "__main__":
    _ = unittest.main()
