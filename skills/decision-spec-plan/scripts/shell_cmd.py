"""A Bash tool call's command text as the simple commands it runs, for the hooks that read one.

Quotes (`$'…'` and `$"…"` too), escapes, comments, heredocs, line continuations, `$( )`, backticks
and `<( )` are read as bash reads them; `bash -c`, `eval` and the pass-through wrappers (`env`,
`timeout`, `nice`, …) are unwrapped. Not a shell: no globbing, aliases or functions, and a variable
expands only to a literal value. Regexes over the raw text missed `if …; then git push`,
`timeout 60 git push`, `(cd x) &&` and a quoted `-C` path, and matched `echo "… git push"` and
`git log --grep push`.

events(text) returns ("open", None) and ("close", None) around a subshell — `( )`, `$( )`, `bash -c`,
a pipeline's commands, a command run with `&` — ("cmd", Cmd) for each simple command, in the order
bash starts them, and ("opaque", what) for text a shell runs that the reader cannot see: a script or
stdin fed to a shell, `source`, a `bash -c` or `eval` of a computed string.
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
# Pass-through wrappers: their options (and the options' values) skipped, the rest is the command.
WRAPPERS = {
    "env": {"-u", "--unset"},
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
}
# Options after which a wrapper's rest is no plain command here: a directory change, a split
# string, a lookup.
WRAPPER_STOPS = {"-C", "--chdir", "-S", "--split-string", "-v", "-V"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
TEMP = "\0temp"  # a `$(mktemp …)` value: a fresh directory, in no repository
# A run of characters with no meaning to the scanner, read at once: one at a time was quadratic.
LITERAL = re.compile(r"[^ \t\r\n\\'\"$`;&|()<>]+|.", re.DOTALL)
DQ_LITERAL = re.compile(r'[^"\\$`]+|.', re.DOTALL)
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
    operator before it (`&&`, `;`, `|`, …), None first in its list."""

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
            word.add("q", m[0])
            i = m.end()
    return n


def _ansi_c(s):
    """The value of a `$'…'` string's text."""

    def one(m):
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


def _scan(text, i=0, close=False):
    """Words and operator strings of text[i:]; with close, up to the `)` that closes a `$(`.
    Returns (tokens, the index after the last character read)."""
    tokens, word, depth, n = [], None, 0, len(text)
    heredocs, delimiter_next = [], None

    def end_word():
        nonlocal word, delimiter_next
        if word is not None:
            if delimiter_next:
                heredocs.append((word.text, delimiter_next == "<<-"))
                delimiter_next = None
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
        else:
            m = LITERAL.match(text, i)
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


def _command(words):
    while words and words[0].static and words[0].text in KEYWORDS:
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
            rest, valued, positional = words[1:], WRAPPERS[name], int(name == "timeout")
            while rest:
                t = rest[0].text
                if t in WRAPPER_STOPS:
                    break
                if t == "--":
                    rest = rest[1:]
                    break
                if t.startswith("-") and t != "-":
                    rest = rest[2:] if t in valued else rest[1:]
                elif name == "env" and (a := _split_assign(rest[0])):
                    assigns.append(a)
                    rest = rest[1:]
                elif positional:
                    positional -= 1
                    rest = rest[1:]
                else:
                    break
            if rest and rest[0].text in WRAPPER_STOPS:
                break
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
                yield from _parse(_scan(words[i].text)[0])
                yield "close", None
            else:
                yield "opaque", f"`{name}` running a computed string, a script or stdin"
            return
        if name == "eval":
            if all(w.static for w in words[1:]):
                yield from _parse(_scan(" ".join(w.text for w in words[1:]))[0])
            else:
                yield "opaque", "`eval` of a computed string"
            return
        if name in ("source", "."):
            yield "opaque", f"`{name}` of a script"
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
        for w in words:
            if not (w.static and w.text in KEYWORDS | NOT_COMMANDS):
                break
            nest += (w.text in OPENERS) - (w.text in CLOSERS)
        for kind, c in _command(words):
            if kind == "cmd":
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
