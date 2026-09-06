#!/usr/bin/env bash
# Behavioral checks for the spar reviewer bridges and payload scanner. Reviewer
# CLIs and fake HOME stay under one private scratch directory. Fixture copies
# of the bridges admit only the exact fixture paths and use the fake account
# home; the unchanged production runtime rejection is tested separately.
# Fixtures that must look like
# credentials are assembled at runtime so the repository itself stays scannable.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
CLAUDE_BRIDGE="$ROOT/agents/.agents/skills/spar/scripts/spar-claude"
CODEX_BRIDGE="$ROOT/agents/.agents/skills/spar/scripts/spar-codex"
SCANNER="$ROOT/agents/.agents/skills/spar/scripts/spar-payload-scan"
WORK=$(mktemp -d)
TMP="$WORK/session"
HOMEBOX="$WORK/home"
export HOME="$HOMEBOX" TMPDIR="$TMP"
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
SHIMS="$HOMEBOX/bin"
trap 'rm -rf -- "$WORK"' EXIT
mkdir -p "$SHIMS" "$TMP/art" "$WORK/bridges"
chmod 700 "$TMP"
chmod 755 "$TMP/art"
SCAN_OUT=("$SCANNER" outbound --scratch-root "$TMP" --)

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

expect_child_stopped() {
  local file=$1 label=$2 child i
  [[ -s $file ]] || return 0
  child=$(<"$file")
  # A group signal is asynchronous; allow bounded scheduling/reaping latency.
  for ((i = 0; i < 40; i++)); do
    kill -0 "$child" 2>/dev/null || return 0
    sleep 0.05
  done
  fail "$label left a descendant after cleanup"
}

# Dependency injection lives only in these disposable copies, never in a
# production environment flag or a writable runtime exemption.
python3 - "$CLAUDE_BRIDGE" "$CODEX_BRIDGE" "$WORK/bridges" "$SHIMS" "$HOMEBOX" <<'PY'
import pathlib, shlex, sys
for source in sys.argv[1:3]:
    text = pathlib.Path(source).read_text()
    needle = '  local root\n'
    assert text.count(needle) == 1
    shims = pathlib.Path(sys.argv[4])
    text = text.replace(needle, needle + '  case $1 in ' + '|'.join(shlex.quote(str(shims / name)) for name in ('claude', 'codex', 'git')) + ') return 0 ;; esac\n')
    needle = 'account_home=$(getent passwd "$(id -u)" | cut -d: -f6)'
    assert text.count(needle) == 1
    text = text.replace(needle, 'account_home=' + shlex.quote(sys.argv[5]))
    target = pathlib.Path(sys.argv[3]) / pathlib.Path(source).name
    target.write_text(text)
    target.chmod(0o755)
PY
cp -- "$SCANNER" "$WORK/bridges/spar-payload-scan"
PRODUCTION_CLAUDE=$CLAUDE_BRIDGE
PRODUCTION_CODEX=$CODEX_BRIDGE
CLAUDE_BRIDGE="$WORK/bridges/spar-claude"
CODEX_BRIDGE="$WORK/bridges/spar-codex"

cat >"$SHIMS/git" <<'SHIM'
#!/usr/bin/env bash
if [[ ${1:-} == config && ${2:-} == --get && -e $(dirname -- "$0")/consent-error ]]; then exit 5; fi
exec /usr/bin/git "$@"
SHIM
chmod 755 "$SHIMS/git"

cat >"$SHIMS/claude" <<'SHIM'
#!/usr/bin/env bash
source "$(dirname -- "$0")/shim.env"
if [[ ${1:-} == --version ]]; then
  if [[ $SPAR_TEST_MODE == bad-version ]]; then printf '%s\n' "$SPAR_TEST_REPLY"; else printf '2.1.261 (Claude Code)\n'; fi
  exit
fi
[[ -z ${CLAUDE_CODE_EFFORT_LEVEL:-} ]] || exit 89
[[ ${CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:-} == 1 && ${DISABLE_AUTOUPDATER:-} == 1 ]] || exit 88
if [[ " $* " == *' auth status '* ]]; then
  printf '%s\n' '{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty"}'
  exit
