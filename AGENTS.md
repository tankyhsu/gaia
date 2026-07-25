# Gaia Agent Development Contract

This repository treats code, tests, documentation, generated contracts, and release impact as one
change set.

## When to use the change workflow

Use the workflow whenever a task changes tracked files. Pure discussion, research, and read-only
review do not create a change set.

Before editing:

1. Run `make change-start INTENT="<concrete outcome>" KIND=<kind>`.
2. Read `CONTRIBUTING.md` and the affected public contract.
3. Identify code, test, documentation, schema, migration, and release impact.

While implementing:

- Deliver one minimum vertical slice at a time.
- Add a regression test before fixing a bug.
- Update tests with behavior changes.
- Update user documentation when public behavior, configuration, API, CLI, Starter, or Console
  behavior changes.
- Update `CHANGELOG.md` for user-visible behavior. Use an explicit exemption only for an internal
  change with a concrete reason.
- Do not make a failing suite pass by deleting assertions, weakening schemas, adding skips, or
  filtering Gaia-owned warnings.
- Do not use `git commit --no-verify` or bypass repository validation.

Before reporting completion:

1. Run `make agent-check`.
2. Review `git diff` for stale code, tests, examples, documentation, and generated artifacts.
3. For public developer-facing capabilities, validate the documented path as an unfamiliar
   consumer or record why that check is not applicable.

Before committing:

1. Stage only the intended change set.
2. Run `make change-ready`.
3. Commit without modifying the index after verification.

The project Codex hooks enforce this contract at session stop and before `git commit`. GitHub
Actions independently rerun the full quality matrix in a clean environment.
