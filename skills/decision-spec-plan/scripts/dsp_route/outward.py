# SPDX-License-Identifier: MIT
"""Outward actions on the hosted repository or a registry, and review comments.

The lead asks the user before each outward action, and a route agent never runs one
(F81). A review comment or note posted to GitHub or GitLab is held while the review's
decision document fails its check (F104).
"""

import functools
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
# The commands that post a review comment or note: each tool's noun and verbs, and the
# REST paths a POST to which posts one (F104).
REVIEW_VERBS = {
    "gh": ("pr", {"review", "comment"}),
    "glab": ("mr", {"note", "comment"}),
}
REVIEW_PATHS = {
    "gh": re.compile(r"\b(?:issues|pulls)/[^/\s]+/(?:comments|reviews)\b"),
    "glab": re.compile(r"/(?:notes|discussions)\b"),
}
# the GraphQL mutations that post a pull request comment or review
REVIEW_MUTATION = re.compile(
    r"\b(?:addComment|addPullRequestReview\w*|submitPullRequestReview)\b"
)
# The subset that posts a review itself, held even where no index records one (F104).
REVIEW_SHAPES = {"gh": ("pr", {"review"})}
REVIEW_SHAPE_PATHS = {"gh": re.compile(r"\bpulls/[^/\s]+/reviews\b")}
REVIEW_SHAPE_MUTATION = re.compile(
    r"\b(?:addPullRequestReview\w*|submitPullRequestReview)\b"
)


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


def _api_call(rest: Sequence[str]) -> tuple[str | None, list[str]]:
    """Return an `api` command's method option, None without one, and its fields."""
    after = [*rest[rest.index("api") + 1 :], ""]
    method: str | None = None
    fields: list[str] = []
    for i, w in enumerate(after[:-1]):
        if m := re.fullmatch(r"(?:-X|--method)=?(.*)", w):
            method = (m[1] or after[i + 1]).upper()
        elif re.match(r"-[fF]|--(?:field|raw-field|input)\b", w):
            fields.append(w + " " + after[i + 1])
    return method, fields


def _gh_api(rest: Sequence[str], verb: Sequence[str]) -> bool:
    """Return whether `gh api` writes.

    A method other than GET writes, else a field (which makes it a POST), but a graphql
    query only when it is a mutation or read from a file.
    """
    method, fields = _api_call(rest)
    if method:
        return method in ("POST", "PATCH", "PUT", "DELETE")
    if verb[1:2] == ["graphql"]:
        # a computed query (`query="$Q"`) may be a mutation too
        return any(re.search(r"\bmutation\b|=@|^--input|[$`]", f) for f in fields)
    return bool(fields)


def _positional(rest: Sequence[str]) -> list[str]:
    """Return the words that are no option or `-R`'s value: the noun and verb first.

    (`gh -R o/r pr merge`, `gh pr -R o/r close`); a later word is a value (`--label
    delete`).
    """
    verb: list[str] = []
    skip = False
    for w in rest:
        if not (skip or w.startswith("-")):
            verb.append(w)
        skip = w in ("-R", "--repo")
    return verb


def _gh_outward(cmd: shell_cmd.Cmd) -> bool:
    """Return whether cmd, a `gh` command, acts on the hosted repository."""
    rest = cmd.argv[1:]
    if "--delete-branch" in rest:
        return True
    verb = _positional(rest)
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


def _api_posts(
    tool: str, rest: Sequence[str], verb: Sequence[str], *, shaped: bool
) -> bool:
    """Return whether a `gh api` or `glab api` call POSTs a review comment or note.

    A field makes the call a POST unless a method says otherwise; a graphql query
    posts one when it names a review mutation. Shaped, only a review itself counts.
    """
    method, fields = _api_call(rest)
    if (method or ("POST" if fields else "GET")) != "POST":
        return False
    mutation, path = (
        (REVIEW_SHAPE_MUTATION, REVIEW_SHAPE_PATHS[tool])
        if shaped
        else (REVIEW_MUTATION, REVIEW_PATHS[tool])
    )
    if tool == "gh" and verb[1:2] == ["graphql"]:
        return any(mutation.search(f) for f in fields)
    after = rest[rest.index("api") + 1 :]
    # a field's `key=value` is no path
    paths = [w for w in after if not re.match(r"[\w\[\]]+=", w)]
    return any(path.search(w) for w in paths)


