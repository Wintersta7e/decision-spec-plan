# The decision brief — full text

Copy to `<planning-dir>/DECISION-BRIEF-p<P>.md`. Keep every unmarked rule (SKILL.md, 'Adapt, don't
trim'); fill every `‹ADAPT›`.

---

```markdown
# ‹ADAPT: Project› — phase-‹P› decision brief

Every decision agent gets this file, identical. That is deliberate: this kind of work's recorded
failure mode is independent agents inventing two answers for one thing. Partitioned by spec
**section**, ~40 agents left **105** contradictions for reconciliation to find; partitioned by
**decision**, with an arbiter settling the seams, ~10 agents left **1** — in two phases of one
project. You are one of the agents in `‹ADAPT: planning-dir›/decisions/phase‹P›/00-index.md`.

## Your job

**Rule on exactly one decision** from `00-index.md`, and write it to
`‹planning-dir›/decisions/phase‹P›/D<n>-<slug>.md`. You are **not** writing a plan, not writing a
spec section, and not writing code. You are producing the ruling a spec author and then a plan
author will implement against.

You do not rule on any other decision. If your work forces a conclusion inside someone else's,
**say so as a binding** (item 4 of the output contract) rather than deciding it for them.

## This is a decision round, not an execution round

- **Do not modify any tracked file.** No code, no tests.
- **Do not commit anything.** The planning directory is gitignored; your output never gets staged.
- **Do not run the build gates.** Nothing you write can break them, and a gate run costs
  ‹ADAPT: minutes› of a machine someone else is using.
- You *may* read anything in the tree, and you **should** — a ruling contradicted by the code that
  already exists is worthless. Read-only commands and throwaway probes in
  `‹ADAPT: scratchpad›/<your-id>/` are fine.

## What this phase is

‹ADAPT: one paragraph — the phase's charter quoted with file:line; which release it is; what makes it
riskier than the last phase (a first destructive operation, a first network write, a first paid
path…). "Every ruling touching <the risky thing> is ruled against the worst day, not the typical
one."›

## Reading order

1. `00-index.md` — the **SETTLED** table, the measured numbers, the confirmed defects, your
   decision's row, and "What each decision may NOT decide". Everything in the settled table is
   already ruled; contradicting one is allowed only with an explicit argument and file:line, never
   by quiet assumption.
2. **The harvest files beside it** — `harvest-spec.md`, `harvest-code.md`, `harvest-design.md`.
   **They are an index, not the source.** Open the file:line before you rely on it. **Start from
   them**: open what your ruling rests on, and search the tree afresh only for what they lack —
   name each such gap in your evidence. Re-exploring what a harvester already mapped is the
   round's largest avoidable cost.
3. ‹ADAPT: the concept/charter document with the line ranges that matter›
4. ‹ADAPT: the previous phase's decision index and arbiter — "several of its rulings were made by
   deferring something to this phase; inherit them, do not re-open them"›
5. ‹ADAPT: the spec directory›. Grep it **as a directory, never one file**. The dominant defect is
   one value in two places drifting; one round found **105**.
6. ‹ADAPT: the plan indexes and their ruling ranges›. Your ruling becomes R‹next›+ if accepted.
7. ‹ADAPT: the measured-results file› — **measured numbers beat any estimate**, including yours.
8. The actual code for anything you assert about it.

**Precedence when sources disagree**: ‹ADAPT: the project's ladder, e.g. measured results > spec >
design handoff (visual only) > synthesis > concept›. An arbiter ruling beats a decision file; **the
code beats a document that describes it wrongly.**

## What earlier phases recorded for this one

‹ADAPT: the obligations earlier phases recorded specifically so this phase could use them (a
ledger, a sidecar, a contract…), each with file:line.› **Read what the tree actually wrote before
designing over it.** A ruling that invents a second one discards the reason the first was built. A
ruling that finds the recorded thing **insufficient** says so with file:line — that is a finding,
not a failure.

## The invariants

They bind this phase unchanged. ‹ADAPT: list the project's standing invariants, one line each, with
the incident or review behind each where one exists, and call out those this phase makes
non-vacuous: "phase ‹P› is where <invariant> stops being vacuous — <why>".›

## The boundary this phase may move

‹ADAPT: the claim the product makes to users today that this phase could widen (a write surface, a
data flow, a permission).› **If your ruling widens it, that is a claim the product currently makes
and you are proposing to stop making. Say so in those words**, name the audit that replaces the one
you retire, and say what the audit must **scan** and that it prints its count. **A check that
inspects only the command it issues is not an audit of what the command does** — configuration,
environment and hooks decide behaviour too.

## Check the contract before naming any type

‹ADAPT, WHOLE PARAGRAPH: where the contract lives (a generated schema, an OpenAPI file, a typed IPC
layer, a database schema) and its current counts with the SHA they were measured on. **If the
project has no generated contract, say so in one line and name what plays that role** (e.g. "the
Tauri command list in `src-tauri/src/main.rs` and the TypeScript bindings beside it") — never leave a
sentence about a generator that does not exist.› A type the contract declares must not also be
hand-written in a second place. If your ruling needs a new command, event or enum, say so as a **change with its shape**,
and never assume a name exists without grepping for it. **State deltas, never totals** — an
absolute count asserted in a lane was wrong after the merge six times in one phase.

## Migrations: contents, never the number

‹ADAPT: the current head migration and the store's rebuild rules.› **Do not assign a migration
number** — three decision files once each claimed the same one. State the **contents** and the
**dependencies**; numbers are assigned once, at plan time, by one hand.

## The defect patterns that recur

Write your ruling so a plan author cannot walk into these.

- **A producer with no production caller.** One phase shipped **six** behind all-green suites. If
  your ruling introduces a seam or a producer, **name who lands the production caller, in the same
  change**.
- **A bar written past its defect proves the wrong thing.** If your ruling depends on a check, say
  what the check must **scan** and that it must print the count.
- **One value stated twice drifts.** One owner per value; a cross-language mirror needs a test that
  reads the other side.
- **A name collision is not evidence of a duplicate.** Compare shapes before collapsing. **Grepping
  for a declaration also matches prose about it.**

## Evidence discipline

- **Every claim about a file carries `file:line`.** A claim without one is an opinion.
- **Before writing "declared nowhere", name the directories and languages you searched** — a ruling
  was once overturned for searching one half of the tree.
- **Verify a path before citing it.** A harvest file's summary is not the source.
- **A number without the tree it was measured on is not a measurement.** Mark each conclusion
  *measured* or *by reading*.
- **Label every figure that drives your ruling *measured*, *documented* or *assumed*** — a rate
  limit, a payload size, a cost at N items, a timing. **Where a read-only probe is cheap, run it**
  (an unauthenticated API request, a throwaway repository, the regex against real input, the command
  timed) — a ruling that probed the API it depends on beat one that read its documentation. For any
  cost, give it as a formula and evaluate it at the scales that matter (e.g. N = 100, 1,000, 5,000).

## Public-repo hygiene

‹ADAPT: what the planning directory may contain (real paths, third-party names) and what must never
reach a commit message, code comment, README, fixture or log line.›

## Report a disagreement rather than silently complying

Nearly every ruling in this kind of work was found by an agent writing *against* the others. If your
decision's framing in `00-index.md` is wrong — the evidence does not say what it claims, the question
is malformed, it is already settled somewhere you found, or it is really two decisions — **say that
first and rule on the real question**. That is the most valuable thing you can return.

## Your output

One file, `‹planning-dir›/decisions/phase‹P›/D<n>-<slug>.md`, containing:

1. **The ruling** — one paragraph a plan author can implement against. Lead with it.
2. **The evidence on both sides**, with `file:line` for every claim.
3. **What it costs** — migrations (contents), changed files, changed spec sections, contract delta
   with shapes, changed or new acceptance criteria.
4. **What it binds** — which other decisions must agree, named by `D<n>`, and what you need from each.
5. **What you refused to decide**, and who owns it — including anything that is **the user's** call
   rather than an engineering one (copy, a visible choice, a published promise).
6. **Where you disagree** with the index, the spec, the contract or the code — file:line both sides.

Then return a **short** reply: the ruling in three sentences, the bindings by number, anything the
user must decide, and the path. **Your reply is truncated around 4 KB**, so anything long that only
lives in the reply is lost. **Write the file first.**
```
