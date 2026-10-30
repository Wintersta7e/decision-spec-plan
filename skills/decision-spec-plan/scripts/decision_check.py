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
L): applied, declined or re-opened. A declined finding's basis is a user ruling `U<n>`, a SETTLED
row `S<n>`, or `verify/R<n>.md` whose first line is `Verdict: REFUTED` — "known limitation" or
"default" is no basis; a finding with `Verdict: UPHELD` is never declined. A finding applied or
re-opened that cites a SETTLED row takes that row out of SETTLED.

With `--verifier R<n> --sha <commit>` it writes `verify/R<n>.prompt.md`: the claim-only verifier's
whole prompt — the finding's text, the commit, the instruction to decide it with a test — and
nothing else: no SETTLED list, no lead rationale, no reviewer name. Dispatch it unchanged, as an
agent named `verify-<id>` (the hook refuses an edited one) or to the second model. With
`--from <sin report>` the directory is a seven-sins run dir and the claim is that report's
finding <id> (`GRE-1`): its place, text and evidence, without severity or owner — a disputed sins
finding is settled this way, not by debate (sins/lead.md).

Usage:
    decision_check.py <decisions-dir> [--rung S|M|L]
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
OWNER = re.compile(r"\b(?:[UADS]\d+|Ask\d+)\b|N/A:\s*\S+\s+\S+")
PATH = re.compile(r"`([^`\s]+?\.[A-Za-z0-9]+)(?::[\d,–-]+)?`")
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


def findings(seams):
    """{R-number: its text} — each finding runs to the next finding or heading."""
    marks = list(FINDING.finditer(seams))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(seams)
        # a heading after the finding's first line ends it; its own `### **R3**` does not
        out.setdefault(
            f"R{m.group(1) or m.group(2)}", seams[m.start() : end].split("\n#")[0]
        )
    return out


def verdict(d, rid):
    path = d / "verify" / f"{rid}.md"
    if not path.exists():
        return None
    first = path.read_text(errors="replace").strip().partition("\n")[0]
    m = re.fullmatch(r"\W*Verdict:\W*(UPHELD|REFUTED|NO-TEST)\W*", first)
    return m.group(1) if m else None


def dispositions(d, index, rung, ids):
    seams = d / "00-seams.md"
    if not seams.exists():
        return []
    found = findings(seams.read_text(errors="replace"))
    holder = d / ("00-index.md" if rung == "S" else "00-arbiter.md")
    text = index if rung == "S" else (holder.read_text() if holder.exists() else "")
    body = section(text, "Dispositions")
    if body is None:
        return [
            f"{holder.name} has no Dispositions table for 00-seams.md's {len(found)} findings"
        ]
    table = {}
    for cells in rows(body):
        if re.fullmatch(r"\**R\d+\**", cells[0]) and len(cells) >= 3:
            table[cells[0].strip("*")] = (cells[1].strip("* ").lower(), cells[2])
    fails = [
        f"{r} has no disposition in {holder.name}" for r in found if r not in table
    ]
    for r, (how, basis) in table.items():
        v = verdict(d, r)
        if how not in ("applied", "declined", "re-opened"):
            fails.append(
                f"{r}: disposition '{how}' is not applied, declined or re-opened"
            )
        elif how == "declined":
            if v == "UPHELD":
                fails.append(
                    f"{r} is declined, but verify/{r}.md upheld it with a test"
                )
            elif v != "REFUTED" and not re.search(r"\b(?:U\d+|S\d+)\b", basis):
                fails.append(
                    f"{r} is declined on '{basis[:60]}': the basis is a user ruling U<n>, a "
                    f"SETTLED row S<n>, or a REFUTED verdict — run "
                    f"`decision_check.py {d} --verifier {r} --sha <commit>`"
                )
        else:
            for sid in re.findall(r"\bS\d+\b", found.get(r, "") + " " + basis):
                if sid in ids:
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
        "when the claim is true, and run it. Then write "
        f"`{d.resolve()}/verify/{rid}.md`: first line `Verdict: UPHELD` (the test demonstrates "
        "the claim), `Verdict: REFUTED` (it shows the claim false) or `Verdict: NO-TEST` (no "
        "test can decide it — say why); then the test's path and text, the command and its "
        "output. Judge the claim, not who made it. Reply with the verdict line and the path.\n"
    )
    print(out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("decisions_dir")
    ap.add_argument("--rung", choices=("S", "M", "L"), default="M")
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
    fails += dispositions(d, index, a.rung, ids)
    for f in fails:
        print(f"FAIL  {f}")
    print(f"decision_check: {len(fails)} failure(s) in {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
