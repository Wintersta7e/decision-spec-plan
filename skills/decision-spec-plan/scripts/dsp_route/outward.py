"""Outward actions on the hosted repository or a registry, which the lead asks the user before and
a route agent never runs (F81)."""

import pathlib
import re

import shell_cmd

from .commands import PUBLISHERS, bash_commands, text_commands

# Outward actions on the hosted repository: the lead asks the user each time and a route agent
# never runs one (F81). Each noun and verb may have any options between them, as gh accepts. A
# false match only asks.
GH_ACTIONS = {
    "pr": {"close", "merge"},
    "issue": {"close", "delete"},
    "release": {"create", "delete", "edit", "upload"},
    "repo": {"delete", "archive", "rename"},
}


def publish_word(tool, w):
    """Whether word w of a PUBLISHERS command may publish: its verb, a push flag or output
    (`--push=true`, `-o type=registry`), a gradle task that abbreviates `publish…` (`pTML`), or a
    computed word that may be the verb (`npm $V`). A computed word with a path or an `=` outside
    its expansions is a value (`-v $PWD:/app`, `-e K=$V`); a false match only asks."""
    t = w.text
    if t in PUBLISHERS[tool] or t.startswith("--push"):
        return True
    if re.search(r"(?i)\b(?:type=registry|push=(?:1|t|true))\b", t):
        return True
    # gradle runs a task by any camel or kebab abbreviation (`pTML`, `PTML`, `p-t-m-l`): a task
    # word that opens with p may be one
    if tool in ("gradle", "gradlew") and re.match(r"(?i)p", t.rpartition(":")[2]):
        return True
    bare = re.sub(r"\$\{[^}]*\}|\$\([^)]*\)|`[^`]*`", "", t)
    return not (w.static or re.search(r"[/=]", bare))


def outward_cmd(cmd):
    """Whether cmd, a command from a `gh`, `git` or publisher's word on, is an outward action."""
    if cmd.name in PUBLISHERS:
        return any(publish_word(cmd.name, w) for w in cmd.words[1:])
    if cmd.name == "gh":
        rest = cmd.argv[1:]
        if "--delete-branch" in rest:
            return True
        # the noun and the verb: the first two words that are no option or `-R`'s value (`gh -R
        # o/r pr merge`, `gh pr -R o/r close`); a later word is a value (`--label delete`)
        verb, skip = [], False
        for w in rest:
            if not (skip or w.startswith("-")):
                verb.append(w)
            skip = w in ("-R", "--repo")
        if getattr(cmd, "loose", False):
            # words read from text the reader could not follow: a noun with its verb anywhere after
            last = {w: i for i, w in enumerate(rest)}
            if any(
                w in GH_ACTIONS and any(last.get(v, -1) > i for v in GH_ACTIONS[w])
                for i, w in enumerate(rest)
            ):
                return True
        elif verb[:1] != ["api"]:
            return len(verb) > 1 and verb[1] in GH_ACTIONS.get(verb[0], ())
        if "api" not in rest:
            return False
        # `gh api` that writes: a method other than GET, else a field (which makes it a POST), but
        # a graphql query only when it is a mutation or read from a file
        after = rest[rest.index("api") + 1 :] + [""]
        method, fields = None, []
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
    # remote refs deleted by `git push`: --delete, -d (alone or grouped), --prune, --mirror, or a
    # refspec with no source (`:<ref>`, `+:<ref>`)
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


def outward_in(command, cwd=None):
    """The first outward action the command runs, as its words, or None."""
    cmds = bash_commands(command, cwd)
    if cmds is None:
        cmds = text_commands(command)
    return next((" ".join(c.argv) for c in cmds if outward_cmd(c)), None)


def outward(event, entry):
    """The outward action an active route's Bash command takes on the hosted repository, if any."""
    marker = entry.get("marker")
    if event.get("tool_name") != "Bash" or not (
        marker and pathlib.Path(marker).exists()
    ):
        return None
    command = str((event.get("tool_input") or {}).get("command") or "")
    if not (found := outward_in(command, event.get("cwd"))):
        return None
    # the action matched, then the command it is in: an excerpt alone once showed no gh at all
    whole = " ".join(command.split())[:120]
    return found[:120] if found == whole else f"{found[:120]}` in `{whole}"
