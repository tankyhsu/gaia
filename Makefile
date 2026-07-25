PYTHON := uv run python
PYTEST_MARKS := not postgres and not redis and not external

.PHONY: setup hooks-install hooks-status change-start change-status agent-check change-ready lint test test-services \
	web-build web-test docs contracts package-smoke verify dev-api dev-console dev-docs \
	infra-up infra-down

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

verify: lint test web-build web-test docs contracts package-smoke

dev-api:
	GAIA_API_KEY=$${GAIA_API_KEY:-gaia-dev-key} \
	GAIA_DEVTOOLS_ENABLED=$${GAIA_DEVTOOLS_ENABLED:-true} \
	GAIA_PROJECT_ROOT=$${GAIA_PROJECT_ROOT:-$(CURDIR)} \
	uv run uvicorn examples.controlled_task.app:create_app --factory --reload

dev-console:
	GAIA_API_KEY=$${GAIA_API_KEY:-gaia-dev-key} \
	npm --prefix apps/web run dev -- --host 127.0.0.1

dev-docs:
	uv run mkdocs serve --dev-addr 127.0.0.1:4175

infra-up:
	docker compose -f infra/dev/compose.yaml up -d

infra-down:
	docker compose -f infra/dev/compose.yaml down
