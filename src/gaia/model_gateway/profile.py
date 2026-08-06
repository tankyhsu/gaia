"""Construct a `ModelEndpointProfile` from `GaiaApplicationConfig.model`.

Every declarative scenario that calls `ctx.model.generate_structured(...)` /
`ctx.model.generate_stream(...)` needs a `ModelEndpointProfile` (defined in
`gaia.contracts.models`) to pass as the `profile` argument. Without this helper, every
application would have to hand-write one (see any reference application's own
`model_profile()`-style helper for what that looks like without this). `config.model`
already carries
`provider` / `model_id` / `base_url` / `api_key` / `timeout_seconds`; this helper fills
in the two fields `ModelEndpointProfile` needs beyond that -- `protocol` and
`capabilities` -- from the same settings.

Note: `ModelEndpointProfile` has no `api_key` field (see `contracts/models.py`), so this
helper never resolves the `SecretRef` in `config.model.api_key`. That resolution happens
where the key is actually consumed -- passed into the `OpenAICompatibleProvider`
constructor by the `model-openai-compatible` Starter (`gaia.starters.builtin`) -- so the
resolved secret lives only inside that provider instance, never in a value this helper
returns or that a `ComponentDescriptor` stores.
"""

from __future__ import annotations

from typing import Literal

from gaia.config.models import GaiaApplicationConfig
from gaia.contracts.models import ModelCapabilities, ModelEndpointProfile


def model_endpoint_profile_from_config(config: GaiaApplicationConfig) -> ModelEndpointProfile:
    settings = config.model
    is_mock = settings.provider == "mock"
    protocol: Literal["openai-compatible", "mock"] = "mock" if is_mock else "openai-compatible"
    return ModelEndpointProfile(
        provider_id=settings.provider,
        protocol=protocol,
        base_url=settings.base_url,
        model_id=settings.model_id,
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=not is_mock,
            max_context_tokens=None,
        ),
        data_residency="local" if is_mock else "external",
        timeout_seconds=settings.timeout_seconds,
    )
