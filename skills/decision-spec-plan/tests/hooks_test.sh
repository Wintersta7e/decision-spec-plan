#!/usr/bin/env bash
# Tests for the route's hooks on throwaway repositories: push_guard.py (PreToolUse:Bash) and
# `route_state.py --hook` (PostToolUse, UserPromptSubmit, SessionStart). Never touches a live
# project; HOME points at a temp dir so the session registry is a throwaway too.
# Usage: hooks_test.sh   — tests the plugin it sits in; prints one line per case and exits
#        non-zero on any failure.  SCRIPTS=<dir> hooks_test.sh — test a staged copy.

set -uo pipefail
SCRIPTS=${SCRIPTS:-$(dirname "$0")/../scripts}
SCRIPTS=$(cd "$(eval echo "$SCRIPTS")" && pwd)
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
	out=$(jq -n --arg c "$3" --arg d "$2" '{tool_input: {command: $c}, cwd: $d}' | python3 "$SCRIPTS/push_guard.py" 2>&1)
	code=$?
	if [ "$code" = "$1" ]; then ok "guard $1  $3"; else
		bad "guard want $1 got $code  $3"
		echo "$out" | sed -n '1,3p'
	fi
}

LAST=""
RS=$SCRIPTS/route_state.py
MK() { # repo [planning-dir, default <repo>/.plan] — that route's marker
	echo "$1/.git/dsp-route-$(realpath "${2:-$1/.plan}" | tr -d '\n' | sha1sum | cut -c1-10).json"
}
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
# a prompt naming the route in a session that has not loaded it: the skill first, before any work
# (one lead did 43 minutes of work after "use dsp" before loading it)
printf '%s\n' '{"type":"user","message":{"role":"user","content":"hi"}}' >"$T/no-skill.jsonl"
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"k1","name":"Skill","input":{"skill":"decision-spec-plan"}}]}}' >"$T/skill.jsonl"
asks() { ev UserPromptSubmit s1 "\"prompt\":$(jq -Rs . <<<"$1"),\"transcript_path\":\"$T/$2\""; }
hook '/decision-spec-plan[^.]*Skill tool[^.]*before any other/' "$(asks 'use dsp to find why the export drops rows' no-skill.jsonl)"
hook '/Skill tool/' "$(asks 'run this through decision-spec-plan' no-skill.jsonl)"
hook silent "$(asks 'use dsp to find why the export drops rows' skill.jsonl)" # loaded already
printf '%s\n' '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Base directory for this skill: /x/.claude/skills/decision-spec-plan\n\n# Decision"}]}}' >"$T/slash.jsonl"
hook silent "$(asks 'now use dsp for the export bug' slash.jsonl)"           # loaded by its slash command
hook silent "$(asks 'tune the DSP filter in the audio path' no-skill.jsonl)" # signal processing
hook silent "$(asks 'how many dsp-deep agents ran?' no-skill.jsonl)"
# an agent's return, a path into the skill's own repository or a dsp source dir is not the user naming it
hook silent "$(asks $'<task-notification>\n<result>3 bugs in skills/decision-spec-plan/scripts/route_state.py, use dsp</result>\n</task-notification>' no-skill.jsonl)"
hook silent "$(asks 'fix the README typo in /work/decision-spec-plan' no-skill.jsonl)"
hook silent "$(asks 'the clipping bug is in src/dsp/biquad.c' no-skill.jsonl)"

out=$(cd "$R" && env -u CLAUDE_CODE_SESSION_ID python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --activate)
[ $? = 1 ] && [ -f "$(MK "$R")" ] && grep -q "CLAUDE_CODE_SESSION_ID is unset" <<<"$out" &&
	ok "activate without a session id: marker written, exit 1, says so" || bad "activate without a session id: $out"
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')"

out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate)
[ -f "$HOME/.claude/dsp-routes/s1.json" ] && grep -q '"--main", "main"' "$(MK "$R")" &&
	ok "activate registered s1, --main resolved to main" || bad "activate s1: $out"
jq -e '.ledger["1"] == true and .ledger["1#checks"] == 2' "$(MK "$R")" >/dev/null && ok "a phase with no index yet is bound by the decision ledger, under today's checks" ||
	bad "a fresh phase's marker lacks ledger: $(cat "$(MK "$R")")"
hook silent "$(route_agent s1 dsp-deep)"
hook 'deny:no active decision-spec-plan route' "$(route_agent s2 dsp-deep)" # another session
# a route setting given without --activate was dropped in silence (live)
for flag in "--rung L" "--sins on" "--ci-harness e2e"; do
	# shellcheck disable=SC2086 # the flag and its value are two words
	out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" $flag 2>&1)
	[ $? = 2 ] && grep -q 'only with --activate' <<<"$out" && ok "$flag without --activate is refused" ||
		bad "$flag without --activate: $out"
done

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
# a sha= line with more fields after dirty=0 (a lane's worktree) passes: its rejection made a lead
# edit the log to fit; a hold names each log of the commit and why it fails
gmsg() { jq -n --arg c "$2" --arg d "$1" '{tool_input: {command: $c}, cwd: $d}' | python3 "$SCRIPTS/push_guard.py" 2>&1; }
GL=$(git -C "$R" "${G[@]}" commit-tree -m gl "$(git -C "$R" rev-parse 'main^{tree}')" -p main)
git -C "$R" branch gl "$GL"
printf 'sha=%s dirty=0 wt=lane-a\nok\nexit=0\n' "$GL" >"$P/lanes/gl-gate.log"
guard 0 "$R" "git push origin gl"
printf 'sha=%s dirty=2 wt=lane-b\nok\nexit=0\n' "$GL" >"$P/lanes/gl-gate.log"
grep -q 'gl-gate.log: .*dirty=2' <<<"$(gmsg "$R" "git push origin gl")" &&
	ok "the hold names a dirty log of the commit" || bad "dirty log not named: $(gmsg "$R" "git push origin gl")"
printf 'sha=%s dirty=0\nok\n' "$GL" >"$P/lanes/gl-gate.log"
grep -q 'gl-gate.log: no exit= line' <<<"$(gmsg "$R" "git push origin gl")" &&
	ok "the hold names a log with no exit= line" || bad "unfinished log not named: $(gmsg "$R" "git push origin gl")"
grep -q 'no gate log under .* names' <<<"$(gmsg "$T/wt" "git push origin feature")" &&
	ok "the hold says when no log names the commit" || bad "no-log reason missing: $(gmsg "$T/wt" "git push origin feature")"
