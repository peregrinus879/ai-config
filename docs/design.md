# Design

`AGENTS.md` states the invariants. This note gives the reasons, so a reader can judge whether the same shape fits their own setup.

## Two interventions

Every change reaches the world through exactly two human actions: approving one exact staged candidate, and running one push command. Everything before the first is the agent's work, verified by the repository's own gates; everything between them is review; everything after the second is verification. Two fixed points keep the human in control without turning the human into the pipeline. A request that spans several repositories still ends with one push command per repository, presented together.

## Enforce, then instruct

Rules live at the lowest layer that can hold them. Permission rules and sandboxes are deterministic; a sandbox holds against a prompt-injected session, and a permission rule holds as far as its matcher reaches, so a path rule on a file tool contains and a text rule on a shell command does not; hooks are deterministic but see only what the tool shows them; scripts make a procedure repeatable across models and testable in CI; prose states intent and covers what the lower layers cannot express. The commit gate is the worked example: the deny on pushes is a permission rule, the "one exact candidate" rule is a hook plus a record on disk, the packet is a script's output, and the skill says when to run which.

## One trust model, three enforcement points

The three tools enforce one policy to different depths, and the configuration says so instead of pretending otherwise. Claude Code has deterministic allow and deny rules plus an auto-mode classifier that judges everything else against written rules. Codex has an OS sandbox with the filesystem root denied and command network off, so its filesystem and command-network boundary holds even when the model is wrong, while the web and app surfaces it keeps are the author's choice, named in `AGENTS.md`. OpenCode has lexical rules and no sandbox, so its rules are guardrails against mistakes, not containment. The same list of credential stores and Git internals is applied in each, and a test keeps the three lists aligned. Reading is open across the author's own repositories under `~/Projects`, the temp roots, and the host's system trees in every tool, each tool denied the other tools' session state under `/tmp`, because a harness that cannot see the sibling repositories or the host's defaults cannot keep them consistent; the file tools keep denying the credential shapes and store copies there, with the exceptions `AGENTS.md` records, and `AGENTS.md` names what each tool cannot enforce.

## Read-only cross-vendor review

A second opinion is worth most when it comes from a different model family that reads the same files. The bridges give one read-only, offline, single-turn reviewer with no write, web, plugin, or subagent surface, launched from a scrubbed environment under a hard timeout. Every flag is hard-coded so a caller cannot weaken the reviewer, and a repository that must not reach the other vendor opts out with one Git setting the bridges honor. The same adversarial loop runs inside each tool as the read-only `auditor` agent, from a fresh context, with one shared charter. Review is recommended before a plan is approved and after implementation, and the permission files, the gate, and the bridges are where it earns its cost; nothing makes it mandatory, because a required review is a tax on trivial edits and teaches the agent to route around it.

## One neutral source

Guidance and skills live once, under `~/.agents`, the home of the Agent Skills format. Each tool reads through its own mechanism, and each tool-side file carries the name that tool documents: Claude Code's user instruction file and skill entries hold symlinks, Codex's global instructions file is a symlink and its skill discovery is native, OpenCode's config names the guidance and the skills path. Skill executables live in each skill's `scripts/` directory, where the Agent Skills specification puts them. Adding a tool means adding a package of symlinks, and a tool adopting the standard means deleting one.

## The gate contract

Skills read a target contract instead of per-repository prose: `lint` and `check` are the repository checks, `restow` and `verify` the host verification, `verify-published` the post-push check. A repository declares a gate by defining the target, host-bound targets refuse on the wrong host or clone, and Make targets and npm scripts of the same name are equivalent. The commit skill therefore needs no knowledge of any repository.

## Two hosts

The harness deploys with GNU Stow without directory folding, so managed parents stay real directories that tools may write into and only leaf files are links; each skill directory under `~/.agents/skills` is the one exception, linked whole, because Codex's loader follows directory links and skips file links. A change that alters deployed state is applied on the host where it is made, and the same commit adds a host pass item to the ledger with the exact steps for the other host; the agent runs the item in the next session there and deletes it. The fixtures prove the hook command, the payload, and the plugin call; only a real tool proves its own dispatch, so `make canary` runs each tool once after a deploy and asserts what the harness promises.

## The repository is the record

Durable decisions live in `AGENTS.md`, unresolved ones in the maintenance ledger, and provenance in Git history. Assistant memory is a single-device cache that holds pointers at most, because the author works across machines and the memory does not travel. Dated evidence in the ledger names its revalidation trigger, so a fact is either current or scheduled to be rechecked.

The canonical [Workstream Checkpoints](../agents/.agents/shared-guidance.md#workstream-checkpoints) rule adds compact, primary-owned, gitignored `.eyr-plans/<workstream>.md` milestones for substantial work. Its atomic change map comes before implementation/delegation so parallel work does not create an inseparable final diff: behavior, tests and docs form the unit, with dependencies and shared hunks assigned explicitly. Prospective candidate checks validate each unit, not merely the integrated worktree. Re-reading on resume, compaction, and handoff makes local continuity explicit without a new skill or docs framework. A completed checkpoint remains local; session scratch is removed. Neither checkpoint persistence nor reviewer agreement authorizes a commit, and ignored state is not cross-machine transport.

## Effort and models

Each tool runs its strongest model at the highest persistent effort, because the cost of a wrong change to live configuration exceeds the cost of tokens. Lightweight tasks that tools delegate, such as titles and summaries, go to a smaller model where the tool offers that setting. Where a tool offers a moving alias or a catalog default, the harness names it, so a new generation arrives without an edit, accepting that a vendor default tracks the vendor's choice rather than a named strongest model and recording where that choice is observed; where it offers only concrete ids, the pin carries its revalidation trigger in the ledger.
