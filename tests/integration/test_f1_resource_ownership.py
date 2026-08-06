"""Run and HumanGate ownership at the Temporal Runtime SPI boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gaia.api.app import ApiDependencies, create_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import (
    GateStatus,
    HumanGate,
    HumanGateDecisionRequest,
    RiskLevel,
    RunSnapshot,
    RunStatus,
    UserIdentity,
    VersionBundle,
)
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.spi.auth import AuthenticationError, AuthnProvider


class MultiActorAuthn:
    def __init__(self, identities: Mapping[str, UserIdentity]) -> None:
        self._identities = identities

    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
        actor = headers.get("X-Test-Actor")
        if actor is None or actor not in self._identities:
            raise AuthenticationError("unknown or missing X-Test-Actor")
        return self._identities[actor]


class OwnershipRuntime(TemporalRuntimeEngine):
    """Preloaded Temporal Query projections with captured write boundaries."""

    def __init__(self, run: RunSnapshot, gate: HumanGate) -> None:
        super().__init__()
        self.run = run
        self.gate = gate
        self.cancel_calls: list[tuple[str, str]] = []
        self.decide_calls: list[tuple[str, HumanGateDecisionRequest]] = []
        self.gates_for_run_calls: list[str] = []

    async def inspect(self, run_id: str) -> RunSnapshot:
        if run_id != self.run.run_id:
            raise KeyError(run_id)
        return self.run

    async def get_gate(self, gate_id: str) -> HumanGate:
        if gate_id != self.gate.gate_id:
            raise KeyError(gate_id)
        return self.gate

    async def gates_for_run(self, run_id: str) -> list[HumanGate]:
        self.gates_for_run_calls.append(run_id)
        if run_id != self.run.run_id:
            return []
        return [self.gate]

    async def cancel(self, run_id: str, reason: str) -> RunSnapshot:
        self.cancel_calls.append((run_id, reason))
        return self.run.model_copy(update={"status": RunStatus.CANCELLED})

    async def decide(
        self,
        gate_id: str,
        body: HumanGateDecisionRequest,
    ) -> RunSnapshot:
        self.decide_calls.append((gate_id, body))
        return self.run.model_copy(
            update={
                "status": RunStatus.SUCCEEDED,
                "pending_gate_id": None,
            }
        )


def _runtime() -> OwnershipRuntime:
    now = datetime.now(UTC)
    run_id = "temporal-run-org-a"
    gate_id = f"{run_id}:gate:publish"
    user = UserIdentity(id="alice", organization="org-a", roles=["user"])
    run = RunSnapshot(
        run_id=run_id,
        scenario_id="f1.request_publish",
        mode="mock",
        status=RunStatus.WAITING_HUMAN,
        user=user,
        version_bundle=VersionBundle(
            policy="policy:1",
            workflow="workflow:1",
            rules="rules:1",
            prompt="prompt:1",
            model_profile="model:1",
            toolset="tools:1",
            context_profile="context:1",
        ),
        pending_gate_id=gate_id,
        created_at=now,
        updated_at=now,
    )
    gate = HumanGate(
        gate_id=gate_id,
        run_id=run_id,
        command_id=f"{run_id}:command:publish",
        reason="Publishing changes a durable business record.",
        risk_level=RiskLevel.HIGH,
        requested_action={"tool_name": "f1.publish", "resource_id": "widget-1"},
        status=GateStatus.PENDING,
        requested_by="alice",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    return OwnershipRuntime(run, gate)


def _app(
    tmp_path: Path,
    runtime: OwnershipRuntime,
    *,
    authn: AuthnProvider | None,
) -> FastAPI:
    config = GaiaApplicationConfig(runtime={"execution": {"provider": "temporal"}})

    def runtime_factory(factory: object, database_url: str) -> OwnershipRuntime:
        del factory, database_url
        return runtime

    return create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=GaiaApplication(config),
        dependencies=ApiDependencies(runtime_factory=runtime_factory),
        authn=authn,
    )


def _headers(actor: str) -> dict[str, str]:
    return {"X-Test-Actor": actor}


def test_cross_organization_gate_read_is_not_found(tmp_path: Path) -> None:
    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    bob = UserIdentity(id="bob", organization="org-b", roles=["user"])
    runtime = _runtime()
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice, "bob": bob}),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/v1/human-gates/{runtime.gate.gate_id}",
            headers=_headers("bob"),
        )

    assert response.status_code == 404
    assert response.json()["code"] == "GATE_NOT_FOUND"
    assert runtime.decide_calls == []


def test_cross_organization_run_read_and_cancel_do_not_cross_boundary(
    tmp_path: Path,
) -> None:
    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    bob = UserIdentity(id="bob", organization="org-b", roles=["user"])
    runtime = _runtime()
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice, "bob": bob}),
    )

    with TestClient(app) as client:
        bob_read = client.get(
            f"/v1/runs/{runtime.run.run_id}",
            headers=_headers("bob"),
        )
        bob_cancel = client.post(
            f"/v1/runs/{runtime.run.run_id}/cancel",
            headers=_headers("bob"),
            json={"reason": "not mine to cancel"},
        )
        alice_read = client.get(
            f"/v1/runs/{runtime.run.run_id}",
            headers=_headers("alice"),
        )

    assert bob_read.status_code == 404
    assert bob_cancel.status_code == 404
    assert alice_read.status_code == 200
    assert runtime.cancel_calls == []


def test_forged_approver_role_is_rejected_before_temporal_update(
    tmp_path: Path,
) -> None:
    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    mallory = UserIdentity(id="mallory", organization="org-a", roles=["user"])
    runtime = _runtime()
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice, "mallory": mallory}),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/v1/human-gates/{runtime.gate.gate_id}/decision",
            headers=_headers("mallory"),
            json={
                "decision": "approved",
                "decided_by": "mallory",
                "roles": ["approver"],
                "comment": "forged by mallory",
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "IDENTITY_MISMATCH"
    assert runtime.decide_calls == []


def test_authenticated_approver_identity_reaches_temporal_update(
    tmp_path: Path,
) -> None:
    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    approver = UserIdentity(
        id="approver-1",
        organization="org-a",
        roles=["approver", "auditor"],
    )
    runtime = _runtime()
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice, "approver-1": approver}),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/v1/human-gates/{runtime.gate.gate_id}/decision",
            headers=_headers("approver-1"),
            json={
                "decision": "approved",
                "decided_by": "approver-1",
                "roles": ["auditor", "approver"],
                "comment": "Looks correct.",
            },
        )

    assert response.status_code == 200
    assert len(runtime.decide_calls) == 1
    gate_id, decision = runtime.decide_calls[0]
    assert gate_id == runtime.gate.gate_id
    assert decision.decided_by == "approver-1"
    assert decision.roles == ["approver", "auditor"]


def test_trusted_service_decision_body_reaches_temporal_update(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    app = _app(tmp_path, runtime, authn=None)

    with TestClient(app) as client:
        response = client.post(
            f"/v1/human-gates/{runtime.gate.gate_id}/decision",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
            json={
                "decision": "approved",
                "decided_by": "approver-1",
                "roles": ["approver"],
                "comment": "Looks correct.",
            },
        )

    assert response.status_code == 200
    assert runtime.decide_calls[0][1].decided_by == "approver-1"


def test_cross_organization_human_gates_for_run_is_not_found(tmp_path: Path) -> None:
    """Same 404-not-403 boundary as reading the Run itself: `authorized_run`
    rejects the Run before `gates_for_run` is ever called."""

    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    bob = UserIdentity(id="bob", organization="org-b", roles=["user"])
    runtime = _runtime()
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice, "bob": bob}),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/v1/runs/{runtime.run.run_id}/human-gates",
            headers=_headers("bob"),
        )

    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"
    assert runtime.gates_for_run_calls == []


def test_human_gates_for_run_names_the_approver_for_the_owning_organization(
    tmp_path: Path,
) -> None:
    """This is the read the demo landing page and the Run list use to say
    "approved by demo-approver" instead of "未记录" for a completed Run."""

    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    runtime = _runtime()
    runtime.gate = runtime.gate.model_copy(
        update={
            "status": GateStatus.APPROVED,
            "decided_by": "demo-approver",
            "decided_at": datetime.now(UTC),
        }
    )
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice}),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/v1/runs/{runtime.run.run_id}/human-gates",
            headers=_headers("alice"),
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["decided_by"] == "demo-approver"
    assert runtime.gates_for_run_calls == [runtime.run.run_id]
