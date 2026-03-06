# ai-config

Global configuration files for AI coding assistants, managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Supported Tools

- [Claude Code](https://code.claude.com/docs/en/overview) - Anthropic's CLI for Claude
- [OpenCode](https://opencode.ai/docs) - Open-source AI coding assistant

## Structure

```
ai-config/
├── claude-code/                          # stow package -> ~/.claude/
│   └── .claude/
│       ├── CLAUDE.md                     # global instructions
│       ├── agents/                       # custom agents
│       └── rules/                        # organized instruction files
└── opencode/                             # stow package -> ~/.config/opencode/
    └── .config/
        └── opencode/
            ├── AGENTS.md                 # global instructions
            ├── agents/                   # custom agent definitions
            ├── commands/                 # custom commands
            ├── modes/                    # mode configurations
            ├── plugins/                  # plugins
            ├── skills/                   # agent skills
            ├── themes/                   # custom themes
            └── tools/                    # custom tool definitions
```

## Setup

### Prerequisites

- [GNU Stow](https://www.gnu.org/software/stow/) (`pacman -S stow`)

### Clone

```bash
git clone git@github.com:peregrinus879/ai-config.git ~/path/to/ai-config
```

### Stow

Create symlinks for all packages:

```bash
cd ~/path/to/ai-config
stow -v -t ~ claude-code opencode
```

### Unstow

```bash
cd ~/path/to/ai-config
stow -D -v -t ~ claude-code opencode
```

### Dry Run

Preview what stow would do without making changes:

```bash
cd ~/path/to/ai-config
stow -v -n -t ~ claude-code opencode
```

## License

[MIT](LICENSE)
