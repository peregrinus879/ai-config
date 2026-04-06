# AGENTS.md - dotfiles-ai

This repo stores portable user-level AI assistant configuration for Claude Code and OpenCode, deployed to `$HOME` via GNU Stow.

## Scope

This repo carries shared cross-tool guidance and portable tracked config for Claude Code and OpenCode.

It owns:

- stowed `claude-code/` and `opencode/` payloads that mirror files into `$HOME`
- the shared guidance file and commit workflow docs used by both tools
- portable runtime config that should follow the user across machines

It does not own:

- auth and session state
- machine-local files, generated host-specific config, or local project memories

## Environment

- Tools: Claude Code, OpenCode
- Deployment: GNU Stow to `$HOME`
- Context: terminal-first user-level configuration

## Key Files

- `README.md` - structure, setup, and verification
- `CLAUDE.md` - thin Claude Code wrapper importing `AGENTS.md`
- `claude-code/.claude/rules/shared-guidance.md` - canonical shared cross-tool guidance file
- `claude-code/.claude/settings.json` - Claude Code runtime settings
- `opencode/.config/opencode/opencode.json` - OpenCode runtime config and instruction loading
- `opencode/.config/opencode/commands/commit.md` - OpenCode wrapper for the commit workflow

## Setup Invariants

- `claude-code/` and `opencode/` are the stowed payloads; repo-root docs are not stowed
- shared cross-tool guidance lives in `claude-code/.claude/rules/shared-guidance.md`
- OpenCode should reference shared user-level instruction files with `$HOME`-based paths
- tracked runtime config stays portable; auth, session state, machine-local files, and generated host-specific files stay out of Git
- keep the repo-root `.gitignore` aligned with the documented excluded local state

## Reference Sources

- Claude Code official docs for overview, settings, memory, skills, and hooks
- OpenCode official docs for rules, config, permissions, agents, skills, and TUI behavior
- installed OpenCode `/help` output and actual runtime behavior when the stable binary and docs disagree

## Skills

- `/commit` - commit workflow with documentation sync before staging when docs are affected

## Workflow

- Read `README.md` before structural changes, doc rewrites, or config-layout changes.
- Consult current official Claude Code and OpenCode docs before changing file layout, naming, or config conventions.
- Keep shared cross-tool guidance canonical in `claude-code/.claude/rules/shared-guidance.md`.
- Share policy, separate mechanism: share content only when the meaning is the same in both tools; keep tool-specific config, wrappers, schemas, and UI settings separate.
- Prefer native integration points for each tool: `.claude/rules/` and `@imports` for Claude Code, `AGENTS.md`, `instructions`, `permission`, and `tui.json` for OpenCode.
- Prefer plural OpenCode directory names (`agents/`, `commands/`, `skills/`, `tools/`, `themes/`, `plugins/`, `modes/`); singular names are backward-compatibility fallbacks.
- Keep wrappers thin. If detailed rationale is needed, put it in `README.md`, not here.
- After instruction or config changes, verify them in a fresh Claude Code session and a fresh OpenCode session when practical.
- For patch review in either tool, use `!git status --short`, `!git diff --stat`, `!git diff`, and `!git diff -- path/to/file`.

## Maintainer Checklist

1. Review the current Claude Code docs for overview, settings, memory, skills, and hooks.
2. Review the current OpenCode docs for config, rules, permissions, agents, skills, TUI, and sharing.
3. Run `opencode debug config` and confirm the resolved config still matches the tracked intent.
4. Start a fresh session in both tools and verify the shared guidance file is loaded.
5. Verify Claude Code status line behavior still matches `claude-code/.claude/settings.json` and `statusline.sh`.
6. Verify OpenCode diff review remains usable over SSH and that sharing stays disabled unless intentionally changed.
7. Verify `/commit` still performs documentation sync before staging when docs are affected.
