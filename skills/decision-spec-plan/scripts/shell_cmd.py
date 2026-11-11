# SPDX-License-Identifier: MIT
"""A Bash tool call's command text as the simple commands it runs.

For the hooks that read one. Quotes (`$'…'` and `$"…"` too), escapes, comments,
heredocs, line continuations, `$( )`, backticks and `<( )` are read as bash reads them;
`bash -c`, `eval` and the pass-through wrappers (`env`, `timeout`, `nice`, …) are
unwrapped. Not a shell: no globbing, aliases or functions, and a variable expands only
to a literal value. Regexes over the raw text missed `if …; then git push`,
`timeout 60 git push`, `(cd x) &&` and a quoted `-C` path, and matched
`echo "… git push"` and `git log --grep push`.

events(text) returns ("open", None) and ("close", None) around a subshell — `( )`,
`$( )`, `bash -c`, a pipeline's commands, a command run with `&` — ("cmd", Cmd) for each
simple command, in the order bash starts them, and ("opaque", Opaque) for text a shell
runs that the reader cannot see: a script or stdin fed to a shell, `source`, a `bash -c`
or `eval` of a computed string. An Opaque's script is the word naming a script file,
which read_script() reads for the caller to check in turn.
"""

import os
import pathlib
import re
import sys
from collections.abc import Generator, Iterable, Iterator, Mapping
from typing import Literal, NamedTuple, Self

OPS = sorted(
    (
        "&&", "||", ";;", "|&", "&>>", "&>", ">>", ">&", "<&", "<>", ">|",
        "<<<", "<<-", "<<", ";", "&", "|", "(", ")", "<", ">", "\n",
    ),
    key=len,
    reverse=True,
)  # fmt: skip
REDIRECTS = {"<", ">", ">>", ">&", "<&", "<>", ">|", "&>", "&>>", "<<<", "<<", "<<-"}
# Words that open or close a compound command; the command after them is still a
# command.
KEYWORDS = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "do",
    "done",
    "while",
    "until",
    "!",
    "{",
    "}",
    "esac",
    "time",
}
# Words whose command is no command: `for x in a b`, `case $x in`.
NOT_COMMANDS = {"for", "select", "case", "function", "[[", "]]"}
# The keywords that open and close a compound command, which a pipeline runs in one
# subshell.
OPENERS = {"{", "if", "while", "until", "for", "select", "case"}
CLOSERS = {"}", "fi", "done", "esac"}
# Operators that run what they join in subshells: a pipeline, a command run in the
# background.
ASYNC = {"|", "|&", "&"}
# Operators that end one element of a list: what comes after is a command of its own.
LIST_OPS = {";", "&", "&&", "||", "\n"}
# Pass-through wrappers: their options (and the options' values) skipped, the rest is
# the command.
WRAPPERS: dict[str, set[str]] = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "command": set(),
    "exec": {"-a"},
    "nice": {"-n", "--adjustment"},
    "nohup": set(),
    "time": set(),
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "ionice": {"-c", "-n", "-p", "--class", "--classdata"},
    "setsid": set(),
    "builtin": set(),
    "chronic": set(),
    "unbuffer": set(),
    "coproc": set(),
    "taskset": set(),
    "ssh-agent": {"-a", "-E", "-t", "-P", "-O"},
    "strace": {
        "-o",
        "-e",
        "-p",
        "-s",
        "-u",
        "-E",
        "-a",
        "-b",
        "-I",
        "-O",
        "-S",
        "-P",
        "-X",
        "--output",
        "--trace",
        "--attach",
        "--string-limit",
        "--user",
        "--env",
        "--columns",
        "--signal",
        "--status",
        "--trace-path",
        "--trace-fds",
        "--inject",
        "--fault",
        "--summary-sort",
        "--summary-columns",
        "--const-print-style",
    },
}
# Long options of a wrapper that take no value. getopt_long takes any unique prefix of a
# long option; one that is no prefix of a known option makes the rest of the command
# unreadable.
FLAGS_LONG = {
    "env": {"--ignore-environment", "--null", "--debug", "--help", "--version"},
    "timeout": {
        "--preserve-status",
        "--foreground",
        "--verbose",
        "--help",
        "--version",
    },
    "nice": {"--help", "--version"},
    "nohup": {"--help", "--version"},
    "stdbuf": {"--help", "--version"},
    "ionice": {"--ignore", "--pid", "--pgid", "--uid", "--help", "--version"},
    "setsid": {"--ctty", "--fork", "--wait", "--help", "--version"},
    "taskset": {"--all-tasks", "--pid", "--cpu-list", "--help", "--version"},
    "strace": {
        "--follow-forks",
        "--output-separately",
        "--summary-only",
        "--summary",
        "--summary-wall-clock",
        "--no-abbrev",
        "--verbose",
        "--raw",
        "--relative-timestamps",
        "--absolute-timestamps",
        "--syscall-times",
        "--instruction-pointer",
        "--stack-trace",
        "--decode-fds",
        "--decode-pids",
        "--quiet",
        "--debug",
        "--seccomp-bpf",
        "--daemonize",
        "--help",
        "--version",
    },
}
# Wrappers whose first plain words are values, not the command: `timeout 60`,
# `taskset 0x3`.
POSITIONAL = {"timeout": 1, "taskset": 1}
# Options after which a wrapper's rest is a lookup, not a command: `command -v git`.
WRAPPER_STOPS = {"command": {"-v", "-V"}}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
TEMP = "\0temp"  # a `$(mktemp …)` value: a fresh directory, in no repository
# A run of characters with no meaning to the scanner, read at once: one at a time was
# quadratic.
LITERAL = re.compile(r"[^ \t\r\n\\'\"$`;&|()<>]+|.", re.DOTALL)
DQ_LITERAL = re.compile(r'[^"\\$`]+|.', re.DOTALL)
SYNTAX = re.compile(r"[ \t\r\n\\'\"$`;&|()<>]")
ANSI_C = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "e": "\x1b",
    "E": "\x1b",
}

