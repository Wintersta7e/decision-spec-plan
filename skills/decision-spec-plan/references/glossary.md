# Glossary

The route's working vocabulary, in reading order. Ids in `code` are the literal prefixes files use.

## Roles and shape

- **Lead** — the session the user talks to. It frames the work, verifies every code claim before
  ruling on it, dispatches agents and arbitrates where their work meets. Above size S it writes no
  decision, spec or plan itself.
- **Size (rung) S / M / L** — how much route a task gets: S for 1–3 open decisions and one plan,
  M for 4–7 or several plans, L for 8+ across subsystems. The size fixes which stages run and how
  many agents each gets (`SKILL.md`, Pick a rung).
- **Stage** — one step of the route: 0 harvest, 1 decisions, 2 spec, 3 reconciliation, 4 plans,
  5 execution. Each ends at a **gate**.
- **Gate** — a condition checked before the next stage starts: files exist, a checker exits 0,
  the user has answered. A gate is mechanical wherever a script can check it.
- **`dsp-deep` / `dsp-mechanical`** — the two agent definitions the route dispatches: deep work on
  the lead's model, mechanical work (a Workflow script's helpers) on a cheaper model.
- **Second model** — any other model the lead can call read-only (another vendor's CLI, say). It
  reviews framing, seams and the finished plan; without one, a fresh `dsp-deep` agent does.
- **Handoff** — the planning directory's `HANDOFF.md`, updated at every gate and every dispatch,
  so a compaction or a lost session loses nothing. Its **in-flight block** lists running agents
  and the file each writes.

## Decisions (Stage 1)

- **Harvest** — Stage 0: what the spec, the code and the design notes already say about the phase,
  each fact measured or read, with file:line.
- **Ask** — a sentence the requester wrote asking for a change, quoted verbatim in the decision
  index. Every change the round makes cites an ask or a user ruling; the **Serves** column names
  the ask each decision answers ("asked by").
- **Backlog** — a change kept out of this round, recorded and not dispatched.
- **Decision record (ledger)** — the round's decision index plus the files it points to: decisions
  `D<n>`, settled facts `S<n>`, rulings and the dispositions of review findings. Checked by
  `decision_check.py`.
- **SETTLED row** (`S<n>`) — a fact the round treats as fixed, with its source. Its source must be a
  ruling or a document, never only "what today's code does".
- **Ruling** — a binding answer: **`U<n>`** the user's, **`A<n>`** the arbiter's. Precedence:
  U > A > a decision file; the code beats any document that describes it wrongly.
- **Arbiter** — the lead's document that settles every conflict between decision files, lists the
  code claims the lead re-verified, and orders the work.
- **Seam** — a place two owners' work meets: a wire format, a store, a shared value, an edge case,
  an acceptance bar. Reviews and reconciliation are cut by seam.
- **Finding** (`R<n>`) and **disposition** — a reviewer's finding and what the round did with it:
  applied, declined (with a ruling or a refuting test), or re-opened.
- **Verifier / REFUTED** — a disputed finding is dismissed only by a test that fails on a mutant
  which makes the finding's claim true; never by argument or vote.
- **Supersede marker** — a note inserted into a decision file where a later ruling overturned it,
  so no reader acts on the stale text (`apply_markers.py`).
- **Lane 0** — the arbiter's list of shipped defects and false published claims; it lands before
  any feature work.

## Spec and plans (Stages 2–4)

- **Section** (`§N`) — one spec file, numbered once and never renumbered. The **scope section**
  opens the phase and binds every author.
- **Acceptance criterion** (`AC-P<P>-<N>-<n>`) — a testable statement in a section; the
  **register** maps each one to the test that proves it (`criteria_check.py`).
- **Reconciliation** — Stage 3: one agent per seam dimension reads every section for
  contradictions; the lead rules them all together.
- **Plan index** — the lead's Stage 4 document: the plans, their wave order, migration numbers
  assigned once, the reconciled contract and a reading map.
- **Plan** — one lane's executable task list, linted by `plan_lint.py` and `scope_check.py`.

## Execution (Stage 5)

- **Lane** — one plan executed in its own git worktree and branch.
- **Wave** — the lanes that run at the same time; no two of them change the same file
  (`scope_check.py --waves`).
- **Task group** — a fresh agent that carries a few of a lane's tasks and returns; the next group
  starts from its **checkpoint** file instead of a long-running agent's growing context.
- **Rulings file** — a lane's `lanes/<plan>-rulings.md`, where the lead's rulings for a running lane
  go (a message reaches a busy agent only when it goes idle).
- **Integrator** — the agent that merges a wave's lanes into main, one exact SHA at a time, and
  runs the full gate after each merge.
- **Gate log** — the evidence that a gate passed on a commit: `lanes/<name>-gate.log`, written by
  **`gate.py`** with the commit (`sha=`), whether the tree was clean (`dirty=`), the command, its
  output and its status (`exit=`). Never written or edited by hand.
- **Push guard** — `push_guard.py`, run as git's pre-push hook (installed by `--activate`): it holds
  a push of any commit without a passing gate log (and, where configured, a CI-harness log and a
  pre-push review). A Bash hook holds `--no-verify`, and checks every push command where the
  repository's hooks live elsewhere.
- **CI harness** — a suite only CI runs (another database, another OS). With `--ci-harness`, every
  push also needs a gate log naming it, except `<commit>:refs/heads/<branch>` to a branch other
  than main — the push that starts the CI run.
- **Budget hold** — `route_state.py --budget` records the route's estimate, once, at the go-ahead;
  the hook holds `exec-` dispatches until the user answers (at S, never), and asks again past 125%
  of the estimate.
- **Units (M)** — the route's cost unit, about a million Opus-input-equivalent tokens
  (`costs.md`).

## Review

- **Seven sins** — the route's adversarial review panel: seven reviewers, each looking for one way
  a change goes wrong once built, with every finding reproduced before it counts
  (`sins/lead.md`).
- **Slice** — a review unit of at most 30 commits; a larger push is reviewed slice by slice,
  because review recall collapses on a large diff.
- **F-codes** (`F<n>`) — rows of `failure-modes.md`: a recorded failure, its cost, and the rule or
  hook that answers it. A rule's evidence, not something to learn first.
