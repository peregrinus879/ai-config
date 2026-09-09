#!/usr/bin/env bash
# Explicit copy only, using fake clipboard backends even on a desktop host.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
CLIP="$ROOT/agents/.agents/skills/publish/scripts/publish-clip"
umask 077
TMP=$(mktemp -d)
SHIMS="$TMP/bin"
EMPTY="$TMP/no-clipboard"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$SHIMS" "$EMPTY" "$TMP/home"
for directory in "$SHIMS" "$EMPTY"; do
  for tool in bash cat timeout; do
    ln -s "$(command -v "$tool")" "$directory/$tool"
  done
done

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

for tool in wl-copy clip.exe; do
  printf '#!/usr/bin/env bash\ncat >"%s/%s.received"\n' "$TMP" "$tool" >"$SHIMS/$tool"
  chmod +x "$SHIMS/$tool"
done
command='git -C ~/Projects/example push origin abc:refs/heads/main --force-with-lease=refs/heads/main:def'

out=$(printf '%s' "$command" | env -i HOME="$TMP/home" HISTFILE=/dev/null PATH="$SHIMS" WAYLAND_DISPLAY=wayland-1 bash "$CLIP")
[[ $out == 'clipboard: unchanged (copy not requested)' && ! -e $TMP/wl-copy.received && ! -e $TMP/clip.exe.received ]] ||
  fail 'default invocation changed the clipboard'
for arguments in '--invalid' '--copy --copy'; do
  # shellcheck disable=SC2086 # Deliberate invalid argument vectors.
  if printf '%s' "$command" | env -i HOME="$TMP/home" HISTFILE=/dev/null PATH="$SHIMS" WAYLAND_DISPLAY=wayland-1 bash "$CLIP" $arguments >/dev/null 2>&1; then
    fail 'invalid copy flags were accepted'
  fi
  [[ ! -e $TMP/wl-copy.received && ! -e $TMP/clip.exe.received ]] || fail 'invalid flags reached a clipboard backend'
done

out=$(printf '%s' "$command" | env -i HOME="$TMP/home" HISTFILE=/dev/null PATH="$SHIMS" WAYLAND_DISPLAY=wayland-1 bash "$CLIP" --copy)
[[ $out == 'clipboard: wl-copy' && $(<"$TMP/wl-copy.received") == "$command" ]] || fail "wl-copy did not take the command under Wayland: $out"

rm -f -- "$TMP"/*.received
out=$(printf '%s' "$command" | env -i HOME="$TMP/home" HISTFILE=/dev/null PATH="$SHIMS" bash "$CLIP" --copy)
[[ $out == 'clipboard: clip.exe' && $(<"$TMP/clip.exe.received") == "$command" && ! -e $TMP/wl-copy.received ]] ||
  fail "clip.exe was not chosen without a Wayland session: $out"

out=$(printf '%s' "$command" | env -i HOME="$TMP/home" HISTFILE=/dev/null PATH="$EMPTY" WAYLAND_DISPLAY=wayland-1 DISPLAY=:99 bash "$CLIP" --copy)
[[ $out == 'clipboard: none' ]] || fail "a missing tool was not reported as none: $out"

rm -f -- "$TMP"/*.received
out=$(printf '' | env -i HOME="$TMP/home" HISTFILE=/dev/null PATH="$SHIMS" WAYLAND_DISPLAY=wayland-1 bash "$CLIP" --copy)
[[ $out == 'clipboard: none (empty input)' && ! -e $TMP/wl-copy.received ]] || fail "empty input reached a clipboard tool: $out"

printf 'ok: publish-clip defaults to no copy; explicit copying uses only the selected fake backend\n'
