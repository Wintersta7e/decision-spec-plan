# decision-spec-plan — install

Paths in this repository are relative to `~/.claude`:

    cp -r agents skills ~/.claude/

Then merge `settings-hooks.json` into `~/.claude/settings.json`: append each entry to that event's
existing array, never replace the array. Without these hooks the route's state hook
(`route_state.py --hook`) and push guard (`push_guard.sh`) stay off, and SKILL.md's claims about
them are false. Both act only for a session that ran `route_state.py --activate`; any other
session pays ~0.02 s per call.

Agent teams are required: set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` under `env` in
`~/.claude/settings.json`.

Set an auto-compact window of about 300000 for the lead's model, e.g.
`"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 300000}}` (or
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`): without it leads grew to ~965k context, where every turn costs
~0.1M (SKILL.md, The route runs unattended). `dsp-deep` runs on the lead's model.

Headless (`claude -p`): set `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`. Otherwise background agents
are stopped 10 minutes after the lead's last turn, and the lead ends its turn to wait for them.

Requires python3, bash, jq and git. `dsp-deep`'s memory cap uses `systemd-run --user`; without it
the agent falls back to `timeout` + `setsid`.

`agents/dsp-*.md` list Serena and Context7 MCP tools — edit their `tools:` line to the MCP servers
you have.

Before editing the skill, and after: `bash ~/.claude/skills/decision-spec-plan-workspace/tools/hooks_test.sh`
(throwaway repos only; fails if SKILL.md grows past 19,000 characters — a compaction cuts it at
20,000).
