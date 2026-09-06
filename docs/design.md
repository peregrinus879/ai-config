# Design

`AGENTS.md` states the invariants. This note gives the reasons, so a reader can judge whether the same shape fits their own setup.

## Two interventions

The normal trusted-repository workflow has two human boundaries: approving one exact staged candidate, and running the reviewed push command. Ordinary edits remain autonomous; ambiguous, destructive, or unsupported operations still stop for H. A request spanning repositories presents their push commands together without merging repository ownership.

Immutable candidate and publication receipts make those boundaries explicit rather than relying on a replaceable latest record. SHA-256 IDs bind the exact candidate or destination scope, while lifecycle status changes separately. Prepared-index recording preserves mixed hunks; whole-file staging is an explicit `--stage` choice. Apply uses a disposable index with normal hooks and checks the resulting commit. Compensation may compare-and-swap only its uniquely identified created commit back to the recorded sole parent; unexplained branch or checkout movement is preserved for H, never reset. Private permissions and cooperating-operation locks support governance, not same-user isolation. A receipt is neither approval nor evidence that worktree gates tested a different index tree.

Publication review covers raw new-commit metadata, explicit per-parent merge patches, the flat diff, and complete newly reachable text. Tip-only or addition-only scans miss merge resolutions and transient disclosures. Unscannable objects remain explicit, digest-bound human-inspection obligations rather than being silently accepted or making ordinary asset work impossible. Normal pre-push hooks remain enabled and fingerprinted for review. Sensitive/identity findings, unsafe hook sources, unsupported options/helpers and missing baselines still refuse. The binding resolves one endpoint and retains an H-run preflight, exact-base lease and incidental tag/submodule suppression; the push uses the configured remote name to preserve Git tracking and hook arguments. Preflight and push are separate processes, not atomic protection against adversarial changes. Remote observation, local tracking, CI and deployment are separate facts.

## Enforce, then instruct

Rules live at the lowest layer that can hold them. A sandbox constrains the surfaces it actually covers; a permission rule reaches only the subjects its tool checks; hooks see only dispatched calls. Scripts make a procedure repeatable across models and testable in CI; prose states intent and covers what lower layers cannot express. The commit gate rejects parsed commit-producing shell forms and ambiguous ff-only exemptions, but is not containment of arbitrary scripts or hostile repository configuration. The skill owns approval procedure, which a shell hook cannot observe.

## One trust model, three enforcement points

The three tools enforce one policy to different depths, and the configuration says so instead of pretending otherwise. Claude Code has deterministic allow and deny rules plus an auto-mode classifier that judges everything else against written rules. Codex has an OS sandbox with the filesystem root denied and command network off, so its filesystem and command-network boundary holds even when the model is wrong, while the web and app surfaces it keeps are the author's choice, named in `AGENTS.md`. OpenCode has lexical rules and no sandbox, so its rules are guardrails against mistakes, not containment. The same list of credential stores and Git internals is applied in each, and a test keeps the three lists aligned. Reading is open across the author's own repositories under `~/Projects`, the temp roots, and the host's system trees in every tool, each tool denied the other tools' session state under `/tmp`, because a harness that cannot see the sibling repositories or the host's defaults cannot keep them consistent; the file tools keep denying the credential shapes and store copies there, with the exceptions `AGENTS.md` records, and `AGENTS.md` names what each tool cannot enforce.

## Read-only cross-vendor review

A second opinion is worth most when it comes from a different model family that reads the same files. The bridges give one read-only, offline, single-turn reviewer with no write, web, plugin, or subagent surface, launched from a scrubbed environment under a hard timeout. Hard-coded flags prevent callers from extending that authority. Unset repository consent permits review; a configured value must be literal `true`, so empty or malformed opt-outs cannot become accidental disclosure grants. A finite scanner supports, but does not replace, that disclosure decision.