PartKind = Literal["lit", "q", "exp"]


class Word:
    """One shell word.

    Its parts of ("lit", unquoted text), ("q", quoted text) or ("exp", the expansion's
    source text), and the token lists of the command substitutions in it.
    """

    def __init__(self) -> None:
        """Start an empty word."""
        self.parts: list[tuple[PartKind, str]] = []
        self.subs: list[list[Token]] = []

    def add(self, kind: PartKind, s: str) -> None:
        """Append text of a kind, joined to a last part of that kind (not `exp`)."""
        if self.parts and self.parts[-1][0] == kind and kind != "exp":
            self.parts[-1] = (kind, self.parts[-1][1] + s)
        else:
            self.parts.append((kind, s))

    @property
    def text(self) -> str:
        """The word's text with its quotes and escapes read."""
        return "".join(s for _, s in self.parts)

    @property
    def static(self) -> bool:
        """Whether no part of the word is an expansion."""
        return all(k != "exp" for k, _ in self.parts)

    def expand(self, env: Mapping[str, str | None]) -> str | None:
        """Return the word's value, or None when any expansion in it is unknown.

        `$NAME`/`${NAME}` read from env (None: not known), `~` as HOME, a
        `$(mktemp …)` as TEMP; None when any other expansion is in it.
        """
        out: list[str] = []
        for i, (kind, s) in enumerate(self.parts):
            if kind == "exp":
                if re.match(r"(\$\(|`)\s*mktemp\b", s):
                    out.append(TEMP)
                    continue
                m = re.fullmatch(r"\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})", s)
                value = env.get(m[1] or m[2]) if m else None
                if value is None:
                    return None
                out.append(value)
            elif kind == "lit" and i == 0 and (s == "~" or s.startswith("~/")):
                home = env.get("HOME", "~")
                if home is None:  # HOME set to what the reader cannot compute
                    return None
                out.append(home + s[1:])
            else:
                out.append(s)
        return "".join(out)


Token = Word | str
Assign = tuple[str, Word]


def literal(text: str) -> Word:
    """Return a static word whose value is text."""
    w = Word()
    w.add("q", text)
    return w


class Cmd:
    """A simple command: its NAME=value assignments and its words, wrappers removed.

    after is the operator before it (`&&`, `;`, `|`, …), None first in its list; loose,
    whether its words come in no known order (cut from text the reader cannot follow).
    """

    loose: bool = False

    def __init__(
        self, assigns: list[Assign], words: list[Word], after: str | None = None
    ) -> None:
        """Hold a command's assignments, words and the operator before it."""
        self.assigns: list[Assign] = assigns
        self.words: list[Word] = words
        self.after: str | None = after

    @property
    def argv(self) -> list[str]:
        """The text of each word."""
        return [w.text for w in self.words]

    @property
    def name(self) -> str:
        """The base name of the command word, empty when there is none."""
        return self.words[0].text.rpartition("/")[2] if self.words else ""


