# A rung-S route, end to end

One real run: a clean-room build of CSV import for a small self-hosted web app (Go + React,
SQLite) that stores timestamped readings per person. Every quote and number comes from the run's
planning files, gate logs and transcripts; names and paths are generalised.

## The task

Rung S, unattended. An old decision had cut import because it "needs a contract it does not have
yet: append/replace/merge, collisions, tombstones, retries, transactionality". The route was to
decide that contract, write the spec and plan, and "execute the plan on a branch until `bash
scripts/check.sh` passes"; "The import must round-trip what the existing CSV export writes". For
any question: "take your recommended option and record it as a default". No push.

## The announcement and `--activate`

From the handoff: "rung S; ~10M units (lead ~3M, S review 0.6M, 5 groups × 1.0M, lead
0.3M/group); 1¾–2 h. Models: all `dsp-deep`, Opus 5.5, session effort." Each figure is a
`costs.md` median (S review agent 0.6M, task group 1.0M, lead 0.2–0.4M per group), about $40 at $4
a unit. The prompt was the go-ahead, so the lead registered the route at once:

```
route_state.py docs/dsp --phase 1 --repo . --activate --rung S
```

It printed `pre-push hook installed` and flagged CI, which runs on `windows-latest`, "which this
host is not"; with no push allowed, the handoff recorded that no harness log was needed.

## Harvest, inline

At S the lead harvests itself. It read the old decision, the design spec and the export code,
then **probed**: a throwaway `go test -overlay` run showed `Neutralise("=SUM(A1)")` and
`Neutralise("'=SUM(A1)")` both return `'=SUM(A1)`. The export is not injective, so under Ask3 it
is data corruption: the round's one confirmed defect and its **Lane 0**. The baseline gate ran
through `gate.py` on `e121394` ("Go 4 packages ok; web 6 files, 38 tests").

## The decision document

