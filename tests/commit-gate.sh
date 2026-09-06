#!/usr/bin/env bash
# Deterministic gate and governance fixtures. Every mutation uses a fake repo,
# config, home, record root, and local filesystem remote under TMPDIR.
set -euo pipefail
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_CONFIG

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/governance-gate.XXXXXX")
trap 'rm -rf -- "$TMP"' EXIT
export PATH="$ROOT/templates/hooks:$ROOT/agents/.agents/skills/commit/scripts:$ROOT/agents/.agents/skills/publish/scripts:$PATH"
export GIT_CONFIG_GLOBAL="$TMP/gitconfig" GIT_CONFIG_NOSYSTEM=1
git config --file "$GIT_CONFIG_GLOBAL" alias.ci commit
git config --file "$GIT_CONFIG_GLOBAL" alias.st status
repo="$TMP/re po"
git init -q -b main "$repo"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
payload() {
  jq -cn --arg cwd "$repo" --arg command "$1" \
    '{hook_event_name: "PreToolUse", tool_name: "Bash", cwd: $cwd, tool_input: {command: $command}}'
}
gate() {
  if commit-gate <<<"$(payload "$1")" >/dev/null 2>&1; then echo 0; else echo $?; fi
}

# Literal expansion tricks are inputs, never executed.
# shellcheck disable=SC2016
for denied in 'git commit -q -F -' 'git commit --dry-run; git commit -m x' 'command git commit -m x' \
  '/usr/bin/git commit -m x' 'GIT_DIR=.git git commit -m x' "bash -c 'git commit -m x'" 'git commit -am x' \
  "git -C '$repo' commit -q -F -" 'git -c user.email=x@y commit -m x' 'git --git-dir=.git commit -m x' \
  'cd elsewhere && git commit -m x' $'echo start\ngit commit --amend' 'make lint && git commit -q -F -' \
  'git ci -m x' 'git commit -- a.txt' 'eval "git commit -m x"' "git co''mmit -m x" 'git co""mmit -m x' \
  'git -c alias.x=commit x -m x' $'git \\\ncommit -m x' 'git co\mmit -m x' 'git cherry-pick abc' 'git merge topic' \
  'git pull' 'git rebase main' 'git revert HEAD' 'git am patch' 'git commit-tree HEAD^{tree}' \
  'git update-ref refs/heads/main abc' 'git merge --ff-only x && git commit -m y' 'git replace a b' \
  'git filter-branch --all' "git ch'e'rry-pick abc" 'git cherry\-pick abc' "git \$'cherry-pick' abc" \
  'sub=cherry-pick; git "$sub" abc' 'git $(printf commit) -m x' 'git `echo commit` -m x' 'git {commit,x} -m y' \
  '"$(git --exec-path)/git-commit" -m x' '/usr/lib/git-core/git-cherry-pick abc' 'git stash push' 'git stash' \
  'git notes add -m x' 'git fast-import <dump' "g''it commit -m x" 'gi\t commit -m x' \
  'git merge --ff-only --no-ff topic' 'git merge --ff-only --ff topic' 'git merge --ff --ff-only topic' \
  'git pull --ff-only --no-ff' 'git pull --ff-only --ff' 'git pull --ff-only --rebase' \
  'git merge -m --ff-only topic' 'git merge -- --ff-only' 'git merge --ff-only "$options"' \
  'git merge --ff-only --squash topic' 'git merge --ff-only --no-verify topic'; do
  [[ $(gate "$denied") == 2 ]] || fail "gate allowed: $denied"
done
# shellcheck disable=SC2016
for allowed in 'git status' 'git log --grep commit' 'commit-apply abc' 'git st' 'git merge --ff-only origin/main' \
  'git pull --ff-only' 'git fetch' 'git rev-parse HEAD^{commit}' 'git log --oneline' 'git stash list' \
  'git stash show -p' 'git write-tree' 'git diff --stat' 'echo "$commit"' 'git -C "$ROOT" diff --binary "$empty_tree" -- x' \
  'git diff --stat $ref' 'git -C "$ROOT" log -1 $sha' 'git pull --no-rebase --ff-only origin main' \
  'git merge --quiet --ff-only origin/main' 'git merge --ff-only x && git pull --ff-only' \
  $'grep -i -E x file && cat <<\'EOT\' >note\nthe gate denies any git\ncommit that differs\nEOT'; do
  [[ $(gate "$allowed") == 0 ]] || fail "gate denied: $allowed"
done
for malformed in '{' '[]' '{}' '{}{}' '{"tool_name":"Bash","tool_input":{}}' \
  '{"tool_name":"Bash","tool_input":{"command":42}}' \
  '{"tool_name":"Bash","tool_input":{"command":["git",42]}}' \
  '{"tool_name":"Bash","tool_input":{"command":""}}' \
  '{"tool_name":"Bash","tool_input":{"command":"git co\u0000mmit"}}' \
  '{"tool_name":"Bash","tool_input":{"command":"git status","cmd":"git commit"}}'; do
  if commit-gate <<<"$malformed" >/dev/null 2>&1; then fail 'gate accepted malformed shell input'; fi
done
commit-gate <<<'{"tool_name":"Read","tool_input":{"file_path":"ordinary.txt"}}' >/dev/null || fail 'gate refused a non-shell tool'
commit-gate <<<'{"tool_name":"Bash","tool_input":{"command":["git","status"]}}' >/dev/null || fail 'gate refused valid command array'

fake_home="$TMP/home"
install -D -m 755 "$ROOT/templates/hooks/commit-gate" "$fake_home/.agents/hooks/commit-gate"
claude_hook=$(jq -r '[.hooks.PreToolUse[].hooks[] | select(.type == "command") | .command][0]' "$ROOT/claude-code/.claude/settings.json")
codex_hook=$(python3 -c 'import sys, tomllib; c = tomllib.load(open(sys.argv[1], "rb")); print(c["hooks"]["PreToolUse"][0]["hooks"][0]["command"])' "$ROOT/templates/codex/config.toml")
for hook in "$claude_hook" "$codex_hook"; do
  if HOME=$fake_home sh -c "$hook" <<<"$(payload 'git commit -m x')" >/dev/null 2>&1; then fail 'configured hook did not deny'; fi
  HOME=$fake_home sh -c "$hook" <<<"$(payload 'git status')" >/dev/null 2>&1 || fail 'configured hook denied a plain command'
done
cp -- "$ROOT/opencode/.config/opencode/plugins/commit-gate.js" "$TMP/plugin.mjs"
# shellcheck disable=SC2016
HOME=$fake_home node --input-type=module -e '
const { CommitGate } = await import(process.argv[1]);
const hooks = await CommitGate({ directory: process.argv[2] });
const before = hooks["tool.execute.before"];
for (const command of ["git commit -m x", "git ci -m x", "git cherry-pick abc", "git pull --ff-only --no-ff"]) {
  let denied = false;
  try { await before({ tool: "bash" }, { args: { command } }); } catch { denied = true; }
  if (!denied) { console.error(`plugin allowed: ${command}`); process.exit(1); }
}
await before({ tool: "bash" }, { args: { command: "git status" } });
await before({ tool: "read" }, { args: { filePath: "git commit" } });
' "$TMP/plugin.mjs" "$repo" || fail 'OpenCode plugin did not enforce the gate'

python3 -I "$ROOT/tests/commit-governance.py"
printf 'ok: commit gate and focused governance fixtures\n'
