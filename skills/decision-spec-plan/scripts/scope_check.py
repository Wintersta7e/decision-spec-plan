#!/usr/bin/env python3
"""Find plans that promise files no task creates.

A plan opens with a File structure section listing the files it will create. A plan whose author
ran out of output before the last task keeps that table and loses the tasks — the table still names
the file, so the gap is invisible unless the two are compared. That is how ten of 21 plans in one
project came to be missing their entire UI.

A promised file is UNIMPLEMENTED when its path appears at most once in its plan (only in the table)
and no other plan mentions it more than once. A mention is the whole path, or in a plan whose table
lists the file the bare name standing alone: `data.rs` does not mention `a.rs`, nor `ui/mod.rs`
`src/mod.rs`.

Bare filenames are resolved against the nearest preceding sub-heading that names a directory in
backticks, because plans group them that way:

    ### Rust — `core/src/session/`
    | `segment.rs` | The segment state machine |

The File structure section ends at the first `## Task`, `## Tasks`, `## Global` or `## Interfaces`
heading (either `##` or `###` depth), or at the end of a plan cut off after its table.

With `--waves <plan-index>` it checks the wave order instead: every file two plans of one wave
both list in their File structure sections. Their lanes run in parallel worktrees, so each edits the
file without the other's change and the integrator meets the collision — three lanes of one wave
edited the same four UI files, and of the seven seam defects that left, the integrator fixed four.
Plans sharing a file go in different waves. A `Depends on` cell opening with `all` waits for every
plan of the waves it names (`all of wave 1`), else of every earlier wave.

A file is a backticked path with one of `--ext`'s extensions, a build file that has none
(`Makefile`, `Dockerfile`, …) or a dotfile (`.gitignore`).

With `--asks <decision-index> [<arbiter>]` it checks the scope fence: every file row of every File
structure section must cite an ask (`Ask<n>`, a row of the index's asks table) or a user ruling
(`U<n>`) that one of those files defines, and none may list a file the index's `Do not touch`
section names. Unasked changes were the largest class of user corrections in one project's
review-fix rounds: a version bump, files the reviewer had said to leave alone, other tickets' work.

With `--diff <base>..<head>` (in `--repo`, default `.`) it lists every file the range changed that
no plan's File structure section lists: what a task group added beyond its plan. A row is read
whatever its extension; a directory row (`src/api/`) covers the files under it, a template under a
directory (`src/gen/<domain>.ts`) any name in its place, and a test file beside a planned file (or
in a `__tests__`/`tests` directory under its directory) is that file's test.

Usage:
    scope_check.py <plans-dir> [--list] [--glob 'p4-*.md'] [--ext rs,ts,tsx,py,go,sql,...]
    scope_check.py <plans-dir> --waves <plans-dir>/p<P>-00-index.md [--glob ...]
    scope_check.py <plans-dir> --asks <decisions-dir>/00-index.md [<decisions-dir>/00-arbiter.md]
    scope_check.py <plans-dir> --diff <base>..<head> [--repo <repo>] [--glob ...]

Exit 0 when nothing is unimplemented, 1 otherwise (a File structure section that lists no file
counts), 2 when no plan matched or no plan has a File structure section. With `--waves`: 0 when
no wave shares a file, 1 when one does or a plan is missing from the index's plan set, 2 when the
index has no table with `Plan` and `Wave` columns. With `--asks`: 0 when every row cites an ask,
1 when one does not or lists a file not to touch, 2 when the plans list no file. With `--diff`: 0
when every changed file is planned, 1 when one is not, 2 when the range changed nothing or git
failed.
"""

import argparse
import pathlib
import re
import subprocess
import sys

