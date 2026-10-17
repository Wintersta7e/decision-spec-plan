---
name: decision-spec-plan
description: "Run the decision → spec → plan route for a large phase, milestone or multi-subsystem feature: harvest what exists, rule each open decision with one agent per decision, cross-model and seam review, ask the user the few calls that matter, write an arbiter, then write the spec one author per file, reconcile by seam, and write executable plans one per lane for wave execution. Use this whenever the user asks to spec, specify, design or plan a phase, milestone, version or roadmap item that has several open design questions or will be built by parallel agents — 'spec the next phase', 'write the decision brief', 'plan v2', 'do it the way we did the last phase', 'let's plan the next milestone properly' — even if they don't name the route. Not for a single feature with one obvious design (use brainstorming + test-driven-development) or for a bug. Load it first for a seven-sins review too ('summon the sins team', 'run the seven sins on this'): the sins run inside this route."
---

# Decision → Spec → Plan

A route for turning a vague phase ("Offline sync", "Billing v2", "Plugin system") into executable,
parallelisable plans **without the contradictions that independent agents produce**.

**The partition changes with the stage**: decisions **by decision**, one agent each, same brief —
open questions are where agents invent two answers for one thing; the spec **by file**, one author
each — once decided, the risk is two authors writing one document; reconciliation **by seam** (wire,
store, values, edges, bar) — the fact falls *between* files; plans **by lane**, one agent's
executable unit in one worktree. ~40 agents by spec section left **105** cross-section
contradictions; ~10 by decision, with an arbiter settling the seams, left **1** (`failure-modes` F1).

**You are the lead.** Above rung S you never write a decision, a spec section (other than the scope
section) or a plan. You **frame, verify, arbitrate and index**, and you re-verify every code claim
before you rule on it. The route's quality is set by three things you control: **the briefs** (agents
are exactly as disciplined as the brief they were handed), **the framing** (a wrong index row costs a
whole agent round), and **your own verification** (a ruling on an unverified claim propagates into
every plan).

## Pick a rung — and say which

| Rung | When | Shape |
|---|---|---|
| **S** | 1–3 open decisions, one plan — **and always** a PR/MR review, a review-fix round or a proposal-only ticket, whatever its count (`failure-modes` F50; an S build: `costs.md`) | **You write the decision document (`templates.md` §1), the one spec file and the one plan**, each to its brief, uncopied; harvest inline; fresh groups execute the plan (`execution.md`), never you. One second-model review after the plan (`prompts.md` §1e; unavailable: Lead mechanics) replaces both reviews. No dispatch file, arbiter, markers, register fold or plan index; the scope tables open the spec file |
| **M** | 4–7 decisions, or fewer needing several plans | Harvest inline or by one agent; 2–4 spec authors; reconciliation per Stage 3. Every other step as at L |
| **L** | 8+ decisions, several subsystems | The full route |

**Say which, why, the headcount, the tiers and the cost** — agents per stage, summed; each role's
tier (`prompts.md` header: deep, this session's model and `/effort` by name, unless the user moves a
role); each stage's wall-clock and each role's expected cost, summed, per `references/costs.md` —
never an estimate. **Name every other active route on the account** (`--activate` lists them;
Quota, below).
**At M and L, wait for the user's go-ahead before the first dispatch** — once, not per stage; the
answer may stop the round, cut a role, or move one to the mechanical tier (`failure-modes` F45 has
what that tier lost when replayed). Restate the headcount when the index fixes it.

**New to the project?** If it has no planning directory, handoff file, charter, spec directory or
checkers, read `references/bootstrap.md` first and build the minimum before stage 0.

## Files in this skill — read each when its stage starts