class Opaque(str):
    """What an ("opaque", …) event runs, as text.

    script is the word naming the script file (`source x`, `bash x`), None for a
    computed string or stdin; sourced, whether it runs in the command's own shell
    (`source`, `.`), so its `cd` and variables hold after it; words, those of a computed
    `eval` or `bash -c` string; assigns, the (name, Word) prefixes it runs with
    (`GIT_DIR=x bash deploy.sh`); held, whether it may push whatever its words say.
    """

    __slots__: tuple[str, ...] = ("__dict__",)
    script: Word | None
    sourced: bool
    words: list[Word]
    assigns: list[Assign]
    held: bool

    def __new__(
        cls,
        what: str,
        script: Word | None = None,
        *,
        sourced: bool = False,
        words: Iterable[Word] = (),
        assigns: Iterable[Assign] = (),
    ) -> Self:
        """Make the text what with its script, words and prefixes; held is False."""
        self = super().__new__(cls, what)
        self.script = script
        self.sourced = sourced
        self.words = list(words)
        self.assigns = list(assigns)
        self.held = False
        return self


Event = (
    tuple[Literal["open", "close"], None]
    | tuple[Literal["cmd"], Cmd]
    | tuple[Literal["opaque"], Opaque]
)

SCRIPT_MAX = 1_000_000
# A `#!` line that runs a shell: `#!/bin/bash`, `#!/usr/bin/env -S bash -e`.
SHELL_SHEBANG = re.compile(r"#!\s*\S*/(?:env\s+(?:-\S*\s+)*)?(?:ba|da|k|z)?sh\b")


def read_script(
    word: Word | None,
    cwd: str | os.PathLike[str] | None,
    *,
    executable: bool = False,
) -> str | None:
    """Return the text of the script file a static word names, or None.

    `~` and a path relative to cwd read as bash reads them; None when it cannot be read
    now: computed, missing, binary or huge, or with executable, not executable. An agent
    moved a command the guard held into a script file it then ran (2026-10-31).
    """
    # A trailing `/` or `/.` names a directory, which no Path keeps.
    if word is None or not word.static or word.text.endswith(("/", "/.")):
        return None
    try:
        path = pathlib.Path(word.text).expanduser()
    except RuntimeError:  # `~user` of no user: the word stays as it is
        path = pathlib.Path(word.text)
    try:
        # pathlib's is_dir/is_file raise PermissionError where os.path's answered False
        if not path.is_absolute():
            if not cwd or not pathlib.Path(cwd).is_dir():
                return None
            path = pathlib.Path(cwd) / path
        if (
            not path.is_file()
            or path.stat().st_size > SCRIPT_MAX
            or (executable and not os.access(path, os.X_OK))
        ):
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return None if b"\0" in data[:4096] else data.decode(errors="replace")


def run_script(word: Word | None, cwd: str | os.PathLike[str] | None) -> str | None:
    """Return the text of the shell script a command runs by its path (`./ship.sh`).

    An executable file with a shell's `#!` line or none, which bash runs as a shell
    script. None for anything else (a binary, a Python script, a name looked up on
    PATH).
    """
    if word is None or "/" not in word.text:
        return None
    text = read_script(word, cwd, executable=True)
    if text is None or (text.startswith("#!") and not SHELL_SHEBANG.match(text)):
        return None
    return text


def _run(pattern: re.Pattern[str], text: str, i: int) -> str:
    """Return the match of pattern at text[i], else the one character there."""
    m = pattern.match(text, i)
    return m[0] if m else text[i]


def _dquote(text: str, i: int, word: Word) -> int:
    """Read a double-quoted string from text[i] (after the quote) into word.

    Returns the index after it.
    """
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            return i + 1
        if c == "\\" and i + 1 < n and text[i + 1] in '$`"\\\n':
            if text[i + 1] != "\n":
                word.add("q", text[i + 1])
            i += 2
        elif c in "$`":
            i = _dollar(text, i, word)
        else:
            run = _run(DQ_LITERAL, text, i)
            word.add("q", run)
            i += len(run)
    return n


