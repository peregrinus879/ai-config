# dotfiles-ai

Global configuration files for AI coding assistants, managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Supported Tools

- [Claude Code](https://code.claude.com/docs/en/overview) - Anthropic's CLI for Claude
- [OpenCode](https://opencode.ai/docs) - Open-source AI coding assistant

## Structure

```
dotfiles-ai/
├── claude-code/                          # stow package -> ~/.claude/
│   └── .claude/
│       ├── CLAUDE.md                     # Claude-specific instructions
│       ├── settings.json                 # runtime settings (status line, permissions)
│       ├── statusline.sh                 # terminal status line script
│       ├── agents/                       # custom agents
│       ├── rules/                        # organized instruction files
│       │   └── shared-guidance.md        # canonical shared instructions
│       └── skills/                       # custom skills (SKILL.md files)
│           └── commit/                   # commit conventions and doc sync
└── opencode/                             # stow package -> ~/.config/opencode/
    └── .config/
        └── opencode/
            ├── AGENTS.md                 # OpenCode-specific instructions
            ├── opencode.json             # runtime config and agent overrides
            ├── tui.json                  # TUI-specific config
            ├── agents/                   # custom agent definitions
            ├── commands/                 # custom slash commands
            │   └── commit.md             # wrapper for the commit skill
            ├── modes/                    # mode configurations
            ├── plugins/                  # plugins
            ├── skills/                   # agent skills
            │   └── commit/               # commit conventions and doc sync
            ├── themes/                   # custom themes
            └── tools/                    # custom tool definitions
```

Tracked runtime config is limited to shared behavior, currently Claude Code `settings.json` for the custom status line, OpenCode `opencode.json` for the shared default model `openai/gpt-5.4`, local `ollama/gemma4:31b` provider definition, built-in `build` agent approval policy, and disabled conversation sharing, plus OpenCode `tui.json` for a stacked diff view that works better over SSH.

Machine-local paths (`projects/`, `agent-memory/`), auth/session state, and generated or host-specific config files remain intentionally excluded.

The built-in OpenCode `build` agent is intentionally overridden to require approval for file edits and non-read-only bash commands while allowing a narrow set of read-only shell inspections.

Shared guidance now lives in `claude-code/.claude/rules/shared-guidance.md`. Claude Code loads it natively from `rules/`, while OpenCode loads the same file through the `instructions` field in `opencode.json` using `$HOME`-based path expansion.

OpenCode skills are loaded by the agent, while custom slash commands live under `commands/`; this repo keeps a `/commit` wrapper and folds documentation sync into the commit workflow instead of maintaining a separate `/update` command.

## Review Workflow

For multi-file review in Claude Code or OpenCode, use Bash mode with Git diffs:

1. Run `!git status --short` to see touched files.
2. Run `!git diff --stat` for a compact overview.
3. Run `!git diff` to review the full patch.
4. Run `!git diff -- path/to/file` to isolate one file.

Both tools support `!`-prefixed Bash commands in the interactive terminal UI.

`opencode/.config/opencode/tui.json` sets `diff_style` to `stacked`, which is easier to scan in narrower SSH terminals.

The current OpenCode docs site can describe TUI features from the `dev` branch before they appear in the latest stable release, so prefer your installed `/help` output over the docs when a slash command is missing.

## Maintainer Checklist

When updating this repo for new Claude Code or OpenCode releases:

1. Review the current Claude Code docs for overview, settings, memory, skills, and hooks.
2. Review the current OpenCode docs for config, rules, permissions, agents, skills, TUI, and sharing.
3. Run `opencode debug config` and confirm the resolved config still matches the tracked intent.
4. Start a fresh session in both tools and verify the shared guidance file is loaded.
5. Verify Claude Code status line behavior still matches `claude-code/.claude/settings.json` and `statusline.sh`.
6. Verify OpenCode diff review remains usable over SSH and that sharing stays disabled unless intentionally changed.
7. Verify `/commit` still performs documentation sync before staging when docs are affected.

## Setup

### Prerequisites

- [GNU Stow](https://www.gnu.org/software/stow/)

```bash
sudo pacman -S --needed stow
```

### Clone

```bash
git clone https://github.com/peregrinus879/dotfiles-ai.git ~/path/to/dotfiles-ai
```

Or with SSH:

```bash
git clone git@github.com:peregrinus879/dotfiles-ai.git ~/path/to/dotfiles-ai
```

### Stow

Create symlinks for all packages:

```bash
cd ~/path/to/dotfiles-ai
stow -v -t ~ claude-code opencode
```

### Unstow

```bash
cd ~/path/to/dotfiles-ai
stow -D -v -t ~ claude-code opencode
```

### Dry Run

Preview what stow would do without making changes:

```bash
cd ~/path/to/dotfiles-ai
stow -v -n -t ~ claude-code opencode
```

## License

[MIT](LICENSE)
