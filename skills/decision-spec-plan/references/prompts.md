# Dispatch prompts

Every dispatch is `run_in_background: true`, all independent ones in **one message** — at most 8 per
message; a spawn that returns "Lock file is already being held" never started, so dispatch it again
(`failure-modes` F65). **You pick each dispatch's model and effort** by what it must get right:
`subagent_type: "decision-spec-plan:dsp-deep"` (`<skill-dir>/agents/dsp-deep.md`, a restricted tool list; the plugin qualifies the name) with the Agent
call's `model` (omitted: the session's) and `effort`. Announce each role's pair with a one-line reason beside the rung and
headcount (SKILL.md, "Pick a rung"); the user may overrule any before the first dispatch. The second
model keeps its own configuration.

| Role | Default | The cheaper pair (`model: "sonnet"`, `effort: "medium"`) |
|---|---|---|
| Framing, seam, S and docs reviews as an agent; the seven-sins reviewers | the session's model and effort | never: a Sonnet docs review passed a commit message that a deep review rated Major (F88) |
| Decision agents | the session's model and effort | only a narrow docs or convention decision that cites no code fact and places no other decision's output: a Sonnet placement ruling (which commit holds what) drew a seam blocker and was rewritten (F88) |
| Spec and design harvesters; supersede markers; the register folder | the session's model and effort | allowed with a reason, and you check the output against its inputs: live runs did as well as deep peers (F88), one replay dropped items (F45) |
| Code harvester, spec authors, reconcilers, plan authors, Stage 5 task groups, integrators | the session's model and effort | never measured on Sonnet |