def ansi_c(s: str) -> str:
    r"""Return the value of a `$'…'` string's text, as bash reads it.

    `\uHHHH`, `\UHHHHHHHH` and `\cX` too, and an escape it does not know (or `\x`, `\u`,
    `\c` with nothing after) keeps its backslash.
    """

    def one(m: re.Match[str]) -> str:
        e = m[1]
        if e[0] in "xuU" and len(e) > 1:
            code = int(e[1:], 16)
            return chr(code) if code <= sys.maxunicode else ""
        if e[0] in "01234567":
            return chr(int(e, 8))
        if e[0] == "c" and len(e) > 1:
            return chr(ord(e[1]) & 0x1F)
        if e in ANSI_C:
            return ANSI_C[e]
        return e if e in "\\'\"?" else "\\" + e

    return re.sub(
        r"\\(x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}|[0-7]{1,3}|c.|.)",
        one,
        s,
        flags=re.DOTALL,
    )


def _dollar(text: str, i: int, word: Word) -> int:
    """Read the expansion (`$…`, a backtick) at text[i] into word; the index after."""
    n = len(text)
    if text.startswith("$'", i):
        j = i + 2
        while j < n and text[j] != "'":
            j += 2 if text[j] == "\\" else 1
        word.add("q", ansi_c(text[i + 2 : j]))
        return j + 1
    if text.startswith('$"', i):
        return _dquote(text, i + 2, word)
    if text[i] == "`":
        j = i + 1
        while j < n and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        word.subs.append(scan(text[i + 1 : j].replace("\\`", "`"))[0])
        word.add("exp", text[i : j + 1])
        return j + 1
    return _substitution(text, i, word)


def _substitution(text: str, i: int, word: Word) -> int:
    """Read the `$(…)`, `${…}` or `$NAME` at text[i] into word; the index after it."""
    if text.startswith("$(", i):
        tokens, j = scan(text, i + 2, close=True)
        word.subs.append(tokens)
        word.add("exp", text[i:j])
        return j
    if text.startswith("${", i):
        j = text.find("}", i)
        j = len(text) - 1 if j < 0 else j
        word.add("exp", text[i : j + 1])
        return j + 1
    m = re.compile(r"\$(?:[A-Za-z_]\w*|[0-9@#?$!*-])").match(text, i)
    if m:
        word.add("exp", m[0])
        return m.end()
    word.add("lit", "$")
    return i + 1


class _Scanner:
    """The state of one scan(): the tokens read so far and the word being read."""

    def __init__(self, text: str, *, close: bool, cuts: list[int] | None) -> None:
        """Start reading text; close and cuts as scan() takes them."""
        self.text: str = text
        self.n: int = len(text)
        self.close: bool = close
        self.cuts: list[int] | None = cuts
        self.closed: bool = False
        self.tokens: list[Token] = []
        self.word: Word | None = None
        self.depth: int = 0
        self.heredocs: list[tuple[str, bool]] = []
        self.delimiter_next: str | None = None
        # compound commands open (`{`, `if`, `case`, `do`), and whether the next word is
        # a command's first, where such a word is a keyword
        self.groups: int = 0
        self.first: bool = True

    def current(self) -> Word:
        """Return the word being read, started when there is none."""
        if self.word is None:
            self.word = Word()
        return self.word

    def end_word(self) -> None:
        """End the word being read, if any, as a token."""
        word = self.word
        if word is None:
            return
        if self.delimiter_next:
            self.heredocs.append((word.text, self.delimiter_next == "<<-"))
            self.delimiter_next = None
        if self.first and word.static:
            t = word.text
            self.groups += (t in ("{", "if", "case", "do")) - (t in CLOSERS)
            self.first = t in KEYWORDS
        else:
            self.first = False
        self.tokens.append(word)
        self.word = None

    def step(self, i: int) -> int:
        """Read what starts at text[i]; the index after it."""
        text = self.text
        c = text[i]
        if c == "\\" and i + 1 < self.n:
            if text[i + 1] != "\n":
                self.current().add("q", text[i + 1])
            return i + 2
        if c in "'\"$`":
            return self.quoted(i)
        if c == "#" and self.word is None:
            j = text.find("\n", i)
            return self.n if j < 0 else j
        if c in " \t\r":
            self.end_word()
            return i + 1
        if op := next((o for o in OPS if text.startswith(o, i)), None):
            return self.operator(op, i)
        run = _run(LITERAL, text, i)
        self.current().add("lit", run)
        return i + len(run)

    def quoted(self, i: int) -> int:
        """Read the quoted string or expansion at text[i]; the index after it."""
        text, word = self.text, self.current()
        if text[i] == "'":
            j = text.find("'", i + 1)
            j = self.n if j < 0 else j
            word.add("q", text[i + 1 : j])
            return j + 1
        if text[i] == '"':
            return _dquote(text, i + 1, word)
        return _dollar(text, i, word)

    def operator(self, op: str, i: int) -> int:
        """Read the operator op at text[i]; the index after it."""
        if op in ("<", ">") and self.text.startswith("(", i + 1):
            # process substitution `<(cmd)`: a word whose value is a command's output
            word = self.current()
            sub, i = scan(self.text, i + 2, close=True)
            word.subs.append(sub)
            word.add("exp", "<(…)")
            return i
        if (
            self.word is not None
            and op[0] in "<>"
            and re.fullmatch(r"\d+", self.word.text)
        ):
            self.word = None  # the descriptor of `2>&1`, no argument
        self.end_word()
        i += len(op)
        if op == "(":
            self.depth += 1
        elif op == ")":
            if self.close and self.depth == 0:
                self.closed = True
                return i
            self.depth -= 1
        self.tokens.append(op)
        if op not in REDIRECTS:
            self.first = True
        if op in ("<<", "<<-"):
            self.delimiter_next = op
        elif op == "\n":
            i = self.heredoc_bodies(i)
        if self.cuts is not None and op in LIST_OPS and self.depth == self.groups == 0:
            self.cuts.append(i)
        return i

    def heredoc_bodies(self, i: int) -> int:
        """Skip each pending heredoc's body from text[i]; the index after the last.

        A body runs to its delimiter line: text, not commands.
        """
        text, n = self.text, self.n
        for delim, tabs in self.heredocs:
            while i < n:
                j = text.find("\n", i)
                j = n if j < 0 else j
                line = text[i:j]
                i = j + 1
                if (line.lstrip("\t") if tabs else line) == delim:
                    break
        self.heredocs = []
        return i


