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
| `settings.json` | User-level runtime settings (status line, permissions, env, features) |
| `statusline.sh` | Terminal status line script ([docs](https://code.claude.com/docs/en/statusline)) |
| `agents/` | User-level custom agents |
| `rules/` | User-level organized instruction files (loaded before project rules) |
| `skills/` | User-level custom skills (SKILL.md files, on-demand workflows) |

Best practices:
- Keep `CLAUDE.md` under 200 lines for context window efficiency
- Use `rules/` for topic-specific files (e.g., `testing.md`, `api-design.md`) and shared cross-tool guidance
- Rules support `paths:` frontmatter for file-scoped instructions
- Use `@path/to/file` syntax in CLAUDE.md to import additional files

## OpenCode Reference

Official docs: https://opencode.ai/docs

### Global config structure (`~/.config/opencode/`)

| Path | Purpose |
|------|---------|
| `AGENTS.md` | User-level global instructions |
| `opencode.json` | User-level runtime config (models, providers, permissions, agent overrides) |
| `tui.json` | TUI-specific settings |
| `agents/` | Custom agent definitions (markdown with frontmatter) |
| `commands/` | Custom command definitions |
| `modes/` | Mode configurations |
| `plugins/` | Plugin files |
| `skills/` | Agent skills |
| `themes/` | Custom themes |
| `tools/` | Custom tool definitions |

Notes:
- OpenCode falls back to `CLAUDE.md` if `AGENTS.md` is absent
- Plural directory names are canonical; singular also supported for backward compatibility
- Built-in agents can be overridden in `opencode.json`; custom agents can be defined as markdown files in `agents/`
- Skills are agent-loadable instruction packs; slash-invokable workflows belong in `commands/`
- Prefer `permission` over legacy `tools` for new OpenCode configuration
- Use the `instructions` field in `opencode.json` to reuse external rule files instead of duplicating long AGENTS content; prefer `$HOME`-based paths for shared user-level files
- This repo currently tracks OpenCode `opencode.json` for the shared default model `openai/gpt-5.4`, local `ollama/gemma4:31b` provider configuration, the built-in `build` agent permission override, and disabled sharing; it also tracks `tui.json` for stacked diff rendering

## Editing Guidelines

- Consult official docs above before structural changes
- Keep instruction files concise; split with `rules/` when growing large
- Keep shared guidance canonical in `claude-code/.claude/rules/shared-guidance.md` and keep tool-specific wrapper files thin
- Keep tracked runtime config limited to shared, portable behavior
- Test changes by starting a new session in the respective tool
