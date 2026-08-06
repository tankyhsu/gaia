from pathlib import Path

import pytest
from pydantic import ValidationError

from gaia.config import (
    ConfigOrigin,
    GaiaApplicationConfig,
    SecretRef,
    load_config,
    resolve_config_path,
)
from gaia.contracts.models import RunMode, WriteMode


def test_profile_env_cli_precedence_and_hash(tmp_path: Path) -> None:
    config_file = tmp_path / "gaia.yaml"
    config_file.write_text(
        "gaia:\n  profile: mock\n  runtime: {max_steps: 5}\n"
        "  profiles:\n    mock: {runtime: {max_steps: 6}}\n"
    )
    config, origins, _ = load_config(
        config_file, overrides=["runtime.max_steps=8"], environ={"GAIA__RUNTIME__MAX_STEPS": "7"}
    )
    assert config.runtime.max_steps == 8
    assert origins["runtime.max_steps"] == ConfigOrigin.CLI
    assert config.stable_hash() == config.stable_hash()


def test_unknown_values_and_secret_redaction_fail_or_hide(tmp_path: Path) -> None:
    config_file = tmp_path / "gaia.yaml"
    config_file.write_text("gaia:\n  unknown: true\n")
    with pytest.raises(ValidationError):
        load_config(config_file)
    secret = SecretRef(env="API_KEY")
    assert secret.redacted() == {"env": "API_KEY"}
    with pytest.raises(ValidationError):
        SecretRef(env="A", file="/tmp/a")


def test_secret_reference_identity_affects_hash_without_resolving_value() -> None:
    from gaia.config import GaiaApplicationConfig

    first = GaiaApplicationConfig(model={"api_key": {"file": "/run/secrets/first"}})
    second = GaiaApplicationConfig(model={"api_key": {"file": "/run/secrets/second"}})

    assert first.stable_hash() != second.stable_hash()
    assert first.redacted()["model"]["api_key"] == {"file": "***"}
    with pytest.raises(ValidationError):
        SecretRef()


def test_starter_defaults_are_lowest_priority_and_origin_marked(tmp_path: Path) -> None:
    config_file = tmp_path / "gaia.yaml"
    config_file.write_text("gaia: {}\n")
    config, origins, _ = load_config(
        config_file, starter_defaults={"model": {"base_url": "http://starter"}}
    )
    assert config.model.base_url == "http://starter"
    assert origins["model.base_url"] == ConfigOrigin.STARTER_DEFAULT


def test_runtime_environment_has_safe_write_defaults() -> None:
    assert GaiaApplicationConfig().runtime.effective_write_mode() == WriteMode.ENABLED
    sandbox = GaiaApplicationConfig(runtime={"environment": "sandbox"})
    customer = GaiaApplicationConfig(
        runtime={
            "environment": "customer",
            "execution": {"provider": "temporal"},
        }
    )

    assert sandbox.runtime.environment == RunMode.SANDBOX
    assert sandbox.runtime.effective_write_mode() == WriteMode.APPROVAL_REQUIRED
    assert customer.runtime.environment == RunMode.CUSTOMER
    assert customer.runtime.effective_write_mode() == WriteMode.DISABLED


def test_sandbox_rejects_unattended_write_mode() -> None:
    with pytest.raises(ValidationError, match="sandbox runtime.write_mode cannot be enabled"):
        GaiaApplicationConfig(runtime={"environment": "sandbox", "write_mode": "enabled"})


def test_customer_environment_requires_temporal() -> None:
    with pytest.raises(ValidationError, match="customer runtime requires"):
        GaiaApplicationConfig(
            runtime={"environment": "customer", "execution": {"provider": "in_process"}}
        )


def test_profile_can_activate_server_owned_sandbox_environment(tmp_path: Path) -> None:
    config_file = tmp_path / "gaia.yaml"
    config_file.write_text(
        "gaia:\n"
        "  profile: mock\n"
        "  runtime: {environment: mock}\n"
        "  profiles:\n"
        "    sandbox:\n"
        "      runtime: {environment: sandbox, write_mode: approval_required}\n"
    )

    config, origins, _ = load_config(
        config_file,
        environ={"GAIA__PROFILE": "sandbox"},
    )

    assert config.profile == "sandbox"
    assert config.runtime.environment == RunMode.SANDBOX
    assert config.runtime.effective_write_mode() == WriteMode.APPROVAL_REQUIRED
    assert origins["runtime.environment"] == ConfigOrigin.PROFILE


