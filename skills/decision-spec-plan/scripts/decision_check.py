#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check a round's ledger: typed SETTLED rows, requirement dimensions, dispositions.

<decisions-dir> is the round's `decisions/phase<P>`. Every check is a failure measured
somewhere:

SETTLED — every row of the index's SETTLED tables (not "Measured numbers") opens with an
id `S<n>`, and its source is a ruling: a user or arbiter ruling (`U<n>`, `A<n>`), a
decision (`D<n>`), an ask (`Ask<n>`), a document (a `.md` path: decision, spec, handoff)
or the user's words with no path. A row whose source is only code `file:lines` records
what today's code does; it read as a ruling and an S build kept the defect it described
(F86). Move it to "Today's code — open to change".

Requirement dimensions — the index's table names each of the nine dimensions (actors and
workflows, data identity, ownership and round-trip, business rules, state machines,
integrations and events, validation and exceptions, background jobs, security and
privacy) with an owner: a ruling or decision id, an ask, an `S<n>` row, or
`N/A: <reason>`. Every arm of one clean room missed a state rule no dimension named
(failure-modes F94).

Dispositions — once `00-seams.md` exists (the seam review at M and L, the §1e review at
S), every finding `R<n>` in it has a row in the Dispositions table (the index's at S,
the arbiter's at M and L, the index's in a round with no arbiter): applied,
`applied (upholds S<n>)`, declined or re-opened. A declined finding's basis is a user
ruling `U<n>`, a SETTLED row `S<n>`, or `verify/R<n>.md` whose first line is
`Verdict: REFUTED`, with a `Claim:` line quoting the finding and a `Mutant run:` line
ending its test's run on code made to match the claim in a non-zero `exit=` — "known
limitation" or "default" is no basis; a finding with `Verdict: UPHELD` is never
declined. A finding applied or re-opened that cites a SETTLED row takes that row out of
SETTLED, unless the fix upholds it: findings that upheld a row were relabelled
"declined" to pass, and the record lied (F98).

With `--verifier R<n> --sha <commit>` it writes `verify/R<n>.prompt.md`: the claim-only
verifier's whole prompt — the finding's text, the commit, the instruction to decide it
with a test — and nothing else: no SETTLED list, no lead rationale, no reviewer name.
Dispatch it unchanged, as an agent named `verify-<id>` (the hook refuses an edited one)
or to the second model. With `--from <sin report>` the directory is a seven-sins run dir
and the claim is that report's finding <id> (`GRE-1`): its place, text and evidence,
without severity or owner — a disputed sins finding is settled this way, not by debate
(sins/lead.md).

Decisions — each row of the index's decisions table names, in its Serves column, the ask
(`Ask<n>`) or user ruling (`U<n>`) it serves, or is marked `backlog`; past six live
decisions the index records the user's triage as `> **Triage**: U<n>`. A review round
grew to 14 mostly-infrastructure decisions priced 20M, was approved, and a minute later
the user disliked its direction (F89). `--legacy` skips this check: the route's hook
passes it for a phase bound before the check existed.

