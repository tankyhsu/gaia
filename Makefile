PYTHON := uv run python
PYTEST_MARKS := not postgres and not redis and not external

.PHONY: setup hooks-install hooks-status change-start change-status agent-check change-ready lint test test-services \
	web-build web-test docs contracts package-smoke verify dev-api dev-console dev-docs \
	infra-up infra-down attack-demo demo capture-histories dev-full dev-full-external \
	prod-up prod-up-external prod-acceptance prod-down

setup:
	uv sync --locked --all-extras --all-groups
	npm --prefix apps/web ci
	npm --prefix apps/web exec playwright install chromium

hooks-install:
	$(PYTHON) scripts/hook_manager.py install --workspace-root "$(or $(WORKSPACE_ROOT),$(CURDIR))"

hooks-status:
	$(PYTHON) scripts/hook_manager.py status --workspace-root "$(or $(WORKSPACE_ROOT),$(CURDIR))"

change-start:
	@test -n "$(INTENT)" || (echo 'INTENT is required' && exit 2)
	$(PYTHON) scripts/change_set.py start --intent "$(INTENT)" --kind "$(or $(KIND),feature)"

change-status:
	$(PYTHON) scripts/change_set.py status

agent-check:
	$(PYTHON) scripts/change_set.py verify --run-checks

change-ready:
	$(PYTHON) scripts/change_set.py verify --staged --run-checks --write-receipt

lint:
	uv run ruff check .
	uv run mypy src

test:
	uv run pytest -q -m "$(PYTEST_MARKS)"

test-services:
	uv run pytest -q -m "(postgres or redis) and not external"

# Re-record the Workflow histories that test_workflow_replay.py replays against
# the current Workflow code. Only run this when a Workflow change is meant to
# ship to a new Worker build: re-recording to make a failing replay pass
# otherwise just deletes the evidence that in-flight Runs would break.
capture-histories:
	GAIA_CAPTURE_HISTORIES=1 uv run pytest -q -p no:randomly \
		tests/integration/test_temporal_end_to_end.py

web-build:
	npm --prefix apps/web run build

web-test:
	npm --prefix apps/web run test:e2e

docs:
	uv run mkdocs build --strict

contracts:
	$(PYTHON) scripts/check_openapi.py

package-smoke:
	$(PYTHON) scripts/package_smoke.py

attack-demo:
	$(PYTHON) scripts/attack_demo.py

# One command from a fresh clone to real evidence in the Console: its own
# disposable databases, migrated, seeded with runs worth looking at, Temporal,
# Worker, API, docs, and Console all started, ending in one URL and one
# sentence -- see scripts/demo.py for what it does and why. Never touches
# var/gaia.db and uses its own ports (8010 / 4180) so it can run alongside
# `make dev-api` / `make dev-console`. Docs are served on the same port as
# `make dev-docs` (4175) -- if that's already running, `make demo` simply
# reports docs as unavailable for this run instead of failing outright; see
# scripts/demo.py's docs handling for details.
demo:
	$(PYTHON) scripts/demo.py

DEV_FULL_COMPOSE = docker compose \
	--project-name gaia-dev-full \
	-f infra/production-like/compose.yaml \
	-f infra/dev-full/compose.yaml
DEV_FULL_EXTERNAL_COMPOSE = $(DEV_FULL_COMPOSE) \
	-f infra/production-like/compose.external.yaml \
	-f infra/dev-full/compose.external.yaml

dev-full:
	@test -n "$$DEEPSEEK_API_KEY" || \
		(echo "DEEPSEEK_API_KEY is required for the dev-full profile" >&2; exit 1)
	$(DEV_FULL_COMPOSE) --profile managed-redis up --build -d --wait
	@printf '%s\n' \
		"Gaia Console: http://127.0.0.1:4181/console/" \
		"HR Showcase:  http://127.0.0.1:4181/hr/" \
		"Gaia Docs:    http://127.0.0.1:4181/docs/" \
		"Temporal UI:  http://127.0.0.1:$${GAIA_TEMPORAL_UI_PORT:-8080}/" \
		"Langfuse:     http://127.0.0.1:$${GAIA_LANGFUSE_PORT:-3000}/"

dev-full-external:
	@test -n "$$DEEPSEEK_API_KEY" || \
		(echo "DEEPSEEK_API_KEY is required for the dev-full profile" >&2; exit 1)
	@test -n "$$GAIA_CONFIG_FILE" -a -n "$$HR_GAIA_CONFIG_FILE" || \
		(echo "GAIA_CONFIG_FILE and HR_GAIA_CONFIG_FILE are required" >&2; exit 1)
	$(DEV_FULL_EXTERNAL_COMPOSE) $(GAIA_MANAGED_PROFILES) up --build -d --wait
	@printf '%s\n' "Development gateway: http://127.0.0.1:4181/"

PROD_COMPOSE = docker compose -f infra/production-like/compose.yaml
PROD_EXTERNAL_COMPOSE = $(PROD_COMPOSE) \
	-f infra/production-like/compose.external.yaml

prod-up:
	$(PROD_COMPOSE) up --build -d --wait

prod-up-external:
	@test -n "$$GAIA_CONFIG_FILE" || \
		(echo "GAIA_CONFIG_FILE is required" >&2; exit 1)
	$(PROD_EXTERNAL_COMPOSE) $(GAIA_MANAGED_PROFILES) up --build -d --wait

prod-acceptance:
	$(PYTHON) scripts/production_like_acceptance.py

prod-down:
	$(PROD_COMPOSE) down --remove-orphans

verify: lint test web-build web-test docs contracts package-smoke

dev-api:
	GAIA_API_KEY=$${GAIA_API_KEY:-gaia-dev-key} \
	GAIA_DEVTOOLS_ENABLED=$${GAIA_DEVTOOLS_ENABLED:-true} \
	GAIA_PROJECT_ROOT=$${GAIA_PROJECT_ROOT:-$(CURDIR)} \
	uv run uvicorn examples.controlled_task.app:create_app --factory --reload

dev-worker:
	GAIA_API_KEY=$${GAIA_API_KEY:-gaia-dev-key} \
	GAIA_DEVTOOLS_ENABLED=$${GAIA_DEVTOOLS_ENABLED:-true} \
	GAIA_PROJECT_ROOT=$${GAIA_PROJECT_ROOT:-$(CURDIR)} \
	uv run gaia worker \
		--config examples/controlled_task/gaia.yaml \
		--app examples.controlled_task.app:create_app

dev-console:
	GAIA_API_KEY=$${GAIA_API_KEY:-gaia-dev-key} \
	npm --prefix apps/web run dev -- --host 127.0.0.1

dev-docs:
	uv run mkdocs serve --dev-addr 127.0.0.1:4175

infra-up:
	docker compose -f infra/dev/compose.yaml up -d

infra-down:
	docker compose -f infra/dev/compose.yaml down
