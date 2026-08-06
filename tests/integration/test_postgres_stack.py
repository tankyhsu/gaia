from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.types import Command
from sqlalchemy import func, select, text

from examples.controlled_task.workflow import build_controlled_task_graph
from gaia.capabilities.outbox import OutboxDispatcher, SqlAlchemyOutboxStore
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import RunMode
from gaia.integrations.events import InProcessEventPublisher
from gaia.integrations.prompt_postgres import PostgresPromptRegistry
from gaia.model_gateway import embedding_function_from_config
from gaia.persistence import GaiaPersistenceResources
from gaia.persistence.audit import SqlAlchemyAuditProjection
from gaia.persistence.database import dispose_session_factory, initialize_database
from gaia.persistence.migrate import current_head, upgrade_database
from gaia.persistence.models import OutboxEventRecord, ReplayJobRecord
from gaia.rag import (
    FixedWindowChunker,
    LocalFileDocumentLoader,
    MemoryRagRepository,
    RagPipeline,
    Utf8TextParser,
)
from gaia.spi.events import EventEnvelope
from gaia.spi.prompt import PromptArtifact, PromptRef, PromptValidation
from gaia.spi.rag import DocumentAccess, DocumentSource, IngestionStatus, RetrievalRequest

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
RUN_EXTERNAL_TESTS = os.environ.get("RUN_EXTERNAL_TESTS") == "1"
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not set"),
]


