"""Authentication outcomes at the Runtime SPI boundary.

``AuthenticationError`` rejects before Runtime, ``UserIdentity`` replaces the
body identity, and ``None`` preserves trusted-service behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gaia.api.app import create_app
from gaia.application import GaiaApplication
from gaia.config import GaiaApplicationConfig
from gaia.contracts.models import UserIdentity
from gaia.spi.auth import AuthenticationError, AuthnProvider
from tests.runtime_capture import CreateCaptureRuntime, capture_api_dependencies


class RaisingAuthn:
    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
        raise AuthenticationError("no credentials accepted in this test")


class IdentityAuthn:
    def __init__(self, identity: UserIdentity) -> None:
        self._identity = identity

    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
        return self._identity


class TrustedServiceAuthn:
    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
        return None


def _app(
    tmp_path: Path,
    *,
    authn: AuthnProvider | None,
) -> tuple[FastAPI, CreateCaptureRuntime]:
    config = GaiaApplicationConfig(runtime={"execution": {"provider": "temporal"}})
    runtime = CreateCaptureRuntime()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=GaiaApplication(config),
        dependencies=capture_api_dependencies(runtime),
        authn=authn,
    )
    return app, runtime


def _run_body(user: dict[str, object]) -> dict[str, object]:
    return {
        "scenario_id": "whoami",
        "mode": "mock",
        "user": user,
        "request": {"text": "who am I"},
    }


def test_authentication_error_rejects_with_401_before_runtime(tmp_path: Path) -> None:
    app, runtime = _app(tmp_path, authn=RaisingAuthn())
    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "authn-fail-0001"},
            json=_run_body(
                {"id": "claimed", "organization": "org", "roles": ["user"]}
            ),
        )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert runtime.requests == []


def test_returned_identity_replaces_request_user_at_runtime_boundary(
    tmp_path: Path,
) -> None:
    identity = UserIdentity(
        id="authenticated-user",
        organization="org-real",
        roles=["user", "auditor"],
    )
    app, runtime = _app(tmp_path, authn=IdentityAuthn(identity))
    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "authn-identity-0001"},
            json=_run_body(
                {
                    "id": "authenticated-user",
                    "organization": "org-real",
                    "roles": ["auditor", "user"],
                }
            ),
        )

    assert response.status_code == 201
    assert response.json()["user"] == {
        "id": "authenticated-user",
        "organization": "org-real",
        "roles": ["user", "auditor"],
    }
    assert runtime.requests[0].user == identity


def test_none_outcome_preserves_request_body_user(tmp_path: Path) -> None:
    app, runtime = _app(tmp_path, authn=TrustedServiceAuthn())
    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "authn-none-0001"},
            json=_run_body(
                {
                    "id": "claimed-by-service",
                    "organization": "org",
                    "roles": ["user"],
                }
            ),
        )

    assert response.status_code == 201
    assert runtime.requests[0].user == UserIdentity(
        id="claimed-by-service",
        organization="org",
        roles=["user"],
    )


def test_identity_conflict_is_rejected_before_runtime(tmp_path: Path) -> None:
    identity = UserIdentity(
        id="authenticated-user",
        organization="org-real",
        roles=["user"],
    )
    app, runtime = _app(tmp_path, authn=IdentityAuthn(identity))
    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "authn-conflict-0001"},
            json=_run_body(
                {
                    "id": "someone-else",
                    "organization": "org-real",
                    "roles": ["user"],
                }
            ),
        )

    assert response.status_code == 409
    assert response.json()["code"] == "IDENTITY_MISMATCH"
    assert runtime.requests == []


def test_default_api_key_authentication_is_unchanged(tmp_path: Path) -> None:
    app, runtime = _app(tmp_path, authn=None)
    with TestClient(app) as client:
        unauthorized = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "authn-default-0001"},
            json=_run_body({"id": "u", "organization": "org", "roles": ["user"]}),
        )
        authorized = client.post(
            "/v1/runs",
            headers={
                "X-Gaia-Api-Key": "gaia-dev-key",
                "Idempotency-Key": "authn-default-0002",
            },
            json=_run_body({"id": "u", "organization": "org", "roles": ["user"]}),
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 201
    assert len(runtime.requests) == 1