Coverage — an index that records a review (`> **Review**: `<base>..<head>``, the range
`git diff --name-only` lists in --repo, default the decisions dir's repository) has a
Coverage section: each file the range changes in a row labelled `Read in full`, `Diff
read` or `Not read` (tests, recordings, documentation and lockfiles exempt), and each
probe run as a line with its command in backticks and `exit=<n>`. With a file Not read
or no probe, the index's `> **Verdict**:` says unfinished. A lead posted a review whose
verdict rested on files it never read and no probe it ran; the route's hook refuses a
review comment while this check fails (F104).

Usage:
    decision_check.py <decisions-dir> [--rung S|M|L] [--legacy] [--repo <dir>]
    decision_check.py <decisions-dir> --verifier R<n> --sha <commit>
    decision_check.py <run-dir> --verifier <finding id> --sha <commit>
        --from <run-dir>/<sin>.md

Exit 0 when every check holds, 1 with each failure listed, 2 when the index is missing.
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import NamedTuple

DIMENSIONS = (
    "actors",
    "data identity",
    "ownership",
    "business rules",
    "state",
    "integrations",
    "validation",
    "background jobs",
    "security",
)
RULING_ID = re.compile(r"\b(?:[UADS]\d+|Ask\d+)\b")
OWNER = re.compile(r"\b(?:[UADS]\d+|Ask\d+)\b|N/A:\s*\S+")
PATH = re.compile(r"`([^`\s]+?\.[A-Za-z0-9]+)(?::[\d,–-]+)?`")
TRIAGE = 6  # live decisions a round rules before the user triages them
# A finding opens a line with its id — `**R<n>`, or a bare `R<n>` and a dash, colon or
# bracket — after a list marker, a numbered list's `1.` or a heading's `#`s. A wrapped
# line that begins "R1's keying …" is no new finding.
FINDING = re.compile(
    r"^[ \t]*(?:[-*+>|][ \t]*|\d+[.)][ \t]*|#{1,6}[ \t]*)?"
    r"(?:\*\*R(\d+)\b|R(\d+)\b(?=\**[ \t]*[—–:(-]))",
    re.MULTILINE,
)
# a dimensions row: the dimension and its owner
DIMENSION_CELLS = 2
# a Dispositions row: the finding, its disposition and the basis
DISPOSITION_CELLS = 3
# a seven-sins report's finding row runs to its evidence, the seventh cell
SIN_CELLS = 7
# the shortest `Claim:` quote that counts as quoting the claim
MIN_QUOTE = 10
# A review's index records the range it reviews (templates.md §1), and its verdict.
REVIEW = re.compile(
    r"^>?\s*\*\*Review\*\*:\s*`([0-9a-f]{7,40}\.\.\.?[0-9a-f]{7,40})`", re.MULTILINE
)
VERDICT = re.compile(r"^[>\s*]*Verdict[*\s]*:[*\s]*(.*)$", re.MULTILINE)
LABELS = ("Read in full", "Diff read", "Not read")
# a Coverage row: the file and how it was read
COVERAGE_CELLS = 2
# a probe: its command in backticks and the exit code it ended with
PROBE = re.compile(r"`[^`\n]+`.*\bexit=\d+")
# Changed files a review need not read: tests, recordings, documentation, lockfiles.
EXEMPT_DIRS = {
    "test",
    "tests",
    "__tests__",
    "testdata",
    "spec",
    "specs",
    "fixtures",
    "recordings",
    "cassettes",
    "snapshots",
    "__snapshots__",
    "doc",
    "docs",
}
EXEMPT_NAME = re.compile(
    r"(?i)test_.*|.*_test\.\w+|.*\.(?:test|spec)\.\w+|.*Tests?\.(?:java|kt|cs|swift)"
    r"|.*\.(?:snap|har)"
    r"|.*\.(?:md|rst|adoc)|(?:readme|changelog|license)(?:\.\w+)?"
    r"|.*(?:\.lock|\.lockb|\.lockfile|-lock\.(?:json|ya?ml))|go\.sum|packages\.lock\.json"
)


class Disposition(NamedTuple):
    """One Dispositions row, with its finding's text and its verifier's verdict."""

    rid: str
    given: str
    basis: str
    claim: str
    verdict: str | None


class _Args(argparse.Namespace):
    """The command line."""

    decisions_dir: str = ""
    rung: str = "M"
    legacy: bool = False
    verifier: str | None = None
    sha: str | None = None
    report: pathlib.Path | None = None
    repo: str | None = None


def matches(pattern: str, text: str) -> list[str]:
    """Return every match of pattern in text, in order."""
    return [m.group(0) for m in re.finditer(pattern, text)]


def section(text: str, title: str) -> str | None:
    """Return the first `## <title>…` section's body, up to the next `## ` heading."""
    m = re.search(
        rf"^## {title}[^\n]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    return m.group(1) if m else None


def rows(body: str) -> list[list[str]]:
    """Return the cells of each table row that is neither a header nor a separator."""
    lines = body.splitlines()
    out: list[list[str]] = []
    for i, line in enumerate(lines):
        if not line.startswith("|") or re.fullmatch(r"[|\s:-]+", line):
            continue
        if i + 1 < len(lines) and re.fullmatch(r"[|\s:-]+", lines[i + 1]):
            continue
        # GFM's `\|` is a pipe inside a cell, not a cell border
        cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        out.append([c.strip().replace("\\|", "|") for c in cells])
    return out


def settled(index: str) -> tuple[dict[str, str], list[str]]:
    """Return {S-id: source} of the SETTLED rows, and the failures."""
    body = section(index, "SETTLED")
    if body is None:
        return {}, ["the index has no SETTLED section"]
    body = re.split(r"^### Measured numbers", body, flags=re.MULTILINE)[0]
    found: dict[str, str] = {}
    fails: list[str] = []
    for cells in rows(body):
        sid = re.fullmatch(r"\**(S\d+)\**", cells[0])
        if not sid:
            fails.append(f"SETTLED row without an S<n> id: {' | '.join(cells)[:120]}")
            continue
        source = cells[-1]
        paths = [m.group(1) for m in PATH.finditer(source)]
        if (
            paths
            and not RULING_ID.search(source)
            and not any(p.endswith(".md") for p in paths)
        ):
            fails.append(
                f"{sid.group(1)} cites only code ({source[:80]}): that is what "
                "today's code does, not a ruling — move it to Today's code, open to "
                "change (F86)"
            )
        found[sid.group(1)] = source
    return found, fails


def dimensions(index: str) -> list[str]:
    """Return the failures of the index's requirement dimensions table."""
    body = section(index, "Requirement dimensions")
    if body is None:
        return ["the index has no Requirement dimensions table"]
    table = {
        c[0].strip("* ").lower(): c[-1] for c in rows(body) if len(c) >= DIMENSION_CELLS
    }
    fails: list[str] = []
    for dim in DIMENSIONS:
        owner = next((v for k, v in table.items() if k.startswith(dim)), None)
        if owner is None:
            fails.append(f"dimension '{dim}' has no row")
        elif not OWNER.search(owner):
            fails.append(
                f"dimension '{dim}' has no owner (a ruling or decision id, an ask, an "
                f"S<n> row, or 'N/A: <reason>'): {owner[:80]}"
            )
    return fails


def decisions(index: str) -> list[str]:
    """Return the failures of the index's decisions table.

    Each decision names the ask or user ruling it serves, or waits in the backlog; past
    TRIAGE live decisions the index records the user's triage.
    """
    body = section(index, "The decisions")
    if body is None:
        return []
    header = next(
        (
            [
                c.strip().strip("*").lower()
                for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))
            ]
            for line in body.splitlines()
            if line.startswith("|")
        ),
        list[str](),
    )
    if "serves" not in header:
        return [
            (
                "the decisions table has no Serves column: each decision names the "
                "Ask<n> or U<n> it serves, or `backlog` (F89)"
            )
        ]
    col = header.index("serves")
    fails: list[str] = []
    live = 0
    for cells in rows(body):
        did = re.fullmatch(r"\**(D\d+)\**", cells[0])
        if not did or col >= len(cells):
            continue
        if re.search(r"\bbacklog\b", cells[col], re.IGNORECASE):
            continue
        live += 1
        if not re.search(r"\b(?:Ask|U)\d+\b", cells[col]):
            fails.append(
                f"{did[1]} serves no ask or user ruling "
                f"({cells[col][:60] or 'empty'}): cite the Ask<n> or U<n> it serves, "
                "or mark it `backlog` (F89)"
            )
    if live > TRIAGE and not re.search(r"\*\*Triage\*\*:.*\bU\d+", index):
        fails.append(
            f"{live} decisions to rule: past {TRIAGE}, the user triages first — which "
            "to rule now, which wait in the backlog, with each one's cost — recorded "
            "as `> **Triage**: U<n>` (F89)"
        )
    return fails


