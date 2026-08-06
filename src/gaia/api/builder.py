"""High-level composition facade for function-based Gaia applications."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from fastapi import FastAPI

from gaia._authoring.scenario import ScenarioHandler
from gaia.api.app import ApiDependencies, create_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.spi.guardrail import ContentGuardrail, GuardrailStage
from gaia.spi.model import ModelProvider
from gaia.spi.prompt import PromptProvider
from gaia.spi.rag import Retriever
from gaia.spi.tool import ToolHandler


@dataclass
class GaiaAppBuilder:
    """Collect public application capabilities without exposing Runtime internals."""

    config: GaiaApplicationConfig
    _scenarios: list[ScenarioHandler] = field(default_factory=list)
    _tools: list[ToolHandler] = field(default_factory=list)
    _model: ModelProvider | None = None
    _retriever: Retriever | Callable[[], Retriever] | None = None
    _prompt_provider: PromptProvider | Callable[[], PromptProvider] | None = None
    _guardrails: dict[GuardrailStage, list[ContentGuardrail]] = field(default_factory=dict)
    _handoff_handlers: dict[str, ScenarioHandler] = field(default_factory=dict)
    _continuation_handlers: dict[str, ScenarioHandler] = field(default_factory=dict)
    _allowed_handoffs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _max_handoffs: int = 4
    _output_correction_attempts: int = 0

    def scenarios(self, *handlers: ScenarioHandler) -> GaiaAppBuilder:
        self._scenarios.extend(handlers)
        return self

    def tools(self, *handlers: ToolHandler) -> GaiaAppBuilder:
        self._tools.extend(handlers)
        return self

    def model(self, provider: ModelProvider) -> GaiaAppBuilder:
        self._model = provider
        return self

    def retrieval(
        self,
        retriever: Retriever | Callable[[], Retriever],
    ) -> GaiaAppBuilder:
        self._retriever = retriever
        return self

    def prompts(
        self,
        provider: PromptProvider | Callable[[], PromptProvider],
    ) -> GaiaAppBuilder:
        self._prompt_provider = provider
        return self

    def guardrails(
        self,
        *guardrails: ContentGuardrail,
        stages: Iterable[GuardrailStage],
    ) -> GaiaAppBuilder:
        """Bind application-owned controls to explicit runtime stages."""

        selected = tuple(GuardrailStage(stage) for stage in stages)
        if not selected:
            raise ValueError("at least one guardrail stage is required")
        for stage in selected:
            self._guardrails.setdefault(stage, []).extend(guardrails)
        return self

    def tool_guardrails(self, *guardrails: ContentGuardrail) -> GaiaAppBuilder:
        """Compatibility binding for retrieval and both tool boundaries."""

        self.guardrails(
            *guardrails,
            stages=(
                GuardrailStage.RETRIEVAL,
                GuardrailStage.TOOL_INPUT,
                GuardrailStage.TOOL_OUTPUT,
            ),
        )
        return self

    def handoffs(
        self,
        handlers: Mapping[str, ScenarioHandler],
        *,
        routes: Mapping[str, tuple[str, ...]],
        max_handoffs: int = 4,
    ) -> GaiaAppBuilder:
        """Register Runtime-persisted Agent handlers and their explicit routes."""

        if max_handoffs < 0:
            raise ValueError("max_handoffs must be non-negative")
        self._handoff_handlers = dict(handlers)
        self._allowed_handoffs = dict(routes)
        self._max_handoffs = max_handoffs
        return self

    def continuations(
        self,
        handlers: Mapping[str, ScenarioHandler],
    ) -> GaiaAppBuilder:
        """Register named handlers invoked after a write or action plan succeeds."""

        self._continuation_handlers = dict(handlers)
        return self

    def structured_output_correction(self, *, max_attempts: int = 1) -> GaiaAppBuilder:
        """Enable bounded correction for schema or explicitly correctable output failures."""

        if max_attempts < 0:
            raise ValueError("max_attempts must be non-negative")
        self._output_correction_attempts = max_attempts
        return self

    def dependencies(self) -> ApiDependencies:
        if not self._scenarios:
            raise ValueError("at least one scenario must be registered")
        return ApiDependencies.from_scenarios(
            self.config,
            *self._scenarios,
            tools=self._tools,
            model_provider=self._model,
            retriever=self._retriever,
            guardrails=self._guardrails,
            prompt_provider=self._prompt_provider,
            handoff_handlers=self._handoff_handlers,
            continuation_handlers=self._continuation_handlers,
            allowed_handoffs=self._allowed_handoffs,
            max_handoffs=self._max_handoffs,
            output_correction_attempts=self._output_correction_attempts,
        )

    def build(
        self,
        *,
        database_url: str | None = None,
        api_key: str | None = None,
        enable_devtools: bool | None = None,
    ) -> FastAPI:
        return create_app(
            database_url=database_url,
            api_key=api_key,
            dependencies=self.dependencies(),
            gaia_application=GaiaApplication(self.config),
            enable_devtools=enable_devtools,
        )


def register_all(
    builder: GaiaAppBuilder,
    *,
    scenarios: Iterable[ScenarioHandler] = (),
    tools: Iterable[ToolHandler] = (),
) -> GaiaAppBuilder:
    """Register iterable modules while keeping the fluent API concise."""

    return builder.scenarios(*scenarios).tools(*tools)
