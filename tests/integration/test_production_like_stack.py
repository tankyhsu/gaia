from pathlib import Path

import yaml

from gaia.config import load_config

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "infra" / "production-like"


def test_production_like_compose_has_independent_replicas_and_data_owners() -> None:
    compose = yaml.safe_load((STACK / "compose.yaml").read_text())
    services = compose["services"]

    assert {
        "api-a",
        "api-b",
        "worker-a",
        "worker-b",
        "gateway",
        "console",
        "temporal",
        "temporal-postgres",
        "gaia-postgres",
        "langfuse-web",
        "langfuse-worker",
        "langfuse-postgres",
        "langfuse-clickhouse",
        "langfuse-redis",
        "langfuse-minio",
    } <= services.keys()
    assert services["worker-a"]["command"] == services["worker-b"]["command"]
    assert services["api-a"]["command"] == services["api-b"]["command"]
    assert services["temporal"]["image"] == "temporalio/server:1.31.2"
    assert services["temporal"]["environment"]["DYNAMIC_CONFIG_FILE_PATH"] == (
        "config/dynamicconfig/production-like.yaml"
    )
    assert services["temporal-schema"]["restart"] == "no"
    assert "127.0.0.1:8123/ping" in " ".join(
        services["langfuse-clickhouse"]["healthcheck"]["test"]
    )
    assert "$$(hostname -i):3000/api/public/health" in " ".join(
        services["langfuse-web"]["healthcheck"]["test"]
    )
    assert "127.0.0.1:8080/health/live" in " ".join(
        services["gateway"]["healthcheck"]["test"]
    )
    assert "127.0.0.1/" in " ".join(services["console"]["healthcheck"]["test"])
    assert services["langfuse-minio"]["command"] == [
        'mkdir -p /data/langfuse && minio server --address ":9000" '
        '--console-address ":9001" /data'
    ]


def test_production_like_config_selects_temporal_postgres_and_langfuse() -> None:
    config, _, _ = load_config(
        STACK / "gaia.yaml",
        environ={
            "GAIA_POSTGRES_URL": "postgresql://gaia:test@postgres/gaia",
            "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
        },
    )

    assert config.runtime.execution.provider == "temporal"
    assert config.runtime.execution.namespace == "gaia-production-like"
    assert config.stores.operational.provider == "postgres"
    assert config.observability.provider == "langfuse"
    assert config.runtime.environment.value == "sandbox"


def test_production_acceptance_exercises_required_failure_boundaries() -> None:
    source = (ROOT / "scripts" / "production_like_acceptance.py").read_text()

    assert 'compose("stop", "worker-a", "worker-b")' in source
    assert 'compose("stop", "api-a")' in source
    assert 'compose("restart", "temporal")' in source
    assert "wait_for_langfuse_trace" in source
    assert 'client.get("/v1/runs"' in source


def test_temporal_initialization_waits_for_namespace_visibility() -> None:
    source = (STACK / "temporal" / "initialize.sh").read_text()

    assert 'until temporal operator namespace describe \\' in source


def test_external_compose_overlay_makes_platform_dependencies_optional() -> None:
    source = (STACK / "compose.external.yaml").read_text()

    assert 'profiles: ["managed-postgres"]' in source
    assert 'profiles: ["managed-temporal"]' in source
    assert 'profiles: ["managed-langfuse"]' in source
    assert "GAIA_CONFIG_FILE is required" in source
