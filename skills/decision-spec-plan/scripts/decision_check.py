#!/usr/bin/env python3
"""Check a decision round's ledger: typed SETTLED rows, requirement dimensions, dispositions.

<decisions-dir> is the round's `decisions/phase<P>`. Every check is a failure measured somewhere:

SETTLED — every row of the index's SETTLED tables (not "Measured numbers") opens with an id `S<n>`,
and its source is a ruling: a user or arbiter ruling (`U<n>`, `A<n>`), a decision (`D<n>`), an ask
(`Ask<n>`), a document (a `.md` path: decision, spec, handoff) or the user's words with no path. A
row whose source is only code `file:lines` records what today's code does; it read as a ruling and
an S build kept the defect it described (F86). Move it to "Today's code — open to change".

Requirement dimensions — the index's table names each of the nine dimensions (actors and
workflows, data identity, ownership and round-trip, business rules, state machines, integrations
and events, validation and exceptions, background jobs, security and privacy) with an owner: a
ruling or decision id, an ask, an `S<n>` row, or `N/A: <reason>`. Every arm of one clean room
missed a state rule no dimension named (failure-modes F94).

Dispositions — once `00-seams.md` exists (the seam review at M and L, the §1e review at S), every
finding `R<n>` in it has a row in the Dispositions table (the index's at S, the arbiter's at M and
L, the index's in a round with no arbiter): applied, `applied (upholds S<n>)`, declined or
re-opened. A declined finding's basis is a user ruling `U<n>`, a SETTLED row `S<n>`, or
`verify/R<n>.md` whose first line is `Verdict: REFUTED`, with a `Claim:` line quoting the finding
and a `Mutant run:` line ending its test's run on code made to match the claim in a non-zero
`exit=` — "known limitation" or "default" is no basis; a finding with `Verdict: UPHELD` is never
declined. A finding applied or re-opened that cites
a SETTLED row takes that row out of SETTLED, unless the fix upholds it: findings that upheld a row
were relabelled "declined" to pass, and the record lied (F98).

With `--verifier R<n> --sha <commit>` it writes `verify/R<n>.prompt.md`: the claim-only verifier's
whole prompt — the finding's text, the commit, the instruction to decide it with a test — and
nothing else: no SETTLED list, no lead rationale, no reviewer name. Dispatch it unchanged, as an
agent named `verify-<id>` (the hook refuses an edited one) or to the second model. With
`--from <sin report>` the directory is a seven-sins run dir and the claim is that report's
finding <id> (`GRE-1`): its place, text and evidence, without severity or owner — a disputed sins
finding is settled this way, not by debate (sins/lead.md).

Decisions — each row of the index's decisions table names, in its Serves column, the ask (`Ask<n>`)
or user ruling (`U<n>`) it serves, or is marked `backlog`; past six live decisions the index records
the user's triage as `> **Triage**: U<n>`. A review round grew to 14 mostly-infrastructure decisions
priced 20M, was approved, and a minute later the user disliked its direction (F101). `--legacy`
skips this check: the route's hook passes it for a phase bound before the check existed.

Usage:
    decision_check.py <decisions-dir> [--rung S|M|L] [--legacy]
    decision_check.py <decisions-dir> --verifier R<n> --sha <commit>
    decision_check.py <run-dir> --verifier <finding id> --sha <commit> --from <run-dir>/<sin>.md

Exit 0 when every check holds, 1 with each failure listed, 2 when the index is missing.
"""

import argparse
import pathlib
import re
import sys

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
# A finding opens a line with its id — `**R<n>`, or a bare `R<n>` and a dash, colon or bracket —
# after a list marker, a numbered list's `1.` or a heading's `#`s. A wrapped line that begins
# "R1's keying …" is no new finding.
FINDING = re.compile(
    r"^[ \t]*(?:[-*+>|][ \t]*|\d+[.)][ \t]*|#{1,6}[ \t]*)?"
    r"(?:\*\*R(\d+)\b|R(\d+)\b(?=\**[ \t]*[—–:(-]))",
    re.MULTILINE,
)


