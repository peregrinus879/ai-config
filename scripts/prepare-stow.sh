#!/usr/bin/env bash
# Prepare $HOME for `stow --no-folding`, and reconcile the Codex config on request.
#
# Without arguments: remove dangling symlinks under the managed target
# directories whose link text names a path inside one of this repository's
# packages, recognized by the package name followed by a top-level entry that
# package really has or once had (RETIRED_ENTRIES), so retired files and moved
# or renamed clones are cleaned and unrelated links with a similar spelling are
# not. The match is not bound to this clone's path, so a dangling link into
# another clone with the same package layout is removed too; only dangling
# links are ever removed, and afterwards the retired managed directories those
# links leave empty are pruned. Links that resolve, links that point elsewhere,
# and regular files are never touched; Stow itself reports any remaining
# conflict without changing the filesystem.
#
# --migrate-codex-config: make ~/.codex/config.toml a host-local, owner-only
# regular file that carries the portable template's root keys and tables and
# preserves every host-only table Codex or the desktop app wrote (projects,
# marketplaces, plugins, mcp_servers, shell_environment_policy, desktop). A
# missing file or a managed symlink is replaced by the template; a regular file
# that already matches the template is left untouched.
#
# --link-skills: make each ~/.agents/skills/<name> one link to the skill's
# directory in the agents package, the shape Codex's skill loader follows
# (it skips symlinks that are not directories, so the leaf links a no-folding
# deploy would leave hide the skill). A directory left by an earlier deploy is
# emptied of links into that skill's source (including recognized retired
# package links) and removed. All selected skills are preflighted before any
# mutation; foreign files and links, including dangling links, stop the script
# unchanged. --check-skills runs that preflight without making changes.
# --unlink-skills removes the links that resolve into this clone's package.
# --require-clone checks all managed endpoints and parents without writing.
# --install-gate installs only at the fixed host endpoint, with real parents
# outside Git workspaces and no endpoint symlink/hardlink. GATE cannot relocate it.
# --check-gate applies the same endpoint checks and verifies executable content,
# without installing or creating directories.
set -euo pipefail

abort() {
  printf 'prepare-stow: %s\n' "$1" >&2
  exit 1
}

script_dir=$(dirname -- "${BASH_SOURCE[0]}")
repository_root=$(realpath -e -- "$script_dir/..") || abort 'cannot resolve repository root'
[[ -n ${HOME:-} && -d $HOME ]] || abort 'HOME must name an existing non-root directory'
HOME=$(realpath -e -- "$HOME") || abort 'cannot resolve HOME'
[[ $HOME != / ]] || abort 'HOME must name an existing non-root directory'
PACKAGES=(agents claude-code codex opencode hermes)
TARGET_ROOTS=("$HOME/.claude" "$HOME/.codex" "$HOME/.agents" "$HOME/.local/bin" "$HOME/.config/opencode" "$HOME/.hermes/plugins")
# Package entries that once existed: links into them are still ours to clean.
RETIRED_ENTRIES=(agents/.local codex/.agents claude-code/.claude/rules opencode/.config/opencode/skills)