| File | Read when |
|---|---|
| `references/briefs/decision-brief.md` · `spec-brief.md` · `reconcile-brief.md` · `plan-brief.md` | Writing that stage's brief. **Full text** — copy, fill every `‹ADAPT›`, keep its unmarked rules (Adapt, don't trim, below) |
| `references/templates.md` | §0 (planning-dir layout, numbering) before the first file or number; then each lead document: the decision index (§1), the arbiter (§2), the scope section (§3), the plan index (§4) |
| `references/prompts.md` | Dispatching any agent: every role's prompt, the tiers, the closing lines |
| `references/costs.md` | The rung announcement and every gate: cost per role, wall-clock, units |
| `references/examples.md` | Judging your own draft — rows, fences, rulings, questions, boundaries at the strength that worked |
| `references/failure-modes.md` | When an agent pushes back on a rule, or you are tempted to skip one — the evidence for every rule |
| `references/execution.md` | Stage 5 |
| `references/sins/lead.md` | At M and L: Stage 3, and before every push — the seven-sins review |
| `references/bootstrap.md` | A project running the route for the first time |
| `scripts/plan_lint.py` · `scripts/scope_check.py` · `scripts/criteria_check.py` | Stage 2 and 4 gates |
| `scripts/usage_report.py` | Every gate: the round's cost so far, per agent, with turns and context per turn |
| `scripts/route_state.py` | `--activate` (The route, below), `--budget` (Quota); its hook (`--hook`, registered per its docstring) is the in-flight block's state |
| `scripts/push_guard.sh` | A PreToolUse:Bash hook, active while the route is: blocks a push of any commit no full gate passed (`execution.md`) |
| `scripts/apply_markers.py` | Stage 1 markers: inserts the markers agent's JSON list |

**Adapt, don't trim.** A brief's unmarked rules answer recorded failures or the user's standing
calls (`failure-modes.md`), and no eval re-checks most of them — a brief shortened to save tokens
loses them silently. Replace `‹ADAPT›` blocks with the project's own facts, **with file:line**; if a
block does not apply, say so in one line rather than deleting the heading. **An unmarked sentence
false for this project** (it names a mechanism the project lacks) is rewritten to name what plays
that role — kept verbatim, such a line failed two graded runs.
A rung omits only what its row in the rung table names.

## Precedence — state it in every brief

**The user's rulings (U) > the arbiter's rulings (A) > a decision file. The code beats any document
that describes it wrongly.** Between sources use the project's ladder (typically *measured results >
spec > design handoff, visual only > synthesis > concept*). **A number carries the SHA it was
measured on.**

## The route

Each stage ends at a **gate**. Don't start the next stage until it holds. **Update the handoff at
every gate** — record the stage's wall-clock (first dispatch to last return), headcount, tiers and
`usage_report.py` cost; the next rung announcement quotes them — and its *in flight* block (agents
running, the file each writes, the next action) **at every dispatch and every return**: the lead
compacts mid-stage, and a lost session or a compaction must lose nothing.
**At the rung announcement run `scripts/route_state.py <planning-dir> --phase <P> --repo <repo>
--activate --rung <S|M|L>`** — again at each new phase, in every new lead session (a `--resume`d one stays
registered), and with `--sections <first>-` once the first section number is known. Its hook then
injects what changed — every expected file and how it ends, lane SHAs, gate exits — on your tool
calls and agents' returns, in place of a probe per turn; you write the next action (`failure-modes`
F57, F62). **After a compaction or a resume** it injects the whole state and names what to
re-read, and on a tool call after this skill changed, its changed files; read them before the next
action (F61, F78). **Tell the
user in a line or two whenever an agent returns**: what came back, what it changes, what is still
running.

### Stage 0 — Harvest (every rung)

