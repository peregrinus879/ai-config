# dotfiles-ai

Global configuration files for AI coding assistants, managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Supported Tools

- [Claude Code](https://code.claude.com/docs/en/overview) - AI-powered coding assistant with a terminal CLI
- [OpenCode](https://opencode.ai/docs) - Open source AI coding agent with a terminal-based interface

## Scope

This repo tracks user-level terminal configuration for Claude Code and OpenCode.

It intentionally excludes auth and session state, machine-local files, and generated host-specific config. The repo root keeps a minimal `AGENTS.md` plus a thin `CLAUDE.md` compatibility wrapper so the repo can be maintained natively in both tools.

## Structure

```
dotfiles-ai/
├── AGENTS.md                             # canonical repo maintenance instructions
├── CLAUDE.md                             # Claude wrapper importing AGENTS.md
├── README.md                             # human-facing documentation
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

Repo-root instruction files exist only to maintain `dotfiles-ai` itself; they are not part of the stowed payload.

The built-in OpenCode `build` agent is intentionally overridden to require approval for file edits and non-read-only bash commands while allowing a narrow set of read-only shell inspections.

Shared guidance now lives in `claude-code/.claude/rules/shared-guidance.md`. Claude Code loads it natively from `rules/`, while OpenCode loads the same file through the `instructions` field in `opencode.json` using `$HOME`-based path expansion.

This shared file reduces drift between Claude Code and OpenCode while keeping tool-specific wrappers thin.

Sharing follows a simple rule in this repo:

- Share policy.
- Separate mechanism.

In practice, guidance is shared when the content and meaning are the same in both tools. Tool-specific config, wrappers, and schemas stay separate.

At the repo root, `AGENTS.md` is the canonical project instruction file and `CLAUDE.md` is a thin compatibility wrapper for Claude Code.

OpenCode skills are loaded by the agent, while custom slash commands live under `commands/`; this repo keeps a `/commit` wrapper and folds documentation sync into the commit workflow instead of maintaining a separate `/update` command.

## Review Workflow

For multi-file review in Claude Code or OpenCode, use Bash mode with Git diffs:

1. Run `!git status --short` to see touched files.
2. Run `!git diff --stat` for a compact overview.
3. Run `!git diff` to review the full patch.
4. Run `!git diff -- path/to/file` to isolate one file.

Both tools support `!`-prefixed Bash commands in the interactive terminal UI.

`opencode/.config/opencode/tui.json` sets `diff_style` to `stacked`, which is easier to scan in narrower SSH terminals.

OpenCode docs can reflect the `dev` branch before a feature reaches the latest stable release, so prefer your installed `/help` output when docs and behavior disagree.

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
