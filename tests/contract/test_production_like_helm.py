from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "infra" / "production-like" / "helm" / "gaia"
STACK = ROOT / "infra" / "production-like" / "helm" / "stack"
LOCAL_DEPENDENCIES = STACK / "local-dependencies"


def test_production_like_chart_has_owned_workloads_and_external_secret_boundary() -> None:
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    templates = {path.name for path in (CHART / "templates").iterdir()}

    assert chart["apiVersion"] == "v2"
    assert chart["type"] == "application"
    assert values["secrets"]["existingSecret"] == "gaia-production-like-secrets"
    assert values["console"]["enabled"] is False
    assert values["gaia"]["config"]["gaia"]["runtime"]["execution"]["provider"] == (
        "temporal"
    )
    assert {
        "api.yaml",
        "worker.yaml",
        "console.yaml",
        "migration-job.yaml",
        "temporal-bootstrap-job.yaml",
        "pdb.yaml",
        "scaling.yaml",
        "networkpolicy.yaml",
    }.issubset(templates)
    assert not any(
        "kind: Secret" in path.read_text()
        for path in (CHART / "templates").glob("*.yaml")
    )


def test_migration_and_temporal_bootstrap_gate_rollout() -> None:
    migration = (CHART / "templates" / "migration-job.yaml").read_text()
    temporal = (CHART / "templates" / "temporal-bootstrap-job.yaml").read_text()

    assert "pre-install,pre-upgrade" in migration
    assert 'helm.sh/hook-weight: "-10"' in migration
    assert "gaia migrate" in migration
    assert "pre-install,pre-upgrade" in temporal
    assert 'helm.sh/hook-weight: "-20"' in temporal
    assert "GaiaOrganization GaiaScenarioId GaiaRunStatus" in temporal


def test_external_values_leave_ui_and_platform_lifecycle_to_operator() -> None:
    values = yaml.safe_load((CHART / "values-external.example.yaml").read_text())
    execution = values["gaia"]["config"]["gaia"]["runtime"]["execution"]
    observability = values["gaia"]["config"]["gaia"]["observability"]

    assert values["console"]["enabled"] is False
    assert values["ingress"]["enabled"] is False
    assert values["temporalBootstrap"]["enabled"] is False
    assert execution["server_address"] == "temporal.platform.example:7233"
    assert observability["base_url"] == "https://langfuse.platform.example"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_chart_lints_and_renders_with_orbstack_values() -> None:
    subprocess.run(["helm", "lint", str(CHART)], check=True, capture_output=True)
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "gaia-production-like",
            str(CHART),
            "--namespace",
            "gaia",
            "--values",
            str(CHART / "values-orbstack.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "kind: Deployment" in rendered
    assert "kind: Job" in rendered
    assert "kind: Secret" not in rendered
    assert "readOnlyRootFilesystem: true" in rendered


def test_complete_stack_pins_upstream_charts_and_uses_cluster_dns() -> None:
    deploy = (STACK / "deploy-orbstack.sh").read_text()
    temporal = yaml.safe_load((STACK / "temporal-values-orbstack.yaml").read_text())
    langfuse = yaml.safe_load((STACK / "langfuse-values-orbstack.yaml").read_text())
    gaia = yaml.safe_load((STACK / "gaia-values-orbstack.yaml").read_text())
    connection_configuration = "\n".join(
        (STACK / filename).read_text()
        for filename in (
            "temporal-values-orbstack.yaml",
            "langfuse-values-orbstack.yaml",
            "gaia-values-orbstack.yaml",
        )
    )

    assert 'TEMPORAL_CHART_VERSION="1.6.0"' in deploy
    assert 'LANGFUSE_CHART_VERSION="1.5.41"' in deploy
    assert "temporal/temporal" in deploy
    assert "langfuse/langfuse" in deploy
    assert temporal["server"]["config"]["persistence"]["defaultStore"] == "default"
    assert langfuse["postgresql"]["deploy"] is True
    assert langfuse["redis"]["deploy"] is True
    assert langfuse["clickhouse"]["deploy"] is True
    assert langfuse["s3"]["deploy"] is True
    assert (
        gaia["gaia"]["config"]["gaia"]["runtime"]["execution"]["server_address"]
        == "temporal-frontend.temporal-product-like.svc.cluster.local:7233"
    )
    assert "host.internal" not in connection_configuration


def test_platform_can_boot_without_a_model_key() -> None:
    deploy = (STACK / "deploy-orbstack.sh").read_text()
    verify = (STACK / "verify-orbstack.sh").read_text()

    platform_install = deploy.index("helm upgrade --install langfuse")
    missing_key_branch = deploy.index('if [[ -z "${DEEPSEEK_API_KEY:-}" ]]')
    gaia_install = deploy.index('helm upgrade --install "$gaia_release"')

    assert platform_install < missing_key_branch < gaia_install
    assert "Gaia and the live-model verification were skipped" in deploy
    assert ': "${DEEPSEEK_API_KEY:?' not in deploy
    assert "gaia_secret_resource_version" in deploy
    assert "podAnnotations.gaia-secret-resource-version" in deploy
    assert 'GAIA_PROFILE="${GAIA_PROFILE:-product-like}"' in deploy
    assert 'platform_namespace="gaia-platform-$GAIA_PROFILE"' in deploy
    assert 'temporal_namespace="temporal-$GAIA_PROFILE"' in deploy
    assert 'langfuse_namespace="langfuse-$GAIA_PROFILE"' in deploy
    assert 'gaia_namespace="gaia-$GAIA_PROFILE"' in deploy
    assert "temporal-system" not in deploy
    assert "langfuse-system" not in deploy
    assert "gaia-system" not in deploy
    assert "temporal-system" not in verify
    assert "langfuse-system" not in verify
    assert "gaia-system" not in verify


def test_complete_stack_verifies_real_model_temporal_and_langfuse() -> None:
    verify = (STACK / "verify-orbstack.sh").read_text()

    assert '"hr.handbook.answer"' in verify
    assert '"deepseek-chat"' in verify
    assert "temporal operator namespace describe" in verify
    assert "temporal workflow describe" in verify
    assert "workflow_description=" in verify
    assert "/api/public/traces/$trace_id" in verify
    assert "Status.*COMPLETED" in verify
    assert "Gaia did not accept a Run after Temporal became queryable" in verify
    assert "Langfuse did not expose Trace" in verify


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_local_dependencies_chart_lints_and_renders_without_secrets() -> None:
    subprocess.run(
        ["helm", "lint", str(LOCAL_DEPENDENCIES)],
        check=True,
        capture_output=True,
    )
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "gaia-local-dependencies",
            str(LOCAL_DEPENDENCIES),
            "--namespace",
            "gaia-platform",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert rendered.count("kind: StatefulSet") == 3
    assert "temporal_visibility" in rendered
    assert "kind: Secret" not in rendered
