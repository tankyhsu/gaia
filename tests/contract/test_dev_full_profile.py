from __future__ import annotations

from pathlib import Path

import yaml

from gaia.config import load_config

ROOT = Path(__file__).resolve().parents[2]
DEV_FULL = ROOT / "infra" / "dev-full"


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor(
    "!override",
    lambda loader, node: loader.construct_sequence(node),
)
ComposeLoader.add_constructor(
    "!reset",
    lambda loader, node: loader.construct_mapping(node),
)


def test_dev_full_profiles_select_real_local_dependencies(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GAIA_POSTGRES_URL", "postgresql://gaia:test@postgres/gaia")
    monkeypatch.setenv("GAIA_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret")

    gaia_config = load_config(DEV_FULL / "gaia.yaml")[0]
    hr_config = load_config(DEV_FULL / "hr-gaia.yaml")[0]

    for config in (gaia_config, hr_config):
        assert config.profile == "dev-full"
        assert config.runtime.environment == "sandbox"
        assert config.runtime.execution.provider == "temporal"
        assert config.stores.operational.provider == "postgres"
        assert config.stores.checkpoint.provider == "postgres"
        assert config.cache.provider == "redis"
        assert config.rate_limit.provider == "redis"
        assert config.model.provider == "openai-compatible"
        assert config.model.model_id == "deepseek-chat"
        assert config.observability.provider == "langfuse"

    assert gaia_config.runtime.execution.task_queue == "gaia-dev-full"
    assert hr_config.runtime.execution.task_queue == "gaia-hr-dev-full"


def test_dev_full_compose_adds_hr_and_gaia_redis_to_production_like_stack() -> None:
    compose = yaml.load(
        (DEV_FULL / "compose.yaml").read_text(),
        Loader=ComposeLoader,
    )
    services = compose["services"]

    assert {"gaia-redis", "hr-api", "hr-worker", "hr-frontend"} <= services.keys()
    assert services["gaia-redis"]["profiles"] == ["managed-redis"]
    assert services["gateway"]["depends_on"]["hr-api"]["condition"] == "service_healthy"
    assert services["gateway"]["environment"]["GAIA_API_KEY"] == (
        "${GAIA_API_KEY:-gaia-production-like-key}"
    )
    assert services["gateway"]["ports"] == [
        "127.0.0.1:${GAIA_GATEWAY_PORT:-4181}:8080"
    ]
    assert services["console"]["ports"] == []
    assert "console.conf:/etc/nginx/conf.d/default.conf:ro" in " ".join(
        services["console"]["volumes"]
    )
    assert services["temporal-ui"]["ports"] == [
        "127.0.0.1:${GAIA_TEMPORAL_UI_PORT:-8080}:8080"
    ]
    assert services["langfuse-web"]["ports"] == [
        "127.0.0.1:${GAIA_LANGFUSE_PORT:-3000}:3000"
    ]
    assert "docs" in services
    assert "../../mkdocs.yml:/workspace/mkdocs.yml:ro" in services["docs"]["volumes"]
    assert (
        "../../developer-docs:/workspace/developer-docs:ro"
        in services["docs"]["volumes"]
    )
    assert services["hr-api"]["environment"]["GAIA_DEVTOOLS_ENABLED"] == "true"
    assert services["hr-frontend"]["environment"]["VITE_GAIA_RUN_MODE"] == "sandbox"
    assert "--base /hr/" in services["hr-frontend"]["command"][-1]
    assert services["worker-a"]["command"][-1] == "examples.function_task.app:build"
    assert services["worker-b"]["command"][-1] == "examples.function_task.app:build"


def test_dev_full_gateway_uses_proxy_safe_canonical_paths() -> None:
    gateway = (DEV_FULL / "gateway.conf.template").read_text()

    assert "location /docs/" in gateway
    assert "location /hr/" in gateway
    assert "docs.gaia.localhost" not in gateway
    assert "hr.gaia.localhost" not in gateway
    assert 'proxy_set_header X-Gaia-Api-Key "${GAIA_API_KEY}";' in gateway
    assert "\\x24{GAIA_API_KEY}" not in gateway
    assert "location /demo/" in gateway
    assert "location /v1/" in gateway
    showcase = (ROOT / "apps/web/src/showcase.ts").read_text()
    assert 'path: "/#' not in showcase
    assert 'path: "#onboarding"' in showcase
    assert 'path: "#handbook"' in showcase
    assert 'path: "#leave"' in showcase
