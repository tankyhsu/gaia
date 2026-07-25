# Contributing to Gaia

Gaia development uses a change-set workflow. The unit of completion is not a code diff; it is a
consistent set of behavior, implementation, tests, documentation, generated contracts, and release
impact.

## Install the local workflow hooks

Run this once for each clone:

```bash
make hooks-install
```

If Codex opens the directory above the Gaia repository, install the forwarding config at that
workspace root so Codex can discover the repository contract:

```bash
make hooks-install WORKSPACE_ROOT=..
```

The command installs the Codex discovery config and sets Git's `core.hooksPath` to the tracked
`.githooks` directory. Check both layers and view the latest audited lifecycle events with:

```bash
make hooks-status WORKSPACE_ROOT=..
```

Hook audit records live under `.git/gaia/hook-events.jsonl`. They contain event names, session IDs,
outcomes, and short failure reasons; user prompts and shell command bodies are not stored. Start a
new Codex task after installing a previously missing workspace config so `SessionStart` can
establish its baseline. Codex binds trust to Hook content: after `hooks.json` changes, review and
trust the new definition in Codex once before expecting automatic execution.

## Start a change

```bash
make change-start INTENT="Describe the observable outcome" KIND=feature
```

Supported kinds are `feature`, `bugfix`, `refactor`, `docs`, `test`, and `build`.

The command creates `.gaia-work/change-set.json`. This local file is ignored by Git and belongs to
the current working session.

## Work vertically

Choose the smallest path that proves the behavior:

```text
configuration or public contract
-> implementation
-> unit/contract/integration/acceptance test
-> generated artifact
-> developer or operator documentation
-> release impact
```

Bug fixes start with a failing regression test. Documentation-only changes do not require an
artificial code or test modification.

## Declare a justified exception

The change guard infers minimum requirements from changed paths. If a requirement is genuinely not
applicable, record the reason instead of touching an unrelated file:

```bash
uv run python scripts/change_set.py exempt docs \
  --reason "Internal refactor with no public behavior or configuration change"
```

Valid areas are `tests`, `docs`, and `release`. Exceptions are visible in the verification report
and must contain a concrete reason.

## Finish the change

Before reporting completion:

```bash
make agent-check
```

Local Playwright checks reuse an already running Gaia Dev Console on the test port. CI always starts
a clean server. Set `GAIA_WEB_TEST_PORT=<port>` when the default `4174` belongs to another process.

Before committing:

```bash
git add <intended files>
make change-ready
git commit
```

`make change-ready` validates the staged change and writes a receipt bound to the current Git index
tree. The Codex `PreToolUse` hook rejects `git commit` if the index changed after verification.

## What automation enforces

- Codex `SessionStart` and `UserPromptSubmit` add this contract to the agent context.
- Codex `Stop` checks changed code, tests, documentation, and generated contracts before an agent
  can finish a modifying turn.
- Codex `SubagentStop` applies the same rule to delegated implementation work.
- Codex `PreToolUse` blocks unverified commits and any attempt to use `--no-verify`.
- Git `pre-commit` checks the staged verification receipt, `post-commit` clears finished Change Set
  metadata, and `pre-push` runs the full deterministic verification suite.
- GitHub Actions reruns deterministic tests, real PostgreSQL and Redis tests, frontend E2E,
  documentation builds, OpenAPI drift checks, and clean-wheel smoke tests.

Codex discovery is scoped to the task workspace, so the forwarding config matters when a task starts
above the repository. Local hooks are workflow guardrails. GitHub required checks remain the
authoritative merge gate.
External-model tests remain explicit local opt-in checks during development; scheduled and release
workflows will be introduced only when Gaia enters a release phase.