def findings(seams: str) -> dict[str, str]:
    """Return {R-number: its text}; each finding runs to the next finding or heading.

    A `#` line in a code fence (a shell comment in a repro) or one with no space after
    the `#`s (`#42`) is no heading.
    """
    marks = list(FINDING.finditer(seams))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(seams)
        lines, fenced = seams[m.start() : end].split("\n"), False
        # a heading after the finding's first line ends it; its own `### **R3**` does
        # not
        for k, line in enumerate(lines[1:], 1):
            if re.match(r"\s*(```|~~~)", line):
                fenced = not fenced
            elif not fenced and re.match(r"#{1,6}(?:\s|$)", line):
                lines = lines[:k]
                break
        _ = out.setdefault(f"R{m.group(1) or m.group(2)}", "\n".join(lines))
    return out


def verdict(d: pathlib.Path, rid: str) -> str | None:
    """Return the verdict on the first line of verify/<rid>.md, None without one."""
    path = d / "verify" / f"{rid}.md"
    if not path.exists():
        return None
    first = path.read_text(errors="replace").strip().partition("\n")[0]
    # the verifier's prompt glosses each verdict, and a verifier may copy the gloss onto
    # the line
    m = re.match(r"\W*Verdict:\W*(UPHELD|REFUTED|NO-TEST)(?![\w-])", first)
    return m.group(1) if m else None


