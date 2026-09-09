# Access Policy

The comparison point for Claude Code, Codex, OpenCode, and Hermes Agent: intended authorization, implemented access, rationale, upstream semantics, and evidence. Read this before reconstructing permissions from individual files. [`AGENTS.md`](../AGENTS.md) owns invariants, [shared guidance](../agents/.agents/shared-guidance.md#safety) owns authorization, the linked configurations implement it, and [`maintenance.md`](maintenance.md) owns unresolved gaps and live revalidation evidence. [`/eyrsync`](../.agents/skills/eyrsync/SKILL.md#access-reconciliation) keeps these views aligned.

## Reading The Matrices

These are **configured baseline capabilities, not permission to use them**. They assume a trusted, non-root Git workspace on Linux/WSL, the tracked user configuration deployed, the primary agent in its normal configured mode, and no extra workspace roots, temporary grants, overrides, or symlink aliases. They are not a certification of every running session, desktop app, hook, or subprocess. Normal OS ownership and permissions still apply; no entry grants root privileges.

| Cell | Meaning |
| --- | --- |
| Allow | The described tool/profile permits this operation without a new permission decision, subject to exceptions below. |
| Auto | Claude Code's permissive auto-mode read default, not an explicit path allow. The first external-read choice can change it. |
| Review | Claude Code's classifier evaluates the action; this is neither automatic permission nor a guaranteed human prompt. |
| Ask | The tool requests native approval for the applicable subject; retained decisions and bypass modes remain tool-specific. |
| Block | A native deny or baseline sandbox restriction applies to the described surface, not necessarily every other tool surface. |
| Guarded | The managed OpenCode scratch plugin permits supported native edits only after its policy/filesystem checks. |
| M | OpenCode's native [move-destination exception](#move-destinations): a destination can miss the edit permission check. |

Read and write remain separate even when equal. Filesystem tables describe Claude Code's native file tools, Codex's sandboxed local filesystem operations, and OpenCode's native Read/Edit/Write/Apply Patch. **Do not apply their cells to arbitrary shell scripts, search results, MCP calls, or client-internal reads.** The tool-call matrix describes those differences. Credential and protected-path exceptions override ordinary-location cells.

### Workspace And Home

External columns are outside the active workspace. A sibling is not a writable workspace merely because it is under `~/Projects`. A path explicitly added as a workspace or resolved through a Stow link needs its effective rules checked again.

| Tool | Access | Workspace | Other `~/Projects` | `~/Projects/scratch` | `~/Projects/quarry` | Other Home Paths | `~/.agents/skills` | `~/.agents/hooks` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [Claude Code](#claude-code) | Read | Allow | Allow | Allow | Allow | Auto | Auto | Auto |
| Claude Code | Write | Allow, except protected | Review | Review | Review | Review | Review | Block |
| [Codex](#codex) | Read | Allow | Allow | Allow | Allow | Block, except named grants | Allow | Block |
| Codex | Write | Allow, except protected | Block | Block | Block | Block | Block | Block |
| [OpenCode](#opencode) | Read | Allow | Ask | Allow | Allow | Ask | Allow | Block |
| OpenCode | Write (M) | Allow, except protected | Ask | Ask | Ask | Ask | Ask | Block |
| [Hermes Agent](#hermes-agent) | Read | Allow | Allow | Allow | Allow | Ask outside standing roots | Allow | Block |
| Hermes Agent | Write | Allow, except protected | Ask | Ask | Ask | Ask | Block through deployed path | Block |

Codex also reads specifically named harness files, `~/.config/opencode`, `~/.local/bin`, and `~/.local/share/mise`; its [template](../templates/codex/config.toml) is the exact inventory. It has no model-facing read grant on `~/.codex/config.toml`. The client loading its own configuration or authentication is not permission for the agent to display it. All four can execute authorized skill scripts through their ordinary shell controls; a filesystem read grant does not mean a script is harmless or read-only when executed.

Quarry is the shared reference-clone root for H and skills, not scratch to discard. [Shared guidance](../agents/.agents/shared-guidance.md#safety) authorizes needed routine fetch/fast-forward refreshes of existing clones declared in the family's `references.txt`, preserving local work and refs. Those shell operations are distinct from native file-write cells: Claude Code's classifier and OpenCode's command controls still apply; Codex's ordinary profile cannot perform the external writes/network and must report that boundary. `/eyrsync` checks the family updater's dry-run before a refresh because `make refs` can also create clones or repoint remotes, effects requiring separate authorization. No clone deletion, force update, arbitrary reference-source edit or sandbox bypass follows from the location grant.

### System Directories

| Tool | Access | `/usr` | `/etc` | `/opt` | `/sys` | `/var/lib/pacman` | `/var/log`, `/mnt`, `/media` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code | Read | Allow | Allow | Allow | Allow | Allow | Auto |
| Claude Code | Write | Review | Review | Review | Review | Review | Review |
| Codex | Read | Allow | Allow | Allow | Allow | Allow | Block |
| Codex | Write | Block | Block | Block | Block | Block | Block |
| OpenCode | Read | Allow | Ask | Ask | Ask | Allow | Ask |
| OpenCode | Write (M) | Ask | Ask | Ask | Ask | Ask | Ask |
| Hermes Agent | Read | Allow | Allow | Allow | Allow | Allow | Ask |
| Hermes Agent | Write | Ask | Ask | Ask | Ask | Ask | Ask |

Codex's `:minimal` additionally supplies platform/runtime access, not a fixed universal file list or a grant on the entire machine. On the checked Linux implementation it includes existing executable/library roots and `/etc`; a sandbox-local `/proc` is also normally mounted. Do not infer that all `/proc`, `/run`, or `/dev` host resources are either readable or absent from the simplified directory table. Native Windows and other sandbox backends need their own verification.

### Temporary Directories

These cells describe ordinary non-secret files, not permission to inspect another session's scratch. An explicit `$TMPDIR` or workspace nested inside one of these roots can change Codex's effective specificity; never point it at another tool's root to gain access.

| Tool | Access | General `/tmp` | General `/var/tmp` | `$TMPDIR` | `/tmp/opencode` | `/tmp/claude-1000` |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Code | Read | Allow | Allow | Containing-path rule | Block | Allow |
| Claude Code | Write | Review | Review | Containing-path rule | Block | Review |
| Codex | Read | Allow | Allow | Allow when set | Block | Block |
| Codex | Write | Allow | Block unless also writable temp/workspace | Allow when set | Block | Block |
| OpenCode | Read | Ask | Ask | Containing-path rule | Allow | Block |
| OpenCode | Write (M) | Ask | Ask | Containing-path rule | Guarded | Block |
| Hermes Agent | Read | Allow | Allow | Containing-path rule | Block | Block |
| Hermes Agent | Write | Ask outside workspace | Ask outside workspace | Containing-path rule | Block | Block |

Claude Code's Read allow on `/tmp` covers its own UID-specific tool root but does not establish ownership of every session there. OpenCode denies external `/tmp/claude-*/**`; Codex names only `/tmp/claude-1000`, so another UID is not covered by that literal. Codex's `:slash_tmp` and `:tmpdir` are broad write capabilities, whereas guidance authorizes only caller-owned session scratch. No persistent scratch write exception is configured for `~/Projects/scratch` in any tool.

### Protected Paths

The credential inventory includes named home stores and copied stores, provider auth files, browser profiles, keyrings, shell histories, `.env`, `.env.*`, `.netrc`, `.npmrc`, `.pypirc`, `secrets/`, `auth.json`, `credentials`, `credentials.*`, the four named OpenSSH `id_*` private keys, and `*.key`, `*.pem`, `*.p12`, `*.pfx`. It is finite path matching, not content classification. `example.env` and `credentials-policy.md` deliberately do not match these names.

| Tool | Access | Named Home Credential Stores | Credential Shapes In Workspace | Copied Stores Under `~/Projects` | `.npmrc` In Another Projects Repo | Credential Shapes In General Temp/System Trees | Workspace `.git/**` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code | Read | Block | Block | Block | Block | Block | Allow |
| Claude Code | Write | Block | Block | Block | Block | Block | Block |
| Codex | Read | Block | Block for configured shapes | Block for configured inventory | Allow | No general shape mask | Allow |
| Codex | Write | Block | Block for configured shapes | Block | Block | Follows location grant | Block at baseline |
| OpenCode | Read | Block | Block | Block | Block | Block through native Read | Allow |
| OpenCode | Write (M) | Block | Block | Block | Block | Block through native edit rules | Block |
| Hermes Agent | Read | Block | Block | Block | Block | Block through native file checks | Allow |
| Hermes Agent | Write | Block | Block | Block | Block | Block through native file checks | Block for literal `.git` paths |

For Codex, workspace glob protection is bounded and applied to existing matches before command execution. General temp/system trees lack a global credential-shape mask; copied-store coverage outside `~/Projects` is not equivalent either. The `.npmrc` omission applies outside effective workspace roots, not to `~/.npmrc` or a workspace's `**/.npmrc`. These are **enforcement gaps, never authorization to access credentials**. Startup-scan failures and the revalidation trigger live in the [ledger](maintenance.md#active-limitations).

Additional persistence protection differs. Claude Code denies native edits under `~/.config/git`, and its auto-mode protected-path checks cover other execution-sensitive files. Codex inherits workspace `.git`, `.agents`, and `.codex` write protection from `:workspace`, including resolved Git directories, and explicitly makes `.git/config` and `.git/hooks` read-only. OpenCode's external-directory map blocks access under `.config/git` and the installed hook location; its native edit rules block `.git/**`. Source files in a harness checkout and installed endpoints are not interchangeable permission subjects.

## Tool Calls

Filesystem reads and writes above are only one axis. Tool availability, local execution, network access, and external effects need separate comparison.

| Tool | Native Read | Grep / Glob | Edit / Write / Patch | Shell Read And Write Operations |
| --- | --- | --- | --- | --- |
| Claude Code | Read path rules and mode | Best-effort Read-policy coverage; checks resolved search directory | `Edit(path)` covers Edit, Write, NotebookEdit; matching Read denies also block Edit/Write | Read-only built-ins/narrow allows, otherwise Review; file/redirect checks have version-dependent coverage pending ledger revalidation; arbitrary subprocess I/O is not contained |
| Codex | Local filesystem profile where supported | Local searches run under the sandbox profile | Writable-root/profile checks, protected metadata and approval boundary | Allow inside the sandbox; eligible boundary crossings go to auto-review, not a universal per-command review |
| OpenCode | `read` subject plus external-directory check | Pattern and directory checks, **no per-result Read filtering** | Shared `edit` permission plus external-directory check, except move-destination edit gap (M); managed scratch adds preflight | `bash.* = allow` with named asks/denies; recognized file commands check directories, not per-file Read/Edit; arbitrary scripts are unconfined |
| Hermes Agent | Managed task-aware path checks plus native guards | Root checks and additive native result-path filtering, after backend traversal | Every parsed native target checked; task-relative operands normalized before dispatch | Native smart review plus terminal commit gate; arbitrary Python/scripts and process stdin remain outside lexical enforcement |

| Tool | Hosted Web Reads | Shell Network Reads / Writes | MCP, Apps, Browser, Plugins | In-Tool Auditor | Sharing / Remote Control |
| --- | --- | --- | --- | --- | --- |
| Claude Code | Available through auto-mode/tool rules; no tracked domain allowlist | No tracked network sandbox; command rules/classifier apply | No blanket disable; loaded components have their own approval/execution surfaces | Read, Grep, Glob only; parent restrictions retained | Off by guidance; no blanket tracked feature disable |
| Codex | `web_search = "live"` | Block at baseline | Separate from command sandbox; apps/browser/plugin availability and permissions depend on product and loaded configuration | Not configured; full-authority verification deferred | Off by guidance; no blanket tracked feature disable |
| OpenCode | `webfetch` and `websearch` Allow | No network sandbox; command rules apply | Primary has no blanket unknown-tool/MCP deny; plugins/custom tools can execute code | Read and Glob only; tighter final-parent-policy intersection | `share = "disabled"`; other remote-control surfaces stay off by guidance |
| Hermes Agent | Native web tools retained; provider/dependency setup required | No network sandbox; native command review and managed gate apply | Native capabilities retained; each configured integration has its own authority | Not configured | Off by shared guidance; no connector/service is activated by deployment |

Web reads still send queries/URLs to a service. Network-enabled does not authorize uploads or remote mutations. No host connector inventory or account permissions are inferred here. Model-provider requests, client configuration loading, inherited environment values, hooks, plugins, and browser/app integrations are not all governed by a local filesystem profile. A native path deny does not sanitize an environment variable or every returned tool result.

### Delegation And Clients

| Tool | Ordinary Delegation | Direct Nested CLI Launches | Cross-Vendor Reviewer |
| --- | --- | --- | --- |
| Claude Code | No blanket agent/workflow deny; parent permissions and agent-specific controls apply | No blanket client deny; command rules/classifier apply | Approved `spar-codex` bridge has fixed read-only flags |
| Codex | Parent sandbox/approval controls apply; no configured read-only auditor | No named client deny; runtime, state and network can remain unavailable inside the sandbox | Codex-to-Claude route remains H-run outside the strict profile |
| OpenCode | `task` available; upstream depth 1 prevents delegates launching more delegates by default; auditor additionally denies Task | Named `claude *`, `codex *`, `opencode *` forms denied; exact version checks allowed, not a general process-containment rule | Approved `spar-claude` bridge is separate from direct client launches |
| Hermes Agent | Native delegation retained; dispatched child tools receive the plugin, with Hermes's own child restrictions | No blanket nested-client disable; guidance and terminal controls apply | Shared `spar-claude` bridge for the Astra primary |

Only the named auditor gets its special read-only cap. Do not infer those caps for general/explore agents, workflows, CLI subprocesses, or MCP-provided agents. The [spar skill](../agents/.agents/skills/spar/SKILL.md) owns bridge scope/consent; a bridge invocation is not authorization to launch an unrestricted client. Upstream [Claude subagents](https://code.claude.com/docs/en/sub-agents#permission-modes), [Codex subagents](https://developers.openai.com/codex/agent-configuration/subagents#approvals-and-sandbox-controls), and [OpenCode depth](https://opencode.ai/docs/config/#subagent-depth) define the relevant defaults.

### Consequential Actions

| Tool | Raw Commit-Producing Git | `git push`, `git clean` | Reset / Restore / Path Checkout / Branch Deletion | Git Config / Remotes | Privilege Escalation |
| --- | --- | --- | --- | --- | --- |
| Claude Code | Block by dispatched Bash gate | Block named forms | Review; explicit target instruction required by policy | Review; explicit instruction required by policy | Block named forms |
| Codex | Block by dispatched local-tool gate | Network block for push; no blanket `git clean` deny | Filesystem boundary where crossed; guidance still required inside it | Protected Git metadata and auto-review where crossed | Rejected by review policy; not a universal command-name deny |
| OpenCode | Block by dispatched Bash gate | Block named forms | Ask named forms | Ask named forms | Block named forms |
| Hermes Agent | Block by dispatched terminal gate | Block named forms | Native smart review plus explicit-instruction guidance | Native guards/review plus explicit-instruction guidance | Block named forms |

The [commit gate](../templates/hooks/commit-gate) also blocks stash mutations, including `drop`/`clear`, despite any underlying Ask/Review rule. Its literal fast-forward-only merge/pull exemptions and stash list/show exceptions do not waive other restrictions. Recognized `gh` mutation denies differ: Claude Code's extra forms go through classifier prose; OpenCode additionally denies `gh api`, auth, repository creation/deletion, workflow dispatch and other listed forms. Codex has no matching command deny inventory; the sandbox, auto-review, gate and guidance are distinct layers.

These are bounded command-form checks, not semantic interception of every script. Claude Code's hook matches `Bash`, OpenCode's plugin matches `bash`, and Codex dispatches its configured `PreToolUse` hook on supported local tools. Hook loading/trust, errors/timeouts, alternate shell tools, and input to an already-running command need their own evidence. The exact-candidate [commit](../agents/.agents/skills/commit/SKILL.md) and [publication](../agents/.agents/skills/publish/SKILL.md) workflows remain mandatory even when a command could technically execute: H approves the candidate and runs the reviewed push. H's authorization never licenses the agent to evade a tool denial.

## Implementation And Semantics

### Claude Code

Implementation: [`settings.json`](../claude-code/.claude/settings.json), specifically `permissions.defaultMode`, `allow`, `deny`, `autoMode`, and the `hooks.PreToolUse` Bash matcher; [`auditor.md`](../claude-code/.claude/agents/auditor.md).

Deterministic precedence is deny, then ask, then allow, not most-specific or last-rule-wins. `Read(//...)` is filesystem-absolute; `Read(~/...)` is home-relative. `Edit(path)`, not `Write(path)`, owns path-based modification rules. No tracked `permissions.ask`, external-read fence, additional working directories, or sandbox is configured. Auto-mode ordinary reads and non-protected workspace edits need not reach the classifier. Its custom `$defaults` entries retain upstream classifier defaults but do not make classifier prose a native file deny.

External reads without an explicit allow use the auto-mode default. The first interactive external read can ask H to keep allowing, start blocking, or ask next time; saved choices and foreground/headless behavior matter. The matrix does not assume an answer from H's private session state. Protected writes and other reviewed actions can be blocked or escalated to H; Review is not synonymous with Ask. Current official sources: [permissions](https://code.claude.com/docs/en/permissions#read-and-edit), [auto-mode decision order and external reads](https://code.claude.com/docs/en/permission-modes#how-the-classifier-evaluates-actions), [classifier configuration](https://code.claude.com/docs/en/auto-mode-config), [tools](https://code.claude.com/docs/en/tools-reference), [sandbox scope](https://code.claude.com/docs/en/sandboxing), and [hooks](https://code.claude.com/docs/en/hooks).

### Codex

Implementation: [`templates/codex/config.toml`](../templates/codex/config.toml), specifically `default_permissions`, `permissions.trusted-workspace`, `approval_policy`, `approvals_reviewer`, `auto_review.policy`, `web_search`, `features`, and `hooks.PreToolUse`. This template is not the credential-bearing host-local config.

The profile extends `:workspace`, denies `:root`, reads `:minimal` plus named roots, writes `:workspace_roots`, `:tmpdir`, and `:slash_tmp`, and disables command network. More-specific paths override broader ones; equal-target precedence is deny, write, read, not TOML order. Runtime workspace roots and `$TMPDIR` must be considered before claiming a literal deny covers every overlap. Linux/WSL glob expansion is a pre-command snapshot with `glob_scan_max_depth = 64`, not continuous content inspection.

`on-request` with `auto_review` changes who evaluates eligible approval requests, not what the baseline sandbox permits. The custom reviewer policy allows necessary turn-scoped non-secret reads of directed context and rejects session grants, external writes, credentials, privilege, destruction, uploads, remote mutations, and bypasses. It does not review every already-permitted action. Its local text **replaces**, rather than appends to, the configurable upstream reviewer policy; built-in review instructions remain. Rejection of external writes is stricter than guidance allowing an explicitly named external edit, so authorization alone may not make that operation available here.

Current official sources: [permission profiles, matching and scope](https://developers.openai.com/codex/permissions), [auto-review](https://developers.openai.com/codex/sandboxing/auto-review), [configuration reference](https://developers.openai.com/codex/config-file/config-reference), [hooks](https://developers.openai.com/codex/hooks), and [subagents](https://developers.openai.com/codex/agent-configuration/subagents). Version-specific implementations: [Linux runtime roots and glob expansion](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/linux-sandbox/src/bwrap.rs), [protected metadata](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/protocol/src/permissions.rs), and [review-policy replacement](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/core/src/guardian/prompt.rs).

### OpenCode

Implementation: [`opencode.json`](../opencode/.config/opencode/opencode.json), specifically `permission.read`, `edit`, `bash`, `external_directory`, `webfetch`, `websearch`, `agent.auditor`, and `share`; [auditor](../opencode/.config/opencode/plugins/auditor-permissions.js), [scratch](../opencode/.config/opencode/plugins/scratch-permissions.js), and [commit-gate](../opencode/.config/opencode/plugins/commit-gate.js) plugins.

Last matching rule wins. Read/edit subjects are relative to the Git worktree; external subjects name a directory or a file's parent plus `/*`. A normal Git worktree is inside the boundary even when the launch directory is a subdirectory. The six explicit preapprovals are `/tmp/opencode/*`, `~/Projects/scratch/**`, `~/Projects/quarry/**`, `~/.agents/skills/**`, `/usr/**`, and `/var/lib/pacman/**`, before sensitive/other-session denies. Upstream can also append a tool-output location grant. An external grant covers location, not read-only use.

Native edits outside a non-root Git worktree match `../* = ask`; persistent scratch and quarry get no edit exception. **When a non-Git project uses worktree `/`, that rule does not match.** The external-directory check still applies outside the launch directory, but preapproved locations can then lack the additional edit ask. The guarded scratch plugin checks supported targets before native work, rejects existing symlink/hardlink escapes and Move-to patches, and does not prove session ownership or prevent filesystem races.

### Move Destinations

**M qualifies every OpenCode write row:** the cell describes a target submitted to the relevant permission check, not a guarantee about every native move destination. In [Apply Patch 1.18.29](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/apply_patch.ts), `Move to` checks the destination's external directory but submits only the source path to `edit`. Consequently, a destination under preapproved persistent scratch can miss the additional edit Ask even in a normal Git worktree; destination-only credential or `.git` edit denies can also be missed. Directory denies still apply where the external check encounters them. This is a native dispatch gap, separate from arbitrary-shell limitations.

The managed scratch plugin refuses moves involving its guarded `/tmp/opencode` targets; it is **not a general move-destination guard**. Use separately checked Add/Delete operations for authorized moves, never the unchecked destination as a route around approval or a deny. No credential, Git-internal, or other protected target is authorized by this limitation. The [ledger](maintenance.md#active-limitations) owns source/runtime revalidation; the matrix does not claim an exploit probe or a fix.

`always` accepts tool-proposed session patterns, not necessarily the single file: external approval spans the displayed directory across tool access; native read/edit proposes `*`. Global auto-approval would accept asks, so it is not part of the normal baseline. The primary's permissive tools do not acquire the auditor's read-only restrictions. Current official sources: [permissions](https://opencode.ai/docs/permissions/), [tool-to-permission mapping](https://opencode.ai/docs/tools/), [configuration precedence](https://opencode.ai/docs/config/#precedence-order), [agents](https://opencode.ai/docs/agents/), and [plugins](https://opencode.ai/docs/plugins/). Version-specific subjects and coverage: [Read](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/read.ts), [Edit](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/edit.ts), [Grep](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/grep.ts), [Glob](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/glob.ts), and [external boundary](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/external-directory.ts).

## Decisions And Parity

### Hermes Agent

Implementation: [`templates/hermes/config.yaml`](../templates/hermes/config.yaml), the opaque [reconciler](../scripts/reconcile-hermes-config.py), and [`hermes/.hermes/plugins/eyragents`](../hermes/.hermes/plugins/eyragents/__init__.py). Checked interface: installed mise/PyPI **0.19.0**, 2026-09-09. [Upstream release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.7.20), [hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks), [configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration), and [skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) provide public context; newer online interfaces do not supersede installed-source evidence.

The general-purpose profile keeps native tools and learning. Shared guidance is a stable environment hint, not a replacement for `SOUL.md`; repository-owned skills are external libraries, and `skill_manage` may mutate only its own local skill targets. Hermes-local memory and skills are runtime-owned exceptions to the ordinary repository edit boundary. Native file writes to those locations still follow the file-tool approval path; their native learning tools use their own ownership rules.

The plugin uses `pre_tool_call`, request middleware and a hard-denial execution backstop. Task-relative read/search/patch operands become absolute before v0.19's shared-environment backend can resolve them against another task's cwd. Every V4A operation, including both `Move File` endpoints, is checked. A narrow composition of `tools.file_tools.get_read_block_error` adds the credential predicate to native returned-search-path filtering. That happens after backend traversal; it is **not proof the backend never read a matching file**, and native counts/errors can disclose metadata. The model must still obey the secret-material rule.

External native reads outside standing roots and writes outside the task's current repository request scoped Hermes approval. Its native approval system may retain decisions or bypass asks in YOLO mode; deployed `smart` mode is not YOLO. Protected native paths and terminal gate refusals are blocks, with an execution middleware backstop against an earlier plugin approval. Later hostile plugins, direct handler calls and client configuration can defeat these controls; safe mode or failed plugin import leaves upstream execution unguarded. Verify discovery and start a fresh session after changes.

The local backend is **not a sandbox**. `execute_code` RPC calls to Hermes tools, normal delegated tools and permitted background-review tools reach normal dispatch. Direct Python I/O, subprocesses, shell scripts, native tool-internal subprocesses and bytes delivered to an existing interactive process do not become additional terminal-hook calls. Secret path checks do not sanitize arbitrary tool results or environments. Literal `.git` write denial is not protection for every separately located Git directory. Symlink/metadata races remain. Remote path semantics, alternate Codex app-server execution, and independently configured profiles need separate verification; unsupported remote native-path checks refuse rather than assume local protection.

`~/.hermes/config.yaml` can contain provider/MCP credentials. Primary native policies, reviewer bridges and the payload scanner protect it; the deployment reconciler processes it opaquely and reports structural results. Session stores and other tools' temporary roots remain outside authorized research. These layers preserve shared intent with documented limits, not identical containment across tools.

Parity means preserving the same authorized work and safety intent where each tool can enforce it, **not broadening the stricter tool until every cell matches**. A technical gap is not an approved exception. Material changes to access, oversight, or useful capabilities require H's decision; this document itself grants nothing.

| Area | Decision And Rationale | Implementation / Current Difference | Status |
| --- | --- | --- | --- |
| Ordinary editing | Autonomous work inside the requested repository; explicit target authorization outside it | Workspace writes permitted, with tool-specific protected files; Codex reviewer rejects external writes even if separately authorized | Shared intent; enforcement differs |
| Reference reads | Standing non-secret reads under Projects, temp, and named OS trees reduce routine interruptions | Claude Read allows and Codex read-only grants; OpenCode preapproves quarry but keeps other Projects and mutable system/general-temp locations at Ask because its grants are not read-only | Deliberate difference |
| Established OpenCode references | Preapprove `/usr`, Pacman metadata and `~/Projects/quarry` for diagnostics, research and skill dependencies without granting every external location | Named location exceptions alongside skill and scratch roots; neither native grants nor OS ownership are a complete read-only guard | Deliberate tradeoff |
| Quarry maintenance | Needed routine fetch/fast-forward refreshes of existing declared reference clones are authorized with preservation checks, not handed back merely because the root is external | Family updater dry-run must exclude unapproved clone creation/remote changes; Claude/OpenCode retain command controls and Codex's network/write restriction remains | Authorized workflow; enforcement differs |
| Home and scratch | Other home context needs H's direction; only session-owned scratch may be modified without a named external-edit request | Claude auto reads and Codex temp writes exceed that authorization; persistent scratch has no special write grant | Guidance narrower than capability |
| Credential material | Never read, write, or expose it; path templates do not authorize real secrets | Native denies aligned by inventory, but Codex scan gaps, Claude indirect subprocesses, and OpenCode search/shell gaps remain | Incomplete enforcement; ledger owns follow-up |
| Git and publication | Protect code-executing metadata and require exact candidate/push review | Native metadata restrictions, lexical gate, receipts, and approval procedure complement one another | Shared intent; no arbitrary-script containment |
| Web and extensions | Keep primary research and H's chosen app/extension capabilities; forbid unauthorized remote effects | Codex command network off while hosted web/apps remain separate; Claude/OpenCode shell network not sandboxed | Deliberate surface differences; actual host inventory unverified |
| Reviewers | Read-only review should not gain primary-agent write/network/delegation authority | Claude auditor Read/Grep/Glob; OpenCode Read/Glob with inheritance checks; Codex auditor deferred; bridge launch flags are separately fixed | Partial parity, not a primary-policy copy |

The durable rationale is [enforce, then instruct](design.md#enforce-then-instruct). Shared guidance forbids secret access even where Claude's classifier text says a named credential-file request can clear a soft block; that text neither overrides native denies nor the stricter guidance. Custom reviewer-policy replacement, hook-surface coverage, and unresolved parity choices are tracked in the ledger, not silently repaired to match this table.

## Evidence And Refresh

The [eyrsync source table](../.agents/skills/eyrsync/SKILL.md#sources) owns the four-tool reference strategy: Codex/OpenCode/Hermes client source and Claude Code's public release/support material, plus official docs and scoped runtime evidence for every tool. A maintained clone does not by itself make any matrix cell source-verified or live-verified. Version-specific docs/release disagreements, including Claude's Bash Read-rule reversals, stay explicit in the ledger until checked.

Source/configuration reconciliation checked **2026-09-06**. The installed mise inventory and latest stable public releases at that check agreed; this does not establish which binary or settings an already-running session loaded.

| Tool | Checked | Installed Inventory | Public Stable Release | Evidence Boundary |
| --- | --- | --- | --- | --- |
| Claude Code | 2026-09-06 | 2.1.263 | [2.1.263](https://github.com/anthropics/claude-code/releases/tag/v2.1.263) | Tracked config plus current official semantics; no fresh classifier/host-policy certification |
| Codex | 2026-09-06 | 0.153.4 | [0.153.4](https://github.com/openai/codex/releases/tag/rust-v0.153.4) | Template plus official docs/release source; no host config or account inventory read |
| OpenCode | 2026-09-06 | 1.18.29 | [1.18.29](https://github.com/anomalyco/opencode/releases/tag/v1.18.29) | Tracked config, plugins and permission call sites; post-restart quarry Read/Glob succeeded with H-confirmed no prompts, bounded live evidence in ledger |
| Hermes Agent | 2026-09-09 | 0.19.0 through mise/PyPI | [PyPI 0.19.0](https://pypi.org/project/hermes-agent/0.19.0/); GitHub latest 0.21.1 is a different channel | Installed source and synthetic full-dispatch refusal before backend calls; live Astra status/replies, guidance/skills, reads, learning, explicit-ID resume, child-result delivery and approval timeout denial. Effective effort and WSL remain unknown; model refusal alone is not hook evidence |

[`tests/config-contracts.py`](../tests/config-contracts.py) checks configured inventory and modeled path cases. [Auditor](../tests/opencode-auditor.sh) and [scratch](../tests/opencode-scratch.sh) tests check plugin transformations and fixtures. [Gate](../tests/commit-gate.sh) and [governance](../tests/commit-governance.py) tests cover their respective command/receipt boundaries. Passing these is not proof that all four upstream runtimes enforce every cell. [The canary](../scripts/canary.sh) is behavioral smoke; a model saying it refused a read is not independent denial evidence.

For actual effective access, account for configuration precedence, launch mode, workspace roots, `$TMPDIR`, session approvals, tool/plugin inventory, hook trust and host backend. Trusted project and CLI/session settings can change defaults; Codex legacy sandbox settings can select a different permission system. Use safe metadata and synthetic non-secret fixtures, not raw host configuration dumps, credentials, environment dumps, or other-tool session records. An unavailable check stays unknown.

Every relevant `/eyrsync` pass reconciles **decision -> matrix -> implementation -> current official semantics -> verification evidence** for all four tools, with read and write kept distinct. Check release notes for changed matchers, defaults, scopes and newly exposed surfaces, not merely renamed keys. Update the current rows/source baseline only to the extent checked; keep per-tool older dates or explicit unknowns when a check is blocked. Preserve unresolved drift with an owner and concrete revalidation trigger in the ledger. Do not change policy just to make a matrix cell or canary green.
