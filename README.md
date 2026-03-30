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
│       ├── CLAUDE.md                     # global instructions
│       ├── agents/                       # custom agents
│       ├── settings.json                 # runtime settings (status line, permissions)
│       ├── rules/                        # organized instruction files
│       ├── skills/                       # custom skills (SKILL.md files)
│       │   ├── commit/                   # commit conventions
│       │   └── update/                   # post-change doc updates
│       └── statusline.sh                 # terminal status line script
└── opencode/                             # stow package -> ~/.config/opencode/
    └── .config/
        └── opencode/
            ├── AGENTS.md                 # global instructions
            ├── agents/                   # custom agent definitions
            ├── commands/                 # custom slash commands
            │   ├── commit.md             # wrapper for the commit skill
            │   └── update.md             # wrapper for the update skill
            ├── modes/                    # mode configurations
            ├── opencode.json             # runtime config and agent overrides
            ├── plugins/                  # plugins
            ├── skills/                   # agent skills
            │   ├── commit/               # commit conventions
            │   └── update/               # post-change doc updates
            ├── themes/                   # custom themes
            └── tools/                    # custom tool definitions
```

Tracked runtime config is limited to shared behavior, currently Claude Code `settings.json` for the custom status line and OpenCode `opencode.json` for the built-in `build` agent approval policy.

Machine-local paths (`projects/`, `agent-memory/`), auth/session state, and generated or host-specific config files remain intentionally excluded.

The built-in OpenCode `build` agent is intentionally overridden to require approval for file edits and non-read-only bash commands while allowing a narrow set of read-only shell inspections.

OpenCode skills are loaded by the agent, while custom slash commands live under `commands/`; this repo includes `/commit` and `/update` wrappers that invoke the corresponding skills.

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