rm "$P/lanes/gl-gate.log"
git -C "$R" branch -q -D gl
# a directory named like a gate log is no log; a guard that crashes holds the push (an exit 1 lets
# it through)
mkdir "$P/lanes/odd-gate.log"
guard 0 "$R" "git push origin main"
rmdir "$P/lanes/odd-gate.log"
out=$(jq -n --arg d "$R" '{tool_input: {command: "git push origin main"}, cwd: $d}' |
	python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import push_guard as g
def boom(*a): raise OSError("injected")
g.walk = boom; sys.exit(g.main())' "$SCRIPTS" 2>&1)
[ $? = 2 ] && grep -q "the guard failed on this command (OSError: injected)" <<<"$out" &&
	ok "a crash in the guard holds the push while a route is active" || bad "guard crash: $out"
# a tag the same command creates before pushing it: its target is what goes out
guard 0 "$R" "git tag v9 $MAIN && git push origin v9 2>&1 | tail -2"
guard 0 "$R" "git tag -a v9 -m \"Release 9\" main && git push origin v9"
guard 0 "$R" "git tag v9; git push origin v9"
guard 2 "$R" "git tag v9 feature && git push origin v9"
guard 2 "$R" "git tag -d v9 && git push origin v9"
guard 2 "$R" "git tag v8 main && git push origin v9"
guard 2 "$R" "git tag --merged=main v9 main && git push origin v9"
guard 2 "$R" "git tag v9 feature && git tag v9 main; git push origin v9"
guard 2 "$R" "git tag feature main && git push origin feature"
guard 0 "$R" "git tag -l 'v*' && git push origin main"
# any other `git tag` holds: moving, deleting or re-making a tag, clustered flags, git options
git -C "$R" tag v7 "$MAIN"
guard 2 "$R" "git tag -f v7 feature && git push origin v7"
guard 2 "$R" "git tag -af v7 -m x feature && git push origin v7"
guard 2 "$R" "git tag -d v7 && git tag v7 feature && git push origin v7"
guard 2 "$R" "git -C $R tag -f v7 feature && git push origin v7"
guard 2 "$R" "git tag v7 main; git push origin refs/tags/v7"
git -C "$R" tag -d v7 >/dev/null
# a ref moved earlier in the command is not the one read now
guard 2 "$R" "git commit -qam x && git push origin main"
guard 2 "$R" "git checkout -q main; git push origin HEAD:main"
guard 2 "$R" "git -C $R merge -q feature && git push origin main"
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
# the command is read as bash reads it (shell_cmd.py); a regex read missed or misread each of these
guard 2 "$T/wt" "timeout 60 git push origin feature"
guard 2 "$T/wt" "env FOO=1 nice -n 5 git push origin feature"
guard 2 "$T/wt" "command git push origin feature"
guard 2 "$T/wt" "bash -c 'git push origin feature'"
guard 2 "$T/wt" "eval git push origin feature"
guard 2 "$T/wt" "for b in feature; do git push origin \$b; done"
guard 2 "$T/wt" "! git push origin feature"
guard 2 "$T/wt" "{ git push origin feature; }"
guard 2 "$T/wt" "\\git push origin feature"
guard 2 "$T/wt" "$(command -v git) push origin feature"
guard 2 "$T/wt" "'git' push origin feature"
guard 2 "$T/wt" "git \\
push origin feature"
guard 2 "$T/wt" "echo \$(git push origin feature)"
guard 2 "$T/wt" "echo \`git push origin feature\`"
guard 2 "$T/wt" "sudo git push origin feature"
guard 2 "$T/wt" "echo feature | xargs git push origin"
guard 2 "$T/wt" "if true; then git push origin feature; fi"
guard 0 "$R" "if true; then git push origin main; fi"
guard 0 "$R" "git push origin \"main\""
guard 0 "$R" 'echo "now run git push"'
guard 0 "$T/wt" "echo 'git push origin feature'; git log -1 --oneline"
guard 0 "$T/wt" "cat <<EOF
git push origin feature
EOF"
guard 0 "$R" "git --no-pager log --grep push"
guard 0 "/tmp" "git --no-pager log --grep push"
# a `cd` inside a subshell leaves the push where it was; a quoted `-C` path with a space is read whole
guard 2 "$T/wt" "(cd /tmp && ls) && git push origin feature"
git -C "$R" worktree add -q --detach "$T/w t" feature
guard 2 "/tmp" "git -C \"$T/w t\" push origin HEAD:feature"
git -C "$R" worktree remove "$T/w t"
# a directory the command computes is held while a route is active; one it sets, or a fresh
# mktemp one, is followed
guard 2 "/tmp" "D=$T/wt; cd \$D && git push origin feature"
guard 2 "$T/wt" "cd \"\$(git rev-parse --show-toplevel)\" && git push origin feature"
guard 0 "$T/wt" "W=\$(mktemp -d) && cd \"\$W\" && git push origin feature"
# refs moved earlier in the command, read-only uses of the same git commands
guard 2 "$R" "git fetch . feature:main && git push origin main"
guard 2 "$R" "git symbolic-ref HEAD refs/heads/feature && git push origin HEAD:main"
guard 0 "$R" "git fetch origin && git push origin main"
guard 0 "$R" "git branch --show-current && git push origin main"
guard 0 "$R" "git branch -a; git push origin main"
guard 2 "$R" "git branch tmp && git push origin main"
guard 0 "$R" "git checkout -- x.txt && git push origin main"
# the matching refspec sends every branch both sides have
guard 2 "$R" "git push origin :"
guard 2 "$R" "git push origin +:"
# a pipeline's commands and a backgrounded one run in subshells: their `cd` stays there
guard 2 "$T/wt" "cd /tmp | true; git push origin feature"
guard 2 "$T/wt" "cd /tmp & git push origin feature"
guard 2 "$T/wt" "{ cd /tmp; } | cat; git push origin feature"
guard 0 "$T/wt" "git log -1 | cat; cd /tmp && git push origin feature"
# a `cd` that fails leaves the shell where it was; only an `&&` chain after it is skipped
guard 2 "$T/wt" "cd /no-such-dir-dsp; git push origin feature"
guard 2 "$T/wt" "cd /no-such-dir-dsp || true; git push origin feature"
guard 2 "$T/wt" "cd /no-such-dir-dsp && cd /no-such-dir-dsp2; git push origin feature"
guard 0 "$T/wt" "cd /no-such-dir-dsp && git push origin feature"
guard 0 "$T/wt" "cd /no-such-dir-dsp || exit 1; git push origin feature"
# an alias runs what it names: from the config, from `-c`, or a shell one
git -C "$R" config alias.pu push
git -C "$R" config alias.sp '!git push'
guard 2 "$T/wt" "git pu origin feature"
guard 0 "$R" "git pu origin main"
guard 2 "$T/wt" "git -c alias.x=push x origin feature"
guard 2 "$R" "git sp origin main"
guard 0 "$R" "git log -1 --oneline && git status --short"
git -C "$R" config --unset alias.pu
git -C "$R" config --unset alias.sp
# any shell alias runs anything; a config the command line or the command's variables point at may
# define an alias the guard cannot read
git -C "$R" config alias.st '!true'
guard 2 "$R" "git st"
git -C "$R" config --unset alias.st
mkdir -p "$T/h" && printf '[alias]\n\tp = push\n' >"$T/h/.gitconfig"
guard 2 "$T/wt" "git -c include.path=$T/h/.gitconfig p origin feature"
guard 2 "$T/wt" "HOME=$T/h git p origin feature"
guard 2 "$T/wt" "export XDG_CONFIG_HOME=$T/h; git p origin feature"
# another repository's config (`--git-dir`), or one the command writes first, may define it too
git -C "$R" config alias.p2 push
guard 2 "/tmp" "git --git-dir=$R/.git p2 origin feature"
git -C "$R" config --unset alias.p2
guard 2 "$T/wt" "git config alias.p3 push && git p3 origin feature"
guard 2 "$T/wt" "printf '[alias]\\n\\tp3 = push\\n' >>.git/config; git p3 origin feature"
guard 2 "$T/wt" "printf '[alias]\\n\\tp3 = push\\n' >>.git/co\\nfig; git p3 origin feature"
guard 2 "$T/wt" "bash -c \"printf '[alias]\\\\n\\\\tp3 = push\\\\n' >>.git/co\\\\nfig\"; git p3 origin feature"
guard 2 "$T/wt" "bash -c '\$(echo git) p\\ush origin feature'"
# however deep the `bash -c` strings nest
deep="\$(echo git) p\\ush origin feature"
for _ in 1 2 3 4 5 6; do printf -v deep 'bash -c %q' "$deep"; done
guard 2 "$T/wt" "$deep"
# ref moves the `--` rule missed
guard 2 "$R" "git checkout -B main feature -- && git push origin main"
guard 2 "$R" "git worktree add -B main $T/wb feature && git push origin main"
guard 2 "$R" "git bisect start feature main && git push origin HEAD:main"
# a command name or git subcommand from a variable is read as its value; an unreadable one is held
guard 2 "$T/wt" "G=git; \$G push origin feature"
guard 2 "$T/wt" "P=push; git \$P origin feature"
guard 0 "$R" "P=push; git \$P origin main"
guard 2 "$T/wt" "git \$UNSET_DSP_X origin feature"
guard 2 "$T/wt" "git \$'push' origin feature"
guard 2 "$T/wt" "git \$'\\x70ush' origin feature"
guard 2 "$T/wt" "git \$\"push\" origin feature"
# a value bash splits into words, or an empty one bash drops, is no single word: held
guard 2 "$T/wt" "X='push origin feature'; git \$X"
guard 2 "$T/wt" "X=; git \$X push origin feature"
# escapes that hide `git` and `push` from the raw text are read too
guard 2 "$T/wt" "g\\it p\\ush origin feature"
# text a shell runs that the guard cannot read is held when it may push
guard 2 "$T/wt" "X='git push origin feature'; bash -c \"\$X\""
guard 2 "$T/wt" "X='git push origin feature'; eval \"\$X\""
guard 2 "$T/wt" "echo 'git push origin feature' | bash"
guard 2 "$T/wt" "bash <<EOF
git push origin feature
EOF"
guard 2 "$T/wt" "source ./push.sh"
guard 0 "$T/wt" "bash -c 'git log -1' && echo pushed"
# text that only names push is no push: the live false holds of 2026-10-31 (a heredoc's event list,
# a loop word, a JS `.push(`) beside a sourced script or a computed string
mkdir -p "$T/scripts"
printf 'export NVM_DIR=x\nnvm_ls() { git -C "$NVM_DIR" fetch; }\n' >"$T/scripts/env.sh"
guard 0 "$T/wt" "cat > $T/wf.yml <<EOF
on: {events: push,schedule}
EOF
source $T/scripts/env.sh && ls"
guard 0 "$T/wt" "for ev in push:none pull_request:none; do . $T/scripts/env.sh; echo \$ev; done"
guard 0 "$T/wt" "node -e 'const a=[]; a.push(1)' & X=\$(echo ls); bash -c \"\$X\""
# a script file the command runs is read as the command is: a push in it is held, none passes
# (an agent moved a held command into a script file, which the guard never read)
printf 'cd %s\ngit push origin feature\n' "$T/wt" >"$T/scripts/ship.sh"
guard 2 "$R" "bash $T/scripts/ship.sh"
guard 2 "$T/wt" "S=$T/scripts; bash \$S/ship.sh"
guard 2 "$T/wt" ". $T/scripts/ship.sh"
printf 'bash %s\n' "$T/scripts/ship.sh" >"$T/scripts/outer.sh"
guard 2 "$R" "sh $T/scripts/outer.sh"
guard 0 "$T/wt" "bash $T/scripts/env.sh && echo push"
# a script run by its path is read too; one in another language is not shell text
chmod +x "$T/scripts/ship.sh" "$T/scripts/env.sh"
guard 2 "$R" "$T/scripts/ship.sh"
guard 0 "$T/wt" "chmod +x $T/scripts/env.sh && $T/scripts/env.sh"
printf '#!/usr/bin/env python3\nprint("git push origin feature")\n' >"$T/scripts/py.sh"
chmod +x "$T/scripts/py.sh"
guard 0 "$T/wt" "$T/scripts/py.sh"
# a script the command writes before it runs it is held when the command may push: the file read
# now is not the one that runs
echo ls >"$T/scripts/w.sh"
guard 2 "$T/wt" "printf 'git push origin feature\\n' >$T/scripts/w.sh; bash $T/scripts/w.sh"
guard 0 "$T/wt" "printf 'ls\\n' >$T/scripts/w.sh; bash $T/scripts/w.sh"
# the command's own state reaches the script it runs, and a sourced script's state comes back
printf 'git push origin main\n' >"$T/scripts/main.sh"
guard 0 "$R" "bash $T/scripts/main.sh"
guard 2 "$R" "export GIT_DIR=$R/.git; bash $T/scripts/main.sh"
printf 'git branch -f main feature\n' >"$T/scripts/moves.sh"
guard 2 "$R" "bash $T/scripts/moves.sh; git push origin main"
# a script's own text naming push does not make its computed names pushes (this suite was held)
printf 'X=$(ls); $X; echo push\n' >"$T/scripts/noisy.sh"
guard 0 "$T/wt" "bash $T/scripts/noisy.sh"
# ...but a computed name or eval in it whose own words or values name push is held
printf '$(echo git) push origin feature\n' >"$T/scripts/hid1.sh"
printf 'X="git push origin feature"; $X\n' >"$T/scripts/hid2.sh"
printf 'X="git push origin feature"; eval "$X"\n' >"$T/scripts/hid3.sh"
for s in hid1 hid2 hid3; do guard 2 "$T/wt" "bash $T/scripts/$s.sh"; done
# a child shell gets only exported variables: an unexported ref is empty there
printf 'git push origin $DSP_REF\n' >"$T/scripts/ref.sh"
guard 2 "$R" "DSP_REF=main; bash $T/scripts/ref.sh"
guard 0 "$R" "export DSP_REF=main; bash $T/scripts/ref.sh"
guard 0 "$R" "DSP_REF=main; source $T/scripts/ref.sh"
# a probe shown then run from a review directory named for the push (a live false hold)
mkdir -p "$T/scripts/p1-push7" && echo ls >"$T/scripts/p1-push7/probe.sh"
guard 0 "$T/wt" "cat $T/scripts/p1-push7/probe.sh; bash $T/scripts/p1-push7/probe.sh"
printf 'export GIT_DIR=%s/.git\n' "$R" >"$T/scripts/genv.sh"
guard 2 "$R" "source $T/scripts/genv.sh; git push origin main"
printf 'cd %s\n' "$T/wt" >"$T/scripts/towt.sh"
guard 2 /tmp ". $T/scripts/towt.sh; git push origin feature"
guard 0 /tmp "bash $T/scripts/towt.sh; git push origin feature"
# a directory the command names before it changes into it may be one it creates: followed, and a
# push from one that does not exist yet is held
rm -rf "$T/lane-y" "$T/wt/out" "$T/wt/build"
guard 2 "$R" "git worktree add ../lane-y feature && cd ../lane-y && git push -u origin feature"
guard 2 "$R" "git worktree add ../lane-y feature && git -C ../lane-y push -u origin feature"
guard 2 "$T/wt" "mkdir -p out && cd out && make && cd .. && git push origin feature"
guard 2 "$T/wt" "mkdir -p build && cd build; cd .. && git push origin feature"
guard 0 "$R" "mkdir -p out && cd out && make && cd .. && git push origin main"
# a one-line `function f { … }`, `time`'s options, a wrapper's own flags, `env -C`/`-S` and more
# wrappers hide no push
for c in "function f { git push origin feature; }; f" "time -p git push origin feature" \
	"time -- git push origin feature" "timeout -v 120 git push origin feature" \
	"ssh-agent bash -c 'ssh-add -q k; git push origin feature'" "op run -- git push origin feature" \
	"direnv exec . git push origin feature" "nix develop -c git push origin feature" \
	"chronic git push origin feature" "unbuffer git push origin feature" \
	"strace -f -o /tmp/t git push origin feature" "taskset -c 0 git push origin feature" \
	"uv run git push origin feature" "coproc git push origin feature" \
	"env -S 'git push origin feature'" "strace -fo /tmp/t git push origin feature" \
	"strace --output /tmp/t git push origin feature" "timeout -s9 5 git push origin feature" \
	"env -vS 'git push origin feature'" "env '-Sgit push origin feature'" \
	"env -S 'git\\_push origin feature'" "coproc P { git push origin feature; }" \
	"coproc { git push origin feature; }"; do
	guard 2 "$T/wt" "$c"
done
guard 2 /tmp "env -C $T/wt git push origin feature"
guard 2 /tmp "env --chdir=$T/wt git push origin feature"
guard 2 /tmp "env -iC$T/wt git push origin feature"
# a GIT_* prefix holds in the script, shell string or sourced file it runs
printf 'git push origin main\n' >"$T/scripts/pm.sh" && chmod +x "$T/scripts/pm.sh"
guard 0 "$R" "bash $T/scripts/pm.sh"
for c in "GIT_DIR=$R/.git bash $T/scripts/pm.sh" "GIT_DIR=$R/.git $T/scripts/pm.sh" \
	"GIT_DIR=$R/.git bash -c 'git push origin main'" "GIT_DIR=$R/.git source $T/scripts/pm.sh" \
	"env GIT_DIR=$R/.git bash $T/scripts/pm.sh"; do
	guard 2 "$R" "$c"
done
# env -S reads `\t` as a separator and fills in `${VAR}`; getopt takes a long option's unique
# prefix (`--out` is ambiguous: held), and a long option the reader does not know leaves the
# command unread; a prefix on a sourced file is gone after it
for c in "env -S 'git\\tpush origin main'" "env -S 'git push \${R:-origin} main'" \
	"strace --bogus git push origin main"; do
	guard 2 "$R" "$c"
done
guard 0 "$R" "strace --str 64 git push origin main"
guard 2 "$R" "strace --out /tmp/t git push origin main"
guard 0 "$R" "timeout --preserve-status 5 git push origin main"
guard 2 "$T/wt" "strace --str 64 git push origin feature"
printf 'true\n' >"$T/scripts/noop.sh"
guard 2 /tmp "export D=$T/wt; D=/tmp source $T/scripts/noop.sh; cd \"\$D\" && git push origin feature"
# a `cd` that fails leaves OLDPWD where the last one that worked set it
guard 2 "$T/wt" "cd /tmp; cd $T/no-such-dir; cd - && git push origin feature"
guard 0 "$R" "command -v git && git push origin main"
# a script only read, shown or made executable before it runs is not written by the command
printf 'echo hi\n' >"$T/scripts/build.sh" && chmod +x "$T/scripts/build.sh"
for c in "chmod +x $T/scripts/build.sh && $T/scripts/build.sh && git push origin main" \
	"cat $T/scripts/build.sh; bash $T/scripts/build.sh; git push origin main" \
	"test -f $T/scripts/build.sh && source $T/scripts/build.sh && git push origin main" \
	"git stash push && cat $T/scripts/build.sh && bash $T/scripts/build.sh"; do
	guard 0 "$R" "$c"
done
# a shell string read from a file runs that file's push
guard 2 "$R" "sh -c \"\$(cat $T/scripts/pm.sh)\""
guard 2 "$R" "bash -c \"\$(<$T/scripts/pm.sh)\""
guard 0 "$R" "sh -c \"\$(cat $T/scripts/build.sh)\""
# one the command writes first, or one the guard cannot read, may hold anything
guard 2 "$R" "printf 'echo hi\\\\n' >$T/scripts/gen.sh; sh -c \"\$(cat $T/scripts/gen.sh)\""
guard 2 "$R" "sh -c \"\$(cat $T/scripts/no-such.sh)\""
# a GIT_* prefix sets the variable for its own command only; deleting a branch moves no ref the
# push sends; `cd -` goes back where the last `cd` left
for c in "GIT_PAGER=cat git log --oneline -3 && git push origin main" \
	"GIT_EDITOR=true git stash list; git push origin main" "git branch -d lane-x && git push origin main" \
	"git branch -D old-lane; git push origin main" "cd /tmp && ls && cd - && git push origin main"; do
	guard 0 "$R" "$c"
done
guard 2 "$R" "GIT_PAGER=cat git push origin main"
guard 2 "$R" "cd - && git push origin main"
guard 2 "$T/wt" "cd /tmp && cd - && git push origin feature"
# git's own `tag <name>` refspec; a refspec the command computes is named as such, not as one that
# does not resolve; a held form's hold says no gate log clears it; a bare `-C` is no crash
git -C "$R" tag v1 main
guard 0 "$R" "git push origin tag v1"
git -C "$R" tag -d v1 >/dev/null
grep -q 'a refspec the command computes' <<<"$(gmsg "$R" 'git push -u origin "$(git branch --show-current)"')" &&
	ok "the hold names a computed refspec" || bad "computed refspec: $(gmsg "$R" 'git push -u origin "$(git branch --show-current)"')"
out=$(gmsg /tmp "git --git-dir=$R/.git push origin main")
grep -q 'No gate log clears' <<<"$out" && ! grep -q 'no full gate has passed' <<<"$out" &&
	ok "a held form's hold says a gate log will not clear it" || bad "held-form banner: $out"
out=$(gmsg "$R" "git -C")
! grep -q 'the guard failed' <<<"$out" && ok "a bare git -C is no guard crash" || bad "git -C: $out"
# every command is read now, so a long line of git commands stays fast: one alias lookup per name
start=$SECONDS
guard 0 "$T/wt" "$(printf 'git x; %.0s' {1..3000})"
[ $((SECONDS - start)) -lt 2 ] && ok "3,000 git commands in one line are read in $((SECONDS - start)) s" ||
	bad "3,000 git commands: $((SECONDS - start)) s"
# a CI harness's log is no full gate; a marker that names no planning dir holds the push
printf 'sha=%s dirty=0\nharness=it\nok\nexit=0\n' "$(git -C "$R" rev-parse feature)" >"$P/lanes/f-it-gate.log"
guard 2 "$T/wt" "git push origin feature"
rm "$P/lanes/f-it-gate.log"
cp "$(MK "$R")" "$T/marker.keep" && echo '{}' >"$(MK "$R")"
guard 2 "$R" "git push origin main"
mv "$T/marker.keep" "$(MK "$R")"
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
# a rerun's log named after the first one (`-gate2.log`) counts: one green on the pushed commit was held
printf 'sha=%s dirty=0\nok\nexit=0\n' "$FEAT" >"$P/lanes/p1-01-a-gate2.log"
guard 0 "$T/wt" "git push origin feature"
rm "$P/lanes/p1-01-a-gate2.log"
# a gate log larger than the memory the report may use is read line by line: whole, it raised ENOMEM
{
	printf 'sha=%s dirty=0\n' "$FEAT"
	yes 'build output line' | head -c 300M
	printf '\nexit=0\n'
} >"$P/lanes/big-gate.log"
out=$( (ulimit -v 250000 && python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R") 2>&1)
! grep -q Traceback <<<"$out" && grep -qE 'gates +[0-9]+ green' <<<"$out" && ok "a 300 MB gate log is reported under a 250 MB memory cap" ||
	bad "big gate log: $(tail -n2 <<<"$out")"
rm "$P/lanes/big-gate.log"

# --- a rung alone asks no review; --sins on (L's phase end, or the user asked): a gated push also
# needs a seven-sins verdict (failure-modes F70)
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung L)
grep -q '"rung": "L"' "$(MK "$R")" && ! grep -q "sins" <<<"$out" &&
	ok "activate --rung L: rung in the marker, no review announced" || bad "activate --rung L: $out"
guard 0 "$R" "git push origin main"
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung L --sins on)
grep -q '"sins": "on"' "$(MK "$R")" && grep -q "sins on: push_guard.py" <<<"$out" &&
	ok "activate --sins on: in the marker, announced" || bad "activate --sins on: $out"
mkdir -p "$P/reviews"
git -C "$R" update-ref refs/remotes/origin/main "$MAIN" # the remote holds main
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
git -C "$R" worktree add -q --detach "$T/dw" rel
guard 0 "$T/dw" "git push origin HEAD" # a detached HEAD names no branch to compare
git -C "$R" worktree remove "$T/dw"
# the remote's tip behind the base: commits older than the base would go out unreviewed
git -C "$R" update-ref refs/remotes/origin/rel "$ONE"
verdict "reviewed=$REV base=$ONE blocking=0" "after=$FIX"
guard 0 "$R" "git push origin rel"
verdict "reviewed=$REV base=$MAIN blocking=0" "after=$FIX"
guard 2 "$R" "git push origin rel"
guard 2 "$R" "git push origin rel:rel"
guard 0 "$R" "git push origin rel:other"
git -C "$R" update-ref -d refs/remotes/origin/rel
# a branch the remote lacks: its base must be on the remote, under any of its refs; a remote with
# no tracking refs (a URL) is never known to hold it. Both went through unchecked.
verdict "reviewed=$FIX base=$REV blocking=0"
guard 2 "$R" "git push origin rel"
verdict "reviewed=$REV base=$MAIN blocking=0" "after=$FIX"
guard 2 "$R" "git push $T/elsewhere.git rel"
guard 0 "$R" "git push 'origin' \"rel:other2\""
# a phase-end review over more than 30 commits counts only as slices of at most 30 that cover
# every commit: review recall collapses on a large diff
C=$MAIN
for i in $(seq 1 31); do
	C=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$C" -m "c$i")
	[ "$i" = 15 ] && C15=$C
	[ "$i" = 14 ] && C14=$C
done
git -C "$R" update-ref refs/heads/wide "$C"
printf 'sha=%s dirty=0\nexit=0\n' "$C" >"$P/lanes/wide-gate.log"
verdict "reviewed=$C base=$MAIN blocking=0"
guard 2 "$R" "git push origin wide"
verdict "reviewed=$C base=$MAIN blocking=0" "slices=$MAIN..$C15 $C15..$C"
guard 0 "$R" "git push origin wide"
verdict "reviewed=$C base=$MAIN blocking=0" "slices=$MAIN..$C14 $C15..$C"
guard 2 "$R" "git push origin wide"
verdict "reviewed=$C base=$MAIN blocking=0" "slices=$MAIN..$C"
guard 2 "$R" "git push origin wide"
# one lane's merge of 31 commits splits along the lane's own history; the merge is in neither range
LM=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$MAIN" -p "$C" -m "merge lane")
git -C "$R" update-ref refs/heads/wide "$LM"
printf 'sha=%s dirty=0\nexit=0\n' "$LM" >"$P/lanes/wide-gate.log"
verdict "reviewed=$LM base=$MAIN blocking=0" "slices=$MAIN..$C15 $C15..$C"
guard 0 "$R" "git push origin wide"
git -C "$R" update-ref -d refs/heads/wide
rm "$P/lanes/wide-gate.log"
rm "$P/reviews/w2-verdict.md"
guard 0 "$R" "DSP_SKIP_REVIEW=1 git push origin main"
guard 2 "$R" "DSP_SKIP_REVIEW=1 git push origin ung"
guard 0 "$R" "DSP_SKIP_PUSH_GUARD=1 git push origin ung"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung S >/dev/null
guard 2 "$R" "git push origin main" # --sins on is kept across re-activations
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung S --sins off >/dev/null
guard 0 "$R" "git push origin main"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
guard 0 "$R" "git push origin main"
jq -e '.rung == "S"' "$(MK "$R")" >/dev/null && ok "a re-activation of the phase without --rung keeps its rung" ||
	bad "re-activation without --rung: $(cat "$(MK "$R")")"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 2 --repo "$R" --sections 1- --activate >/dev/null
grep -q rung "$(MK "$R")" && bad "a new phase without --rung keeps the old phase's rung" || ok "a new phase without --rung has none"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
# execution.md's `--activate --sins on` names neither --repo nor --sections: both are kept
before=$(jq -c .args "$(MK "$R")")
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --activate --sins off >/dev/null
[ "$(jq -c .args "$(MK "$R")")" = "$before" ] && ok "a re-activation keeps --repo, --sections and --main" ||
	bad "a re-activation dropped arguments: $before -> $(jq -c .args "$(MK "$R")")"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
git -C "$R" update-ref -d refs/heads/rel
git -C "$R" update-ref -d refs/heads/ung
git -C "$R" update-ref -d refs/remotes/origin/main
rm -r "$P/reviews" "$P/lanes/rel-gate.log"

# --- a suite CI runs that the local gate does not: a gated push also needs that harness's log (F90)
activate_ci() { CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate "$@"; }
out=$(activate_ci --ci-harness it-3db)
grep -q '"ci_harness": "it-3db"' "$(MK "$R")" && grep -q 'CI harness it-3db: push_guard.py' <<<"$out" &&
	ok "activate --ci-harness: in the marker, announced" || bad "activate --ci-harness: $out"
out=$(jq -n --arg c "git push origin main" --arg d "$R" '{tool_input: {command: $c}, cwd: $d}' | python3 "$SCRIPTS/push_guard.py" 2>&1)
[ $? = 2 ] && grep -q '^  not passed by the CI harness: main = ' <<<"$out" && grep -q 'echo "harness=it-3db"' <<<"$out" &&
	ok "guard: a commit gated locally only is held, with the harness log's command" || bad "guard, CI harness: $out"
# the branch push that starts the CI run cannot carry its log: only `refs/heads/<x>`, x not main, skips it
guard 0 "$R" "git push origin main:refs/heads/ci-run"
guard 2 "$R" "git push origin main:refs/heads/main"
guard 2 "$R" "git push origin main:refs/tags/v9"
# ...a bare name is read against the remote's refs, which may hold a tag of that name
guard 2 "$R" "git push origin main:ci-run"
guard 2 "$R" "git push origin main:heads/main"
guard 2 "$R" "git push origin main:refs/remotes/origin/x"
activate_ci --main refs/heads/main >/dev/null
guard 2 "$R" "git push origin main:refs/heads/main"
activate_ci --main main >/dev/null
printf 'sha=%s dirty=0\nharness=it-3db\nok\nexit=1\n' "$MAIN" >"$P/lanes/ci-it-3db-gate.log"
guard 2 "$R" "git push origin main"
printf 'sha=%s dirty=0\nharness=other\nok\nexit=0\n' "$MAIN" >"$P/lanes/ci-it-3db-gate.log"
guard 2 "$R" "git push origin main"
printf 'sha=%s dirty=0\nharness=it-3db\nok\nexit=0\n' "$MAIN" >"$P/lanes/ci-it-3db-gate.log"
guard 0 "$R" "git push origin main"
activate_ci >/dev/null
grep -q '"ci_harness": "it-3db"' "$(MK "$R")" && ok "a re-activation keeps the CI harness" ||
	bad "a re-activation dropped the CI harness"
rm "$P/lanes/ci-it-3db-gate.log"
guard 2 "$R" "git push origin main"
activate_ci --ci-harness none >/dev/null
guard 0 "$R" "git push origin main"
grep -q ci_harness "$(MK "$R")" && bad "--ci-harness none kept the harness" || ok "--ci-harness none clears it"
# CI on a runner this host is not: activation says so until the route names a harness or none
# (live: Windows CI was "the only test" and no harness was ever set; 2 of 4 pushes went red)
mkdir -p "$R/.github/workflows"
printf 'jobs:\n  t:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: [ubuntu-latest, windows-latest]\n' >"$R/.github/workflows/ci.yml"
jq 'del(.ci_none)' "$(MK "$R")" >"$T/m.json" && mv "$T/m.json" "$(MK "$R")"
out=$(activate_ci 2>&1)
[ $? = 1 ] && grep -q 'CI runs on windows-latest' <<<"$out" && grep -q -- '--ci-harness none' <<<"$out" &&
	ok "activate: CI on another OS asks for a harness" || bad "activate, foreign CI: $out"
activate_ci --ci-harness none >/dev/null
out=$(activate_ci 2>&1)
[ $? = 0 ] && ! grep -q 'CI runs on' <<<"$out" && ok "--ci-harness none is remembered as the answer" ||
	bad "--ci-harness none not remembered: $out"
rm -r "$R/.github"

# --- the state hook: who it speaks to
hook report "$(ev PostToolUse s1 '"tool_name":"Agent"')"
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # throttled
unthrottle
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # nothing changed
hook silent "$(ev PostToolUse s1 '"tool_name":"Read","agent_id":"a1"')"
hook silent "$(ev PostToolUse s2 '"tool_name":"Read"')" # a session that never activated
hook silent "$(ev UserPromptSubmit s1 '"prompt":"what is left on the todo?"')"
hook silent "$(ev UserPromptSubmit s1 '"prompt":"<task-notification>\n<task-id>x</task-id>"')"

# --- the user's answers: nine in ten taking the recommendation stop telling the lead anything
# (F101: 34 of 37 asks taken on one route, 27 of 29 on another, once 3 s after the ask)
askq() { # answer [recommended-label]
	ev PostToolUse s1 "$(jq -nc --arg a "$1" --arg r "${2:-Keep it (Recommended)}" \
		'{tool_name:"AskUserQuestion",tool_input:{questions:[{question:"Q?",options:[{label:$r},{label:"Drop it"}]}]},tool_response:{answers:{"Q?":$a}}}' |
		sed 's/^{//; s/}$//')"
}
out=$(askq 'Drop it' | python3 "$RS" --hook 2>&1)
for _ in 1 2 3 4 5 6 7 8; do out+=$(askq 'Keep it (Recommended)' | python3 "$RS" --hook 2>&1); done
[ -z "$out" ] && jq -e '.asks | length == 9' "$(MK "$R")" >/dev/null &&
	ok "answers are tallied, and fewer than ten say nothing" || bad "answer tally, under ten: $out $(jq -c .asks "$(MK "$R")")"
