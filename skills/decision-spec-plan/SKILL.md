---
name: decision-spec-plan
description: "Run the decision → spec → plan route for a large phase, milestone or multi-subsystem feature: harvest what exists, rule each open decision with one agent per decision, cross-model and seam review, ask the user the few calls that matter, write an arbiter, then write the spec one author per file, reconcile by seam, and write executable plans one per lane for wave execution. Use this whenever the user asks to spec, specify, design or plan a phase, milestone, version or roadmap item that has several open design questions or will be built by parallel agents — 'spec the next phase', 'write the decision brief', 'plan v2', 'do it the way we did the last phase', 'let's plan the next milestone properly' — even if they don't name the route. Not for a single feature with one obvious design (use brainstorming + test-driven-development) or for a bug. Load it first for a seven-sins review too ('summon the sins team', 'run the seven sins on this'): the sins run inside this route."
---

# Decision → Spec → Plan

A route for turning a vague phase ("Offline sync", "Billing v2", "Plugin system") into executable,
parallelisable plans **without the contradictions that independent agents produce**.

**The partition changes with the stage**: decisions **by decision**, the spec **by file**,
reconciliation **by seam** (wire, store, values, edges, bar), plans **by lane** — one agent's unit in
one worktree; each brief says why. ~40 agents by spec section left **105** cross-section
contradictions; ~10 by decision, with an arbiter settling the seams, left **1** (`failure-modes` F1).

**You are the lead.** Above rung S you never write a decision, a spec section (other than the scope
section) or a plan. You **frame, verify, arbitrate and index**, and re-verify every code claim before
you rule on it. The route's quality is set by **the briefs** (agents are exactly as disciplined as
their brief), **the framing** (a wrong index row costs a whole agent round) and **your own
verification** (a ruling on an unverified claim propagates into every plan).

## Pick a rung — and say which

| Rung | When | Shape |
|---|---|---|
| **S** | 1–3 open decisions, one plan — **and always** a PR/MR review, a review-fix round or a proposal-only ticket, whatever its count (`failure-modes` F50; an S build: `costs.md`) | **You write the decision document (`templates.md` §1), the one spec file and the one plan**, each to its brief, uncopied; harvest inline; fresh groups execute the plan (`execution.md`), never you. One second-model review after the plan (`prompts.md` §1e; unavailable: Lead mechanics) replaces both reviews. No dispatch file, arbiter, markers, register fold or plan index; the scope tables open the spec file |
| **M** | 4–7 decisions, or fewer needing several plans | Harvest inline or by one agent; 2–4 spec authors; reconciliation per Stage 3. Every other step as at L |
| **L** | 8+ decisions, several subsystems | The full route |

**Say which, why, the headcount, the models and the cost** — agents per stage, summed; the model
and effort you picked for each role, with a one-line reason (`prompts.md` header: the session's model
and effort unless the task calls for another pair); each stage's wall-clock and each role's cost per `references/costs.md`, summed — never an
estimate. **Name every other active route on the account** (`--activate` lists them; Quota, below).
**At M and L, wait for the user's go-ahead before the first dispatch** — once, not per stage; the
answer may stop the round, cut a role, or change a role's model or effort (`failure-modes` F45,
F88: what Sonnet lost, replayed and live). Restate the headcount when the index fixes it.

**New to the project?** If it has no planning directory, handoff file, charter, spec directory or
checkers, read `references/bootstrap.md` first and build the minimum before stage 0.

## Files in this skill — read each when its stage starts

