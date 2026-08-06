"""HTTP boundary coverage for ``GET /v1/runs``.

Gaia's audit projection owns filtering and pagination. These tests prove that
the API forwards authenticated organization scope and query parameters through
the Runtime SPI without filtering an already loaded page in Python.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gaia.api.app import ApiDependencies, create_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import RunPage, RunStatus, UserIdentity
from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
from gaia.spi.auth import AuthenticationError, AuthnProvider


class ListingRuntime(TemporalRuntimeEngine):
    """Scripted Runtime projection; it never executes a Workflow."""

    def __init__(self, pages: list[RunPage]) -> None:
        super().__init__()
        self._pages = iter(pages)
        self.calls: list[dict[str, object]] = []

    async def list_runs(
        self,
        *,
        organization: str | None,
        status: RunStatus | None = None,
        scenario_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> RunPage:
        self.calls.append(
            {
                "organization": organization,
                "status": status,
                "scenario_id": scenario_id,
                "limit": limit,
                "cursor": cursor,
            }
        )
        return next(self._pages)


class MultiActorAuthn:
    def __init__(self, identities: Mapping[str, UserIdentity]) -> None:
        self._identities = identities

    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
        actor = headers.get("X-Test-Actor")
        if actor is None or actor not in self._identities:
            raise AuthenticationError("unknown or missing X-Test-Actor")
        return self._identities[actor]


def _app(
    tmp_path: Path,
    runtime: ListingRuntime,
    *,
    authn: AuthnProvider | None,
) -> FastAPI:
    config = GaiaApplicationConfig(runtime={"execution": {"provider": "temporal"}})
    return create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=GaiaApplication(config),
        dependencies=ApiDependencies(
            runtime_factory=lambda factory, database_url: runtime,
        ),
        authn=authn,
    )


def _headers(actor: str) -> dict[str, str]:
    return {"X-Test-Actor": actor}


def test_http_forwards_authenticated_organization_scope(tmp_path: Path) -> None:
    bob = UserIdentity(id="bob", organization="org-b", roles=["user"])
    runtime = ListingRuntime([RunPage(items=[])])
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"bob": bob}),
    )

    with TestClient(app) as client:
        response = client.get("/v1/runs", headers=_headers("bob"))

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
    assert runtime.calls == [
        {
            "organization": "org-b",
            "status": None,
            "scenario_id": None,
            "limit": 50,
            "cursor": None,
        }
    ]


def test_http_limit_above_maximum_is_rejected_before_runtime(tmp_path: Path) -> None:
    runtime = ListingRuntime([])
    app = _app(tmp_path, runtime, authn=None)

    with TestClient(app) as client:
        response = client.get(
            "/v1/runs",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
            params={"limit": 100_000},
        )

    assert response.status_code == 422
    assert runtime.calls == []


def test_http_forwards_audit_projection_filters(tmp_path: Path) -> None:
    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    runtime = ListingRuntime([RunPage(items=[])])
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice}),
    )

    with TestClient(app) as client:
        response = client.get(
            "/v1/runs",
            headers=_headers("alice"),
            params={"status": "failed", "scenario_id": "h1.fail", "limit": 7},
        )

    assert response.status_code == 200
    assert runtime.calls == [
        {
            "organization": "org-a",
            "status": RunStatus.FAILED,
            "scenario_id": "h1.fail",
            "limit": 7,
            "cursor": None,
        }
    ]


def test_http_forwards_opaque_audit_projection_cursor(tmp_path: Path) -> None:
    alice = UserIdentity(id="alice", organization="org-a", roles=["user"])
    runtime = ListingRuntime(
        [
            RunPage(items=[], next_cursor="audit-page-2"),
            RunPage(items=[]),
        ]
    )
    app = _app(
        tmp_path,
        runtime,
        authn=MultiActorAuthn({"alice": alice}),
    )

    with TestClient(app) as client:
        first = client.get("/v1/runs", headers=_headers("alice"), params={"limit": 3})
        second = client.get(
            "/v1/runs",
            headers=_headers("alice"),
            params={"limit": 3, "cursor": first.json()["next_cursor"]},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert [call["cursor"] for call in runtime.calls] == [None, "audit-page-2"]


def test_http_api_key_mode_requests_unscoped_audit_projection(tmp_path: Path) -> None:
    runtime = ListingRuntime([RunPage(items=[])])
    app = _app(tmp_path, runtime, authn=None)

    with TestClient(app) as client:
        response = client.get(
            "/v1/runs",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )

    assert response.status_code == 200
    assert runtime.calls[0]["organization"] is None
