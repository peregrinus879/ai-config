---
name: commit
description: Commit conventions. Conventional commits, atomic changes, staging, imperative mood, co-author line.
disable-model-invocation: true
---

# Commit Conventions

## Format

```
<type>: <subject>

[optional body]

Co-Authored-By: Claude {current model} <noreply@anthropic.com>
```

## Types

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only
- `refactor:` - Code change that neither fixes a bug nor adds a feature
- `style:` - Formatting, whitespace (no code change)
- `test:` - Adding or correcting tests
- `chore:` - Maintenance tasks

## Pre-commit check

Before staging, verify whether pending changes add, remove, or rename
files referenced in project documentation (README.md, CLAUDE.md, or
similar). If so, update the affected existing documentation before
proceeding with staging and commits.

When syncing docs for the current change:

- Identify the existing documentation files affected by the pending changes.
- Compare documented commands, paths, workflows, and file listings against the current repo state.
- Update only what the current change requires; do not expand scope.
- Do not create new documentation files unless explicitly requested.

## Staging

- Stage specific files by name (`git add <file>`). Do not use `git add -A` or `git add .`.
- When a file contains changes belonging to different logical commits, use `git add -p <file>` to stage only the relevant hunks.
- Review staged changes (`git diff --cached`) before committing.
- Never stage sensitive files (.env, credentials, private keys).

## Rules

- Atomic: one complete, self-contained change per commit
- Separate commits by type
- Subject: imperative mood, concise (50 chars), lowercase
- Body: when the change needs context (explain why, not what)
- Co-Author: always append with current model
- Push: user handles manually (SSH passphrase required). Do not push.
- After committing, get the current branch with `git branch --show-current`, then check for an upstream tracking branch with `git rev-parse --abbrev-ref @{upstream} 2>/dev/null`, and show the appropriate push command:
  - Has upstream: `git push`
  - Has `origin`, no upstream: `git push -u origin <branch>`
  - No `origin`: `git remote add origin <url> && git push -u origin <branch>`
