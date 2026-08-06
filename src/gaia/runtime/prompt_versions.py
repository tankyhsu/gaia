"""Resolve Prompt release selectors into immutable Run version evidence."""

from __future__ import annotations

from collections.abc import Mapping

from gaia.contracts.models import RunRequest, VersionBundle
from gaia.runtime.dependencies import VersionResolutionError
from gaia.spi.prompt import PromptProvider, PromptRef


class PromptRunVersionResolver:
    def __init__(
        self,
        provider: PromptProvider,
        refs: Mapping[str, PromptRef],
    ) -> None:
        self._provider = provider
        self._refs = dict(refs)

    async def resolve(
        self,
        request: RunRequest,
        base: VersionBundle,
    ) -> VersionBundle:
        ref = self._refs.get(request.scenario_id)
        if ref is None:
            return base
        try:
            artifact = await self._provider.resolve(ref)
        except LookupError as error:
            raise VersionResolutionError(
                "PROMPT_NOT_AVAILABLE",
                retryable=False,
            ) from error
        except Exception as error:
            raise VersionResolutionError(
                "PROMPT_PROVIDER_UNAVAILABLE",
                retryable=True,
            ) from error
        return base.model_copy(update={"prompt": artifact.version_id})
