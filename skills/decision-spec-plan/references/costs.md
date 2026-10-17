# Costs — for the rung announcement and every gate

The announcement's expected cost is per role, summed: the project's own medians first, measured on
its last route by `usage_report.py` (`--groups` for task groups); for a role it has not run, this
table's newest run set that measured it. Each stage's wall-clock comes
from the last recorded run in the handoff — none recorded: run set B's one MR-review round at rung
L, all deep (harvest 44–63 min, framing review 17 min, decision agents 17–34 min), or "unknown" —
never an estimate.

| Role — median cost per agent | Run set A: 4 runs, 2026-09-24..10-01 | Run set B: 20 runs, 2026-09-24..10-03 | Run set F: 2 runs' Stage 5, 2026-10-14 |
|---|---|---|---|
| Harvester · decision agent | 0.7M · 1.0M | 2.1M · 1.4M (mechanical 0.3M · 0.3M) | — |
| Framing · seam or S review, as an agent (the second model costs no Claude usage) | — · 1.6M | 1.1M · 1.5M | — |
| Supersede markers · register folder | 3.8M · 0.8M | — | — |
| Spec author · reconciler · plan author | 1.2M · 0.9M · 2.1M | 1.3M · 1.4M · 1.5M | — |
| Execution: a whole-lane agent · one task group · a wave integrator (`execution.md`) | 4.2M (up to 22M) · — · — | 8–27M · 3.1M · — | — · 0.6M (49 groups, 0.06–2.6M; a group that compacted 1.4–2.6M) · 0.2M |
| Lead, one rung M or L run | 3–66M (66M ran three phases in one session) | 5–35M | Stage 5: 0.2–0.4M per task group dispatched |

**Stage 5**, per wave: its task groups × the group median (the project's own, from
`usage_report.py --groups` on its last route, before the table's), plus the lead per group, plus one
seven-sins review per push at M and L. Run set F's groups had orientation maps (`failure-modes` F67);
B's 3.1M predates them — about five times run set F's median. Record each wave's figure with
`route_state.py --budget` (`execution.md`).

**Rung S**: two MR reviews cost ~8M and ~9M (B) — review only, no execution. One S round with
execution cost ~19M (run set D, `failure-modes` F68): lead ~15M, five agents ~4M, with the lead
executing post-lane work itself. Announce an S build as the lead's writing plus its execution
priced per task group from the row above. A seven-sins review with its fix round (run set G,
measured in today's units; the lead never loaded the skill, `failure-modes` F79) cost 56.7M in ~7 h:
lead 7.8M, seven sin reviewers 11.2M, 27 task groups 30.6M (median 1.1M, 0.2–1.9M; 78 commits),
three integrators 3.7M, hook sessions 1.6M. Announce a review-fix round as the review, plus its
findings' task groups — findings ÷ the tasks a group fits (`execution.md`) — at the group median,
plus the lead ~0.3M a group.

**Seven-sins review** (`sins/lead.md`; M and L: one spec review per phase, one code review per
push). Code mode, measured twice at rung M with reproductions (run set F): 9 commits cost ~5.4M in
~15 min (agents ~4.2M, lead ~1.2M), 31 commits ~8.5M in ~45 min (agents ~6.6M, lead ~1.9M) —
announce ~5M up to 10 commits and ~8.5M up to 30, more above. A whole 1,328-file repository with no
focus, before reproductions were added, cost ~11M in 40 min (run set E: agents ~10.6M at 1.1–2.0M
per sin, lead ~0.6M). Spec mode is unmeasured: announce ~11M and 40 min until one is recorded.
Record each review's `usage_report.py` figures in the handoff.

Units are Opus 5.5 input tokens — 1M units is about $4 at API prices (read 2026-10-17): cache read
×0.05, 5-minute cache write ×1.25, 1-hour ×2, output ×5; Sonnet 5.5 ×0.5 of that, Haiku 5.5 ×0.025
(`usage_report.py`). Every figure here was measured in the older units (cache read ×0.1, Sonnet
×0.6) and is converted by its role's ratio of new to old units, measured on 324 local route agents
and 17 leads (2026-10-17): task group 0.59, integrator 0.60, harvester 0.62, sin reviewer 0.64,
decision agent 0.65, plan author 0.66, spec author and register folder 0.68, lead 0.69, reconciler
0.72, framing or seam review 0.74, markers 0.93; a mechanical (Sonnet) role ×0.83 more. The
`failure-modes` evidence stays in the older units. Cache reads are the largest part of a role's
cost (68–90% in the older units) — every turn re-sends the agent's whole context — so cost follows
turns × context size, not the number of steps. `scripts/usage_report.py` prints a running round's
actual figures; quote them at each gate.