def test_config_path_precedence_and_legacy_migration(
    tmp_path: Path,
) -> None:
    explicit = tmp_path / "explicit.yaml"
    configured = tmp_path / "configured.yaml"
    legacy = tmp_path / "legacy.yaml"

    assert (
        resolve_config_path(
            explicit,
            environ={
                "GAIA_CONFIG_PATH": str(configured),
                "GAIA_CONFIG": str(legacy),
            },
        )
        == explicit.resolve()
    )
    assert (
        resolve_config_path(
            environ={"GAIA_CONFIG_PATH": str(configured), "GAIA_CONFIG": str(legacy)}
        )
        == configured.resolve()
    )
    with pytest.warns(DeprecationWarning, match="use GAIA_CONFIG_PATH"):
        assert resolve_config_path(environ={"GAIA_CONFIG": str(legacy)}) == legacy.resolve()


def test_scenarios_modules_parsed_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "gaia.yaml"
    config_file.write_text(
        "gaia:\n  scenarios:\n    modules: [myapp.flows, myapp.tools]\n"
    )
    config, _, _ = load_config(config_file)
    assert config.scenarios.modules == ("myapp.flows", "myapp.tools")


def test_scenarios_modules_default_to_empty_tuple() -> None:
    assert GaiaApplicationConfig().scenarios.modules == ()


def test_scenarios_modules_change_affects_stable_hash() -> None:
    first = GaiaApplicationConfig(scenarios={"modules": ["myapp.flows"]})
    second = GaiaApplicationConfig(scenarios={"modules": ["myapp.tools"]})

    assert first.stable_hash() != second.stable_hash()


def test_runtime_execution_defaults_to_in_process() -> None:
    execution = GaiaApplicationConfig().runtime.execution

    assert execution.provider == "in_process"


def test_removed_local_provider_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Input should be 'in_process' or 'temporal'"):
        GaiaApplicationConfig(runtime={"execution": {"provider": "local"}})


def test_removed_execution_topology_is_rejected() -> None:
    with pytest.raises(ValidationError, match="topology"):
        GaiaApplicationConfig(runtime={"execution": {"topology": "distributed"}})


def test_removed_top_level_runtime_provider_is_rejected() -> None:
    with pytest.raises(ValueError):
        GaiaApplicationConfig(runtime={"provider": "temporal"})


def test_runtime_execution_temporal_connection_defaults() -> None:
    settings = GaiaApplicationConfig().runtime.execution

    assert settings.server_address == "127.0.0.1:7233"
    assert settings.tls_enabled is False


def test_runtime_execution_can_override_temporal_connection_settings() -> None:
    config = GaiaApplicationConfig(
        runtime={"execution": {"server_address": "127.0.0.1:8233", "tls_enabled": True}}
    )

    assert config.runtime.execution.server_address == "127.0.0.1:8233"
    assert config.runtime.execution.tls_enabled is True


def test_langfuse_observability_requires_and_redacts_secret_refs() -> None:
    config = GaiaApplicationConfig(
        observability={
            "provider": "langfuse",
            "base_url": "https://langfuse.example.com",
            "public_key": {"env": "LANGFUSE_PUBLIC_KEY"},
            "secret_key": {"file": "/run/secrets/langfuse"},
        }
    )

    assert config.observability.provider == "langfuse"
    assert config.redacted()["observability"]["public_key"] == {
        "env": "LANGFUSE_PUBLIC_KEY"
    }
    assert config.redacted()["observability"]["secret_key"] == {"file": "***"}
    with pytest.raises(
        ValidationError,
        match="langfuse observability requires observability.public_key",
    ):
        GaiaApplicationConfig(
            observability={
                "provider": "langfuse",
                "secret_key": {"env": "LANGFUSE_SECRET_KEY"},
            }
        )
    with pytest.raises(ValidationError):
        GaiaApplicationConfig(
            observability={"environment": "Production With Spaces"}
        )


def test_control_and_secret_environment_variables_are_not_misreported_as_overrides(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "gaia.yaml"
    config_file.write_text("gaia: {}\n")

    _, _, warnings_out = load_config(
        config_file,
        environ={
            "GAIA_CONFIG_PATH": str(config_file),
            "GAIA_API_KEY": "secret",
            "GAIA_MODEL_API_KEY": "secret",
        },
    )

    assert warnings_out == []
