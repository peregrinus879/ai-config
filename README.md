# dotfiles-ai

Claude Code and OpenCode global dotfiles, managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Repo Family

- [`dotfiles-ai`](https://github.com/peregrinus879/dotfiles-ai) - AI harness configs: Claude Code and OpenCode settings, shared guidance, and commit workflow
- [`dotfiles-arch`](https://github.com/peregrinus879/dotfiles-arch) - Shared Arch Linux terminal baseline: Bash, Tmux, Neovim, Starship, Git, Yazi, btop, and fastfetch
- [`dotfiles-wsl`](https://github.com/peregrinus879/dotfiles-wsl) - WSL overlay for dotfiles-arch: Windows Terminal, clipboard integration, and repo auto-refresh
- [`dotfiles-omarchy`](https://github.com/peregrinus879/dotfiles-omarchy) - Personal Omarchy customizations: Bash overrides, Hyprland bindings, Neovim plugins, and Yazi

## Supported Tools

- [Claude Code](https://code.claude.com/docs/en/overview) - AI-powered coding assistant with a terminal CLI
- [OpenCode](https://opencode.ai/docs) - Open source AI coding agent with a terminal-based interface

## Scope

This repo tracks shared cross-tool AI assistant guidance and portable tracked config for Claude Code and OpenCode.

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
│           └── commit/                   # commit workflow (doc sync, scratch cleanup)
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
            │   └── commit/               # commit workflow (doc sync, scratch cleanup)
            ├── themes/                   # custom themes
            └── tools/                    # custom tool definitions
```

Tracked runtime config is limited to shared behavior, currently Claude Code `settings.json` for the custom status line, OpenCode `opencode.json` for the shared default model `openai/gpt-5.4`, local `ollama/gemma4:31b` provider definition, built-in `build` agent approval policy, and disabled conversation sharing, plus OpenCode `tui.json` for a stacked diff view that works better over SSH.

Machine-local paths (`projects/`, `agent-memory/`), auth/session state, and generated or host-specific config files remain intentionally excluded. The repo root `.gitignore` tracks the documented machine-local paths so accidental local state stays out of Git.

Repo-root instruction files exist only to maintain `dotfiles-ai` itself; they are not part of the stowed payload.

The built-in OpenCode `build` agent is intentionally overridden to require approval for file edits and non-read-only bash commands while allowing a narrow set of read-only shell inspections.

Shared guidance now lives in `claude-code/.claude/rules/shared-guidance.md`. Claude Code loads it natively from `rules/`, while OpenCode loads the same file through the `instructions` field in `opencode.json` using `$HOME`-based path expansion.

This shared file reduces drift between Claude Code and OpenCode while keeping tool-specific wrappers thin.

Sharing follows a simple rule in this repo:

- Share policy.
- Separate mechanism.

In practice, guidance is shared when the content and meaning are the same in both tools. Tool-specific config, wrappers, and schemas stay separate.

At the repo root, `AGENTS.md` is the canonical project instruction file and `CLAUDE.md` is a thin compatibility wrapper for Claude Code.

OpenCode skills are loaded by the agent, while custom slash commands live under `commands/`; this repo keeps a `/commit` wrapper and folds documentation sync and scratch file cleanup into the commit workflow instead of maintaining a separate `/update` command.

## Review Workflow

For multi-file review in Claude Code or OpenCode, use Bash mode with Git diffs:

1. Run `!git status --short` to see touched files.
2. Run `!git diff --stat` for a compact overview.
3. Run `!git diff` to review the full patch.
4. Run `!git diff -- path/to/file` to isolate one file.

Both tools support `!`-prefixed Bash commands in the interactive terminal UI.

`opencode/.config/opencode/tui.json` sets `diff_style` to `stacked`, which is easier to scan in narrower SSH terminals.

OpenCode docs can reflect the `dev` branch before a feature reaches the latest stable release, so prefer your installed `/help` output when docs and behavior disagree.

## Setup

### Prerequisites

- [GNU Stow](https://www.gnu.org/software/stow/)

```bash
sudo pacman -S --needed stow
```

### Clone

Recommended local layout for this repo family:

```text
~/projects/repos/dotfiles/dotfiles-ai
```

Stow can work from any clone location, but the related docs and cross-repo maintenance workflows assume this layout.

```bash
git clone https://github.com/peregrinus879/dotfiles-ai.git ~/projects/repos/dotfiles/dotfiles-ai
```

### Prepare

Checklist before stowing:

- Stow is installed
- `dotfiles-ai` was cloned locally
- Any existing conflicting config files were removed

Remove existing files that would conflict with stow. The first block removes tree-folded directory symlinks left by a previous stow (harmless on a fresh machine). The second block removes the one file Claude Code auto-creates that would conflict on a fresh install:

```bash
# Tree-folded directory symlinks (from a previous stow)
rm -f ~/.claude/agents ~/.claude/rules ~/.claude/skills
rm -f ~/.config/opencode ~/.config/opencode/agents ~/.config/opencode/commands \
  ~/.config/opencode/modes ~/.config/opencode/plugins ~/.config/opencode/skills \
  ~/.config/opencode/themes ~/.config/opencode/tools

# Individual config files
rm -f ~/.claude/settings.json
```

### Stow

Create symlinks for all packages:

```bash
cd ~/projects/repos/dotfiles/dotfiles-ai
stow -v -t ~ claude-code opencode
```

### Unstow

```bash
cd ~/projects/repos/dotfiles/dotfiles-ai
stow -D -v -t ~ claude-code opencode
```

### Dry Run

Preview what stow would do without making changes:

```bash
cd ~/projects/repos/dotfiles/dotfiles-ai
stow -v -n -t ~ claude-code opencode
```

### Re-stow

To update symlinks after the repo content changes (same clone path):

```bash
cd ~/projects/repos/dotfiles/dotfiles-ai
stow -R -v -t ~ claude-code opencode
```

To migrate from a different clone path, unstow from the old location first:

```bash
cd /old/clone/path
stow -D -v -t ~ claude-code opencode
cd ~/projects/repos/dotfiles/dotfiles-ai
stow -v -t ~ claude-code opencode
```

If the old clone is no longer available, run the full cleanup in the Prepare section before stowing.

## Verify

After stowing the shared AI tooling config:

- Confirm core symlinks exist: `test -L ~/.claude/CLAUDE.md && test -L ~/.config/opencode/opencode.json`
- Start a fresh Claude Code session and confirm the shared guidance file and status line load as expected.
- Run `opencode debug config` and confirm the resolved config includes the shared guidance path and `share = disabled`.
- Confirm `/commit` still routes through the repo skill workflow in both tools.

## References

- `README.md` - repo scope, structure, setup, and verification
- `AGENTS.md` - canonical repo-specific assistant context and maintainer checklist
- `CLAUDE.md` - thin Claude Code wrapper importing `AGENTS.md`
- `claude-code/.claude/rules/shared-guidance.md` - canonical shared cross-tool guidance

## Related Repos

- `~/projects/repos/dotfiles/dotfiles-arch` - shared Linux baseline for terminal tooling and editor config
- `~/projects/repos/dotfiles/dotfiles-wsl` - additive WSL and Windows-specific overlay for the same repo family

## License

[MIT](LICENSE)
