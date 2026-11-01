#!/usr/bin/env python3
"""Derive a phase's acceptance-criterion ids from the spec, and check that the plans map each one.

Spec (the Stage 2 gate). In each section file, take the LAST heading of level 1-3 whose text
contains "cceptance", up to the next heading of level 1-3 (a `#` line inside a code fence is not a
heading). A criterion is defined by a line that
opens -- after an optional `N.`, `-` or `*` marker -- with bold `**AC-P<P>-<NN>-<n>` (backticks
allowed), or by a table row whose first cell is that id. An ordered-list item that opens with `**`
and carries no id is counted by its list number and reported. A regex over full ids anywhere in
the file is NOT the method: one found 236 of 253 because a section listed its criteria without ids.

Plans (the Stage 4 gate, with --plans). A mapping row is a table row whose first cell names
criteria, in a table whose header's second cell starts with "Task". Compact forms expand:
`AC-P4-47-13, -14, -16` and `AC-P4-38-1 … -24`. A row maps its ids when its task cell names a
task number and its test cell -- the first column after Task whose header names a test, else the
third -- holds a backticked test path (`tests/x.rs`, `x.test.ts`, `file::test`; --test-re; a
path in a notes column is no test), or a later cell says "manual" beside the ruling that allows it (`manual (R199)`;
--ruling-re, looked for after the cell's AC- ids are stripped). Every number the task cell names
outside backticks must be a `## Task N` or `### Task N` heading in that plan, else "task not
found"; backticked text is a reference (`p4-43`), struck text (`~~14~~`) is withdrawn and a
ruling id (`R242`, --ruling-re) cites a ruling -- none is a task; a range (`9–13`) names every
number in it. Every criterion the spec defines
must be mapped by some plan; every manual one is printed with its ruling, for the lead to read.

Index files (`00-*.md`, `p<N>-00-*.md`) are skipped: an index is not a plan.

Usage:
    criteria_check.py <spec-dir> --phase P --sections 38-48 [--plans <plans-dir>] [--glob '*.md']
        [--list] [--test-re RE] [--ruling-re RE] [--emit-register]

Section NN is the file `<spec-dir>/<NN>-<slug>.md` (leading zeros allowed: `07-…` is section 7).
--test-re and --ruling-re replace the defaults their help shows.

--emit-register prints the register's per-section table (count and ids as ranges) after the spec
check, for the register folder to paste rather than re-derive.

Exit 0 when every check holds, 1 on any problem, 2 when a section file is missing, no criterion
was found, or --plans matched no plan.
"""

import argparse
import pathlib
import re
import sys

HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
TASK_HEADING = re.compile(r"^#{2,3} Task (\d+)", re.MULTILINE)
SPAN = re.compile(r"`([^`]*)`")
AC_ID = re.compile(r"AC-[A-Za-z0-9-]+")
MANUAL = re.compile(r"\bmanual\b", re.IGNORECASE)
# test_check.py's test paths too: colocated `test_*.py`, `*Test.java`, `*Tests.cs`
TEST_RE = (
    r"(^|/)(tests?|spec|__tests__)/|[._-](test|spec)\.|_test\.|::"
    r"|(^|/)test_[^/]*\.py\b|Tests?\.(java|kt|cs)\b"
)
RULING_RE = r"\b(?:U|R|[A-Z]?A)\d+\b"
TOKEN = re.compile(
    r"AC-P(\d+)-(\d+)-(\d+)"  # a full id
    r"|(?:…|\.\.\.|–)\s*`?(?:AC-P\d+-\d+-|-)?(\d+)"  # the end of a range
    r"|(?:,|\band\b)\s*`?-(\d+)"  # a compact continuation
)
STRUCK = re.compile(r"~~.*?~~")
TASK_RANGE = re.compile(r"(?<![\w-])(\d+)\s*[–-]\s*(\d+)(?![\w-])")


def task_numbers(cell, ruling_re):
    """The task numbers a task cell names. Backticked text is a reference, struck text is
    withdrawn and a ruling id (`R242`) cites a ruling -- none is a task. A range names each
    number in it, so a missing middle task is caught."""
    text = ruling_re.sub("", STRUCK.sub("", SPAN.sub("", cell)))
    nums = set()
    for lo, hi in TASK_RANGE.findall(text):
        nums.update(range(int(lo), int(hi) + 1))
    return nums | {int(n) for n in re.findall(r"\d+", TASK_RANGE.sub("", text))}


def headings(lines):
    """(index, HEADING match) of every heading outside a code fence: a `# comment` in a fenced
    shell block is not a heading."""
    fenced = False
    for i, line in enumerate(lines):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and (m := HEADING.match(line)):
            yield i, m