| File | Read when |
|---|---|
| `references/briefs/decision-brief.md` · `spec-brief.md` · `reconcile-brief.md` · `plan-brief.md` | Writing that stage's brief: **full text** — copy, fill every `‹ADAPT›`, keep its unmarked rules (below) |
| `references/templates.md` | §0 (layout, numbering) before the first file or number; then each lead document — decision index §1, arbiter §2, scope section §3, plan index §4 |
| `references/prompts.md` | Dispatching any agent: every role's prompt, its model and effort, the closing lines |
| `references/costs.md` | The rung announcement and every gate: cost per role, wall-clock, units |
| `references/examples.md` | Judging your own draft against rows, fences, rulings, questions and boundaries that worked |
| `references/failure-modes.md` | An agent pushes back on a rule, or you are tempted to skip one: every rule's evidence |
| `references/execution.md` | Stage 5 |
| `references/sins/lead.md` | At M and L: Stage 3, and before every push — the seven-sins review |
| `references/bootstrap.md` | A project running the route for the first time |
| `scripts/plan_lint.py` · `scope_check.py` · `criteria_check.py` | Stage 2 and 4 gates |
| `scripts/usage_report.py` | Every gate: the round's cost so far, per agent |
| `scripts/route_state.py` | `--activate` (The route), `--budget` (Quota); its `--hook` is the in-flight block's state |
| `scripts/push_guard.sh` | A PreToolUse:Bash hook while the route is active: blocks a push of any commit no full gate passed |
| `scripts/apply_markers.py` | Stage 1 markers: inserts the markers agent's JSON list |

**A script's `--help` is its whole interface** — read it, never the script's source (F84).

**Adapt, don't trim.** A brief's unmarked rules answer recorded failures or the user's standing
calls (`failure-modes.md`); no eval re-checks most of them, so a brief shortened to save tokens loses
them silently. Replace each `‹ADAPT›` block with the project's own facts, **with file:line** — one
line if it does not apply, never a deleted heading. **An unmarked sentence false for this project**
(a mechanism it lacks) is rewritten to name what plays that role; kept verbatim, such a line failed
two graded runs. A rung omits only what its row in the rung table names.

## Precedence — state it in every brief

**The user's rulings (U) > the arbiter's rulings (A) > a decision file. The code beats any document
that describes it wrongly.** Between sources use the project's ladder (typically *measured results >
spec > design handoff, visual only > synthesis > concept*). **A number carries the SHA it was
measured on.**

## The route

Each stage ends at a **gate**; don't start the next stage until it holds. **Update the handoff at
every gate** — the stage's wall-clock (first dispatch to last return), headcount, tiers and
`usage_report.py` cost, which the next announcement quotes — and its *in flight* block (agents
running, the file each writes, the next action) **at every dispatch and every return**: a lost
session or a compaction must lose nothing.
**At the rung announcement run `scripts/route_state.py <planning-dir> --phase <P> --repo <repo>
--activate --rung <S|M|L>`** — again at each new phase, in every new lead session (a `--resume`d one
stays registered), and with `--sections <first>-` once the first section number is known. Its hook
then injects what changed (every expected file and how it ends, lane SHAs, gate exits) in place of a
probe per turn — you write the next action (F57, F62); after a compaction or a resume, the whole state
and what to re-read; after this skill changed, its changed files. Read them before the next action
(F61, F78). **Tell the user in a line or two whenever an agent returns**: what came back, what it
changes, what is still running.

### Stage 0 — Harvest

Three agents in parallel (`prompts.md` §0): **spec** (every deferral to this phase, verbatim with
file:line), **code** (what the tree records for this phase and **whether each producer has a
production caller** — the project's unwired-producer audit, else its callers outside tests; a
test-only producer is the commonest defect found), **design** (every ruling, idea and open question,
with a *nobody has decided this* list). **A fourth harvester names the question only it answers**,
priced in the announcement (F51). At M you may harvest yourself, answering the same three; **at S
you always do, with no harvester**, whatever earlier rounds did: the hook refuses one (F87).
**Harvesters probe, not just read** — a throwaway reproduction per claimed defect, a cheap read-only
request per third-party figure, each fact *measured* or *by reading*: the runs that found the most
ran something.

**Gate**: you have read the three files' conflict, unspecified and defect sections, and
**reproduced any claimed shipped defect yourself** (a probe repo, a query, a run). A verified
data-loss or safety defect goes to the user immediately, with a proposed fix — not at the end.

### Stage 1 — The decision round