fi
printf '%s\n' "$*" >>"$SPAR_TEST_CALLS"
printf '%s\0' "$@" >"$SPAR_TEST_CALLS.argv"
printf '%s\n' "$PWD" >>"$SPAR_TEST_CALLS.pwd"
env >"$SPAR_TEST_CALLS.env"
cat >"$SPAR_TEST_CALLS.stdin"
session="33333333-3333-4333-8333-333333333333"
case ${SPAR_TEST_MODE:-ok} in
  ok|bad-version) jq -cn --arg s "$session" '{type:"result",is_error:false,result:"review ok",session_id:$s}' ;;
  metadata) jq -cn --arg s "$session" --arg m "$SPAR_TEST_REPLY" '{type:"result",is_error:false,result:"review ok",session_id:$s,modelUsage:{($m):{}},usage:{service_tier:"standard"},model:"configured-not-effective",effort:"configured-not-effective"}' ;;
  metadata-tier) jq -cn --arg s "$session" --arg t "$SPAR_TEST_REPLY" '{type:"result",is_error:false,result:"review ok",session_id:$s,modelUsage:{"claude-observed-fixture":{}},usage:{service_tier:$t}}' ;;
  malformed-metadata) jq -cn --arg s "$session" --arg m "$SPAR_TEST_REPLY" '{type:"result",is_error:false,result:"review ok",session_id:$s,modelUsage:$m}' ;;
  reply) jq -cn --arg s "$session" --arg t "$SPAR_TEST_REPLY" '{type:"result",is_error:false,result:$t,session_id:$s}' ;;
  failure) printf 'reviewer failed while reading .env policy\n' >&2; exit 1 ;;
  error-result) jq -cn '{type:"result",is_error:true,result:"review failed"}' ;;
  limit) jq -cn '{type:"result",is_error:true,result:"usage limit reached"}' ;;
  hang)
    trap '' TERM
    (trap '' TERM; while :; do sleep 1; done) &
    printf '%s\n' "$!" >"$SPAR_TEST_CHILD_PID"
    while :; do sleep 1; done ;;
esac
SHIM

cat >"$SHIMS/codex" <<'SHIM'
#!/usr/bin/env bash
source "$(dirname -- "$0")/shim.env"
if [[ ${1:-} == --version ]]; then
  if [[ $SPAR_TEST_MODE == bad-version ]]; then printf '%s\n' "$SPAR_TEST_REPLY"; else printf 'codex-cli 0.153.4\n'; fi
  exit
fi
if [[ ${1:-} == login && ${2:-} == status ]]; then
  printf 'Logged in using ChatGPT (fixture workspace)\n'
  exit
fi
[[ ${1:-} == exec ]] || exit 90
printf '%s\n' "$*" >>"$SPAR_TEST_CALLS"
printf '%s\0' "$@" >"$SPAR_TEST_CALLS.argv"
printf '%s\n' "$PWD" >>"$SPAR_TEST_CALLS.pwd"
env >"$SPAR_TEST_CALLS.env"
cat >"$SPAR_TEST_CALLS.stdin"
thread="11111111-1111-4111-8111-111111111111"
case ${SPAR_TEST_MODE:-ok} in
  ok|bad-version)
    jq -cn --arg t "$thread" '{type:"thread.started",thread_id:$t}'
    jq -cn '{type:"item.completed",item:{type:"agent_message",text:"review ok"}}'
    jq -cn '{type:"turn.completed"}' ;;
  reply)
    jq -cn --arg t "$thread" '{type:"thread.started",thread_id:$t}'
    jq -cn --arg t "$SPAR_TEST_REPLY" '{type:"item.completed",item:{type:"agent_message",text:$t}}'
    jq -cn '{type:"turn.completed"}' ;;
  multi)
    jq -cn --arg t "$thread" '{type:"thread.started",thread_id:$t}'
    jq -cn '{type:"item.completed",item:{type:"agent_message",text:"part one"}}'
    jq -cn '{type:"item.completed",item:{type:"agent_message",text:"part two"}}'
    jq -cn '{type:"turn.completed"}' ;;
  failure) printf 'reviewer failed while reading .env policy\n' >&2; exit 1 ;;
  error-result)
    jq -cn --arg t "$thread" '{type:"thread.started",thread_id:$t}'
    jq -cn '{type:"turn.failed",error:"review failed"}' ;;
  limit) printf 'rate limit reached; resets later\n' >&2; exit 1 ;;
  hang)
    trap '' TERM
    (trap '' TERM; while :; do sleep 1; done) &
    printf '%s\n' "$!" >"$SPAR_TEST_CHILD_PID"
    while :; do sleep 1; done ;;
esac
SHIM
chmod 755 "$SHIMS/claude" "$SHIMS/codex"

configure_shims() { # mode calls-file [reply-text] [child-pid-file]
  printf 'SPAR_TEST_MODE=%q\nSPAR_TEST_CALLS=%q\nSPAR_TEST_REPLY=%q\nSPAR_TEST_CHILD_PID=%q\n' \
    "$1" "$2" "${3:-}" "${4:-}" >"$SHIMS/shim.env"
}

# Credential-shaped fixtures are assembled here so no literal exists on disk.
token=$(printf '%s%s' 'sk-' 'UNKNOWNFIXTURE0123456789ABCDEF')
key_name=$(printf '%s_%s' 'OPENAI_API' 'KEY')
envelope=$(printf '%s %s' '-----BEGIN TEST PRIVATE' 'KEY-----')
github_token=$(printf '%s%s' 'ghp_' 'PUBLICFIXTURE0123456789AB')