hook '/took your recommendation in 9 of their last 10 answers/' "$(askq 'Keep it (Recommended)')"
hook silent "$(askq 'Keep it' 'Keep it')" # no option recommended: not tallied
hook '/9 of their last 10/' "$(askq 'Drop it')"
hook silent "$(askq 'Drop it')"
# the tally spans the route: a phase's re-activation (Stage 5's `--sins on`) keeps it
n=$(jq '.asks | length' "$(MK "$R")")
CLAUDE_CODE_SESSION_ID=s1 python3 "$RS" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
jq -e --argjson n "$n" '.asks | length == $n' "$(MK "$R")" >/dev/null && ok "a re-activation keeps the answer tally" ||
	bad "re-activation dropped the answer tally: $(jq -c .asks "$(MK "$R")")"

# --- pending, not missing: index rows without files
printf '| D1 | a |\n| D2 | b |\n' >"$P/decisions/phase1/00-index.md"
echo "ruling" >"$P/decisions/phase1/D1-a.md"
# this old-format index stands for a phase begun before the ledger check: unbound, as on a route
# activated while its index already existed
jq '.ledger["1"] = false' "$(MK "$R")" >"$T/m.json" && mv "$T/m.json" "$(MK "$R")"
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
# a CI harness's log runs only that suite: no full gate, as push_guard.py reads it
printf 'sha=%s dirty=0\nharness=it\nok\nexit=0\n' "$FX" >"$P/lanes/fix-ui-it-gate.log"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R")
grep -q "fix-ui .* · no gate log at this SHA · " <<<"$out" && ok "the lane line: a harness log is no full gate" ||
	bad "harness log as gate: $(grep fix-ui <<<"$out")"
rm "$P/lanes/fix-ui-it-gate.log"
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
touch -d '3 days ago' "$(MK "$R")"
# The stop hook's sent-waits sidecar lives in the registry too, and is no route.
echo '{"a1:b1": 1}' >"$HOME/.claude/dsp-routes/s9.waits.json"
out=$(CLAUDE_CODE_SESSION_ID=s3 python3 "$SCRIPTS/route_state.py" "$M/.plan" --phase 1 --repo "$M" --activate 2>&1) &&
	ok "activate skips a waits sidecar in the registry" || bad "activate beside a waits sidecar: $out"
rm "$HOME/.claude/dsp-routes/s9.waits.json"
grep -q '"--main", "master"' "$(MK "$M")" && ok "--main defaults to master" || bad "--main default: $(cat "$(MK "$M")")"
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

# --- base drift: the base or an assumed branch moved since the decision index recorded them (F91)
B=$T/base
git init -q -b main "$B"
git -C "$B" "${G[@]}" commit -q --allow-empty -m base
git -C "$B" branch api
B0=$(git -C "$B" rev-parse main)
mkdir -p "$B/.plan/decisions/phase1"
printf '# Phase 1\n> **Base**: `main` at `%s`\n> **Assumes**: `api` at `%s` — its new endpoints\n> **Assumes**: `gone` at `%s`\n' \
	"$B0" "${B0:0:12}" "$B0" >"$B/.plan/decisions/phase1/00-index.md"
out=$(python3 "$SCRIPTS/route_state.py" "$B/.plan" --phase 1 --repo "$B")
! grep -q 'base moved\|assumed ref moved' <<<"$out" && grep -q "assumes ref gone *gone (recorded at ${B0:0:9})" <<<"$out" &&
	ok "base drift: nothing moved, one assumed ref gone" || bad "base drift, unmoved: $out"
git -C "$B" checkout -q api
git -C "$B" "${G[@]}" commit -q --allow-empty -m endpoint
git -C "$B" checkout -q main
git -C "$B" "${G[@]}" merge -q --no-ff -m merge api
out=$(python3 "$SCRIPTS/route_state.py" "$B/.plan" --phase 1 --repo "$B")
grep -q "base moved *main 2 commits past ${B0:0:9}" <<<"$out" &&
	grep -q "assumed ref moved *api ${B0:0:9} → [0-9a-f]\{9\}, merged into main" <<<"$out" &&
	ok "base drift: the base moved and an assumed branch merged into it" || bad "base drift, moved: $out"

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
# ...but a task group whose work names a harvest, or a review of harvested findings, is no harvester
hook 'deny:has no Stage 5 budget' "$(harvester exec-p1-01-a 'Fix harvest-date parsing in crop importer')"
hook silent "$(harvester review-1e 'Second-model review of harvested findings fallback')"
reactivate --rung M
hook silent "$(harvester h1 'MR Harvest h1 runtime')"
reactivate

out=$(CLAUDE_CODE_SESSION_ID=s2 python3 "$SCRIPTS/route_state.py" --budget w1 --estimate 10 --groups 4)
[ $? = 2 ] && ok "--budget without a registered session: exit 2" || bad "--budget unregistered: $out"
# the planning dir may be named, as leads did (live, 3 refusals); another route's is refused
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w1 "$T" --estimate 10 --groups 4 2>&1)
[ $? = 2 ] && grep -q "not this session's route" <<<"$out" && ! jq -e '.budgets' "$(MK "$R")" >/dev/null &&
	ok "--budget naming another planning dir records nothing" || bad "--budget other dir: $out"
# so may the phase and repository, as a lead passed them from --activate (live); another route's is refused
for flags in "--phase 2" "--repo $T"; do
	# shellcheck disable=SC2086
	out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w1 $flags --estimate 10 --groups 4 2>&1)
	[ $? = 2 ] && grep -q "not this session's route" <<<"$out" && ! jq -e '.budgets' "$(MK "$R")" >/dev/null &&
		ok "--budget $flags of another route records nothing" || bad "--budget $flags: $out"
done
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w1 "$P" --phase 1 --repo "$R" --estimate 10 --groups 4)
[ $? = 0 ] && jq -e '.budgets[-1] | .label == "w1" and .groups == 4 and .phase == "1"' "$(MK "$R")" >/dev/null &&
	grep -q "past 12.5M spent or 5 exec- dispatches" <<<"$out" &&
	grep -qF 'Ask exactly: "Wave w1: 10M for 4 exec- agents' <<<"$out" &&
	ok "--budget records the wave in the marker and prints the question to ask" || bad "--budget: $out"
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
peer 1 >>"$LEAD"
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
human 1 >>"$HOME/.claude/projects/p/s9.jsonl" # an answer in another lead session of the route
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
human 1 >>"$LEAD"
hook '/^ETA exec-p1-01-a: none yet — no task group of this route has finished/' "$(dispatch exec-p1-01-a t1)"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
jq -e '.budgets | length == 1' "$(MK "$R")" >/dev/null && ok "a re-activation keeps the budgets" || bad "re-activation dropped the budgets"
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
# a lead's prompt rewritten after it sat idle past the cache's life is the wait's cost, not the
# wave's: one such rewrite after a 3 h wait tipped a wave over and cost a third ask (F93)
creq() { # offset id fresh write read
	jq -nc --arg t "$(ts "$1")" --arg id "$2" --argjson f "$3" --argjson w "$4" --argjson r "$5" \
		'{type:"assistant",timestamp:$t,requestId:$id,message:{id:$id,model:"claude-opus-5-5",content:[],usage:{input_tokens:$f,cache_creation_input_tokens:$w,cache_read_input_tokens:$r,output_tokens:0}}}'
}
uprompt() { # offset origin-kind — a user record: the user's prompt, or an agent's return
	jq -nc --arg t "$(ts "$1")" --arg k "$2" '{type:"user",timestamp:$t,origin:{kind:$k},message:{role:"user",content:"x"}}'
}
IW=$T/idle
mkdir -p "$IW"
{
	creq -9000 i1 1000 0 0
	creq -8940 i2 0 1000 100000
	uprompt -4010 human
	creq -4000 i3 0 100000 0
	creq -3990 i4 0 500 100000
} >"$IW/gap.jsonl"
# the same gap ended by a task group's return is the wave's own cost: the lead per group
{
	creq -9000 i1 1000 0 0
	creq -8940 i2 0 1000 100000
	uprompt -4010 task-notification
	creq -4000 i3 0 100000 0
	creq -3990 i4 0 500 100000
} >"$IW/ret.jsonl"
{
	creq -9000 i1 1000 0 0
	creq -8940 i2 0 1000 100000
	creq -3990 i4 0 500 100000
} >"$IW/none.jsonl"
{
	creq -9000 i1 1000 0 0
	creq -8940 i2 0 1000 100000
	creq -8900 i3 0 100000 0
	creq -3990 i4 0 500 100000
} >"$IW/busy.jsonl"
out=$(python3 -c 'import pathlib, sys; sys.path.insert(0, sys.argv[1]); import route_state as r
s = lambda f: r.spend([pathlib.Path(sys.argv[2], f)], sys.argv[3])
print(s("gap.jsonl") == s("none.jsonl") < s("busy.jsonl") == s("ret.jsonl"))' "$SCRIPTS" "$IW" "$(ts -10000)" 2>&1)
[ "$out" = True ] && ok "budget spend: a rewrite after waiting for the user is not the wave's; one after a group's return or no gap is" ||
	bad "budget spend, idle rewrite: $out"
# a budget another lead session recorded, answered there, is not this session's (F74)
CLAUDE_CODE_SESSION_ID=s9 python3 "$SCRIPTS/route_state.py" --budget w3 --estimate 50 --groups 9 >/dev/null
human 2 >>"$HOME/.claude/projects/p/s9.jsonl"
human 2 >>"$LEAD"
hook 'deny:recorded in another lead session' "$(dispatch exec-p1-07-a t7)"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w3 --estimate 50 --groups 9 >/dev/null
human 3 >>"$LEAD"
hook '/^ETA exec-p1-07-a/' "$(dispatch exec-p1-07-a t7)"
# asked first, recorded after the answer in the same turn: that one answer is enough (F93); a
# prompt that opened the turn, or an answer in an earlier turn, is not
endturn() { jq -nc --arg t "$(ts "$1")" '{type:"assistant",timestamp:$t,message:{id:"e",stop_reason:"end_turn",content:[{type:"text",text:"ok"}]}}'; }
auq() { jq -nc --arg t "$(ts "$1")" --arg q "${2:-Raise the budget to 50M?}" '{type:"user",timestamp:$t,toolUseResult:{questions:[{question:$q}],answers:{($q):"Yes"}},message:{role:"user",content:[{type:"tool_result",tool_use_id:"q",content:"answered"}]}}'; }
sleep 4 # past the answers stamped up to 3 s ahead above
endturn -2 >>"$LEAD"
human -1 >>"$LEAD"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w4 --estimate 50 --groups 9 >/dev/null
hook 'deny:has not answered' "$(dispatch exec-p1-07-a t7)"
# an answer to another question in the turn is no answer to the figure
auq -1 'Which lane runs first, p1-01 or p1-02?' >>"$LEAD"
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w4b --estimate 50 --groups 9)
grep -q "Tell the user this figure" <<<"$out" && ok "--budget: an answer to another question does not approve the figure" ||
	bad "--budget took an unrelated answer: $out"
auq -1 'Wave w5: ≈50M for 9 exec- agents — go ahead?' >>"$LEAD" # a non-ASCII sign before the figure
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w5 --estimate 50 --groups 9)
grep -q "answered your question at .*earlier in this turn" <<<"$out" && ok "--budget after an answer in the turn says so" ||
	bad "--budget after an answer: $out"
hook '/^ETA exec-p1-07-a/' "$(dispatch exec-p1-07-a t7)"
endturn 0 >>"$LEAD"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w6 --estimate 50 --groups 9 >/dev/null
hook 'deny:has not answered' "$(dispatch exec-p1-07-a t7)"
human 3 >>"$LEAD"
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

# --- two routes in one repository: each keeps its own phase, budgets, spend and push checks (F93)
P2=$R/.plan2
mkdir -p "$P2/lanes"
CLAUDE_CODE_SESSION_ID=s5 python3 "$RS" "$P2" --phase 4 --repo "$R" --activate --rung M >/dev/null
jq -e '.args[2] == "1" and (.budgets | length) == 8' "$(MK "$R")" >/dev/null && jq -e '.args[2] == "4"' "$(MK "$R" "$P2")" >/dev/null &&
	ok "a second route in the repository leaves the first's phase and budgets" || bad "second route: $(cat "$(MK "$R")")"
L5=$HOME/.claude/projects/p/s5.jsonl
CLAUDE_CODE_SESSION_ID=s5 python3 "$RS" --budget w9 --estimate 1 --groups 9 >/dev/null
human 1 >"$L5"
used 2 u9 5000000 >>"$HOME/.claude/projects/p/s9.jsonl" # 5M by the first route's other lead
hook '/^ETA exec-p4-01-a/' "$(ev PreToolUse s5 "\"tool_name\":\"Agent\",\"tool_input\":{\"name\":\"exec-p4-01-a\"},\"tool_use_id\":\"v1\",\"transcript_path\":\"$L5\"")"
# the pushing session's own route decides; with no session, the newest route
gs() { jq -n --arg c "$2" --arg d "$R" --arg s "$1" '{tool_input: {command: $c}, cwd: $d, session_id: $s}' | python3 "$SCRIPTS/push_guard.py" >/dev/null 2>&1; }
printf 'sha=%s dirty=0\nok\nexit=0\n' "$(git -C "$R" rev-parse main)" >"$P/lanes/two-gate.log"
gs s1 "git push origin main" && ok "guard: s1's route has main's gate log" || bad "guard: s1's own route"
gs s5 "git push origin main" && bad "guard: s5's route has no gate log, yet passed" || ok "guard: s5's route holds main"
gs "" "git push origin main" && bad "guard: no session took the older route" || ok "guard: no session, the newest route holds main"
rm "$(MK "$R" "$P2")" "$HOME/.claude/dsp-routes/s5.json" "$P/lanes/two-gate.log"
# a route activated under the one-per-repository marker moves to its own, budgets and all
X=$T/xrepo
git init -q -b main "$X"
mkdir -p "$X/.plan"
echo "{\"planning_dir\": \"$(realpath "$X/.plan")\", \"budgets\": [{\"label\": \"old\"}]}" >"$X/.git/dsp-route.json"
CLAUDE_CODE_SESSION_ID=s6 python3 "$RS" "$X/.plan" --phase 1 --repo "$X" --activate >/dev/null
[ ! -e "$X/.git/dsp-route.json" ] && jq -e '.budgets[0].label == "old"' "$(MK "$X")" >/dev/null &&
	ok "a legacy marker moves to the route's own, budgets kept" || bad "legacy marker: $(ls "$X/.git")"
rm "$HOME/.claude/dsp-routes/s6.json"

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
# --project-dir naming the project itself, as a lead did (live): its transcripts are under its slug
D="$T/proj.x" && mkdir -p "$D" && S="$HOME/.claude/projects/$(sed 's/[^A-Za-z0-9]/-/g' <<<"$D")"
mkdir -p "$S" && cp "$HOME/.claude/projects/p/s1.jsonl" "$S/"
out=$(python3 "$SCRIPTS/usage_report.py" s1 --project-dir "$D" 2>&1)
[ $? = 0 ] && grep -q '^lead .*turns=   2' <<<"$out" && ok "usage_report --project-dir of the project reads its transcripts" ||
	bad "usage_report --project-dir project: $(head -3 <<<"$out")"
rm -r "$D" "$S"
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
# --budget prints that measure where the lead prices the wave: groups planned at five tasks where
# two fit ran 5 -> 11 groups (F60, F75)
jq '.budgets = []' "$(MK "$R")" >"$T/gm.json"
jq -nc --arg m "$T/gm.json" --arg p "$P" '{marker:$m, planning_dir:$p}' >"$HOME/.claude/dsp-routes/g1.json"
out=$(CLAUDE_CODE_SESSION_ID=g1 python3 "$SCRIPTS/route_state.py" --budget wg --estimate 5 --groups 3 --tasks 9 2>&1)
grep -q 'about 2 commits fit under 200k' <<<"$out" && grep -q '9 tasks need at least 5 task groups, not 3' <<<"$out" &&
	ok "--budget prints the project's measured group fit and the groups the tasks need" || bad "--budget fit: $out"
out=$(CLAUDE_CODE_SESSION_ID=g1 python3 "$SCRIPTS/route_state.py" --budget wg2 --estimate 5 --groups 6 --tasks 9 2>&1)
grep -q 'about 2 commits fit' <<<"$out" && ! grep -q 'need at least' <<<"$out" &&
	ok "--budget with enough groups only prints the fit" || bad "--budget fit, enough: $out"
# the fit reads task groups only: a scan of every hook session per transcript took 54 s at 300
out=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import usage_report, route_state
def read(*a): raise SystemExit("sdk sessions read")
usage_report.sdk_sessions = read
print(route_state.measured_fit("g1")[1])' "$SCRIPTS" 2>&1)
[ "$out" = 2 ] && ok "--budget's fit never reads the hook sessions" || bad "--budget fit, sdk sessions: $out"
rm "$HOME/.claude/dsp-routes/g1.json"

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
# `all` and `all of wave 1` wait for the earlier wave, not for the plan beside them
W=$T/plans-all
mkdir -p "$W"
plan p1-01-a src/a.js
plan p1-02-c src/app.js
plan p1-03-d src/app.js
printf '| Plan | Wave | Depends on |\n|---|---|---|\n| `p1-01-a` | 1 | — |\n| `p1-02-c` | 2 | all of wave 1 |\n| `p1-03-d` | 2 | all |\n' >"$W/p1-00-index.md"
out=$(python3 "$SCRIPTS/scope_check.py" "$W" --waves "$W/p1-00-index.md")
code=$?
[ $code = 1 ] && grep -q '^wave 2 *src/app.js  p1-02-c, p1-03-d$' <<<"$out" &&
	ok "scope_check --waves: all (of wave 1) does not wait for its own wave" || bad "scope_check --waves, all (exit $code): $out"