managed_link_text() { # link text
  local text=$1 package tail entry
  for package in "${PACKAGES[@]}"; do
    [[ $text == *"/$package/"* ]] || continue
    tail=${text#*"/$package/"}
    [[ -n $tail && -e "$repository_root/$package/${tail%%/*}" ]] && return 0
    for entry in "${RETIRED_ENTRIES[@]}"; do
      [[ "$package/$tail" == "$entry" || "$package/$tail" == "$entry"/* ]] && return 0
    done
  done
  return 1
}

require_clone() {
  local src path resolved scan
  local -a sources=()
  [[ -n ${HOME:-} && $HOME != / && -d $HOME ]] || abort 'HOME must name an existing non-root directory'
  mapfile -d '' -t sources < <(git -C "$repository_root" ls-files -z --cached --others --exclude-standard -- "${PACKAGES[@]}")
  scan=$!; wait "$scan" || abort 'cannot enumerate package files'
  ((${#sources[@]})) || abort 'no Git-visible package files found'
  # The installed gate has no Stow source, but its parents are also writable.
  sources+=(agents/.agents/hooks/commit-gate)
  for src in "${sources[@]}"; do
    path="$HOME/${src#*/}"
    while [[ $path != "$HOME" ]]; do
      if [[ -L $path ]]; then
        resolved=$(realpath -m -- "$path") || abort "cannot resolve $path"
        if [[ $resolved != "$repository_root"/* ]]; then
          if [[ -e $path ]] || ! managed_link_text "$(readlink -- "$path")"; then
            abort "$path is linked from another clone or an unmanaged location; run from the deployed clone"
          fi
        fi
      fi
      path=${path%/*}
    done
  done
}

manage_gate() { # install|check
  local gate=${GATE-"$HOME/.agents/hooks/commit-gate"} parent
  [[ $gate == "$HOME/.agents/hooks/commit-gate" ]] || abort 'GATE must name the fixed canonical HOME/.agents/hooks/commit-gate endpoint'
  [[ $gate != "$repository_root"/* ]] || abort 'the installed gate must remain outside the repository'
  parent=${gate%/*}
  while [[ -n $parent && $parent != / ]]; do
    [[ ! -L $parent && ( ! -e $parent || -d $parent ) ]] || abort "gate parent must be a real directory, not a fold or file: $parent"
    if [[ -f $parent/.git || -L $parent/.git || -e $parent/.git/HEAD ]]; then
      abort "the installed gate must remain outside Git workspaces: $parent"
    fi
    parent=${parent%/*}
  done
  for parent in "$HOME/.agents" "$HOME/.agents/hooks"; do
    [[ ! -e $parent || -O $parent ]] || abort "gate parent must be owned by you: $parent"
  done
  [[ ! -L $gate ]] || abort "gate endpoint must not be a symlink: $gate"
  if [[ -e $gate ]]; then
    [[ -f $gate && -O $gate && $(stat -c '%h' -- "$gate") == 1 ]] || abort 'gate endpoint must be an owner-controlled, single-link regular file'
  fi
  [[ $(realpath -m -- "$gate") == "$gate" ]] || abort 'gate endpoint must resolve to its canonical host path'
  if [[ $1 == check ]]; then
    if [[ ! -f $gate || ! -x $gate ]] || ! cmp -s "$repository_root/templates/hooks/commit-gate" "$gate"; then
      abort 'installed commit gate is missing, not executable, unreadable, or drifted (run make restow)'
    fi
    printf 'ok:   installed commit gate matches templates/hooks/commit-gate\n'
    return
  fi
  mkdir -p -- "$HOME/.agents/hooks"
  [[ -d $HOME/.agents && ! -L $HOME/.agents && -d $HOME/.agents/hooks && ! -L $HOME/.agents/hooks &&
    ! -L $gate && $(realpath -m -- "$gate") == "$gate" ]] || abort 'gate destination changed before installation'
  install -T -m 755 -- "$repository_root/templates/hooks/commit-gate" "$gate"
  printf 'ok:   commit gate installed at %s\n' "$gate"
}

clean_links() {
  local root path text dir
  [[ -n ${HOME:-} && $HOME != / ]] || abort 'HOME must name a non-root directory'
  for root in "${TARGET_ROOTS[@]}"; do
    [[ -d $root && ! -L $root ]] || continue
    while IFS= read -r -d '' path; do
      text=$(readlink -- "$path") || continue
      managed_link_text "$text" || continue
      rm -- "$path"
      printf 'removed dangling managed link: %s\n' "$path"
    done < <(find "$root" -xtype l -print0 2>/dev/null)
  done
  # Managed directories the retired links leave behind, pruned only when empty, deepest first.
  local -a retired=("$HOME"/.config/opencode/skills/*/ "$HOME/.config/opencode/skills" "$HOME/.claude/rules")
  for dir in "${retired[@]}"; do
    dir=${dir%/}
    [[ -d $dir && ! -L $dir ]] || continue
    rmdir -- "$dir" 2>/dev/null || continue
    printf 'removed empty retired directory: %s\n' "$dir"
  done
}

migrate_codex_config() {
  local codex_root="$HOME/.codex" config template reconcile temp
  local -a host=()
  template="$repository_root/templates/codex/config.toml"
  reconcile="$repository_root/scripts/reconcile-codex-config.py"
  config="$codex_root/config.toml"
  [[ -f $template && ! -L $template ]] || abort "Codex portable template is missing: $template"
  [[ -f $reconcile ]] || abort "Codex reconciliation script is missing: $reconcile"
  command -v python3 >/dev/null || abort 'python3 is required for Codex config reconciliation'
  [[ -d $codex_root && ! -L $codex_root && -O $codex_root ]] ||
    abort "Codex runtime root must be a real directory owned by you: $codex_root"

  if [[ -L $config ]]; then
    managed_link_text "$(readlink -- "$config")" ||
      abort "refusing to replace an unmanaged Codex config symlink: $config"
  elif [[ -e $config ]]; then
    [[ -f $config && -O $config ]] || abort "host-local Codex config must be a regular file owned by you: $config"
    if python3 "$reconcile" check "$template" "$config" && [[ $(stat -c '%a' -- "$config") =~ ^[46]00$ ]]; then
      printf 'prepare-stow: host-local Codex config already matches the template\n'
      return
    fi
    host=("$config")
  fi

  umask 077
  temp=$(mktemp -- "$codex_root/.config.toml.XXXXXX") || abort 'cannot create reconciliation temporary file'
  trap 'rm -f -- "$temp"' EXIT
  python3 "$reconcile" merge "$template" "${host[@]}" >"$temp" || abort 'cannot reconcile the Codex config'
  sync -f -- "$temp" || abort 'cannot flush the reconciled Codex config'
  mv -T -- "$temp" "$config" || abort "cannot install the reconciled Codex config: $config"
  trap - EXIT
  if ((${#host[@]})); then
    printf 'prepare-stow: reconciled host-local Codex config with the template, host tables preserved\n'
  else
    printf 'prepare-stow: installed host-local Codex config from the template\n'
  fi
}

package_skills() {
  local dir
  for dir in "$repository_root"/agents/.agents/skills/*/; do
    [[ -d $dir ]] || continue
    basename -- "$dir"
  done
}

check_skills() {
  local root="$HOME/.agents/skills" name source target entry resolved scan
  local -a entries=()
  [[ -n ${HOME:-} && $HOME != / ]] || abort 'HOME must name a non-root directory'
  [[ ! -L $HOME/.agents ]] || abort "the agents root must be a real directory, not a link: $HOME/.agents"
  [[ ! -L $root ]] || abort "the skills root must be a real directory, not a link: $root"
  [[ ! -e $root || -d $root ]] || abort "the skills root is not a directory: $root"
  while IFS= read -r name; do
    source="$repository_root/agents/.agents/skills/$name"
    target="$root/$name"
    if [[ -L $target ]]; then
      resolved=$(realpath -m -- "$target") || abort "cannot resolve $target"
      [[ $resolved == "$source" ]] && continue
      if [[ ! -e $target && ( $resolved == */agents/.agents/skills/"$name" ||
        $resolved == */codex/.agents/skills/"$name" ) ]]; then continue; fi
      abort "refusing to repoint a foreign skill link: $target"
    elif [[ -d $target ]]; then
      mapfile -d '' -t entries < <(find "$target" -mindepth 1 -print0)
      scan=$!; wait "$scan" || abort "cannot inspect the skill directory: $target"
      for entry in "${entries[@]}"; do
        if [[ -L $entry ]]; then
          resolved=$(realpath -m -- "$entry") || abort "cannot resolve $entry"
          [[ $resolved == "$source"/* ]] && continue
          # Earlier deployments used codex/.agents; recognize only a dangling
          # link naming this selected skill, not arbitrary missing targets.
          if [[ ! -e $entry && ( $resolved == */codex/.agents/skills/"$name"/* ||
            $resolved == */agents/.agents/skills/"$name"/* ) ]]; then continue; fi
          abort "foreign link inside a managed skill directory: $entry"
        elif [[ -d $entry ]]; then
          continue
        fi
        abort "foreign entry inside a managed skill directory: $entry"
      done
    elif [[ -e $target ]]; then
      abort "skill endpoint is neither a link nor a directory: $target"
    fi
  done < <(package_skills)
}

link_skills() {
  local root="$HOME/.agents/skills" name source target text entry
  check_skills
  mkdir -p -- "$root"
  while IFS= read -r name; do
    source="$repository_root/agents/.agents/skills/$name"
    target="$root/$name"
    if [[ -L $target ]]; then
      [[ $(realpath -m -- "$target") == "$source" ]] && continue
      rm -- "$target"
    fi
    text=$(realpath --relative-to="$root" -- "$source")
    if [[ -d $target ]]; then
      while IFS= read -r -d '' entry; do
        rm -- "$entry"
      done < <(find "$target" -type l -print0)
      find "$target" -depth -type d -exec rmdir -- {} + || abort "cannot remove empty skill directories: $target"
    fi
    ln -s -- "$text" "$target"
    printf 'linked skill directory: %s -> %s\n' "$target" "$text"
  done < <(package_skills)
}

unlink_skills() {
  local root="$HOME/.agents/skills" name target
  while IFS= read -r name; do
    target="$root/$name"
    [[ -L $target ]] || continue
    [[ $(realpath -m -- "$target") == "$repository_root/agents/.agents/skills/$name" ]] || continue
    rm -- "$target"
    printf 'removed skill directory link: %s\n' "$target"
  done < <(package_skills)
}

[[ $# -le 1 ]] || abort "unsupported arguments: $*"
case ${1:-} in
  ''|--require-clone|--check-skills|--install-gate|--check-gate|--migrate-codex-config|--migrate-hermes-config|--link-skills|--unlink-skills) ;;
  *) abort "unsupported arguments: $*" ;;
esac
require_clone
case ${1:-} in
  '') check_skills; clean_links ;;
  --require-clone) ;;
  --check-skills) check_skills ;;
  --install-gate) manage_gate install ;;
  --check-gate) manage_gate check ;;
  --migrate-hermes-config)
    python3 "$repository_root/scripts/reconcile-hermes-config.py" install "$repository_root" ;;
  --migrate-codex-config)
    [[ $# == 1 ]] || abort "unsupported arguments: $*"
    migrate_codex_config ;;
  --link-skills)
    [[ $# == 1 ]] || abort "unsupported arguments: $*"
    link_skills ;;
  --unlink-skills)
    [[ $# == 1 ]] || abort "unsupported arguments: $*"
    check_skills
    unlink_skills ;;
  *) abort "unsupported arguments: $*" ;;
esac
