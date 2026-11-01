# Bootstrapping a project that has never run the route

The route's effectiveness in a mature project comes partly from what that project accumulated: a
charter, a spec directory with owners, a handoff file, mechanical checkers, and a standing list of
the defects that recur. A new project has none of it. Build the minimum **before stage 0**, and tell
the user what you created.

## 1. The planning directory — private, gitignored

- Pick `<planning-dir>` (`.dev/` is a good default) and add it to `.gitignore` **before** writing
  into it. It will name real paths, real third-party projects and unreleased plans.
- Create `HANDOFF.md` there. **Update it at every stage boundary** with: the SHA, what is done, what
  is in flight (which agents, writing which files), the next action, and anything the user owes —
  and its in-flight block at every dispatch and return, since the lead may compact mid-stage. A lost
  session must lose nothing: check each claim (SHA, test result, file state) before writing it. **Keep it
  under 40 KB — one `Read`**: closed lanes, settled rulings and old gate records move to
  `HANDOFF-archive.md`, which no one re-reads by default (`route_state.py` flags a larger file).
  **Why:** one lead re-read an 80 KB handoff — past the `Read` cap, two reads each time — after each
  of seven compactions and rewrote it 38 times: 1.4M (`failure-modes` F76).

## 2. The charter — what the phase *is*

The decision round needs a charter to quote with file:line. If the project has a concept/roadmap
document, use it. If not, **write a one-page charter with the user first**: the phase's goal, what is explicitly out, the release it belongs to, and
the non-goals. Everything later cites it; a phase framed from memory produces decisions nobody can
check.

## 3. The spec directory — owners from the start

- One file per section, numbered `§N` and **stable across files**; a `README.md` indexing them with
  a **one-value-one-owner table** (which section owns each value others reference).
- The first phase's first section is a scope section (`templates.md` §3). Later phases append; they
  never renumber.

## 4. The standing defect list — in the project's instructions

Put a short **defect-patterns section** into the project's `CLAUDE.md` (or equivalent), one line
each, and grow it every round:
- a seam declared for testability gets its fake and never its production implementation;
- a bar written past its defect proves the wrong thing;
- one value stated twice drifts;
- a name collision is not evidence of a duplicate;
- an absolute count asserted in a lane is wrong after the merge.
These are what every brief's "defect patterns" paragraph cites. `failure-modes.md` has the evidence.

## 5. Mechanical checkers

- Copy `scripts/plan_lint.py`, `scripts/scope_check.py` and `scripts/criteria_check.py` into the
  project's **local** tool directory (inside `<planning-dir>`, not a committed `scripts/`, unless the
  build or CI runs them). Adjust `--require` fields and `--ext` if the project's plans or languages
  differ.
- **An unwired-producer audit** for the project's languages, before any phase is registered: list
  every new public function/type/command and check each has a caller outside tests. With symbol
  tooling (an LSP, Serena, `ast-grep`) this is a short script; without it, a manual pass over the
  diff. Six uncalled producers once sat behind all-green suites.
- **A full-gate script** that runs every suite and writes every result file the acceptance bar
  reads, so nobody hand-captures a partial run.

## 6. An acceptance register

Criteria are prose in the spec (`AC-P<P>-<section>-<n>`); the register maps each to the test that
proves it. Start simple — a table or a JSON file of id → test name → status — but make a tool count
it; `criteria_check.py` counts the spec's ids and checks the plans map each one. **Never untag a test
to go green.**

## 7. The second model

If the user has a second model the lead can call read-only, confirm it works with one tiny
read-only request **before** the round depends on it, and note its quota behaviour
(unavailable: Lead mechanics).

## Scale it down honestly

For a young project the right rung is usually **S** or **M**; SKILL.md's rung table says what each
omits. Say which rung you chose and why.
