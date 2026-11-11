# SPDX-License-Identifier: MIT
"""The `git` and `gh` commands a Bash tool call runs.

Read as bash reads it (shell_cmd.py), with a word-by-word fallback for text the reader
cannot follow.
"""

import collections
import os
import pathlib
import re
from collections.abc import Sequence
from typing import NamedTuple

import shell_cmd

# Git commands that make a commit: one made before the agent re-reads a ruling skips it
# (F59).
COMMITTING = {"commit", "merge", "cherry-pick", "revert", "am", "pull", "rebase"}
# Tools that publish to a package registry or an image registry, with the verbs that do:
# what they send cannot be taken back, and one lead published five immutable packages on
# a bare "go" (F81). A verb counts anywhere in the command's words, and so does `--push`
# (`docker buildx build --push`) or a computed word (outward.py); a false match only
# asks.
PUBLISHERS = {
    "gradle": {"publish"},
    "gradlew": {"publish"},
    "skopeo": {"copy"},
    "crane": {"push", "copy"},
    "npm": {"publish"},
    "pnpm": {"publish"},
    "yarn": {"publish"},
    "bun": {"publish"},
    "deno": {"publish"},
    "vsce": {"publish"},
    "cargo": {"publish"},
    "twine": {"upload"},
    "poetry": {"publish"},
    "uv": {"publish"},
    "flit": {"publish"},
    "hatch": {"publish"},
    "gem": {"push"},
    "dotnet": {"push"},
    "nuget": {"push"},
    "mvn": {"deploy"},
    "docker": {"push"},
    "podman": {"push"},
    "helm": {"push"},
}
# How many script files deep a command's scripts are read.
SCRIPT_DEPTH = 3
# How many words after a `git`, `gh` or publisher's word text_commands reads.
TEXT_WORDS = 40


class _Text(NamedTuple):
    """A command being read, its script depth, and the script names it uses twice.

    A script so named may be written by the command before it runs.
    """

    command: str
    depth: int
    twice: frozenset[str]


def _basename(text: str) -> str:
    """Return the last `/`-separated part of text, as os.path.basename does."""
    return text.rpartition("/")[2]


def _home(text: str) -> str:
    """Return text with a leading `~` read as a home; an unknown user's stays as is."""
    if not text.startswith("~"):
        return text
    try:
        return str(pathlib.Path(text).expanduser())
    except RuntimeError:
        return text


def _read(command: str) -> tuple[list[shell_cmd.Event], frozenset[str]] | None:
    """Return the command's events and script names used twice; None if unreadable.

    A script is named by the words of the commands run and by the files written.
    """
    try:
        found = shell_cmd.events(command)
        named = [
            w.text for _, c in found if isinstance(c, shell_cmd.Cmd) for w in c.words
        ]
        named += [
            c.script.text
            for _, c in found
            if isinstance(c, shell_cmd.Opaque) and c.script
        ]
        named = [_basename(t) for t in named]
        named += [_basename(t.text) for t, _ in shell_cmd.redirects(command)]
    except Exception:  # noqa: BLE001 — unreadable text falls back to the text check
        return None
    counts = collections.Counter(named)
    return found, frozenset(n for n, k in counts.items() if k > 1)