# the Plan column may hold plan ids (`p1-02`), as every other doc names a plan
printf '| Plan | Wave | Depends on |\n|---|---|---|\n| p1-01 | 1 | — |\n| `p1-02` | 2 | p1-01 |\n| p1-03 | 2 | all |\n' >"$W/p1-00-index.md"
out=$(python3 "$SCRIPTS/scope_check.py" "$W" --waves "$W/p1-00-index.md")
code=$?
[ $code = 1 ] && grep -q '^wave 2 *src/app.js  p1-02-c, p1-03-d$' <<<"$out" && ! grep -q 'not in the index' <<<"$out" &&
	ok "scope_check --waves: a Plan column of plan ids" || bad "scope_check --waves, plan ids (exit $code): $out"

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
# a build file with no extension and a dotfile are files a plan can list, and not touch
X=$T/extless
mkdir -p "$X/plans"
git init -q -b main "$X/repo"
git -C "$X/repo" "${G[@]}" commit -q --allow-empty -m base
printf 'all:\n' >"$X/repo/Makefile" && echo 'FROM scratch' >"$X/repo/Dockerfile" && echo '*.log' >"$X/repo/.gitignore"
git -C "$X/repo" add -A . && git -C "$X/repo" "${G[@]}" commit -q -m build
printf '# p1-01\n## File structure\n| File | Why |\n|---|---|\n| `Makefile` | build (Ask1) |\n| `Dockerfile` | image (Ask1) |\n| `.gitignore` | logs (Ask1) |\n## Task 1\nCreate `Makefile`, `Dockerfile` and `.gitignore`.\n' >"$X/plans/p1-01-build.md"
out=$(python3 "$SCRIPTS/scope_check.py" "$X/plans" --diff HEAD~1..HEAD --repo "$X/repo")
code=$?
[ $code = 0 ] && grep -q '^0 of 3 changed files' <<<"$out" && ok "scope_check --diff: Makefile, Dockerfile and .gitignore can be planned" ||
	bad "scope_check --diff, extensionless (exit $code): $out"
printf '| **Ask1** | x |\n### Do not touch\n- `Makefile` — the build stays\n' >"$X/00-index.md"
out=$(python3 "$SCRIPTS/scope_check.py" "$X/plans" --asks "$X/00-index.md")
code=$?
[ $code = 1 ] && grep -q 'Makefile  (do not touch)$' <<<"$out" && ok "scope_check --asks: a Makefile not to touch" ||
	bad "scope_check --asks, Makefile (exit $code): $out"
# a rename onto a planned path still deletes an unplanned file, and a path with a space is one path
D=$T/diffr
mkdir -p "$D/plans" "$D/repo/src"
printf '# p1-01-a\n## File structure\n| `src/new.py` | new |\n## Task 1\n' >"$D/plans/p1-01-a.md"
git init -q -b main "$D/repo"
echo keep >"$D/repo/src/old.py"
git -C "$D/repo" add src && git -C "$D/repo" "${G[@]}" commit -q -m base
git -C "$D/repo" mv src/old.py src/new.py && git -C "$D/repo" "${G[@]}" commit -q -m move
echo x >"$D/repo/src/my notes.py"
git -C "$D/repo" add src && git -C "$D/repo" "${G[@]}" commit -q -m notes
out=$(python3 "$SCRIPTS/scope_check.py" "$D/plans" --diff HEAD~2..HEAD --repo "$D/repo")
code=$?
[ $code = 1 ] && grep -qx '   src/old.py' <<<"$out" && grep -qx '   src/my notes.py' <<<"$out" &&
	grep -q '^2 of 3 changed files' <<<"$out" && ok "scope_check --diff: a renamed-away file and a path with a space" ||
	bad "scope_check --diff, rename and space (exit $code): $out"

# --- scope_check.py: a plan cut off after its File structure table, and a file named only inside a
# longer path (`data.rs` holds `a.rs`; another plan's `ui/mod.rs` is not `src/mod.rs`), are
# unimplemented; a bare name under a directory heading still counts (F25)
U=$T/unimpl
mkdir -p "$U"
printf '# p1-01-a\n## File structure\n| `src/a.rs` | a |\n| `src/mod.rs` | module |\n| `src/data.rs` | data |\n## Task 1\nCreate `src/data.rs`.\n' >"$U/p1-01-a.md"
printf '# p1-02-b\n## File structure\n### `core/`\n| `seg.rs` | segment |\n| `ui/mod.rs` | module |\n## Task 1\nEdit `ui/mod.rs`, write `seg.rs`.\n' >"$U/p1-02-b.md"
printf '# p1-03-c\n## File structure\n| `web/app.ts` | app |\n' >"$U/p1-03-c.md"
out=$(python3 "$SCRIPTS/scope_check.py" "$U" --list)
code=$?
[ $code = 1 ] && grep -q '^3 promised files' <<<"$out" && grep -qx '   src/a.rs' <<<"$out" &&
	grep -qx '   src/mod.rs' <<<"$out" && grep -qx '   web/app.ts' <<<"$out" &&
	! grep -qE '^   (src/data.rs|ui/mod.rs|core/seg.rs)$' <<<"$out" &&
	ok "scope_check: a truncated plan and a name inside a longer path are unimplemented" ||
	bad "scope_check unimplemented (exit $code): $out"

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
hook 'deny:re-read .*p1-01-rulings.md \(.*\) before you commit' "$(inagent x1 'git -C /w commit -m x')"
# the text says which: a file the agent never read is not one changed "after your last read"
# (live); a fast-forward makes no commit of the agent's
hook 'deny:p1-01-rulings.md \(you have not read it\) before you commit' "$(inagent x1 'git commit -m x')"
hook silent "$(inagent x1 'git merge --ff-only exec-p1-01-a')"
hook silent "$(inagent x1 'git status')"
hook silent "$(inagent y1 'git commit -m x')"
jq -nc --arg t "$(ts 30)" --arg f "$P/lanes/p1-01-rulings.md" '{type:"assistant",timestamp:$t,message:{id:"r1",content:[{type:"tool_use",id:"r1",name:"Read",input:{file_path:$f}}]}}' >>"$SUB/agent-x1.jsonl"
hook silent "$(inagent x1 'git commit -m x')"
# the transcript repeats a tool_use in an untimestamped api-request-blob record; the read still counts
jq -nc --arg f "$P/lanes/p1-01-rulings.md" '{type:"api-request-blob",agentId:"x1",hash:"h1",sessionId:"s1",message:{id:"r1",content:[{type:"tool_use",id:"r1",name:"Read",input:{file_path:$f}}]}}' >>"$SUB/agent-x1.jsonl"
hook silent "$(inagent x1 'git commit -m x')"
touch -d '+2 minutes' "$P/lanes/p1-01-rulings.md"
hook 'deny:re-read .*p1-01-rulings.md \(the lead changed it after your last read\)' "$(inagent x1 'git commit -m x')"
# every form that makes a commit, read as bash reads it: a regex missed each of these
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 "git -C '/a b/wt' commit -m x")"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'git --no-pager commit -m x')"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'git merge --no-ff lane')"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'git cherry-pick abc123')"
hook silent "$(inagent x1 "git log --grep 'commit'")"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'sudo git commit -m x')"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 "git \$'commit' -m x")"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 "X='git commit -m x'; bash -c \$X")"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'bash <<EOF\ngit commit -m x\nEOF')"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'git merge --ff-only --no-ff lane')"
hook silent "$(inagent x1 'git merge --no-ff --ff-only lane')"
# a script it runs is read where the command's `cd` left it, by path too, and as it will be written
printf 'git commit -m x\n' >"$T/scripts/commit.sh"
chmod +x "$T/scripts/commit.sh"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 "cd $T/scripts && bash commit.sh")"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 "$T/scripts/commit.sh")"
echo ls >"$T/scripts/w.sh"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 "printf 'git commit -m x' >$T/scripts/w.sh; bash $T/scripts/w.sh")"
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
# the text names the action it matched, past the excerpt of a long command (live: the excerpt
# showed no gh at all)
hook 'ask:`gh pr close 9` in `echo' "$(leadbash s1 "$(printf 'echo x; %.0s' {1..30})gh pr close 9")"
# read as bash reads the command: wrapped forms count, quoted text does not, and a long line is
# read in linear time (a regex took 36 s on 1,000 repeats of `gh pr x`)
hook 'ask:timeout 30 gh pr close 5' "$(leadbash s1 'timeout 30 gh pr close 5')"
hook 'ask:bash -c' "$(leadbash s1 "bash -c 'git push origin --delete old'")"
hook silent "$(leadbash s1 "echo 'gh pr close 5'")"
# text a shell runs that the reader cannot follow, or one it fails on, asks when it names gh or push
hook 'ask:eval' "$(leadbash s1 "X='gh pr close 5'; eval \$X")"
hook 'ask:bash' "$(leadbash s1 "echo 'gh pr close 5' | bash")"
deep="$(printf '$(%.0s' {1..1500})gh pr close 5$(printf ')%.0s' {1..1500})"
hook 'ask:acts on the hosted repository' "$(leadbash s1 "$deep")"
# ...and only then: an unreadable command that names gh or push for anything else passes (a stub gh,
# a JS .push(, a plain push held 5 agents' local work on 2026-10-31)
hook silent "$(leadbash s1 'X=$(ls); bash -c $X; node -e a.push(1); gh cache delete 5')"
hook silent "$(leadbash s1 'source ./env.sh; git push origin main')"
hook silent "$(leadbash s1 'eval $X; gh pr view 5; git log --grep merge')"
# a script file the command runs is read: an outward action in it asks
printf 'gh pr merge 7 --squash\n' >"$T/scripts/merge.sh"
hook 'ask:acts on the hosted repository' "$(leadbash s1 "bash $T/scripts/merge.sh")"
hook silent "$(leadbash s1 "bash $T/scripts/env.sh")"

# --- a gate log holds only what the gate printed: a lead sed -i'd one and wrote `exit=0` into
# another, and two pushes went out on them (F97). A gate's own output, redirected or copied, passes.
GL=$P/lanes/p1-01-gate.log
gl() { ev PreToolUse s1 "\"tool_name\":\"$1\",\"tool_input\":{\"file_path\":\"$2\"}"; }
hook 'deny:a gate log holds only what the gate printed' "$(gl Write "$GL")"
hook 'deny:a gate log holds only what the gate printed' "$(gl Edit "$GL")"
hook silent "$(gl Write "$P/lanes/p1-01-rulings.md")"
for c in "sed -i 's/dirty=1/dirty=0/' $GL" "echo \\\"exit=0\\\" >> $GL" \
	"printf 'sha=abc dirty=0\\\\nexit=0\\\\n' > $GL" "cat > $GL <<EOF\\nsha=abc dirty=0\\nEOF" \
	"{ echo sha=abc dirty=0; true; echo exit=0; } > $GL" "perl -pi -e s/1/0/ $GL" \
	"{ echo \\\"sha=\$(git rev-parse HEAD) dirty=0\\\"; make test; echo \\\"exit=\$?\\\"; } > $GL"; do
	hook 'deny:a gate log holds only what the gate printed' "$(leadbash s1 "$c")"
done
hook 'deny:a gate log holds only what the gate printed' "$(inagent x1 "sed -i s/1/0/ $GL")"
# a log named from the lanes directory, as the live edit was: by the command's `cd` or its cwd
hook 'deny:a gate log holds only what the gate printed' "$(leadbash s1 "cd $P/lanes && sed -i s/1/0/ p1-01-gate.log")"
hook 'deny:a gate log holds only what the gate printed' "$(ev PreToolUse s1 "\"cwd\":\"$P/lanes\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo exit=0 >> p1-01-gate.log\"}")"
hook silent "$(ev PreToolUse s1 "\"cwd\":\"$T\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo exit=0 >> p1-01-gate.log\"}")"
# the same claims through a variable, tee, an interpreter, a printf format or another edit tool
hook 'deny:a gate log holds only what the gate printed' "$(gl MultiEdit "$GL")"
hook 'deny:a gate log holds only what the gate printed' "$(gl NotebookEdit "$GL")"
for c in "L=$GL; echo exit=0 > \$L" "echo exit=0 | tee $GL" "tee $GL <<EOF\\nexit=0\\nEOF" \
	"python3 -c \\\"open('$GL','w').write('exit=0')\\\"" "python3 - <<EOF\\nopen('$GL','a').write('exit=0')\\nEOF" \
	"printf 'exit=%d\\\\n' 0 >> $GL" \
	"python3 - <<EOF\\np='$GL'\\ns=open(p).read().replace('exit=1','exit=0')\\nopen(p,'w').write(s)\\nEOF"; do
	hook 'deny:a gate log holds only what the gate printed' "$(leadbash s1 "$c")"
done
# code that writes a handoff whose text quotes a gate log and its claims (live, 50 times)
for c in "printf 'exit=%s\\\\n' \$? >> $GL" "python3 tools/summarize.py $GL" "make gate 2>&1 | tee $GL" \
	"python3 - <<EOF\\np='HANDOFF.md'\\ns=open(p).read()+'gate lanes/p1-01-gate.log sha=abc1234 dirty=0 exit=0'\\nopen(p,'w').write(s)\\nEOF"; do
	hook silent "$(leadbash s1 "$c")"
done
# a function the command names `ex` that reads two logs (live)
hook silent "$(leadbash s1 "cd $P/lanes && ex(){ grep ok \$1 | sort; }; ex a-gate.log > /tmp/b.txt; ex p1-01-gate.log")"
# a status the shell computed is the gate's; so is a marker for a step that failed before it
for c in "{ echo \\\"sha=\$(git rev-parse HEAD) dirty=\$(git status --porcelain | grep -c .)\\\"; make test; echo \\\"exit=\$?\\\"; } > $GL 2>&1" \
	"cargo build > /tmp/b.txt; echo release=\$? > $GL" \
	"grep -q '^exit=' $GL || echo \\\"exit=PRE-\$?\\\" >> $GL; rg -q 'exit=0' $GL" \
	"tools/full-gate.sh /tmp/s > $P/lanes/deps-1-gate.log 2>&1; echo \\\"gate exit=\$?\\\"" \
	"cp /tmp/gate-final.txt $P/lanes/p1-01-gate-neutral.log" "tail -3 $GL; rg exit= $GL; sed -n 1p $GL"; do
	hook silent "$(leadbash s1 "$c")"
done
leadcmd() { jq -nc --arg c "$1" '{hook_event_name:"PreToolUse",session_id:"s1",cwd:"/tmp",tool_name:"Bash",tool_input:{command:$c}}'; }
# a claim spelled into another file in the same command, or a perl flag with an `i` in it, writes no
# log; Python that names the log in the text it writes to the handoff writes none either
RECIPE="{ echo \"sha=\$(git rev-parse HEAD) dirty=\$(git status --porcelain --untracked-files=no | grep -c .)\"; make check; echo \"exit=\$?\"; } > $GL 2>&1"
for c in "$RECIPE; printf 'Gate: %s (exit=0)\n' $GL > $P/lanes/p1-01-checkpoint.md" \
	"$RECIPE; tail -1 $GL | grep -q exit=0 && echo 'gate green (exit=0)'" \
	"perl -Mstrict -ne 'print if /exit=/' $GL" \
	"python3 - <<'EOF'
