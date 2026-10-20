#!/usr/bin/env bash
# Tests for the route's hooks on throwaway repositories: push_guard.sh (PreToolUse:Bash) and
# `route_state.py --hook` (PostToolUse, UserPromptSubmit, SessionStart). Never touches a live
# project; HOME points at a temp dir so the session registry is a throwaway too.
# Usage: hooks_test.sh   — prints one line per case and exits non-zero on any failure.
#        SCRIPTS=<dir> hooks_test.sh — test a staged copy.

set -uo pipefail
SCRIPTS=${SCRIPTS:-~/.claude/skills/decision-spec-plan/scripts}
SCRIPTS=$(eval echo "$SCRIPTS")
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
export HOME=$T/home
mkdir -p "$HOME"
G=(-c user.name=t -c user.email=t@t)

R=$T/repo
git init -q -b main "$R"
git -C "$R" "${G[@]}" commit -q --allow-empty -m one
git -C "$R" "${G[@]}" commit -q --allow-empty -m two
git -C "$R" branch feature HEAD~1
git -C "$R" worktree add -q "$T/wt" feature
P=$R/.plan
mkdir -p "$P/lanes" "$P/plans" "$P/decisions/phase1" "$P/spec"
MAIN=$(git -C "$R" rev-parse main)

ok() { echo "ok    $*"; }
bad() {
	echo "FAIL  $*"
	FAIL=1
}

guard() { # expected-exit cwd command
	local out code
	out=$(jq -n --arg c "$3" --arg d "$2" '{tool_input: {command: $c}, cwd: $d}' | bash "$SCRIPTS/push_guard.sh" 2>&1)
	code=$?
	if [ "$code" = "$1" ]; then ok "guard $1  $3"; else
		bad "guard want $1 got $code  $3"
		echo "$out" | sed -n '1,3p'
	fi
}

