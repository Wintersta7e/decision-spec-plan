"""A gate log written by hand rather than by the gate runner, refused to the lead and its agents
alike (F97)."""

import os
import re

import shell_cmd

GATE_LOG = re.compile(r"(?:^|/)lanes/(?:[^/\s]+/)*[^/\s]*gate[^/\s]*\.log$")
# What push_guard.py reads from a gate log, spelled out rather than computed by the shell.
CLAIM = re.compile(r"\b(?:exit=\d+|dirty=\d+|sha=[0-9a-f]{7,40})\b")
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
INTERPRETERS = re.compile(r"python[\d.]*|node|perl|ruby|php|deno|bun")
# a file write in interpreter code: open() (in a write mode: Python, Perl), a write method, a
# write helper
WRITE_CALL = re.compile(
    r"\b(?:f|sys)?open\(|\bopenSync\(|\.write_(?:text|bytes)\("
    r"|(?:(?:write|append)File(?:Sync)?|createWriteStream|File\.write|file_put_contents)\("
)
# an open mode that writes: a quoted one (Python, Perl, PHP, Node) or an O_* flag (os.open, sysopen)
WRITE_MODE = re.compile(
    r"['\"](?:[wax]|r\+|>>?|\+<)[+bt]*['\"]|\bO_(?:WRONLY|RDWR|APPEND|CREAT|TRUNC)\b"
)
LOG_LITERAL = re.compile(r"['\"]([^'\"\s]*gate[^'\"\s]*\.log)['\"]")


def call_args(line):
    """{index of each `(`: (end of its first argument, its closing `)`)} in line, quotes skipped
    and brackets balanced, in one pass (a scan per call was quadratic on a long line); an unclosed
    one runs to the end of the line."""
    out, stack, quote, j = {}, [], None, 0
    while j < len(line):
        ch = line[j]
        if ch == "\\":
            j += 1
        elif quote:
            quote = None if ch == quote else quote
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            stack.append([j, ch, None])
        elif ch in ")]}" and stack:
            start, kind, comma = stack.pop()
            if kind == "(":
                out[start] = (j if comma is None else comma), j
        elif ch == "," and stack and stack[-1][2] is None:
            stack[-1][2] = j
        j += 1
    for start, kind, comma in stack:
        if kind == "(":
            out[start] = (len(line) if comma is None else comma), len(line)
    return out


def code_writes_log(code, is_log):
    """Interpreter code with a write call naming a gate log as the file it writes, by its literal
    path or by a name a line bound to one (`p='lanes/x-gate.log'` … `open(p,'w')`): the line up
    to the call's file — open()'s arguments, the receiver of `.write_text(`, a helper's first
    argument, nested calls in them read whole (`path.join(d, 'x-gate.log')`). A log quoted in the
    text being written is not one: leads edit handoffs that cite gate logs (live)."""
    names, lines = set(), code.splitlines()
    for line in lines:
        bound = re.match(r"\s*(?:my\s+|const\s+|let\s+|var\s+)?\$?(\w+)\s*=(?!=)", line)
        if bound and any(is_log(m[1]) for m in LOG_LITERAL.finditer(line)):
            names.add(bound[1])
    for line in lines:
        # where the line first names a log: a head holds one when it reaches that far
        marks = [m.end() for m in LOG_LITERAL.finditer(line) if is_log(m[1])]
        for n in names:
            if m := re.search(rf"(?<!\w){re.escape(n)}(?!\w)", line):
                marks.append(m.end())
        if not marks:
            continue
        mark, args = min(marks), call_args(line)
        for call in WRITE_CALL.finditer(line):
            # a call inside what the scan took for a quote: the whole line
            first, end = args.get(call.end() - 1, (len(line), len(line)))
            if call[0].startswith("."):
                head = call.start()
            elif call[0].endswith(("open(", "openSync(")):
                if not WRITE_MODE.search(line, call.end(), end):
                    continue
                head = end
            else:
                head = first
            if mark <= head:
                return True
    return False