def scan(
    text: str, i: int = 0, *, close: bool = False, cuts: list[int] | None = None
) -> tuple[list[Token], int]:
    """Return the words and operator strings of text[i:], and the index after them.

    With close, up to the `)` that closes a `$(`. With cuts, a list, the index after
    each list separator outside a subshell and a compound command is appended to it.
    """
    scanner = _Scanner(text, close=close, cuts=cuts)
    while i < scanner.n:
        i = scanner.step(i)
        if scanner.closed:
            return scanner.tokens, i
    scanner.end_word()
    return scanner.tokens, scanner.n


def _split_assign(w: Word) -> Assign | None:
    """Return (name, value word) of a `NAME=value` word, else None."""
    if not w.parts or w.parts[0][0] != "lit":
        return None
    m = ASSIGN.match(w.parts[0][1])
    if not m:
        return None
    value = Word()
    value.subs = w.subs
    rest = w.parts[0][1][m.end() :]
    if rest:
        value.add("lit", rest)
    for kind, s in w.parts[1:]:
        value.add(kind, s)
    return m[0][:-1], value


def _tail(w: Word, n: int) -> Word | None:
    """Return the word w with its first n characters cut: the value of `-o/x`, `--o=x`.

    None when they do not all lie in its first, unexpanded part.
    """
    kind, first = w.parts[0]
    if kind == "exp" or len(first) < n:
        return None
    value = Word()
    value.subs = w.subs
    if first[n:]:
        value.add(kind, first[n:])
    for part_kind, s in w.parts[1:]:
        value.add(part_kind, s)
    return value


def _option(
    t: str, valued: set[str], flags: Iterable[str] = ()
) -> tuple[str | None, int | None]:
    """Return (option, cut) of an option word as getopt reads it.

    The valued option it sets, and how many characters precede the value it carries
    (None: the value is the next word); (None, None) for flags only; ("?", None) for a
    long option that is no unique prefix of a known one. `-fo x` sets -o; `-o/x`,
    `--output=x` and `--out=x` carry their value.
    """
    if t.startswith("--"):
        name, eq, _ = t.partition("=")
        known = valued | set(flags)
        hits = [name] if name in known else [o for o in known if o.startswith(name)]
        if len(hits) != 1:
            return "?", None
        if hits[0] not in valued:
            return None, None
        return hits[0], len(name) + 1 if eq else None
    for k in range(1, len(t)):
        if f"-{t[k]}" in valued:
            return f"-{t[k]}", (k + 1 if k + 1 < len(t) else None)
    return None, None


