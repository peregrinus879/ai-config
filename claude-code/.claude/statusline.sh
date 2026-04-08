#!/usr/bin/env bash
# Claude Code status line
# Docs: https://code.claude.com/docs/en/statusline

input=$(cat)

# --- Parse JSON input (single jq call for performance) ---
readarray -t _f <<< "$(echo "$input" | jq -r '
  (.workspace.current_dir // .cwd // ""),
  (.model.display_name // ""),
  (.context_window.used_percentage // ""),
  (.context_window.context_window_size // 0),
  (.rate_limits.five_hour.used_percentage // ""),
  (.rate_limits.seven_day.used_percentage // ""),
  (.cost.total_cost_usd // ""),
  (.rate_limits.five_hour.resets_at // ""),
  (.rate_limits.seven_day.resets_at // ""),
  (.session_id // "")
')"
for i in "${!_f[@]}"; do _f[$i]="${_f[$i]%$'\r'}"; done
cwd="${_f[0]}" model="${_f[1]}" used_pct="${_f[2]}" ctx_size="${_f[3]}"
rate_5h="${_f[4]}" rate_7d="${_f[5]}" cost_usd="${_f[6]}"
reset_5h="${_f[7]}" reset_7d="${_f[8]}" session_id="${_f[9]}"

# effortLevel is not in the statusline JSON schema;
# read directly from settings.json as a workaround.
effort=$(jq -r '.effortLevel // empty' ~/.claude/settings.json 2>/dev/null)

# --- ANSI colors ---
dim='\033[2m'
bold_cyan='\033[1;36m'
italic_cyan='\033[3;36m'
yellow='\033[33m'
bold_yellow='\033[1;33m'
green='\033[32m'
red='\033[31m'
reset='\033[0m'

# --- Helpers ---

# Color by percentage threshold
pct_color() {
  local pct=${1:-0}
  if [ "$pct" -ge 90 ] 2>/dev/null; then echo "$red"
  elif [ "$pct" -ge 70 ] 2>/dev/null; then echo "$yellow"
  else echo "$green"
  fi
}

# Format tokens: 200000 -> 200k
fmt_k() {
  local n=${1:-0}
  if [ -z "$n" ] || [ "$n" = "null" ] || [ "$n" -eq 0 ] 2>/dev/null; then echo ""; return; fi
  echo "$((n / 1000))k"
}

# Format seconds remaining to countdown: Xh Ym or Xm
fmt_countdown() {
  local remaining=${1:-0}
  if [ "$remaining" -le 0 ] 2>/dev/null; then echo ""; return; fi
  local h=$((remaining / 3600))
  local m=$(( (remaining % 3600) / 60 ))
  if [ "$h" -gt 0 ] 2>/dev/null; then
    echo "${h}h ${m}m"
  else
    echo "${m}m"
  fi
}

# Append a rate-limit segment to rate_seg
# Args: label pct reset_epoch date_fmt
build_rate_seg() {
  local label=$1 pct=$2 epoch=$3 dfmt=$4
  local color value rtime_part=""

  [ -z "$pct" ] || [ "$pct" = "null" ] && return
  pct=$(printf '%.0f' "$pct")
  color=$(pct_color "$pct")

  if [ "$pct" -ge 100 ] 2>/dev/null && [ "${epoch:-0}" -gt 0 ] 2>/dev/null; then
    local countdown
    countdown=$(fmt_countdown "$((epoch - now))")
    value="${countdown:-${pct}%}"
  else
    value="${pct}%"
  fi

  if [ "${epoch:-0}" -gt "$now" ] 2>/dev/null; then
    local rtime
    rtime=$(date -d "@$epoch" +"$dfmt" 2>/dev/null)
    [ -n "$rtime" ] && rtime_part=" ${dim}@${rtime}${reset}"
  fi

  rate_seg+="  ${dim}${label}:${reset}${color}${value}${reset}${rtime_part}"
}

# --- Detect extra usage (5h OR 7d at 100%) ---
extra_usage=0
if [ -n "$rate_5h" ] && [ "$rate_5h" != "null" ]; then
  [ "$(printf '%.0f' "$rate_5h")" -ge 100 ] 2>/dev/null && extra_usage=1
fi
if [ "$extra_usage" -eq 0 ] && [ -n "$rate_7d" ] && [ "$rate_7d" != "null" ]; then
  [ "$(printf '%.0f' "$rate_7d")" -ge 100 ] 2>/dev/null && extra_usage=1
fi

# --- Git cache (docs: cache expensive operations) ---
git_cache="/tmp/statusline-git-cache-${cwd//\//_}"
git_cache_max_age=5

git_cache_stale() {
  [ ! -f "$git_cache" ] || \
  [ $(($(date +%s) - $(stat -c %Y "$git_cache" 2>/dev/null || echo 0))) -gt $git_cache_max_age ]
}

# --- Segments ---

# 1. SSH hostname (shown only for remote sessions)
host_seg=""
if [ -n "$SSH_CONNECTION" ]; then
  host_seg="${bold_yellow}${HOSTNAME%%.*}${reset}  "
fi

# 2. Directory + Git branch (cached, refreshed every 5s)
branch=""
repo_root=""
if [ -n "$cwd" ] && [ -d "$cwd" ]; then
  if git_cache_stale; then
    branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null \
             || GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --short HEAD 2>/dev/null)
    repo_root=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
    printf '%s\n%s\n' "$branch" "$repo_root" > "$git_cache"
  else
    { read -r branch; read -r repo_root; } < "$git_cache"
  fi
fi

# Directory: repo root + relative path inside git repos, last 2 components outside
if [ -n "$repo_root" ]; then
  repo_name="${repo_root##*/}"
  rel_path="${cwd#"$repo_root"}"
  rel_path="${rel_path#/}"
  if [ -n "$rel_path" ]; then
    short_cwd="${repo_name}/${rel_path}"
  else
    short_cwd="$repo_name"
  fi
else
  short_cwd="${cwd/#$HOME/\~}"
  IFS='/' read -ra parts <<< "$short_cwd"
  n=${#parts[@]}
  if [ "$n" -gt 2 ]; then
    short_cwd="…/${parts[$((n-2))]}/${parts[$((n-1))]}"
  fi
fi

# 3. Model (strip "Claude " prefix if present)
short_model="${model#Claude }"

# 4. Effort
effort_seg=""
[ -n "$effort" ] && [ "$effort" != "null" ] && effort_seg="  ${dim}${effort}${reset}"

# 5. Context window: used (pct%)
# used_percentage and ctx_size can be null early in session before first API call.
ctx_seg=""
if [ -n "$used_pct" ] && [ "$used_pct" != "null" ] && [ "$ctx_size" -gt 0 ] 2>/dev/null; then
  used_int=$(printf '%.0f' "$used_pct")
  used_raw=$((ctx_size * used_int / 100))
  ctx_seg="  $(pct_color "$used_int")$(fmt_k "$used_raw") (${used_int}%)${reset}"
fi

# 6. Rate limits: 5h and 7d (with reset countdown and local reset time)
now=$(date +%s)
rate_seg=""
build_rate_seg "5h" "$rate_5h" "$reset_5h" "%H:%M"
build_rate_seg "7d" "$rate_7d" "$reset_7d" "%a.%H:%M"

# 7. Session cost (tracks only extra usage spend)
# State: line 1 = active|frozen, line 2 = baseline, line 3 = prior extra, line 4 = last displayed
extra_state="/tmp/statusline-extra-${session_id:-unknown}"
cost_seg=""
if [ "$extra_usage" -eq 1 ] 2>/dev/null; then
  if [ -f "$extra_state" ]; then
    { read -r _st; read -r _bl; read -r _pr; read -r _ld; } < "$extra_state"
    if [ "$_st" = "frozen" ]; then
      # Re-entering extra usage: carry over frozen value, set new baseline
      _pr="${_ld:-0}"
      _bl="${cost_usd:-0}"
    fi
  else
    _bl="${cost_usd:-0}" _pr="0" _ld="0"
  fi
  if [ -n "$cost_usd" ] && [ "$cost_usd" != "null" ]; then
    extra_cost=$(jq -n --argjson c "$cost_usd" --argjson b "${_bl:-0}" --argjson p "${_pr:-0}" '$p + $c - $b' 2>/dev/null) || extra_cost=0
    printf '%s\n' "active" "$_bl" "$_pr" "$extra_cost" > "$extra_state"
    cost_seg="  ${yellow}$(printf '$%.2f' "$extra_cost")${reset}"
  fi
else
  if [ -f "$extra_state" ]; then
    { read -r _st; read -r _bl; read -r _pr; read -r _ld; } < "$extra_state"
    if [ "$_st" = "active" ]; then
      # Transition to frozen: use last displayed value, not recomputed
      printf '%s\n' "frozen" "0" "0" "${_ld:-0}" > "$extra_state"
    fi
    cost_seg="  ${dim}$(printf '$%.2f' "${_ld:-0}")${reset}"
  else
    cost_seg="  ${dim}\$0.00${reset}"
  fi
fi

# --- Output ---
printf "%b\n" "${host_seg}${bold_cyan}${short_cwd}${reset}${branch:+  ${italic_cyan}${branch}${reset}}  ${dim}${short_model}${reset}${effort_seg}${ctx_seg}${rate_seg}${cost_seg}"