def refuted_gaps(d: pathlib.Path, rid: str, claim: str) -> list[str]:
    """Return what a REFUTED verdict lacks to decline a finding.

    It needs a quote of the claim its test checks, and that test failing on a mutant
    that makes the claim true — a test that cannot see the defect refutes nothing.
    """
    text = (d / "verify" / f"{rid}.md").read_text(errors="replace")

    def flat(s: str) -> str:
        return " ".join(s.split())

    out: list[str] = []
    q = re.search(r"(?m)^\W*Claim:\W*(.+?)\W*$", text)
    if not q or len(flat(q[1])) < MIN_QUOTE or flat(q[1]) not in flat(claim):
        out.append(
            f"{rid}'s REFUTED in verify/{rid}.md quotes no line of the claim "
            '(`Claim: "<its words>"`)'
        )
    if not re.search(r"(?m)^\W*Mutant run:.*\bexit=[1-9]", text):
        out.append(
            f"{rid}'s REFUTED in verify/{rid}.md shows no mutant run that fails "
            "(`Mutant run: <command> exit=<non-zero>`): a test that passes on code "
            "made to match the claim cannot refute it"
        )
    return out


def declined_fails(
    d: pathlib.Path, row: Disposition, ids: Mapping[str, str]
) -> list[str]:
    """Return why a declined finding's basis does not decline it."""
    r, basis = row.rid, row.basis
    if row.verdict == "UPHELD":
        return [f"{r} is declined, but verify/{r}.md upheld it with a test"]
    sids = matches(r"\bS\d+\b", basis)
    if re.search(r"\bU\d+\b", basis) or (sids and set(sids) <= ids.keys()):
        return []
    if row.verdict == "REFUTED":
        return refuted_gaps(d, r, row.claim)
    gone = [s for s in sids if s not in ids]
    return [f"{r} is declined on {s}, which is not in SETTLED" for s in gone] + [
        (
            f"{r} is declined on '{basis[:60]}': the basis is a user ruling U<n>, a "
            f"SETTLED row S<n>, or a REFUTED verdict — run "
            f"`decision_check.py {d} --verifier {r} --sha <commit>`"
        )
    ]


def row_fails(d: pathlib.Path, row: Disposition, ids: Mapping[str, str]) -> list[str]:
    """Return the failures of one Dispositions row."""
    r, given = row.rid, row.given
    # `applied (upholds S<n>, …)`: the fix holds those rows, which stay in SETTLED
    m = re.fullmatch(
        r"(applied|declined|re-opened)"
        r"(?:\s*\(upholds\s+(S\d+(?:\s*,\s*S\d+)*)\))?",
        given,
        re.IGNORECASE,
    )
    upheld = set(matches(r"S\d+", m[2].upper())) if m and m[2] else set[str]()
    if not m or (upheld and m[1].lower() != "applied"):
        return [
            (
                f"{r}: disposition '{given}' is not applied, applied (upholds S<n>), "
                "declined or re-opened"
            )
        ]
    how = m[1].lower()
    fails = [f"{r} upholds {s}, which is not in SETTLED" for s in upheld - ids.keys()]
    if how == "declined":
        return fails + declined_fails(d, row, ids)
    fails.extend(
        f"{r} is {how} against {sid}, which is still in SETTLED"
        for sid in matches(r"\bS\d+\b", row.claim + " " + row.basis)
        if sid in ids and sid not in upheld
    )
    return fails