# --- Scanner ---
printf 'Review ordinary material.' | "$SCANNER" outbound >"$TMP/out" || fail "scanner rejected a safe request"
[[ $(<"$TMP/out") == 'Review ordinary material.' ]] || fail "scanner did not preserve a safe request"

printf 'plan body\n' >"$TMP/art/spar-plan.md"
printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/spar-plan.md" >"$TMP/out" || fail "scanner rejected a safe artifact"
[[ $(<"$TMP/out") == *'===== artifact: spar-plan.md ====='*'plan body'*'===== end artifact: spar-plan.md ====='* ]] ||
  fail "scanner did not inline the artifact with delimiters"
if printf 'Review.' | "$SCANNER" outbound "$TMP/art/spar-plan.md" >/dev/null 2>&1; then fail "artifact accepted without a root"; fi
printf 'operand, not an option\n' >"$TMP/art/--root"
printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/--root" >/dev/null || fail "scanner treated an operand as an option"
if [[ $TMP == /tmp/opencode/* || $TMP == /tmp/claude-*/* || $TMP == /tmp/codex*/* ]]; then
  if printf 'Review.' | "$SCANNER" outbound --root "$TMP" -- "$TMP/art/spar-plan.md" >/dev/null 2>&1; then
    fail "scanner accepted another tool session through a broad root rather than caller scratch"
  fi
fi
for scratch in /tmp /var/tmp /tmp/opencode "$TMP/art"; do
  if printf 'Review.' | "$SCANNER" outbound --scratch-root "$scratch" -- >/dev/null 2>&1; then
    fail "scanner accepted a shared or non-private scratch root: $scratch"
  fi
done

if printf '' | "$SCANNER" outbound >/dev/null 2>&1; then fail "empty request passed scanner"; fi
printf 'binary\0content' >"$TMP/art/payload.bin"
if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/payload.bin" >/dev/null 2>&1; then fail "binary artifact passed scanner"; fi
printf '\377' >"$TMP/art/latin.md"
if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/latin.md" >/dev/null 2>&1; then fail "non-UTF-8 artifact passed scanner"; fi
printf 'outside\n' >"$HOMEBOX/outside.md"
ln -s -- "$TMP/art/spar-plan.md" "$TMP/art/linked-inside.md"
ln -s -- "$HOMEBOX/outside.md" "$TMP/art/linked-outside.md"
printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/linked-inside.md" >/dev/null 2>&1 || fail "symlink to a confined artifact was rejected"
if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/linked-outside.md" >/dev/null 2>&1; then fail "symlink to an outside file passed scanner"; fi
if printf 'Review.' | "${SCAN_OUT[@]}" "$HOMEBOX/outside.md" >/dev/null 2>&1; then fail "artifact outside every root passed scanner"; fi
mkdir -p "$TMP/art/secrets" "$TMP/art/.git"
printf 'harmless\n' >"$TMP/art/secrets/ordinary.md"
printf 'harmless\n' >"$TMP/art/.git/HEAD"
printf 'harmless\n' >"$TMP/art/.env"
for path in "$TMP/art/secrets/ordinary.md" "$TMP/art/.git/HEAD" "$TMP/art/.env"; do
  if printf 'Review.' | "${SCAN_OUT[@]}" "$path" >/dev/null 2>&1; then fail "artifact under a sensitive or Git-internal path passed scanner: $path"; fi
done
ln -- "$TMP/art/spar-plan.md" "$TMP/art/hard-linked.md"
if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/hard-linked.md" >/dev/null 2>&1; then fail "hard-linked artifact passed scanner"; fi
rm -- "$TMP/art/hard-linked.md"
mkfifo "$TMP/art/pipe.md"
if timeout 5 "${SCAN_OUT[@]}" "$TMP/art/pipe.md" <<<'Review.' >/dev/null 2>&1; then fail "FIFO artifact passed scanner"; fi
[[ $? != 124 ]] || fail "FIFO artifact hung the scanner"
if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/missing.md" >/dev/null 2>&1; then fail "missing artifact passed scanner"; fi
python3 -c 'import sys; sys.stdout.write("x" * (512 * 1024 + 1))' >"$TMP/art/oversized.md"
if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/oversized.md" >/dev/null 2>&1; then fail "oversized artifact passed scanner"; fi
for index in 1 2 3; do python3 -c 'import sys; sys.stdout.write("x" * 400000)' >"$TMP/art/big$index.md"; done
if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/big1.md" "$TMP/art/big2.md" "$TMP/art/big3.md" >/dev/null 2>&1; then
  fail "oversized aggregate payload passed scanner"
fi
if python3 -c 'import sys; sys.stdout.write("x" * (256 * 1024 + 1))' | "$SCANNER" outbound >/dev/null 2>&1; then
  fail "oversized request passed scanner"
fi

printf '%s=%s\n' "$key_name" "$token" >"$TMP/art/leak.md"
rc=0
diagnostic=$(printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/leak.md" 2>&1 >/dev/null) || rc=$?
[[ $rc == 2 && $diagnostic != *"$token"* ]] || fail "credential assignment passed scanner or leaked into diagnostics"
for content in "$envelope" "$github_token" "$(printf 'AKIA%s' 'PUBLICFIXTURE123')" \
  "$(printf '//registry.example.invalid/:_%s=%s' 'authToken' 'PUBLICPACKAGEAUTH123')" \
  "$(printf 'machine example.invalid\n%s %s' 'password' 'PUBLICNETRC123')"; do
  printf '%s\n' "$content" >"$TMP/art/vector.md"
  if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/vector.md" >/dev/null 2>&1; then
    fail "credential-shaped fixture passed scanner"
  fi
done
printf '%s=placeholder-token\n//registry.example.invalid/:_%s=example-token\n%s=%s\n' \
  "$key_name" 'authToken' 'PASSWORD' "\${PASSWORD}" >"$TMP/art/placeholders.md"
printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/placeholders.md" >/dev/null 2>&1 ||
  fail "scanner rejected documented placeholder values"
# Secrets in shapes the assignment rule used to miss are rejected.
for content in "$(printf 'AWS_SECRET_ACCESS_%s=%s' 'KEY' 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYRUNTIMEVALUE1')" \
  "$(printf 'DATABASE_URL=postgres:%s//app:%s@db.internal/app' '' 'Hunter2Runtime')" \
  "$(printf 'GITHUB_%s: %s' 'TOKEN' 'literal-runtime-value-9f8e7d')" \
  "$(printf '%s = "%s"' 'passphrase' 'literal runtime words')" \
  "$(printf 'API_%s=SecretStr("%s")' 'TOKEN' 'literal-runtime-value-9f8e7d')" \
  "$(printf 'API_%s=os.getenv("API_TOKEN", "%s")' 'TOKEN' 'literal-runtime-value-9f8e7d')"; do
  printf '%s\n' "$content" >"$TMP/art/shape.md"
  if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/shape.md" >/dev/null 2>&1; then
    fail "credential shape passed scanner: ${content%%[=:]*}"
  fi
done
# Code that handles credentials without containing one is accepted.
{
  printf '%s = get_password()\n' 'password'
  printf '%s: os.environ["CLIENT_SECRET"]\n' 'client_secret'
  printf 'export %s="%s"\n' 'CLIENT_SECRET' "\$SECRET"
  printf '%s=%s\n' 'token' "\$(vault read -field=token secret/app)"
  printf '%s: process.env.API_KEY\n' 'api_key'
  printf 'DATABASE_URL=postgres:%s//app:%s@db.internal/app\n' '' "\${DB_PASSWORD}"
  printf '%s: null\n' 'passphrase'
  printf '%s: {{ secrets.aws }}\n' 'AWS_SECRET_ACCESS_KEY'
  printf '%s = vault.read("secret/data/app")\n' 'password'
  printf '%s = SecretStr(os.environ["DB_PASSWORD"])\n' 'password'
} >"$TMP/art/code.md"
printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/code.md" >/dev/null 2>&1 ||
  fail "scanner rejected credential-handling code without a literal secret"
for _ in $(seq 1 10); do printf '%s=%s\n' "$key_name" "$token"; done >"$TMP/art/many.md"
rc=0
diagnostic=$(printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/many.md" 2>&1 >/dev/null) || rc=$?
[[ $rc == 2 && $(grep -c '^SPAR-PAYLOAD FINDING:' <<<"$diagnostic") == 9 && $diagnostic == *'2 additional findings omitted'* ]] ||
  fail "scanner finding report was not bounded"

sensitive_headers=(
  'diff --git a/.env.production b/.env.production'
  'diff --git a/a/.env-old/config b/a/.env-old/config'
  'diff --git a/private.pem/key.txt b/private.pem/key.txt'
  'diff --git "a/\056env" "b/\056env"'
  'diff --git a/public secrets/x b/public secrets/x'
  'diff --cc secrets/config'
  'diff --combined private.pem'
  '--- a/.netrc'
  '+++ b/auth.json'
  'rename from credentials.old'
  'rename to id_rsa/public.txt'
  'copy to .env_bak'
  'diff --git "a/.env"x" "b/public"'
  'diff --git a/pub\lic b/public'
)
for header in "${sensitive_headers[@]}"; do
  printf '%s\n' "$header" >"$TMP/art/header.md"
  if printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/header.md" >/dev/null 2>&1; then
    fail "sensitive or malformed diff header passed scanner: $header"
  fi
done
printf '%s\n' 'diff --git "a/public\040file" "b/public\040file"' 'diff --git a/public file b/public file' \
  'diff --git "a/caf\303\251.txt" b/public file.txt' '--- a/public' $'+++ b/public\tcomment' \
  '+  diff --git a/.env b/.env' 'diff --git a/credentials-policy.md b/credentials-policy.md' >"$TMP/art/safe-headers.md"
printf 'Review.' | "${SCAN_OUT[@]}" "$TMP/art/safe-headers.md" >/dev/null 2>&1 ||
  fail "safe diff headers were rejected"

printf 'The .env path is denied.\n' | "$SCANNER" reply >/dev/null || fail "reply scanner rejected sensitive-path prose"
if printf '%s=%s\n' "$key_name" "$token" | "$SCANNER" reply >/dev/null 2>&1; then fail "reply scanner accepted a credential value"; fi
# The diff mode used by the commit and publish skills checks content and paths.
printf '%s\n' 'diff --git a/notes.md b/notes.md' '+harmless' | "$SCANNER" diff >/dev/null || fail "diff scanner rejected a safe diff"
if printf '%s\n' 'diff --git a/.env b/.env' '+harmless' | "$SCANNER" diff >/dev/null 2>&1; then fail "diff scanner accepted a sensitive path"; fi
if printf '%s\n' 'diff --git a/app.py b/app.py' "+$(printf '%s=%s' "$key_name" "$token")" | "$SCANNER" diff >/dev/null 2>&1; then
  fail "diff scanner accepted a credential value"
fi
printf '%s\n' 'diff --git a/app.py b/app.py' "-$(printf '%s=%s' "$key_name" "$token")" '+replaced' | "$SCANNER" diff >/dev/null ||
  fail "diff scanner flagged a removed line that the base already publishes"
printf '%s\n' 'diff --git a/config.toml b/config.toml' '+"secrets" = "deny"' '+secrets: allow' | "$SCANNER" diff >/dev/null ||
  fail "diff scanner flagged a permission rule as a secret"

# The repository must stay reviewable by its own scanner, file by file: the whole tree
# exceeds one review request, and the bound on a request is deliberate. The index is
# scanned, since that is what a commit exposes and a working-tree deletion is not.
empty_tree=$(git -C "$ROOT" hash-object -t tree /dev/null)
while IFS= read -r -d '' tracked; do
  git -C "$ROOT" --literal-pathspecs diff --binary --cached "$empty_tree" -- "$tracked" | "$SCANNER" outbound >/dev/null ||
    fail "the repository's own tracked content fails the outbound scan: $tracked"
done < <(git -C "$ROOT" ls-files -z)

# --- Bridges ---
repo="$TMP/repo"
git init -q "$repo"
for bridge in "$PRODUCTION_CLAUDE" "$PRODUCTION_CODEX"; do
  rc=0
  PATH="$SHIMS:$PATH" /usr/bin/env -C "$repo" "$bridge" review 'Refuse planted runtime.' >"$TMP/out" 2>"$TMP/err" || rc=$?
  [[ $rc == 2 && $(<"$TMP/err") == *'resolves under a temp root'* ]] || fail "production bridge admitted a temp runtime"
done
printf 'harmless\n' >"$repo/README.md"
printf 'in-repo artifact\n' >"$repo/notes.md"
# Generator semantics live in review-brief.sh. Exercise the generated artifact's
# handoff to both mocked reviewers in the ordinary review below, without gates.
git -C "$repo" add README.md notes.md
git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.invalid commit -qm 'bridge fixture'
printf 'Outcome: review bridge fixture\nNon-goals: deployment\nConstraints: offline\nAcceptance: intact brief\n' >"$TMP/art/intent.md"
/usr/bin/env -C "$repo" "$ROOT/agents/.agents/skills/spar/scripts/review-brief" \
  --intent "$TMP/art/intent.md" --out "$TMP/art/brief.md" --plan >"$TMP/brief.out"
mkdir -p "$repo/secrets"
printf 'harmless\n' >"$repo/secrets/ordinary.md"
run_bridge() { # bridge mode calls-file [bridge args...]
  local bridge=$1 mode=$2 calls=$3
  shift 3
  BRIDGE_RC=0
  rm -f -- "$calls" "$calls.pwd" "$calls.stdin" "$calls.env" "$calls.argv"
  configure_shims "$mode" "$calls" "${SPAR_TEST_REPLY:-}"
  PATH="$SHIMS:$PATH" /usr/bin/env -C "$repo" "$bridge" review "$@" >"$calls.out" 2>"$calls.err" || BRIDGE_RC=$?
}

for bridge in "$CLAUDE_BRIDGE" "$CODEX_BRIDGE"; do
  name=${bridge##*/}
  calls="$TMP/calls-$name"

  for value in false maybe True '' ' true' $'true\n'; do
    git -C "$repo" config spar.consent "$value"
    run_bridge "$bridge" ok "$calls" "Review after opt-out."
    [[ $BRIDGE_RC == 2 && ! -e $calls && $(<"$calls.err") == *'spar.consent'* ]] ||
      fail "$name ran with spar.consent=$value"
    git -C "$repo" config --unset spar.consent
  done
  git -C "$repo" config spar.consent false
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=spar.consent GIT_CONFIG_VALUE_0=true run_bridge "$bridge" ok "$calls" "Review with an environment override."
  [[ $BRIDGE_RC == 2 && ! -e $calls ]] || fail "$name let a Git environment variable override the opt-out"
  git -C "$repo" config --unset spar.consent
  touch "$SHIMS/consent-error"
  run_bridge "$bridge" ok "$calls" "Refuse a consent lookup error after successful repository discovery."
  [[ $BRIDGE_RC == 2 && ! -e $calls && $(<"$calls.err") == *'spar.consent'* ]] || fail "$name accepted a failed consent lookup"
  rm -- "$SHIMS/consent-error"
  git -C "$repo" config spar.consent true
  run_bridge "$bridge" ok "$calls" "Review with explicit consent."
  [[ $BRIDGE_RC == 0 ]] || fail "$name refused explicit consent"
  git -C "$repo" config --unset spar.consent

  GIT_EDITOR=true OPENAI_BASE_URL=sentinel ANTHROPIC_BASE_URL=sentinel SPAR_TEST_CANARY=leak \
    run_bridge "$bridge" ok "$calls" "Review ordinary material." "$TMP/art/spar-plan.md" "$repo/notes.md" "$TMP/art/brief.md"
  [[ $BRIDGE_RC == 0 && $(<"$calls.out") == 'review ok' ]] || fail "$name failed an ordinary review: $(<"$calls.err")"
  [[ $(<"$calls.err") == *'SPAR-BRIDGE ID: '* ]] || fail "$name did not report the reviewer id"
  [[ $(<"$calls.err") == *'"model":"unknown","effort":"unknown","tier":"unknown","clientversion":"'* ]] ||
    fail "$name inferred effective metadata from configuration"
  [[ $(<"$calls.pwd") == "$repo" ]] || fail "$name did not launch from the repository root"
  [[ $(<"$calls.stdin") == *'Review ordinary material.'*'===== artifact: spar-plan.md ====='*'plan body'*'===== artifact: notes.md ====='* ]] ||
    fail "$name did not send the scanned prompt with the inlined artifacts on stdin"
  [[ $(<"$calls.stdin") == *'===== artifact: brief.md ====='*"$(<"$TMP/art/brief.md")"*'===== end artifact: brief.md ====='* ]] ||
    fail "$name did not relay the complete generated brief with artifact delimiters"
  ! grep -qE '^(OPENAI_BASE_URL|ANTHROPIC_BASE_URL|SPAR_TEST_CANARY|GIT_EDITOR|TMPDIR)=' "$calls.env" ||
    fail "$name passed caller environment to the reviewer"
  grep -qE '^HOME=' "$calls.env" || fail "$name scrubbed HOME from the reviewer"
  args=$(<"$calls")
  cp -- "$calls.argv" "$TMP/$name.argv"
  mapfile -d '' argv <"$calls.argv"
  if [[ $name == spar-claude ]]; then
    for flag in '--tools Read,Glob,Grep' '--permission-mode dontAsk' '--safe-mode' '--setting-sources=' \
      '--strict-mcp-config' '--model fable' '--effort xhigh' '--output-format json' 'ANTHROPIC_DEFAULT_FABLE_MODEL' \
      "Read(/$repo/**)" "Read(/$repo/.git/**)" 'Read(./**/.env)' 'Read(./**/*.pem)' "Read(/$HOME/.ssh/**)"; do
      [[ $args == *"$flag"* ]] || fail "$name isolation missing: $flag"
    done
    # The model is the fable alias and the settings clear exactly its override,
    # checked on the argument values, not on names in the joined text.
    for ((i = 0; i < ${#argv[@]}; i++)); do
      case ${argv[i]} in
        --model) [[ ${argv[i + 1]:-} == fable ]] || fail "$name reviews with '${argv[i + 1]:-}' instead of the fable alias" ;;
        --model=*) fail "$name passes the model as ${argv[i]}" ;;
        --settings) jq -e '.env == {ANTHROPIC_DEFAULT_FABLE_MODEL: ""}' <<<"${argv[i + 1]:-}" >/dev/null 2>&1 ||
          fail "$name settings do not clear exactly the fable override" ;;
      esac
    done
  else
    for flag in 'default_permissions="spar-reviewer"' 'approval_policy="never"' 'features.plugins=false' \
      'features.multi_agent=false' 'web_search="disabled"' 'network={enabled=false}' '":root"="deny"' 'service_tier="default"' \
      "\"$repo\"=\"read\"" "\"$repo/.git\"=\"deny\"" '"**/.env"="deny"' '"**/*.pem"="deny"' \
      "trust_level=\"untrusted\"" 'project_doc_max_bytes=0' '--ignore-user-config' '--ignore-rules'; do
      [[ $args == *"$flag"* ]] || fail "$name isolation missing: $flag"
    done
    # No token selects a model, in any flag or configuration-override form:
    # the catalog default is the reviewer.
    for ((i = 0; i < ${#argv[@]}; i++)); do
      override=""
      case ${argv[i]} in
        --model|--model=*|-m|-m?*|--profile|--profile=*|-p|-p?*) fail "$name pins a reviewer model instead of the catalog default: ${argv[i]}" ;;
        -c|--config) override=${argv[i + 1]:-} ;;
        -c?*) override=${argv[i]#-c} ;;
        --config=*) override=${argv[i]#--config=} ;;
      esac
      key=${override%%=*}
      key=${key//[[:space:]]/}
      [[ -z $override || ( $key != model && $key != *.model ) ]] ||
        fail "$name pins a reviewer model through a configuration override: ${argv[i]} $override"
    done
  fi
  [[ $args != *'/var/tmp/spar-'* ]] || fail "$name still references a handoff directory"

  run_bridge "$bridge" ok "$calls" "Review an outside artifact." "$HOMEBOX/outside.md"
  [[ $BRIDGE_RC == 2 && ! -e $calls && $(<"$calls.err") == *'scratch'* ]] ||
    fail "$name accepted an artifact outside the repository and temp roots"
  run_bridge "$bridge" ok "$calls" "Do not expand roots." --root "$HOMEBOX" "$HOMEBOX/outside.md"
  [[ $BRIDGE_RC == 2 && ! -e $calls ]] || fail "$name accepted caller scanner options"
  printf '\n[broken\n' >>"$repo/.git/config"
  run_bridge "$bridge" ok "$calls" "Refuse config lookup errors."
  [[ $BRIDGE_RC == 2 && ! -e $calls ]] || fail "$name accepted a Git configuration error"
  git config --file "$repo/.git/config.new" core.repositoryformatversion 0
  mv -- "$repo/.git/config.new" "$repo/.git/config"
  for path in "$repo/.git/HEAD" "$repo/secrets/ordinary.md"; do
    run_bridge "$bridge" ok "$calls" "Review a confined path." "$path"
    [[ $BRIDGE_RC == 2 && ! -e $calls ]] || fail "$name accepted an artifact under a sensitive or Git-internal path: $path"
  done

  mkdir -p "$repo/bin" "$TMP/bin"
  for dir in "$repo/bin" "$TMP/bin"; do
    cp -- "$SHIMS/${name#spar-}" "$dir/${name#spar-}"
    cp -- "$SHIMS/shim.env" "$dir/shim.env"
    rm -f -- "$calls"
    rc=0
    PATH="$dir:$SHIMS:$PATH" /usr/bin/env -C "$repo" "$bridge" review "Review with a planted runtime." >"$calls.out" 2>"$calls.err" || rc=$?
    [[ $rc == 2 && ! -e $calls ]] || fail "$name accepted a reviewer runtime under $dir"
  done
  rm -rf -- "${repo:?}/bin" "${TMP:?}/bin"

  resume_id="22222222-2222-4222-8222-222222222222"
  run_bridge "$bridge" ok "$calls" --resume "$resume_id" "Follow up."
  [[ $BRIDGE_RC == 0 && $(<"$calls") == *"$resume_id"* ]] || fail "$name did not resume the requested session"
  run_bridge "$bridge" ok "$calls" --resume not-a-uuid "Follow up."
  [[ $BRIDGE_RC == 64 && ! -e $calls ]] || fail "$name accepted a malformed resume id"

  run_bridge "$bridge" ok "$calls" "$(printf '%s=%s' "$key_name" "$token")"
  [[ $BRIDGE_RC == 2 && ! -e $calls ]] || fail "$name sent a credential-shaped request"
  run_bridge "$bridge" ok "$calls" "Review leak." "$TMP/art/leak.md"
  [[ $BRIDGE_RC == 2 && ! -e $calls && $(<"$calls.err") != *"$token"* ]] || fail "$name sent a credential-shaped artifact"

  SPAR_TEST_REPLY="$(printf '%s=%s' "$key_name" "$token")" run_bridge "$bridge" reply "$calls" "Review reply."
  [[ $BRIDGE_RC == 2 && $(<"$calls.out") != *"$token"* && $(<"$calls.err") != *"$token"* ]] ||
    fail "$name relayed a credential-shaped reply"
  SPAR_TEST_REPLY='The .env path is denied.' run_bridge "$bridge" reply "$calls" "Review prose."
  [[ $BRIDGE_RC == 0 && $(<"$calls.out") == 'The .env path is denied.' ]] || fail "$name rejected sensitive-path prose"
  SPAR_TEST_REPLY="$token" run_bridge "$bridge" bad-version "$calls" "Review unsafe version metadata."
  [[ $BRIDGE_RC == 0 && $(<"$calls.err") != *"$token"* && $(<"$calls.err") == *'"clientversion":"unknown"'* ]] ||
    fail "$name leaked or inferred malformed version metadata"
  if [[ $name == spar-codex ]]; then
    run_bridge "$bridge" multi "$calls" "Review in parts."
    [[ $BRIDGE_RC == 0 && $(<"$calls.out") == *'part one'*'part two'* ]] || fail "$name dropped an earlier reviewer message"
  else
    SPAR_TEST_REPLY=claude-observed-fixture run_bridge "$bridge" metadata "$calls" "Review metadata."
    [[ $BRIDGE_RC == 0 && $(<"$calls.err") == *'"model":"claude-observed-fixture","effort":"unknown","tier":"standard","clientversion":"2.1.261"'* ]] ||
      fail "$name lost observed safe provenance"
    for value in $'claude-fixture\nunexpected text' $'claude-fixture\n' "$(printf 'claude-fixture\n%0200d' 0)"; do
      SPAR_TEST_REPLY="$value" run_bridge "$bridge" metadata "$calls" "Review multiline model metadata."
      [[ $BRIDGE_RC == 0 && $(<"$calls.err") == *'"model":"unknown"'* ]] || fail "$name retained a multiline model identifier"
      SPAR_TEST_REPLY="$value" run_bridge "$bridge" metadata-tier "$calls" "Review multiline tier metadata."
      [[ $BRIDGE_RC == 0 && $(<"$calls.err") == *'"tier":"unknown"'* ]] || fail "$name retained a multiline tier identifier"
    done
    SPAR_TEST_REPLY="$token" run_bridge "$bridge" metadata "$calls" "Review unsafe metadata."
    [[ $BRIDGE_RC == 0 && $(<"$calls.err") != *"$token"* && $(<"$calls.err") == *'"model":"unknown"'* ]] ||
      fail "$name leaked unsafe metadata"
    SPAR_TEST_REPLY="$token" run_bridge "$bridge" malformed-metadata "$calls" "Review malformed metadata."
    [[ $BRIDGE_RC == 0 && $(<"$calls.err") != *"$token"* && $(<"$calls.err") == *'"model":"unknown"'* ]] ||
      fail "$name leaked a metadata parser diagnostic"
  fi

  run_bridge "$bridge" limit "$calls" "Review limit."
  [[ $BRIDGE_RC == 3 && $(<"$calls.err") == *'SPAR-BRIDGE LIMIT'* ]] || fail "$name did not classify a usage limit"
  run_bridge "$bridge" error-result "$calls" "Review error."
  [[ $BRIDGE_RC == 5 && $(<"$calls.err") == *'SPAR-BRIDGE ERROR'* ]] || fail "$name did not classify an error result"
  run_bridge "$bridge" failure "$calls" "Review failure."
  [[ $BRIDGE_RC == 5 && $(<"$calls.err") == *'reviewer failed while reading .env policy'* ]] ||
    fail "$name did not relay safe reviewer diagnostics"

  child_pid_file="$TMP/child-$name"
  configure_shims hang "$calls" "" "$child_pid_file"
  start=$(date +%s)
  rc=0
  SPAR_BRIDGE_TIMEOUT=1 PATH="$SHIMS:$PATH" /usr/bin/env -C "$repo" "$bridge" review "Review timeout." \
    >"$calls.out" 2>"$calls.err" || rc=$?
  [[ $rc == 124 && $(<"$calls.err") == *'SPAR-BRIDGE TIMEOUT'* ]] || fail "$name did not classify a timeout"
  (( $(date +%s) - start <= 8 )) || fail "$name timeout was not bounded"
  expect_child_stopped "$child_pid_file" "$name timeout"

  rm -f -- "$child_pid_file" "$calls"
  configure_shims hang "$calls" "" "$child_pid_file"
  PATH="$SHIMS:$PATH" /usr/bin/env -C "$repo" "$bridge" review "Review signal." >/dev/null 2>"$calls.err" &
  bridge_pid=$!
  for _ in $(seq 1 50); do [[ -s $child_pid_file ]] && break; sleep 0.1; done
  kill -TERM "$bridge_pid"
  rc=0
  wait "$bridge_pid" || rc=$?
  [[ $rc == 130 ]] || fail "$name did not return 130 after TERM"
  expect_child_stopped "$child_pid_file" "$name TERM"
  rc=0
done

SPAR_BRIDGE_FIXTURES="$TMP" env -u HOST_CODEX_CONFIG -u CONFIG_CONTRACT_ROOT python3 -B "$ROOT/tests/config-contracts.py"
printf 'ok: spar bridges relay scanned one-pass reviews from a scrubbed environment and honor opt-out\n'