log = \"$GL\"
last = open(log).read().splitlines()[-1]
open(\".plan/HANDOFF.md\", \"a\").write(f\"- gate: {log} ends {last} (exit=0 expected)\\n\")
EOF" \
	"python3 -c \"import pathlib; h=pathlib.Path('.plan/HANDOFF.md'); h.write_text(h.read_text() + '- gate: ' + '$GL' + ' exit=0')\""; do
	hook silent "$(leadcmd "$c")"
done
# ...while a claim a loop or an `if` prints into the log is still held, and a log a Python write
# opens through a pathlib receiver
for c in "for f in a; do echo exit=0; done > $GL" "if true; then echo exit=0; fi >> $GL" \
	"python3 -c \"import pathlib; pathlib.Path('$GL').open('a').write('exit=0')\""; do
	hook 'deny:a gate log holds only what the gate printed' "$(leadcmd "$c")"
done
# the hold names the computed dirty count its own remedy needs (a literal `dirty=0` is held)
hook 'deny:dirty=\$\(git status --porcelain' "$(leadcmd "sed -i s/1/0/ $GL")"
# reads on the hosted repository are no actions: a GET with fields, a graphql query, a list whose
# label is a verb; a mutation still asks
for c in "gh api -X GET search/issues -f q='repo:o/r is:pr is:open'" \
	"gh api graphql -f query='{ viewer { login } }'" "gh issue list --label delete --state open"; do
	hook silent "$(leadcmd "$c")"
done
hook 'ask:gh api graphql' "$(leadcmd "gh api graphql -f query='mutation { closeIssue(input:{issueId:\"x\"}) { clientMutationId } }'")"
# a commit message that mentions a gh action, next to a command the reader cannot follow or a script
# it runs, runs no gh
mkdir -p "$T/msg/scripts" && printf '#!/bin/bash\nexit 0\n' >"$T/msg/scripts/check.sh" && chmod +x "$T/msg/scripts/check.sh"
for c in "\$PY -m pytest -q && git commit -qm \"docs: gh release create needs a tag\"" \
	"\"\$(git rev-parse --show-toplevel)\"/scripts/test.sh && git commit -qF - <<'EOF'
fix(release): stop gh pr merge before checks
EOF" \
	"cd $T/msg && ./scripts/check.sh && git commit -qam \"ci: check.sh blocks gh pr merge on red\""; do
	hook silent "$(leadcmd "$c")"
done
hook 'ask:gh pr merge' "$(leadcmd "G=gh; \$G pr merge 5")"
# the value is split into words as bash splits it: a name holding the subcommand, or none at all
hook 'ask:gh pr merge' "$(leadcmd "G='gh pr merge'; \$G 5")"
hook 'ask:gh pr merge' "$(leadcmd "E=; \$E gh pr merge 5")"
for c in "IFS=,; G=gh,pr,merge; \$G 5" "export IFS=,; G=gh,pr,merge; \$G 5" "read IFS; G=gh:pr:merge; \$G 5" \
	"IFS=,; unset IFS; G='gh pr merge'; \$G 5" "IFS=:; export IFS=,; G=gh,pr,merge; \$G 5" "IFS=x; G=ghxprxmerge; \$G 5"; do
	hook 'ask:gh pr merge' "$(leadcmd "$c")"
done
# ...but a name set more than once, in a loop or from a command's output is read from the whole
# text, and a computed graphql query may be a mutation
for c in "X=\$(echo gh); \$X pr merge 5" "if true; then G=gh; else G=echo; fi; \$G pr merge 5" \
	"for G in gh; do \$G pr merge 5; done" "gh api graphql -f query=\"\$Q\""; do
	hook 'ask:acts on the hosted repository' "$(leadcmd "$c")"
done
# a write helper's file argument is read whole, nested calls and all; PHP's fopen and an os.open
# with write flags are opens too
for c in "node -e \"require('fs').writeFileSync(require('path').resolve('$GL'), 'exit=0')\"" \
	"php -r \"fwrite(fopen('$GL','w'), 'exit=0');\"" \
	"python3 -c \"import os; os.write(os.open('$GL', os.O_WRONLY), b'exit=0')\""; do
	hook 'deny:a gate log holds only what the gate printed' "$(leadcmd "$c")"
done
# a line of many calls is read in linear time
start=$SECONDS
out=$(leadcmd "python3 -c \"# gate exit=0 $(printf 'open(%.0s' {1..20000})\"" | timeout 20 python3 "$RS" --hook 2>&1)
[ $((SECONDS - start)) -lt 5 ] && ok "20,000 calls on one interpreter line are read in $((SECONDS - start)) s" ||
	bad "20,000 calls on one line: $((SECONDS - start)) s $out"
for long in "$(printf 'gh pr x %.0s' {1..1000})" "$(printf 'git x push y %.0s' {1..1000})"; do
	start=$SECONDS
	out=$(leadbash s1 "$long" | timeout 20 python3 "$RS" --hook 2>&1)
	[ $? = 0 ] && [ -z "$out" ] && [ $((SECONDS - start)) -lt 2 ] &&
		ok "a ${#long}-byte command line is read in $((SECONDS - start)) s" || bad "long line: $((SECONDS - start)) s, $out"
done
hook 'deny:a route agent never runs one' "$(inagent x1 'gh pr close 5')"
hook silent "$(leadbash s2 'gh pr close 5')" # a session with no route

# --- the lead's files grow past one read (F76); the skill changes under a running lead (F78)
head -c 41000 /dev/zero | tr '\0' x >"$P/HANDOFF.md"
seq 40 >"$P/lanes/p1-04-checkpoint.md"
unthrottle
hook '/HANDOFF.md over 40 KB[\s\S]*checkpoint over 35 lines +lanes\/p1-04-checkpoint.md \(40/' "$(ev PostToolUse s1 '"tool_name":"Read"')"
rm "$P/HANDOFF.md" "$P/lanes/p1-04-checkpoint.md"
hook '/Re-read .*HANDOFF.md and, for Stage 5 \(going by the planning dir\) references\/execution.md,/' "$(ev SessionStart s1 '"source":"compact"')"
# a project whose handoff is SESSION-HANDOFF.md: the size check and the re-read name it (live)
head -c 41000 /dev/zero | tr '\0' x >"$P/SESSION-HANDOFF.md"
unthrottle
hook '/SESSION-HANDOFF.md over 40 KB/' "$(ev PostToolUse s1 '"tool_name":"Read"')"
hook '/Re-read \S*\/SESSION-HANDOFF.md and,/' "$(ev SessionStart s1 '"source":"compact"')"
rm "$P/SESSION-HANDOFF.md"
cp -rp "$SCRIPTS/.." "$T/skill"
RS=$T/skill/scripts/route_state.py
touch "$T/skill/references/execution.md"
unthrottle
hook '/changed since this session read it: references\/execution.md \(in /' "$(ev PostToolUse s1 '"tool_name":"Read"')"
unthrottle
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # told once
RS=$SCRIPTS/route_state.py
# the route ended (its marker deleted): a registered session's next route agent waits for --activate
MKR=$(MK "$R")
mv "$MKR" "$T/marker.bak"
hook 'deny:no active decision-spec-plan route' "$(route_agent s1 dsp-deep)"
hook silent "$(leadbash s1 'gh pr close 5')"
mv "$T/marker.bak" "$MKR"

# --- the mechanical tier carries the deep tier's role rules: a lane moved to it once ran with no
# one-group limit, context stop, rulings, no-progress or heavy-run rule
AGENTS=$SCRIPTS/../agents
body() { sed -n '/^Your final message/,$p' "$1"; }
[ -n "$(body "$AGENTS/dsp-deep.md")" ] && [ "$(body "$AGENTS/dsp-deep.md")" = "$(body "$AGENTS/dsp-mechanical.md")" ] &&
	ok "dsp-mechanical carries dsp-deep's role rules" ||
	bad "dsp-mechanical's role rules differ from dsp-deep's: $(diff <(body "$AGENTS/dsp-deep.md") <(body "$AGENTS/dsp-mechanical.md") 2>&1 | head -3)"

# --- the plugin's wiring: its hooks run this plugin's scripts on every event the route needs, and
# a dispatch names the agent as the plugin qualifies it (a bare `dsp-deep` resolves to no agent)
PLUGIN=$SCRIPTS/..
[ "$(jq -r .name "$PLUGIN/.claude-plugin/plugin.json")" = decision-spec-plan ] &&
	ok "plugin.json names the plugin decision-spec-plan" || bad "plugin.json does not name the plugin decision-spec-plan"
reg=$(jq -r '.hooks | to_entries[] | .key as $e | .value[] | "\($e) \(.matcher // "") \(.hooks[].command)"' "$PLUGIN/hooks/hooks.json" | sort)
want='PostToolUse * python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook
PreToolUse Agent|Bash|Write|Edit|MultiEdit|NotebookEdit python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook
PreToolUse Bash python3 "${CLAUDE_PLUGIN_ROOT}/scripts/push_guard.py"
SessionStart compact|resume python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook
SubagentStop  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook
TeammateIdle  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook
UserPromptSubmit  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/route_state.py" --hook'
[ "$reg" = "$want" ] && ok "hooks.json registers route_state.py and push_guard.py on the route's 7 hooks" ||
	bad "hooks.json registrations differ: $(diff <(echo "$want") <(echo "$reg") | head -4)"
bare=$(grep -rn 'subagent_type: "dsp-\|agentType: .dsp-' "$PLUGIN/SKILL.md" "$PLUGIN/references")
[ -z "$bare" ] && ok "every dispatch names decision-spec-plan:dsp-*" || bad "a dispatch names a bare agent: $bare"

# --- an agent that ends its turn while its own background job runs is sent back to wait on it:
# nothing wakes a teammate when the job ends (F92). The hook reads the agent's transcript for the
# jobs it started; SubagentStop says which still run, TeammateIdle leaves it to each output file.
stophook() { # expected-exit regex json
	local out code
	out=$(echo "$3" | python3 "$RS" --hook 2>&1)
	code=$?
	if [ "$code" = "$1" ] && grep -qE -- "$2" <<<"$out"; then ok "stop $1  $3"; else
		bad "stop want $1 /$2/ got $code  $3"
		echo "$out" | sed -n '1,3p'
	fi
}
TASKS=$T/tasks
mkdir -p "$TASKS"
tm=$SUB/agent-aexec-p1-02-a-0123456789abcdef.jsonl
call() { # tool-use-id tool input-json result-text
	jq -nc --arg i "$1" --arg n "$2" --argjson in "$3" '{type:"assistant",message:{content:[{type:"tool_use",id:$i,name:$n,input:$in}]}}'
	jq -nc --arg i "$1" --arg r "$4" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$i,content:$r}]}}'
}
{
	call t1 Bash '{"command":"npm test","run_in_background":true}' "Command running in background with ID: bsh1. Output is being written to: $TASKS/bsh1.output. You will be notified when it completes."
	call t2 Bash '{"command":"ls"}' "a b"
} >"$tm"
idle() { ev TeammateIdle s1 "\"teammate_name\":\"exec-p1-02-a\",\"agent_id\":\"aexec-p1-02-a-0123456789abcdef\",\"transcript_path\":\"$LEAD\""; }
printf 'running\n' >"$TASKS/bsh1.output"
stophook 2 'npm test.*bsh1.output.*F92' "$(idle)"
printf 'running\n\n[exited with code 0]\n' >"$TASKS/bsh1.output"
stophook 0 '^$' "$(idle)"
printf '\n[killed]\n' >"$TASKS/bsh1.output"
stophook 0 '^$' "$(idle)"
call t3 Monitor '{"command":"until grep -q ^exit= g.log; do sleep 20; done","description":"gate"}' "Monitor started (task bmo1, expires in 30m unless the source ends first)." >>"$tm"
printf 'x\n' >"$TASKS/bmo1.output"
stophook 2 'until grep -q \^exit= g.log.*F92' "$(idle)"
rm "$TASKS/bmo1.output"
notice() { # task-id [status] — a task notification the agent received; a monitor's event has no status
	jq -nc --arg p "<task-notification>
<task-id>$1</task-id>
${2:+<status>$2</status>
}<event>x</event>
</task-notification>" '{type:"attachment",attachment:{type:"queued_command",prompt:$p,origin:{kind:"task-notification"}}}'
}
notice bmo1 completed >>"$tm"
stophook 0 '^$' "$(idle)" # its notification ended it
stophook 0 '^$' "$(ev TeammateIdle s1 "\"teammate_name\":\"nobody\",\"agent_id\":\"anobody-00000000\",\"transcript_path\":\"$LEAD\"")"
# a foreground command past its timeout moves to the background without run_in_background
call t4 Bash '{"command":"npx eslint . > lint.log"}' "partial output
Command did not complete within its 300s timeout and was moved to the background (ID: bauto1). Output is being written to: $TASKS/bauto1.output. You will be notified when it completes." >>"$tm"
printf 'x\n' >"$TASKS/bauto1.output"
stophook 2 'npx eslint.*bauto1.output.*F92' "$(idle)"
rm "$TASKS/bauto1.output"
# SubagentStop lists every background job of the session, a neighbour teammate's too (a plan
# author was sent back twice to wait on another's probe): only the jobs the stopping agent's own
# transcript started count, and an agent with no transcript has none.
tb=$SUB/agent-aexec-p1-02-b-0123456789abcdef.jsonl
{
	call u1 Bash '{"command":"npm test > gate.log","run_in_background":true}' "Command running in background with ID: bsb1. Output is being written to: $TASKS/bsb1.output. You will be notified when it completes."
	call u2 Monitor '{"command":"tail -f x","description":"watch"}' "Monitor started (task bsb2, expires in 30m unless the source ends first)."
} >"$tb"
bg() { echo "\"background_tasks\":[{\"id\":\"$1\",\"type\":\"$2\",\"status\":\"$3\",\"command\":\"npm test > gate.log\"}]"; }
sub() { ev SubagentStop "${2:-s1}" "\"agent_id\":\"aexec-p1-02-b-0123456789abcdef\",\"agent_type\":\"dsp-deep\",\"transcript_path\":\"$LEAD\",$1"; }
stophook 2 'npm test > gate.log.*bsb1.output.*F92' "$(sub "$(bg bsb1 shell running)")"
stophook 0 '^$' "$(sub "$(bg bsb1 shell completed)")"
stophook 0 '^$' "$(sub "$(bg bsb1 subagent running)")"
stophook 2 'tail -f x.*F92' "$(sub "$(bg bsb2 monitor running)")"
stophook 0 '^$' "$(sub "$(bg bother shell running)")"                                                 # a neighbour's job
stophook 0 '^$' "$(ev SubagentStop s1 "\"agent_id\":\"a0123456789abcdef\",$(bg bsb1 shell running)")" # no transcript
stophook 0 '^$' "$(sub "$(bg bsb1 shell running)" s77)"                                               # no route
stophook 2 'F92' "$(sub "\"stop_hook_active\":true,$(bg bsb1 shell running)")"
stophook 0 '^$' "$(sub "\"stop_hook_active\":true,$(bg bsb1 shell running)")" # sent back twice: a hung job is the agent's to report

# --- decision_check.py: a SETTLED row that only describes today's code (F86), a requirement
# dimension nobody owns, and a review finding declined with no ruling or refuting test
DC=$T/dc/decisions/phase1
mkdir -p "$DC/verify"
dims() {
	echo "## Requirement dimensions"
	echo "| Dimension | Owner |"
	echo "|---|---|"
	for d in "Actors and workflows" "Data identity" "Ownership and round-trip" "Business rules" "State machines" "Integrations and events" "Validation and exceptions" "Background jobs"; do
		echo "| $d | D1 |"
	done
	echo "| Security and privacy | ${1:-N/A: no accounts, local only} |"
}
index() { # settled-row [security-owner] [extra]
	printf '# Phase 1\n## SETTLED — do not re-open\n### Import\n| # | Ruling | Source |\n|---|---|---|\n%s\n' "$1"
	printf '### Measured numbers that bind any ruling\n| Figure | Source |\n|---|---|\n| 3 s | `src/a.ts:4` |\n\n'
	dims "${2:-}"
	printf '\n## The decisions\n| # | Decision | Serves |\n|---|---|---|\n| D1 | x | Ask1 |\n%s\n' "${3:-}"
}
dcheck() { # expected-exit regex [args]
	local out code want=$1 re=$2
	shift 2
	out=$(python3 "$SCRIPTS/decision_check.py" "$DC" "$@" 2>&1)
	code=$?
	if [ "$code" = "$want" ] && grep -qE -- "$re" <<<"$out"; then ok "decision_check $want /$re/"; else
		bad "decision_check want $want /$re/ got $code"
		echo "$out" | sed -n '1,4p'
	fi
}
dcheck 2 'no index'
index '| S1 | **Names merge only on email** | U2, the user 10-20 |' >"$DC/00-index.md"
dcheck 0 '0 failure'
index '| S1 | **Rows keep 14 columns** | `src/import.ts:40-52` |' >"$DC/00-index.md"
dcheck 1 "S1 cites only code.*Today's code"
index '| S1 | **Rows keep 14 columns** | `docs/spec/02-import.md` §3 |' >"$DC/00-index.md"
dcheck 0 '0 failure'
index '| **Names merge** | U2 |' >"$DC/00-index.md"
dcheck 1 'without an S<n> id'
index '| S1 | **x** | U2 |' 'TBD' >"$DC/00-index.md"
dcheck 1 "dimension 'security' has no owner"
index '| S1 | **x** | U2 |' 'N/A:' >"$DC/00-index.md"
dcheck 1 "dimension 'security' has no owner"
index '| S1 | **x** | U2 |' 'N/A: offline-only' >"$DC/00-index.md"
dcheck 0 '0 failure'
index '| S1 | **x** | U2 |' | grep -v 'Background jobs' >"$DC/00-index.md"
dcheck 1 "dimension 'background jobs' has no row"
# a decision serves an ask or a user ruling, or waits in the backlog; past six, the user triages
# first: a review round grew to 14 mostly-infra decisions priced 20M, approved, and a minute later
# the user disliked the direction (F101)
index '| S1 | **x** | U2 |' | sed 's/| # | Decision | Serves |/| # | Decision | Why |/' >"$DC/00-index.md"
dcheck 1 'decisions table has no Serves column'
index '| S1 | **x** | U2 |' | sed 's/| D1 | x | Ask1 |/| D1 | x | tidier infra |/' >"$DC/00-index.md"
dcheck 1 'D1 serves no ask'
seven=$(for i in 2 3 4 5 6 7; do echo "| D$i | x | Ask1 |"; done)
index '| S1 | **x** | U2 |' '' "$seven" >"$DC/00-index.md"
dcheck 1 '7 decisions to rule.*Triage'
index '| S1 | **x** | U2 |' '' "$seven
> **Triage**: U3 — the user kept all seven" >"$DC/00-index.md"
dcheck 0 '0 failure'
index '| S1 | **x** | U2 |' '' "$(sed '1,2s/Ask1/backlog/' <<<"$seven")" >"$DC/00-index.md"
dcheck 0 '0 failure'
# dispositions, once the review exists: at S in the index, at M and L in the arbiter
printf '# Seams\n## A. BLOCKERS\n**R1** — `src/a.ts:9` merges two people with one name; contradicts S1.\n**R2** — the cache is never cleared.\n## E. SAFETY\n- R3 — a crash loses the draft.\n' >"$DC/00-seams.md"
index '| S1 | **x** | U2 |' >"$DC/00-index.md"
dcheck 1 'has no Dispositions table' --rung S
disp() { printf '\n## Dispositions\n| Finding | Disposition | Basis |\n|---|---|---|\n%s\n' "$1"; }
index '| S1 | **x** | U2 |' '' "$(disp '| R1 | declined | known limitation |
| R2 | applied | D1 |')" >"$DC/00-index.md"
dcheck 1 'R3 has no disposition' --rung S
dcheck 1 "R1 is declined on 'known limitation'.*--verifier R1" --rung S
index '| S1 | **x** | U2 |' '' "$(disp '| R1 | re-opened | user asked |
| R2 | applied | D1 |
| R3 | declined | U4 |')" >"$DC/00-index.md"
dcheck 1 'R1 is re-opened against S1, which is still in SETTLED' --rung S
# a decline rests on a SETTLED row only if the row is there
index '| S2 | **y** | U2 |' '' "$(disp '| R1 | declined | S9 |
| R2 | declined | the S3 bucket is out of scope |
| R3 | declined | S2 |')" >"$DC/00-index.md"
dcheck 1 'R1 is declined on S9, which is not in SETTLED' --rung S
dcheck 1 "R2 is declined on 'the S3 bucket" --rung S
index '| S2 | **y** | U2 |' '' "$(disp '| R1 | declined | default |
| R2 | applied | D1 |
| R3 | declined | S2 |')" >"$DC/00-index.md"
dcheck 1 "R1 is declined on 'default'" --rung S
out=$(python3 "$SCRIPTS/decision_check.py" "$DC" --verifier R1 --sha abc123)
p=$DC/verify/R1.prompt.md
[ "$out" = "$p" ] && grep -qF 'merges two people with one name' "$p" && grep -qF 'abc123' "$p" &&
	! grep -qE 'cache|known limitation|Ruling' "$p" && ok "decision_check --verifier writes the claim and commit, nothing else" ||
	bad "decision_check --verifier: $out"
grep -qF 'Mutant run:' "$p" && grep -qF 'Claim:' "$p" && ok "the verifier prompt asks for the claim quoted and a mutant run" ||
	bad "verifier prompt lacks Claim/Mutant run: $(cat "$p")"
# a finding's repro block keeps its shell comments, and a wrapped `#42` is no heading
DF=$T/dc-fence/decisions/phase1
mkdir -p "$DF"
printf '# Seams\n**R1** — importing twice duplicates rows. Repro:\n```sh\n# import the same file twice\napp import a.csv && app import a.csv\n```\nAfter the second run every row is there twice, see\n#42 for the report.\n## B. OTHER\n**R2** — the cache is never cleared.\n' >"$DF/00-seams.md"
python3 "$SCRIPTS/decision_check.py" "$DF" --verifier R1 --sha abc123 >/dev/null
grep -qF 'After the second run every row is there twice' "$DF/verify/R1.prompt.md" && grep -qF '#42 for the report' "$DF/verify/R1.prompt.md" &&
	! grep -qF 'OTHER' "$DF/verify/R1.prompt.md" && ok "decision_check: a finding runs past a fenced # comment to the next heading" ||
	bad "finding cut short: $(cat "$DF/verify/R1.prompt.md")"