def _prefixed(assigns: list[Assign], found: Iterable[Event]) -> Iterator[Event]:
    """Return the events found, each command and opaque text run with assigns first."""
    for event in found:
        c = event[1]
        if c is not None and assigns:
            c.assigns = assigns + c.assigns
        yield event


class _Stop(NamedTuple):
    """The option that ends a wrapper's options: "?" (unknown), env's -S or -C."""

    opt: str
    value: Word | None
    after: list[Word]
    cut: int | None


def _one_option(name: str, rest: list[Word]) -> tuple[list[Word], _Stop | None]:
    """Read the option word rest[0] of wrapper name.

    Returns the words after it and its value, and the option when it ends the
    wrapper's options.
    """
    opt, cut = _option(rest[0].text, WRAPPERS[name], FLAGS_LONG.get(name, ()))
    if opt is None:
        return rest[1:], None
    if opt == "?":
        return rest, _Stop(opt, None, [], None)
    if cut is None:
        value, after = (rest[1:2] or [None])[0], rest[2:]
    else:
        value, after = _tail(rest[0], cut), rest[1:]
    if name == "env" and opt not in ("-u", "--unset"):
        return after, _Stop(opt, value, after, cut)
    return after, None


def _skip_options(
    name: str, rest: list[Word], assigns: list[Assign]
) -> tuple[list[Word], _Stop | None]:
    """Read the options of wrapper name, and their values, from rest.

    Returns the words after them and the option that ends them, if any. env's
    `NAME=value` words are appended to assigns.
    """
    positional, stops = POSITIONAL.get(name, 0), WRAPPER_STOPS.get(name, ())
    while rest:
        t = rest[0].text
        if t in stops:
            break
        if t == "--":
            return rest[1:], None
        if t.startswith("-") and t != "-":
            rest, stop = _one_option(name, rest)
            if stop is not None:
                return rest, stop
            continue
        if name == "env" and (a := _split_assign(rest[0])):
            assigns.append(a)
            rest = rest[1:]
        elif positional:
            positional -= 1
            rest = rest[1:]
        else:
            break
    return rest, None


def _split_string(
    value: Word | None, after: list[Word], assigns: list[Assign]
) -> Iterator[Event]:
    """Return the events of `env -S '<cmd line>'`.

    It splits a string, reading escapes and `${VAR}` in it that a shell does not.
    """
    line = [w for w in [value, *after] if w is not None]
    text = " ".join(w.text for w in line)
    static = value is not None and all(w.static for w in line)
    if static and not re.search(r"[\\$]", text):
        yield from _prefixed(assigns, _parse(scan(text)[0]))
        return
    what = "`env -S` of a string it rewrites"
    # every escape read as a separator (`\_`, `\t`; `\c` ends it), so `git\_push` names
    # push; a `${VAR}` it fills in is held outright
    seen = [*line, literal(re.sub(r"\\.", " ", text))]
    opaque = Opaque(what, words=seen, assigns=assigns)
    opaque.held = "$" in text
    yield "opaque", opaque


def _stopped(
    name: str, rest: list[Word], stop: _Stop, assigns: list[Assign]
) -> Iterator[Event]:
    """Return the events of wrapper name whose options end at stop."""
    if stop.opt == "?":
        # it may take the next word as its value or not: the command is unknown
        what = f"`{name}` with an option {rest[0].text} the reader does not know"
        yield "opaque", Opaque(what, words=rest, assigns=assigns)
    elif stop.opt in ("-S", "--split-string"):
        yield from _split_string(stop.value, stop.after, assigns)
    else:
        # `env -C <dir> cmd` runs cmd there
        yield "open", None
        if stop.value is None and stop.cut is not None:
            yield "opaque", Opaque("`env -C` of a computed directory")
        elif stop.value is not None:
            yield "cmd", Cmd([], [literal("cd"), stop.value])
        yield from _prefixed(assigns, _command(stop.after))
        yield "close", None


def _wrapped(
    name: str, words: list[Word], assigns: list[Assign]
) -> Generator[Event, None, list[Word] | None]:
    """Yield the events of wrapper name that ends the command.

    Returns the words it runs as the command, None when it ends the command.
    """
    rest, stop = _skip_options(name, words[1:], assigns)
    if stop is not None:
        yield from _stopped(name, rest, stop, assigns)
        return None
    if rest and rest[0].text in WRAPPER_STOPS.get(name, ()):
        yield "cmd", Cmd(assigns, words)
        return None
    if name == "coproc":
        # `coproc NAME { …; }`: a NAME before a compound command names the coprocess
        if len(rest) > 1 and rest[1].static and rest[1].text in KEYWORDS:
            rest = rest[1:]
        yield from _prefixed(assigns, _command(rest))
        return None
    return rest


