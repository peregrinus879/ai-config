# AGENTS.md - dotfiles-ai

This repo stores portable user-level AI assistant configuration for Claude Code and OpenCode, deployed to `$HOME` via GNU Stow.

## Purpose

- Track portable user-level configuration for both tools.
- Keep shared cross-tool guidance canonical while keeping tool-specific wrappers thin.
- Keep auth and session state, machine-local files, and generated host-specific files out of Git.
- Keep human-facing explanation in `README.md`; keep project instructions here concise and actionable.

## Repo Notes

- `claude-code/` and `opencode/` are the stowed payloads that mirror files into `$HOME`.
- Repo-root files like `README.md`, `AGENTS.md`, and `CLAUDE.md` exist to maintain `dotfiles-ai` itself and are not stowed.

## Guidance

- Read `README.md` before structural changes, doc rewrites, or config-layout changes.
- Consult current official Claude Code and OpenCode docs before changing file layout, naming, or config conventions.
- Keep shared cross-tool guidance canonical in `claude-code/.claude/rules/shared-guidance.md`.
- Share policy, separate mechanism: share content only when the meaning is the same in both tools; keep tool-specific config, wrappers, schemas, and UI settings separate.
- Prefer native integration points for each tool: `.claude/rules/` and `@imports` for Claude Code, `AGENTS.md`, `instructions`, `permission`, and `tui.json` for OpenCode.
- Prefer `$HOME`-based paths for shared user-level files referenced from OpenCode config.
- Prefer plural OpenCode directory names (`agents/`, `commands/`, `skills/`, `tools/`, `themes/`, `plugins/`, `modes/`); singular names are backward-compatibility fallbacks.
- Keep tracked runtime config limited to shared, portable behavior.
- Keep the repo-root `.gitignore` aligned with the documented excluded local state.
- Keep wrappers thin. If detailed rationale is needed, put it in `README.md`, not here.
- After instruction or config changes, verify them in a fresh Claude Code session and a fresh OpenCode session when practical.
- For patch review in either tool, use `!git status --short`, `!git diff --stat`, `!git diff`, and `!git diff -- path/to/file`.
- If OpenCode docs disagree with the installed stable binary, prefer installed `/help` output and actual runtime behavior.