# a REFUTED from a test that cannot see the defect refutes nothing: it must fail on a mutant that
# makes the claim true, and quote the claim it checks (published: generated tests are jointly
# valid on 9.21% of tasks)
echo 'Verdict: REFUTED' >"$DC/verify/R1.md"
dcheck 1 "R1's REFUTED in verify/R1.md quotes no line of the claim" --rung S
printf 'Verdict: REFUTED\nClaim: "merges two people with one name"\nRun: npm test -- a → exit=0\nMutant: key by name alone\nMutant run: npm test -- a → exit=0\n' >"$DC/verify/R1.md"
dcheck 1 "R1's REFUTED in verify/R1.md shows no mutant run that fails" --rung S
printf 'Verdict: REFUTED\nClaim: "merges two dogs"\nMutant run: npm test -- a → exit=1\n' >"$DC/verify/R1.md"
dcheck 1 "R1's REFUTED in verify/R1.md quotes no line of the claim" --rung S
printf 'Verdict: REFUTED\nClaim: "merges two people with one   name"\nRun: npm test -- a → exit=0\nMutant: key by name alone\nMutant run: npm test -- a → exit=1\n' >"$DC/verify/R1.md"
dcheck 0 '0 failure' --rung S
echo 'Verdict: UPHELD' >"$DC/verify/R1.md"
dcheck 1 'R1 is declined, but verify/R1.md upheld it' --rung S
# the verifier prompt glosses each verdict; one copied onto the line is still that verdict
echo 'Verdict: UPHELD (the test demonstrates the claim)' >"$DC/verify/R1.md"
dcheck 1 'R1 is declined, but verify/R1.md upheld it' --rung S
# a round with no arbiter (a review round run S-shaped under an M route) keeps them in its index
dcheck 1 'R1 is declined, but verify/R1.md upheld it' --rung M
echo '# Arbiter' >"$DC/00-arbiter.md"
dcheck 1 '00-arbiter.md has no Dispositions table' --rung M
disp '| R1 | applied | A3 |
| R2 | applied | A1 |
| R3 | applied | A2 |' >"$DC/00-arbiter.md"
dcheck 0 '0 failure' --rung M
# a fix that holds a SETTLED row says so and the row stays: findings that upheld a row were
# relabelled "declined" to pass (live)
index '| S1 | **x** | U2 |' '' "$(disp '| R1 | applied (upholds S1) | D1 |
| R2 | applied | D1 |
| R3 | declined | U4 |')" >"$DC/00-index.md"
dcheck 0 '0 failure' --rung S
index '| S1 | **x** | U2 |' '' "$(disp '| R1 | applied (upholds S7) | D1 |
| R2 | applied | D1 |
| R3 | declined | U4 |')" >"$DC/00-index.md"
dcheck 1 'R1 upholds S7, which is not in SETTLED' --rung S
index '| S1 | **x** | U2 |' '' "$(disp '| R1 | declined (upholds S1) | D1 |
| R2 | applied | D1 |
| R3 | declined | U4 |')" >"$DC/00-index.md"
dcheck 1 "R1: disposition 'declined \(upholds S1\)' is not" --rung S
# the hook holds the lead's exec- dispatch while the route's ledger fails, and a verifier whose
# prompt is not the script-written file
dispatch() { ev PreToolUse s1 "\"tool_name\":\"Agent\",\"transcript_path\":\"$LEAD\",\"tool_input\":{\"name\":\"$1\",\"prompt\":$(jq -Rs . <<<"$2")}"; }
index '| S1 | **Rows keep 14 columns** | `src/import.ts:40` |' >"$P/decisions/phase1/00-index.md"
out=$(dispatch exec-p1-09-a go | python3 "$RS" --hook 2>&1)
! grep -q 'decision ledger' <<<"$out" && ok "a phase begun before the ledger check is not held by it" ||
	bad "an unbound phase is held by the ledger: $out"
jq '.ledger["1"] = true' "$(MK "$R")" >"$T/m.json" && mv "$T/m.json" "$(MK "$R")"
hook "deny:decision ledger fails(.|\n)*S1 cites only code" "$(dispatch exec-p1-09-a go)"
index '| S1 | **x** | U2 |' >"$P/decisions/phase1/00-index.md"
out=$(dispatch exec-p1-09-a go | python3 "$RS" --hook 2>&1)
! grep -q 'decision ledger' <<<"$out" && ok "a passing ledger releases the exec- dispatch to the budget gate" ||
	bad "a passing ledger still holds: $out"
# a check added after a phase was bound never holds that phase: its index was written without it
index '| S1 | **x** | U2 |' | sed 's/| # | Decision | Serves |/| # | Decision | Why |/' >"$P/decisions/phase1/00-index.md"
hook "deny:decision ledger fails(.|\n)*no Serves column" "$(dispatch exec-p1-09-a go)"
jq 'del(.ledger["1#checks"])' "$(MK "$R")" >"$T/m.json" && mv "$T/m.json" "$(MK "$R")"
out=$(dispatch exec-p1-09-a go | python3 "$RS" --hook 2>&1)
! grep -q 'decision ledger' <<<"$out" && ok "a phase bound before the Serves check is not held by it" ||
	bad "a phase bound before the Serves check is held: $out"
jq '.ledger["1#checks"] = 2' "$(MK "$R")" >"$T/m.json" && mv "$T/m.json" "$(MK "$R")"
index '| S1 | **x** | U2 |' >"$P/decisions/phase1/00-index.md"
# a review round in its own directory is checked by its own index (live: two rounds never read)
RND=$P/decisions/phase1/wave2-review
mkdir -p "$RND"
index '| S1 | **Rows keep 14 columns** | `src/import.ts:40` |' >"$RND/00-index.md"
hook "deny:decision ledger fails.*wave2-review(.|\n)*S1 cites only code" "$(dispatch exec-p1-09-a go)"
cp "$DC/00-seams.md" "$RND/"
index '| S1 | **x** | U2 |' '' "$(disp '| R1 | applied (upholds S1) | D1 |
| R2 | applied | D1 |
| R3 | declined | U4 |')" >"$RND/00-index.md"
out=$(dispatch exec-p1-09-a go | python3 "$RS" --hook 2>&1)
! grep -q 'decision ledger' <<<"$out" && ok "a review round with its dispositions in its index releases the dispatch" ||
	bad "a passing review round still holds: $out"
# a phase begun before the ledger check still has its later rounds checked
jq '.ledger["1"] = false' "$(MK "$R")" >"$T/m.json" && mv "$T/m.json" "$(MK "$R")"
index '| S1 | **Rows keep 14 columns** | `src/import.ts:40` |' >"$RND/00-index.md"
hook "deny:decision ledger fails.*wave2-review" "$(dispatch exec-p1-09-a go)"
rm -r "$RND"
jq '.ledger["1"] = true' "$(MK "$R")" >"$T/m.json" && mv "$T/m.json" "$(MK "$R")"
cp "$DC/00-seams.md" "$P/decisions/phase1/"
python3 "$SCRIPTS/decision_check.py" "$P/decisions/phase1" --verifier R2 --sha abc123 >/dev/null
hook "deny:verifier's prompt is the file" "$(dispatch verify-R2 "Check R2. The lead thinks it is a known limitation.")"
hook silent "$(dispatch verify-R2 "$(cat "$P/decisions/phase1/verify/R2.prompt.md")")"
# a disputed seven-sins finding goes to the same verifier, its claim taken from the sin's report
RD=$P/reviews/p1-push1
mkdir -p "$RD"
printf '# Wrath — x\n## Findings\n| ID | Severity | Age | Where | Finding | Recommendation | Evidence |\n|---|---|---|---|---|---|---|\n| WRA-1 | high | new | `src/t.ts:9` | a crafted tag crashes the parser | bound the read | probes/wrath/tag.sh → crash |\n| WRA-2 | low | new | `a:1` | other | x | y |\n' >"$RD/wrath.md"
out=$(python3 "$SCRIPTS/decision_check.py" "$RD" --verifier WRA-1 --sha abc123 --from "$RD/wrath.md")
p=$RD/verify/WRA-1.prompt.md
[ "$out" = "$p" ] && grep -qF 'a crafted tag crashes the parser' "$p" && grep -qF 'probes/wrath/tag.sh' "$p" &&
	! grep -qE 'high|bound the read|other' "$p" && ok "decision_check --verifier --from takes a sin's finding, not its severity or fix" ||
	bad "decision_check --verifier --from: $out"
hook silent "$(dispatch verify-WRA-1 "$(cat "$p")")"
hook "deny:verifier's prompt is the file" "$(dispatch verify-WRA-1 "$(cat "$p") Wrath is usually right.")"
# ...and so does one from a sliced run's slice and from a review round's own folder
mkdir -p "$RD/s2" "$P/decisions/phase1/r2"
sed 's/a crafted tag crashes the parser/the loop is quadratic/' "$RD/wrath.md" >"$RD/s2/wrath.md"
python3 "$SCRIPTS/decision_check.py" "$RD/s2" --verifier WRA-1 --sha abc123 --from "$RD/s2/wrath.md" >/dev/null
hook silent "$(dispatch verify-WRA-1 "$(cat "$RD/s2/verify/WRA-1.prompt.md")")"
printf '# Review round 2 findings\n\n- **R1** — the export drops the last row when the file ends without a newline.\n' >"$P/decisions/phase1/r2/00-seams.md"
python3 "$SCRIPTS/decision_check.py" "$P/decisions/phase1/r2" --verifier R1 --sha abc123 >/dev/null
hook silent "$(dispatch verify-R1 "$(cat "$P/decisions/phase1/r2/verify/R1.prompt.md")")"
rm -r "$RD" "$P/decisions/phase1/r2"
rm -r "$P/decisions/phase1/00-index.md" "$P/decisions/phase1/00-seams.md" "$P/decisions/phase1/verify"
# a finding opens with its id — in a numbered list or a heading too — and a wrapped line that
# begins with another finding's id stays in its finding
cat >"$DC/00-seams.md" <<'EOF'
# Seams
1. **R1** — the export drops the id column.
2. **R2** — two people sharing a name merge on import,
R1's keying makes this reachable from every import path.
### **R3** — the cache is never cleared.
EOF
rm -f "$DC/verify/R1.md"
index '| S1 | **x** | U2 |' '' "$(disp '| R1 | applied | D1 |')" >"$DC/00-index.md"
dcheck 1 'R2 has no disposition' --rung S
dcheck 1 'R3 has no disposition' --rung S
python3 "$SCRIPTS/decision_check.py" "$DC" --verifier R2 --sha abc123 >/dev/null &&
	grep -qF 'reachable from every import path' "$DC/verify/R2.prompt.md" &&
	python3 "$SCRIPTS/decision_check.py" "$DC" --verifier R3 --sha abc123 >/dev/null &&
	grep -qF 'the cache is never cleared' "$DC/verify/R3.prompt.md" &&
	ok "decision_check --verifier: a wrapped finding whole, a heading finding" || bad "decision_check wrapped or heading finding"
# an escaped pipe stays inside its table cell
printf '| ID | Severity | Age | Where | Finding | Recommendation | Evidence |\n|---|---|---|---|---|---|---|\n| WRA-3 | high | new | `a:1` | reads unbounded | cap | `cat big.tag \\| ./reader` ran out of memory |\n' >"$T/wrath.md"
python3 "$SCRIPTS/decision_check.py" "$DC" --verifier WRA-3 --sha abc123 --from "$T/wrath.md" >/dev/null &&
	grep -qF 'cat big.tag | ./reader` ran out of memory' "$DC/verify/WRA-3.prompt.md" &&
	ok "decision_check --from: an escaped pipe stays in the evidence" || bad "escaped pipe: $(cat "$DC/verify/WRA-3.prompt.md")"

# --- a re-activation keeps the rung; at S the index holds the decisions; an ended route's phase
# stays bound by the ledger
Q=$T/qrepo
git init -q -b main "$Q"
git -C "$Q" "${G[@]}" commit -q --allow-empty -m one
mkdir -p "$Q/.plan/decisions/phase1"
CLAUDE_CODE_SESSION_ID=s7 python3 "$RS" "$Q/.plan" --phase 1 --repo "$Q" --activate --rung S >/dev/null
CLAUDE_CODE_SESSION_ID=s7 python3 "$RS" "$Q/.plan" --phase 1 --repo "$Q" --activate --sins on >/dev/null
jq -e '.rung == "S" and .sins == "on"' "$(MK "$Q")" >/dev/null && ok "a re-activation without --rung keeps the rung" ||
	bad "re-activation dropped the rung: $(cat "$(MK "$Q")")"
printf '| **D1** | x |\n| **D2** | y |\n' >"$Q/.plan/decisions/phase1/00-index.md"
out=$(python3 "$RS" "$Q/.plan" --phase 1 --repo "$Q")
grep -q 'decisions  0 D files (2 in the index)' <<<"$out" && ! grep -q pending <<<"$out" &&
	ok "rung S: the index's decisions are not pending D files" || bad "rung S pending: $out"
rm "$(MK "$Q")"
CLAUDE_CODE_SESSION_ID=s7 python3 "$RS" "$Q/.plan" --phase 1 --repo "$Q" --activate --rung S >/dev/null
jq -e '.ledger["1"] == true' "$(MK "$Q")" >/dev/null && ok "an ended route's phase stays bound by the ledger" ||
	bad "ledger lost on a restarted route: $(cat "$(MK "$Q")")"
# a review round written before its phase was first activated keeps its format; a later one is bound
mkdir -p "$Q/.plan/decisions/phase2/old-round" "$Q/.plan/decisions/phase2/new-round"
touch "$Q/.plan/decisions/phase2/old-round/00-index.md"
CLAUDE_CODE_SESSION_ID=s7 python3 "$RS" "$Q/.plan" --phase 2 --repo "$Q" --activate >/dev/null
touch "$Q/.plan/decisions/phase2/new-round/00-index.md"
CLAUDE_CODE_SESSION_ID=s7 python3 "$RS" "$Q/.plan" --phase 2 --repo "$Q" --activate >/dev/null
jq -e '.ledger["2/old-round"] == false and (.ledger | has("2/new-round") | not)' "$(MK "$Q")" >/dev/null &&
	ok "a round older than its phase's first activation is unbound, a later one bound" ||
	bad "round binding: $(cat "$(MK "$Q")")"
rm "$HOME/.claude/dsp-routes/s7.json"

# --- the report on odd inputs: a squashed lane named in backticks, another phase's gate log, a
# carriage return before exit=, a non-UTF-8 byte, an en dash, a detached master repo
S=$T/srepo
git init -q -b main "$S"
git -C "$S" "${G[@]}" commit -q --allow-empty -m one
git -C "$S" checkout -q -b p1-01
for f in a b; do
	echo "$f" >"$S/$f"
	git -C "$S" add "$f"
	git -C "$S" "${G[@]}" commit -q -m "$f"
done
LANE=$(git -C "$S" rev-parse HEAD)
git -C "$S" checkout -q main
git -C "$S" merge -q --squash p1-01 >/dev/null
git -C "$S" "${G[@]}" commit -q -m squash
git -C "$S" branch -q -D p1-01
SP=$S/.plan
mkdir -p "$SP/lanes" "$SP/decisions/phase1"
printf 'Final SHA: %s\n' "$LANE" >"$SP/lanes/p1-01-checkpoint.md"
printf -- '- Merged `p1-01` `%s` → `%s`\n' "${LANE:0:9}" "$(git -C "$S" rev-parse --short=9 main)" >"$SP/lanes/wave1-integration.md"
printf 'sha=%s dirty=0\nexit=1\n' "$(printf 'a%.0s' {1..40})" >"$SP/lanes/p2-03-gate.log"
{
	printf 'sha=%s dirty=0\n' "$(git -C "$S" rev-parse main)"
	printf 'progress 100%%\rexit=0\n'
} >"$SP/lanes/wave1-gate.log"
printf '| **D1** | Caf\xe9 |\n' >"$SP/decisions/phase1/00-index.md"
out=$(python3 "$RS" "$SP" --phase 1 --repo "$S" --sections 1–2 2>&1)
grep -q '1 merged into main' <<<"$out" && ok "report: a squashed lane recorded in backticks is merged" || bad "backticked record: $out"
! grep -q 'p2-03-gate.log' <<<"$out" && grep -q 'gates      0 green · 0 red · 1 without exit=' <<<"$out" &&
	ok "report: another phase's gate log is not counted; a CR is no line break" || bad "gate logs: $out"
grep -q 'decisions  0 D files (1 in the index' <<<"$out" && grep -q 'spec       0/2 sections' <<<"$out" &&
	ok "report: a cp1252 byte in the index and an en dash in --sections" || bad "odd bytes: $out"
DM=$T/drepo
git init -q -b master "$DM"
git -C "$DM" "${G[@]}" commit -q --allow-empty -m one
git -C "$DM" "${G[@]}" commit -q --allow-empty -m lane
mkdir -p "$DM/.plan/lanes"
printf 'Final SHA: %s\n' "$(git -C "$DM" rev-parse HEAD)" >"$DM/.plan/lanes/p1-01-checkpoint.md"
git -C "$DM" checkout -q --detach
out=$(python3 "$RS" "$DM/.plan" --phase 1 --repo "$DM")
grep -q '1 merged into master' <<<"$out" && ! grep -q 'does not exist' <<<"$out" &&
	ok "report: a detached master repo with no origin uses master" || bad "detached master: $out"

# --- base drift: an assumed branch merged without moving; the base's upstream moved on a fetch (F91)
B2=$T/base2
git init -q -b main "$B2"
git -C "$B2" "${G[@]}" commit -q --allow-empty -m base
git -C "$B2" checkout -q -b feat
git -C "$B2" "${G[@]}" commit -q --allow-empty -m f
F0=$(git -C "$B2" rev-parse feat)
git -C "$B2" checkout -q main
mkdir -p "$B2/.plan/decisions/phase1"
printf '> **Base**: `main` at `%s`\n> **Assumes**: `feat` at `%s`\n' "$(git -C "$B2" rev-parse main)" "$F0" >"$B2/.plan/decisions/phase1/00-index.md"
git -C "$B2" "${G[@]}" merge -q --no-ff -m merge feat
out=$(python3 "$RS" "$B2/.plan" --phase 1 --repo "$B2")
grep -q "assumed ref merged *feat ${F0:0:9} into main" <<<"$out" && ok "base drift: an assumed branch merged without moving" ||
	bad "base drift, merged unmoved: $out"
git clone -q "$B2" "$T/clone"
C0=$(git -C "$T/clone" rev-parse main)
mkdir -p "$T/clone/.plan/decisions/phase1"
printf '> **Base**: `main` at `%s`\n' "$C0" >"$T/clone/.plan/decisions/phase1/00-index.md"
git -C "$B2" "${G[@]}" commit -q --allow-empty -m later
git -C "$T/clone" fetch -q
out=$(python3 "$RS" "$T/clone/.plan" --phase 1 --repo "$T/clone")
grep -qF "main@{upstream} 1 commits past ${C0:0:9}" <<<"$out" && ok "base drift: the base's upstream moved, fetched not pulled" ||
	bad "base drift, upstream: $out"

# --- usage_report.py: a route's other headless lead is a lead, a project named alike is not a
# worktree, and with no session id the running session's own transcript
W=$T/tab
git init -q -b main "$W"
git -C "$W" "${G[@]}" commit -q --allow-empty -m one
git -C "$W" worktree add -q "$T/tab-p1-01" -b p1-01
git init -q -b main "$T/tab-v2"
UP=$HOME/.claude/projects
mkdir -p "$UP/-t-tab" "$UP/-t-tab-p1-01" "$UP/-t-tab-v2"
crec() { # offset id tokens cwd [entrypoint]
	jq -nc --arg t "$(ts "$1")" --arg id "$2" --argjson n "$3" --arg c "$4" --arg e "${5:-cli}" \
		'{type:"assistant",timestamp:$t,requestId:$id,cwd:$c,entrypoint:$e,message:{id:$id,model:"claude-opus-5-5",content:[],usage:{input_tokens:$n}}}'
}
{
	crec -100 a1 1000000 "$W"
	crec -50 a2 1000000 "$W"
} >"$UP/-t-tab/lead.jsonl"
crec -80 b1 5000000 "$W" sdk-cli >"$UP/-t-tab/lead2.jsonl"
echo '{}' >"$HOME/.claude/dsp-routes/lead2.json"
crec -80 c1 2000000 "$T/tab-p1-01" sdk-ts >"$UP/-t-tab-p1-01/hook.jsonl"
crec -80 d1 7000000 "$T/tab-v2" sdk-py >"$UP/-t-tab-v2/other.jsonl"
touch -d '1 minute ago' "$UP/-t-tab/lead.jsonl"
out=$(python3 "$SCRIPTS/usage_report.py" lead --project-dir "$UP/-t-tab" 2>&1)
grep -q '^total 4.0M = lead 2.0M + 0 agents 0.0M + 1 hook sessions 2.0M' <<<"$out" &&
	ok "usage_report: hook sessions are neither a route's lead nor another project" || bad "usage_report hook sessions: $(head -2 <<<"$out")"
