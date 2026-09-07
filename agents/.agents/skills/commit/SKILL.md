---
name: commit
description: Stage, review, and commit one exact atomic change with H's approval.
---

# Commit

## Message format

```
<type>[(scope)]: <subject>

[optional body]

Co-Authored-By: <official display name of the active model> <provider no-reply address>
```

- Types: `feat`, `fix`, `docs`, `refactor`, `style`, `test`, `chore`. Add a scope when the change is localized to one component.
- Subject: imperative mood, lowercase, 50 characters max. No ticket numbers, audit numbers, or session identifiers.
- Trailer: resolve the display name from the active model identifier at commit time and keep every qualifier. Anthropic models use `<noreply@anthropic.com>`; OpenAI models use `OpenAI <display name> <noreply@openai.com>`. Never hard-code a model.

## Before staging

For substantial work, re-read the checkpoint's atomic change map established before implementation. Reconcile actual changes with it: each candidate contains one independently valid behavior with its tests and documentation, not one delegate's output. Assign shared-file hunks explicitly and keep runtime/configuration dependencies together. If the map is missing, stop and establish it before staging; do not treat a full-worktree gate pass as proof that an extracted candidate works. Cross-repository atomicity means reviewed companion commits and exact-pair verification, not one Git transaction. The map itself is not approval.

1. Classify untracked files (`git ls-files --others --exclude-standard`) as intended new files or session scratch, and account separately for the active ignored workstream artifacts. The primary removes its own no-longer-needed checkpoint, `audit/`, and `spar/` files under shared guidance's lifecycle; user-created or unknown untracked files still need H's approval. Retain evidence needed for the candidate and respect any previously approved artifact disposition. Approval/publication records are not workstream scratch.
2. Update documentation whose commands, paths, workflows, or listings changed, keeping each fact in its canonical owner. Create no documentation file unasked.
3. Run the repository's gates, fixing and rerunning until each passes: `make lint` and `make check` when defined, else `npm run check`; then `make restow` and `make verify` when defined, else `npm run verify`. Combine compatible Make targets in one invocation to avoid repeating prerequisite suites. Wrong-host or wrong-clone refusals are skipped with their reason, never bypassed. Elsewhere use the documented checks. Record commands/results, source or candidate identity, and relevant runtime/host inputs in the checkpoint or a scanned review brief. Reuse same-workstream results only after re-reading the original passing evidence and establishing the exact tested contents and relevant context are unchanged. A receipt, a new `--no-gates` brief, or tracked-file equality alone is not proof; unknown inputs, untracked contents, unverified symlink targets, or source changes forbid reuse. Verify deployed state after deployment; an earlier host pass does not cover changed links/configuration.
4. Review is recommended before the packet, through the `spar` skill across vendors or the `auditor` agent inside the tool, where outside review can change the outcome; the repository's `AGENTS.md` may name the paths where it earns its cost. It is never mandatory. Carry any verdict into the packet.

## Candidate

1. Compose the message in session scratch. `~/.agents/skills/commit/scripts/commit-candidate --message-file <file> -- <path>...` records the prepared index without staging. For whole files entirely owned by this change, add `--stage`; it stages only named literal paths and refuses partially staged mixed files before modifying the index. For mixed files, stage only intended hunks with `git apply --cached` on a reviewed patch, then use default record-only mode, or defer to H. Never use `git add -A` or `git add .`, or stage credential-shaped paths. Actual scanner/identity findings create no new receipt and must be resolved, not bypassed; post-staging refusal can leave the index staged, never silently restored.
2. Capture `candidate-id`, tree, parent, branch, message, and scan state. The immutable digest identifies this exact receipt; multiple receipts may coexist. Screen staged paths, identities, message, and privacy findings for the declared audience, world-readable by default: machine/user identifiers, local paths, security posture, correspondence, and session metadata. `scan=partial` binds unscanned object IDs, sizes, reasons and tree/path locations: show metadata only and require H's inspection of those exact objects in a separate pane before approval. Never call a partial scan clean or treat sensitive findings as manual-inspection exceptions.
3. Ensure gates cover the candidate's exact contents. A different working tree is not a superset or an attestation of the index; validate the staged snapshot in an appropriate disposable context without deploying it, or defer the mixed candidate. Present a compact packet: repository and `candidate-id`, stat, full message, tree/parent/branch, gate results and tested-state match, complete/partial scan and required inspection, privacy review, reviewer verdict when one ran, and scratch disposition. Do not paste the full diff or repeat the review-key table unless H asks. Use the interactive selector with `Commit and resume` first and `Commit and pause` second, naming the exact repository/ID and any required inspection. Only a selected option authorizes that candidate. Free text is a revision, rejection, or question, never approval: answer and re-present the same packet/selector; revisions require a new receipt, affected gates, and a packet stating what changed.

Any change to content, message, audience, or scratch disposition after approval requires a fresh receipt and approval. `commit-candidate --show ID` displays an exact receipt; `--clear ID` rejects a ready receipt without deleting it or changing the index/worktree. Reject superseded receipts on H's revision/rejection. Unstaging with `git restore --staged -- <paths>` still requires H's instruction and must not touch unrelated hunks. A checkpoint may record IDs but never substitutes for approval.

## Review cheat sheet

Reference on request, not repeated in normal packets. In a separate Neovim pane, open a file or select a Neo-tree item in the candidate's repository. The family Neovim configuration resolves the Git-review mappings from that context without a manual directory change; stock configurations may still require launching `nvim .` from the repository root. Review the staged changes, not merely the mixed working file:

| Keys | Action |
|---|---|
| `<Space>gd` | open tracked staged and unstaged hunks |
| `<Space>gs` | open Git Status for intended untracked files |
| `<M-w>` | cycle the input, hunk list, and preview panes |
| `<C-n>` `<C-p>` or arrows | move between hunks; the preview follows |
| `<M-p>` | toggle the preview |
| `<M-m>` | maximize or restore the active pane |
| `<Enter>` | open the selected file and close the picker |
| `<Space>sR` | resume the picker after opening a file |
| `<Esc>` | close without opening |
| avoid `<Tab>` and `<C-r>` | they stage and restore |

Terminal fallback: `git -C "/path/to/candidate-repository" diff --cached --stat`, `git -C "/path/to/candidate-repository" diff --cached`, and `git -C "/path/to/candidate-repository" diff --cached -- path/to/file`. Replace the quoted repository path with the exact candidate root. These commands do not change the editor or shell cwd.

## Commit

1. Run `~/.agents/skills/commit/scripts/commit-apply ID` with the exact approved ID and the same record root. It verifies the receipt digest and current index/parent/branch/effective identity, commits through an isolated index with normal hooks, and validates the actual tree, complete parent list, message, identities, and branch position. The original index/worktree is never restored or overwritten. Compensation can reject only this invocation's uniquely identified created commit with an exact compare-and-swap; ambiguous evidence or moved checkout/tip stays untouched for H. On any refusal or mismatch, report the outcome and stop; never amend, reset, change branches, or bypass hooks to repair it. Raw commit-producing Git commands H wants run are H's own through `!`; the shell-text hook is a guardrail, not containment of arbitrary scripts.
2. Report the hash and title. `Commit and resume` continues the request's authorized work, including its remaining commits and repositories; when none remains, load the `publish` skill and present every push the request produced together, one per repository with a configured upstream or a destination H named, joined into one command line as the publish skill describes, without stopping. Present a push earlier only when a later step depends on it having landed. `Commit and pause` stops for discussion.