def review_post_cmd(cmd: shell_cmd.Cmd, *, shaped: bool = False) -> bool:
    """Return whether cmd, from a `gh` or `glab` word on, posts a review comment.

    Shaped, whether it posts a review itself: `gh pr review`, a POST to a pull
    request's reviews, a review mutation.
    """
    table = REVIEW_SHAPES if shaped else REVIEW_VERBS
    if cmd.name not in table:
        return False
    noun, verbs = table[cmd.name]
    rest = cmd.argv[1:]
    verb = _positional(rest)
    if cmd.loose:
        # words in no known order: the noun with a verb anywhere after
        last = {w: i for i, w in enumerate(rest)}
        if noun in last and any(last.get(v, -1) > rest.index(noun) for v in verbs):
            return True
    elif verb[:1] != ["api"]:
        return len(verb) > 1 and verb[0] == noun and verb[1] in verbs
    return "api" in rest and _api_posts(cmd.name, rest, verb, shaped=shaped)


@functools.cache
def _commands(command: str, cwd: str | None) -> list[shell_cmd.Cmd]:
    """Return the commands a Bash command runs, read once for every check."""
    cmds = bash_commands(command, cwd)
    return text_commands(command) if cmds is None else cmds


def outward_in(command: str, cwd: str | None = None) -> str | None:
    """Return the first outward action the command runs, as its words, or None."""
    return next(
        (" ".join(c.argv) for c in _commands(command, cwd) if outward_cmd(c)), None
    )


def _bash(event: Mapping[str, object]) -> tuple[str, str | None]:
    """Return a Bash call's command and its directory."""
    command = str((as_dict(event.get("tool_input")) or {}).get("command") or "")
    cwd = event.get("cwd")
    return command, cwd if isinstance(cwd, str) else None


def _active(entry: Mapping[str, object]) -> bool:
    """Return whether the registry entry's route marker still exists."""
    marker = entry.get("marker")
    return bool(marker and pathlib.Path(str(marker)).exists())


def outward(event: Mapping[str, object], entry: Mapping[str, object]) -> str | None:
    """Return the outward action an active route's Bash command takes, if any."""
    if event.get("tool_name") != "Bash" or not _active(entry):
        return None
    command, cwd = _bash(event)
    if not (found := outward_in(command, cwd)):
        return None
    # the action matched, then the command it is in: an excerpt alone once showed no gh
    # at all
    whole = " ".join(command.split())[:EXCERPT]
    excerpt = found[:EXCERPT]
    return excerpt if found == whole else f"{excerpt}` in `{whole}"


def review_post(
    event: Mapping[str, object], entry: Mapping[str, object]
) -> tuple[str, bool] | None:
    """Return the review comment an active route's tool call posts, if any (F104).

    A Bash command's `gh` or `glab` post, or an MCP tool whose name ends in
    `create_note`, with whether it posts a review itself (REVIEW_SHAPES), which the
    excerpt then quotes.
    """
    name = str(event.get("tool_name") or "")
    if not _active(entry):
        return None
    if name.startswith("mcp__") and name.endswith("create_note"):
        return name, False
    if name != "Bash":
        return None
    cmds = _commands(*_bash(event))
    for shaped in (True, False):
        if found := next(
            (" ".join(c.argv) for c in cmds if review_post_cmd(c, shaped=shaped)), None
        ):
            return found[:EXCERPT], shaped
    return None