def acceptance_block(text):
    lines = text.split("\n")
    found = list(headings(lines))
    starts = [i for i, m in found if "cceptance" in m.group(2)]
    if not starts:
        return None
    end = next((i for i, _ in found if i > starts[-1]), len(lines))
    return lines[starts[-1] + 1 : end]


def definitions(block, p, nn):
    ided = re.compile(
        rf"^(?:(?:\d+[a-z]?\.|[-*])\s+)?(?:\*\*`?|\|\s*`?\*{{0,2}}`?)"
        rf"AC-P{p}-{nn}-(\d+)([a-z]?(?:-[A-Za-z]\w*)*)"
    )
    idless = re.compile(r"^(\d+)\.\s+\*\*(?!`?AC-)")
    nums, suffixed, implied = [], [], 0
    for line in block:
        m = ided.match(line)
        if m and m.group(2):
            suffixed.append(m.group(1) + m.group(2))
        elif m:
            nums.append(int(m.group(1)))
        elif m := idless.match(line):
            nums.append(int(m.group(1)))
            implied += 1
    return nums, suffixed, implied


def expand(cell, p):
    """The (section, n) ids of phase p that one table cell names, compact forms expanded."""
    out, cur, last = set(), None, 0
    for m in TOKEN.finditer(cell):
        if m.group(1):
            cur, last = (int(m.group(1)), int(m.group(2))), int(m.group(3))
            if cur[0] == p:
                out.add((cur[1], last))
        elif cur and cur[0] == p and m.group(4):
            end = int(m.group(4))
            out.update((cur[1], n) for n in range(last + 1, end + 1))
            last = end
        elif cur and cur[0] == p and m.group(5):
            last = int(m.group(5))
            out.add((cur[1], last))
    return out


def mappings(text, p, test_re, ruling_re):
    """(id, task, test, rulings) for every mapping row in one plan. task is None when the task
    cell names no number, False when a number it names has no `## Task N` heading in this plan;
    rulings are the ruling ids beside "manual" when no test path is given."""
    tasks = {
        int(n) for n in TASK_HEADING.findall(re.sub(r"(?ms)^```.*?^```", "", text))
    }
    out, header = [], None
    for line in text.split("\n"):
        if not line.startswith("|"):
            header = None
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if header is None:
            header = c
            # The test cell of `| Id | Task | Test file |`; more columns may follow it.
            col = next((k for k, h in enumerate(c) if k > 1 and "test" in h.lower()), 2)
            continue
        if len(header) < 3 or not header[1].lower().startswith("task"):
            continue
        named = task_numbers(c[1], ruling_re) if len(c) > 1 else set()
        task = named <= tasks if named else None
        test = col < len(c) and any(test_re.search(s) for s in SPAN.findall(c[col]))
        rulings = ()
        if not test:
            rulings = tuple(
                m.group(0)
                for x in c[2:]
                if MANUAL.search(x)
                for m in ruling_re.finditer(AC_ID.sub("", x))
            )
        out += [(i, task, test, rulings) for i in expand(c[0], p)]
    return out


def register(table, p):
    """The register's table: per section the count and the ids, as ranges `expand` reads back."""
    print("\n| § | Criteria | Ids |\n|---|---|---|")
    for nn, nums, suffixed in table:
        runs, ids = [], sorted(set(nums))
        for n in ids:
            if runs and n == runs[-1][1] + 1:
                runs[-1][1] = n
            else:
                runs.append([n, n])
        parts = [
            (f"`AC-P{p}-{nn}-{lo}`" if i == 0 else f"`-{lo}`")
            + (f" … `-{hi}`" if hi > lo else "")
            for i, (lo, hi) in enumerate(runs)
        ] + [f"`AC-P{p}-{nn}-{s}`" for s in suffixed]
        print(f"| §{nn} | {len(nums) + len(suffixed)} | {', '.join(parts)} |")
    print(f"| **Total** | **{sum(len(n) + len(s) for _, n, s in table)}** | |")


