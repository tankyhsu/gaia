"""Run-scoped retrieval with identity binding and retrieval-stage guardrails."""

from __future__ import annotations

from gaia.contracts.models import ErrorCode, RunRequest
from gaia.guardrails import GuardrailPipeline, GuardrailViolation
from gaia.spi.guardrail import GuardrailContext, GuardrailStage
from gaia.spi.rag import RetrievalHit, RetrievalRequest, Retriever

from .tool_execution import ToolExecutionError


class ScopedRetriever:
    """Bind application retrieval to the authenticated Run identity."""

    def __init__(
        self,
        retriever: Retriever,
        *,
        run_id: str,
        request: RunRequest,
        guardrails: GuardrailPipeline | None = None,
    ) -> None:
        self._retriever = retriever
        self._run_id = run_id
        self._request = request
        self._guardrails = guardrails

    async def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]:
        identity = self._request.user
        if (
            request.tenant_id != identity.organization
            or request.user_id != identity.id
            or not set(request.roles).issubset(identity.roles)
        ):
            raise ToolExecutionError(ErrorCode.FORBIDDEN)
        hits = await self._retriever.retrieve(request)
        if self._guardrails is None:
            return hits
        guarded_hits = []
        for hit in hits:
            try:
                text = await self._guardrails.evaluate(
                    hit.text,
                    GuardrailContext(
                        stage=GuardrailStage.RETRIEVAL,
                        run_id=self._run_id,
                        scenario_id=self._request.scenario_id,
                        metadata={
                            "document_id": hit.citation.document_id,
                            "chunk_id": hit.citation.chunk_id,
                        },
                    ),
                )
            except GuardrailViolation as error:
                raise ToolExecutionError(ErrorCode.GUARDRAIL_BLOCKED) from error
            guarded_hits.append(hit.model_copy(update={"text": text}))
        return tuple(guarded_hits)
