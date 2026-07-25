# Contributing to Gaia

Gaia development uses a change-set workflow. The unit of completion is not a code diff; it is a
consistent set of behavior, implementation, tests, documentation, generated contracts, and release
impact.

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
- GitHub Actions reruns deterministic tests, real PostgreSQL and Redis tests, frontend E2E,
  documentation builds, OpenAPI drift checks, and clean-wheel smoke tests.

Local hooks are workflow guardrails. GitHub required checks remain the authoritative merge gate.
External-model tests remain explicit local opt-in checks during development; scheduled and release
workflows will be introduced only when Gaia enters a release phase.
