# SPDX-License-Identifier: MIT
"""Outward actions on the hosted repository or a registry.

The lead asks the user before each one, and a route agent never runs one (F81).
"""

import pathlib
import re
from collections.abc import Mapping, Sequence

import shell_cmd

from .commands import PUBLISHERS, bash_commands, text_commands
from .common import as_dict

# Outward actions on the hosted repository: the lead asks the user each time and a route
# agent never runs one (F81). Each noun and verb may have any options between them, as
# gh accepts. A false match only asks.
GH_ACTIONS = {
    "pr": {"close", "merge"},
    "issue": {"close", "delete"},
    "release": {"create", "delete", "edit", "upload"},
    "repo": {"delete", "archive", "rename"},
}
# How much of an action and of its command a hold quotes.
EXCERPT = 120


def publish_word(tool: str, w: shell_cmd.Word) -> bool:
    """Return whether word w of a PUBLISHERS command may publish.

    It may be its verb, a push flag or output (`--push=true`, `-o type=registry`), a
    gradle task that abbreviates `publish…` (`pTML`), or a computed word that may be the
    verb (`npm $V`). A computed word with a path or an `=` outside its expansions is a
    value (`-v $PWD:/app`, `-e K=$V`); a false match only asks.
    """
    t = w.text
    if t in PUBLISHERS[tool] or t.startswith("--push"):
        return True
    if re.search(r"(?i)\b(?:type=registry|push=(?:1|t|true))\b", t):
        return True
    # gradle runs a task by any camel or kebab abbreviation (`pTML`, `PTML`, `p-t-m-l`):
    # a task word that opens with p may be one
    if tool in ("gradle", "gradlew") and re.match(r"(?i)p", t.rpartition(":")[2]):
        return True
    bare = re.sub(r"\$\{[^}]*\}|\$\([^)]*\)|`[^`]*`", "", t)
    return not (w.static or re.search(r"[/=]", bare))


def _gh_api(rest: Sequence[str], verb: Sequence[str]) -> bool:
    """Return whether `gh api` writes.

    A method other than GET writes, else a field (which makes it a POST), but a graphql
    query only when it is a mutation or read from a file.
    """
    after = [*rest[rest.index("api") + 1 :], ""]
    method: str | None = None
    fields: list[str] = []
    for i, w in enumerate(after[:-1]):
        if m := re.fullmatch(r"(?:-X|--method)=?(.*)", w):
            method = (m[1] or after[i + 1]).upper()
        elif re.match(r"-[fF]|--(?:field|raw-field|input)\b", w):
            fields.append(w + " " + after[i + 1])
    if method:
        return method in ("POST", "PATCH", "PUT", "DELETE")
    if verb[1:2] == ["graphql"]:
        # a computed query (`query="$Q"`) may be a mutation too
        return any(re.search(r"\bmutation\b|=@|^--input|[$`]", f) for f in fields)
    return bool(fields)


def _gh_outward(cmd: shell_cmd.Cmd) -> bool:
    """Return whether cmd, a `gh` command, acts on the hosted repository."""
    rest = cmd.argv[1:]
    if "--delete-branch" in rest:
        return True
    # the noun and the verb: the first two words that are no option or `-R`'s value (`gh
    # -R o/r pr merge`, `gh pr -R o/r close`); a later word is a value (`--label
    # delete`)
    verb: list[str] = []
    skip = False
    for w in rest:
        if not (skip or w.startswith("-")):
            verb.append(w)
        skip = w in ("-R", "--repo")
    if cmd.loose:
        # words read from text the reader could not follow: a noun with its verb
        # anywhere after
        last = {w: i for i, w in enumerate(rest)}
        if any(
            w in GH_ACTIONS and any(last.get(v, -1) > i for v in GH_ACTIONS[w])
            for i, w in enumerate(rest)
        ):
            return True
    elif verb[:1] != ["api"]:
        return len(verb) > 1 and verb[1] in GH_ACTIONS.get(verb[0], ())
    return "api" in rest and _gh_api(rest, verb)


def outward_cmd(cmd: shell_cmd.Cmd) -> bool:
    """Return whether cmd, from a `gh`, `git` or publisher's word on, acts outward."""
    if cmd.name in PUBLISHERS:
        return any(publish_word(cmd.name, w) for w in cmd.words[1:])
    if cmd.name == "gh":
        return _gh_outward(cmd)
    # remote refs deleted by `git push`: --delete, -d (alone or grouped), --prune,
    # --mirror, or a refspec with no source (`:<ref>`, `+:<ref>`)
    g = shell_cmd.git_args(cmd)
    return (
        bool(g)
        and g[1] == "push"
        and any(
            w in ("--delete", "--prune", "--mirror")
            or re.fullmatch(r"-[a-zA-Z]*d[a-zA-Z]*|\+?:.+", w)
            for w in (a.text for a in g[2])
        )
    )


def outward_in(command: str, cwd: str | None = None) -> str | None:
    """Return the first outward action the command runs, as its words, or None."""
    cmds = bash_commands(command, cwd)
    if cmds is None:
        cmds = text_commands(command)
    return next((" ".join(c.argv) for c in cmds if outward_cmd(c)), None)


def outward(event: Mapping[str, object], entry: Mapping[str, object]) -> str | None:
    """Return the outward action an active route's Bash command takes, if any."""
    marker = entry.get("marker")
    if event.get("tool_name") != "Bash" or not (
        marker and pathlib.Path(str(marker)).exists()
    ):
        return None
    command = str((as_dict(event.get("tool_input")) or {}).get("command") or "")
    cwd = event.get("cwd")
    if not (found := outward_in(command, cwd if isinstance(cwd, str) else None)):
        return None
    # the action matched, then the command it is in: an excerpt alone once showed no gh
    # at all
    whole = " ".join(command.split())[:EXCERPT]
    excerpt = found[:EXCERPT]
    return excerpt if found == whole else f"{excerpt}` in `{whole}"