out=$(CLAUDE_CODE_SESSION_ID=lead python3 "$SCRIPTS/usage_report.py" --project-dir "$UP/-t-tab" 2>&1)
grep -q '^session lead ' <<<"$out" && ok "usage_report without a session id reports the running session" ||
	bad "usage_report picked: $(head -1 <<<"$out")"
rm "$HOME/.claude/dsp-routes/lead2.json"

# --- every file SKILL.md sends the lead to exists: its pointer to the ask format named a file the
# skill never shipped
gone=$(grep -oE '`[A-Za-z0-9_./-]+\.md`' "$PLUGIN/SKILL.md" | tr -d '`' | sort -u | while read -r n; do
	[ -n "$(find "$(dirname "$PLUGIN/SKILL.md")" -name "$(basename "$n")" -print -quit)" ] || echo "$n"
done)
[ -z "$gone" ] && ok "every file SKILL.md names exists" || bad "SKILL.md names missing files: $gone"

# --- a script's --help is its whole interface: shown only its docstring's first line, a lead read
# ~20k characters of the scripts' source to learn their options (F84)
for s in route_state.py push_guard.py criteria_check.py plan_lint.py scope_check.py test_check.py usage_report.py apply_markers.py decision_check.py; do
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

# --- criteria_check.py: a `# comment` in a fenced block does not end the acceptance section, and
# only the test cell names a test: a spec path or a type's `::` path in a notes column is no test
C=$T/crit
mkdir -p "$C/spec" "$C/plans"
cat >"$C/spec/38-auth.md" <<'EOF'
# 38 Auth
## Acceptance criteria
1. **AC-P4-38-1** login works
2. **AC-P4-38-2** logout works, checked with:
```bash
# start the server first
./run.sh
```
3. **AC-P4-38-3** a session expires after 30 minutes
4. **AC-P4-38-4** five failures lock the account
## Notes
EOF
out=$(python3 "$SCRIPTS/criteria_check.py" "$C/spec" --phase 4 --sections 38)
code=$?
[ $code = 0 ] && grep -qE '^§38 +4 +4  ok$' <<<"$out" && ok "criteria_check: a fenced # comment does not end the section" ||
	bad "criteria_check fenced comment (exit $code): $out"
printf '# 39 Sessions\n## Acceptance criteria\n1. **AC-P4-39-1** a\n2. **AC-P4-39-2** b\n3. **AC-P4-39-3** c\n' >"$C/spec/39-sessions.md"
cat >"$C/plans/p4-01-auth.md" <<'EOF'
# p4-01-auth
## Task 1: sessions
| Id | Task | Test file | Notes |
|---|---|---|---|
| AC-P4-39-1 | 1 | `tests/session_test.py` | |
| AC-P4-39-2 | 1 | — | per `spec/39-sessions.md` |
| AC-P4-39-3 | 1 | — | calls `Session::end` |
EOF
out=$(python3 "$SCRIPTS/criteria_check.py" "$C/spec" --phase 4 --sections 39 --plans "$C/plans")
code=$?
[ $code = 1 ] && grep -q '1 of 3 criteria mapped to a task and a test' <<<"$out" &&
	grep -q 'NO TEST FILE: AC-P4-39-2, AC-P4-39-3$' <<<"$out" &&
	ok "criteria_check: only the test cell names a test" || bad "criteria_check test cell (exit $code): $out"
# a table row's id may be bold around code; colocated pytest files and .Tests projects are tests
printf '# 45 Parsing\n## Acceptance criteria\n| Id | Criterion |\n|---|---|\n| **`AC-P4-45-1`** | empty input |\n| **`AC-P4-45-2`** | one row |\n' >"$C/spec/45-parse.md"
mkdir -p "$C/plans45"
printf '# p4-02\n| Id | Task | Test file |\n|---|---|---|\n| AC-P4-45-1 | 1 | `src/parser/test_parse.py` |\n| AC-P4-45-2 | 1 | `MyApp.Tests/ParserTests.cs` |\n\n## Task 1 — parse\n' >"$C/plans45/p4-02-parse.md"
out=$(python3 "$SCRIPTS/criteria_check.py" "$C/spec" --phase 4 --sections 45 --plans "$C/plans45")
code=$?
[ $code = 0 ] && grep -q '2 of 2 criteria mapped' <<<"$out" &&
	ok "criteria_check: bold-code table ids, colocated and .Tests test paths" || bad "criteria_check ids and paths (exit $code): $out"

# --- plan_lint.py: a plan cut off inside a code fence indented under a step is unbalanced
L=$T/lint
mkdir -p "$L"
cat >"$L/p4-01-cut.md" <<'EOF'
**Goal:** a
**Spec:** b
**Depends on:** none
## Task 1 — a
- Produces: a
- Consumes: none
- [ ] Step 1: write the test
  ```python
  def test_a():
      assert a() ==
EOF
out=$(python3 "$SCRIPTS/plan_lint.py" "$L")
code=$?
[ $code = 1 ] && grep -q 'unbalanced fences (1)' <<<"$out" && ok "plan_lint: an indented unclosed fence is unbalanced" ||
	bad "plan_lint indented fence (exit $code): $out"

# --- apply_markers.py: a CRLF file keeps its line endings; a malformed list is refused by name,
# with exit 2 and nothing written, never a traceback
M=$T/markers
mkdir -p "$M/d"
printf '# D2\r\n\r\nThe cache is per user.\r\nOther line.\r\n' >"$M/d/D2-x.md"
echo '[{"file":"D2-x.md","anchor":"per user","ruling":"A1","clause":"one global cache"}]' >"$M/ok.json"
out=$(python3 "$SCRIPTS/apply_markers.py" "$M/d" "$M/ok.json" 2>&1)
code=$?
crlf() { python3 -c 'import sys; b = open(sys.argv[1], "rb").read(); print(b.count(b"\n"), b.count(b"\r\n"))' "$1"; }
[ $code = 0 ] && [ "$(crlf "$M/d/D2-x.md")" = "6 6" ] && grep -q 'SUPERSEDED BY A1' "$M/d/D2-x.md" &&
	ok "apply_markers: a CRLF file keeps CRLF" || bad "apply_markers CRLF (exit $code, lf crlf: $(crlf "$M/d/D2-x.md")): $out"
before=$(md5sum <"$M/d/D2-x.md")
echo '[{"file":"D2-x.md","anchor":"Other line","ruling":"A2"}]' >"$M/noclause.json"
echo '{"file":"D2-x.md"}' >"$M/object.json"
for j in noclause object; do
	out=$(python3 "$SCRIPTS/apply_markers.py" "$M/d" "$M/$j.json" 2>&1)
	code=$?
	[ $code = 2 ] && ! grep -q Traceback <<<"$out" && grep -q "cannot read $M/$j.json" <<<"$out" &&
		[ "$(md5sum <"$M/d/D2-x.md")" = "$before" ] && ok "apply_markers: a malformed list ($j) is refused" ||
		bad "apply_markers malformed $j (exit $code): $out"
done

# --- apply_markers.py: a clause that repeats its anchor re-runs as present; an anchor in a code
# block is marked above the fence; mixed line endings stay mixed; a BOM stays first
printf '# D3\n\nThe client retries three times on a timeout.\n' >"$M/d/D3-r.md"
echo '[{"file":"D3-r.md","anchor":"retries three times","ruling":"A7","clause":"it retries three times only when idempotent"}]' >"$M/r.json"
python3 "$SCRIPTS/apply_markers.py" "$M/d" "$M/r.json" >/dev/null
out=$(python3 "$SCRIPTS/apply_markers.py" "$M/d" "$M/r.json" 2>&1)
code=$?
[ $code = 0 ] && [ "$(grep -c 'SUPERSEDED BY A7' "$M/d/D3-r.md")" = 1 ] &&
	ok "apply_markers: a clause repeating its anchor re-runs as present" || bad "apply_markers re-run (exit $code): $out"
printf '# D4\n\n```sql\nCREATE TABLE a (id INTEGER);\n\nCREATE TABLE item (\n  qty INTEGER CHECK (qty <= 3)\n);\n```\n' >"$M/d/D4-s.md"
echo '[{"file":"D4-s.md","anchor":"CHECK (qty <= 3)","ruling":"A4","clause":"qty is capped at 5"}]' >"$M/s.json"
out=$(python3 "$SCRIPTS/apply_markers.py" "$M/d" "$M/s.json" 2>&1)
code=$?
[ $code = 0 ] && grep -A1 'SUPERSEDED BY A4' "$M/d/D4-s.md" | grep -q '^```sql$' &&
	ok "apply_markers: an anchor in a code block is marked above the fence" ||
	bad "apply_markers fence (exit $code): $out $(cat "$M/d/D4-s.md")"
printf '# D5\n\nAlpha paragraph.\r\n\nBeta anchor here.\n' >"$M/d/D5-m.md"
echo '[{"file":"D5-m.md","anchor":"Beta anchor","ruling":"A1","clause":"gone"}]' >"$M/m.json"
out=$(python3 "$SCRIPTS/apply_markers.py" "$M/d" "$M/m.json" 2>&1)
code=$?
[ $code = 0 ] && [ "$(crlf "$M/d/D5-m.md")" = "7 1" ] &&
	ok "apply_markers: mixed line endings stay mixed" || bad "apply_markers mixed (exit $code, lf crlf: $(crlf "$M/d/D5-m.md")): $out"
printf '\xef\xbb\xbf# D6\n\nGamma anchor here.\n' >"$M/d/D6-b.md"
echo '[{"file":"D6-b.md","anchor":"Gamma anchor","ruling":"A2","clause":"gone"}]' >"$M/b.json"
out=$(python3 "$SCRIPTS/apply_markers.py" "$M/d" "$M/b.json" 2>&1)
code=$?
[ $code = 0 ] && [ "$(head -c 7 "$M/d/D6-b.md" | od -An -tx1 | tr -d ' \n')" = efbbbf23204436 ] &&
	[ "$(sed -n 2p "$M/d/D6-b.md")" = '> **Read 00-arbiter.md first.**' ] &&
	ok "apply_markers: a BOM stays first, the header under the title" || bad "apply_markers BOM (exit $code): $out $(head -3 "$M/d/D6-b.md" | od -c | head -3)"

# --- the hook on a route of its own (session h1): a dispatch refused before it ran is no dispatch
H=$T/hk
git init -q -b main "$H"
git -C "$H" "${G[@]}" commit -q --allow-empty -m one
mkdir -p "$H/.plan/lanes" "$H/.plan/decisions/phase1"
HL=$HOME/.claude/projects/hk/h1.jsonl
mkdir -p "$(dirname "$HL")"
human -3600 >"$HL"
CLAUDE_CODE_SESSION_ID=h1 python3 "$SCRIPTS/route_state.py" "$H/.plan" --phase 1 --repo "$H" --activate >/dev/null
hdispatch() { ev PreToolUse h1 "\"tool_name\":\"Agent\",\"tool_input\":{\"name\":\"$1\"},\"tool_use_id\":\"$2\",\"transcript_path\":\"$HL\""; }
refused() { jq -nc --arg t "$(ts "$1")" --arg id "$2" '{type:"user",timestamp:$t,message:{role:"user",content:[{type:"tool_result",tool_use_id:$id,is_error:true,content:"held"}]}}'; }
CLAUDE_CODE_SESSION_ID=h1 python3 "$SCRIPTS/route_state.py" --budget hw --estimate 50 --groups 1 >/dev/null
sent 1 r1 exec-p1-01-a >>"$HL" # held: the user had not answered yet
refused 1 r1 >>"$HL"
human 2 >>"$HL"
hook '/^ETA exec-p1-01-a/' "$(hdispatch exec-p1-01-a r2)"
sent 3 r2 exec-p1-01-a >>"$HL"
hook 'deny:this would be exec- dispatch 2 since' "$(hdispatch exec-p1-02-a r3)"
# each gate fails on its own: a ledger check that raises still leaves the budget hold to run
sleep 4 # past the records stamped up to 3 s ahead above
CLAUDE_CODE_SESSION_ID=h1 python3 "$SCRIPTS/route_state.py" --budget hw2 --estimate 50 --groups 4 >/dev/null
HD=$H/.plan/decisions/phase1
mkdir "$HD/00-index.md"
hook 'deny:has not answered' "$(hdispatch exec-p1-02-a r3)"
rmdir "$HD/00-index.md"
# an arbiter saved in a Windows code page is read, not raised on
index '| S1 | **x** | U2 |' >"$HD/00-index.md"
printf '# Seams\n**R1** — the cache is never cleared.\n' >"$HD/00-seams.md"
printf '## Dispositions\n| R | How | Basis |\n|---|---|---|\n| R2 | applied | fixed \x96 see U1 |\n' >"$HD/00-arbiter.md"
hook 'deny:decision ledger fails(.|\n)*R1 has no disposition in 00-arbiter.md' "$(hdispatch exec-p1-02-a r3)"
rm "$HD/00-index.md" "$HD/00-seams.md" "$HD/00-arbiter.md"

# a teammate's monitor runs, with no output file yet, until its notification or its TaskStop (F92)
HS=$HOME/.claude/projects/hk/h1/subagents
mkdir -p "$HS"
hm=$HS/agent-aexec-p1-03-a-0123456789abcdef.jsonl
hidle() { ev TeammateIdle h1 "\"teammate_name\":\"exec-p1-03-a\",\"agent_id\":\"aexec-p1-03-a-0123456789abcdef\",\"transcript_path\":\"$HL\""; }
call m1 Monitor '{"command":"until grep -q ^exit= g.log; do sleep 20; done","description":"gate"}' "Monitor started (task hmo1, expires in 30m unless the source ends first)." >"$hm"
stophook 2 'until grep -q \^exit= g.log.*F92' "$(hidle)"
notice hmo1 >>"$hm" # an event: still running
stophook 2 'until grep -q \^exit= g.log.*F92' "$(hidle)"
call m2 Monitor '{"command":"tail -f a.log","description":"a"}' "Monitor started (task hmo2, expires in 30m unless the source ends first)." >>"$hm"
notice hmo2 completed >>"$hm"
stophook 0 '^$' "$(hidle)"
call m3 Monitor '{"command":"tail -f b.log","description":"b"}' "Monitor started (task hmo3, expires in 30m unless the source ends first)." >>"$hm"
call s3 TaskStop '{"task_id":"hmo3"}' '{"message":"Successfully stopped task: hmo3"}' >>"$hm"
stophook 0 '^$' "$(hidle)"
# a job is the one Claude Code records with the result (toolUseResult), not one its output quotes
rcall() { # tool-use-id command result-text toolUseResult-json
	call "$1" Bash "$(jq -nc --arg c "$2" '{command:$c}')" "$3" | jq -c --argjson u "$4" 'if .type == "user" then .toolUseResult = $u else . end'
}
rcall q1 'cat notes.md' "Command running in background with ID: hph1. Output is being written to: $TASKS/hph1.output." '{"stdout":"quoted"}' >>"$hm"
stophook 0 '^$' "$(hidle)"
printf 'running\n' >"$TASKS/hbg1.output"
rcall q2 'npm run gate' "Command running in background with ID: hbg1. Output is being written to: $TASKS/hbg1.output. You will be notified when it completes." '{"stdout":"","backgroundTaskId":"hbg1"}' >>"$hm"
stophook 2 'npm run gate.*hbg1.output.*F92' "$(hidle)"

# a project named alike whose sessions ran no one knows where is not the route's spend
CLAUDE_CODE_SESSION_ID=h1 python3 "$SCRIPTS/route_state.py" --budget hw3 --estimate 1 --groups 9 >/dev/null
human 1 >>"$HL"
mkdir -p "$UP/hk-other"
crec 2 z1 3000000 '' sdk-cli | jq -c 'del(.cwd)' >"$UP/hk-other/o.jsonl"
hook '/^ETA exec-p1-04-a/' "$(hdispatch exec-p1-04-a r9)"

# a verifier prompt saved in a Windows code page is read, not raised on: raised, the check let
# every edited verifier prompt through
mkdir -p "$H/.plan/reviews/s1/verify"
printf 'You decide one claim \x96 R1.\n' >"$H/.plan/reviews/s1/verify/R1.prompt.md"
hook 'deny:a verifier.s prompt is the file' "$(ev PreToolUse h1 "\"tool_name\":\"Agent\",\"tool_input\":{\"name\":\"verify-R1\",\"prompt\":\"edited\"},\"transcript_path\":\"$HL\"")"

# --- test_check.py: a lane that deletes a test file, drops a test or adds a skip turns its gate
# green by testing less; the plan must name each deletion, and every skip goes to the lead
TC=$T/tcheck
mkdir -p "$TC/plans" "$TC/repo/tests" "$TC/repo/src"
printf '# p1-01-x\n## File structure\n| `src/list.ts` | list |\n## Task 1\n' >"$TC/plans/p1-01-x.md"
git init -q -b main "$TC/repo"
printf 'def test_merge():\n    assert 1\n    assert 11\n\n\ndef test_split():\n    assert 2\n\n\ndef test_shift():\n    assert 4\n' >"$TC/repo/tests/test_names.py"
printf "it('sorts', () => {});\n" >"$TC/repo/src/list.test.ts"
printf 'def test_gone():\n    assert 3\n' >"$TC/repo/tests/test_old.py"
printf 'def test_moves():\n    assert 5\n' >"$TC/repo/tests/test_moved.py"
printf 'def test_loose():\n    assert x == 1\n' >"$TC/repo/tests/test_loose.py"
printf '#[test]\nfn reads() {\n    let v = load().expect("loads");\n    // assert_eq!(v, 1) by construction\n    check(v);\n}\n' >"$TC/repo/tests/seam.rs"
printf 'fn one() -> u8 { 1 }\n\n#[test]\nfn adds() {\n    assert_eq!(one(), 1);\n}\n' >"$TC/repo/src/lib.rs"
git -C "$TC/repo" add . && git -C "$TC/repo" "${G[@]}" commit -q -m base
printf 'def test_merge():\n    assert 1\n' >"$TC/repo/tests/test_names.py"
printf 'def test_shift():\n    assert 4\n' >"$TC/repo/tests/test_other.py"
printf 'def test_loose():\n    assert x\n' >"$TC/repo/tests/test_loose.py"
printf '#[test]\nfn reads() {\n    check(load_ok());\n}\n' >"$TC/repo/tests/seam.rs"
printf "it.skip('sorts', () => {});\n" >"$TC/repo/src/list.test.ts"
printf 'fn one() -> u8 { [0, 1].iter().skip(1).sum() }\n' >"$TC/repo/src/lib.rs"
mkdir -p "$TC/repo/tests/unit"
git -C "$TC/repo" mv tests/test_moved.py tests/unit/test_moved.py
git -C "$TC/repo" rm -q tests/test_old.py
git -C "$TC/repo" add . && git -C "$TC/repo" "${G[@]}" commit -q -m lane
out=$(python3 "$SCRIPTS/test_check.py" "$TC/plans" --diff HEAD~1..HEAD --repo "$TC/repo")
code=$?
[ $code = 1 ] && grep -qx 'DELETED  tests/test_old.py' <<<"$out" &&
	grep -qx 'REMOVED  test_split  tests/test_names.py' <<<"$out" && grep -qx 'REMOVED  adds  src/lib.rs' <<<"$out" &&
	grep -q '^SKIP     src/list.test.ts:1 ' <<<"$out" && grep -qx 'FEWER    tests/test_names.py  1 fewer assertions' <<<"$out" &&
	! grep -q 'test_merge\|test_shift\|test_gone\|test_moves\|lib.rs:\|^REMOVED  sorts\|test_other\|test_loose\|seam.rs' <<<"$out" &&
	ok "test_check: a deleted test file, two dropped tests, a dropped assertion and an added skip; moves, iter().skip and an assertion rewritten in place are not" ||
	bad "test_check (exit $code): $out"