def _shell(name: str, words: list[Word], assigns: list[Assign]) -> Iterator[Event]:
    """Return the events of a shell run on a `-c` string, a script or stdin."""
    i = 1
    shell_c = False
    while i < len(words) and words[i].text[:1] in "-+" and words[i].text != "--":
        t = words[i].text
        shell_c |= not t.startswith("--") and "c" in t
        i += 2 if t in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file") else 1
    if shell_c and i < len(words) and words[i].static:
        yield "open", None
        yield from _prefixed(assigns, _parse(scan(words[i].text)[0]))
        yield "close", None
    elif shell_c or i >= len(words) or words[i].text in ("-", "--"):
        what = f"`{name}` running a computed string or stdin"
        yield "opaque", Opaque(what, words=words[i:], assigns=assigns)
    else:
        what = f"`{name}` running a script"
        yield "opaque", Opaque(what, words[i], assigns=assigns)


def _eval(words: list[Word], assigns: list[Assign]) -> Iterator[Event]:
    """Return the events of an `eval` of its words."""
    if all(w.static for w in words[1:]):
        text = " ".join(w.text for w in words[1:])
        yield from _prefixed(assigns, _parse(scan(text)[0]))
    else:
        what = "`eval` of a computed string"
        yield "opaque", Opaque(what, words=words[1:], assigns=assigns)


def _skip_keywords(words: list[Word]) -> list[Word]:
    """Return words after the keywords before the command.

    `function f { …` runs its body here; `time -p`.
    """
    while words and words[0].static and words[0].text in KEYWORDS | {"function"}:
        t = words[0].text
        words = words[2:] if t == "function" else words[1:]
        while t == "time" and words and words[0].text in ("-p", "--"):
            words = words[1:]
    return words


def _command(words: list[Word]) -> Iterator[Event]:
    """Return the events of the words of one simple command."""
    words = _skip_keywords(words)
    if not words or (words[0].static and words[0].text in NOT_COMMANDS):
        return
    assigns: list[Assign] = []
    while words and (a := _split_assign(words[0])):
        assigns.append(a)
        words = words[1:]
    while words:
        name = words[0].text.rpartition("/")[2]
        if name in WRAPPERS:
            rest = yield from _wrapped(name, words, assigns)
            if rest is None:
                return
            words = rest
            continue
        if name in SHELLS:
            yield from _shell(name, words, assigns)
            return
        if name == "eval":
            yield from _eval(words, assigns)
            return
        if name in ("source", "."):
            script = words[1] if len(words) > 1 else None
            what = f"`{name}` of a script"
            yield "opaque", Opaque(what, script, sourced=True, assigns=assigns)
            return
        break
    yield "cmd", Cmd(assigns, words)


def _nesting(words: list[Word]) -> int:
    """Return how far the compound-command keywords words open with change the nesting.

    `function f { …` and `coproc NAME { …`: the `{` after the name opens the body.
    """
    head = words[0].text if words and words[0].static else ""
    skip = 0
    if head == "function":
        skip = 2
    elif head == "coproc":
        named = any(w.static and w.text in KEYWORDS for w in words[2:3])
        skip = 2 if named else 1
    nest = 0
    for w in words[skip:]:
        if not (w.static and w.text in KEYWORDS | NOT_COMMANDS):
            break
        nest += (w.text in OPENERS) - (w.text in CLOSERS)
    return nest


def _command_events(words: list[Word], last: str | None) -> list[Event]:
    """Return the events of a simple command's words, after the operator last."""
    out: list[Event] = []
    for event in _command(words):
        c = event[1]
        if isinstance(c, Cmd) and c.after is None:
            # the "cmd" events; a `bash -c` or `eval` body keeps its own operators
            # after its first command
            c.after = last
        out.append(event)
    return out


def _element(element: list[Event], before: str | None, op: str | None) -> list[Event]:
    """Return a list element's events, in a subshell when a pipe or `&` joins it."""
    if before in ASYNC or op in ASYNC:
        return [("open", None), *element, ("close", None)]
    return element


