#!/usr/bin/env python3
"""List the tests a commit range takes away: what a lane gave up to turn its gate green.

A lane's gate passes as easily by testing less as by fixing the code, and the review of its diff
reads the code it changed, not the tests it no longer runs. On impossible tasks, Claude-family
agents that cheated did it mostly by editing the tests. This lists five kinds of change in
`<base>..<head>` (in `--repo`, default `.`):

    DELETED  <file>              a test file the range deletes or renames out of the test paths
    REMOVED  <test>  <file>      a test whose defining line the range removes and adds nowhere
    SKIP     <file>:<line> <text>  a skip, only or ignore marker the range adds
    FEWER    <file>  <n> fewer assertions   a test file of the range that ends with fewer
    EDITED   <file>  <commit>…   an acceptance test file one of whose assertions or tests a
                                 commit changes or removes after it was written

An acceptance test file is a test file a row of a plan's mapping table (`| Id | Task | Test file |`,
read as criteria_check.py reads it) maps an `AC-` id to (a source file holding the test changes
with its code); a rename inside the test paths carries it along. Its assertions and
tests are read-only once written — by the base, or by the range's first commit that touches it —
and later commits may only add beside them: an assertion loosened in place keeps every count the
same.

A test file is a path under `test/`, `tests/`, `__tests__/` or `spec/`, or named `test_*.py`,
`*_test.py`, `*_test.go`, `*.test.js`/`*.spec.ts` (and the jsx/tsx/mjs/cjs kin), `*Test.java`,
`*Tests.cs`, `*Test.kt` or `*_spec.rb`. A test is a Python `def test*`, a Go `func Test*`, a JS/TS
`it('...')` or `test('...')`, or the function after a `#[test]`, `@Test`, `[Fact]`, `[Test]` or
`[TestMethod]` line. The tests of a deleted file are its DELETED line, not REMOVED lines. An
assertion is a line of a test file opening with `assert` or calling `assert*(`, `assert*!(`,
`expect(`, `Assert.*(`, `t.Error(`, `t.Fatal(` or `require.*(`; one the range adds back anywhere
moved, one rewritten in place offsets the line it replaced, and a removed test's own are its
REMOVED line.

A DELETED or REMOVED line passes when a plan matching `--glob` names it: the path, or the test's
name standing alone. A SKIP, FEWER or EDITED line, or a deleted acceptance test file, never passes: the lead rules each one, since a
plan that names a skip does not say the test it hides was meant to fail. Not caught: an assertion
loosened in place outside an acceptance test file, a test body emptied there, assertions dropped
from a test inside a source file (a Rust `mod tests`), a test excluded by the runner's
configuration.

Usage:
    test_check.py <plans-dir> --diff <base>..<head> [--repo <repo>] [--glob 'p1-03-*.md']

Exit 0 when nothing is unnamed and nothing went to the lead, 1 otherwise, 2 when the range changed
nothing or git failed.
"""

import argparse
import codecs
import pathlib
import re
import subprocess
import sys


def header_path(rest):
    """The path of a diff's `--- ` or `+++ ` line, None for /dev/null. Git C-quotes a path with a
    `"`, a backslash or a control character, and ends one holding a space with a tab."""
    rest = rest.rstrip("\t")
    if rest == "/dev/null":
        return None
    if rest.startswith('"'):
        rest = codecs.escape_decode(rest[1:-1].encode())[0].decode(errors="replace")
    return rest[2:]