1. **Write the brief** (`briefs/decision-brief.md`) **and the index** (`templates.md` §1) — its
   **asks** first: every sentence the requester wrote asking for a change, verbatim, and a Do not
   touch list; every change the round makes cites one or a user ruling (F89) — and check
   the index against §1's pre-dispatch list — each item there was a real framing error somewhere.
2. **Framing review before dispatch** by the second model, read-only (`prompts.md` §1a); apply its
   corrections to the index and brief before dispatch.
3. **Dispatch one agent per decision** in one message, background, same brief, a focus paragraph
   each naming the disputed sources and any measured defect (`prompts.md` §1b) — **written first to
   `decisions/phase<P>/00-dispatch.md`**: that file is what "ready to dispatch" means.
4. **Seam review of all rulings** (`prompts.md` §1c) by the second model.
5. **Ask the user the calls that change what gets built**, collected as they surface — at most four
   per `AskUserQuestion`, the four that most change the architecture, recommended option first,
   **each option stating its consequence** so the fallout needs no second round-trip. A fifth
   becomes a default in the arbiter that the user may overturn (the same limit in
   `user-questions.md`). Tell the user anything an agent did that they should know (e.g. read their
   personal data).
6. **Write the arbiter** (`templates.md` §2): U-rulings first, then A-rulings by topic, each citing
   the seam item, which side won and why, what each losing ruling must now say — **and the code
   claims you re-verified in this session, listed** — plus the sequencing (a **Lane 0** of shipped
   defects and false published claims that lands before any feature) and the defaults.
7. **Apply supersede markers** — one agent lists them, `scripts/apply_markers.py` inserts them
   (`prompts.md` §1d).

**Gate**: every decision file exists; every seam blocker is ruled (at S: after the plan, §1e); the
user's calls are answered; markers applied.

### Stage 2 — The spec round

1. **Write the scope section yourself** (`templates.md` §3) — it binds every author; its contract
   rules also name who owns each shared read and which table is rebuilt once, by whom.
2. **Write the spec brief** (`briefs/spec-brief.md`); dispatch one author per file (`prompts.md`
   §2), each told which shared values another section owns.
3. When all have replied, run `scripts/criteria_check.py <spec-dir> --phase <P> --sections <a>-<b>`
   (every section that defines criteria; at S, the one spec file) — **never a regex over full ids**
   (`failure-modes` F19) — then **one agent folds the register**, pasting the table
   `criteria_check.py --emit-register` prints.
4. **Keep a returns log** (`decisions/phase<P>/spec-returns.md`) of each author's delta,
   supersessions and disagreements as it replies: the reconcilers' "already known" list and the plan
   index's first source of rulings, safe from a compaction. A return that changes what a
   still-running author must write: **message that author now**.

**Gate**: every section exists; you have every author's delta, supersessions and disagreements;
`criteria_check.py` exits 0.

### Stage 3 — Reconciliation by seam (two or more spec authors)

One agent per kept dimension (`briefs/reconcile-brief.md` §3); one for all at 2–4 spec authors.
They recommend; **you rule all dimensions together** as numbered rulings in the plan index. At M
and L the seven sins review the same sections beside them for what goes wrong once built
(`sins/lead.md`, spec mode; `failure-modes` F71); rule both sets together.
**Gate**: every blocker ruled.

### Stage 4 — The plan round

1. **Write the plan index** (`templates.md` §4): the plan set and wave order, **migration numbers
   assigned once by one hand in dependency order**, the reconciled contract delta stated once, the
   rulings, and a **reading map** — per plan, the anchors it reads beyond its own section.
2. **Write the plan brief** (`briefs/plan-brief.md`); dispatch one author per plan (`prompts.md` §4),
   each writing a plan and a manifest.
3. **Lint**: `scripts/plan_lint.py <plans-dir>`, `scripts/scope_check.py <plans-dir>` (every file a
   File-structure table promises is created somewhere; a heuristic, `failure-modes` F25) and
   `scope_check.py <plans-dir> --waves <index>` (no file changed by two plans that run at once; F82)
   and `--asks <decision-index> <arbiter>` (every planned file cites an ask or a U-ruling; F89).
