# Costs — for the rung announcement and every gate

The announcement's expected cost is per role, summed: the project's own medians first, measured on
its last route by `usage_report.py` (`--groups` for task groups); for a role it has not run, this
table's newest run set that measured it. Each stage's wall-clock comes
from the last recorded run in the handoff — none recorded: run set B's one MR-review round at rung
L, all deep (harvest 44–63 min, framing review 17 min, decision agents 17–34 min), or "unknown" —
never an estimate.

| Role — median cost per agent | Run set A: 4 runs, 2026-09-24..10-01 | Run set B: 20 runs, 2026-09-24..10-03 | Run set F: 2 runs' Stage 5, 2026-10-14 | Run set J: 20 runs on one project, 2026-10-21..27 |
|---|---|---|---|---|
| Harvester · decision agent | 0.7M · 1.0M | 2.1M · 1.4M (mechanical 0.3M · 0.3M) | — | 0.9M · 0.8M |
| Framing · seam or S review, as an agent (the second model costs no Claude usage) | — · 1.6M | 1.1M · 1.5M | — | 0.6M (both, 35 agents) |
| Supersede markers · register folder | 3.8M · 0.8M | — | — | 0.2M · 0.4M |
| Spec author · reconciler · plan author | 1.2M · 0.9M · 2.1M | 1.3M · 1.4M · 1.5M | — | 1.2M · 1.1M · 1.5M |
| Execution: a whole-lane agent · one task group · a wave integrator (`execution.md`) | 4.2M (up to 22M) · — · — | 8–27M · 3.1M · — | — · 0.6M (49 groups, 0.06–2.6M; a group that compacted 1.4–2.6M) · 0.2M | — · 1.0M (210 groups, p90 1.8M, max 3.2M) · 0.6M |
| Lead, one rung M or L run | 3–66M (66M ran three phases in one session) | 5–35M | Stage 5: 0.2–0.4M per task group dispatched | 0.5M per agent dispatched; 32% of all cost |

**Stage 5**, per wave: its task groups × the group median (the project's own, from
`usage_report.py --groups` on its last route, before the table's), plus the lead per group, plus at
L one seven-sins review before the phase's last push (and any review the user asks for). Run sets F and J had orientation maps (`failure-modes` F67);
B's 3.1M predates them. J's 1.0M over 210 groups replaces F's 0.6M over 49. Record each wave's figure with
`route_state.py --budget` (`execution.md`).

**Rung S**: two MR reviews cost ~8M and ~9M (B) — review only, no execution; 15 reviews of another
developer's MR (run set I, 2026-10-07..20) a median 4.2M (1.6–10.8M), and the five with no
harvester 1.6–2.6M against 4.9–8.0M for the four with one (`failure-modes` F87); with no harvester
dispatched, run set J's a median ≈2.6M (0.9–5.8M). One S round with
execution cost ~19M (run set D, `failure-modes` F68): lead ~15M, five agents ~4M, with the lead
executing post-lane work itself. Announce an S build as the lead's writing plus its execution
priced per task group from the row above. Two S builds of one task measured in today's units (run
set H, `failure-modes` F85): 5.7M in 1 h 45 min — lead 2.8M, the S review as an agent 0.6M, six
task groups 2.3M (median 0.4M and 11 min each) — and 6.7M in 1 h 54 min (lead 3.8M, five groups
at a median 0.5M). A seven-sins review with its fix round (run set G,
measured in today's units; the lead never loaded the skill, `failure-modes` F79) cost 56.7M in ~7 h:
lead 7.8M, seven sin reviewers 11.2M, 27 task groups 30.6M (median 1.1M, 0.2–1.9M; 78 commits),
three integrators 3.7M, hook sessions 1.6M. Announce a review-fix round as the review, plus its
findings' task groups — findings ÷ the tasks a group fits (`execution.md`) — at the group median,
plus the lead ~0.3M a group.

**Seven-sins review** (`sins/lead.md`; at L one spec review in Stage 3 and one code review before
the phase's last push; other reviews only when the user asks). Code mode, measured twice at rung M with reproductions and the since-removed debate (run set F): 9 commits cost ~5.4M in
~15 min (agents ~4.2M, lead ~1.2M), 31 commits ~8.5M in ~45 min (agents ~6.6M, lead ~1.9M) —
announce ~5M up to 10 commits and ~8.5M a slice of up to 30; over 30, one review per slice, so
announce the slices × ~8.5M. A claim-only verifier is unmeasured: announce ~0.6M as a `dsp-deep` agent
(the S review agent's figure), 0 units on the second model, one per expected dispute. A whole 1,328-file repository with no
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
`failure-modes` evidence stays in the older units. In these units the turn is the cost: a lead's
read turn measured ~25k units — 27% re-reading the context, 40% cache write, 33% output — so one
turn fewer saves far more than a shorter resident text. `scripts/usage_report.py` prints a running round's
actual figures; quote them at each gate.