def dispositions(
    d: pathlib.Path, index: str, rung: str, ids: Mapping[str, str]
) -> list[str]:
    """Return the failures of the Dispositions table against 00-seams.md's findings."""
    seams = d / "00-seams.md"
    if not seams.exists():
        return []
    found = findings(seams.read_text(errors="replace"))
    # a round with no arbiter — a review round run S-shaped under an M route — keeps
    # them in its index (live: two such rounds)
    holder = d / "00-arbiter.md"
    if rung == "S" or not holder.exists():
        holder = d / "00-index.md"
    text = index if holder.name == "00-index.md" else holder.read_text(errors="replace")
    body = section(text, "Dispositions")
    if body is None:
        return [
            (
                f"{holder.name} has no Dispositions table for 00-seams.md's "
                f"{len(found)} findings"
            )
        ]
    table: dict[str, tuple[str, str]] = {}
    for cells in rows(body):
        if re.fullmatch(r"\**R\d+\**", cells[0]) and len(cells) >= DISPOSITION_CELLS:
            table[cells[0].strip("*")] = (cells[1].strip("* "), cells[2])
    fails = [
        f"{r} has no disposition in {holder.name}" for r in found if r not in table
    ]
    for r, (given, basis) in table.items():
        row = Disposition(r, given, basis, found.get(r, ""), verdict(d, r))
        fails += row_fails(d, row, ids)
    return fails