4. Rule the plan authors' challenges — they find arbiter mistakes; that is the round working.

**Gate**: every plan lints `ok`, scope-check reports 0 all three ways — each change no ask covers
went to the user as a yes or no, and dropped or became a U-ruling — `criteria_check.py --plans <plans-dir>`
exits 0 — every criterion maps to a task and a test file — and you read every printed MANUAL line.

### Stage 5 — Execution

`references/execution.md`: lanes of fresh task-group agents, one integrator per wave, you check
its SHAs first-hand; no lane merges a file outside its plan (`scope_check.py --diff`; at S, you run
it before the push). Every outward action (push, PR, release) is asked for when it happens (F81), and a
push sends only commits a full gate passed (`push_guard.sh`) — at M and L, only ones a seven-sins
verdict covers (`sins/lead.md`, code mode; F70).

## Lead mechanics

- Agents: the Agent tool, `run_in_background: true`, independent dispatches in **one message, at
  most 8** (F65), each with the `model` and `effort` you announced for its role (`prompts.md`). The Workflow tool only with the user's explicit
  opt-in (`/effort ultracode` is one).
- A prompt no brief covers (a repair round, an ad-hoc role) ends with `prompts.md`'s closing lines and
  carries the rules listed there. **Never have one agent emit N large items** — one agent per item.
  An agent whose write was refused wrote to the scratchpad: copy its file.
- The second model (`codex-delegation`), where the user has one, runs the framing, seam and
  cross-model reviews read-only, on its own usage, model and effort — never this skill's. Poll its
  background job by the **state line**, never a keyword (F39). **Unavailable** (none, quota,
  outage): run its prompt on a `dsp-deep` agent now, into the file the prompt names, and record which
  ran in the handoff and the arbiter header (at S, the decision document's). On its return it
  reviews the earliest artefact nothing is built on yet — index and brief before dispatch, rulings
  before the arbiter, else arbiter and spec; at S, the same three documents.
- **Never rewrite a ruling in place while an agent may be reading it** — append, mark the old text,
  quote rulings verbatim in any message about them. **A `SendMessage` reaches a busy agent only when
  it goes idle** (F59); a ruling for a running lane goes to its rulings file (`execution.md`). An
  idle notice repeating a return you have: one line, no tool call (F69).
- **Never batch several edits to one file in one message**, yours or an agent's.
- **Measure before ruling.** When two agents disagree about the tree, open the code or run a probe.
- **Quota.** Routes on one account share its weekly limit — four at once hit it in a day and
  stalled 62.7 h (`failure-modes` F63). Before a stage estimated at ≥20M, quote `usage_report.py`'s
  figures so far and the estimate; a Stage 5 wave's goes to `route_state.py --budget`, whose hook
  holds `exec-` dispatches until the user answers, then gives each an ETA to tell them
  (`execution.md`, F83) — headless (`claude -p`) it holds nothing: record the budget anyway and
  report it at the end. A stage >25% over its announced headcount, or grown into the next rung:
  re-announce and wait for the user.
- **The route runs unattended** — never ask the user to `/clear` or restart mid-route. An
  auto-compact window ≈ 300000 (`autoCompactWindow` per model under `modelSettings`, or
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW`) keeps the lead small: without it leads grew to ~965k, where every
  turn costs ~0.1M (`failure-modes` F47). Unset at the announcement: say so.
- **A stopped agent is resumed, not re-dispatched**: after a session or spend limit, `SendMessage` it
  to continue from its file, whose end you check first (F38) — a fresh dispatch repays its whole
  exploration (F49). New work — an execution lane's next task group above all — goes to a fresh
  agent (`execution.md`). **After a lead restart, `ListAgents` first**: an agent not listed is
  unreachable ("No agent named … is reachable"); a fresh one continues from its file's skeleton (F64).