TEST_PATH = re.compile(
    r"(?:^|/)(?:tests?|__tests__|spec)/|(?:^|/)test_[^/]*\.py$|_test\.(?:py|go)$"
    r"|\.(?:test|spec)\.[cm]?[jt]sx?$|Tests?\.(?:java|kt|cs)$|_spec\.rb$"
)
NAME = re.compile(
    r"^\s*(?:async\s+)?def\s+(test\w*)|^func\s+(Test\w+)\s*\("
    r"|^\s*(?:it|test)(?:\.\w+)*\s*\(\s*(['\"`])(.+?)\3"
)
ATTR = re.compile(
    r"^\s*(?:#\[(?:\w+::)?test\]|@Test\b|\[(?:Fact|Theory|Test|TestMethod)\])"
)
AFTER_ATTR = re.compile(r"\bfn\s+(\w+)|\b(\w+)\s*\(")
# the attributes a line opens with: `@Test fun name()` names its test on the same line
ATTRS = re.compile(r"^\s*(?:(?:@[\w.]+(?:\([^)]*\))?|#?\[[^\]]*\])\s*)+")
SKIP = re.compile(
    r"\b(?:it|test|describe|context|suite)\.(?:skip|only|todo|fixme)\b|\bx(?:it|describe|test)\s*\("
    r"|\bpytest\.mark\.(?:skip|skipif|xfail)\b|@unittest\.(?:skip\w*|expectedFailure)\b"
    r"|\bpytest\.(?:skip|xfail)\s*\(|\.skipTest\s*\(|#\[ignore\b|\bt\.Skip(?:Now|f)?\s*\("
    r"|@Disabled\b|@Ignore\b|\[Ignore\b|\bSkip\s*=\s*\""
)
ASSERT = re.compile(
    r"^\s*assert\b|\b(?:assert\w*!?|assert\.\w+|(?<![.\w])expect|Assert\.\w+|t\.(?:Error|Fatal)f?"
    r"|require\.\w+)\s*\("
)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")