def _computed(
    c: shell_cmd.Cmd, env: dict[str, str], command: str
) -> shell_cmd.Cmd | list[shell_cmd.Cmd] | None:
    """Return the command bash runs for a computed name, or the commands in its words.

    A variable the command sets once is read as that value; one it sets more than once,
    in a loop or by `read` sends the whole text to the word read (None). A name the
    command's own assignments do not fill has only its own words read (text_commands).
    """
    refs = [m[1] for m in re.finditer(r"\$\{?([A-Za-z_]\w*)", c.words[0].text)]
    sets = sum(len(re.findall(rf"(?<![\w${{]){v}(?!\w)", command)) for v in refs)
    name = c.words[0].expand(env) if sets == 1 else None
    if name is None and sets:
        return None
    if name is None:
        return text_commands(" ".join(w.text for w in c.words))
    if re.search(r"[*?\[]", name):  # a glob the shell expands against files
        return None
    # bash splits the value into words (`G='gh pr merge'; $G 5`, `E=; $E gh …`) on IFS.
    # A command that touches IFS splits on the value read and on any punctuation too:
    # one set again where it cannot be read (`unset`, `export`, `read`, a subshell) then
    # only splits more than bash would, never less.
    if not re.search(r"\bIFS\b", command):
        parts = name.split()
    else:
        ifs = "|[" + re.escape(env["IFS"]) + "]" if env.get("IFS") else ""
        parts = [p for p in re.split(r"[^\w./-]" + ifs, name) if p]
    words = [*map(shell_cmd.literal, parts), *c.words[1:]]
    return shell_cmd.Cmd(c.assigns, words) if words else []


def _resolve(
    c: shell_cmd.Cmd, env: dict[str, str], command: str
) -> shell_cmd.Cmd | list[shell_cmd.Cmd] | None:
    """Return c with its computed name read (_computed); a bare assignment sets env."""
    if not c.words:
        env |= {n: x for n, v in c.assigns if (x := v.expand(env)) is not None}
        return c
    return c if c.words[0].static else _computed(c, env, command)


def _script(
    target: shell_cmd.Cmd | shell_cmd.Opaque, here: str | None, depth: int
) -> tuple[shell_cmd.Word | None, str | None]:
    """Return the script file target runs and its text, None where it cannot be read."""
    if isinstance(target, shell_cmd.Opaque):
        script = target.script
        return script, (
            shell_cmd.read_script(script, here) if depth < SCRIPT_DEPTH else None
        )
    script = target.words[0] if target.words and depth < SCRIPT_DEPTH else None
    return script, shell_cmd.run_script(script, here)


def _nested(
    read: _Text, script: shell_cmd.Word | None, text: str | None, here: str | None
) -> list[shell_cmd.Cmd] | None:
    """Return the commands of a script file the command runs; None if unreadable.

    One the command writes before it runs has the command's own words read too.
    """
    if text is None or script is None:  # script is set wherever text was read
        return None
    inner = bash_commands(text, here, read.depth + 1)
    if inner is not None and _basename(script.text) in read.twice:
        inner += text_commands(read.command)
    return inner


def _dir_after(c: shell_cmd.Cmd, here: str | None) -> str | None:
    """Return the shell's directory after c: None after a `cd` to a computed path."""
    if c.name in ("pushd", "popd"):
        return None
    if c.name != "cd":
        return here
    to = next((w for w in c.words[1:] if w.text not in ("-L", "-P", "--")), None)
    path = _home(to.text if to else "~")
    if (to and (not to.static or to.text == "-")) or not (
        here or pathlib.Path(path).is_absolute()
    ):
        return None
    return os.path.normpath(pathlib.Path(here or "", path))


def _tools(c: shell_cmd.Cmd) -> list[shell_cmd.Cmd] | None:
    """Return each `git` command in c and its first `gh` or publisher, from that word.

    None when a git subcommand is computed. Every `git` word counts (`sudo -u git git
    push`); only the first `gh` or publisher, whose check reads all the words after it
    (each later one took the line to quadratic time).
    """
    out: list[shell_cmd.Cmd] = []
    names = [_basename(w) for w in c.argv]
    for i, name in enumerate(names):
        if name == "git" or (name in ("gh", *PUBLISHERS) and name not in names[:i]):
            cmd = shell_cmd.Cmd([], c.words[i:])
            if (g := shell_cmd.git_args(cmd)) and g[1] is None:
                return None
            out.append(cmd)
    return out