def printf_text(args):
    """What `printf <format> <args>` prints, as far as static text can say: each `%…` takes the
    next argument (`printf 'exit=%d' 0` prints `exit=0`)."""
    rest = iter(args[1:])
    return re.sub(r"%[-+ #0-9.]*[a-zA-Z]", lambda m: next(rest, m[0]), args[0])


def gate_log_edit(event):
    """How the tool call writes a gate log by hand, if it does (F97): an edit tool on one,
    `sed -i`/`perl -i` on one, an interpreter whose code names one and a claim, or a command
    that writes into one (a redirect, `tee`) while `echo`, `printf` or a heredoc spells out a
    line the push check reads (`exit=0`, `dirty=0`, `sha=<hex>`). A gate's own output
    redirected, piped or copied in is what a log holds, and so is a status the shell computed
    (`echo release=$?`, `echo "exit=PRE-$?"` after a failed step). An editor by name is not
    read: a lead's own function `ex` read two logs (live)."""
    tool, given = event.get("tool_name"), event.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        path = str(given.get("file_path") or given.get("notebook_path") or "")
        return f"{tool} on {path}" if GATE_LOG.search(path) else None
    command = str(given.get("command") or "") if tool == "Bash" else ""
    if "gate" not in command:
        return None
    cmds = [c for k, c in shell_cmd.events(command) if k == "cmd"]
    found = [c for c in cmds if c.words]
    # the command's own `NAME=value` assignments, so `> $LOG` reads as the path it names
    env = {}
    for c in cmds:
        if not c.words:
            env |= {n: x for n, v in c.assigns if (x := v.expand(env)) is not None}

    def text(w):
        return w.expand(env) or w.text

    # a relative name read from the cwd or from any directory the command `cd`s to: the live
    # edit named `x-gate.log` from inside lanes/
    dirs = [str(event.get("cwd") or "")]
    dirs += [text(c.words[1]) for c in found if c.name == "cd" and c.words[1:]]

    def is_log(t):
        return any(GATE_LOG.search(os.path.join(d, t)) for d in dirs)

    for c in found:
        args = [text(w) for w in c.words[1:]]
        # the code is in the command: a `-c` argument or a heredoc body
        m = INTERPRETERS.fullmatch(c.name) and CLAIM.search(command)
        if m and code_writes_log(command, is_log):
            return f"`{c.name}` code writing a gate log, `{m[0]}` in it"
        # `-i` alone or grouped (`-pi`), not inside a switch that takes the rest of its word
        # (`perl -Mstrict`)
        inplace = (
            r"-[a-zA-Z]*i\S*"
            if c.name == "sed"
            else r"-[a-cf-ln-wyzABGHJ-LN-UW-Z0-9]*i\S*"
        )
        if (
            c.name in ("sed", "perl")
            and any(is_log(a) for a in args)
            and any(re.fullmatch(rf"{inplace}|--in-place\S*", a) for a in args)
        ):
            return f"`{c.name}` editing it in place"
    # what a list element prints counts only when that element writes into a log: a checkpoint
    # line or a status echo after the gate run is no claim in it
    for part in shell_cmd.elements(command):
        into = [t for t, _ in shell_cmd.redirects(part) if is_log(text(t))]
        spelled = []
        for c in (c for k, c in shell_cmd.events(part) if k == "cmd" and c.words):
            args = [text(w) for w in c.words[1:]]
            if c.name in ("echo", "printf") and args:
                spelled += [shell_cmd._ansi_c(a) for a in args]
                if c.name == "printf":
                    spelled.append(shell_cmd._ansi_c(printf_text(args)))
            if c.name == "tee":
                into += [a for a in args if is_log(a)]
        if not into:
            continue
        if "<<" in part:
            spelled.append(part)  # a heredoc's text is in the command, not in a word
        if m := CLAIM.search(" ".join(spelled)):
            return f"`{m[0]}` spelled out into it"
    return None