One file, `decisions/phase1/00-index.md`: five asks quoted verbatim, SETTLED rows (S1 "The app
WARNS, it NEVER refuses"), measured numbers labelled *measured* or *by reading* with their SHA,
requirement dimensions each owned or `N/A: <reason>`, and four decisions, each serving an ask:

- **D1, mode and identity.** Options: append, replace or merge. Ruling: "Import only ever
  **appends**… (replace is what backup-restore is for; merge-update is `backlog`)". Rows are
  de-duplicated by content "as a multiset", so "a retry, a double click, or two tabs committing
  the same file are idempotent with no import table, no idempotency key and no migration". An id
  column in the export was weighed and rejected: "one key, one rule".
- **D3, protocol.** "`POST /api/import/preview` classifies and writes nothing; `POST /api/import`
  classifies again **inside one write transaction**", with an 8 MiB cap on those two routes.
- **D4, round trip.** Defines the term (export A, import into an empty database, export B,
  multiset-equal rows) and fixes the neutraliser first: `Unneutralise(Neutralise(s)) == s` "for
  every `s` (a fuzz test proves it)".

Each question became a **Default the user may overturn**, eleven in the end: "1.
**Append-only; no replace or merge mode** (D1). Overturn → a merge-update decision."
`decision_check.py --rung S` exited 0.

## The spec and the plan

`spec/1-csv-import.md` opens with the scope section (§1.0: in, out, inherited rules, invariants,
Lane 0, supersedes, defects, contract deltas); §1.1–§1.8 hold the contract and §1.9 the criteria
`AC-P1-1-<n>`. Draft one had 17; `criteria_check.py` printed 17 of 17 ok.

`plans/p1-01-csv-import.md`: header, architecture, the measured defect, a File structure table
whose every row cites an ask, global rules (one task, one commit; test-first; gates written to a
file, never piped), eight tasks each naming its spec section, criteria and test file, an
**Acceptance mapping** (`AC-P1-1-13 | 5 | internal/store/import_test.go`) and the **execution
groups**. `plan_lint.py` ok; `scope_check.py` 0 unimplemented, 0 unasked; `--plans` 17 mapped.

## The second-model review

None was available, so the review prompt ran on a `dsp-deep` agent (12.5 min, 0.8M), given the
checkers' output and told to "report what they miss". It probed and wrote `00-seams.md`: **41
findings, R1–R41**, with "two blockers: quality can't round-trip, and same-name people would
merge". R2, *measured*: the API accepts "Person A", a second "Person A" and "person a", and the
spec keyed new names "by the folded name", "So importing into an empty database merges both
people's … histories into one person and lists nothing."

All 41 were dispositioned `applied` (some `applied (upholds S<n>)`), as an appended **Amendments
after the S review** section that "WIN over the D1–D4 text they name". Its 17 entries are numbered
by finding, A-R1 to A-R28; the final report's "28 changes made after the review" is that highest
number, not a count. What changed:

- **A-R1** a verified `<db>.pre-import.bak` copy before importing into a non-empty database;
- **A-R2** the export gains `person_id`; people resolve "by id, then exact name", so "two
  same-named people in the source stay two people";
- **A-R10** a file's `quality` kept as written; **A-R11** caps raised to 32 MiB / 100,000 rows.

The lead rewrote the spec (18 criteria) and the plan (six groups) and re-recorded the Stage 5
budget at 7.8M with `route_state.py --budget`. Spent so far: 2.3M.

## Execution in task groups

One lane, branch `csv-import`, six fresh `dsp-deep` groups in turn. Each prompt named its tasks,
spec sections and criteria, the previous checkpoint and orientation map (from G2), and the rulings
file to "re-read… before each task and before each commit". Each group overwrote the checkpoint
(≤35 lines, ending `Final SHA: <sha>`) and replied in under 1 KB.

| Group | Tasks | Commit | Cost |
|---|---|---|---|
| G1 | 1 neutraliser (Lane 0), 2 export columns | `5d5bbee`, `e4b0d26` | 0.2M |
| G2 | 3 parser | `5386f01` | 0.4M |
| G3 | 4 import planner | `5752364` | 0.5M |
| G4 | 5 transaction + copy | `fda10f4` | 0.4M |
| G5 | 6 HTTP routes, round trip | `aa4b625` | 0.4M |
| G6 | 7 Settings dialog, 8 gate + real binary | `14773a9` | 0.5M |

After each return the route hook reported head SHA, commits, gate state and trailers (after G1:
"2 commits · no gate log at this SHA"). G2 touched a file outside the plan; the lead accepted it in
the rulings file as **L1**. At the end the lead ran both merge checks on `e121394..14773a9`:
`scope_check.py --diff` printed "1 of 23 changed files are in no plan's File structure" (L1), and
`test_check.py --diff` printed `EDITED internal/httpapi/api_test.go aa4b625`. The lead read that
diff and ruled **L2**: "ACCEPTED, a strengthening… No assertion dropped."

## The gate

Task 8 ran the full gate as the plan wrote it:

```
gate.py docs/dsp p1-01-csv-import -- 'nice -n 19 ionice -c3 bash scripts/check.sh'
```

`lanes/p1-01-csv-import-gate.log` opens `sha=14773a9… dirty=0` and ends `All checks passed.` /
`exit=0`. The lead checked it first-hand: `git status --porcelain` empty, `grep -c FAIL` 0, Go
packages `ok`, lint "0 issues", "Tests 52 passed (52)". G6 also drove the real binary: export from
one instance, import into another, then "re-commit 0 imported, 3 duplicates".

## What the push guard would have checked

Nothing was pushed. A `git push` of `csv-import` would have met the pre-push hook `--activate`
installed, which needs a log under `lanes/` whose first `sha=` line is `sha=14773a9… dirty=0` and
whose last `exit=` is `exit=0`: the gate log above. The Windows CI suite would first need
`--ci-harness <label>` (or `none`); with a label, every push but one to a non-main branch also
needs that suite's gate log.

## The final report

Branch and SHA (`csv-import` @ `14773a9`, 7 commits, not merged), the gate result, the eleven
defaults, and the cost from `usage_report.py`: "**5.0M total**: 1.8M for me plus 3.1M across 7
agents (one review and six build groups). That is about half the ~10M I announced". Then what
still needs a person, such as the screenshot baseline and running the Windows `.exe`.

## What it cost and what it bought

$20.32 at list price, 72 minutes. Plain Claude Code on the same task: $7.29, 19 minutes; both
branches passed the project's gate. Against 15 hidden acceptance scenarios the route's branch had
4 defects, plain Claude's 7. Plain Claude merged two different people who share a name; the route
kept them apart, after its review raised exactly that (R2) before any code existed. Two of the
route's four misses trace to its own unattended rulings: D2's "`confirmed` is never carried in"
fails a confirmed-survives scenario, and A-R22's documented apostrophe loss on old files fails
another. One task and one run each: an observation, not a benchmark.
