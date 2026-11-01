"""A Bash tool call's command text as the simple commands it runs, for the hooks that read one.

Quotes (`$'…'` and `$"…"` too), escapes, comments, heredocs, line continuations, `$( )`, backticks
and `<( )` are read as bash reads them; `bash -c`, `eval` and the pass-through wrappers (`env`,
`timeout`, `nice`, …) are unwrapped. Not a shell: no globbing, aliases or functions, and a variable
expands only to a literal value. Regexes over the raw text missed `if …; then git push`,
`timeout 60 git push`, `(cd x) &&` and a quoted `-C` path, and matched `echo "… git push"` and
`git log --grep push`.

events(text) returns ("open", None) and ("close", None) around a subshell — `( )`, `$( )`, `bash -c`,
a pipeline's commands, a command run with `&` — ("cmd", Cmd) for each simple command, in the order
bash starts them, and ("opaque", Opaque) for text a shell runs that the reader cannot see: a script or
stdin fed to a shell, `source`, a `bash -c` or `eval` of a computed string. An Opaque's script is
the word naming a script file, which read_script() reads for the caller to check in turn.
"""

import os
import re

OPS = sorted(
    (
        "&&", "||", ";;", "|&", "&>>", "&>", ">>", ">&", "<&", "<>", ">|", "<<<", "<<-", "<<",
        ";", "&", "|", "(", ")", "<", ">", "\n",
    ),
    key=len,
    reverse=True,
)  # fmt: skip
REDIRECTS = {"<", ">", ">>", ">&", "<&", "<>", ">|", "&>", "&>>", "<<<", "<<", "<<-"}
# Words that open or close a compound command; the command after them is still a command.
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
}
KEYWORDS |= {"esac", "time"}
# Words whose command is no command: `for x in a b`, `case $x in`.
NOT_COMMANDS = {"for", "select", "case", "function", "[[", "]]"}
# The keywords that open and close a compound command, which a pipeline runs in one subshell.
OPENERS = {"{", "if", "while", "until", "for", "select", "case"}
CLOSERS = {"}", "fi", "done", "esac"}
# Operators that run what they join in subshells: a pipeline, a command run in the background.
ASYNC = {"|", "|&", "&"}
# Operators that end one element of a list: what comes after is a command of its own.
LIST_OPS = {";", "&", "&&", "||", "\n"}
# Pass-through wrappers: their options (and the options' values) skipped, the rest is the command.
WRAPPERS = {
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
# Long options of a wrapper that take no value. getopt_long takes any unique prefix of a long
# option; one that is no prefix of a known option makes the rest of the command unreadable.
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
# Wrappers whose first plain words are values, not the command: `timeout 60`, `taskset 0x3`.
POSITIONAL = {"timeout": 1, "taskset": 1}
# Options after which a wrapper's rest is a lookup, not a command: `command -v git`.
WRAPPER_STOPS = {"command": {"-v", "-V"}}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
TEMP = "\0temp"  # a `$(mktemp …)` value: a fresh directory, in no repository
# A run of characters with no meaning to the scanner, read at once: one at a time was quadratic.
LITERAL = re.compile(r"[^ \t\r\n\\'\"$`;&|()<>]+|.", re.DOTALL)
DQ_LITERAL = re.compile(r'[^"\\$`]+|.', re.DOTALL)
SYNTAX = re.compile(r"[ \t\r\n\\'\"$`;&|()<>]")
ANSI_C = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
ANSI_C |= {"e": "\x1b", "E": "\x1b"}


class Word:
    """One shell word: parts of ("lit", unquoted text), ("q", quoted text) or ("exp", the
    expansion's source text), and the token lists of the command substitutions in it."""

    def __init__(self):
        self.parts = []
        self.subs = []

    def add(self, kind, s):
        if self.parts and self.parts[-1][0] == kind and kind != "exp":
            self.parts[-1] = (kind, self.parts[-1][1] + s)
        else:
            self.parts.append((kind, s))

    @property
    def text(self):
        return "".join(s for _, s in self.parts)

    @property
    def static(self):
        return all(k != "exp" for k, _ in self.parts)

    def expand(self, env):
        """The word's value with `$NAME`/`${NAME}` from env (None: not known), `~` as HOME, a
        `$(mktemp …)` as TEMP; None when any other expansion is in it."""
        out = []
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
                out.append(env.get("HOME", "~") + s[1:])
            else:
                out.append(s)
        return "".join(out)


def literal(text):
    """A static word whose value is text."""
    w = Word()
    w.add("q", text)
    return w


class Cmd:
    """A simple command: its NAME=value assignments and its words, wrappers removed; after is the
    operator before it (`&&`, `;`, `|`, …), None first in its list; loose, whether its words come
    in no known order (cut from text the reader cannot follow)."""

    loose = False

    def __init__(self, assigns, words, after=None):
        self.assigns = assigns
        self.words = words
        self.after = after

    @property
    def argv(self):
        return [w.text for w in self.words]

    @property
    def name(self):
        return os.path.basename(self.words[0].text) if self.words else ""


class Opaque(str):
    """What an ("opaque", …) event runs, as text; script is the word naming the script file
    (`source x`, `bash x`), None for a computed string or stdin; sourced, whether it runs in the
    command's own shell (`source`, `.`), so its `cd` and variables hold after it; words, those of
    a computed `eval` or `bash -c` string; assigns, the (name, Word) prefixes it runs with
    (`GIT_DIR=x bash deploy.sh`); held, whether it may push whatever its words say."""

    script: Word | None
    sourced: bool
    words: list
    assigns: list
    held: bool

    def __new__(
        cls, what, script=None, sourced=False, words=(), assigns=(), held=False
    ):
        self = super().__new__(cls, what)
        self.script = script
        self.sourced = sourced
        self.words = list(words)
        self.assigns = list(assigns)
        self.held = held
        return self


SCRIPT_MAX = 1_000_000
# A `#!` line that runs a shell: `#!/bin/bash`, `#!/usr/bin/env -S bash -e`.
SHELL_SHEBANG = re.compile(r"#!\s*\S*/(?:env\s+(?:-\S*\s+)*)?(?:ba|da|k|z)?sh\b")


def read_script(word, cwd, executable=False):
    """The text of the script file a static word names (`~` and a path relative to cwd read as
    bash reads them), or None when it cannot be read now: computed, missing, binary or huge, or
    with executable, not executable. An agent moved a command the guard held into a script file
    it then ran (2026-10-31)."""
    if word is None or not word.static:
        return None
    path = os.path.expanduser(word.text)
    if not os.path.isabs(path):
        if not cwd or not os.path.isdir(cwd):
            return None
        path = os.path.join(cwd, path)
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > SCRIPT_MAX:
            return None
        if executable and not os.access(path, os.X_OK):
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return None if b"\0" in data[:4096] else data.decode(errors="replace")


def run_script(word, cwd):
    """The text of the shell script a command runs by its path (`./ship.sh`): an executable file
    with a shell's `#!` line or none, which bash runs as a shell script. None for anything else
    (a binary, a Python script, a name looked up on PATH)."""
    if word is None or "/" not in word.text:
        return None
    text = read_script(word, cwd, executable=True)
    if text is None or (text.startswith("#!") and not SHELL_SHEBANG.match(text)):
        return None
    return text


def _dquote(text, i, word):
    """Read a double-quoted string from text[i] (after the quote) into word; the index after it."""
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
            m = DQ_LITERAL.match(text, i)
            assert m  # `|.` matches any character, and i < n
            word.add("q", m[0])
            i = m.end()
    return n


def _ansi_c(s):
    """The value of a `$'…'` string's text."""

    def one(m: re.Match[str]) -> str:
        e = m[1]
        if e[0] == "x":
            return chr(int(e[1:], 16))
        if e[0] in "01234567":
            return chr(int(e, 8))
        return ANSI_C.get(e, e)

    return re.sub(r"\\(x[0-9a-fA-F]{1,2}|[0-7]{1,3}|.)", one, s, flags=re.DOTALL)


def _dollar(text, i, word):
    """Read the expansion at text[i] (`$…` or a backtick) into word; the index after it."""
    n = len(text)
    if text.startswith("$'", i):
        j = i + 2
        while j < n and text[j] != "'":
            j += 2 if text[j] == "\\" else 1
        word.add("q", _ansi_c(text[i + 2 : j]))
        return j + 1
    if text.startswith('$"', i):
        return _dquote(text, i + 2, word)
    if text[i] == "`":
        j = i + 1
        while j < n and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        word.subs.append(_scan(text[i + 1 : j].replace("\\`", "`"))[0])
        word.add("exp", text[i : j + 1])
        return j + 1
    if text.startswith("$(", i):
        tokens, j = _scan(text, i + 2, close=True)
        word.subs.append(tokens)
        word.add("exp", text[i:j])
        return j
    if text.startswith("${", i):
        j = text.find("}", i)
        j = n - 1 if j < 0 else j
        word.add("exp", text[i : j + 1])
        return j + 1
    m = re.compile(r"\$(?:[A-Za-z_]\w*|[0-9@#?$!*-])").match(text, i)
    if m:
        word.add("exp", m[0])
        return m.end()
    word.add("lit", "$")
    return i + 1


def _scan(text, i=0, close=False, cuts=None):
    """Words and operator strings of text[i:]; with close, up to the `)` that closes a `$(`.
    Returns (tokens, the index after the last character read). With cuts, a list, the index
    after each list separator outside a subshell and a compound command is appended to it."""
    tokens, word, depth, n = [], None, 0, len(text)
    heredocs, delimiter_next = [], None
    # compound commands open (`{`, `if`, `case`, `do`), and whether the next word is a command's
    # first, where such a word is a keyword
    groups, first = 0, True

    def end_word():
        nonlocal word, delimiter_next, groups, first
        if word is not None:
            if delimiter_next:
                heredocs.append((word.text, delimiter_next == "<<-"))
                delimiter_next = None
            if first and word.static:
                t = word.text
                groups += (t in ("{", "if", "case", "do")) - (t in CLOSERS)
                first = t in KEYWORDS
            else:
                first = False
            tokens.append(word)
            word = None

    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            if text[i + 1] != "\n":
                word = word or Word()
                word.add("q", text[i + 1])
            i += 2
        elif c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            word = word or Word()
            word.add("q", text[i + 1 : j])
            i = j + 1
        elif c == '"':
            word = word or Word()
            i = _dquote(text, i + 1, word)
        elif c in "$`":
            word = word or Word()
            i = _dollar(text, i, word)
        elif c == "#" and word is None:
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c in " \t\r":
            end_word()
            i += 1
        elif op := next((o for o in OPS if text.startswith(o, i)), None):
            if op in ("<", ">") and text.startswith("(", i + 1):
                # process substitution `<(cmd)`: a word whose value is a command's output
                word = word or Word()
                sub, i = _scan(text, i + 2, close=True)
                word.subs.append(sub)
                word.add("exp", "<(…)")
                continue
            if word is not None and op[0] in "<>" and re.fullmatch(r"\d+", word.text):
                word = None  # the descriptor of `2>&1`, no argument
            end_word()
            i += len(op)
            if op == "(":
                depth += 1
            elif op == ")":
                if close and depth == 0:
                    return tokens, i
                depth -= 1
            tokens.append(op)
            if op not in REDIRECTS:
                first = True
            if op in ("<<", "<<-"):
                delimiter_next = op
            elif op == "\n":
                # each pending heredoc's body runs to its delimiter line: text, not commands
                for delim, tabs in heredocs:
                    while i < n:
                        j = text.find("\n", i)
                        j = n if j < 0 else j
                        line = text[i:j]
                        i = j + 1
                        if (line.lstrip("\t") if tabs else line) == delim:
                            break
                heredocs = []
            if cuts is not None and op in LIST_OPS and depth == groups == 0:
                cuts.append(i)
        else:
            m = LITERAL.match(text, i)
            assert m  # `|.` matches any character, and i < n
            word = word or Word()
            word.add("lit", m[0])
            i = m.end()
    end_word()
    return tokens, n


def _split_assign(w):
    """(name, value word) of a `NAME=value` word, else None."""
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


def _tail(w, n):
    """The word w with its first n characters cut: the value of `-o/x` or `--opt=x`. None when
    they do not all lie in its first, unexpanded part."""
    kind, first = w.parts[0]
    if kind == "exp" or len(first) < n:
        return None
    value = Word()
    value.subs = w.subs
    if first[n:]:
        value.add(kind, first[n:])
    for kind, s in w.parts[1:]:
        value.add(kind, s)
    return value


def _option(t, valued, flags=()):
    """(option, cut) of an option word as getopt reads it: the valued option it sets, and how
    many characters precede the value it carries (None: the value is the next word); (None, None)
    for flags only; ("?", None) for a long option that is no unique prefix of a known one. `-fo x`
    sets -o; `-o/x`, `--output=x` and `--out=x` carry their value."""
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


def _prefixed(assigns, found):
    """The events found, each command and opaque text run with the prefixes assigns."""
    for kind, c in found:
        if kind in ("cmd", "opaque") and assigns:
            c.assigns = assigns + c.assigns
        yield kind, c


def _command(words):
    # keywords before the command; `function f { …` runs its body here; `time -p`
    while words and words[0].static and words[0].text in KEYWORDS | {"function"}:
        t = words[0].text
        words = words[2:] if t == "function" else words[1:]
        while t == "time" and words and words[0].text in ("-p", "--"):
            words = words[1:]
    if not words or (words[0].static and words[0].text in NOT_COMMANDS):
        return
    assigns = []
    while words and (a := _split_assign(words[0])):
        assigns.append(a)
        words = words[1:]
    while words:
        name = os.path.basename(words[0].text)
        if name in WRAPPERS:
            rest, valued = words[1:], WRAPPERS[name]
            positional, stops = POSITIONAL.get(name, 0), WRAPPER_STOPS.get(name, ())
            while rest:
                t = rest[0].text
                if t in stops:
                    break
                if t == "--":
                    rest = rest[1:]
                    break
                if t.startswith("-") and t != "-":
                    opt, cut = _option(t, valued, FLAGS_LONG.get(name, ()))
                    if opt == "?":
                        # it may take the next word as its value or not: the command is unknown
                        what = f"`{name}` with an option {t} the reader does not know"
                        yield "opaque", Opaque(what, words=rest, assigns=assigns)
                        return
                    if cut is None:
                        value, after = (rest[1:2] or [None])[0], rest[2:]
                    else:
                        value, after = _tail(rest[0], cut), rest[1:]
                    if opt is None:
                        rest = rest[1:]
                        continue
                    rest = after
                    if name != "env" or opt in ("-u", "--unset"):
                        continue
                    # `env -C <dir> cmd` runs cmd there; `env -S '<cmd line>'` splits a string,
                    # reading escapes and `${VAR}` in it that a shell does not
                    if opt in ("-S", "--split-string"):
                        line = [w for w in [value, *after] if w is not None]
                        text = " ".join(w.text for w in line)
                        static = value is not None and all(w.static for w in line)
                        if static and not re.search(r"[\\$]", text):
                            yield from _prefixed(assigns, _parse(_scan(text)[0]))
                            return
                        what = "`env -S` of a string it rewrites"
                        # every escape read as a separator (`\_`, `\t`; `\c` ends it), so
                        # `git\_push` names push; a `${VAR}` it fills in is held outright
                        seen = [*line, literal(re.sub(r"\\.", " ", text))]
                        yield (
                            "opaque",
                            Opaque(what, words=seen, assigns=assigns, held="$" in text),
                        )
                        return
                    yield "open", None
                    if value is None and cut is not None:
                        yield "opaque", Opaque("`env -C` of a computed directory")
                    elif value is not None:
                        yield "cmd", Cmd([], [literal("cd"), value])
                    yield from _prefixed(assigns, _command(after))
                    yield "close", None
                    return
                if name == "env" and (a := _split_assign(rest[0])):
                    assigns.append(a)
                    rest = rest[1:]
                elif positional:
                    positional -= 1
                    rest = rest[1:]
                else:
                    break
            if rest and rest[0].text in stops:
                break
            if name == "coproc":
                # `coproc NAME { …; }`: a NAME before a compound command names the coprocess
                if len(rest) > 1 and rest[1].static and rest[1].text in KEYWORDS:
                    rest = rest[1:]
                yield from _prefixed(assigns, _command(rest))
                return
            words = rest
            continue
        if name in SHELLS:
            i = 1
            shell_c = False
            while (
                i < len(words) and words[i].text[:1] in "-+" and words[i].text != "--"
            ):
                t = words[i].text
                shell_c |= not t.startswith("--") and "c" in t
                i += (
                    2 if t in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file") else 1
                )
            if shell_c and i < len(words) and words[i].static:
                yield "open", None
                yield from _prefixed(assigns, _parse(_scan(words[i].text)[0]))
                yield "close", None
            elif shell_c or i >= len(words) or words[i].text in ("-", "--"):
                what = f"`{name}` running a computed string or stdin"
                yield "opaque", Opaque(what, words=words[i:], assigns=assigns)
            else:
                what = f"`{name}` running a script"
                yield "opaque", Opaque(what, words[i], assigns=assigns)
            return
        if name == "eval":
            if all(w.static for w in words[1:]):
                text = " ".join(w.text for w in words[1:])
                yield from _prefixed(assigns, _parse(_scan(text)[0]))
            else:
                what = "`eval` of a computed string"
                yield "opaque", Opaque(what, words=words[1:], assigns=assigns)
            return
        if name in ("source", "."):
            script = words[1] if len(words) > 1 else None
            what = f"`{name}` of a script"
            yield "opaque", Opaque(what, script, sourced=True, assigns=assigns)
            return
        break
    yield "cmd", Cmd(assigns, words)


def _parse(tokens):
    """The events of a token list. Each command of a pipeline, and a list run with `&`, runs in a
    subshell of its own, so a `cd` in it leaves the next command where it was."""
    out, element, words = [], [], []
    redirect, nest, before, last = False, 0, None, None

    def end_command():
        nonlocal nest, words
        # `function f { …` and `coproc NAME { …`: the `{` after the name opens the body
        skip, head = 0, words[0].text if words and words[0].static else ""
        if head == "function":
            skip = 2
        elif head == "coproc":
            skip = (
                2
                if len(words) > 2 and words[2].static and words[2].text in KEYWORDS
                else 1
            )
        for w in words[skip:]:
            if not (w.static and w.text in KEYWORDS | NOT_COMMANDS):
                break
            nest += (w.text in OPENERS) - (w.text in CLOSERS)
        for kind, c in _command(words):
            if isinstance(c, Cmd):  # the "cmd" events
                c.after = last
            element.append((kind, c))
        words = []

    def end_element(op):
        nonlocal element, before
        if before in ASYNC or op in ASYNC:
            element = [("open", None), *element, ("close", None)]
        out.extend(element)
        element, before = [], op

    for t in tokens:
        if isinstance(t, str):
            if t in REDIRECTS:
                redirect = True
                continue
            end_command()
            if t in ("(", ")"):
                nest += 1 if t == "(" else -1
                element.append(("open" if t == "(" else "close", None))
                continue
            if nest <= 0:
                end_element(t)
            last = t
            continue
        for sub in t.subs:
            element += [("open", None), *_parse(sub), ("close", None)]
        if redirect:
            redirect = False
        else:
            words.append(t)
    end_command()
    end_element(None)
    return out


def events(text):
    """("open" | "close", None) around each subshell, ("cmd", Cmd) for each simple command and
    ("opaque", what) for text run that cannot be read."""
    return _parse(_scan(text)[0])


def words(text):
    """Every word of text with its quotes and escapes read, redirect targets and the words of
    each `$( )` included: what a check for a name in the text should search. A static word that
    still holds shell syntax (a `bash -c` or `eval` string) is read again, as deep as it nests:
    reading a word only drops quotes and escapes, so each level is shorter until one reads as
    itself."""
    out = []

    def collect(tokens, text):
        for t in tokens:
            if not isinstance(t, str):
                out.append(t)
                for sub in t.subs:
                    collect(sub, text)
                if t.static and t.text != text and SYNTAX.search(t.text):
                    collect(_scan(t.text)[0], t.text)

    collect(_scan(text)[0], text)
    return out


def elements(text):
    """The text of each element of text's top-level lists, a heredoc's body with its command: a
    subshell, a `{ }` group, `if … fi`, `case … esac` and `do … done` stay whole, with the
    redirects on them."""
    cuts = []
    _scan(text, cuts=cuts)
    out, start = [], 0
    for end in [*cuts, len(text)]:
        out.append(text[start:end])
        start = end
    return [part for part in out if part.strip()]


OUTPUTS = {">", ">>", ">|", "&>", "&>>"}


def redirects(text):
    """(target word, the words of the simple command before it) for each output redirect in
    text, `$( )` and `bash -c` strings included as words() reads them; the words are only `}`
    after a group and none after a `)`."""
    out = []

    def collect(tokens, text):
        before, op = [], None
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
                collect(_scan(t.text)[0], t.text)

    collect(_scan(text)[0], text)
    return out


def git_args(cmd):
    """(git's own options as [(option, value or None)], subcommand, its argument words) when cmd
    runs git, else None. The subcommand is None when its word is not static."""
    if cmd.name != "git":
        return None
    words, i, opts = cmd.words, 1, []
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