def changed_files(repo: str, span: str) -> tuple[list[str] | None, str]:
    """Return the files `git diff --name-only <span>` lists in repo, or None and why."""
    r = subprocess.run(
        [shutil.which("git") or "git", "-C", repo, "diff", "--name-only", "-z", span],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode:
        return None, (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[0]
    return [f for f in r.stdout.split("\0") if f], ""


def exempt(path: str) -> bool:
    """Return whether a review need not read path: a test, recording, doc, lockfile."""
    *dirs, name = path.split("/")
    return bool(EXEMPT_DIRS & {d.lower() for d in dirs}) or bool(
        EXEMPT_NAME.fullmatch(name)
    )


def unlabelled(
    files: Sequence[str], body: str, span: str
) -> tuple[list[str], list[str]]:
    """Return the failures of the Coverage rows of files, and the files Not read."""
    labels = {
        c[0].strip("`* ").removeprefix("./"): c[1].strip("`* ")
        for c in rows(body)
        if len(c) >= COVERAGE_CELLS
    }
    fails: list[str] = []
    unread: list[str] = []
    for f in (f for f in files if not exempt(f)):
        label = labels.get(f)
        if label is None:
            fails.append(
                f"{f} changed in {span} and has no Coverage row: Read in full, Diff "
                "read or Not read (F104)"
            )
        elif label not in LABELS:
            fails.append(
                f"{f}: '{label}' is not Read in full, Diff read or Not read (F104)"
            )
        elif label == "Not read":
            unread.append(f)
    return fails, unread


def review_coverage(index: str, repo: str) -> list[str]:
    """Return the failures of a review's Coverage section; [] for no review (F104).

    Each changed file but the exempt is labelled, and the verdict says unfinished while
    a file is Not read or no probe ran.
    """
    m = REVIEW.search(index)
    if not m:
        return []
    span = m[1]
    body = section(index, "Coverage")
    if body is None:
        return [
            (
                "the index records a review (`**Review**`) and has no Coverage "
                "section: list each changed file as Read in full, Diff read or Not "
                "read, and each probe run with its exit code (F104)"
            )
        ]
    files, why = changed_files(repo, span)
    if files is None:
        return [
            (
                "cannot list the files the review changed (`git diff --name-only "
                f"{span}` in {repo}: {why}): fetch both commits, or pass --repo (F104)"
            )
        ]
    fails, unread = unlabelled(files, body, span)
    verdict = VERDICT.search(index)
    if not verdict:
        return [*fails, "the review states no verdict (`> **Verdict**: …`) (F104)"]
    if "unfinished" in verdict[1].lower():
        return fails
    if unread:
        n = len(unread)
        fails.append(
            f"{n} file{'' if n == 1 else 's'} Not read ({', '.join(unread)}): the "
            "verdict says unfinished until each is read (F104)"
        )
    if not any(PROBE.search(line) for line in body.splitlines()):
        fails.append(
            "no probe run with its exit code in the Coverage section (`- `<command>` "
            "exit=<n>`): the verdict says unfinished until one has run (F104)"
        )
    return fails


def sin_finding(report: pathlib.Path, fid: str) -> str | None:
    """Return a seven-sins finding as a claim: where, what, the evidence.

    No severity or owner.
    """
    for cells in rows(report.read_text(errors="replace")):
        if len(cells) >= SIN_CELLS and cells[0].strip("* ") == fid:
            return f"Where: {cells[3]}\n\n{cells[4]}\n\nEvidence given: {cells[6]}"
    return None


def write_verifier(
    d: pathlib.Path, rid: str, sha: str, report: pathlib.Path | None = None
) -> int:
    """Write verify/<rid>.prompt.md, the claim-only verifier's prompt; exit status."""
    source = report or d / "00-seams.md"
    if not source.exists():
        claim = None
    elif report:
        claim = sin_finding(report, rid)
    else:
        claim = findings(source.read_text(errors="replace")).get(rid)
    if not claim:
        print(f"no finding {rid} in {source}", file=sys.stderr)
        return 2
    out = d / "verify" / f"{rid}.prompt.md"
    out.parent.mkdir(exist_ok=True)
    _ = out.write_text(
        f"You decide one claim about this repository at commit {sha}, with a test. "
        "Work in a fresh worktree of that commit "
        f"(`git worktree add --detach <scratch-dir> {sha}`); read the code, never a "
        "planning file.\n\nThe claim:\n\n"
        + claim.strip()
        + "\n\nWrite a test in the project's own framework that fails at this commit "
        "exactly when the claim is true, and run it. A test that passes proves nothing "
        "until it fails where the claim holds: then change the code in the scratch "
        "worktree so the claim becomes true (the mutant), run the test again, and "
        "expect it to fail. Then write "
        f"`{d.resolve()}/verify/{rid}.md`: first line `Verdict: UPHELD` (the test "
        "demonstrates the claim), `Verdict: REFUTED` (it passes here and fails on the "
        "mutant) or `Verdict: NO-TEST` (no test can decide it — say why); then, "
        'one per line, `Claim: "<the claim\'s words your test checks, verbatim>"`, '
        "`Test: <path>` with its text, `Run: <command> exit=<status>` with its output, "
        "and for REFUTED `Mutant: <the change>` and `Mutant run: <command> "
        "exit=<status>`. A REFUTED without a failing mutant run does not count. Judge "
        "the claim, not who made it. Reply with the verdict line and the path.\n"
    )
    print(out)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Check the ledger, or with --verifier write a verifier's prompt; exit status."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    _ = ap.add_argument("decisions_dir")
    _ = ap.add_argument("--rung", choices=("S", "M", "L"), default="M")
    _ = ap.add_argument("--legacy", action="store_true")
    _ = ap.add_argument("--verifier", metavar="R<n>")
    _ = ap.add_argument("--sha")
    _ = ap.add_argument(
        "--from", dest="report", metavar="SIN_REPORT", type=pathlib.Path
    )
    _ = ap.add_argument(
        "--repo", help="where a review's range is read (default: the decisions dir's)"
    )
    a = ap.parse_args(argv, namespace=_Args())
    d = pathlib.Path(a.decisions_dir)
    if a.verifier:
        if not a.sha:
            ap.error("--verifier needs --sha")
        return write_verifier(d, a.verifier, a.sha, a.report)
    index_path = d / "00-index.md"
    if not index_path.exists():
        print(f"no index at {index_path}", file=sys.stderr)
        return 2
    index = index_path.read_text(errors="replace")
    ids, fails = settled(index)
    fails += dimensions(index)
    fails += [] if a.legacy else decisions(index)
    fails += dispositions(d, index, a.rung, ids)
    fails += review_coverage(index, a.repo or str(d))
    for f in fails:
        print(f"FAIL  {f}")
    print(f"decision_check: {len(fails)} failure(s) in {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
