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
    customer = GaiaApplicationConfig(runtime={"environment": "customer"})

    assert sandbox.runtime.environment == RunMode.SANDBOX
    assert sandbox.runtime.effective_write_mode() == WriteMode.APPROVAL_REQUIRED
    assert customer.runtime.environment == RunMode.CUSTOMER
    assert customer.runtime.effective_write_mode() == WriteMode.DISABLED


def test_sandbox_rejects_unattended_write_mode() -> None:
    with pytest.raises(ValidationError, match="sandbox runtime.write_mode cannot be enabled"):
        GaiaApplicationConfig(runtime={"environment": "sandbox", "write_mode": "enabled"})


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

    assert resolve_config_path(
        explicit,
        environ={
            "GAIA_CONFIG_PATH": str(configured),
            "GAIA_CONFIG": str(legacy),
        },
    ) == explicit.resolve()
    assert resolve_config_path(
        environ={"GAIA_CONFIG_PATH": str(configured), "GAIA_CONFIG": str(legacy)}
    ) == configured.resolve()
    with pytest.warns(DeprecationWarning, match="use GAIA_CONFIG_PATH"):
        assert resolve_config_path(environ={"GAIA_CONFIG": str(legacy)}) == legacy.resolve()


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
