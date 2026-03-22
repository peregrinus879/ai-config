# CLAUDE.md - dotfiles-ai

This repo stores global/user-level configuration files for AI coding assistants (Claude Code and OpenCode), deployed to `$HOME` via GNU Stow.

## Repo Layout

Two stow packages mirror their respective `$HOME` targets:

- `claude-code/` -> `~/.claude/`
- `opencode/` -> `~/.config/opencode/`

Stow commands:

```bash
cd ~/path/to/dotfiles-ai
stow -v -t ~ claude-code opencode     # install
stow -D -v -t ~ claude-code opencode  # uninstall
stow -v -n -t ~ claude-code opencode  # dry run
```

## Claude Code Reference

Official docs: https://code.claude.com/docs/en/overview

### Global config structure (`~/.claude/`)

| Path | Purpose |
|------|---------|
| `CLAUDE.md` | User-level persistent instructions (loaded every session) |
| `settings.json` | User-level settings (permissions, env, features) |
| `agents/` | User-level custom agents |
| `rules/` | User-level organized instruction files (loaded before project rules) |
| `skills/` | User-level custom skills (SKILL.md files, on-demand workflows) |

Best practices:
- Keep `CLAUDE.md` under 200 lines for context window efficiency
- Use `rules/` for topic-specific files (e.g., `testing.md`, `api-design.md`)
- Rules support `paths:` frontmatter for file-scoped instructions
- Use `@path/to/file` syntax in CLAUDE.md to import additional files

## OpenCode Reference

Official docs: https://opencode.ai/docs

### Global config structure (`~/.config/opencode/`)

| Path | Purpose |
|------|---------|
| `AGENTS.md` | User-level global instructions |
| `opencode.json` | User-level config (models, providers, permissions, tools) |
| `tui.json` | TUI-specific settings |
| `agents/` | Custom agent definitions (markdown with frontmatter) |
| `commands/` | Custom command definitions |
| `tools/` | Custom tool definitions |
| `themes/` | Custom themes |
| `modes/` | Mode configurations |
| `plugins/` | Plugin files |
| `skills/` | Agent skills |

Notes:
- OpenCode falls back to `CLAUDE.md` if `AGENTS.md` is absent
- Plural directory names are canonical; singular also supported for backward compatibility
- Agent files use markdown with YAML frontmatter for config (model, tools, permissions)

## Editing Guidelines

- Consult official docs above before structural changes
- Keep instruction files concise; split with `rules/` when growing large
- Keep both tools' instruction files in sync where intent overlaps
- Test changes by starting a new session in the respective tool
