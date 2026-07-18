# Agent Coordination

This repository uses a serial agent workflow: only one agent edits the shared worktree at
a time. Agents run the Git commands below themselves; the user does not need to run them.

## Before a Write Task

Before editing files at the start of a new task or after another agent may have worked, run:

```bash
git status --short --branch
git log -5 --oneline --decorate
```

- If the worktree is dirty, inspect `git diff --stat` and `git diff` before editing.
- Preserve all existing changes. If their ownership or relationship to the task is unclear,
  stop and ask the user before editing.
- When another agent may have completed work, inspect the newest checkpoint with
  `git show --stat --oneline HEAD` and read the relevant changed files.
- Do not pull, rebase, reset, amend, or discard existing work unless the user explicitly asks.

## While Working

- Stay within the requested scope and avoid unrelated refactors.
- Treat `docs/operations/azure-deployment-handoffs.md` as an Azure deployment runbook, never
  as an AI session log.
- Use Git commits and the current task prompt as the handoff record; do not create a persistent
  AI session log.
- For `apps/console` UI work, read `PRODUCT.md` and `DESIGN.md` first and follow
  `.cursor/rules/design.mdc`. Prefer Fluent UI + existing tokens over new visual systems.
- Skill payloads under `.cursor/skills/` and `.agents/skills/` are gitignored. Reinstall
  locally with:
  `npx skills add anthropics/skills --skill frontend-design -y`
  `npx skills add Leonxlnx/taste-skill --skill design-taste-frontend -y`
  `npx impeccable@latest install --providers=cursor --scope=project`

## Before Handoff

For any task that changes files:

1. Review the complete diff and run `git diff --check`.
2. Run the smallest relevant tests, lint, type checks, or build checks for the changed area.
3. Create one focused commit containing only the current task's changes, unless the user says
   not to commit. Never amend an existing commit unless explicitly requested.
4. Confirm the resulting worktree state with `git status --short --branch`.
5. Report the commit hash, checks run, and any remaining concerns. Do not push unless asked.