def _parse(tokens: list[Token]) -> list[Event]:
    """Return the events of a token list.

    Each command of a pipeline, and a list run with `&`, runs in a subshell of its own,
    so a `cd` in it leaves the next command where it was.
    """
    out: list[Event] = []
    element: list[Event] = []
    words: list[Word] = []
    redirect, nest = False, 0
    before: str | None = None
    last: str | None = None
    for t in tokens:
        if isinstance(t, str):
            if t in REDIRECTS:
                redirect = True
                continue
            nest += _nesting(words)
            element += _command_events(words, last)
            words = []
            if t in ("(", ")"):
                nest += 1 if t == "(" else -1
                element.append(("open", None) if t == "(" else ("close", None))
                continue
            if nest <= 0:
                out += _element(element, before, t)
                element, before = [], t
            last = t
            continue
        for sub in t.subs:
            element.append(("open", None))
            element += _parse(sub)
            element.append(("close", None))
        if redirect:
            redirect = False
        else:
            words.append(t)
    element += _command_events(words, last)
    out += _element(element, before, None)
    return out


def events(text: str) -> list[Event]:
    """Return the events of the command text.

    ("open" | "close", None) around each subshell, ("cmd", Cmd) for each simple command
    and ("opaque", what) for text run that cannot be read.
    """
    return _parse(scan(text)[0])


def words(text: str) -> list[Word]:
    """Return every word of text with its quotes and escapes read.

    Redirect targets and the words of each `$( )` included: what a check for a name in
    the text should search. A static word that still holds shell syntax (a `bash -c` or
    `eval` string) is read again, as deep as it nests: reading a word only drops quotes
    and escapes, so each level is shorter until one reads as itself.
    """
    out: list[Word] = []

    def collect(tokens: list[Token], text: str) -> None:
        for t in tokens:
            if not isinstance(t, str):
                out.append(t)
                for sub in t.subs:
                    collect(sub, text)
                if t.static and t.text != text and SYNTAX.search(t.text):
                    collect(scan(t.text)[0], t.text)

    collect(scan(text)[0], text)
    return out


def elements(text: str) -> list[str]:
    """Return the text of each element of text's top-level lists.

    A heredoc's body with its command: a subshell, a `{ }` group, `if … fi`,
    `case … esac` and `do … done` stay whole, with the redirects on them.
    """
    cuts: list[int] = []
    _ = scan(text, cuts=cuts)
    out: list[str] = []
    start = 0
    for end in [*cuts, len(text)]:
        out.append(text[start:end])
        start = end
    return [part for part in out if part.strip()]


OUTPUTS = {">", ">>", ">|", "&>", "&>>"}


def redirects(text: str) -> list[tuple[Word, list[Word]]]:
    """Return (target word, the words of the command before it) of each output redirect.

    `$( )` and `bash -c` strings included as words() reads them; the words are only `}`
    after a group and none after a `)`.
    """
    out: list[tuple[Word, list[Word]]] = []

    def collect(tokens: list[Token], text: str) -> None:
        before: list[Word] = []
        op: str | None = None
        for t in tokens:
            if isinstance(t, str):
                if t in REDIRECTS:
                    op = t
                else:
                    before = []
                continue
            if op:
                if op in OUTPUTS:
                    out.append((t, list(before)))
                op = None
            else:
                before.append(t)
            for sub in t.subs:
                collect(sub, text)
            if t.static and t.text != text and SYNTAX.search(t.text):
                collect(scan(t.text)[0], t.text)

    collect(scan(text)[0], text)
    return out


GitOptions = list[tuple[str, Word | None]]


def git_args(cmd: Cmd) -> tuple[GitOptions, str | None, list[Word]] | None:
    """Return (git's own options, subcommand, its argument words) when cmd runs git.

    The options as [(option, value or None)]; the subcommand is None when its word is
    not static. None when cmd does not run git.
    """
    if cmd.name != "git":
        return None
    words, i = cmd.words, 1
    opts: GitOptions = []
    valued = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}
    valued.add("--config-env")
    while i < len(words) and words[i].text.startswith("-"):
        t = words[i].text
        if t in valued and i + 1 < len(words):
            opts.append((t, words[i + 1]))
            i += 2
        else:
            opts.append((t, None))
            i += 1
    if i >= len(words):
        return opts, "", []
    return opts, words[i].text if words[i].static else None, words[i + 1 :]
