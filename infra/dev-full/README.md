# Gaia dev-full

`dev-full` is the local production-shaped development profile. It keeps
`make demo` deterministic and starts the real infrastructure path separately:

- PostgreSQL for Gaia operational state and checkpoints;
- Redis for cache and rate limiting;
- Temporal with a durable PostgreSQL store and the Temporal UI;
- Langfuse with OTLP ingestion, ClickHouse, Redis, MinIO and PostgreSQL;
- Gaia API and Worker replicas;
- the HR reference API and Worker on their own Temporal task queue;
- the HR frontend and Gaia Dev Console;
- DeepSeek through Gaia's OpenAI-compatible model boundary.

Set `DEEPSEEK_API_KEY` in the shell, then run:

```bash
make dev-full
```

The command waits for every required service. One development-only Nginx
gateway exposes Console, HR demo, docs, Temporal UI, and Langfuse on port
`4181`. The canonical links are `http://127.0.0.1:4181/console/`, `/hr/`, and
`/docs/`; they do not depend on wildcard localhost DNS or proxy bypass rules.
Temporal UI and Langfuse retain their native root-path assumptions and are
published on configurable loopback ports `8080` and `3000`. The Gaia Console is routed to the
HR API, so HR Runs, model calls,
Guardrail decisions and Human Gates are visible in the same Console.
The Console uses port `4181`, leaving the deterministic `make demo` port
`4180` independent.

This profile is still safe for local development: Runtime environment is
`sandbox` and writes remain `approval_required`. It is production-shaped, not
a production credential or deployment template.

For a hybrid enterprise setup, point `GAIA_CONFIG_FILE` and
`HR_GAIA_CONFIG_FILE` at configs containing existing service addresses, set
`GAIA_MANAGED_PROFILES` only for missing components, and run
`make dev-full-external`.