def check_spec(spec_dir, p, secs, table=None):
    defined, total, problems, missing = set(), 0, 0, False
    print(f"{'section':<8} {'criteria':>8} {'max':>4}  problems")
    print("-" * 72)
    for nn in secs:
        files = [
            f for f in sorted(spec_dir.glob("*.md")) if re.match(rf"0*{nn}-", f.name)
        ]
        nums, suffixed, implied = [], [], 0
        for f in files:
            block = acceptance_block(f.read_text(errors="replace"))
            if block is not None:
                n, s, i = definitions(block, p, nn)
                nums, suffixed, implied = nums + n, suffixed + s, implied + i
        top = max(nums, default=0)
        gaps = sorted(set(range(1, top + 1)) - set(nums))
        dups = sorted({n for n in nums if nums.count(n) > 1})
        issues = []
        if not files:
            issues.append("no section file")
            missing = True
        elif not nums:
            issues.append("no criteria found")
        if gaps:
            issues.append(f"gaps {gaps}")
        if dups:
            issues.append(f"duplicates {dups}")
        if suffixed:
            issues.append(f"suffixed {suffixed}")
        if implied:
            issues.append(f"{implied} items carry no id")
        problems += len(issues)
        total += len(nums) + len(suffixed)
        defined |= {(nn, n) for n in nums}
        if table is not None:
            table.append((nn, nums, suffixed))
        print(
            f"§{nn:<7} {len(nums) + len(suffixed):>8} {top:>4}  {'; '.join(issues) or 'ok'}"
        )
    print(f"\n{total} criteria defined in {len(secs)} sections, {problems} problems")
    return defined, problems, missing


def check_plans(plans, p, defined, show_all, test_re, ruling_re):
    rows = [
        (f.name, *r)
        for f in plans
        for r in mappings(f.read_text(errors="replace"), p, test_re, ruling_re)
    ]
    named = {r[1] for r in rows}
    tasked = {r[1] for r in rows if r[2] is not None}
    lost = {r[1] for r in rows if r[2] is False}
    mapped = {r[1] for r in rows if r[2] is not None and (r[3] or r[4])}
    tested = {r[1] for r in rows if r[2] is not None and r[3]}
    whole = {r[1] for r in rows if r[2] and (r[3] or r[4])}
    manual, untested = {}, defined - tested
    for plan, i, task, _, rulings in rows:
        if i in untested and task is not None and rulings:
            manual.setdefault(i, {})[f"{', '.join(rulings)} ({plan})"] = None
    groups = [
        ("UNMAPPED", sorted(defined - named)),
        ("NO TASK", sorted((defined & named) - tasked)),
        ("TASK NOT FOUND", sorted(defined & lost)),
        ("NO TEST FILE", sorted((defined & tasked) - mapped)),
        ("NOT DEFINED", sorted(named - defined)),
    ]
    print(
        f"\n{len(plans)} plans scanned; {len(defined & whole)} of {len(defined)} criteria mapped"
        f" to a task and a test ({len(manual)} manual); "
        + "; ".join(f"{len(ids)} {label.lower()}" for label, ids in groups)
    )
    for label, ids in groups:
        if ids and (show_all or len(ids) <= 20):
            print(f"  {label}: {', '.join(f'AC-P{p}-{s}-{n}' for s, n in ids)}")
    for (s, n), cites in sorted(manual.items()):
        print(f"  MANUAL: AC-P{p}-{s}-{n} — {'; '.join(cites)}")
    return sum(len(ids) for _, ids in groups)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("spec_dir")
    ap.add_argument("--phase", type=int, required=True)
    ap.add_argument("--sections", required=True, help="e.g. 38-48 or 38,40-41")
    ap.add_argument("--plans")
    ap.add_argument("--glob", default="*.md")
    ap.add_argument("--list", action="store_true")
    ap.add_argument(
        "--emit-register",
        action="store_true",
        help="print the register's per-section table for the register folder to paste",
    )
    ap.add_argument(
        "--test-re",
        default=TEST_RE,
        help="a backticked test path must match this (default: %(default)s)",
    )
    ap.add_argument(
        "--ruling-re",
        default=RULING_RE,
        help="a manual cell must cite a ruling id matching this (default: %(default)s)",
    )
    a = ap.parse_args()
    secs = []
    for part in a.sections.split(","):
        lo, _, hi = part.partition("-")
        secs += range(int(lo), int(hi or lo) + 1)

    table = [] if a.emit_register else None
    defined, problems, missing = check_spec(
        pathlib.Path(a.spec_dir), a.phase, secs, table
    )
    if missing or not defined:
        return 2
    if table is not None:
        register(table, a.phase)
    if a.plans:
        plans = [
            f
            for f in sorted(pathlib.Path(a.plans).glob(a.glob))
            if not re.match(r"(p\d+-)?00-", f.name)
        ]
        if not plans:
            print(f"no plans matched {a.glob} in {a.plans}")
            return 2
        problems += check_plans(
            plans,
            a.phase,
            defined,
            a.list,
            re.compile(a.test_re),
            re.compile(a.ruling_re),
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
