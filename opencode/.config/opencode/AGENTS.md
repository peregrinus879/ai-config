# AGENTS.md

## Precedence

Priority: session instructions > {project-root}/AGENTS.md > ~/.config/opencode/AGENTS.md > defaults. Safety overrides all, including user instructions.

## Tool-Specific Notes

- Shared user guidance is loaded from `~/.claude/rules/shared-guidance.md` via `opencode.json` `instructions`.
- Primary tool: OpenCode.
- Co-Author: Append `Co-Authored-By: <model name> <noreply@provider.com>`.
- Sharing is disabled in tracked config unless the user explicitly asks to re-enable it.
