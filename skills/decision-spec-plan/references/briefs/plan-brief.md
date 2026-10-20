# The plan brief — full text

Copy to `<planning-dir>/PLAN-BRIEF-p<P>.md`. Keep every unmarked rule (SKILL.md, 'Adapt, don't
trim'); fill every `‹ADAPT›`.

---

```markdown
# ‹ADAPT: Project› — phase-‹P› plan-writing brief

**Every plan agent gets this file, identical.** Your plan is the only thing that differs, and it
arrives in your dispatch message.

## Your job

**Write one implementation plan.** One file, `‹planning-dir›/plans/p‹P›-<id>-<slug>.md`, plus its
manifest. You write no product code. Your plan is executed later by a different agent in its own
worktree, who will have your plan, the spec, and **nothing of your reasoning that you did not write
down**.

**The decision and spec rounds — and reconciliation, where it ran — are closed.** You schedule
that work into tasks; you do not re-rule it.

## Read before writing, in this order

1. **The plan index** (`plans/p‹P›-00-index.md`) — migration numbers, the reconciled contract delta,
   the wave order, the rulings, and **your row of its reading map**. **Its numbers are your
   requirements and are not repeated in plan bodies.**
2. **The scope section** — it binds every reader. Confirmed defects assigned to your section ride
   your plan and need tasks.
3. **Your spec section, in full.** Every other section it names, **at the anchors your reading-map
   row gives** — `grep -n` the heading, read that range — not the whole file.
4. The arbiter rulings your row names — the spec says *what*, the arbiter says *why*.
5. The earlier phases' plan indexes — their rulings bind this phase unchanged.
6. The reconciliation findings your row names, where Stage 3 ran.

**The map is a floor, not a fence.** Where your section needs something it does not name — a value
another section owns, a ruling, a finding — read it, and list each such read in your reply (item 7)
so the lead can correct the map. Every neighbouring section read whole is re-sent on every later turn:
plan authors read 150–720 KB each, mostly other sections whole, and were the third-largest cost of a
run.

**Precedence**: ‹ADAPT: ladder›. An arbiter ruling beats a decision file; the scope section beats a
decision file; **the code beats a document that describes it wrongly.**

## Verify every anchor you cite

Every `file:line` you write into your plan, you opened. A claim without a line reference is an
opinion; a line reference you did not open is worse, because the next reader trusts it. **Compare
shapes, not strings.** **Before writing "declared nowhere", name the languages and directories you
searched.** ‹ADAPT: the tools — symbol search, structural search, text search.›

## The plan file's shape — `plan_lint.py` enforces it

| Requirement | Form |
|---|---|
| Header fields | `**Goal:**` · `**Spec:**` · `**Depends on:**`, each at column 0 |
| Tasks | `## Task N — <title>` or `### Task N — <title>`; at least one |
| Interfaces per task | one `- Produces:` line and one `- Consumes` line, **at column 0**. A final gate task may produce nothing — **one** shortfall allowed |
| Steps | `- [ ] …` checkboxes |
| Fences | every ``` paired |

`scope_check.py` must report **0** for your plan. It reads your `## File structure` section (ends at
the first `## Task`/`## Tasks`/`## Global`/`## Interfaces`), collects every file in backticks
(bare names resolve against the nearest preceding heading naming a directory in backticks), and
**fails any file that appears only in that table**. **This caught ten of 21 plans in one project
shipping a File structure table and no tasks for the UI it promised** — *the table makes the gap
invisible, because a named file reads as owned.* **Do not list a file you do not give a task.**

**The table lists every file your plan creates or changes, tests included, and each row cites the
ask (`Ask<n>`) or user ruling (`U<n>`) that wants it**; `scope_check.py <plans-dir> --asks
<decision-index> <arbiter>` must report 0. A change you think is needed that no ask covers — a
refactor, a rename, a version, a file on the index's Do not touch list — is not planned: name it in
your reply, and the lead asks the user. *Unasked changes were the largest class of corrections in
one project's review rounds, and each cost a cleanup round* (`failure-modes` F89).

Shape: goal, architecture paragraph, what is actually broken (*measured*), File structure, then
numbered tasks, each with Requirements / Interfaces / Steps / the test that proves it.

## Your manifest

Write `‹planning-dir›/manifests/<plan-id>.json`:

    {"plan": "<file>", "taskCount": N, "lineCount": N,
     "produces": [{"name": "...", "kind": "...", "signature": "<real signature>", "where": "<path>"}]}

**Every name another plan will consume must be in it, with its real signature.** A manifest trimmed
to keep a checker quiet is a lie about the plan set — once, the collisions it hid became a ruling.

## Tasks — the rules that make a plan executable

- **Test-driven, and the test must be discriminating.** Every task names the failing test to write
  first, the command that runs it, and what it prints when it fails. *A test written after the fix
  can pass for the wrong reason.* Say how the executor proves the test bites — usually *revert the
  fix and watch it fail*.
- **A gate whose passing run scans zero files is a failing gate.** Every scanning or parsing check
  prints its count and fails at zero. The count is the checker's own output or an assertion: never
  a logger, a log config or a print added to tests or product code for it — 83 such lines in 21
  files were a reviewer's cleanup round (F89).