def _embed(texts: Sequence[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for value in texts:
        lowered = value.lower()
        vectors.append(
            [
                float("invoice" in lowered or "billing" in lowered),
                float("employee" in lowered or "people" in lowered),
                float("machine" in lowered or "factory" in lowered),
                0.01,
            ]
            + [0.0] * 60
        )
    return vectors


def _config() -> GaiaApplicationConfig:
    assert POSTGRES_URL is not None
    return GaiaApplicationConfig.model_validate(
        {
            "runtime": {"database_url": POSTGRES_URL},
            "stores": {
                "operational": {"provider": "postgres", "auto_create": False},
                "checkpoint": {
                    "provider": "postgres",
                    "pool_min_size": 1,
                    "pool_max_size": 3,
                },
                "memory": {
                    "provider": "postgres",
                    "pool_min_size": 1,
                    "pool_max_size": 3,
                },
                "vector": {
                    "provider": "pgvector",
                    "dimensions": 64,
                    "fields": ["text"],
                },
            },
        }
    )


def _write_state(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "request_text": "pause res-001 because maintenance",
        "intent": {
            "operation": "set_status",
            "resource_id": "res-001",
            "target_status": "paused",
            "reason": "maintenance",
        },
        "user": {"id": "operator", "organization": "org-alpha", "roles": ["operator"]},
        "resource": {
            "resource_id": "res-001",
            "organization": "org-alpha",
            "status": "active",
            "readable_roles": ["reader", "operator"],
        },
        "context_gaps": [],
        "gate_id": f"gate-{run_id}",
        "visited": [],
    }


async def test_postgres_operational_transactions_and_migration() -> None:
    assert POSTGRES_URL is not None
    await asyncio.to_thread(upgrade_database, POSTGRES_URL)
    factory = await initialize_database(POSTGRES_URL, auto_create=False)
    committed_id = f"committed-{uuid4()}"
    rolled_back_id = f"rolled-back-{uuid4()}"
    try:
        async with factory.begin() as session:
            session.add(
                ReplayJobRecord(
                    replay_id=committed_id,
                    status="completed",
                    total=1,
                    passed=1,
                    failed=0,
                    created_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
            )
        async with factory() as session:
            transaction = await session.begin()
            session.add(
                ReplayJobRecord(
                    replay_id=rolled_back_id,
                    status="completed",
                    total=1,
                    passed=1,
                    failed=0,
                    created_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
            )
            await transaction.rollback()
        async with factory() as session:
            committed = await session.scalar(
                select(func.count())
                .select_from(ReplayJobRecord)
                .where(ReplayJobRecord.replay_id == committed_id)
            )
            rolled_back = await session.scalar(
                select(func.count())
                .select_from(ReplayJobRecord)
                .where(ReplayJobRecord.replay_id == rolled_back_id)
            )
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
        assert committed == 1
        assert rolled_back == 0
        # Assert against whatever head the migration scripts directory itself reports,
        # not a hardcoded revision string -- a literal here goes stale on every new
        # migration (it previously pinned "0010_business_builder_runtime" while the real
        # head had already moved to "0014_runtime_leases").
        assert version == current_head(POSTGRES_URL)
    finally:
        await dispose_session_factory(factory)


async def test_postgres_prompt_registry_publishes_and_resolves_environment_pointer() -> None:
    assert POSTGRES_URL is not None
    await asyncio.to_thread(upgrade_database, POSTGRES_URL)
    factory = await initialize_database(POSTGRES_URL, auto_create=False)
    registry = PostgresPromptRegistry(factory)
    prompt_id = f"postgres-prompt-{uuid4()}"
    artifact = PromptArtifact(
        prompt_id=prompt_id,
        version="1.0.0",
        messages=({"role": "system", "content": "PostgreSQL integration."},),
    )
    try:
        await registry.import_draft(artifact, actor="integration")
        await registry.validate(
            artifact.ref,
            PromptValidation(
                passed=True,
                dataset_id="postgres-golden",
                dataset_version="1",
                report_id=f"report-{uuid4()}",
                gate_ids=("pass-rate",),
            ),
            actor="integration-qa",
        )
        await registry.publish(artifact.ref, RunMode.SANDBOX, actor="integration-release")

        resolved = await registry.resolve(
            PromptRef(prompt_id=prompt_id, environment=RunMode.SANDBOX)
        )

        assert resolved.version_id == artifact.version_id
    finally:
        await dispose_session_factory(factory)


async def test_postgres_outbox_claims_are_concurrent_safe_and_dispatchable() -> None:
    assert POSTGRES_URL is not None
    await asyncio.to_thread(upgrade_database, POSTGRES_URL)
    factory = await initialize_database(POSTGRES_URL, auto_create=False)
    store = SqlAlchemyOutboxStore(factory)
    delivered: list[str] = []
    publisher = InProcessEventPublisher()

    async def capture(event: EventEnvelope) -> None:
        delivered.append(event.event_id)

    publisher.subscribe("integration.events", capture)
    events = [
        EventEnvelope(
            topic="integration.events",
            event_type="integration.created",
            key=str(uuid4()),
            payload={"index": index},
        )
        for index in range(2)
    ]
    try:
        async with factory.begin() as session:
            for event in events:
                await store.enqueue(session, event)

        first, second = await asyncio.gather(
            store.claim_batch(worker_id="postgres-worker-1", batch_size=1, lease_seconds=30),
            store.claim_batch(worker_id="postgres-worker-2", batch_size=1, lease_seconds=30),
        )
        claims = [*first, *second]
        assert len(claims) == 2
        assert len({claim.event.event_id for claim in claims}) == 2

        for worker_id, worker_claims in (
            ("postgres-worker-1", first),
            ("postgres-worker-2", second),
        ):
            for claim in worker_claims:
                await store.mark_failed(
                    claim.event.event_id,
                    worker_id=worker_id,
                    error="release for dispatcher",
                    max_attempts=8,
                    retry_delay_seconds=0,
                )

        dispatcher = OutboxDispatcher(store, publisher, worker_id="postgres-dispatcher")
        report = await dispatcher.dispatch_once()
        assert report.published == 2
        assert set(delivered) == {event.event_id for event in events}
        async with factory() as session:
            published = await session.scalars(
                select(OutboxEventRecord.status).where(
                    OutboxEventRecord.event_id.in_([event.event_id for event in events])
                )
            )
        assert set(published) == {"published"}
    finally:
        await dispose_session_factory(factory)


async def test_postgres_rag_ingests_replaces_filters_and_cites(tmp_path: Path) -> None:
    corpus_id = f"rag-{uuid4()}"
    document = tmp_path / "policy.md"
    document.write_text("Invoice requests require finance approval.", encoding="utf-8")
    resources = GaiaPersistenceResources(_config(), embed=_embed)
    async with resources.lifespan():
        assert resources.memory is not None
        pipeline = RagPipeline(
            LocalFileDocumentLoader(tmp_path),
            Utf8TextParser(),
            FixedWindowChunker(chunk_size=128, overlap=16),
            MemoryRagRepository(resources.memory, candidate_multiplier=10),
        )
        first_source = DocumentSource(
            document_id="policy",
            tenant_id="tenant-integration",
            corpus_id=corpus_id,
            version="1.0.0",
            uri="policy.md",
            media_type="text/markdown",
            access=DocumentAccess(allowed_roles=("finance",)),
        )
        created = await pipeline.ingest(first_source)
        unchanged = await pipeline.ingest(first_source)
        authorized = await pipeline.retrieve(
            RetrievalRequest(
                tenant_id="tenant-integration",
                corpus_id=corpus_id,
                query="invoice approval",
                user_id="finance-user",
                roles=("finance",),
            )
        )
        denied = await pipeline.retrieve(
            RetrievalRequest(
                tenant_id="tenant-integration",
                corpus_id=corpus_id,
                query="invoice approval",
                user_id="engineering-user",
                roles=("engineering",),
            )
        )
        document.write_text("Factory machines require weekly inspection.", encoding="utf-8")
        replaced = await pipeline.ingest(first_source.model_copy(update={"version": "2.0.0"}))
        current = await pipeline.retrieve(
            RetrievalRequest(
                tenant_id="tenant-integration",
                corpus_id=corpus_id,
                query="factory machine",
                user_id="finance-user",
                roles=("finance",),
            )
        )
        deleted = await pipeline.delete(
            tenant_id="tenant-integration",
            corpus_id=corpus_id,
            document_id="policy",
        )

        assert created.status == IngestionStatus.CREATED
        assert unchanged.status == IngestionStatus.UNCHANGED
        assert authorized[0].citation.permission_basis == "role:finance"
        assert authorized[0].citation.document_version == "1.0.0"
        assert denied == ()
        assert replaced.status == IngestionStatus.REPLACED
        assert current[0].citation.document_version == "2.0.0"
        assert deleted.status == IngestionStatus.DELETED


async def test_postgres_checkpoint_survives_provider_restart() -> None:
    run_id = f"checkpoint-{uuid4()}"
    config = {"configurable": {"thread_id": run_id}}
    first = GaiaPersistenceResources(_config(), embed=_embed)
    async with first.lifespan():
        paused = build_controlled_task_graph(first.checkpointer).invoke(
            _write_state(run_id), config
        )
        assert paused["outcome"] == "approval"
        assert "execute_side_effect" not in paused["visited"]

    restarted = GaiaPersistenceResources(_config(), embed=_embed)
    async with restarted.lifespan():
        resumed = build_controlled_task_graph(restarted.checkpointer).invoke(
            Command(resume={"decision": "approved"}), config
        )
        assert resumed["approval_decision"] == "approved"
        assert "execute_side_effect" in resumed["visited"]
        assert resumed["visited"][-1] == "finalize"


async def test_postgres_memory_filter_vector_search_and_restart() -> None:
    namespace = ("integration", str(uuid4()))
    resources = GaiaPersistenceResources(_config(), embed=_embed)
    async with resources.lifespan():
        assert resources.memory is not None
        await resources.memory.put(
            namespace,
            "billing",
            {"text": "invoice billing policy", "department": "finance"},
        )
        await resources.memory.put(
            namespace,
            "people",
            {"text": "employee people handbook", "department": "hr"},
        )
        exact = await resources.memory.get(namespace, "billing")
        filtered = await resources.memory.search(namespace, filters={"department": "finance"})
        semantic = await resources.memory.search(namespace, query="invoice question", limit=1)
        assert exact is not None and exact.value["department"] == "finance"
        assert [item.key for item in filtered] == ["billing"]
        assert [item.key for item in semantic] == ["billing"]

    restarted = GaiaPersistenceResources(_config(), embed=_embed)
    async with restarted.lifespan():
        assert restarted.memory is not None
        persisted = await restarted.memory.get(namespace, "billing")
        assert persisted is not None
        await restarted.memory.delete(namespace, "billing")
        assert await restarted.memory.get(namespace, "billing") is None

    assert POSTGRES_URL is not None
    factory = await initialize_database(POSTGRES_URL, auto_create=False)
    try:
        async with factory() as session:
            vector_extension = await session.scalar(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
        assert vector_extension == "vector"
    finally:
        await dispose_session_factory(factory)



async def test_postgres_pgvector_with_configured_siliconflow_embedding() -> None:
    payload = _config().model_dump(mode="python")
    payload["embedding"] = {
        "provider": "openai-compatible",
        "model_id": "Qwen/Qwen3-Embedding-0.6B",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": {"env": "SILICONFLOW_API_KEY"},
        "dimensions": 64,
        "batch_size": 8,
        "timeout_seconds": 30,
    }
    config = GaiaApplicationConfig.model_validate(payload)
    resources = GaiaPersistenceResources(
        config,
        embed=embedding_function_from_config(config),
    )
    namespace = ("siliconflow", str(uuid4()))
    async with resources.lifespan():
        assert resources.memory is not None
        await resources.memory.put(
            namespace,
            "finance",
            {"text": "员工取得发票后提交财务报销申请"},
        )
        await resources.memory.put(
            namespace,
            "maintenance",
            {"text": "工厂设备需要定期停机保养和维修"},
        )
        result = await resources.memory.search(
            namespace,
            query="财务发票应该怎样报销",
            limit=1,
        )
        assert [item.key for item in result] == ["finance"]


async def test_audit_projection_pages_the_same_way_on_postgres() -> None:
    """Keyset paging must mean the same thing on both dialects.

    SQLite hands back naive datetimes and PostgreSQL hands back aware ones, and
    the cursor compares those values directly. That single normalization is the
    only cross-dialect assumption the audit store makes, so it is worth proving
    against a real PostgreSQL rather than inferring it from the SQLite suite.
    """

    assert POSTGRES_URL is not None
    await asyncio.to_thread(upgrade_database, POSTGRES_URL)
    factory = await initialize_database(POSTGRES_URL, auto_create=False)
    projection = SqlAlchemyAuditProjection(factory)
    organization = f"paging-{uuid4().hex[:8]}"
    other = f"other-{uuid4().hex[:8]}"

    def snapshot(index: int, owner: str) -> dict[str, object]:
        stamp = f"2026-07-29T00:00:{index:02d}+00:00"
        return {
            "run_id": f"{owner}-run-{index:02d}",
            "scenario_id": "ticket.prepare",
            "mode": "mock",
            "status": "succeeded",
            "user": {"id": "alice", "organization": owner, "roles": ["user"]},
            "version_bundle": {"policy": "p:1.0.0"},
            "created_at": stamp,
            "updated_at": stamp,
        }

    try:
        for index in range(1, 13):
            await projection.record(snapshot=snapshot(index, organization), events=[], gates=[])
        await projection.record(snapshot=snapshot(1, other), events=[], gates=[])

        walked: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            page = await projection.list_runs(
                organization=organization, limit=5, cursor=cursor
            )
            walked.extend(str(item["run_id"]) for item in page["items"])
            pages += 1
            cursor = page["next_cursor"]
            if cursor is None:
                break
            assert pages < 20, "pagination did not terminate"

        single = await projection.list_runs(organization=organization, limit=100)

        assert walked == [str(item["run_id"]) for item in single["items"]]
        assert len(walked) == len(set(walked)) == 12
        assert walked == sorted(walked, reverse=True)
        assert pages == 3
        assert all(not run_id.startswith(other) for run_id in walked)
    finally:
        await dispose_session_factory(factory)