Three agents in parallel (`prompts.md` §0): **spec** (every deferral to this phase, verbatim with
file:line), **code** (what the tree records for this phase and **whether each producer has a
production caller** — run the project's unwired-producer audit if it has one, otherwise check each
relevant producer's callers outside tests; a test-only producer is the commonest defect this finds),
**design** (every ruling, idea and open question, with a *nobody has decided this* list). **A fourth
harvester names the question only it answers**, and the announcement carries its cost
(`failure-modes` F51). Below L you may
harvest yourself — the same three questions still get answered. **Tell every harvester to probe, not just read**: a claimed defect gets a throwaway
reproduction, a third-party figure gets a cheap read-only request, and each fact is labelled
*measured* or *by reading*. The runs that found the most found it by running something.

**Gate**: you have read the three files' conflict, unspecified and defect sections, and
**reproduced any claimed shipped defect yourself** (a probe repo, a query, a run). A verified
data-loss or safety defect goes to the user immediately, with a proposed fix — not at the end.

### Stage 1 — The decision round

1. **Write the brief** (`briefs/decision-brief.md`) **and the index** (`templates.md` §1), and check
   the index against §1's pre-dispatch list — each item there was a real framing error somewhere.
2. **Framing review before dispatch** — a second model, read-only (`prompts.md` §1a; unavailable:
   Lead mechanics). Apply its corrections to the index and brief before dispatch.
3. **Dispatch one agent per decision** — in one message (at most 8: Lead mechanics), background,
   same brief, a focused paragraph each that names the disputed sources and any measured defect
   (`prompts.md` §1b). **Write those focus paragraphs to `decisions/phase<P>/00-dispatch.md` before
   dispatching** — when the user asks you to stop at "ready to dispatch", this file is what *ready*
   means, and a round without it is not ready.
4. **Seam review of all rulings** (`prompts.md` §1c) by the second model (unavailable: Lead
   mechanics).
5. **Ask the user the calls that change what gets built** — `AskUserQuestion` takes **at most four**
   per call, so rank them and ask the four that most change the architecture; recommended option
   first, **each option stating its consequence** so you can rule the fallout without a second
   round-trip. A fifth question is not asked: it becomes a default the user may overturn, listed in
   the arbiter. (The same limit applies when you write `user-questions.md` instead of asking.)
   Tell the user anything they should know that an agent did (e.g. read their personal data).
6. **Write the arbiter** (`templates.md` §2): U-rulings first, then A-rulings grouped by topic,
   each citing the seam item, which side won and why, what each losing ruling must now say — **and
   the code claims you re-verified in this session, listed**. Include the sequencing (a **Lane 0** of
   shipped defects and false published claims that lands before any feature) and the defaults.
7. **Apply supersede markers** — one agent judges and lists them, `scripts/apply_markers.py`
   inserts them (`prompts.md` §1d).

**Gate**: every decision file exists; every seam blocker is ruled (at S: after the plan, §1e); the
user's calls are answered; markers applied.

### Stage 2 — The spec round

1. **Write the scope section yourself** (`templates.md` §3) — it binds every author; its contract
   rules also name who owns each shared read and which table is rebuilt once, by whom.
2. **Write the spec brief** (`briefs/spec-brief.md`) and dispatch one author per file
   (`prompts.md` §2), each told which shared values another section owns.
3. When all have replied, run `scripts/criteria_check.py <spec-dir> --phase <P> --sections <a>-<b>`
   (every section that defines criteria; at S, the one spec file): it derives each section's
   criterion ids from its acceptance list and prints counts, gaps, duplicates and id-less items.
   **Never a regex over full ids** (`failure-modes` F19). Then **one agent folds the register**,
   pasting the table
   `criteria_check.py --emit-register` prints.
4. **Keep a returns log** (`decisions/phase<P>/spec-returns.md`): as each author replies, append its
   delta, supersessions and disagreements. It is the reconcilers' "already known" list and the plan
   index's first source of rulings; without it they live only in replies that a compaction loses.
   When one author's return changes what a still-running author must write (a scrub list, a call it
   must make), **message that author now** rather than leaving it to reconciliation.

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
3. **Lint mechanically**: `scripts/plan_lint.py <plans-dir>`, `scripts/scope_check.py <plans-dir>`
   (every file a File-structure table promises is created somewhere) and `scope_check.py
   <plans-dir> --waves <index>` (no file changed by two plans that run at once; F82). Each prints
   counts and exits non-zero on a problem; `scope_check` is a heuristic (`failure-modes` F25).
4. Rule the plan authors' challenges — they find arbiter mistakes; that is the round working.

**Gate**: every plan lints `ok`, scope-check reports 0 both ways, `criteria_check.py --plans <plans-dir>`
exits 0 — every criterion maps to a task and a test file, and you read every printed MANUAL line.

