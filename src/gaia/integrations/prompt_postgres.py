"""Transactional Prompt Registry backed by Gaia's SQLAlchemy persistence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gaia.contracts.models import RunMode
from gaia.persistence.database import session_factory_resource
from gaia.persistence.models import (
    PromptAuditRecord,
    PromptReleaseRecord,
    PromptVersionRecord,
)
from gaia.sdk.prompt import (
    PromptArtifact,
    PromptLifecycleStatus,
    PromptRef,
    PromptRelease,
    PromptValidation,
    PromptVersion,
)


class PromptRegistryConflict(ValueError):
    """The requested lifecycle transition conflicts with registry state."""


class PromptRegistryNotFound(LookupError):
    """The requested immutable version or release pointer does not exist."""


class PostgresPromptRegistry:
    """Immutable versions and mutable environment pointers in one database."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def resolve(self, ref: PromptRef) -> PromptArtifact:
        async with self._session_factory() as session:
            record = await self._resolve_record(session, ref)
            return PromptArtifact.model_validate(record.artifact_json)

    async def import_draft(
        self,
        artifact: PromptArtifact,
        *,
        actor: str,
    ) -> PromptVersion:
        now = datetime.now(UTC)
        key = (artifact.prompt_id, artifact.version)
        async with self._session_factory.begin() as session:
            existing = await session.get(PromptVersionRecord, key, with_for_update=True)
            if existing is not None:
                if existing.content_hash != artifact.content_hash:
                    raise PromptRegistryConflict("PROMPT_VERSION_IMMUTABLE")
                return _version(existing)
            record = PromptVersionRecord(
                prompt_id=artifact.prompt_id,
                version=artifact.version,
                content_hash=artifact.content_hash,
                artifact_json=artifact.model_dump(mode="json"),
                status=PromptLifecycleStatus.DRAFT.value,
                validation_json=None,
                created_by=actor,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.add(
                _audit(
                    artifact.prompt_id,
                    version=artifact.version,
                    action="import_draft",
                    actor=actor,
                    details={"content_hash": artifact.content_hash},
                    now=now,
                )
            )
            await session.flush()
            return _version(record)

    async def validate(
        self,
        ref: PromptRef,
        evidence: PromptValidation,
        *,
        actor: str,
    ) -> PromptVersion:
        if not evidence.passed:
            raise PromptRegistryConflict("PROMPT_QUALITY_GATE_FAILED")
        prompt_id, version = _exact(ref)
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            record = await session.get(
                PromptVersionRecord,
                (prompt_id, version),
                with_for_update=True,
            )
            if record is None:
                raise PromptRegistryNotFound(f"PROMPT_NOT_FOUND:{prompt_id}:{version}")
            if record.status == PromptLifecycleStatus.VALIDATING.value:
                if record.validation_json == evidence.model_dump(mode="json"):
                    return _version(record)
                raise PromptRegistryConflict("PROMPT_ALREADY_VALIDATED")
            if record.status != PromptLifecycleStatus.DRAFT.value:
                raise PromptRegistryConflict("PROMPT_VALIDATION_STATE_INVALID")
            record.status = PromptLifecycleStatus.VALIDATING.value
            record.validation_json = evidence.model_dump(mode="json")
            record.updated_at = now
            session.add(
                _audit(
                    prompt_id,
                    version=version,
                    action="validate",
                    actor=actor,
                    details={
                        "dataset_id": evidence.dataset_id,
                        "dataset_version": evidence.dataset_version,
                        "report_id": evidence.report_id,
                        "gate_ids": list(evidence.gate_ids),
                    },
                    now=now,
                )
            )
            await session.flush()
            return _version(record)

    async def publish(
        self,
        ref: PromptRef,
        environment: RunMode,
        *,
        actor: str,
    ) -> PromptRelease:
        prompt_id, version = _exact(ref)
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            version_record = await session.get(
                PromptVersionRecord,
                (prompt_id, version),
                with_for_update=True,
            )
            if version_record is None:
                raise PromptRegistryNotFound(f"PROMPT_NOT_FOUND:{prompt_id}:{version}")
            if version_record.status not in {
                PromptLifecycleStatus.VALIDATING.value,
                PromptLifecycleStatus.PUBLISHED.value,
            }:
                raise PromptRegistryConflict("PROMPT_NOT_VALIDATED")
            if version_record.validation_json is None:
                raise PromptRegistryConflict("PROMPT_QUALITY_EVIDENCE_MISSING")

            release = await session.get(
                PromptReleaseRecord,
                (prompt_id, environment.value),
                with_for_update=True,
            )
            previous = release.version if release is not None else None
            if release is None:
                release = PromptReleaseRecord(
                    prompt_id=prompt_id,
                    environment=environment.value,
                    version=version,
                    content_hash=version_record.content_hash,
                    updated_by=actor,
                    updated_at=now,
                )
                session.add(release)
            else:
                release.version = version
                release.content_hash = version_record.content_hash
                release.updated_by = actor
                release.updated_at = now
            version_record.status = PromptLifecycleStatus.PUBLISHED.value
            version_record.updated_at = now
            session.add(
                _audit(
                    prompt_id,
                    version=version,
                    environment=environment,
                    action="publish",
                    actor=actor,
                    details={"previous_version": previous},
                    now=now,
                )
            )
            await session.flush()
            return _release(release)

    async def retire(self, ref: PromptRef, *, actor: str) -> PromptVersion:
        prompt_id, version = _exact(ref)
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            record = await session.get(
                PromptVersionRecord,
                (prompt_id, version),
                with_for_update=True,
            )
            if record is None:
                raise PromptRegistryNotFound(f"PROMPT_NOT_FOUND:{prompt_id}:{version}")
            if record.status == PromptLifecycleStatus.RETIRED.value:
                return _version(record)
            active = await session.scalar(
                select(PromptReleaseRecord).where(
                    PromptReleaseRecord.prompt_id == prompt_id,
                    PromptReleaseRecord.version == version,
                )
            )
            if active is not None:
                raise PromptRegistryConflict("PROMPT_VERSION_STILL_RELEASED")
            record.status = PromptLifecycleStatus.RETIRED.value
            record.updated_at = now
            session.add(
                _audit(
                    prompt_id,
                    version=version,
                    action="retire",
                    actor=actor,
                    details={},
                    now=now,
                )
            )
            await session.flush()
            return _version(record)

    async def rollback(
        self,
        prompt_id: str,
        environment: RunMode,
        target_version: str,
        *,
        actor: str,
    ) -> PromptRelease:
        target = PromptRef(prompt_id=prompt_id, version=target_version)
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            target_record = await session.get(
                PromptVersionRecord,
                (target.prompt_id, target.version),
                with_for_update=True,
            )
            if target_record is None:
                raise PromptRegistryNotFound(f"PROMPT_NOT_FOUND:{prompt_id}:{target_version}")
            if target_record.status != PromptLifecycleStatus.PUBLISHED.value:
                raise PromptRegistryConflict("PROMPT_ROLLBACK_TARGET_NOT_PUBLISHED")
            release = await session.get(
                PromptReleaseRecord,
                (prompt_id, environment.value),
                with_for_update=True,
            )
            if release is None:
                raise PromptRegistryConflict("PROMPT_RELEASE_NOT_FOUND")
            previous = release.version
            release.version = target_version
            release.content_hash = target_record.content_hash
            release.updated_by = actor
            release.updated_at = now
            session.add(
                _audit(
                    prompt_id,
                    version=target_version,
                    environment=environment,
                    action="rollback",
                    actor=actor,
                    details={"previous_version": previous},
                    now=now,
                )
            )
            await session.flush()
            return _release(release)

    async def versions(self, prompt_id: str) -> tuple[PromptVersion, ...]:
        async with self._session_factory() as session:
            records = (
                await session.scalars(
                    select(PromptVersionRecord)
                    .where(PromptVersionRecord.prompt_id == prompt_id)
                    .order_by(PromptVersionRecord.created_at.desc())
                )
            ).all()
            return tuple(_version(record) for record in records)

    async def releases(self, prompt_id: str) -> tuple[PromptRelease, ...]:
        async with self._session_factory() as session:
            records = (
                await session.scalars(
                    select(PromptReleaseRecord)
                    .where(PromptReleaseRecord.prompt_id == prompt_id)
                    .order_by(PromptReleaseRecord.environment)
                )
            ).all()
            return tuple(_release(record) for record in records)

    async def _resolve_record(
        self,
        session: AsyncSession,
        ref: PromptRef,
    ) -> PromptVersionRecord:
        if ref.experiment is not None:
            raise ValueError("prompt experiments are not available in M2")
        if ref.version is not None:
            record = await session.get(PromptVersionRecord, (ref.prompt_id, ref.version))
        else:
            assert ref.environment is not None
            release = await session.get(
                PromptReleaseRecord,
                (ref.prompt_id, ref.environment.value),
            )
            if release is None:
                raise PromptRegistryNotFound(
                    f"PROMPT_RELEASE_NOT_FOUND:{ref.prompt_id}:{ref.environment.value}"
                )
            record = await session.get(
                PromptVersionRecord,
                (ref.prompt_id, release.version),
            )
        if record is None:
            selector = ref.version or ref.environment or ref.experiment
            raise PromptRegistryNotFound(f"PROMPT_NOT_FOUND:{ref.prompt_id}:{selector}")
        return record


@asynccontextmanager
async def prompt_registry_resource(
    database_url: str,
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout_seconds: int,
    pool_recycle_seconds: int,
) -> AsyncIterator[PostgresPromptRegistry]:
    async with session_factory_resource(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout_seconds=pool_timeout_seconds,
        pool_recycle_seconds=pool_recycle_seconds,
        auto_create=False,
    ) as factory:
        yield PostgresPromptRegistry(factory)


def _exact(ref: PromptRef) -> tuple[str, str]:
    if ref.version is None:
        raise ValueError("prompt lifecycle operations require an exact version")
    return ref.prompt_id, ref.version


def _version(record: PromptVersionRecord) -> PromptVersion:
    return PromptVersion(
        artifact=PromptArtifact.model_validate(record.artifact_json),
        status=PromptLifecycleStatus(record.status),
        validation=(
            None
            if record.validation_json is None
            else PromptValidation.model_validate(record.validation_json)
        ),
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _release(record: PromptReleaseRecord) -> PromptRelease:
    return PromptRelease(
        prompt_id=record.prompt_id,
        environment=RunMode(record.environment),
        version=record.version,
        content_hash=record.content_hash,
        updated_by=record.updated_by,
        updated_at=record.updated_at,
    )


def _audit(
    prompt_id: str,
    *,
    action: str,
    actor: str,
    details: dict[str, Any],
    now: datetime,
    version: str | None = None,
    environment: RunMode | None = None,
) -> PromptAuditRecord:
    return PromptAuditRecord(
        audit_id=str(uuid4()),
        prompt_id=prompt_id,
        version=version,
        environment=None if environment is None else environment.value,
        action=action,
        actor=actor,
        details_json=details,
        created_at=now,
    )
