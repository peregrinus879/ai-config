#!/usr/bin/env bash
# Claude Code status line
# Docs: https://code.claude.com/docs/en/statusline

input=$(cat)

# --- Parse JSON input ---
cwd=$(echo "$input" | jq -r '.cwd // ""')
model=$(echo "$input" | jq -r '.model.display_name // ""')
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
ctx_size=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
rate_5h=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
rate_7d=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')

# effortLevel is not in the statusline JSON schema;
# read directly from settings.json as a workaround.
effort=$(jq -r '.effortLevel // empty' ~/.claude/settings.json 2>/dev/null)

# --- ANSI colors ---
dim='\033[2m'
cyan='\033[36m'
yellow='\033[33m'
green='\033[32m'
red='\033[31m'
magenta='\033[35m'
reset='\033[0m'

# --- Helpers ---

# Color by percentage threshold
pct_color() {
  local pct=${1:-0}
  if [ "$pct" -ge 80 ] 2>/dev/null; then echo "$red"
  elif [ "$pct" -ge 50 ] 2>/dev/null; then echo "$yellow"
  else echo "$green"
  fi
}

# Format tokens: 200000 -> 200k
fmt_k() {
  local n=${1:-0}
  if [ -z "$n" ] || [ "$n" = "null" ] || [ "$n" -eq 0 ] 2>/dev/null; then echo ""; return; fi
  echo "$((n / 1000))k"
}

# --- Segments ---

# 1. Directory (shorten $HOME to ~)
short_cwd="${cwd/#$HOME/\~}"

# 2. Git branch (GIT_OPTIONAL_LOCKS avoids lock contention)
branch=""
if [ -n "$cwd" ] && [ -d "$cwd" ]; then
  branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null \
           || GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --short HEAD 2>/dev/null)
fi

# 3. Model (strip "Claude " prefix if present)
short_model="${model#Claude }"

# 4. Effort
effort_seg=""
[ -n "$effort" ] && [ "$effort" != "null" ] && effort_seg="  ${dim}${effort}${reset}"

# 5. Context window: used/total (pct%)
# used_percentage and ctx_size can be null early in session before first API call.
ctx_seg=""
if [ -n "$used_pct" ] && [ "$used_pct" != "null" ] && [ "$ctx_size" -gt 0 ] 2>/dev/null; then
  used_int=$(printf '%.0f' "$used_pct")
  used_raw=$((ctx_size * used_int / 100))
  ctx_seg="  $(pct_color "$used_int")$(fmt_k "$used_raw")/$(fmt_k "$ctx_size") (${used_int}%)${reset}"
fi

# 6. Rate limits: 5h and 7d
# rate_limits can be absent early in session.
rate_seg=""
if [ -n "$rate_5h" ] && [ "$rate_5h" != "null" ]; then
  r5=$(printf '%.0f' "$rate_5h")
  rate_seg="  ${dim}5h:${reset}$(pct_color "$r5")${r5}%${reset}"
fi
if [ -n "$rate_7d" ] && [ "$rate_7d" != "null" ]; then
  r7=$(printf '%.0f' "$rate_7d")
  rate_seg+="  ${dim}7d:${reset}$(pct_color "$r7")${r7}%${reset}"
fi

# --- Output ---
printf "%b\n" "${cyan}${short_cwd}${reset}${branch:+  ${magenta}${branch}${reset}}  ${dim}${short_model}${reset}${effort_seg}${ctx_seg}${rate_seg}"