def section(text, title):
    """The body of the first `## <title>…` section, up to the next `## ` heading."""
    m = re.search(
        rf"^## {title}[^\n]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    return m.group(1) if m else None


def rows(body):
    """The cells of each table row that is neither a header nor a separator."""
    lines = body.splitlines()
    out = []
    for i, line in enumerate(lines):
        if not line.startswith("|") or re.fullmatch(r"[|\s:-]+", line):
            continue
        if i + 1 < len(lines) and re.fullmatch(r"[|\s:-]+", lines[i + 1]):
            continue
        # GFM's `\|` is a pipe inside a cell, not a cell border
        cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        out.append([c.strip().replace("\\|", "|") for c in cells])
    return out


def settled(index):
    """{S-id: source} of the SETTLED rows, and the failures."""
    body = section(index, "SETTLED")
    if body is None:
        return {}, ["the index has no SETTLED section"]
    body = re.split(r"^### Measured numbers", body, flags=re.MULTILINE)[0]
    found, fails = {}, []
    for cells in rows(body):
        sid = re.fullmatch(r"\**(S\d+)\**", cells[0])
        if not sid:
            fails.append(f"SETTLED row without an S<n> id: {' | '.join(cells)[:120]}")
            continue
        source = cells[-1]
        paths = PATH.findall(source)
        if (
            paths
            and not RULING_ID.search(source)
            and not any(p.endswith(".md") for p in paths)
        ):
            fails.append(
                f"{sid.group(1)} cites only code ({source[:80]}): that is what today's code "
                "does, not a ruling — move it to Today's code, open to change (F86)"
            )
        found[sid.group(1)] = source
    return found, fails


def dimensions(index):
    body = section(index, "Requirement dimensions")
    if body is None:
        return ["the index has no Requirement dimensions table"]
    table = {c[0].strip("* ").lower(): c[-1] for c in rows(body) if len(c) >= 2}
    fails = []
    for dim in DIMENSIONS:
        owner = next((v for k, v in table.items() if k.startswith(dim)), None)
        if owner is None:
            fails.append(f"dimension '{dim}' has no row")
        elif not OWNER.search(owner):
            fails.append(
                f"dimension '{dim}' has no owner (a ruling or decision id, an ask, an S<n> "
                f"row, or 'N/A: <reason>'): {owner[:80]}"
            )
    return fails


def decisions(index):
    """Each decision names the ask or user ruling it serves, or waits in the backlog; past
    TRIAGE live decisions the index records the user's triage."""
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
        [],
    )
    if "serves" not in header:
        return [
            (
                "the decisions table has no Serves column: each decision names the Ask<n> or "
                "U<n> it serves, or `backlog` (F101)"
            )
        ]
    col = header.index("serves")
    fails, live = [], 0
    for cells in rows(body):
        did = re.fullmatch(r"\**(D\d+)\**", cells[0])
        if not did or col >= len(cells):
            continue
        if re.search(r"\bbacklog\b", cells[col], re.IGNORECASE):
            continue
        live += 1
        if not re.search(r"\b(?:Ask|U)\d+\b", cells[col]):
            fails.append(
                f"{did[1]} serves no ask or user ruling ({cells[col][:60] or 'empty'}): cite "
                "the Ask<n> or U<n> it serves, or mark it `backlog` (F101)"
            )
    if live > TRIAGE and not re.search(r"\*\*Triage\*\*:.*\bU\d+", index):
        fails.append(
            f"{live} decisions to rule: past {TRIAGE}, the user triages first — which to rule "
            "now, which wait in the backlog, with each one's cost — recorded as "
            "`> **Triage**: U<n>` (F101)"
        )
    return fails


def findings(seams):
    """{R-number: its text} — each finding runs to the next finding or heading. A `#` line in a
    code fence (a shell comment in a repro) or one with no space after the `#`s (`#42`) is no
    heading."""
    marks = list(FINDING.finditer(seams))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(seams)
        lines, fenced = seams[m.start() : end].split("\n"), False
        # a heading after the finding's first line ends it; its own `### **R3**` does not
        for k, line in enumerate(lines[1:], 1):
            if re.match(r"\s*(```|~~~)", line):
                fenced = not fenced
            elif not fenced and re.match(r"#{1,6}(?:\s|$)", line):
                lines = lines[:k]
                break
        out.setdefault(f"R{m.group(1) or m.group(2)}", "\n".join(lines))
    return out


def verdict(d, rid):
    path = d / "verify" / f"{rid}.md"
    if not path.exists():
        return None
    first = path.read_text(errors="replace").strip().partition("\n")[0]
    # the verifier's prompt glosses each verdict, and a verifier may copy the gloss onto the line
    m = re.match(r"\W*Verdict:\W*(UPHELD|REFUTED|NO-TEST)(?![\w-])", first)
    return m.group(1) if m else None


def refuted_gaps(d, rid, claim):
    """What a REFUTED verdict lacks to decline a finding: a quote of the claim its test checks,
    and that test failing on a mutant that makes the claim true — a test that cannot see the
    defect refutes nothing."""
    text = (d / "verify" / f"{rid}.md").read_text(errors="replace")

    def flat(s):
        return " ".join(s.split())

    out = []
    q = re.search(r"(?m)^\W*Claim:\W*(.+?)\W*$", text)
    if not q or len(flat(q[1])) < 10 or flat(q[1]) not in flat(claim):
        out.append(
            f"{rid}'s REFUTED in verify/{rid}.md quotes no line of the claim "
            '(`Claim: "<its words>"`)'
        )
    if not re.search(r"(?m)^\W*Mutant run:.*\bexit=[1-9]", text):
        out.append(
            f"{rid}'s REFUTED in verify/{rid}.md shows no mutant run that fails "
            "(`Mutant run: <command> exit=<non-zero>`): a test that passes on code made to "
            "match the claim cannot refute it"
        )
    return out