def git(repo, *args):
    out = subprocess.run(
        ["git", "-C", repo, "-c", "core.quotePath=false", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode:
        print(out.stderr.strip())
        sys.exit(2)
    return out.stdout


def scan(diff):
    """(names on removed lines, names on added lines, added skip lines, {test file: assertion
    lines removed minus added}) of a -U0 diff; a name is (test, file), a skip (file, line, text).
    An assertion removed after a removed test's defining line in one hunk is that test's, which
    its REMOVED line (or its move) already covers — unless the range adds a test of that name."""
    names = {"-": set(), "+": set()}
    added, asserts, gone, came = [], [], set(), set()
    old = new = path = None
    line, header, armed, inside = 0, False, {"-": False, "+": False}, None
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            header, old, new = True, None, None
            continue
        if header:
            # a deleted file's lines belong to its old path, every other file's to its new one
            if raw.startswith("--- "):
                old = header_path(raw[4:])
            elif raw.startswith("+++ "):
                new = header_path(raw[4:])
                path = new or old
            elif m := HUNK.match(raw):
                line, header, armed = int(m[1]), False, {"-": False, "+": False}
                inside = None
            continue
        if m := HUNK.match(raw):
            line, armed, inside = int(m[1]), {"-": False, "+": False}, None
            continue
        sign, text = raw[:1], raw[1:]
        if sign not in ("+", "-"):
            continue
        name, rest = None, None
        if ATTR.match(text) or (armed[sign] and ATTRS.match(text)):
            # the test marker, or another attribute between it and its function
            armed[sign], rest = True, ATTRS.sub("", text, count=1)
        elif m := NAME.match(text):
            name = m[1] or m[2] or m[4]
        elif armed[sign]:
            rest = text
        if rest and (m := AFTER_ATTR.search(rest)):
            name, armed[sign] = m[1] or m[2], False
        if name:
            names[sign].add((name, path))
            if sign == "-":
                inside = name
        if (
            TEST_PATH.search(path)
            and ASSERT.search(text)
            and not text.lstrip().startswith(("//", "#", "*", "/*"))
        ):
            asserts.append((sign, path, text.strip(), inside if sign == "-" else None))
        if sign == "+":
            if SKIP.search(text):
                added.append((path, line, text.strip()))
            came.add(text.strip())
            line += 1
        else:
            gone.add(text.strip())
    # an assertion whose line the range adds back anywhere moved; one rewritten in place offsets
    # the line it replaced
    fewer, readded = {}, {n for n, _ in names["+"]}
    for sign, p, t, owner in asserts:
        if owner and owner not in readded:
            continue  # the removed test's REMOVED line covers it
        if t not in (came if sign == "-" else gone):
            fewer[p] = fewer.get(p, 0) + (1 if sign == "-" else -1)
    skips = [s for s in added if s[2] not in gone]
    return names["-"], names["+"], skips, fewer


def named(text, word):
    return re.search(rf"(?<![\w./-]){re.escape(word)}(?![\w/-]|\.\w)", text)


def acceptance_files(plans):
    """The test files a mapping table's rows map, `::test` cut off, read as criteria_check reads
    them: a table whose header's second cell starts with "Task", its test cell the first column
    after Task whose header names a test, else the third. A source file holding the test changes
    with the code, so it is never one."""
    files, header, col = set(), None, 2
    for line in plans.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            col = next(
                (k for k, h in enumerate(cells) if k > 1 and "test" in h.lower()), 2
            )
        elif (
            len(header) > 2
            and header[1].lower().startswith("task")
            and col < len(cells)
        ):
            for f in re.findall(r"`([^`]+)`", cells[col]):
                if TEST_PATH.search(path := f.split("::")[0]):
                    files.add(path)
    return files


def edited(repo, rng, path, now=None):
    """The commits of the range, oldest first, that change or remove an assertion or a test's
    defining line of `path` after it was written: a file the base lacks is written by its first
    commit, which is never one. An import widened for a test added beside it is not. `now` is
    the path the range renames it to inside the test paths: the rename itself changes nothing."""
    base = rng.partition("..")[0]
    paths = [path, now] if now else [path]
    commits = git(
        repo, "log", "--no-merges", "--follow", "--format=%h", rng, "--", paths[-1]
    )
    commits = commits.split()[::-1]
    if not git(repo, "ls-tree", base, "--", path).strip():
        commits = commits[1:]
    out = []
    for c in commits:
        diff = git(repo, "diff", "-U0", "-M", f"{c}^", c, "--", *paths).splitlines()
        if any(
            ln.startswith("-")
            and not ln.startswith("--- ")
            and (ASSERT.search(ln[1:]) or NAME.match(ln[1:]) or ATTR.match(ln[1:]))
            and not ln[1:].lstrip().startswith(("//", "#", "*", "/*"))
            for ln in diff
        ):
            out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("plans_dir")
    ap.add_argument("--diff", metavar="RANGE", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--glob", default="*.md")
    args = ap.parse_args()
    plans = "\n".join(
        f.read_text(errors="replace")
        for f in sorted(pathlib.Path(args.plans_dir).glob(args.glob))
    )

    status = git(args.repo, "diff", "--name-status", "-M", "-z", args.diff).split("\0")
    if not [s for s in status if s]:
        print(f"{args.diff} changed nothing")
        return 2
    # a test file renamed out of the test paths no longer runs: it is deleted, and its new path's
    # lines are its DELETED line's, like a deleted file's
    deleted, retired, moved, i = set(), set(), {}, 0
    while i < len(status) - 1:
        kind = status[i]
        if kind == "D":
            deleted.add(status[i + 1])
        elif kind[:1] == "R" and not TEST_PATH.search(status[i + 2]):
            deleted.add(status[i + 1])
            retired.add(status[i + 2])
        elif kind[:1] == "R":
            moved[status[i + 1]] = status[i + 2]
        i += 3 if kind[:1] in "RC" else 2
    # explicit prefixes: header_path() cuts two characters, whatever diff.noprefix says
    diff = git(
        args.repo, "diff", "-U0", "-M", "--src-prefix=a/", "--dst-prefix=b/", args.diff
    )
    removed, added, skips, fewer = scan(diff)
    added_names = {n for n, _ in added}
    gone = deleted | retired

    accept = acceptance_files(plans)
    # the mapping row that names an acceptance test is no plan to delete it
    bad = [
        f"DELETED  {f}"
        for f in sorted(deleted)
        if TEST_PATH.search(f) and (f in accept or not named(plans, f))
    ]
    bad += [
        f"REMOVED  {n}  {f}"
        for n, f in sorted(removed)
        if f not in gone and n not in added_names and not named(plans, n)
    ]
    bad += [f"SKIP     {f}:{n} {t}" for f, n, t in skips]
    bad += [
        f"FEWER    {f}  {n} fewer assertions"
        for f, n in sorted(fewer.items())
        if n > 0 and f not in gone
    ]
    bad += [
        f"EDITED   {f}  {' '.join(cs)}"
        for f in sorted(accept - gone)
        if (cs := edited(args.repo, args.diff, f, moved.get(f)))
    ]
    for b in bad:
        print(b)
    print(
        f"{len(bad)} deleted test files, removed tests, added skips, dropped assertions or "
        "edited acceptance tests need a ruling"
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
