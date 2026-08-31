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

### No blanket staging

You MUST NEVER use `git commit -a` / `git commit --all`, `git add -A` / `git add --all`, `git add .`, or `git add -u`.
You MUST NEVER pass a pathspec to `git commit` (e.g. `git commit -m "..." -- file`) — the pathspec form re-stages the *entire current working-tree state* of that path, ignoring what you carefully staged.
You MUST stage by listing exact file paths: `git add <path1> <path2> ...`, then `git commit -m "..."` with no pathspec.

### Verify the staged diff, not just the file list

Before every commit you MUST run `git diff --cached` (the full hunk diff, not `--stat`) and confirm that **every hunk** is one you wrote for this task.
A filename check (`git diff --cached --stat` / `--name-only`) is NOT sufficient: when another session has unstaged edits in a file you also edited, `git add <that file>` stages their hunks too, and they do not appear as a new filename — only as extra `+`/`-` lines inside a file that is legitimately yours.
If any staged hunk is not yours, you MUST stop, unstage (`git restore --staged <file>`), and report to the human — do not try to surgically separate the hunks yourself (interactive `git add -p` is unavailable in this environment). Wait for the other session to commit its own hunks first, then rebase/re-apply yours.

### Incident record — why these rules exist

Commit `0a35b6a` (`feat(WON-35 Unit 3)`) silently included another session's WON-36 work: `commerce_facts.py::order_action_out_of_scope()` plus its `__all__` entry. Both sessions were editing `commerce_facts.py` concurrently; the WON-35 session ran `git add src/utils/commerce_facts.py` while the WON-36 hunks sat unstaged in the working tree, so `git add <file>` swept them in. The pre-commit check that ran was `git diff --cached --stat`, which showed `commerce_facts.py | 19 ++` — the reviewer read that as "my ~13-line change" and committed without reading the hunks. Result: WON-36 code landed under a WON-35 commit, attribution wrong, history entangled (WON-36's follow-up commit `8ce01b0` then had to work around it). This is a recurrence of the same class of sweep that motivated the atomic-add rule above; a filename-level check does not catch it.

## Regression base comparison in a shared working tree

Multiple sessions share one working tree and one stash stack. To compare test results against a base revision, you MUST NOT temporarily remove your changes from the working tree.

You MUST NEVER use `git stash` (any form) for this. When git operations from several sessions interleave, the stash stack shifts under you: a later `git stash pop` can report success while restoring the wrong entry, silently leaving your work stashed.
You MUST NEVER use `git checkout -- <file>` / `git restore <file>` / `git restore --source=<rev> <file>` for this. It discards whatever another session has uncommitted in that file.

Instead:
- To compare file *contents* only: `git show <commit>:<path>` (or `git diff <commit> -- <path>`) — writes nothing to the tree.
- To *run tests* against a base revision: `git worktree add <dir> <commit>`, run there, then `git worktree remove <dir>`. This is the only safe way to have base files on disk without touching the shared tree.
- Prefer committing your work first, then comparing `HEAD` against `HEAD~1` in a worktree.

### Incident record — why these rules exist

During `feat(WON-37 Unit 2)` (`19a6287`) the session ran `git stash push -- src/agents/nodes.py src/payment/node.py`, ran the baseline suite, then `git stash pop`, which printed `Dropped refs/stash@{0}` — apparent success. But concurrent git activity from other sessions had shifted the stash stack, so the pop restored a different entry and the session's Unit 2 edits stayed stashed as `stash@{0}` ("WIP on rookie/Agent_v3: 16befc0"). It went unnoticed until an e2e run showed `cancel_node` had silently reverted to its pre-edit body. Recovered with `git stash apply` + full hunk review (the stash happened to hold only that session's two files). `git checkout -- <file>` fails the same way from the other direction — it would have wiped another session's concurrent edits to those files. Neither touches-the-tree approach is safe here; use `git show` or `git worktree`.

## Hotspot push gate

Before pushing a commit that changes any hotspot file, you MUST report the hotspot diff and obtain explicit approval.
You MUST verify the final staged diff after approval and before push.
You MUST NEVER push hotspot changes without this gate.

## Destructive Git operations

Before any destructive Git operation, you MUST record the current branch, `git status`, and current commit hash.
You MUST identify the exact files or commits that may be overwritten or removed.
You MUST obtain explicit approval before running the operation.
You MUST NEVER run `git reset --hard`, destructive checkout, clean, force-push, or equivalent operations without approval.
