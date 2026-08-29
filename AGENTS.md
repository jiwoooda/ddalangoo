# Repository Safety Rules

These rules are mandatory for every agent working in this repository.

## Hotspot files

The following files are shared architectural hotspots:

- `router.py`
- `schema.py`
- `node_inputs.py`
- `builder.py`

Before editing a hotspot file, you MUST announce the exact file and intended change.
You MUST check whether another active task is modifying the same hotspot.
You MUST NEVER silently edit a hotspot file during parallel work.

## Pre-commit status check

Immediately before every commit, you MUST run `git status`.
You MUST distinguish your changes from pre-existing or unrelated changes.
You MUST stage only files that belong to the approved task.
You MUST NEVER include unrelated working-tree changes in a commit.
You MUST run `git add` and `git commit` atomically, with no gap between them. Never stage files and then wait — if another session runs a pathless commit in that gap, your staged files get swept into it.

## Hotspot push gate

Before pushing a commit that changes any hotspot file, you MUST report the hotspot diff and obtain explicit approval.
You MUST verify the final staged diff after approval and before push.
You MUST NEVER push hotspot changes without this gate.

## Destructive Git operations

Before any destructive Git operation, you MUST record the current branch, `git status`, and current commit hash.
You MUST identify the exact files or commits that may be overwritten or removed.
You MUST obtain explicit approval before running the operation.
You MUST NEVER run `git reset --hard`, destructive checkout, clean, force-push, or equivalent operations without approval.