### Stage 5 — Execution

`references/execution.md`: lanes of fresh task-group agents, one integrator per wave, you check
its SHAs first-hand. Every outward action (push, PR, release) is asked for when it happens (F81), and a
push sends only commits a full gate passed (`push_guard.sh`) — at M and L, only ones a seven-sins
verdict covers (`sins/lead.md`, code mode; F70).

## Lead mechanics

- Agents: the Agent tool, `run_in_background: true`, independent dispatches in **one message, at
  most 8 per message** — larger fan-outs hit "Lock file is already being held", and a spawn that
  hit it never started: dispatch it again (F65). Each role on its tier from the
  `prompts.md` header (`dsp-deep`, `dsp-mechanical`, or `general-purpose` for a tool outside their
  lists). The Workflow tool only with the user's explicit opt-in (`/effort ultracode` is one).
- A prompt no brief covers (a repair round, an ad-hoc role) ends with `prompts.md`'s closing lines
  and carries, by name, the rules every brief carries (listed there). **Never have one agent emit
  N large items** — fan out one agent per item.
- The second model (`codex-delegation`), where the user has one, reviews: the framing, seam and
  cross-model passes, read-only; its usage is not Claude's. Its model and effort come from its own
  configuration, never from this skill. Poll a background job by its **state line**, never a
  keyword (F39).
- **The second model unavailable** (none, quota, outage): run its prompt on a `dsp-deep` agent now;
  the review lands in the file the prompt names either way. Record which ran in the handoff and
  the arbiter header. On its return it reviews the earliest artefact nothing is built on yet:
  index and brief before dispatch, rulings before the arbiter, else arbiter and spec. At S: record
  it in the decision document's header; on return, the second model reviews the same three
  documents.
- An agent whose write was refused falls back to the scratchpad (the closing lines); you copy the
  file.
- **Never rewrite a ruling in place while an agent may be reading it** — append, mark the old text,
  and quote rulings verbatim in any message about them. **A `SendMessage` reaches a busy agent only
  when it goes idle** — after it has replied (F59); a ruling for a running lane goes
  to its rulings file (`execution.md`). An idle notice repeating a return you have: one line, no
  tool call (F69).
- **Never batch several edits to one file in one message**, yours or an agent's.
- **Measure before ruling.** When two agents disagree about the tree, open the code or run a probe.
- Collect the user's calls as they surface; ask them together, at the arbiter.
- **Quota.** Routes on one account share its weekly limit — four at once hit it in a day and
  stalled 62.7 h (`failure-modes` F63). Before dispatching a stage estimated at ≥20M, quote
  `usage_report.py`'s figures so far and the stage's estimate; a Stage 5 wave's goes to
  `route_state.py --budget`, whose hook holds `exec-` dispatches until the user answers, then
  gives each an ETA to tell them (`execution.md`, F83). When a stage runs >25% over its announced headcount, or the round grows into
  the next rung, re-announce and wait for the user.
- **The route runs unattended** — never ask the user to `/clear` or restart mid-route. The lead's
  context stays small through an auto-compact window ≈ 300000 (`autoCompactWindow` in settings, per
  model under `modelSettings`, or `CLAUDE_CODE_AUTO_COMPACT_WINDOW`): without it leads grew to
  ~965k, where every turn costs ~0.1M (`failure-modes` F47). If the window is unset at the rung
  announcement, say so.
- **A stopped agent is resumed, not re-dispatched.** After a session or spend limit, `SendMessage`
  the same agent to continue from its file — its transcript survives; a fresh dispatch repays its
  whole exploration (`failure-modes` F49). Check its file's end first (F38). Resuming finishes the
  agent's own work; new work — an execution lane's next task group above all — goes to a fresh
  agent (`execution.md`). **After a lead restart, `ListAgents` first**: an agent not listed is
  unreachable ("No agent named … is reachable") — dispatch a fresh one told to continue from its
  file, whose skeleton the closing lines had it write first (F64).