LAST=""
RS=$SCRIPTS/route_state.py
hook() { # expect(silent | report | delta | /regex/ | deny:regex | ask:regex) json
	local out want=$1
	out=$(echo "$2" | python3 "$RS" --hook 2>&1)
	LAST=$out
	case "$want" in
	silent) [ -z "$out" ] ;;
	report) jq -e '.hookSpecificOutput.additionalContext | test("route state ·")' <<<"$out" >/dev/null ;;
	delta) jq -e '.hookSpecificOutput.additionalContext | test("changed between")' <<<"$out" >/dev/null ;;
	/*/) jq -e --arg r "${want:1:-1}" '.hookSpecificOutput.additionalContext | test($r)' <<<"$out" >/dev/null ;;
	deny:*) jq -e --arg r "${want:5}" '.hookSpecificOutput | .permissionDecision == "deny" and (.permissionDecisionReason | test($r))' <<<"$out" >/dev/null ;;
	ask:*) jq -e --arg r "${want:4}" '.hookSpecificOutput | .permissionDecision == "ask" and (.permissionDecisionReason | test($r))' <<<"$out" >/dev/null ;;
	esac
	if [ $? = 0 ]; then ok "hook  $want  $2"; else
		bad "hook want $want  $2"
		echo "$out" | sed -n '1,4p'
	fi
}
unthrottle() { rm -f "$HOME/.claude/dsp-routes/"*.checked; }
ev() { # event session [extra json fields]
	echo "{\"hook_event_name\":\"$1\",\"session_id\":\"$2\",\"cwd\":\"/tmp\"${3:+,$3}}"
}

# --- no route active: everything passes, the hook is silent
guard 0 "$R" "git push origin main"
guard 0 "$R" "git --no-pager push origin main"
hook silent "$(ev PostToolUse s1 '"tool_name":"Agent"')"
# ...but a route agent dispatched with no route means the skill never loaded: every hook is off (F79)
route_agent() { ev PreToolUse "$1" "\"tool_name\":\"Agent\",\"tool_input\":{\"subagent_type\":\"$2\",\"name\":\"pride-r1\"}"; }
hook 'deny:no active decision-spec-plan route.*Skill tool.*--activate --rung' "$(route_agent s1 dsp-deep)"
hook 'deny:no active decision-spec-plan route' "$(route_agent s1 decision-spec-plan:dsp-mechanical)"
hook silent "$(route_agent s1 general-purpose)"
hook silent "$(ev PreToolUse s1 '"agent_id":"a1","tool_name":"Agent","tool_input":{"subagent_type":"dsp-deep"}')"

out=$(cd "$R" && env -u CLAUDE_CODE_SESSION_ID python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --activate)
[ $? = 1 ] && [ -f "$R/.git/dsp-route.json" ] && grep -q "CLAUDE_CODE_SESSION_ID is unset" <<<"$out" &&
	ok "activate without a session id: marker written, exit 1, says so" || bad "activate without a session id: $out"
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')"

out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate)
[ -f "$HOME/.claude/dsp-routes/s1.json" ] && grep -q '"--main", "main"' "$R/.git/dsp-route.json" &&
	ok "activate registered s1, --main resolved to main" || bad "activate s1: $out"
hook silent "$(route_agent s1 dsp-deep)"
hook 'deny:no active decision-spec-plan route' "$(route_agent s2 dsp-deep)" # another session

# --- route active, no gate log
guard 0 "$R" "ls -la"
guard 0 "$R" 'grep -rn "git push" .'
guard 2 "$R" "git push origin main"
guard 2 "$R" "git push"
guard 2 "/tmp" "cd $R && git push origin main"
guard 2 "/tmp" "git -C $R push origin main"
guard 2 "$T/wt" "git push origin feature"
guard 2 "$R" "git push --tags"
guard 0 "$R" "git push --dry-run origin main"
guard 0 "$R" "git push origin --delete old"
guard 0 "$R" "git push origin :old"
guard 0 "$R" "DSP_SKIP_PUSH_GUARD=1 git push origin main"
# where the push runs: relative, chained and quoted `cd`s resolve from the cwd; an unresolvable
# one is skipped, never replaced by the cwd (that blocked an agent's push in its throwaway repo)
guard 2 "$T" "cd repo && git push origin main"
guard 2 "/tmp" "cd $T && cd repo && git push origin main"
guard 2 "/tmp" "cd \"$R\" && git push origin main"
guard 2 "$R" "echo abcd /tmp; git push origin main"
guard 0 "$R" 'S=/tmp/x && cd $S && git push origin main'
guard 0 "$R" "cd /no-such-dir-dsp && git push origin main"
# every push of a command is checked: a first push that sends nothing used to pass the whole command
guard 2 "$R" "git push --dry-run origin main && git push origin main"
guard 2 "$R" "git push origin --delete old; git push origin main"
guard 2 "$R" "git status && git push -n origin main
git push origin main"
guard 2 "/tmp" "cd /no-such-dir-dsp && git push origin main; cd $R && git push origin main"
guard 2 "$R" 'cd $X && git push origin main; cd '"$R"' && git push origin main'
guard 0 "$R" "git push --dry-run origin main && git push origin --delete old"

# --- gate logs: red, dirty, then green for main only
printf 'sha=%s dirty=0\n...\nexit=1\n' "$MAIN" >"$P/lanes/red-gate.log"
guard 2 "$R" "git push origin main"
printf 'sha=%s dirty=3\n...\nexit=0\n' "$MAIN" >"$P/lanes/dirty-gate.log"
guard 2 "$R" "git push origin main"
printf 'sha=%s dirty=0\nok\nexit=0\n' "$MAIN" >"$P/lanes/wave1-int-gate.log"
guard 0 "$R" "git push origin main"
guard 0 "$R" "git push origin HEAD:main"
guard 0 "$R" "git push -u origin main 2>&1"
guard 0 "$R" "git push -o ci.skip origin main"
guard 0 "/tmp" "cd $R && git push origin main"
guard 2 "$R" "git push origin main feature"
guard 2 "$T/wt" "git push origin feature"
guard 2 "$R" "git push origin main && git -C $T/wt push origin feature"
guard 0 "$R" "git push origin main; git push origin HEAD:main"
# what a push sends must be readable from the command: no refspec (push.default, push refspecs,
# mirror and pushRemote config decide), git options before push, or GIT_* variables — held
guard 2 "$R" "git push"
guard 2 "$R" "git push origin"
guard 2 "$R" "git -c remote.origin.mirror=true push origin main"
guard 2 "$R" "git --no-pager push origin main"
guard 2 "$R" "git --git-dir=$R/.git push origin main"
guard 2 "$R" "GIT_DIR=$R/.git git push origin main"
guard 2 "$R" "true && GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=push.default GIT_CONFIG_VALUE_0=matching git push origin main"
guard 0 "$R" "DSP_X=1 git push origin main"
guard 0 "$R" "MY_GIT_X=1 true; git push origin main"
guard 0 "/tmp" "git -C $R push origin main"
# from outside the route's repository, a held form may still push it: held while a route is active
guard 2 "/tmp" "git --git-dir=$R/.git push origin main"
guard 2 "/tmp" 'git -c core.x=1 push origin main'
guard 2 "/tmp" "export GIT_DIR=$R/.git; git push origin main"
guard 2 "/tmp" "pushd $R && git push origin main"
# a gate whose codegen/build steps print before the sha= line (one measured at line 6)
FEAT=$(git -C "$R" rev-parse feature)
{
	printf 'build %s\n' $(seq 20)
	printf 'sha=%s dirty=0\nok\nexit=0\n' "$FEAT"
} >"$P/lanes/late-gate.log"
guard 2 "$T/wt" "git push origin feature"
{
	printf 'build %s\n' $(seq 5)
	printf 'sha=%s dirty=0\nok\nexit=0\n' "$FEAT"
} >"$P/lanes/late-gate.log"
guard 0 "$T/wt" "git push origin feature"
rm "$P/lanes/late-gate.log"

# --- rung M: a gated push also needs a pre-push review's verdict (failure-modes F70)
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung M)
grep -q '"rung": "M"' "$R/.git/dsp-route.json" && grep -q "rung M: push_guard.sh" <<<"$out" &&
	ok "activate --rung M: rung in the marker, announced" || bad "activate --rung M: $out"
mkdir -p "$P/reviews"
verdict() { printf '# pre-push review\n%s\n' "$@" >"$P/reviews/w2-verdict.md"; }
ONE=$(git -C "$R" rev-parse main~1)
TREE=$(git -C "$R" rev-parse "main^{tree}")
REV=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$MAIN" -m reviewed)
FIX=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$REV" -m fix)
UNG=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$MAIN" -m ungated)
git -C "$R" update-ref refs/heads/rel "$FIX"
git -C "$R" update-ref refs/heads/ung "$UNG"
printf 'sha=%s dirty=0\nok\nexit=0\n' "$FIX" >"$P/lanes/rel-gate.log"
guard 2 "$R" "git push origin main"
verdict "reviewed=$MAIN base=$ONE blocking=1"
guard 2 "$R" "git push origin main"
verdict "reviewed=$MAIN base=$ONE blocking=0"
guard 0 "$R" "git push origin main"
guard 0 "$R" "git push origin HEAD:main"
verdict "reviewed=${MAIN:0:12} base=${ONE:0:12} blocking=0"
guard 2 "$R" "git push origin main"
# a fix committed after the review: covered only when listed on after=
verdict "reviewed=$REV base=$MAIN blocking=0"
guard 2 "$R" "git push origin rel"
verdict "reviewed=$REV base=$MAIN blocking=0" "after=$FIX"
guard 0 "$R" "git push origin rel"
verdict "reviewed=$MAIN base=$ONE blocking=0" "after=$REV,$FIX"
guard 0 "$R" "git push origin rel"
# the remote's tip behind the base: commits older than the base would go out unreviewed
git -C "$R" update-ref refs/remotes/origin/rel "$ONE"
verdict "reviewed=$REV base=$ONE blocking=0" "after=$FIX"
guard 0 "$R" "git push origin rel"
verdict "reviewed=$REV base=$MAIN blocking=0" "after=$FIX"
guard 2 "$R" "git push origin rel"
guard 2 "$R" "git push origin rel:rel"
guard 0 "$R" "git push origin rel:other"
git -C "$R" update-ref -d refs/remotes/origin/rel
rm "$P/reviews/w2-verdict.md"
guard 0 "$R" "DSP_SKIP_REVIEW=1 git push origin main"
guard 2 "$R" "DSP_SKIP_REVIEW=1 git push origin ung"
guard 0 "$R" "DSP_SKIP_PUSH_GUARD=1 git push origin ung"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung S >/dev/null
guard 0 "$R" "git push origin main"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
guard 0 "$R" "git push origin main"
grep -q rung "$R/.git/dsp-route.json" && bad "a marker without --rung keeps a rung" || ok "a marker without --rung has none"
git -C "$R" update-ref -d refs/heads/rel
git -C "$R" update-ref -d refs/heads/ung
rm -r "$P/reviews" "$P/lanes/rel-gate.log"

# --- the state hook: who it speaks to
hook report "$(ev PostToolUse s1 '"tool_name":"Agent"')"
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # throttled
unthrottle
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # nothing changed
hook silent "$(ev PostToolUse s1 '"tool_name":"Read","agent_id":"a1"')"
hook silent "$(ev PostToolUse s2 '"tool_name":"Read"')" # a session that never activated
hook silent "$(ev UserPromptSubmit s1 '"prompt":"what is left on the todo?"')"
hook silent "$(ev UserPromptSubmit s1 '"prompt":"<task-notification>\n<task-id>x</task-id>"')"

# --- pending, not missing: index rows without files
printf '| D1 | a |\n| D2 | b |\n' >"$P/decisions/phase1/00-index.md"
echo "ruling" >"$P/decisions/phase1/D1-a.md"
unthrottle
hook '/decisions  1 D files \(2 in the index; pending D2\)/' "$(ev PostToolUse s1 '"tool_name":"Agent"')"
jq -e '.hookSpecificOutput.additionalContext | test("missing|written [0-9]+s ago") | not' <<<"$LAST" >/dev/null &&
	ok "no missing / freshness flags in a hook report" || bad "missing or freshness flag in: $LAST"

# --- deltas on an agent's return, by prompt or by the next tool call
echo "- [x] done" >"$P/lanes/p1-01-checkpoint.md"
echo "Final SHA: $MAIN" >>"$P/lanes/p1-01-checkpoint.md"
hook '/lanes      1 checkpoints/' "$(ev UserPromptSubmit s1 '"prompt":"<teammate-message teammate_id=\"g1\">done</teammate-message>"')"
hook silent "$(ev UserPromptSubmit s1 '"prompt":"<agent-message from=\"a1\">\n[Subagent hand-back] done"')"
echo "ruling" >"$P/decisions/phase1/D2-b.md"
unthrottle
hook '/changed between .*\n.*2 D files \(2 in the index\)/' "$(ev PostToolUse s1 '"tool_name":"Bash"')"

# --- SessionStart after a compaction and a resume
hook '/Re-read .*HANDOFF.md[\s\S]*\nroute state ·/' "$(ev SessionStart s1 '"source":"compact"')"
hook '/Read .*SKILL.md in full/' "$(ev SessionStart s1 '"source":"resume"')"
hook silent "$(ev SessionStart s1 '"source":"startup"')"
hook silent "$(ev SessionStart s2 '"source":"compact"')"

# --- lanes: Final SHA, merged by ancestry, by patch, by the integrator's record
git -C "$T/wt" "${G[@]}" commit -q --allow-empty -m lane-a
echo "x" >"$T/wt/f.txt"
git -C "$T/wt" add f.txt && git -C "$T/wt" "${G[@]}" commit -q -m lane-b
F2=$(git -C "$T/wt" rev-parse HEAD)
git -C "$R" "${G[@]}" cherry-pick "$F2" >/dev/null
printf 'Final SHA: %s\nnote: older commit %s\n' "$F2" "${MAIN:0:7}" >"$P/lanes/p1-02-checkpoint.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-02 .*${F2:0:7}[0-9a-f]* merged (by patch)" <<<"$out" && ok "Final SHA used, rebased lane merged by patch" ||
	bad "by patch: $(grep p1-02 <<<"$out")"
grep -q "p1-01 .*merged" <<<"$out" && grep -q "1 lane worktrees" <<<"$out" &&
	ok "ancestor lane merged; main's worktree not counted" || bad "lanes line: $(grep -E 'p1-01|^lanes' <<<"$out")"
echo "fixup" >"$T/wt/g.txt"
git -C "$T/wt" add g.txt && git -C "$T/wt" "${G[@]}" commit -q -m 'fixup! lane-b'
F3=$(git -C "$T/wt" rev-parse HEAD)
echo "squashed" >"$R/g.txt"
git -C "$R" add g.txt && git -C "$R" "${G[@]}" commit -q -m squashed
SQ=$(git -C "$R" rev-parse HEAD)
printf 'Final SHA: %s\n' "$F3" >"$P/lanes/p1-03-checkpoint.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-03 .*not merged" <<<"$out" && ok "squashed lane without a record: not merged" || bad "squash: $(grep p1-03 <<<"$out")"
printf '# wave 1\nMerged p1-03 `%s` → `%s`\n' "${F3:0:9}" "${SQ:0:9}" >"$P/lanes/wave1-integration.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-03 .*merged as ${SQ:0:9} (wave1-integration.md)" <<<"$out" && ok "squashed lane merged per the integrator's record" ||
	bad "record: $(grep p1-03 <<<"$out")"
grep -q "no \`Final SHA:\` line" <<<"$out" && bad "Final SHA flag on checkpoints that have one" || ok "no Final SHA flag when present"
# a merged lane's long checkpoint: no next group reads it, so no length flag (F76)
{
	printf 'Final SHA: %s\n' "$MAIN"
	seq 40
} >"$P/lanes/p1-05-checkpoint.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-05 .*merged" <<<"$out" && ! grep -q "checkpoint over 35 lines *lanes/p1-05" <<<"$out" &&
	ok "no length flag on a merged lane's checkpoint" || bad "merged lane length flag: $(grep p1-05 <<<"$out")"
rm "$P/lanes/p1-05-checkpoint.md"
# an open lane's line is the lead's check of a return (F80); lanes are found whatever their name,
# never another phase's
git -C "$R" worktree add -q -b fix-ui "$T/wt2" main
echo a >"$T/wt2/a.txt"
git -C "$T/wt2" add a.txt && git -C "$T/wt2" "${G[@]}" commit -q -m 'ui: a' -m 'Co-Authored-By: t'
FX=$(git -C "$T/wt2" rev-parse HEAD)
printf 'Final SHA: %s\n' "$FX" >"$P/lanes/fix-ui-checkpoint.md"
printf 'Final SHA: %s\n' "$MAIN" >"$P/lanes/p2-01-checkpoint.md"
head -c 13000 /dev/zero | tr '\0' x >"$P/lanes/fix-ui-rulings.md"
head -c 20000 /dev/zero | tr '\0' x >"$P/lanes/fix-ui-rulings-archive.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R")
grep -q "fix-ui .* not merged · 1 commits · no gate log at this SHA · trailers Co-Authored-By ×1$" <<<"$out" &&
	! grep -q p2-01 <<<"$out" && ok "an open lane's line without --all, any name, not another phase's" ||
	bad "open lane line: $(grep -E 'fix-ui|p2-01' <<<"$out")"
# an open lane's rulings file every group reads whole, past 12 KB; never its archive (F67)
grep -q "rulings over 12 KB *lanes/fix-ui-rulings.md (13 KB" <<<"$out" && ! grep -q "rulings-archive.md (" <<<"$out" &&
	ok "an open lane's rulings file over 12 KB is flagged, its archive is not" || bad "rulings size: $(grep rulings <<<"$out")"
printf 'sha=%s dirty=0\nok\nexit=0\n' "$FX" >"$P/lanes/fix-ui-gate.log"
echo b >>"$T/wt2/a.txt"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R")
grep -q "fix-ui .* · gate exit=0 · trailers Co-Authored-By ×1 · 1 uncommitted in its worktree$" <<<"$out" &&
	ok "the lane line: gate at its SHA, uncommitted work" || bad "lane line: $(grep fix-ui <<<"$out")"
unthrottle
hook report "$(ev SessionStart s1 '"source":"compact"')"
git -C "$T/wt2" "${G[@]}" commit -q -am 'ui: b'
printf 'Final SHA: %s\n' "$(git -C "$T/wt2" rev-parse HEAD)" >"$P/lanes/fix-ui-checkpoint.md"
unthrottle
hook '/changed between [\s\S]*fix-ui +[0-9a-f]+ not merged · 2 commits · no gate log at this SHA/' "$(ev PostToolUse s1 '"tool_name":"Bash"')"
git -C "$R" worktree remove --force "$T/wt2"
git -C "$R" branch -q -D fix-ui
rm "$P/lanes/fix-ui-checkpoint.md" "$P/lanes/fix-ui-gate.log" "$P/lanes/p2-01-checkpoint.md" \
	"$P/lanes/fix-ui-rulings.md" "$P/lanes/fix-ui-rulings-archive.md"

# --- --main: the default branch of a master repo, and a wrong --main in an old marker
M=$T/mrepo
git init -q -b master "$M"
git -C "$M" "${G[@]}" commit -q --allow-empty -m one
mkdir -p "$M/.plan"
# The route of s1 restarted as s9: listed once, active as of s9's transcript (5 min ago).
cp "$HOME/.claude/dsp-routes/s1.json" "$HOME/.claude/dsp-routes/s9.json"
mkdir -p "$HOME/.claude/projects/p"
touch -d '5 minutes ago' "$HOME/.claude/projects/p/s9.jsonl"
touch -d '3 days ago' "$R/.git/dsp-route.json"
out=$(CLAUDE_CODE_SESSION_ID=s3 python3 "$SCRIPTS/route_state.py" "$M/.plan" --phase 1 --repo "$M" --activate)
grep -q '"--main", "master"' "$M/.git/dsp-route.json" && ok "--main defaults to master" || bad "--main default: $(cat "$M/.git/dsp-route.json")"
[ "$(grep -c "other route on this account: $P (lead last active 5m ago)" <<<"$out")" = 1 ] &&
	ok "activate lists the other route once, active as of its lead's transcript" || bad "other routes: $out"
out=$(python3 "$SCRIPTS/route_state.py" "$M/.plan" --phase 1 --repo "$M" --main main)
grep -q -- "--main main does not exist .*using master" <<<"$out" && ok "a wrong --main falls back with a flag" || bad "wrong --main: $out"

# --- sections: closed range with pending, open range
echo "x" >"$P/spec/01-scope.md"
echo "x" >"$P/spec/02-core.md"
grep -q "spec       2 sections from §1" <<<"$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --sections 1-)" &&
	ok "--sections 1- counts every section from §1" || bad "open sections"
grep -q "spec       2/3 sections (pending §3)" <<<"$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --sections 1-3)" &&
	ok "--sections 1-3 lists the pending one" || bad "closed sections"

# --- Stage 5 budget: the lead's exec- dispatches wait for a recorded, answered budget (F74)
ts() { python3 -c 'import datetime as d, sys; print((d.datetime.now(d.UTC) + d.timedelta(seconds=int(sys.argv[1]))).isoformat(timespec="milliseconds").replace("+00:00", "Z"))' "$1"; }
human() { jq -nc --arg t "$(ts "$1")" '{type:"user",timestamp:$t,origin:{kind:"human"},message:{role:"user",content:"go"}}'; }
peer() { jq -nc --arg t "$(ts "$1")" '{type:"user",timestamp:$t,origin:{kind:"peer"},message:{role:"user",content:"Another Claude session sent a message: done"}}'; }
sent() { jq -nc --arg t "$(ts "$1")" --arg id "$2" --arg n "$3" '{type:"assistant",timestamp:$t,message:{id:$id,content:[{type:"tool_use",id:$id,name:"Agent",input:{name:$n}}]}}'; }
used() { jq -nc --arg t "$(ts "$1")" --arg id "$2" --argjson n "$3" '{type:"assistant",timestamp:$t,requestId:$id,message:{id:$id,model:"claude-opus-5-5",content:[],usage:{input_tokens:$n,output_tokens:0}}}'; }
LEAD=$HOME/.claude/projects/p/s1.jsonl
human -3600 >"$LEAD"
dispatch() { ev PreToolUse s1 "\"tool_name\":\"Agent\",\"tool_input\":{\"name\":\"$1\"},\"tool_use_id\":\"$2\",\"transcript_path\":\"$LEAD\""; }
hook 'deny:phase 1 has no Stage 5 budget' "$(dispatch exec-p1-01-a t1)"
hook silent "$(dispatch plan-p1-01 t1)"
hook silent "$(ev PreToolUse s2 '"tool_name":"Agent","tool_input":{"name":"exec-p1-01-a"}')"

# --- rung S: the lead harvests itself, so a harvester dispatch is refused (F87)
reactivate() { CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate "$@" >/dev/null; }
harvester() { ev PreToolUse s1 "\"tool_name\":\"Agent\",\"tool_input\":{\"subagent_type\":\"dsp-deep\",\"name\":\"$1\",\"description\":\"$2\"}"; }
reactivate --rung S
hook 'deny:rung S has no harvester.*re-announce it at M' "$(harvester h1 'MR Harvest h1 runtime')"
hook 'deny:rung S has no harvester' "$(harvester harvest-code 'code facts')"
hook silent "$(harvester s-review 'S review of the plan')"
reactivate --rung M
hook silent "$(harvester h1 'MR Harvest h1 runtime')"
reactivate

out=$(CLAUDE_CODE_SESSION_ID=s2 python3 "$SCRIPTS/route_state.py" --budget w1 --estimate 10 --groups 4)
[ $? = 2 ] && ok "--budget without a registered session: exit 2" || bad "--budget unregistered: $out"
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w1 --estimate 10 --groups 4)
[ $? = 0 ] && jq -e '.budgets[-1] | .label == "w1" and .groups == 4 and .phase == "1"' "$R/.git/dsp-route.json" >/dev/null &&
	grep -q "past 12.5M spent or 5 exec- dispatches" <<<"$out" && ok "--budget records the wave in the marker" || bad "--budget: $out"
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
peer 1 >>"$LEAD"
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
human 1 >>"$HOME/.claude/projects/p/s9.jsonl" # an answer in another lead session of the route
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
human 1 >>"$LEAD"
hook '/^ETA exec-p1-01-a: none yet — no task group of this route has finished/' "$(dispatch exec-p1-01-a t1)"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
jq -e '.budgets | length == 1' "$R/.git/dsp-route.json" >/dev/null && ok "a re-activation keeps the budgets" || bad "re-activation dropped the budgets"
unthrottle
hook '/budget     w1 · 10M · 4 exec- agents/' "$(ev PostToolUse s1 '"tool_name":"Agent"')"
for i in 1 2 3 4; do sent 2 "t$i" "exec-p1-0$i-a" >>"$LEAD"; done
hook '/^ETA exec-p1-04-a/' "$(dispatch exec-p1-04-a t4)" # its own call is not counted twice
hook '/^ETA exec-p1-05-a/' "$(dispatch exec-p1-05-a t5)" # 5 = 4 × 1.25
sent 2 t5 exec-p1-05-a >>"$LEAD"
hook 'deny:this would be exec- dispatch 6 since — more than 25% over' "$(dispatch exec-p1-06-a t6)"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w2 --estimate 0.01 --groups 9 >/dev/null
human 1 >>"$LEAD"
used 2 u1 11000 >>"$LEAD"
hook '/^ETA exec-p1-06-a/' "$(dispatch exec-p1-06-a t6)"
used 2 u2 2000 >>"$LEAD"
hook 'deny:budget .w2. .*0.0M spent since — more than 25% over' "$(dispatch exec-p1-06-a t6)" # the spend
# a budget another lead session recorded, answered there, is not this session's (F74)
CLAUDE_CODE_SESSION_ID=s9 python3 "$SCRIPTS/route_state.py" --budget w3 --estimate 50 --groups 9 >/dev/null
human 2 >>"$HOME/.claude/projects/p/s9.jsonl"
human 2 >>"$LEAD"
hook 'deny:recorded in another lead session' "$(dispatch exec-p1-07-a t7)"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w3 --estimate 50 --groups 9 >/dev/null
human 3 >>"$LEAD"
hook '/^ETA exec-p1-07-a/' "$(dispatch exec-p1-07-a t7)"
# an allowed dispatch's ETA: the median minutes of the route's finished agents of its kind, its
# lane's first (one route ran 3 h with no ETA in any report, until the user paused it, F83)
EA=$HOME/.claude/projects/p/s1/subagents
mkdir -p "$EA"
fin() { # agent-id name start-offset end-offset stop_reason
	{
		jq -nc --arg t "$(ts "$3")" '{type:"user",timestamp:$t,message:{role:"user",content:"go"}}'
		jq -nc --arg t "$(ts "$4")" --arg s "$5" '{type:"assistant",timestamp:$t,message:{id:"m",stop_reason:$s,content:[{type:"text",text:"done"}]}}'
	} >"$EA/agent-$1.jsonl"
	echo "{\"name\":\"$2\",\"agentType\":\"dsp-deep\"}" >"$EA/agent-$1.meta.json"
}
fin f1 exec-p1-08-a -7200 -6600 end_turn # 10 min
fin f2 exec-p1-08-b -6000 -4200 end_turn # 30 min
fin f3 exec-p1-09-a -7200 -3600 end_turn # 60 min
fin f4 exec-p1-08-c -5400 -60 tool_use   # still running
fin f5 exec-wave1 -3000 4200 end_turn    # 120 min, an integrator
hook '/^ETA exec-p1-08-d: about 20 min, the median of lane p1-08.s 2 finished task groups \(the route.s 3: 30 min\)/' \
	"$(dispatch exec-p1-08-d t8)"
hook '/^ETA exec-p1-10-a: about 30 min, the median of the route.s 3 finished task groups\. Tell the user/' \
	"$(dispatch exec-p1-10-a t9)"
hook '/^ETA exec-wave2: about 120 min, the median of the route.s 1 finished integrator\./' "$(dispatch exec-wave2 t10)"

# --- usage_report.py: without --since, and a --since in another zone than the transcripts' UTC
UR=(python3 "$SCRIPTS/usage_report.py" s1 --project-dir "$HOME/.claude/projects/p")
out=$("${UR[@]}" 2>&1)
[ $? = 0 ] && grep -q '^lead .*turns=   2' <<<"$out" && ok "usage_report without --since" || bad "usage_report without --since: $(head -3 <<<"$out")"
z=$(ts -600)
o=$(python3 -c 'import datetime as d, sys; print(d.datetime.fromisoformat(sys.argv[1]).astimezone(d.timezone(d.timedelta(hours=2))).isoformat())' "$z")
a=$("${UR[@]}" --since "$z" | grep '^lead')
b=$("${UR[@]}" --since "$o" | grep '^lead')
[ "$a" = "$b" ] && grep -q 'turns=   2' <<<"$a" && ok "usage_report --since $o counts as $z" || bad "usage_report --since $z: $a | $o: $b"
out=$("${UR[@]}" --since yesterday 2>&1)
[ $? = 2 ] && grep -q 'argument --since' <<<"$out" && ok "usage_report refuses an unparseable --since" || bad "usage_report --since yesterday: $(head -3 <<<"$out")"
# the units by model (cache read ×0.05 on Opus and Sonnet 5.5; Haiku 5.5 over 100k ×0.125, read
# ×0.1), and hook sessions counted only up to the round's last record or --until
rec() { jq -nc --arg t "$(ts "$1")" --arg id "$2" --arg m "$3" --argjson n "$4" --arg e "${5:-}" \
	'{type:"assistant",timestamp:$t,requestId:$id,message:{id:$id,model:$m,content:[],usage:{cache_read_input_tokens:$n}}} + (if $e == "" then {} else {entrypoint:$e} end)'; }
U=$HOME/.claude/projects/u
mkdir -p "$U"
{
	rec -100 q1 claude-opus-5-5 10000000
	rec -90 q2 claude-sonnet-5-5 20000000
	rec -50 q3 claude-haiku-5-5 24000000
} >"$U/u1.jsonl"
{
	rec -60 k1 claude-opus-5-5 4000000 sdk-ts
	rec 100 k2 claude-opus-5-5 10000000 sdk-ts
} >"$U/u2.jsonl"
out=$(python3 "$SCRIPTS/usage_report.py" u1 --project-dir "$U" 2>&1)
grep -q '^total 1.5M = lead 1.3M + 0 agents 0.0M + 1 hook sessions 0.2M' <<<"$out" &&
	ok "usage_report: units by model, hook sessions up to the round's end" || bad "usage_report units: $(head -2 <<<"$out")"
out=$(python3 "$SCRIPTS/usage_report.py" u1 --project-dir "$U" --until "$(ts -55)" 2>&1)
grep -q '^total 1.2M = lead 1.0M + 0 agents 0.0M + 1 hook sessions 0.2M' <<<"$out" &&
	ok "usage_report --until" || bad "usage_report --until: $(head -2 <<<"$out")"
# each agent's effort as its requests record it, a change mid-run included (the lead sets it per call)
erec() { jq -nc --arg t "$(ts "$1")" --arg id "$2" --arg f "$3" \
	'{type:"assistant",timestamp:$t,requestId:$id,message:{id:$id,model:"claude-sonnet-5-5",content:[],usage:{input_tokens:1000}}} + (if $f == "" then {} else {effort:$f} end)'; }
erec -30 e0 xhigh >"$U/u3.jsonl"
mkdir -p "$U/u3/subagents"
{
	erec -20 e1 high
	erec -10 e2 xhigh
	erec -5 e3 high
} >"$U/u3/subagents/agent-ax.jsonl"
erec -20 e4 "" >"$U/u3/subagents/agent-ay.jsonl"
out=$(python3 "$SCRIPTS/usage_report.py" u3 --project-dir "$U" 2>&1)
grep -q '^lead .* effort xhigh$' <<<"$out" && grep -q '^agent .*claude-sonnet-5-5 *high/xhigh  *agent-ax$' <<<"$out" &&
	grep -q '^agent .*claude-sonnet-5-5 *-  *agent-ay$' <<<"$out" &&
	ok "usage_report prints each agent's effort" || bad "usage_report effort: $out"
# --groups: a task group's context at its first edit, its peak and commits, and how many commits
# fit under the 200k stop (F60, F75); an integrator (exec-wave*) is not a task group
grec() { jq -nc --arg t "$(ts "$1")" --arg id "$2" --argjson n "$3" --argjson c "${4:-[]}" \
	'{type:"assistant",timestamp:$t,requestId:$id,message:{id:$id,model:"claude-opus-5-5",content:$c,usage:{cache_read_input_tokens:$n}}}'; }
tool() { jq -nc --arg id "$1" --arg n "$2" --arg c "${3:-}" '[{type:"tool_use",id:$id,name:$n,input:{command:$c}}]'; }
GP=$HOME/.claude/projects/g
mkdir -p "$GP/g1/subagents"
grec -700 l1 1000 >"$GP/g1.jsonl"
{
	grec -600 e1 30000
	grec -500 e2 80000 "$(tool t1 Edit)"
	grec -400 e3 120000 "$(tool t2 Bash 'git add a && git commit -m x')"
	grec -400 e3 120000 "$(tool t2 Bash 'git add a && git commit -m x')" # a streamed copy
	grec -300 e4 160000 "$(tool t3 Bash 'git -C /w commit -m y')"
	grec -240 e5 190000 "$(tool t4 Bash 'git log')"
} >"$GP/g1/subagents/agent-e1.jsonl"
echo '{"name":"exec-p1-01-a","agentType":"dsp-deep"}' >"$GP/g1/subagents/agent-e1.meta.json"
{
	grec -200 w1 50000 "$(tool t5 Write)"
	grec -100 w2 60000 "$(tool t6 Bash 'git commit -m m')"
} >"$GP/g1/subagents/agent-e2.jsonl"
echo '{"name":"exec-wave1","agentType":"dsp-deep"}' >"$GP/g1/subagents/agent-e2.meta.json"
out=$(python3 "$SCRIPTS/usage_report.py" g1 --project-dir "$GP" --groups 2>&1)
grep -Eq '^group  exec-p1-01-a .*first-edit=  80k  peak= 190k  commits= 2  per-commit=  55k +6 min' <<<"$out" &&
	grep -q '^groups 1: median 6 min, 0.0M; first edit at 80k, +55k context per commit: about 2 commits fit under 200k' <<<"$out" &&
	! grep -q 'exec-wave1' <<<"$out" &&
	ok "usage_report --groups" || bad "usage_report --groups: $(grep -v '^agent' <<<"$out")"

# --- scope_check.py --waves: a file two plans of one wave change at once, unless one waits for the
# other (three lanes of one wave edited the same UI files and left seven seam defects)
W=$T/plans
mkdir -p "$W"
plan() { # plan-stem file...
	local f=$W/$1.md
	printf '# %s\n## File structure\n| File | Change |\n|---|---|\n' "$1" >"$f"
	shift
	printf '| `%s` | x |\n' "$@" >>"$f"
	echo '## Task 1' >>"$f"
}
plan p1-01-a src/app.js src/a.js
plan p1-02-b src/app.js src/b.js
plan p1-03-c src/a.js
plan p1-04-d src/app.js
plan p1-05-e src/e.js
cat >"$W/p1-00-index.md" <<'EOF'
# Phase 1 — plan index
## The plan set
| Plan | Section | Wave | Depends on |
|---|---|---|---|
| `p1-01-a` | §1 | 1 | — |
| `p1-02-b` | §2 | 1 | — |
| `p1-03-c` | §3 | 1 | p1-01 |
| `p1-04-d` | §4 | 2 | all |
EOF
out=$(python3 "$SCRIPTS/scope_check.py" "$W" --waves "$W/p1-00-index.md")
code=$?
[ $code = 1 ] && grep -q '^wave 1 *src/app.js  p1-01-a, p1-02-b$' <<<"$out" && ! grep -q 'src/a.js' <<<"$out" &&
	grep -q '^1 files changed' <<<"$out" && grep -q "not in the index's plan set: p1-05-e.md" <<<"$out" &&
	ok "scope_check --waves: a shared file of plans that run at once, not of a plan that waits" ||
	bad "scope_check --waves (exit $code): $out"
out=$(python3 "$SCRIPTS/scope_check.py" "$W" --waves "$W/p1-00-index.md" --glob 'p1-0[134]-*.md')
[ $? = 0 ] && grep -q '^0 files changed' <<<"$out" && ok "scope_check --waves: exit 0 with no shared file" ||
	bad "scope_check --waves, no overlap: $out"

# --- scope_check.py --asks: every planned file cites an ask or a user ruling and none is a file not
# to touch; --diff: every file a range changed is in a plan (unasked changes, F89)
A=$T/asks
mkdir -p "$A/plans" "$A/repo/src/core"
cat >"$A/00-index.md" <<'EOF'
# Phase 1 — the decision round
## The asks
| Ask | Verbatim | Source |
|---|---|---|
| **Ask1** | "port the adapter" | review thread |
### Do not touch
- `pom.xml` — no version bump (the reviewer)
## The decisions
| **D1** | names Ask7 without defining it |
EOF
printf '## The user rulings\n### U2 — keep the old test\n' >"$A/00-arbiter.md"
cat >"$A/plans/p1-01-a.md" <<'EOF'
# p1-01-a
## File structure
### `src/core/`
| File | Change | Ask |
|---|---|---|
| `Adapter.java` | new | Ask1 |
| `OldTest.java` | keep | U2 |
| `Extra.java` | refactor | — |
| `Other.java` | tidy | Ask7 |
| `pom.xml` | dependency | Ask1 |
## Task 1
EOF
printf '# p1-02-b\n## File structure\n| `src/b.js` | new | Ask1 |\n## Task 1\n' >"$A/plans/p1-02-b.md"
out=$(python3 "$SCRIPTS/scope_check.py" "$A/plans" --asks "$A/00-index.md" "$A/00-arbiter.md")
code=$?
[ $code = 1 ] && grep -q 'p1-01-a.md  src/core/Extra.java  (no ask)$' <<<"$out" &&
	grep -q 'src/core/Other.java  (no ask)$' <<<"$out" && grep -q 'src/core/pom.xml  (do not touch)$' <<<"$out" &&
	! grep -q 'Adapter.java\|OldTest.java\|src/b.js' <<<"$out" && grep -q '^3 of 6 planned files' <<<"$out" &&
	ok "scope_check --asks: a row with no ask, an undefined ask and a file not to touch" ||
	bad "scope_check --asks (exit $code): $out"
out=$(python3 "$SCRIPTS/scope_check.py" "$A/plans" --asks "$A/00-index.md" --glob 'p1-02-*.md')
[ $? = 0 ] && grep -q '^0 of 1 planned files' <<<"$out" && ok "scope_check --asks: exit 0 when every row cites an ask" ||
	bad "scope_check --asks, all asked: $out"
git init -q -b main "$A/repo"
touch "$A/repo/src/core/Adapter.java" "$A/repo/src/core/Stray.java"
git -C "$A/repo" "${G[@]}" commit -q --allow-empty -m base
git -C "$A/repo" add src && git -C "$A/repo" "${G[@]}" commit -q -m lane
out=$(python3 "$SCRIPTS/scope_check.py" "$A/plans" --diff HEAD~1..HEAD --repo "$A/repo")
code=$?
[ $code = 1 ] && grep -q '^   src/core/Stray.java$' <<<"$out" && ! grep -q 'Adapter' <<<"$out" &&
	grep -q '^1 of 2 changed files' <<<"$out" && ok "scope_check --diff: a changed file no plan lists" ||
	bad "scope_check --diff (exit $code): $out"
out=$(python3 "$SCRIPTS/scope_check.py" "$A/plans" --diff HEAD..HEAD --repo "$A/repo")
[ $? = 2 ] && grep -q '^0 of 0 changed files' <<<"$out" && ok "scope_check --diff: an empty range fails" ||
	bad "scope_check --diff, empty range: $out"

# --- inside an exec- agent: the context stop (F75) and a commit held for an unread ruling (F59)
SUB=$HOME/.claude/projects/p/s1/subagents
mkdir -p "$SUB"
echo '{"name":"exec-p1-01-b","agentType":"dsp-deep"}' >"$SUB/agent-x1.meta.json"
echo '{"name":"pride-p1-push1","agentType":"dsp-deep"}' >"$SUB/agent-y1.meta.json"
jq -nc --arg t "$(ts -60)" --arg f "$P/lanes/p1-01-rulings.md" '{type:"user",timestamp:$t,message:{role:"user",content:("Rulings file: " + $f)}}' >"$SUB/agent-x1.jsonl"
used -50 a1 150000 >>"$SUB/agent-x1.jsonl"
cp "$SUB/agent-x1.jsonl" "$SUB/agent-y1.jsonl"
inagent() { ev PreToolUse s1 "\"agent_id\":\"$1\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$2\"},\"transcript_path\":\"$LEAD\""; }
hook silent "$(inagent x1 'ls')"
used -40 a2 210000 >>"$SUB/agent-x1.jsonl"
used -40 a2 210000 >>"$SUB/agent-y1.jsonl"
hook '/your context is 210k tokens. Finish the task/' "$(inagent x1 'ls')"
hook silent "$(inagent x1 'ls')"              # told once
hook silent "$(inagent y1 'ls')"              # not an exec- agent
hook silent "$(inagent x1 'git commit -m x')" # no rulings file yet
echo "R1 use the old API" >"$P/lanes/p1-01-rulings.md"
hook 'deny:re-read .*p1-01-rulings.md before you commit' "$(inagent x1 'git -C /w commit -m x')"
hook silent "$(inagent x1 'git status')"
hook silent "$(inagent y1 'git commit -m x')"
jq -nc --arg t "$(ts 30)" --arg f "$P/lanes/p1-01-rulings.md" '{type:"assistant",timestamp:$t,message:{id:"r1",content:[{type:"tool_use",id:"r1",name:"Read",input:{file_path:$f}}]}}' >>"$SUB/agent-x1.jsonl"
hook silent "$(inagent x1 'git commit -m x')"
# the transcript repeats a tool_use in an untimestamped api-request-blob record; the read still counts
jq -nc --arg f "$P/lanes/p1-01-rulings.md" '{type:"api-request-blob",agentId:"x1",hash:"h1",sessionId:"s1",message:{id:"r1",content:[{type:"tool_use",id:"r1",name:"Read",input:{file_path:$f}}]}}' >>"$SUB/agent-x1.jsonl"
hook silent "$(inagent x1 'git commit -m x')"
touch -d '+2 minutes' "$P/lanes/p1-01-rulings.md"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'git commit -m x')"
# only the agent's own lane file holds its commit: a `lanes/` listing once named every lane's (F59)
jq -nc --arg t "$(ts 200)" --arg f "$P/lanes/p1-01-rulings.md" '{type:"assistant",timestamp:$t,message:{id:"r2",content:[{type:"tool_use",id:"r2",name:"Bash",input:{command:("cat " + $f)}}]}}' >>"$SUB/agent-x1.jsonl"
echo "R1 another lane's ruling" >"$P/lanes/p1-02-rulings.md"
touch -d '+5 minutes' "$P/lanes/p1-02-rulings.md"
jq -nc --arg t "$(ts 210)" --arg o "$(ls "$P/lanes")" '{type:"user",timestamp:$t,message:{role:"user",content:[{type:"tool_result",tool_use_id:"l1",content:$o}]}}' >>"$SUB/agent-x1.jsonl"
hook silent "$(inagent x1 'git commit -m x')"
# the lane's archive of applied rulings never holds a commit: a group reads only the ids it is named
echo "R0 applied" >"$P/lanes/p1-01-rulings-archive.md"
touch -d '+5 minutes' "$P/lanes/p1-01-rulings-archive.md"
hook silent "$(inagent x1 'git commit -m x')"
# a lane file named by plan id, never in the transcript: the dispatch points at a brief file
echo '{"name":"exec-p1-03-c","agentType":"dsp-deep"}' >"$SUB/agent-z1.meta.json"
jq -nc --arg t "$(ts -60)" '{type:"user",timestamp:$t,message:{role:"user",content:"Read your brief first: /w/dispatch-p1-03-c.md"}}' >"$SUB/agent-z1.jsonl"
echo "R1 wide" >"$P/lanes/p1-03-wide-rulings.md"
hook 'deny:re-read .*p1-03-wide-rulings.md' "$(inagent z1 'git commit -m x')"
rm "$P/lanes/p1-01-rulings.md" "$P/lanes/p1-01-rulings-archive.md" "$P/lanes/p1-02-rulings.md" "$P/lanes/p1-03-wide-rulings.md"

# --- outward actions on the hosted repository: the lead asks the user each time, an agent never
# runs one (nine PRs were closed with --delete-branch unasked; F81)
leadbash() { ev PreToolUse "$1" "\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$2\"}"; }
hook 'ask:gh pr close 5.*the user approves it here' "$(leadbash s1 'gh pr close 5 --delete-branch')"
hook 'ask:gh -R o/r pr merge' "$(leadbash s1 'gh -R o/r pr merge 7 --squash')"
hook 'ask:--delete-branch' "$(leadbash s1 'git fetch && gh pr merge 7 --delete-branch')"
hook 'ask:gh release create' "$(leadbash s1 'gh release create v1.0 dist/app.zip')"
hook silent "$(leadbash s1 'gh pr view 5 --json title')"
hook silent "$(leadbash s1 'gh run watch 12 --exit-status')"
hook silent "$(leadbash s1 'gh pr list; git log --oneline -1 | grep merge')"
# the same actions in other forms: options between gh's words, `gh api` writes, remote deletes
hook 'ask:gh pr -R o/r close 5' "$(leadbash s1 'gh pr -R o/r close 5')"
hook 'ask:gh api -X PATCH' "$(leadbash s1 'gh api -X PATCH repos/o/r/pulls/5 -f state=closed')"
hook 'ask:--method DELETE' "$(leadbash s1 'gh api repos/o/r/git/refs/heads/x --method DELETE')"
hook 'ask:gh api repos/o/r/issues/5/comments -f' "$(leadbash s1 'gh api repos/o/r/issues/5/comments -f body=x')"
hook 'ask:git push origin --delete old' "$(leadbash s1 'git push origin --delete old')"
hook 'ask:git push origin :old' "$(leadbash s1 'git push origin :old')"
hook 'ask:-fbody=x' "$(leadbash s1 'gh api repos/o/r/issues/5/comments -fbody=x')"
hook 'ask:--prune' "$(leadbash s1 "git push --prune origin 'refs/heads/*:refs/heads/*'")"
hook 'ask:git push -fd' "$(leadbash s1 'git push -fd origin old')"
hook "ask:git push origin ':old'" "$(leadbash s1 "git push origin ':old'")"
hook silent "$(leadbash s1 'gh api repos/o/r/pulls/5')"
hook silent "$(leadbash s1 'git push origin main && git push origin HEAD:refs/heads/x')"
hook silent "$(leadbash s1 'git push --dry-run -u origin main --follow-tags')"
hook 'deny:a route agent never runs one' "$(inagent x1 'gh pr close 5')"
hook silent "$(leadbash s2 'gh pr close 5')" # a session with no route

# --- the lead's files grow past one read (F76); the skill changes under a running lead (F78)
head -c 41000 /dev/zero | tr '\0' x >"$P/HANDOFF.md"
seq 40 >"$P/lanes/p1-04-checkpoint.md"
unthrottle
hook '/HANDOFF.md over 40 KB[\s\S]*checkpoint over 35 lines +lanes\/p1-04-checkpoint.md \(40/' "$(ev PostToolUse s1 '"tool_name":"Read"')"
rm "$P/HANDOFF.md" "$P/lanes/p1-04-checkpoint.md"
hook '/Re-read .*HANDOFF.md and, for Stage 5 \(going by the planning dir\) references\/execution.md,/' "$(ev SessionStart s1 '"source":"compact"')"
cp -rp "$SCRIPTS/.." "$T/skill"
RS=$T/skill/scripts/route_state.py
touch "$T/skill/references/execution.md"
unthrottle
hook '/changed since this session read it: references\/execution.md \(in /' "$(ev PostToolUse s1 '"tool_name":"Read"')"
unthrottle
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # told once
RS=$SCRIPTS/route_state.py
# the route ended (its marker deleted): a registered session's next route agent waits for --activate
mv "$R/.git/dsp-route.json" "$T/marker.bak"
hook 'deny:no active decision-spec-plan route' "$(route_agent s1 dsp-deep)"
hook silent "$(leadbash s1 'gh pr close 5')"
mv "$T/marker.bak" "$R/.git/dsp-route.json"

# --- the mechanical tier carries the deep tier's role rules: a lane moved to it once ran with no
# one-group limit, context stop, rulings, no-progress or heavy-run rule
AGENTS=$SCRIPTS/../../../agents
body() { sed -n '/^Your final message/,$p' "$1"; }
if [ -f "$AGENTS/dsp-mechanical.md" ]; then
	[ -n "$(body "$AGENTS/dsp-deep.md")" ] && [ "$(body "$AGENTS/dsp-deep.md")" = "$(body "$AGENTS/dsp-mechanical.md")" ] &&
		ok "dsp-mechanical carries dsp-deep's role rules" ||
		bad "dsp-mechanical's role rules differ from dsp-deep's: $(diff <(body "$AGENTS/dsp-deep.md") <(body "$AGENTS/dsp-mechanical.md") | head -3)"
else
	echo "SKIP  no agents dir at $AGENTS — the tiers' rules were not compared"
fi

# --- a script's --help is its whole interface: shown only its docstring's first line, a lead read
# ~20k characters of the scripts' source to learn their options (F84)
for s in route_state.py criteria_check.py plan_lint.py scope_check.py usage_report.py apply_markers.py; do
	last=$(python3 -c 'import ast, sys; print(ast.get_docstring(ast.parse(open(sys.argv[1]).read())).strip().splitlines()[-1].strip())' "$SCRIPTS/$s")
	python3 "$SCRIPTS/$s" --help 2>&1 | grep -qF -- "$last" && ok "$s --help prints its whole docstring" ||
		bad "$s --help lacks its docstring's last line: $last"
done
python3 "$SCRIPTS/route_state.py" --help | grep -qF 'claude -p' &&
	ok "route_state.py --help says what the budget hold does headless" ||
	bad "route_state.py --help does not say what the budget hold does headless"
python3 "$SCRIPTS/criteria_check.py" --help | grep -qF '<NN>-<slug>.md' &&
	ok "criteria_check.py --help names the file that holds a section" ||
	bad "criteria_check.py --help does not name the file that holds a section"
python3 "$SCRIPTS/criteria_check.py" --help | grep -qF '__tests__' &&
	ok "criteria_check.py --help shows the --test-re default" ||
	bad "criteria_check.py --help does not show the --test-re default"

# --- SKILL.md fits what a compaction re-attaches (cut at 20,000 characters; failure-modes F61)
n=$(python3 -c 'import sys; print(len(open(sys.argv[1], encoding="utf-8").read()))' "$SCRIPTS/../SKILL.md")
[ "$n" -le 19000 ] && ok "SKILL.md is $n characters (limit 19000)" || bad "SKILL.md is $n characters — over 19000; move detail to a reference"

[ "$FAIL" = 0 ] && echo "ALL PASS" || echo "FAILURES"
exit "$FAIL"
