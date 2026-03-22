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
│       ├── rules/                        # organized instruction files
│       └── skills/                       # custom skills (SKILL.md files)
│           ├── commit/                   # commit conventions
│           └── update/                   # post-change doc updates
└── opencode/                             # stow package -> ~/.config/opencode/
    └── .config/
        └── opencode/
            ├── AGENTS.md                 # global instructions
            ├── agents/                   # custom agent definitions
            ├── commands/                 # custom commands
            ├── modes/                    # mode configurations
            ├── plugins/                  # plugins
            ├── skills/                   # agent skills
            │   ├── commit/               # commit conventions
            │   └── update/               # post-change doc updates
            ├── themes/                   # custom themes
            └── tools/                    # custom tool definitions
```

Machine-local paths (`projects/`, `agent-memory/`) and auto-generated config files (`settings.json`, `keybindings.json`) are intentionally excluded.

## Setup

### Prerequisites

- [GNU Stow](https://www.gnu.org/software/stow/)

```bash
pacman -S --needed stow
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