**Effort.** By default omit `effort`: the dispatch takes the session's `/effort` and follows it when
the user changes it mid-run (measured: a task group went from `xhigh` to `high` with its lead).
Depart from the default wherever the task calls for it, with a one-line reason in the announcement:
`effort: "xhigh"` for a role whose call is hard to get right (a concurrency or distributed-state
decision, conflicting hypotheses, a cross-component seam), less for the cheaper rows above. Every
measured run used `xhigh` for every role, so a session at `high` is itself unmeasured (run set I):
record each agent's model and effort with its cost in the handoff (`usage_report.py` prints both). A Workflow script picks
the pair with `agentType: 'decision-spec-plan:dsp-deep'` (the session's model and effort) or `'decision-spec-plan:dsp-mechanical'`
(Sonnet, medium) in the `agent()` options. **Why `dsp-deep` is a named agent:** `general-purpose` carries every tool schema and the skill listing, so its first turn started
at 29.5k tokens against 15.1k for `dsp-deep` (same headless session, same prompt, 2026-10-06;
40.8k for `general-purpose` from an interactive session; another machine: 55.9k against 40.9k), and every later turn re-sends the difference. A role that needs a
tool outside the list (a browser MCP) is dispatched as `general-purpose`.

**Why the default is the session's model.** Every recorded run used it, and a written model alias can resolve to another version or a smaller context window than the session's.
**Three roles were replayed on `sonnet` against a session-model control over one finished phase
(2026-09-29); none held.** Markers: 66 of the original's 77 (file, ruling) pairs to the control's
73, and one sequencing ruling missing from all five files that carried it. Design harvester: 14 of
the decision round's 20 open questions fully covered to the control's 20, missing one that became a
spec cluster. Register fold: the checker's table copied exactly, but 38 of 45 moved criteria to the
control's 44. Session-model wall-clock: markers 25 min, design harvest 23, register fold 45;
`sonnet` ran each in roughly half. Run set B put exactly those roles on the mechanical tier by
judgement, unmeasured; run set I's live Sonnet roles are F88. To settle a role's pair for a
project, replay it: strip that role's output from
a copy of a finished round **and every annotation added to its inputs since**; re-run its prompt on
the cheaper tier **and on the session setting as a control** — inputs drift, and one run differs
from the next (the control reproduced 88% of the original's markers); compare at the unit the next
stage reads (ruling per file, criterion, open question), never raw counts and never an agent's own
tally (one reported 242 markers and wrote 230); print both counts and every difference.

Before dispatching on a copied brief, compare its unmarked text with the template's and print two
counts: lines rewritten because false for this project (each named), and unmarked paragraphs
dropped or otherwise changed — the second must be 0.
Every prompt ends with the same closing lines — keep them:

> Write only your own file. Modify no tracked file, commit nothing, run no build gate (throwaway
> probes only under `<scratchpad>/<your-id>/`). If a write under `<planning-dir>` is refused, write to
> the scratchpad and say so. Write the file's skeleton — its headings, each marked `pending` — in
> your first turns and fill it as you go: if you are stopped, a fresh agent continues from it. Your
> reply is truncated around 4 KB: **finish the file first**, then reply with <the short shape for
> this role>. Your final message is that reply — never `SendMessage` it to the lead as well.

**Why the skeleton:** after a lead restart a stopped agent can be unreachable ("No agent named … is
reachable"), and the fresh agent that replaces it starts from whatever file exists (`failure-modes`
F64). **Why one reply:** the lead receives an agent's final message in its idle notice; a return
also sent by `SendMessage` reached it twice (F69).

A prompt no brief covers (a repair round, an ad-hoc role) ends with the closing lines and carries,
by name, the rules every brief states with its evidence: report disagreement, file:line on both
sides; compare shapes; name what you searched; *measured* vs *by reading*; one value, one owner;
deltas, never totals; migration contents, never numbers; a producer names its caller; a gate that
scans nothing fails; a test exercises the real shape; `‹COPY›` placeholders; hygiene — nothing from
the planning dir reaches a commit, comment, fixture, log line or README; turn economy — batched
lookups, ranged reads. **Never have one agent emit N large items** — fan out one agent per item.

The turn-economy rule (batch known lookups, `grep -n` first, ranged reads) and an execution agent's
one-group limit live in the `dsp-deep` and `dsp-mechanical` definitions, so they hold however a
prompt or brief is worded — a lead-written lane brief left the rule out of 21 of 24 dispatches
(2026-10-04). A `general-purpose` dispatch gets both paragraphs pasted from `<skill-dir>/agents/dsp-deep.md`.

Substitute `<repo>`, `<planning-dir>`, `<P>`, `<scratchpad>` — each as an absolute path: a lane
agent works in a worktree with no planning dir (`execution.md`, *A lane*).

---

## §0 — Harvest (three, in parallel)

**spec**
> You are harvesting inputs for the phase-<P> decision round of <project> (<one-line description>).
> Phase <P> per `<concept>:<lines>` is "<charter>". TASK: find EVERY place the written contract
> defers something to phase <P> (or names its subjects: <keywords>) and record it verbatim with
> file:line. Sources in order: the spec directory (grep it AS A DIRECTORY with a keyword regex; read
> each hit ±15 lines — a deferral often carries a constraint); the previous phases' decision indexes
> and arbiters; the plan indexes' rulings; the handoff's carried-forward items. OUTPUT
> `<planning-dir>/decisions/phase<P>/harvest-spec.md`: a table grouped by topic (source file:line ·
> short verbatim quote · the constraint it places on phase <P> · phase <P> / later / ambiguous);
> "Conflicts" (both sides); "Carried-forward defects phase <P> must own or decline"; counts per
> topic, counted by script. Reply <2 KB: path, counts, the five most consequential items.

**code**
> … TASK: establish with file:line what the tree ALREADY records or implements that phase <P> would
> build on — and for each, whether it has a PRODUCTION caller or is test-only (this project has
> shipped producers with no caller behind green suites; <audit tools, if any> exist — run them
> read-only). Inventory at minimum: <the recorded obligations; the tables/columns/jobs the phase
> reads; the write surface and its audit; notification/export/tray code; settings; the contract's
> current counts>. OUTPUT `harvest-code.md`: one section per item (what exists, shape, production
> caller yes/no with its file:line, what is ABSENT), a "Recorded for phase <P> — state" table, and
> "Defects found in passing" (file:line both sides; say which were reproduced and which only read).
> Reply <2 KB: path and the eight most consequential findings.

**design**
> … TASK: collect every design ruling, idea, measurement and open question about phase <P>'s subject
> from the design sources, with file:line, and flag disagreements. Precedence: <ladder>. Sources:
> <concept ranges; synthesis; ideas/*; design constraints; the design handoff and prototype; measured
> results; stack notes>. OUTPUT `harvest-design.md` by topic (ruling/idea, file:line, settled /
> proposed / contradicted), then "Conflicts" (both sides, numbered C-n) and "Unspecified — nobody has
> decided this" (numbered U-n: the questions a decision round must answer). Reply <2 KB: path and the
> eight most consequential rulings/conflicts/open questions.

---

## §1a — Framing review, before dispatch (second model, read-only; unavailable: Lead mechanics)

> You are reviewing the FRAMING of a decision round before N agents are dispatched, one per decision.
> Read-only. Read <brief>, <index>, and skim the three harvests (their conflicts/unspecified/defect
> sections). Consult the concept, the spec and the code to verify. Answer in
> `<planning-dir>/decisions/phase<P>/00-framing-review.md`, a numbered list with file:line, blunt,
> under 1500 words: 1. MISSING DECISIONS (owned by no row, or a requirement dimension marked N/A
> that the asks touch — which D<n> should take it, or does it need its own; do not manufacture one). 2. MIS-PARTITIONS (a row that is two
> decisions; one question split across two rows so both will rule on it). 3. WRONG SETTLED ROWS
> (misquoted, over-stated, contradicted by a later ruling — verify quotes — or recording what today's
> code does as a ruling: name the fix it forecloses, F86). 4. WRONG CLAIMS about the
> code in the defects table or rows. 5. The single riskiest framing error, and the one question
> agents are most likely to answer inconsistently. 6. TEMPLATE LINES — against <the decision-brief
> template>: every brief sentence false for this repo (a mechanism it lacks), and every unmarked
> template paragraph the brief dropped or changed; print both counts.
> Reply <3 KB: counts per heading, the riskiest framing error, the path.

## §1b — A decision agent

> You are a decision agent in <project>'s phase-<P> decision round. Repo root: <repo>. Read
> `<planning-dir>/DECISION-BRIEF-p<P>.md` FIRST and follow it exactly — it is your contract. Then
> `00-index.md` in full (SETTLED, confirmed defects, the decisions, and "What each decision may NOT
> decide"), then the harvest files. YOUR DECISION: **D<n> — <title>.** Write your ruling to
> `<planning-dir>/decisions/phase<P>/D<n>-<slug>.md`. Focus (from the index row; the row is
> authoritative): <the specific questions, the disputed sources by harvest id, the defects it owns,
> the neighbour boundaries it must respect, and "or say first why the framing is wrong">.
> <N−1> other agents are ruling the other decisions in parallel right now. <the closing lines>
> Reply: the ruling in three sentences, the bindings by number, what the user must decide, the path.

## §1c — Seam review of all rulings (second model; unavailable: Lead mechanics)

> You are the seam reviewer of a decision round — the step before an arbiter writes rulings that WIN
> over the decision files. Read-only; throwaway probes allowed under <scratchpad>/seam/. Inputs: the
> brief, the index, and all N rulings. Each was written independently; partitioning by decision
> leaves the SEAMS unsettled by construction. Your job is the seams. <Leads already known — verify,
> do not assume: list any conflicts you saw in the agents' replies.> Report into
> `<planning-dir>/decisions/phase<P>/00-seams.md`, each finding opening `**R<n>**`, numbered on
> through every heading, with file:line on every side:
> A. BLOCKERS (cannot both be implemented — which side wins and why, ≤2 sentences) · B. WRONG CODE
> CLAIMS (what is actually there) · C. UNOWNED (assumed landed by someone else, taken by no one —
> natural owner) · D. SETTLED-ROW OVERTURNS (does the argument hold?) · E. SAFETY (anything that
> could still destroy data or claim a guarantee the product lacks — be adversarial, probe) ·
> F. SCHEMA/MIGRATION COLLISIONS (every delta by ruling; same name twice; one table rebuilt twice) ·
> G. USER DECISIONS (deduplicated, grouped by how much each changes what gets built) · H. UNASKED
> (a ruling that changes something no row of the index's asks names, or an item on its Do not touch
> list — quote the nearest ask). Write the file
> first; reply <3 KB: counts per heading, the five worst blockers, the path.

## §1d — Supersede markers (one agent judges, a script inserts)

> You mark which paragraphs of the phase-<P> decision files `D1…D<N>` under
> `<planning-dir>/decisions/phase<P>/` the rulings override; a script inserts the markers — edit no
> file by hand. Read `00-arbiter.md` in full first; `00-seams.md` carries the file:line each ruling
> cites; then read every `D` file in one turn. For every paragraph, table row or bullet a U- or
> A-ruling overrides, add one entry to `<planning-dir>/decisions/phase<P>/00-markers.json`:
> `{"file": "D<n>-<slug>.md", "anchor": "<verbatim text from that block, unique in the file>",
> "ruling": "A<n>", "clause": "<one clause: what now holds>"}`. Then run
> `<skill-dir>/scripts/apply_markers.py <planning-dir>/decisions/phase<P> <that file>`: it puts
> `> **SUPERSEDED BY A<n>** — <clause>.` directly above the block, adds
> `> **Read 00-arbiter.md first.**` under each marked file's title, never deletes or rewrites text,
> and refuses an anchor that is missing or not unique. Fix each refused entry with a longer anchor
> and re-run — markers already in place are skipped. If you believe a ruling overrides a paragraph
> but the arbiter does not clearly say so, don't mark it — list it. Reply <2 KB: the script's
> per-file table, and the ambiguous paragraphs left unmarked.

## §1e — The S review (second model, read-only; after the plan, before execution)

> You are the one independent reviewer of a phase-<P> round a lead wrote alone at rung S: a
> decision document, one spec file and one plan, with no decision agents, spec authors or
> reconcilers behind them. Read-only; throwaway probes allowed under <scratchpad>/review/. Read
> `<planning-dir>/decisions/phase<P>/00-index.md` (the decision document), <the spec file> and
> <the plan>. The outputs of `plan_lint.py`, `scope_check.py` and `criteria_check.py` are pasted
> below: report what they miss, not what they print. Consult the code to verify. Answer as one
> list, each finding opening `**R<n>**`, numbered on through every heading, with file:line on
> every side, blunt: 1. THE DECISION DOCUMENT — MISSING DECISIONS
> (owned by no row, or a requirement dimension marked N/A that the asks touch; do not manufacture
> one) and WRONG SETTLED ROWS (misquoted, over-stated,
> contradicted by a later ruling — verify quotes — or recording what today's code does as a ruling:
> name the fix it forecloses; the lead re-opens that row and never adopts the gap as a default,
> F86). 2. ITS RULINGS AGAINST THE CODE — A. BLOCKERS
> (cannot both be implemented) · B. WRONG CODE CLAIMS (what is actually there) · C. UNOWNED
> (assumed landed by someone, taken by no one) · E. SAFETY (anything that could destroy data or
> claim a guarantee the product lacks — be adversarial, probe). 3. THE SPEC — a value with two
> owners; a criterion that cannot fail. 4. THE PLAN — a criterion with no task or no test file; a
> promised file with no task; a task that names no test; a change no ask names, or an item on the
> Do not touch list. Reply <3 KB, the answer itself, counts
> per heading first; the lead saves it as `<planning-dir>/decisions/phase<P>/00-seams.md`.

## §1f — The claim-only verifier (a finding you would decline; a disputed sins finding)

No prompt to write: `scripts/decision_check.py <decisions-dir> --verifier R<n> --sha <commit>`
writes `verify/R<n>.prompt.md` — the finding's text and the commit, nothing else: no SETTLED list,
no rationale of yours, no reviewer's name, so the verifier judges the claim and not the framing.
Send that file unchanged: to the second model (it costs no Claude usage), or as a `dsp-deep`
agent named `verify-R<n>` — the hook refuses any other prompt for that name. It writes a test in
a fresh worktree of the commit and `verify/R<n>.md`: UPHELD (apply the finding), REFUTED (the
only basis to decline it without a ruling), NO-TEST (at M and L ask the user; at S apply the
reviewer's fix as a default and flag it in the handoff). A REFUTED counts only with the claim
quoted and the test failing on a mutant that makes the claim true: `decision_check.py` reads both
lines. **Why:** published, generated tests were jointly valid on 9.21% of tasks, and a test
that cannot see the defect passes either way.

---

## §2 — A spec author

> You are a spec author in <project>'s phase-<P> spec round. Repo <repo>. Read
> `<planning-dir>/SPEC-BRIEF-p<P>.md` FIRST and follow it exactly. YOUR SECTION: **§<n> — <title>**,
> file `<planning-dir>/spec/<n>-<slug>.md`. Owning rulings: <D<k>; U…; A…>. Scope-section defect
> rows assigned to you: <list>. Ownership to respect: <values another section owns that you
> cross-reference, e.g. "the day-one anchor is §43's; you read it">. <N−1> other authors are writing
> the other sections in parallel; write only your file. <closing lines> Reply per the brief's
> output list, <3 KB.

**Register folder** (after `criteria_check.py` exits 0 on the spec): one agent writes the register
section — ids, owning sections and counts **pasted from `criteria_check.py --emit-register`**, never
re-derived — plus the earlier criteria that move and the gates that are wrong today.

## §3 — A reconciler

> You are a reconciliation agent for <project>'s phase-<P> spec. Read
> `<planning-dir>/RECONCILE-BRIEF-p<P>.md` FIRST. YOUR DIMENSION: **<a kept row of the brief's §3,
> or `all`>** — <one sentence of what it reads for>. Read EVERY phase-<P> spec file along it.
> Write `<planning-dir>/reconcile/p<P>-<dimension>.md`. <closing lines> Reply ≤20 lines.

## §4 — A plan author

> You are a plan author for <project>'s phase-<P> plan round. Read
> `<planning-dir>/PLAN-BRIEF-p<P>.md` FIRST, then `plans/p<P>-00-index.md` (your migration numbers,
> the delta, the rulings — they are requirements — and your reading-map row: read other sections at
> its anchors, not whole). YOUR PLAN: **p<P>-<nn>-<slug>** for §<n>, wave
> <w>, depends on <plans>. Write `<planning-dir>/plans/p<P>-<nn>-<slug>.md` and
> `<planning-dir>/manifests/p<P>-<nn>-<slug>.json`. Run `plan_lint.py`, `scope_check.py` and
> `scope_check.py --asks <decision-index> <arbiter>` on your file before replying; all must pass. <closing lines> Reply per the brief's output list, <3 KB.

---

## §5 — A wave integrator (Stage 5, one per wave; `execution.md`)

It commits merges and runs gates, so it does not end with the closing lines. Its `name` is
`exec-wave<w>`: the route's hooks find Stage 5 agents by the `exec-` prefix.

> You integrate wave <w> of <project>'s phase-<P> plans into `<main-branch>` at <repo>, locally:
> never push, open a PR or rewrite history. No lane of this wave is running. Lanes in the plan
> index's order, with the SHA each reported: <plan-id → SHA, worktree>. Baseline gate on <SHA>:
> <counts; failing-test identities>. For each lane: 1. confirm its checkpoint
> (`<planning-dir>/lanes/<plan-id>-checkpoint.md`) names that SHA and its lane gate log
> (`<planning-dir>/lanes/<plan-id>-gate.log`) opens `sha=<that SHA> dirty=0` and ends `exit=0` — a
> lane SHA without one: stop and record it — and that
> `<skill-dir>/scripts/scope_check.py <planning-dir>/plans --glob '<plan-id>-*.md' --diff <wave base>..<SHA> --repo <repo>`
> exits 0 — a file outside the lane's plan: stop and record it — and that `test_check.py` with the
> same arguments exits 0 — a test deleted or removed that the plan does not name, a skip added,
> assertions dropped or an acceptance test edited: stop and record each line it printed — then merge exactly that SHA, never
> the branch name. 2. Resolve conflicts; regenerate every derived file and count (<codegen, locks>),
> never hand-merge them. 3. Run the full gate with its whole output to
> `<planning-dir>/lanes/wave<w>-<plan-id>-gate.log` — never piped through `tail` or `head` — exactly
> `{ echo "sha=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | grep -c .)"; <command>; echo "exit=$?"; } > <log> 2>&1`
> (the push guard accepts a commit only by that first and last line), and hand-check every file both sides touched: the values, not only that
> it compiles. 4. `git merge-base --is-ancestor <sha> HEAD`. A red gate or a failed check: stop,
> leave the merge as it is and record it — the lead rules the fix. Then clean <the build caches that
> accumulate stale artefacts>. <Last feature wave: also run the unwired-producer audit (<command>).
> After the register lane: drive the real product once (<how>) and record what you ran and saw, with
> screenshot paths.> Commit messages: <the commit rules — the subject convention the repo's `git log`
> shows (a `type:` prefix, a scope), lengths, trailers; state them; subagents default to adding
> their own trailers>. Write `<planning-dir>/lanes/wave<w>-integration.md` first: per lane a line
> `Merged <plan-id> <lane SHA> → <the merge commit's SHA on <main-branch>>`, each conflict and its resolution, the files regenerated, the gate's exit
> status, counts and failing-test identities against the baseline, the files both sides touched and
> what you checked; then the new `<main-branch>` SHA. Reply <2 KB: per lane green or red with its
> gate counts, the new SHA, the path.

## §6 — A seven-sins reviewer (at L: Stage 3 spec mode, Stage 5 code mode per slice; or asked)

Seven at once, each `name`d `<sin>-<review name>`; the prompt is in `sins/lead.md` §2. It does not end with
the closing lines — `sins/protocol.md` carries the skeleton, the one reply and where probes go.
