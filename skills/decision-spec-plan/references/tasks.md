# Any task the user hands you

The route is a shape for the work. Run the task the user named, at the rung its open decisions
need, and never swap in the skill's nearest stage. Where the user names one step ("hunt bugs",
"just review it", "no spec"), do that step, and offer the rest without running it. **Why:** asked
for a bug hunt, a lead recommended a ~5M review panel instead; the user: "Scratch 7 sins run".

| The user hands you | Stage 0 | The decision round | Then |
|---|---|---|---|
| **A bug** ("X is broken") | Reproduce it yourself: a test that fails at the reported SHA, and the root cause at file:line | S: the fix's options and the one you rule; the failing test is the first acceptance check | One plan, executed by fresh groups; the reproduction passing and the full gate green close it |
| **A bug hunt** ("find what's wrong in Y") | Hunters that probe: a failing reproduction per suspected defect, measured, never argued | The user triages the reproduced findings: keep or `backlog` (`user-questions.md`) | One S fix round for the kept findings, grouped by the files they touch |
| **A question, an investigation, a comparison** | Harvest plus probes that measure the answer | The decision document is the deliverable: options, evidence at file:line or by measurement, a recommendation | A spec and plan only when the user asks to build it |
| **A feature, a refactor, a phase** | As SKILL.md | As the rung table | As SKILL.md |
| **A review** (a PR/MR, a design, a review-fix round) | Rung S, always (`failure-modes` F50) | The steps below | |

A review of a change, at S, rests its verdict on what it read and ran (F104):
1. Fetch the change and record its range in the index's header, `> **Review**: `<base-sha>..<head-sha>``
   (`templates.md` §1): the review covers every file `git diff --name-only` of that range lists.
2. Probe in a tree of the review's own — `git worktree add --detach <scratch-dir> <head-sha>` — never
   the lead's checkout or the branch under review: a test, a reproduction, the code run on the input
   a finding says breaks it. Record each probe in the Coverage section with its exit code.
3. Label each changed file in the Coverage section as you go: `Read in full`, `Diff read` or
   `Not read`. Tests, recordings, documentation and lockfiles are exempt.
4. The verdict says unfinished while any file is Not read or no probe has run;
   `decision_check.py` fails the index otherwise, and the hook refuses posting the review's
   comments while it fails.

Every shape keeps the route's verification:
- each code claim is re-verified before a ruling;
- each number carries its SHA;
- gate logs come from the gate itself;
- `test_check.py` runs at each merge;
- the lead never executes a plan task.

A small task stays small: rung S, with no harvester and no arbiter. It still runs the gates.
