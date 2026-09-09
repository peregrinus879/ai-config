# EyrAgents

One policy, one workflow, three coding agents. EyrAgents is a personal harness that makes [Claude Code](https://code.claude.com/docs/en/overview), [Codex](https://learn.chatgpt.com/codex), and [OpenCode](https://opencode.ai/docs) read the same guidance, follow the same commit and publication procedure, and hold the same safety posture, on an [Omarchy](https://omarchy.org) desktop and a WSL Arch machine. It is a [GNU Stow](https://www.gnu.org/software/stow/) repository: each package mirrors `$HOME`, and `make stow` links the configuration into place.

## What You Get

- **Shared guidance.** One markdown policy that every tool loads at session start. Its [Approach](agents/.agents/shared-guidance.md#approach) starts from H's goal and the surrounding system, checks missing counterparts and alternatives, and clarifies material uncertainty rather than treating the first example or existing file as the whole problem. It distinguishes broad reasoning from authorized action and recurring workarounds from durable results. It lives once under `~/.agents`, and each tool reads it through its own mechanism.
- **Two approval/publication boundaries.** The `commit` skill runs the repository's gates and asks for approval of one exact staged candidate; the `publish` skill reviews what a push would expose, hands over the push command, and verifies the result afterwards. Packets stay visible in chat. Copying the push command is optional and user-triggered; ambiguity and unsafe operations still stop for H.
- **Skills in the open format.** The workflows are [Agent Skills](https://agentskills.io) `SKILL.md` files with their executables in `scripts/`, written once under `~/.agents`; Codex and OpenCode read them there, and Claude Code through symlinks until it reads the standard's home itself.
- **A safety posture per tool.** Deterministic denies plus an auto-mode classifier for Claude Code, a root-denied sandbox for Codex, and guardrail rules for OpenCode, all aligned on one list of credential stores and Git internals.
- **Review on two axes.** Read-only, offline reviewer bridges let Claude Code ask Codex, and OpenCode ask Claude, for a second opinion with no write, web, or network surface; a read-only `auditor` agent runs the same adversarial loop inside the tool from a fresh context. One or the other is recommended before a plan is approved and after implementation, at the model's choice; neither is mandatory.
- **Deployment you can verify.** `make stow` deploys, `make verify` proves that every link resolves and that the host Codex config carries the template's boundaries, and CI runs the repository checks on every push.

## The Tools

| Tool | More | What it reads from this repository |
|---|---|---|
| [Claude Code](https://code.claude.com/docs/en/overview) | [github.com/anthropics/claude-code](https://github.com/anthropics/claude-code) | `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills/`, `~/.claude/agents/`, and the status line script |
| [Codex](https://learn.chatgpt.com/codex) | [github.com/openai/codex](https://github.com/openai/codex) | `~/.codex/AGENTS.md`, `~/.agents/skills/`, and a host-local `~/.codex/config.toml` installed from the tracked template |
| [OpenCode](https://opencode.ai/docs) | [github.com/anomalyco/opencode](https://github.com/anomalyco/opencode) | `~/.config/opencode/AGENTS.md`, a symlink to shared guidance, and `opencode.json`, whose `skills.paths` and auditor prompt point at `~/.agents`, plus `tui.json`, the slash commands, and the plugins |

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

## Reference Strategy

[`references.txt`](references.txt) declares three official references under `~/Projects/quarry`: `claude-code` for public release/plugin/support material, and `codex` and `opencode` for client source and tests. Claude Code's public repository does not contain its proprietary CLI implementation. All three still need current official documentation, release notes and appropriately scoped runtime evidence; a source checkout alone does not prove installed behavior.

[`/eyrsync`](.agents/skills/eyrsync/SKILL.md#sources) owns reference roles and evidence coverage, and starts by checking every managed tool rather than whichever clone already exists. Its [reference lifecycle](.agents/skills/eyrsync/SKILL.md#reference-lifecycle) distinguishes explicitly approved initial creation from routine preservation-safe refreshes. Sibling `make refs` refreshes existing declared family references but does not create missing EyrAgents-only entries. Missing references and conflicting evidence stay explicit until resolved; no clone is silently discarded or added merely for symmetry.

## Where Things Live

[`AGENTS.md`](AGENTS.md) holds the repository invariants. The skills hold workflow procedure and the scripts hold the steps. [`docs/access.md`](docs/access.md) compares all three tools' read/write access, tool-call controls, rationale, implementation, and official sources. [`docs/design.md`](docs/design.md) gives the reasons behind the shape. [`docs/maintenance.md`](docs/maintenance.md) holds active limitations, open decisions, deferred work, and revalidation triggers.

## Layout

Each path inside a package mirrors its path under `~`; Stow links every leaf file into place.

```text
eyragents/
├── agents/.agents/                       # tool-neutral source package, deployed to ~/.agents
│   ├── shared-guidance.md                # canonical cross-tool policy
│   ├── agents/auditor.md                 # the auditor's charter, shared by every tool's agent
│   ├── skills/{commit,publish,spar}/SKILL.md   # canonical skills; Codex and OpenCode read them here
│   ├── skills/commit/scripts/{commit-candidate,commit-apply,governance.py}   # candidate/publication receipts and commit procedure
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
│   ├── AGENTS.md                         # native global instructions: symlink to the shared guidance
│   ├── opencode.json                     # permissions, models, skills path, and the auditor agent
│   ├── tui.json
│   ├── commands/{commit,publish,spar}.md # slash commands that load the skills
│   └── plugins/{commit-gate,auditor-permissions,scratch-permissions}.js   # shell gate, auditor policy and native scratch guardrail
├── .agents/skills/eyrsync/SKILL.md       # this repository's own skill, with a .claude symlink; Codex and OpenCode read .agents natively
├── templates/codex/config.toml           # portable Codex profile, installed host-locally by make stow
├── templates/hooks/commit-gate           # the commit gate, installed as a real file at ~/.agents/hooks by make stow
├── references.txt                        # official source/release references, with roles and lifecycle owned by eyrsync
├── scripts/                              # link cleanup and Codex config reconciliation
├── tests/                                # configuration, bridge, statusline, and preparation checks
├── docs/access.md                        # three-tool access matrices, decisions, implementation, and sources
├── docs/design.md                        # why the harness is shaped this way
├── docs/maintenance.md                   # active maintenance ledger
├── .github/workflows/test.yml            # CI: make lint and make check
├── AGENTS.md                             # repository invariants
└── Makefile                              # setup, verification, and cleanup targets
```

## Safety Model

Trusted-repository work is autonomous until the commit boundary: a clear implementation request authorizes edits and the repository's gates, every commit requires approval of one exact staged candidate, and the user performs pushes manually after the `publish` skill reviews the delta; the same skill verifies the push and the published state afterwards.

Start with the [three-tool access matrices](docs/access.md): separate read/write rows for workspace, home, system and temporary directories, followed by tool calls, consequential actions, and parity decisions. They distinguish authorization, configured capability, and verified behavior rather than treating a location grant as read-only or a classifier decision as a human prompt.

Shared guidance authorizes non-secret reads under `~/Projects`, `/tmp`, `/var/tmp`, `/usr`, `/etc`, `/opt`, `/sys`, and `/var/lib/pacman`, excluding other tools' session roots. It does not promise prompt-free or technically read-only access everywhere. Claude Code uses native rules and auto-mode review without a tracked sandbox; Codex restricts local execution with a root-denied filesystem/command-network sandbox and reviews eligible boundary crossings; OpenCode uses lexical/path guardrails, not OS containment. Credential and edit boundaries still apply where those mechanisms have gaps. Prefer narrow, one-time approvals over persistent broad grants; no global auto-approval is needed.

This repository is itself live configuration on a stowed host: an edit here is active for the next session of the tool it belongs to before anything is committed. Work on it only in a session you are watching.

User-directed reads of relevant non-secret external context use each tool's native permission mechanism; a directory the user names may be granted, broad or unnamed grants may not.

Before long or unattended work, the atomic plan also identifies work/reference/scratch roots and approval-sensitive operations. Resolve predictable access needs while H is present, rather than repeatedly interrupting authorized routine work. Unexpected access needs remain blockers, not permission to bypass a gate or enlarge permanent grants; independent authorized work can continue where possible. Commit and publication remain deliberate human boundaries.

`~/Projects/quarry` is the shared reference-clone root used by H and the sync skills, not an incidental external directory. OpenCode preapproves its location alongside `~/Projects/scratch`; Claude Code and Codex already read it through their Projects grants. Shared guidance authorizes needed routine fetch/fast-forward refreshes of existing declared quarry clones, with preservation and native permission checks. The [access matrix](docs/access.md#workspace-and-home) distinguishes that workflow from arbitrary writes and Codex's network/write restriction; `/eyrsync` owns the refresh preflight.

The `spar` workflow uses subscription-authenticated, read-only cross-vendor reviewers without web or command-network access. A reviewer may receive readable repository files, including private-repository files, except for Git internals and credential-shaped paths; a repository that must not reach the other vendor opts out with `git config spar.consent false`. An unset setting permits review; only literal `true` permits it when set, and empty values or lookup errors refuse. OpenCode's in-tool auditor permits only read/glob and denies unknown tools; grep is blocked because upstream does not apply per-file read policies to its results.

## Setup

### Prerequisites

- Git, GNU Make, and GNU Stow
- jq, Python, and Node.js (required for EyrAgents verification, not the EyrWSL baseline)
- ShellCheck 0.11.0 or newer
- GNU coreutils and util-linux (`flock`, `setsid`)
- Claude Code, Codex, and OpenCode installed through [mise](https://mise.jdx.dev) under `~/.local/share/mise`, where the Codex sandbox can execute them: Omarchy's own wrappers on the desktop, eyrwsl's `mise` package on WSL

On Arch Linux:

```bash
sudo pacman -Syu --needed git make stow jq python nodejs shellcheck util-linux
```

### Clone

```bash
git clone https://github.com/peregrinus879/eyragents.git
cd eyragents
```

### Manage Links

Run from the repository root:

```bash
make dry-run   # preview Stow actions before resolving conflicts
make clean     # guard clone and skills, then remove recognized dangling package links
make stow      # clean, then link every package file (directories stay real; each skill directory is one link)
make restow    # clean, then refresh links after repo content changes
make unstow    # remove package links
make canary    # up to six calls per tool; interactive-only checks stay incomplete
```

Stow runs without directory folding, so `~/.claude`, `~/.config/opencode`, and the other managed parents stay real directories that tools may write into. The one exception is each `~/.agents/skills/<name>`, linked whole by `make stow`, because Codex's skill loader follows directory links and skips file links. Stow reports any conflicting regular file without changing it; reconcile it explicitly.

Every host-writing Make target checks deployed-clone ownership, including cleanup, gate installation, and Codex reconciliation. `make check-skills` preflights every selected skill before cleanup or link conversion; foreign files or links cause unchanged refusal rather than partial conversion. Deployment goals are serialized within one Make invocation, including `make -j`; this is not a transaction against I/O failure or independent concurrent deployments. `make dry-run` previews Stow, not all reconciliation effects.

`make stow` and `make restow` also install `templates/hooks/commit-gate` as a real file under `~/.agents/hooks`, outside every workspace because the hooks run it outside the Codex sandbox, and install `~/.codex/config.toml` from `templates/codex/config.toml` as a host-local file. The template owns the effort, review, feature, and permission settings; host-only tables, `hooks.state`, and the root `service_tier` a `/fast` choice writes are preserved across reconciliations, the latter unless the host root is still exactly a committed template's, which is residue. Reconciliation parses TOML boundaries and checks preserved semantics before emitting replacement bytes; unsupported layouts, including inline/dotted `hooks.state`, refuse rather than discard state. Stop for deliberate host-local repair, without printing configuration values.

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

### Model Effort

The configured primary OpenCode model defaults to `xhigh`. In `/variants`, `Default` means use configured request defaults, not medium effort. An explicit named variant overrides that setting. OpenCode remembers choices separately for base Astra and Astra Fast and can skip the follow-up effort dialog when a choice already exists; use `/variants` to inspect it. A missing effort badge is not evidence of a lower request effort. Keep deliberate overrides rather than rewriting saved state or adding duplicate model pins solely for the display.

### Change Workflow

- `commit` runs the repository's gates and presents an exact candidate and its gate evidence for approval. `commit-candidate -- PATH...` records the prepared index without staging; explicit `--stage` stages whole literal intended paths and refuses partially staged mixed files before staging anything. Its immutable `candidate-id` identifies the tree, parent, branch, message, and identity; `commit-apply ID` requires that exact approved ID. `commit-candidate --show ID` displays it; `--clear ID` rejects it without restoring the index or worktree. Apply uses an isolated index with normal hooks and checks the actual commit. Rejection compensates only by a safe compare-and-swap of that invocation's uniquely identified commit; otherwise it preserves state and stops for H, never resets an unexplained tip.
- `publish` uses `publish-bind` to record an immutable `binding-id` covering the reviewed commit, tracking baseline, resolved push endpoint, branch, and relevant configuration. It scans every new commit's raw metadata, explicit per-parent merge patches, the flat diff, and complete newly reachable blobs and tree paths, including transient content removed before the tip. Its H-run command preserves `publish-bind --check ID` immediately before the explicit one-branch push, with an exact-base lease and no incidental tags or submodule pushes. `publish-verify ID` observes the bound push endpoint through read-only `ls-remote`; local tracking is reported separately, CI remains a separate check, and `verify-published` runs only where defined. Remote equality is a point-in-time observation, not proof of who pushed.
- `spar` runs an optional read-only cross-model review of a plan, diff, or decision: `review-brief` assembles the artifact from the intent, the repository state, the gate results as run, and the change, and `~/.agents/skills/spar/scripts/spar-<reviewer> review "<request>" <artifact>...` from the repository. Claude Code reviews with `spar-codex`, OpenCode with `spar-claude`, and a Codex session hands the request to the user because its profile cannot launch the bridge. Consult the maintenance ledger for active bridge availability.
- `eyrsync`, this repository's own skill, starts with reference/evidence coverage for all three tools, then reconciles the harness against current official documentation, releases, available version-matched source and runtime evidence. Its access pass connects matrix cells to decisions and implementation; its sibling pass checks shared contracts. Run it for relevant interface changes, any managed tool's breaking release, missing references or conflicting evidence, or periodically. The Agent Skills specification remains the shared format reference.

Receipts do not attest approval or gates: checks against a worktree do not attest a different staged tree, and untracked files need separate classification. Candidate and binding IDs coexist; there is no implicit latest-record apply/verify. Drift requires a new receipt and review. Binary/non-UTF-8/oversized or otherwise unscannable objects produce a partial scan with bound IDs, sizes, reasons and historical tree/path locations; H inspects those exact objects before approval or publication. Normal pre-push hooks remain enabled, with their effective targets/content digests bound for review. Actual sensitive/identity findings, unsafe hook sources, first publication without a tracking baseline, configured push options, and unsupported helpers still refuse; manual inspection is not a bypass for these. See the skills for the procedure and the ledger for active limits.

Commit and publication packets appear in normal chat before short exact-ID selectors. Preparing or re-displaying a push leaves the clipboard alone. `Copy push command` triggers one `publish-clip --copy` attempt; the helper without that flag neither reads stdin nor changes the clipboard. Copying is not approval or push confirmation. Only H's selected `Pushed, verify and resume` or `Pushed, verify and pause` starts verification.

Retained review documents live with their workstream: `.eyr-plans/<workstream>/audit/` for the in-tool auditor, and `.eyr-plans/<workstream>/spar/` for cross-vendor spar. The primary writes briefs and saves returned results; both review paths remain read-only. Disposable execution files and external temporary artifacts use the caller's private, owned `TMPDIR` below `/tmp` or `/var/tmp`, not a shared tool root. The bridges inline scanned artifacts, so reviewers need no scratch-write grant. Bridge stdout is reply-only; stderr carries a validated reviewer ID and safe runtime provenance (`model`, `effort`, `tier`, `clientversion`), with `unknown` where the client does not expose a reliable value. Configured preferences are not substituted for effective runtime evidence.

`review-brief` records full HEAD, read-only source/index fingerprints and actual gate commands/results. Failed gates or source drift keep a scanned diagnostic artifact and return exit 1. Plan mode runs no gates and writes only in private scratch or to a new, ignored, untracked Markdown file directly under `.eyr-plans/<workstream>/{audit,spar}/`; existing workstream/artifact directories must be private, owned and unlinked, and `governance` is reserved. The generator creates no directories or ignore rules and never overwrites an artifact. The fingerprints are not Git tree IDs or runtime/host attestations. Same-workstream reuse requires the original passing evidence plus unchanged relevant contents/context; untracked inputs, unattested links, unknown context, or a fresh `--no-gates` artifact cannot establish it. Combine compatible Make targets to avoid repeated prerequisite suites without inventing a persistent cache.

Substantial work uses a lean `.eyr-plans/<workstream>/checkpoint.md`, read on resume, compaction and session handoff. Its remaining atomic change map assigns behavior, code/tests/docs, dependencies and ownership before implementation or delegation. The primary updates current state and links needed `audit/` or `spar/` evidence rather than copying it into a journal. The canonical [Workstream Checkpoints](agents/.agents/shared-guidance.md#workstream-checkpoints) rule needs no extra skill: automatically remove workflow-owned artifacts once no implementation, review, approval or handoff needs them, then remove empty directories. Preserve user files and separate approval/publication records; do not keep completed plan or review archives.

For finish/push/pull handoff to another host, create a tracked `docs/handoff.md` only for concrete remaining work. It names direction, applicable code baseline/dependencies, pending actions, acceptance checks and blockers, linking the maintenance ledger's procedures instead of duplicating them. The receiving session verifies its host and Git state, then deletes the handoff in the normal approved completion commit or updates it for a real reverse handoff. It contains no credentials, transcripts or local approval records: Git retains deleted content. No empty template, automatic synchronization or transferred approval is implied.

The skills read a target contract instead of per-repository rules. `lint` and `check` are the repository checks, safe anywhere and run by CI; `restow` and `verify` are the host verification, refusing on the wrong host or clone; `verify-published` runs after a push, waits for the deployment, and compares the published commit with the pushed one. Make targets and npm scripts of the same names are equivalent, and a repository declares a gate by defining it.

## Verify

After changing managed payloads:

```bash
make lint
make check
```

After stowing, `make verify` runs both and adds deployment checks. GitHub Actions runs `make lint` and `make check` on every push to `main` and every pull request. Restart OpenCode after changing its config or skills because they load at process startup.

CI uses the official `archlinux:base` container with a full signed-package upgrade, matching the Arch userspace of both supported hosts. `ubuntu-latest` supplies only GitHub's VM. Checks run as an unprivileged `ci` user with explicit Bash, a private temporary directory and container process reaping; checkout credentials are not persisted. CI does not perform or attest deployment to Omarchy or WSL.

`make canary` is separate live behavioral smoke testing, not a repository gate or independent permission-dispatch proof. It makes up to six calls per tool: skills, reported gate denial with unchanged HEAD, README read, system read, external temporary fixture read, and fixture-marker non-disclosure. OpenCode reads its own fixture README and the preapproved `/usr/lib/os-release`; only its general external-temp check requires interactive approval and stays explicitly skipped. Each performed assertion requires a successful, nonempty reply. Exit 1 means failure; exit 2 means skipped or unverified checks; exit 0 means all selected behavioral checks passed. Verify remaining prompts interactively rather than bypassing them for green output. A moved/unreadable fixture HEAD stops the probe without resetting it. Mocks and static checks do not establish live behavior.

Consult [`docs/maintenance.md`](docs/maintenance.md) before major tool or plugin changes, permission or bridge changes, cross-host work, `/doctor`, or work on a listed limitation or deferred item.

## Adopt

The harness is personal, and forking it means replacing a few facts rather than the structure:

- The addressee. The guidance and skills speak to `H`; the commit skill's identity check expects a GitHub no-reply address.
- The hosts. Omarchy and WSL are named in the guidance, the Makefile guards, and the ledger's host pass items; the `require-host` guards in the sibling repositories encode which machine runs which targets.
- The models. Claude Code's `model` alias and effort, the Codex template's effort, which pins no model or service tier, and OpenCode's `model` and `small_model` are each one line; `tests/config-contracts.py` holds those shapes, so a fork that pins differently relaxes its model block.
- The packages. `PACKAGES` in the Makefile and the clean script name what Stow deploys; add a package for a new tool as a directory of symlinks to `agents/.agents`.
- The credential list. It lives in three configurations, the bridges, and the scanner, and `tests/config-contracts.py` fails when they drift apart.

Everything else, the two approval/publication boundaries, the gate contract, the scripts, the reviewer bridges, and the ledger discipline, transfers as it is. [`docs/design.md`](docs/design.md) explains why each part exists.

## License

[MIT](LICENSE)
