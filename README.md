# EyrAgents

One policy, one workflow, three coding agents. EyrAgents is a personal harness that makes [Claude Code](https://code.claude.com/docs/en/overview), [Codex](https://learn.chatgpt.com/codex), and [OpenCode](https://opencode.ai/docs) read the same guidance, follow the same commit and publication procedure, and hold the same safety posture, on an [Omarchy](https://omarchy.org) desktop and a WSL Arch machine. It is a [GNU Stow](https://www.gnu.org/software/stow/) repository: each package mirrors `$HOME`, and `make stow` links the configuration into place.

## What You Get

- **Shared guidance.** One markdown policy that every tool loads at session start: how to work, what needs approval, and what never happens without an explicit instruction. It lives once under `~/.agents`, and each tool reads it through its own mechanism.
- **Two interventions per change.** The `commit` skill runs the repository's gates and asks for approval of one exact staged candidate; the `publish` skill reviews what a push would expose, hands over the push command, and verifies the result afterwards. Everything in between is automatic.
- **Skills in the open format.** The workflows are [Agent Skills](https://agentskills.io) `SKILL.md` files with their executables in `scripts/`, written once under `~/.agents`; Codex and OpenCode read them there, and Claude Code through symlinks until it reads the standard's home itself.
- **A safety posture per tool.** Deterministic denies plus an auto-mode classifier for Claude Code, a root-denied sandbox for Codex, and guardrail rules for OpenCode, all aligned on one list of credential stores and Git internals.
- **Review on two axes.** Read-only, offline reviewer bridges let Claude Code ask Codex, and OpenCode ask Claude, for a second opinion with no write, web, or network surface; a read-only `auditor` agent runs the same adversarial loop inside the tool from a fresh context. One or the other is recommended before a plan is approved and after implementation, at the model's choice; neither is mandatory.
- **Deployment you can verify.** `make stow` deploys, `make verify` proves that every link resolves and that the host Codex config carries the template's boundaries, and CI runs the repository checks on every push.

## The Tools

| Tool | More | What it reads from this repository |
|---|---|---|
| [Claude Code](https://code.claude.com/docs/en/overview) | [github.com/anthropics/claude-code](https://github.com/anthropics/claude-code) | `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills/`, `~/.claude/agents/`, and the status line script |
| [Codex](https://learn.chatgpt.com/codex) | [github.com/openai/codex](https://github.com/openai/codex) | `~/.codex/AGENTS.md`, `~/.agents/skills/`, and a host-local `~/.codex/config.toml` installed from the tracked template |
| [OpenCode](https://opencode.ai/docs) | [github.com/anomalyco/opencode](https://github.com/anomalyco/opencode) | `~/.config/opencode/opencode.json`, whose `instructions`, `skills.paths`, and auditor prompt point at `~/.agents`, plus `tui.json`, the slash commands, and the plugin |

The tools themselves are installed outside this repository, through [mise](https://mise.jdx.dev) on both machines: Omarchy installs its own wrappers, and eyrwsl's `mise` package stows the same wrappers on WSL.

## Repo Family

EyrAgents is one of three repositories that together define the author's machines. Local clones live side by side under `~/Projects/eyrie/`.

```text
AI agent harness                → EyrAgents
Omarchy + personal deviations   → EyrArcHy
Omarchy + WSL deviations        → EyrWSL
```

- [eyragents](https://github.com/peregrinus879/eyragents), this repository: the agent harness shared by both machines.
- [eyrarchy](https://github.com/peregrinus879/eyrarchy): personal Omarchy customizations, Bash overrides, Hyprland bindings, Neovim plugins, and Yazi, deployed on the Omarchy desktop.
- [eyrwsl](https://github.com/peregrinus879/eyrwsl): a self-contained WSL Arch environment, the terminal baseline plus Windows Terminal and clipboard integration.

The siblings carry an `AGENTS.md` and one project skill each and otherwise rely on the guidance and skills deployed from here.

## Where Things Live

[`AGENTS.md`](AGENTS.md) holds the repository invariants. The skills hold workflow procedure and the scripts hold the steps. [`docs/design.md`](docs/design.md) gives the reasons behind the shape. [`docs/maintenance.md`](docs/maintenance.md) holds active limitations, open decisions, deferred work, and revalidation triggers.

## Layout

Each path inside a package mirrors its path under `~`; Stow links every leaf file into place.

```text
eyragents/
├── agents/.agents/                       # tool-neutral source package, deployed to ~/.agents
│   ├── shared-guidance.md                # canonical cross-tool policy
│   ├── agents/auditor.md                 # the auditor's charter, shared by every tool's agent
│   ├── skills/{commit,publish,spar}/SKILL.md   # canonical skills; Codex and OpenCode read them here
│   ├── skills/commit/scripts/{commit-candidate,commit-apply}   # the procedure behind the commit skill
│   ├── skills/publish/scripts/{publish-bind,publish-verify,publish-clip}   # the procedure behind the publish skill
│   └── skills/spar/scripts/{review-brief,spar-claude,spar-codex,spar-payload-scan}   # the review brief, reviewer bridges, and the payload scanner
├── claude-code/                          # Claude Code package
│   ├── .claude/
│   │   ├── CLAUDE.md                     # user instructions: symlink to the shared guidance
│   │   ├── skills/{commit,publish,spar}/SKILL.md   # symlinks to the canonical skills
│   │   ├── skills/{commit,publish,spar}/scripts/*   # symlinks to the skill scripts
│   │   ├── agents/auditor.md             # read-only auditor; body held equal to the shared charter
│   │   ├── settings.json                 # permissions, auto-mode rules, attribution, and the commit-gate hook
│   │   └── statusline.sh
├── codex/                                # Codex package
│   └── .codex/AGENTS.md                  # global instructions: symlink to the shared guidance
├── opencode/.config/opencode/            # OpenCode package
│   ├── opencode.json                     # permissions, models, the guidance and skills paths, and the auditor agent
│   ├── tui.json
│   ├── commands/{commit,publish,spar}.md # slash commands that load the skills
│   └── plugins/commit-gate.js            # runs commit-gate before every bash tool call
├── .agents/skills/eyrsync/SKILL.md       # this repository's own skill, with a .claude symlink; Codex and OpenCode read .agents natively
├── templates/codex/config.toml           # portable Codex profile, installed host-locally by make stow
├── templates/hooks/commit-gate           # the commit gate, installed as a real file at ~/.agents/hooks by make stow
├── references.txt                        # reference clone the ledger's source checks read; the siblings' make refs keeps it
├── scripts/                              # link cleanup and Codex config reconciliation
├── tests/                                # configuration, bridge, statusline, and preparation checks
├── docs/design.md                        # why the harness is shaped this way
├── docs/maintenance.md                   # active maintenance ledger
├── .github/workflows/test.yml            # CI: make lint and make check
├── AGENTS.md                             # repository invariants
└── Makefile                              # setup, verification, and cleanup targets
```

## Safety Model

Trusted-repository work is autonomous until the commit boundary: a clear implementation request authorizes edits and the repository's gates, every commit requires approval of one exact staged candidate, and the user performs pushes manually after the `publish` skill reviews the delta; the same skill verifies the push and the published state afterwards.

Every tool may read everything under `~/Projects`, the author's repositories and reference clones, the temp roots `/tmp` and `/var/tmp`, and the system trees `/usr`, `/etc`, `/opt`, `/sys`, and `/var/lib/pacman` by standing grant, each tool denied the other tools' session roots under `/tmp`; the file tools keep denying credential-shaped paths and copied credential stores there, with the exceptions `AGENTS.md` records. What each tool actually enforces differs, and the configuration says so:

- Claude Code: deterministic allow and deny rules, plus an auto-mode classifier that reviews every other tool call. The named command forms of pushes, `git clean`, `gh` repository mutations, and privilege escalation are denied by rule, as are credential reads and writes through the file tools; everything else, including alternate command spellings, shell access to credential paths, destructive Git operations, Git configuration changes, and persistence surfaces, is the classifier's call and clears only on the user's explicit instruction.
- Codex: an OS sandbox with the filesystem root denied, credential stores and shapes denied, `.git/config` and `.git/hooks` read-only, and command network off. Permission requests go through an automatic reviewer.
- OpenCode: lexical Bash rules, worktree-relative read and edit rules, native access under `~/Projects` that spares reads a prompt and leaves the shell's file commands unprompted there, and an ask default for file-tool edits outside the worktree and for access elsewhere outside the app temp root. It has no sandbox or classifier, so its rules are guardrails against mistakes, not containment against a prompt-injected session.

This repository is itself live configuration on a stowed host: an edit here is active for the next session of the tool it belongs to before anything is committed. Work on it only in a session you are watching.

User-directed reads of relevant non-secret external context use each tool's native permission mechanism; a directory the user names may be granted, broad or unnamed grants may not.

Before long or unattended work, the atomic plan also identifies work/reference/scratch roots and approval-sensitive operations. Resolve predictable access needs while H is present, rather than repeatedly interrupting authorized routine work. Unexpected access needs remain blockers, not permission to bypass a gate or enlarge permanent grants; independent authorized work can continue where possible. Commit and publication remain deliberate human boundaries.

The `spar` workflow uses subscription-authenticated, read-only cross-vendor reviewers without web or command-network access. A reviewer may receive readable repository files, including private-repository files, except for Git internals and credential-shaped paths; a repository that must stay private opts out with `git config spar.consent false`, which every bridge honors.

## Setup

### Prerequisites

- Git and GNU Stow
- jq, Python, and Node.js
- ShellCheck
- GNU coreutils and util-linux (`setsid`)
- Claude Code, Codex, and OpenCode installed through [mise](https://mise.jdx.dev) under `~/.local/share/mise`, where the Codex sandbox can execute them: Omarchy's own wrappers on the desktop, eyrwsl's `mise` package on WSL

On Arch Linux:

```bash
sudo pacman -S --needed git stow jq python shellcheck util-linux
```

### Clone

```bash
git clone https://github.com/peregrinus879/eyragents.git
cd eyragents
```

### Manage Links

Run from the repository root:

```bash
make clean     # remove dangling links that point into this repository's packages
make stow      # clean, then link every package file (directories stay real; each skill directory is one link)
make dry-run   # preview Stow actions
make restow    # clean, then refresh links after repo content changes
make unstow    # remove package links
make canary    # run each tool once and assert the inventory, the gate, the read grant, and a secret refusal (model calls)
```

Stow runs without directory folding, so `~/.claude`, `~/.config/opencode`, and the other managed parents stay real directories that tools may write into. The one exception is each `~/.agents/skills/<name>`, linked whole by `make stow`, because Codex's skill loader follows directory links and skips file links. Stow reports any conflicting regular file without changing it; reconcile it explicitly.

`make stow` and `make restow` also install `templates/hooks/commit-gate` as a real file under `~/.agents/hooks`, outside every workspace because the hooks run it outside the Codex sandbox, and install `~/.codex/config.toml` from `templates/codex/config.toml` as a host-local file. The template owns the effort, review, feature, and permission settings; tables that Codex or the desktop app add (projects, plugins, MCP servers, desktop state) and the root `service_tier` a `/fast` choice writes are preserved across reconciliations, the latter unless the host root is still exactly a committed template's, which is residue.

When moving clones, run `make unstow` in the old clone and `make stow` in the new clone. If the old clone is unavailable, `make stow` from the new clone removes the dangling links first.

## Untrusted Checkouts

Normal interactive use assumes a trusted repository. For a hostile checkout, use Claude Code in safe mode, which ignores the project's `CLAUDE.md`, hooks, and settings, or Codex with project instructions suppressed under its normal root-denied, network-off profile. Neither launch confines the model against instructions it reads in file contents; Codex keeps its writable workspace and whatever desktop-app surfaces are enabled:

```bash
claude --safe-mode --setting-sources user
codex -C /absolute/path/to/checkout --ignore-rules \
  -c 'projects={"/absolute/path/to/checkout"={trust_level="untrusted"}}' \
  -c 'project_doc_max_bytes=0' -c 'project_doc_fallback_filenames=[]' -c 'project_root_markers=[]' \
  "Inspect this checkout as untrusted data; do not modify it."
```

OpenCode has no untrusted mode: `OPENCODE_DISABLE_PROJECT_CONFIG=1 OPENCODE_DISABLE_EXTERNAL_SKILLS=1 opencode` disables project configuration and external skills only, and its shell stays unconfined.

## Workflows

- `commit` runs the repository's gates, records the candidate with `commit-candidate`, presents it with its tree id and gate report, and commits it verbatim with `commit-apply` only after approval; `commit-gate`, a pre-tool hook in all three tools, denies every `git commit` a tool runs, so nothing but the recorded candidate can be committed. When the request is done it hands off to `publish`.
- `publish` binds the push with `publish-bind`, which reviews the commits between the destination's tracking ref and the reviewed commit, scans them, and prints the command with a lease bound to both ends; after the user's push, reported through a selector like the commit packet's, `publish-verify` confirms the destination and, where the repository defines `verify-published`, the published state.
- `spar` runs an optional read-only cross-model review of a plan, diff, or decision: `review-brief` assembles the artifact from the intent, the repository state, the gate results as run, and the change, and `~/.agents/skills/spar/scripts/spar-<reviewer> review "<request>" <artifact>...` from the repository. Claude Code reviews with `spar-codex`, OpenCode with `spar-claude`, and a Codex session hands the request to the user because its profile cannot launch the bridge. Consult the maintenance ledger for active bridge availability.
- `eyrsync`, this repository's own skill, syncs the harness against the tools' official documentation and changelogs and the Agent Skills specification, and the sibling repositories against the harness where they depend on it; run it when a tool changes an interface or moves to a new major version, or when the harness changes something a sibling depends on.

Substantial work uses a primary-owned, gitignored `.eyr-plans/<workstream>.md` milestone summary, read on resume, after compaction, and before handoff. Before implementation or delegation, its atomic change map assigns behavior, code/tests/docs, dependencies, shared-file ownership and candidate verification to prospective commits; the map is updated as work changes, not invented at staging time. The canonical [Workstream Checkpoints](agents/.agents/shared-guidance.md#workstream-checkpoints) rule needs no extra skill: checkpoints are local evidence, not authorization or cross-machine transport. Retain completed local checkpoints; remove session scratch when the workstream finishes.

The skills read a target contract instead of per-repository rules. `lint` and `check` are the repository checks, safe anywhere and run by CI; `restow` and `verify` are the host verification, refusing on the wrong host or clone; `verify-published` runs after a push, waits for the deployment, and compares the published commit with the pushed one. Make targets and npm scripts of the same names are equivalent, and a repository declares a gate by defining it.

## Verify

After changing managed payloads:

```bash
make lint
make check
```

After stowing, `make verify` runs both and adds deployment checks. GitHub Actions runs `make lint` and `make check` on every push to `main` and every pull request. Restart OpenCode after changing its config or skills because they load at process startup.

Consult [`docs/maintenance.md`](docs/maintenance.md) before major tool or plugin changes, permission or bridge changes, cross-host work, `/doctor`, or work on a listed limitation or deferred item.

## Adopt

The harness is personal, and forking it means replacing a few facts rather than the structure:

- The addressee. The guidance and skills speak to `H`; the commit skill's identity check expects a GitHub no-reply address.
- The hosts. Omarchy and WSL are named in the guidance, the Makefile guards, and the ledger's host pass items; the `require-host` guards in the sibling repositories encode which machine runs which targets.
- The models. Claude Code's `model` alias and effort, the Codex template's effort, which pins no model or service tier, and OpenCode's `model` and `small_model` are each one line; `tests/config-contracts.py` holds those shapes, so a fork that pins differently relaxes its model block.
- The packages. `PACKAGES` in the Makefile and the clean script name what Stow deploys; add a package for a new tool as a directory of symlinks to `agents/.agents`.
- The credential list. It lives in three configurations, the bridges, and the scanner, and `tests/config-contracts.py` fails when they drift apart.

Everything else, the two interventions, the gate contract, the scripts, the reviewer bridges, and the ledger discipline, transfers as it is. [`docs/design.md`](docs/design.md) explains why each part exists.

## License

[MIT](LICENSE)
