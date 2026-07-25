"""YAML/profile/environment/CLI configuration loading with source tracking."""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from gaia.config.models import ConfigOrigin, GaiaApplicationConfig

_DEPRECATED_ENV_OVERRIDES = {
    "GAIA_MODE": "GAIA__RUNTIME__ENVIRONMENT",
    "GAIA_DATABASE_URL": "GAIA__RUNTIME__DATABASE_URL",
    "GAIA_MODEL_PROVIDER": "GAIA__MODEL__PROVIDER",
    "GAIA_MODEL_BASE_URL": "GAIA__MODEL__BASE_URL",
    "GAIA_MODEL_ID": "GAIA__MODEL__MODEL_ID",
}


def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        result[key] = (
            _merge(result[key], value)
            if isinstance(value, Mapping) and isinstance(result.get(key), dict)
            else value
        )
    return result


def _set(data: dict[str, Any], path: list[str], value: Any) -> None:
    current = data
    for item in path[:-1]:
        current = current.setdefault(item, {})
    current[path[-1]] = value


def _parse(value: str) -> Any:
    return yaml.safe_load(value)


def _leaves(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, Mapping):
        leaves: set[str] = set()
        for key, item in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else key
            leaves.update(_leaves(item, nested_prefix))
        return leaves
    return {prefix}


def _layer(data: dict[str, Any], origin: ConfigOrigin) -> dict[str, ConfigOrigin]:
    return {path: origin for path in _leaves(data)}


def _apply_environment(
    data: dict[str, Any], environment: Mapping[str, str]
) -> tuple[dict[str, ConfigOrigin], list[str]]:
    origins: dict[str, ConfigOrigin] = {}
    warnings_out: list[str] = []
    for key, value in environment.items():
        if key.startswith("GAIA__"):
            path_parts = [part.lower() for part in key[6:].split("__")]
            _set(data, path_parts, _parse(value))
            origins[".".join(path_parts)] = ConfigOrigin.ENVIRONMENT
        elif replacement := _DEPRECATED_ENV_OVERRIDES.get(key):
            warnings_out.append(f"{key} is deprecated; use {replacement}")
    return origins, warnings_out


def resolve_config_path(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the application config path with one consistent precedence."""
    if path is not None:
        return path.expanduser().resolve()
    environment = os.environ if environ is None else environ
    configured = environment.get("GAIA_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    legacy = environment.get("GAIA_CONFIG")
    if legacy:
        warnings.warn(
            "GAIA_CONFIG is deprecated; use GAIA_CONFIG_PATH",
            DeprecationWarning,
            stacklevel=2,
        )
        return Path(legacy).expanduser().resolve()
    return Path("gaia.yaml").resolve()


def load_config(
    path: Path,
    *,
    overrides: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    starter_defaults: dict[str, Any] | None = None,
) -> tuple[GaiaApplicationConfig, dict[str, ConfigOrigin], list[str]]:
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("gaia", {}), dict):
        raise ValueError("gaia.yaml must contain a gaia mapping")
    raw_data = dict(raw["gaia"])
    profiles = raw_data.pop("profiles", {})
    environment = os.environ if environ is None else environ
    # Profile selectors are evaluated before profile content is merged.
    profile = raw_data.get("profile", "mock")
    if "GAIA__PROFILE" in environment:
        profile = str(_parse(environment["GAIA__PROFILE"]))
    for override in overrides or []:
        if override.startswith("profile="):
            profile = str(_parse(override.partition("=")[2]))
    data = _merge({}, starter_defaults or {})
    origins = _layer(data, ConfigOrigin.STARTER_DEFAULT)
    data = _merge(data, raw_data)
    origins.update(_layer(raw_data, ConfigOrigin.YAML))
    data["profile"] = profile
    if profile in profiles:
        data = _merge(data, profiles[profile])
        origins.update(_layer(profiles[profile], ConfigOrigin.PROFILE))
    environment_origins, warnings_out = _apply_environment(data, environment)
    origins.update(environment_origins)
    for message in warnings_out:
        warnings.warn(message, DeprecationWarning, stacklevel=2)
    for override in overrides or []:
        key, separator, value = override.partition("=")
        if not separator:
            raise ValueError(f"invalid override: {override}")
        path_parts = key.split(".")
        _set(data, path_parts, _parse(value))
        origins[".".join(path_parts)] = ConfigOrigin.CLI
    config = GaiaApplicationConfig.model_validate(data)
    final_leaves = _leaves(config.model_dump(mode="json", by_alias=True))
    complete = {leaf: ConfigOrigin.DEFAULT for leaf in final_leaves}
    for origin_path, origin in origins.items():
        for leaf in final_leaves:
            if leaf == origin_path or leaf.startswith(f"{origin_path}."):
                complete[leaf] = origin
    return config, complete, warnings_out