def dispositions(d, index, rung, ids):
    seams = d / "00-seams.md"
    if not seams.exists():
        return []
    found = findings(seams.read_text(errors="replace"))
    # a round with no arbiter — a review round run S-shaped under an M route — keeps them in
    # its index (live: two such rounds)
    holder = d / "00-arbiter.md"
    if rung == "S" or not holder.exists():
        holder = d / "00-index.md"
    text = index if holder.name == "00-index.md" else holder.read_text(errors="replace")
    body = section(text, "Dispositions")
    if body is None:
        return [
            f"{holder.name} has no Dispositions table for 00-seams.md's {len(found)} findings"
        ]
    table = {}
    for cells in rows(body):
        if re.fullmatch(r"\**R\d+\**", cells[0]) and len(cells) >= 3:
            table[cells[0].strip("*")] = (cells[1].strip("* "), cells[2])
    fails = [
        f"{r} has no disposition in {holder.name}" for r in found if r not in table
    ]
    for r, (given, basis) in table.items():
        v = verdict(d, r)
        # `applied (upholds S<n>, …)`: the fix holds those rows, which stay in SETTLED
        m = re.fullmatch(
            r"(applied|declined|re-opened)"
            r"(?:\s*\(upholds\s+(S\d+(?:\s*,\s*S\d+)*)\))?",
            given,
            re.IGNORECASE,
        )
        how = m and m[1].lower()
        upheld = set(re.findall(r"S\d+", m[2].upper())) if m and m[2] else set()
        if not m or (upheld and how != "applied"):
            fails.append(
                f"{r}: disposition '{given}' is not applied, applied (upholds S<n>), "
                "declined or re-opened"
            )
            continue
        fails += [
            f"{r} upholds {s}, which is not in SETTLED" for s in upheld - ids.keys()
        ]
        if how == "declined":
            if v == "UPHELD":
                fails.append(
                    f"{r} is declined, but verify/{r}.md upheld it with a test"
                )
            elif re.search(r"\bU\d+\b", basis) or (
                (sids := re.findall(r"\bS\d+\b", basis)) and set(sids) <= ids.keys()
            ):
                pass
            elif v == "REFUTED":
                fails += refuted_gaps(d, r, found.get(r, ""))
            else:
                gone = [s for s in re.findall(r"\bS\d+\b", basis) if s not in ids]
                fails += [
                    f"{r} is declined on {s}, which is not in SETTLED" for s in gone
                ]
                fails.append(
                    f"{r} is declined on '{basis[:60]}': the basis is a user ruling U<n>, a "
                    f"SETTLED row S<n>, or a REFUTED verdict — run "
                    f"`decision_check.py {d} --verifier {r} --sha <commit>`"
                )
        else:
            for sid in re.findall(r"\bS\d+\b", found.get(r, "") + " " + basis):
                if sid in ids and sid not in upheld:
                    fails.append(
                        f"{r} is {how} against {sid}, which is still in SETTLED"
                    )
    return fails


def sin_finding(report, fid):
    """A seven-sins report's finding as a claim: where, what, the evidence — no severity or owner."""
    for cells in rows(report.read_text(errors="replace")):
        if len(cells) >= 7 and cells[0].strip("* ") == fid:
            return f"Where: {cells[3]}\n\n{cells[4]}\n\nEvidence given: {cells[6]}"
    return None


def write_verifier(d, rid, sha, report=None):
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
    out.write_text(
        f"You decide one claim about this repository at commit {sha}, with a test. Work in a "
        f"fresh worktree of that commit (`git worktree add --detach <scratch-dir> {sha}`); read "
        "the code, never a planning file.\n\nThe claim:\n\n"
        + claim.strip()
        + "\n\nWrite a test in the project's own framework that fails at this commit exactly "
        "when the claim is true, and run it. A test that passes proves nothing until it fails "
        "where the claim holds: then change the code in the scratch worktree so the claim "
        "becomes true (the mutant), run the test again, and expect it to fail. Then write "
        f"`{d.resolve()}/verify/{rid}.md`: first line `Verdict: UPHELD` (the test demonstrates "
        "the claim), `Verdict: REFUTED` (it passes here and fails on the mutant) or "
        "`Verdict: NO-TEST` (no test can decide it — say why); then, one per line, "
        '`Claim: "<the claim\'s words your test checks, verbatim>"`, `Test: <path>` with its '
        "text, `Run: <command> exit=<status>` with its output, and for REFUTED `Mutant: <the "
        "change>` and `Mutant run: <command> exit=<status>`. A REFUTED without a failing "
        "mutant run does not count. Judge the claim, not who made it. Reply with the verdict "
        "line and the path.\n"
    )
    print(out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("decisions_dir")
    ap.add_argument("--rung", choices=("S", "M", "L"), default="M")
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--verifier", metavar="R<n>")
    ap.add_argument("--sha")
    ap.add_argument("--from", dest="report", metavar="SIN_REPORT", type=pathlib.Path)
    a = ap.parse_args(argv)
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
    for f in fails:
        print(f"FAIL  {f}")
    print(f"decision_check: {len(fails)} failure(s) in {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
