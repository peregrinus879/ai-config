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

1. Classify untracked files (`git ls-files --others --exclude-standard`) as intended new files or session scratch. Propose a disposition for scratch; never delete an untracked file without H's approval.
2. Update documentation whose commands, paths, workflows, or listings changed, keeping each fact in its canonical owner. Create no documentation file unasked.
3. Run the repository's gates, fixing and rerunning until each passes: the repository checks, `make lint` and `make check` when the Makefile defines them, else `npm run check` when the package defines it; then the host verification, `make restow` and `make verify` when defined, else `npm run verify`. A target that refuses because this is not its host or its deployed clone is skipped with that reason. The contract covers H's repositories; elsewhere run the checks the project documents.
4. Review is recommended before the packet, through the `spar` skill across vendors or the `auditor` agent inside the tool, where outside review can change the outcome; the repository's `AGENTS.md` may name the paths where it earns its cost. It is never mandatory. Carry any verdict into the packet.

## Candidate

1. Compose the message in the session scratch directory, then run `~/.agents/skills/commit/scripts/commit-candidate --message-file <file> -- <path>...`. The script validates the message, confirms the no-reply identity, refuses an index that already holds changes outside the named paths, stages exactly those paths, runs the payload scanner over the staged diff, screens added lines for identifiers, records the candidate, and prints the packet inputs. A rejected message or a scanner finding leaves no record: resolve it, never stage around it. When a file mixes the commit's hunks with unrelated changes, stage exactly the intended hunks with `git apply --cached` on a trimmed patch before naming that path, or defer the file and ask H. Never use `git add -A` or `git add .`, and never stage credential-shaped files.
2. Screen the printed privacy hits, the staged paths, and the message for content unsuited to the audience, world-readable unless H says otherwise: machine, user, and host identifiers; local paths; security posture; private correspondence; session metadata. Report only metadata for binary or unreadable files and ask H to inspect them in a separate pane.
3. Present the packet: the script's stat, the message, the tree, parent, and branch, the gate report (each target passed, failed with its output, or skipped with its reason, and the script's worktree-equals-index line, which shows whether the gates covered exactly the candidate tree), the scan result, the privacy screen, the spar verdict when one ran, and the scratch disposition. Do not paste the full diff unless H asks. Follow the packet with the review cheat sheet below, then use the tool's interactive question selector (Claude Code, OpenCode, and Codex each have one) with `Commit and resume` first and `Commit and pause` second. Only a selected option authorizes the commit. Free text, whether typed as the selector's own answer or sent while rejecting it, carries revision requests, rejection, and questions: a revision request updates the candidate, reruns the gates the change touches, and produces a fresh packet that opens with what changed since the previous one; a question is answered and the same packet is presented again. In both cases the selector follows in the same reply, and text that merely names an option is handled the same way.

Any change to the staged content, message, audience, or scratch disposition after approval requires a fresh candidate: rerun `commit-candidate`, whose record replaces the old one. Rejection preserves the worktree; on H's instruction, `commit-candidate --clear` drops the record and `git restore --staged -- <paths>` clears the index.

## Review cheat sheet

Repeat this table in every packet until H asks to retire it. Review from a separate terminal pane at the repository root, starting with `nvim .`:

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

Terminal fallback: `git diff --cached --stat`, `git diff --cached`, and `git diff --cached -- path/to/file`.

## Commit

1. Run `~/.agents/skills/commit/scripts/commit-apply`. It refuses when the tree, parent, branch, or identity no longer equal the record, in which case present a fresh packet; otherwise it commits the recorded message verbatim on the current branch, verifies the new commit's tree, parent, branch, full message, and both addresses against the record, and reports the hash and title. When the result differs, a hook restaged content or rewrote the message: the script moves the branch back to the recorded parent, leaves the rejected commit unreachable, and prints the exact difference; report it and stop for H's decision. Never amend, create branches, or skip hooks unasked. Never push. `commit-gate`, a pre-tool hook in every tool, denies every commit-producing Git command a tool runs, so a raw Git command H wants, such as an amend, a merge, or a rebase, is H's own, through the `!` prefix, and prose that mentions such a command is written with the file tools, not a shell heredoc.
2. Report the hash and title. `Commit and resume` continues the request's authorized work, including its remaining commits and repositories; when none remains, load the `publish` skill and present every push the request produced together, one per repository with a configured upstream or a destination H named, joined into one command line as the publish skill describes, without stopping. Present a push earlier only when a later step depends on it having landed. `Commit and pause` stops for discussion.