Temporary review artifacts belong to a private caller-selected `TMPDIR`, not the whole temp tree. Scanned artifacts are inlined, separating broad non-secret diagnostic reads from artifact disclosure and eliminating any reviewer scratch-write need. The scanner's `--` separator prevents artifact names from becoming root options. Safe returned provenance reports effective model, effort, tier, and client version only where exposed; `unknown` is more useful than asserting a configured preference was used.

The in-tool auditor roles remain separately configured. Review is recommended where it earns its cost, not mandatory for every trivial edit.

## One neutral source

Guidance and skills live once, under `~/.agents`, the home of the Agent Skills format. Each tool reads through its own mechanism, and each tool-side file carries the name that tool documents: Claude Code's user instruction file and skill entries hold symlinks, Codex's global instructions file is a symlink and its skill discovery is native, OpenCode's config names the guidance and the skills path. Skill executables live in each skill's `scripts/` directory, where the Agent Skills specification puts them. Adding a tool means adding a package of symlinks, and a tool adopting the standard means deleting one.

## The gate contract

Skills read a target contract instead of per-repository prose: `lint` and `check` are the repository checks, `restow` and `verify` the host verification, `verify-published` the post-push check. A repository declares a gate by defining the target, host-bound targets refuse on the wrong host or clone, and Make targets and npm scripts of the same name are equivalent. The commit skill therefore needs no knowledge of any repository.

Combine compatible Make goals so prerequisites run once. Reuse elsewhere is conditional on re-reading original passing evidence and checking exact source and relevant context, not a generic persistent cache. Review-brief source/index fingerprints expose drift and unsupported inputs without staging or claiming Git-tree equality; runtime, ignored dependencies and host state still need independent validation. Failed gates keep useful scanned diagnostics but return failure; plan-only briefs never run gates.

## Two hosts

The harness deploys with GNU Stow without directory folding, so managed parents stay real directories that tools may write into and only leaf files are links; each skill directory under `~/.agents/skills` is the one exception, linked whole, because Codex's loader follows directory links and skips file links. A change that alters deployed state is applied on the host where it is made, and the same commit adds a host pass item to the ledger with the exact steps for the other host; the agent runs the item in the next session there and deletes it. The fixtures prove the hook command, the payload, and the plugin call; only a real tool proves its own dispatch, so `make canary` runs each tool once after a deploy and asserts what the harness promises.

## The repository is the record

Durable decisions live in `AGENTS.md`, unresolved ones in the maintenance ledger, and provenance in Git history. Assistant memory is a single-device cache that holds pointers at most, because the author works across machines and the memory does not travel. Dated evidence in the ledger names its revalidation trigger, so a fact is either current or scheduled to be rechecked.

The canonical [Workstream Checkpoints](../agents/.agents/shared-guidance.md#workstream-checkpoints) rule adds compact, primary-owned, gitignored `.eyr-plans/<workstream>.md` milestones for substantial work. Its atomic change map comes before implementation/delegation so parallel work does not create an inseparable final diff: behavior, tests and docs form the unit, with dependencies and shared hunks assigned explicitly. Prospective candidate checks validate each unit, not merely the integrated worktree. Re-reading on resume, compaction, and handoff makes local continuity explicit without a new skill or docs framework. A completed checkpoint remains local; session scratch is removed. Neither checkpoint persistence nor reviewer agreement authorizes a commit, and ignored state is not cross-machine transport.

## Effort and models

Each tool runs its strongest model at the highest persistent effort, because the cost of a wrong change to live configuration exceeds the cost of tokens. Lightweight tasks that tools delegate, such as titles and summaries, go to a smaller model where the tool offers that setting. Where a tool offers a moving alias or a catalog default, the harness names it, so a new generation arrives without an edit, accepting that a vendor default tracks the vendor's choice rather than a named strongest model and recording where that choice is observed; where it offers only concrete ids, the pin carries its revalidation trigger in the ledger.
