---
name: update-docs
description: After code changes, verify and update project documentation (README, APPROACH, etc.) to stay in sync with the implementation.
---

# Update Documentation

After making code changes, verify and update project documentation to reflect the current state.

## Workflow

1. Identify documentation files in the project root (`README.md`, `APPROACH.md`, `CHANGELOG.md`, or similar)
2. Read each documentation file
3. Compare documented behavior against the current implementation
4. Propose changes before editing

## What to verify

- Commands, flags, and usage examples match the implementation
- Setup/install steps reference correct packages and commands
- Workflow descriptions reflect the actual flow
- Troubleshooting covers current failure modes
- File listings and directory structures match reality
- Removed features are removed from docs; new features are documented

## Rules

- Present proposed changes before editing
- Do not add, remove, or modify content beyond what the recent code changes require
- Match existing formatting and style conventions in each file
- Keep docs focused on user-facing information; internal details belong in `.claude/CLAUDE.md`
- Do not create new documentation files unless explicitly requested