def bash_commands(
    command: str, cwd: str | None = None, depth: int = 0
) -> list[shell_cmd.Cmd] | None:
    """Return each `git`, `gh` and PUBLISHERS command the Bash command runs.

    Each is read from that word on (`sudo git commit`), as bash reads the command
    (shell_cmd.py): regexes over the text missed wrapped and quoted forms and
    backtracked for 36 s on a long line. A script file it runs is read in turn, three
    deep. None when a part cannot be read — stdin or an unreadable script fed to a
    shell, a computed `bash -c` or `eval`, a computed git subcommand — or the reader
    fails on it (nesting too deep): the caller then reads the words (text_commands). A
    computed command name the command's own assignments do not fill (`$PY -m pytest`)
    has only its own words read so: read with the whole text, a commit message naming
    `gh release create` beside it was held.
    """
    if (parsed := _read(command)) is None:
        return None
    found, twice = parsed
    read = _Text(command, depth, twice)
    out: list[shell_cmd.Cmd] = []
    # each shell's directory, where a script path is read from: None after a `cd` to a
    # computed path
    dirs = [cwd]
    # the command's own `NAME=value` assignments (`G=gh; $G pr merge 5`)
    env: dict[str, str] = {}
    for kind, event in found:
        if kind == "open":
            dirs.append(dirs[-1])
            continue
        if event is None:  # a subshell's close
            dirs = dirs[:-1] or dirs
            continue
        here = dirs[-1]
        c = None
        if isinstance(event, shell_cmd.Cmd):
            c = _resolve(event, env, command)
            if c is None:
                return None
            if isinstance(c, list):
                out += c
                continue
        script, text = _script(event if c is None else c, here, depth)
        if c is not None and text is None:
            dirs[-1] = _dir_after(c, here)
            more = _tools(c)
        else:
            more = _nested(read, script, text, here)
        if more is None:
            return None
        out += more
    return out


def text_commands(command: str) -> list[shell_cmd.Cmd]:
    """Return each `git`, `gh` and PUBLISHERS command in text the reader cannot follow.

    Read word by word: from that word to the next such word, at most 40 words. A regex
    over the text for `gh` or `push` held a stub `gh` on PATH, a JS `.push(` and a plain
    push (2026-10-31). The blank-split words, ends trimmed, count too: a heredoc's body
    is text to the reader but commands to a shell fed it (`bash <<EOF`), and the reader
    fails on nesting too deep.
    """
    texts = [re.sub(r"^[$(`'\"]+|[)`'\";&|]+$", "", t) for t in command.split()]
    try:
        read = [w.text for w in shell_cmd.words(command)]
    except Exception:  # noqa: BLE001 — the blank-split words alone
        read = []
    texts = read + texts
    # a NAME=value word is read as its value (`X='gh pr close 5'`)
    names = [_basename(re.sub(r"^[A-Za-z_]\w*=", "", t)) for t in texts]
    out: list[shell_cmd.Cmd] = []
    for i, name in enumerate(names):
        if name in ("git", "gh", *PUBLISHERS):
            # only a git or gh word ends one: a publisher's may be a value
            # (`gh -R npm pr merge`)
            end = min(len(names), i + TEXT_WORDS + 1)
            end = next((k for k in range(i + 1, end) if names[k] in ("git", "gh")), end)
            cmd = shell_cmd.Cmd(
                [], [shell_cmd.literal(t) for t in [name, *texts[i + 1 : end]]]
            )
            cmd.loose = True  # words in no known order: outward_cmd reads them loosely
            out.append(cmd)
    return out


def _ff_only(args: Sequence[shell_cmd.Word]) -> bool:
    """Return whether the last of --ff, --no-ff and --ff-only in args is --ff-only."""
    modes = [a.text for a in args if a.text in ("--ff", "--no-ff", "--ff-only")]
    return modes[-1:] == ["--ff-only"]


def makes_commit(command: str, cwd: str | None = None) -> bool:
    """Return whether the command makes a commit of its own.

    A fast-forward-only merge makes none (the last of --ff, --no-ff and --ff-only is the
    one git uses).
    """
    cmds = bash_commands(command, cwd)
    if cmds is None:
        cmds = text_commands(command)
    return any(
        (g := shell_cmd.git_args(c))
        and g[1] in COMMITTING
        and not (g[1] == "merge" and _ff_only(g[2]))
        for c in cmds
    )