printf 'Task 1 deletes `tests/test_old.py`, drops test_split and the `adds` test.\n' >>"$TC/plans/p1-01-x.md"
out=$(python3 "$SCRIPTS/test_check.py" "$TC/plans" --diff HEAD~1..HEAD --repo "$TC/repo")
code=$?
[ $code = 1 ] && grep -q '^SKIP     src/list.test.ts:1 ' <<<"$out" && grep -q '^FEWER    tests/test_names.py' <<<"$out" &&
	! grep -q '^DELETED\|^REMOVED' <<<"$out" &&
	ok "test_check: deletions the plan names pass, a skip and a dropped assertion still go to the lead" ||
	bad "test_check, named (exit $code): $out"
printf "it('sorts', () => {});\n" >"$TC/repo/src/list.test.ts"
printf 'def test_merge():\n    assert 1\n    assert 11\n' >"$TC/repo/tests/test_names.py"
git -C "$TC/repo" add . && git -C "$TC/repo" "${G[@]}" commit -q -m unskip
out=$(python3 "$SCRIPTS/test_check.py" "$TC/plans" --diff HEAD~2..HEAD --repo "$TC/repo")
[ $? = 0 ] && ok "test_check: exit 0 when every change is named and nothing is skipped" || bad "test_check, clean: $out"
out=$(python3 "$SCRIPTS/test_check.py" "$TC/plans" --diff HEAD..HEAD --repo "$TC/repo")
[ $? = 2 ] && ok "test_check: an empty range fails" || bad "test_check, empty range: $out"
# a test file renamed out of the test paths stops running as surely as one deleted; a path git
# quotes (a `"` in it) keeps its own lines, never the previous file's
TQ=$T/tcheck2
mkdir -p "$TQ/plans" "$TQ/repo/tests"
printf '# p1-01-x\n' >"$TQ/plans/p1-01-x.md"
git init -q -b main "$TQ/repo"
printf 'def test_hidden():\n    assert 1\n' >"$TQ/repo/tests/test_hide.py"
printf 'def test_kept():\n    assert 1\n\n\ndef test_quoted():\n    assert 2\n' >"$TQ/repo/tests/test_q\"x.py"
printf 'def test_a():\n    assert 1\n' >"$TQ/repo/tests/test_a.py"
printf 'def test_spaced():\n    assert 1\n\n\ndef test_other():\n    assert 2\n' >"$TQ/repo/tests/test sp.py"
git -C "$TQ/repo" add . && git -C "$TQ/repo" "${G[@]}" commit -q -m base
mkdir -p "$TQ/repo/notes"
git -C "$TQ/repo" mv tests/test_hide.py notes/hide.txt
printf 'def test_kept():\n    assert 1\n' >"$TQ/repo/tests/test_q\"x.py"
printf 'def test_a():\n    assert 1\n    assert 3\n' >"$TQ/repo/tests/test_a.py"
printf 'def test_other():\n    assert 2\n' >"$TQ/repo/tests/test sp.py"
git -C "$TQ/repo" add . && git -C "$TQ/repo" "${G[@]}" commit -q -m lane
out=$(python3 "$SCRIPTS/test_check.py" "$TQ/plans" --diff HEAD~1..HEAD --repo "$TQ/repo")
code=$?
[ $code = 1 ] && grep -qx 'DELETED  tests/test_hide.py' <<<"$out" &&
	grep -qx 'REMOVED  test_quoted  tests/test_q"x.py' <<<"$out" && grep -qx 'REMOVED  test_spaced  tests/test sp.py' <<<"$out" && ! grep -q 'test_a.py\|hide.txt' <<<"$out" &&
	ok "test_check: a test file renamed out of the test paths, and a quoted path" ||
	bad "test_check, rename out and quoted path (exit $code): $out"
# an acceptance test is read-only once written: a later commit that changes its lines — `== 3`
# loosened to `> 0` — goes to the lead, which no count of tests or assertions shows (F99)
TA=$T/tcheck3
mkdir -p "$TA/plans" "$TA/repo/tests"
# only the mapping table's rows, and only test files: a source file's inline tests change with it
printf '# p1-01-x\n| AC | Gate | Run |\n|---|---|---|\n| AC-P1-3-1 | full | `tests/test_unit.py` |\n\n| Id | Task | Test file |\n|---|---|---|\n| AC-P1-3-1 | 1 | `tests/test_ac.py::test_rule` |\n| AC-P1-3-2, -3 | 2 | `tests/test_pre.py` |\n| AC-P1-3-4 | 2 | manual |\n| AC-P1-3-5 | 2 | `src/lib.rs::tests::adds` |\n' >"$TA/plans/p1-01-x.md"
git init -q -b main "$TA/repo"
mkdir -p "$TA/repo/src"
printf 'fn one() -> u8 { 1 }\n' >"$TA/repo/src/lib.rs"
printf 'def test_pre():\n    assert load() == []\n' >"$TA/repo/tests/test_pre.py"
printf 'def test_unit():\n    assert 1\n' >"$TA/repo/tests/test_unit.py"
git -C "$TA/repo" add . && git -C "$TA/repo" "${G[@]}" commit -q -m base
printf 'from m import total\n\n\ndef test_rule():\n    assert total(x) == 3\n' >"$TA/repo/tests/test_ac.py"
git -C "$TA/repo" add . && git -C "$TA/repo" "${G[@]}" commit -q -m 'task 1'
# a test added beside it, its import widened: the import line changes, no assertion does
sed -i 's/import total/import more, total/' "$TA/repo/tests/test_ac.py"
printf '\n\ndef test_more():\n    assert more(y) == 4\n' >>"$TA/repo/tests/test_ac.py"
printf 'def test_unit():\n    assert 2\n' >"$TA/repo/tests/test_unit.py"
git -C "$TA/repo" add . && git -C "$TA/repo" "${G[@]}" commit -q -m 'task 2'
sed -i 's/== 3/> 0/' "$TA/repo/tests/test_ac.py"
sed -i 's/== \[\]/is not None/' "$TA/repo/tests/test_pre.py"
printf 'fn one() -> u8 { 2 }\n' >"$TA/repo/src/lib.rs"
git -C "$TA/repo" add . && git -C "$TA/repo" "${G[@]}" commit -q -m fix
c3=$(git -C "$TA/repo" log -1 --format=%h)
out=$(python3 "$SCRIPTS/test_check.py" "$TA/plans" --diff HEAD~3..HEAD --repo "$TA/repo")
code=$?
[ $code = 1 ] && grep -qx "EDITED   tests/test_ac.py  $c3" <<<"$out" && grep -qx "EDITED   tests/test_pre.py  $c3" <<<"$out" &&
	! grep -q 'test_unit\|manual\|FEWER' <<<"$out" &&
	ok "test_check: an acceptance test changed after it was written goes to the lead; its first commit and additions do not" ||
	bad "test_check, read-only acceptance tests (exit $code): $out"
out=$(python3 "$SCRIPTS/test_check.py" "$TA/plans" --diff HEAD~3..HEAD~1 --repo "$TA/repo")
[ $? = 0 ] && ok "test_check: an acceptance test written and then added to passes" || bad "test_check, acceptance additions: $out"
# a fresh repo with one base commit of the files written so far; tcrun runs the check over it
tcrepo() {
	TB=$(mktemp -d "$T/tc.XXXX")
	mkdir -p "$TB/plans" "$TB/repo/tests"
	git init -q -b main "$TB/repo"
}
tcbase() { git -C "$TB/repo" add -A . && git -C "$TB/repo" "${G[@]}" commit -q -m "${1:-base}"; }
tcrun() { out=$(python3 "$SCRIPTS/test_check.py" "$TB/plans" --diff "${1:-HEAD~1}..HEAD" --repo "$TB/repo"); }
# an assertion dropped beside a test's changed signature: the test is still there, so no REMOVED
# line covers the assertion
tcrepo
printf 'def test_x():\n    assert g() == 2\n    assert f() == 1\n' >"$TB/repo/tests/test_a.py" && tcbase
printf 'def test_x(tmp_path):\n    assert f() == 1\n' >"$TB/repo/tests/test_a.py" && tcbase sig
tcrun
grep -qx 'FEWER    tests/test_a.py  1 fewer assertions' <<<"$out" &&
	ok "test_check: an assertion dropped in the hunk of a test re-defined under its name is counted" || bad "test_check, re-defined test: $out"
# skips written as pytestmark, skipTest and [Ignore("…")]
tcrepo
printf 'import pytest\n\n\ndef test_a():\n    assert a()\n' >"$TB/repo/tests/test_a.py"
printf 'class T(unittest.TestCase):\n    def test_b(self):\n        self.assertTrue(b())\n' >"$TB/repo/tests/test_b.py"
printf 'public class CTests {\n    [Test]\n    public void Works() { Assert.That(c()); }\n}\n' >"$TB/repo/tests/CTests.cs"
tcbase
printf 'import pytest\n\npytestmark = pytest.mark.skip(reason="flaky")\n\n\ndef test_a():\n    assert a()\n' >"$TB/repo/tests/test_a.py"
printf 'class T(unittest.TestCase):\n    def test_b(self):\n        self.skipTest("later")\n        self.assertTrue(b())\n' >"$TB/repo/tests/test_b.py"
printf 'public class CTests {\n    [Test]\n    [Ignore("later")]\n    public void Works() { Assert.That(c()); }\n}\n' >"$TB/repo/tests/CTests.cs"
tcbase skip
tcrun
[ "$(grep -c '^SKIP' <<<"$out")" = 3 ] && ok "test_check: pytestmark, skipTest and [Ignore(\"…\")] are skips" || bad "test_check, skip forms: $out"
# the user's diff.noprefix leaves the paths whole
tcrepo
printf '#[test]\nfn parses() {\n    assert_eq!(1, f());\n    assert_eq!(2, g());\n}\n' >"$TB/repo/tests/parse.rs" && tcbase
printf '#[test]\nfn parses() {\n    assert_eq!(1, f());\n}\n' >"$TB/repo/tests/parse.rs" && tcbase drop
git -C "$TB/repo" config diff.noprefix true
tcrun
[ "$out" = "$(printf 'FEWER    tests/parse.rs  1 fewer assertions\n1 deleted test files, removed tests, added skips, dropped assertions or edited acceptance tests need a ruling')" ] &&
	ok "test_check: diff.noprefix does not cut the paths" || bad "test_check, noprefix: $out"
# a mapping table read as criteria_check reads it: `Task(s)`, and a Test file column that is not
# the third; a same-line `@Test fun name()` names its own test
tcrepo
printf 'def test_ac():\n    assert parse("a") == ["a"]\n' >"$TB/repo/tests/test_ac.py"
mkdir -p "$TB/repo/src/test/kotlin"
printf 'class ParserTest {\n    @Test fun parsesEmpty() {\n        assertEquals(0, parse(""))\n    }\n\n    @Test fun parsesOne() {\n        assertEquals(1, parse("a"))\n    }\n}\n' >"$TB/repo/src/test/kotlin/ParserTest.kt"
tcbase
printf 'def test_ac():\n    assert parse("a")\n' >"$TB/repo/tests/test_ac.py"
printf 'class ParserTest {\n    @Test fun parsesEmpty() {\n        assertEquals(0, parse(""))\n    }\n}\n' >"$TB/repo/src/test/kotlin/ParserTest.kt"
tcbase loosen
printf '# p1-01\n| Id | Task(s) | Notes | Test file |\n|---|---|---|---|\n| AC-P1-1-1 | 1 | see x | `tests/test_ac.py` |\n\n## Task 1 — x\n' >"$TB/plans/p1-01-x.md"
tcrun
grep -q '^EDITED   tests/test_ac.py' <<<"$out" && grep -qx 'REMOVED  parsesOne  src/test/kotlin/ParserTest.kt' <<<"$out" &&
	ok "test_check: a Task(s) table's Test file column, and a same-line @Test fun" || bad "test_check, table and same-line test: $out"
# an acceptance test moved inside the test paths is no edit; one loosened after its move is, and one
# deleted goes to the lead though its mapping row names it
tcrepo
printf 'import x\n\n\ndef test_ac():\n' >"$TB/repo/tests/test_ac.py"
for l in a b c d e; do printf '    assert parse("%s") == ["%s"]\n' $l $l >>"$TB/repo/tests/test_ac.py"; done
printf 'def test_gone():\n    assert 1\n' >"$TB/repo/tests/test_gone.py"
tcbase
git -C "$TB/repo" mv tests/test_ac.py tests/test_parse_ac.py && tcbase move
printf '# p1-01\n| Id | Task | Test file |\n|---|---|---|\n| AC-P1-1-1 | 1 | `tests/test_ac.py` |\n| AC-P1-1-2 | 1 | `tests/test_gone.py` |\n\n## Task 1 — x\n' >"$TB/plans/p1-01-x.md"
tcrun
[ -z "$(grep '^EDITED\|^DELETED' <<<"$out")" ] && ok "test_check: an acceptance test moved inside the test paths is not edited" || bad "test_check, git mv: $out"
sed -i 's/== \["a"\]//' "$TB/repo/tests/test_parse_ac.py" && git -C "$TB/repo" rm -q tests/test_gone.py && tcbase loosen
tcrun HEAD~2
grep -q '^EDITED   tests/test_ac.py' <<<"$out" && grep -qx 'DELETED  tests/test_gone.py' <<<"$out" &&
	ok "test_check: an acceptance test loosened after its move, or deleted, goes to the lead" || bad "test_check, move then loosen: $out"

# --- F41: a lane's commits past its merged SHA that main lacks; a lane the integrator rebased
# and merged has none, though its tip is not the checkpoint's SHA
TF=$T/f41
git init -q -b main "$TF/r"
git -C "$TF/r" "${G[@]}" commit -q --allow-empty -m base
git -C "$TF/r" worktree add -q -b p1-01-a "$TF/wt"
echo x >"$TF/wt/x" && git -C "$TF/wt" add x && git -C "$TF/wt" "${G[@]}" commit -q -m lane
c1=$(git -C "$TF/wt" rev-parse HEAD)
echo y >"$TF/r/y" && git -C "$TF/r" add y && git -C "$TF/r" "${G[@]}" commit -q -m main2
git -C "$TF/wt" "${G[@]}" rebase -q main && git -C "$TF/r" merge -q --ff-only p1-01-a
mkdir -p "$TF/plan/lanes" && printf 'Final SHA: %s\n' "$c1" >"$TF/plan/lanes/p1-01-a-checkpoint.md"
touch -d '-1 hour' "$TF/plan/lanes/p1-01-a-checkpoint.md"
out=$(python3 "$RS" "$TF/plan" --phase 1 --repo "$TF/r" --all 2>&1)
grep -q 'p1-01-a .*merged' <<<"$out" && ! grep -q F41 <<<"$out" &&
	ok "report: a lane rebased and merged has not moved past its SHA" || bad "report, rebased lane: $out"
echo z >"$TF/wt/z" && git -C "$TF/wt" add z && git -C "$TF/wt" "${G[@]}" commit -q -m late
out=$(python3 "$RS" "$TF/plan" --phase 1 --repo "$TF/r" --all 2>&1)
grep -q 'lane moved past its merged SHA *p1-01-a (1 commits, F41)' <<<"$out" &&
	ok "report: a lane commit after its merge, missing from main, is flagged" || bad "report, late lane commit: $out"
# a red CI-harness run is reported like any gate log, though it is no full gate
printf 'sha=%s dirty=0\nharness=pg\n3 failed\nexit=1\n' "$c1" >"$TF/plan/lanes/p1-01-a-gate-pg.log"
out=$(python3 "$RS" "$TF/plan" --phase 1 --repo "$TF/r" --all 2>&1)
grep -q 'gates .* 1 red' <<<"$out" && grep -q 'RED harness=pg exit=1 *lanes/p1-01-a-gate-pg.log' <<<"$out" &&
	ok "report: a red CI-harness gate log is flagged" || bad "report, red harness log: $out"

# a rung-S route activated without --repo: its marker sits in the planning dir's repository, and
# its index rows are the decisions — no D file is pending (templates.md §1)
git init -q -b main "$T/sr" && git -C "$T/sr" "${G[@]}" commit -q --allow-empty -m one
mkdir -p "$T/sr/.plan/decisions/phase1" && printf '| D1 | a |\n| D2 | b |\n' >"$T/sr/.plan/decisions/phase1/00-index.md"
CLAUDE_CODE_SESSION_ID=rs1 python3 "$RS" "$T/sr/.plan" --phase 1 --activate --rung S >/dev/null
out=$(echo '{"hook_event_name":"PostToolUse","session_id":"rs1","cwd":"/tmp","tool_name":"Read"}' | python3 "$RS" --hook 2>&1)
grep -q 'decisions  0 D files (2 in the index)' <<<"$out" && ! grep -q pending <<<"$out" &&
	ok "report: a rung-S route without --repo lists no D file as pending" || bad "report, rung S without --repo: $out"
rm -f "$HOME/.claude/dsp-routes/rs1.json"

# the hook's delta: a lane line that changed is no cleared flag
TC=$T/cl
git init -q -b main "$TC/r" && git -C "$TC/r" "${G[@]}" commit -q --allow-empty -m base
git -C "$TC/r" worktree add -q -b p1-01-a "$TC/wt" && git -C "$TC/wt" "${G[@]}" commit -q --allow-empty -m l1
mkdir -p "$TC/r/.plan/lanes"
printf 'Final SHA: %s\n' "$(git -C "$TC/wt" rev-parse HEAD)" >"$TC/r/.plan/lanes/p1-01-a-checkpoint.md"
touch -d '-1 hour' "$TC/r/.plan/lanes/p1-01-a-checkpoint.md"
CLAUDE_CODE_SESSION_ID=rc1 python3 "$RS" "$TC/r/.plan" --phase 1 --repo "$TC/r" --activate >/dev/null
cev='{"hook_event_name":"PostToolUse","session_id":"rc1","cwd":"/tmp","tool_name":"Read"}'
echo "$cev" | python3 "$RS" --hook >/dev/null
git -C "$TC/wt" "${G[@]}" commit -q --allow-empty -m l2
printf 'Final SHA: %s\n' "$(git -C "$TC/wt" rev-parse HEAD)" >"$TC/r/.plan/lanes/p1-01-a-checkpoint.md"
touch -d '-1 hour' "$TC/r/.plan/lanes/p1-01-a-checkpoint.md"
rm -f "$HOME/.claude/dsp-routes/rc1.checked"
out=$(echo "$cev" | python3 "$RS" --hook 2>&1)
grep -q 'changed between' <<<"$out" && ! grep -q 'flags cleared' <<<"$out" &&
	ok "hook delta: a changed lane line is no cleared flag" || bad "hook delta, lane line: $out"
rm -f "$HOME/.claude/dsp-routes/rc1.json"

[ "$FAIL" = 0 ] && echo "ALL PASS" || echo "FAILURES"
exit "$FAIL"