DEFAULT_EXT = "rs,ts,tsx,js,jsx,mjs,cjs,css,scss,json,sql,yml,yaml,toml,py,go,java,kt,swift,c,h,cpp,hpp,cs,rb,sh,md,html,xml,properties,gradle,kts"
SECTION_RE = re.compile(
    r"^#{2,3} File structure\s*$(.*?)(?:^#{2,3} (?:Task|Tasks|Global|Interfaces)|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
NAMED = (
    "Makefile|GNUmakefile|Dockerfile|Containerfile|Jenkinsfile|Procfile|Gemfile|Rakefile"
    "|Justfile|justfile|Vagrantfile|LICENSE|CODEOWNERS"
)
DIR_RE = re.compile(r"`([A-Za-z0-9_./-]*/)`")
# --diff: a backticked path of a row, templates (`<domain>.ts`, `*.sql`) included
PATH_TOKEN = re.compile(r"`([A-Za-z0-9_./<>*-]+)`")
TEST_FILE = re.compile(
    r"(?:^|/)(?:__tests__|tests?)/|\.(?:test|spec)\.\w+$|(?:^|/)test_[^/]*\.py$|_test\.\w+$"
)
TEST_DIR = re.compile(r"(?:/(?:__tests__|tests?))+$")
PLAN_ID = re.compile(r"p\d+-\d+[a-z]?(?=-|$)")
ASK_RE = re.compile(r"\b((?:Ask|U)\d+)\b")
# an id is defined where a line, heading or table row opens with it
DEFINED_RE = re.compile(r"^[#>*|\s-]*\**((?:Ask|U)\d+)\b", re.MULTILINE)
FENCE_RE = re.compile(
    r"^#{2,4} Do not touch\s*$(.*?)(?=^#{1,4} |\Z)", re.MULTILINE | re.DOTALL
)


def rows(section, file_re):
    """(file, its line) for every file the section lists."""
    cur = ""
    for line in section.split("\n"):
        if line.startswith("#"):
            m = DIR_RE.search(line)
            cur = m.group(1) if m else ""
            continue
        for f in file_re.findall(line):
            yield (f if "/" in f else cur + f), line


def promised(section, file_re):
    return sorted({f for f, _ in rows(section, file_re)})


def mentions(text, path, bare):
    """How often text names path whole, plus, with bare, its file name standing alone. A name
    inside a longer path is another file: `data.rs` is not `a.rs`, `ui/mod.rs` is not `src/mod.rs`."""
    names = {path, path.split("/")[-1]} if bare else {path}
    return sum(
        len(re.findall(rf"(?<![\w./-]){re.escape(n)}(?![\w/-]|\.\w)", text))
        for n in names
    )


def unasked(plans, sources, file_re):
    """Plan rows that cite no ask the index defines, or list a file under its Do not touch."""
    text = "\n".join(pathlib.Path(s).read_text(errors="replace") for s in sources)
    known = set(DEFINED_RE.findall(text))
    m = FENCE_RE.search(text)
    fenced = set(file_re.findall(m.group(1))) if m else set()
    print(
        f"{len(known)} asks and user rulings defined; {len(fenced)} files not to touch"
    )
    print(f"{'plan':<40} {'files':>5} {'UNASKED':>7}")
    print("-" * 54)
    total, bad = 0, []
    for name, text in plans.items():
        m = SECTION_RE.search(text)
        found = list(rows(m.group(1), file_re)) if m else []
        total += len(found)
        miss = [
            (
                f,
                "do not touch"
                if f in fenced or f.split("/")[-1] in fenced
                else "no ask",
            )
            for f, line in found
            if f in fenced
            or f.split("/")[-1] in fenced
            or not set(ASK_RE.findall(line)) & known
        ]
        bad += [(name, f, why) for f, why in miss]
        print(f"{name:<40} {len(found):>5} {len(miss):>7}")
    for name, f, why in bad:
        print(f"   {name}  {f}  ({why})")
    print(
        f"\n{len(bad)} of {total} planned files cite no ask (Ask<n> or U<n>) or are not to be touched"
    )
    return 2 if not total else 1 if bad else 0


def planned_paths(section):
    """Every path the section's rows name in backticks, of any extension: --ext lists what a plan
    may create, but a changed file a row names is planned whatever its extension. A backticked
    name with no dot and no slash is a symbol (`KeysSection`), not a path."""
    for path, _ in rows(section, PATH_TOKEN):
        name = path.rstrip("/").rpartition("/")[2]
        # a template with no directory (`<domain>.ts` in a description cell) would cover every
        # file of its extension
        if re.search(r"[<*]", path) and "/" not in path:
            continue
        if path.endswith("/") or "." in name or re.fullmatch(NAMED, name):
            yield path


def unplanned(plans, rev_range, repo):
    """Files a commit range changed that no plan's File structure section lists. Live, the check
    read rows by --ext alone and flagged 55 of 123 files on six lanes, all of them in a row: a
    `.mts`, `.adoc` or `.puml` file, a directory, a test beside its planned file; every integrator
    overrode it."""
    # --no-renames: a rename onto a planned path still deletes the old one. -z: a path keeps its
    # spaces and is never quoted.
    out = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", "--no-renames", "-z", rev_range],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode:
        print(out.stderr.strip())
        return 2
    changed = [c for c in out.stdout.split("\0") if c]
    covers, dirs = [], set()
    for text in plans.values():
        m = SECTION_RE.search(text)
        for path in planned_paths(m.group(1)) if m else ():
            # a template's `<domain>` or `*` stands for any one name; a directory row covers
            # everything under it
            body = re.sub(r"<[^<>/]*>|\\\*", "[^/]+", re.escape(path))
            covers.append(
                re.compile(rf"(?:.*/)?{body}{'.+' if path.endswith('/') else ''}")
            )
            if not path.endswith("/") and "/" in path:
                dirs.add(path.rpartition("/")[0])

    def planned(c):
        if any(p.fullmatch(c) for p in covers):
            return True
        # a test beside a planned file, or in a test directory under its directory, tests it
        if not TEST_FILE.search(c):
            return False
        home = TEST_DIR.sub("", c.rpartition("/")[0])
        return any(home == d or home.endswith("/" + d) for d in dirs)

    extra = [c for c in changed if not planned(c)]
    for c in extra:
        print(f"   {c}")
    print(
        f"{len(extra)} of {len(changed)} changed files are in no plan's File structure"
    )
    return 2 if not changed else 1 if extra else 0


def plan_table(index):
    """{plan stem: (wave, its `Depends on` text)} from the plan index's plan-set table: the one
    with `Plan` and `Wave` columns."""
    rows, cols = {}, None
    for line in pathlib.Path(index).read_text(errors="replace").splitlines():
        if not line.startswith("|"):
            cols = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols is None:
            names = [c.lower() for c in cells]
            if "plan" in names and "wave" in names:
                deps = names.index("depends on") if "depends on" in names else None
                cols = names.index("plan"), names.index("wave"), deps
        elif not set("".join(cells)) <= set("-: "):
            plan, wave, deps = cols
            rows[cells[plan].strip("`").removesuffix(".md")] = (
                cells[wave],
                cells[deps] if deps is not None and deps < len(cells) else "",
            )
    return rows


def wave_no(wave):
    m = re.search(r"\d+", wave)
    return int(m[0]) if m else None


def depends(rows):
    """{plan stem: every plan it waits for}, directly or through others. A cell opening with `all`
    waits for every plan of the waves it names (`all of wave 1`), else of every earlier wave —
    never its own wave's, which run beside it."""
    ident = {s: m.group(0) if (m := PLAN_ID.match(s)) else s for s in rows}

    def everything(s, text):
        named = {
            int(n) for n in re.findall(r"\bwaves?[\s-]*(\d+)", text, re.IGNORECASE)
        }
        mine = wave_no(rows[s][0])
        return {
            o
            for o in rows
            if o != s
            and (w := wave_no(rows[o][0])) is not None
            and (w in named if named else mine is not None and w < mine)
        }

    direct = {
        s: {
            o
            for o in rows
            if o != s and re.search(rf"(?<![\w-]){re.escape(ident[o])}(?!\w)", text)
        }
        | (everything(s, text) if text.strip().lower().startswith("all") else set())
        for s, (_, text) in rows.items()
    }
    reach = {}
    for s in rows:
        stack, seen = list(direct[s]), set()
        while stack:
            if (o := stack.pop()) not in seen:
                seen.add(o)
                stack.extend(direct[o])
        reach[s] = seen
    return reach


def overlaps(plans, index, file_re):
    """Files that two plans of one wave, neither waiting for the other, both change: their lanes
    run in parallel worktrees, and each edits the file without the other's change until the
    integrator merges them."""
    rows = plan_table(index)
    if not rows:
        print(f"no plan-set table with Plan and Wave columns in {index}")
        return 2
    reach = depends(rows)
    owners, unlisted, row = {}, [], {}
    for name, text in plans.items():
        stem = name.removesuffix(".md")
        # the Plan column holds the stem or the plan id (`p1-02`), as the other docs name a plan
        m = PLAN_ID.match(stem)
        key = stem if stem in rows else m.group(0) if m and m.group(0) in rows else None
        if key is None:
            unlisted.append(name)
            continue
        row[stem] = key
        m = SECTION_RE.search(text)
        for f in promised(m.group(1), file_re) if m else ():
            owners.setdefault((rows[key][0], f), []).append(stem)
    shared = []
    for (wave, f), stems in sorted(owners.items()):
        both = sorted(
            {
                s
                for a in stems
                for b in stems
                if a != b
                and row[b] not in reach[row[a]]
                and row[a] not in reach[row[b]]
                for s in (a, b)
            }
        )
        if both:
            shared.append(f)
            print(f"wave {wave:<4} {f}  {', '.join(both)}")
    print(
        f"{len(shared)} files changed by two or more plans of one wave that run at once"
    )
    if unlisted:
        print(f"not in the index's plan set: {', '.join(unlisted)}")
    return 1 if shared or unlisted else 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("plans_dir")
    ap.add_argument("--glob", default="*.md")
    ap.add_argument("--ext", default=DEFAULT_EXT)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--waves", metavar="PLAN_INDEX")
    ap.add_argument("--asks", nargs="+", metavar="INDEX")
    ap.add_argument("--diff", metavar="RANGE")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    exts = "|".join(re.escape(e.strip()) for e in args.ext.split(",") if e.strip())
    # a path with one of the extensions, a build file with none, or a dotfile (`.gitignore`)
    file_re = re.compile(
        rf"`((?:[A-Za-z0-9_./-]*/)?(?:{NAMED}|\.[A-Za-z0-9_][A-Za-z0-9_.-]*)"
        rf"|[A-Za-z0-9_./-]+\.(?:{exts}))`"
    )

    plans = {
        f.name: f.read_text(errors="replace")
        for f in sorted(pathlib.Path(args.plans_dir).glob(args.glob))
        if not re.match(r"(p\d+-)?00-", f.name)
    }
    if not plans:
        print(f"no plans matched {args.glob} in {args.plans_dir}")
        return 2
    if args.waves:
        return overlaps(plans, args.waves, file_re)
    if args.asks:
        return unasked(plans, args.asks, file_re)
    if args.diff:
        return unplanned(plans, args.diff, args.repo)

    # A bare name counts only in a plan whose own table resolves it to this path.
    lists = {
        name: set(promised(m.group(1), file_re))
        if (m := SECTION_RE.search(text))
        else set()
        for name, text in plans.items()
    }

    def elsewhere(path, owner):
        return any(
            mentions(text, path, path in lists[name]) > 1
            for name, text in plans.items()
            if name != owner
        )

    print(f"{'plan':<40} {'tasks':>5} {'promised':>8} {'UNIMPL':>7}")
    print("-" * 66)
    total, detail, empty = 0, {}, []
    for name, text in plans.items():
        tasks = len(re.findall(r"^#{2,3} Task ", text, re.MULTILINE))
        m = SECTION_RE.search(text)
        if not m:
            print(
                f"{name:<40} {tasks:>5} {'—':>8} {'—':>7}   (no File structure section)"
            )
            continue
        files = promised(m.group(1), file_re)
        bad = [
            x for x in files if mentions(text, x, True) <= 1 and not elsewhere(x, name)
        ]
        detail[name] = bad
        total += len(bad)
        if not files:
            empty.append(name)
        print(
            f"{name:<40} {tasks:>5} {len(files):>8} {len(bad):>7}{'   <-- half-scoped' if bad else ''}"
            f"{'' if files else '   <-- lists no file'}"
        )

    if not detail:
        print(f"\n0 of {len(plans)} plans have a File structure section")
        return 2
    print(f"\n{total} promised files that no task in any plan creates")
    if empty:
        print(f"{len(empty)} File structure sections list no file: {', '.join(empty)}")
    if args.list:
        for name, bad in detail.items():
            if bad:
                print(f"\n## {name}  ({len(bad)})")
                for x in bad:
                    print(f"   {x}")
    return 1 if total or empty else 0


if __name__ == "__main__":
    sys.exit(main())