- **Declare a seam and its production implementation in the same task.** Five recorded instances of
  the opposite each compiled, passed against the fake, and failed at assembly.
- **One owner per value.** A cross-language mirror needs a test that *reads the other language's
  source*. Where a store CHECK mirrors a generated enum, the two are one value stated twice: carry a
  test that inserts **every** variant against a **real migrated store** and **prints the count
  inserted**.
- **A rule every instance must keep is tested over the instances the test finds in the code** —
  every handler, every control that writes — and prints their count; never over a hand-kept list,
  which misses each one added after it. *A gate stayed green while 31 write controls broke such a
  rule: its test checked a list kept by hand.*
- **Check the contract before naming any type or command.** A type it declares must not also be
  hand-written.
- **A producer must distinguish *absent* from *unreadable*** before it may create or open anything
  from it — a timeout looks exactly like a missing file.
- **Name the task that creates your acceptance tests.** One round found **41** checks with an owner
  and no implementing task — *the structure that makes something checkable gets built, and the thing
  itself is assumed to be somebody's next step.* Your last task normally lands your section's suite
  and says which file it creates.
- **Every task is one commit.** ‹ADAPT: the commit rules — the subject convention the repo's
  `git log` shows (a `type:` prefix, a scope), subject length, body length, trailers.›
- **Size.** ‹ADAPT: the project's task range per plan, or "none".› A task that cannot be described
  in a paragraph plus a test is two tasks.

## Your section's acceptance criteria are already written

Your spec section states its criteria as prose, numbered `AC-P‹P›-<section>-<n>`. **Do not restate
them, do not renumber them, do not add one.** Your plan **maps** them in one table,
`| Id | Task | Test file |` (more columns may follow): the id or a compact group
(`AC-P4-47-13, -14, -16`), the task number(s) that land it, and the test file (or `file::test`) in
backticks — or `manual` beside the ruling that allows it. `criteria_check.py` reads only this table:
an id mapped in prose, or handed to another plan, is unmapped until a table lists it. The register
lane folds that mapping, which is why every id must reach a **named test file**, not an intention.
If a criterion cannot be satisfied as written,
**say so with file:line on both sides** — do not quietly drop or weaken it. *A criterion a correct
implementation cannot pass is the same defect wearing the opposite sign.*

## Migrations: use the assigned number, add nothing

The plan index assigns every migration number, in dependency order, by one hand. **If your section
states a migration and the index gives you no number, you do not own one** — report it.
‹ADAPT: the rebuild procedure and its traps.›

## Contract deltas: state yours, never a total

The plan index's delta table is the only place any phase total is written. **A section that wrote a
running total into its own file was wrong on three of five counts the moment another section
landed.** ‹ADAPT: where totals are hard-coded; "regenerate, never hand-merge"; the symptom a stale
generated file produces.›

## Do not edit any earlier phase's spec file

Your section records its supersessions in a table. **Your plan schedules each into the task that
lands its code**, as a `[p‹P›]` marker — *the bar and the body move together*. **Give every
supersession row a task number.** Patch documents surgically; never rewrite — a wholesale rewrite once
silently dropped two subsystems while the bar still tested them.

## Invariants and boundaries

‹ADAPT: the scope section's invariants and boundaries, one line each — they do not expire at the
phase boundary.›

## The gates your plan must be executable against

‹ADAPT: the exact gate commands, chained with `&&`. The baseline counts with their SHA.› **Never pipe
a gate through `tail`/`head`** — the pipeline returns the pipe's exit status and a red gate reads
green. **Compare failing-test identity, not count.**

## Public-repo hygiene

‹ADAPT›

## Report a disagreement rather than silently complying

Plan authors have overturned the arbiter repeatedly, each time correctly. If your section
contradicts the plan index, the scope section, the arbiter, the contract or the code: **say so with
file:line on both sides**, write the reading that keeps the system correct, mark it as a deviation.
**Do not hand-write a duplicate of something another plan owns** — land the minimal
forward-compatible piece and report the gap. Some plan defects are **ordering**, not content — a plan
split across a boundary its dependency row cannot express.

## Output

**Your plan file and your manifest.** Run `plan_lint.py`, `scope_check.py` and `scope_check.py
--asks` on your plan first; all must pass. Then a reply under 3 KB: 1. your plan-index row (plan, one-line contents, task count,
line count); 2. your contract delta and migration contents; 3. the criteria → task → test-file
mapping as a count plus any id you could not place; 4. what you superseded, with the task number that
applies it; 5. any disagreement, file:line both sides; 6. what you refused to specify and who owns
it; 7. every read beyond your reading-map row, with what you needed there. **The plan file is the
deliverable.**

## House rules

- **Do not commit anything.** You write documents; a different agent executes them.
- **Do not edit another plan's file, another section's spec, or any tool.**
- **Never batch multiple edits to the same file in one message** — concurrent edits race on a shared
  snapshot and apply partially, silently.
- ‹ADAPT: formatter hooks and other environment traps.›
```
