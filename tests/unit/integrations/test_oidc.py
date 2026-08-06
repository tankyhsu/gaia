"""F2: `JwtAuthnProvider` validates real, self-signed JWTs end to end.

No mocking of the verification step: every token here is generated with a
real RSA keypair created in this file and signed with `pyjwt`, exactly as an
IdP would. Only the JWKS HTTP fetch is mocked (via `respx`) since there is no
real IdP to fetch from.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

# This whole module needs `gaia-framework[oidc]` (pyjwt + cryptography). Skip
# cleanly at collection time rather than erroring when it is not installed --
# `oidc` in `pyproject.toml`'s `[tool.pytest.ini_options].markers` documents
# the same gate for `-m` filtering, matching how `postgres`/`redis` tests are
# marked; unlike those, no live service is needed here, only the dependency.
pytest.importorskip("jwt", reason="requires gaia-framework[oidc]")

import httpx  # noqa: E402
import jwt  # noqa: E402
import respx  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jwt.algorithms import RSAAlgorithm  # noqa: E402

from gaia.api.app import create_app  # noqa: E402
from gaia.application import GaiaApplication  # noqa: E402
from gaia.config.models import (  # noqa: E402
    AuthnSettings,
    ClaimMappingSettings,
    GaiaApplicationConfig,
)
from gaia.contracts.models import UserIdentity  # noqa: E402
from gaia.integrations.oidc import ClaimMapping, JwtAuthnProvider  # noqa: E402
from gaia.spi.auth import AuthenticationError  # noqa: E402
from tests.runtime_capture import (  # noqa: E402
    CreateCaptureRuntime,
    capture_api_dependencies,
)

pytestmark = pytest.mark.oidc

ISSUER = "https://idp.example.com/realms/gaia"
AUDIENCE = "gaia-api"
JWKS_URL = "https://idp.example.com/realms/gaia/protocol/openid-connect/certs"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


def _generate_keypair(kid: str) -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return private_key, jwk


PRIMARY_KEY, PRIMARY_JWK = _generate_keypair("primary-key")
OTHER_KEY, OTHER_JWK = _generate_keypair("other-key")


def _payload(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-42",
        "org_id": "org-acme",
        "roles": ["admin", "auditor"],
        "iat": now,
        "exp": now + 300,
        "nbf": now - 5,
    }
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def _sign(
    payload: dict[str, object],
    *,
    key: rsa.RSAPrivateKey = PRIMARY_KEY,
    kid: str | None = "primary-key",
    algorithm: str = "RS256",
) -> str:
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(payload, key, algorithm=algorithm, headers=headers)


def _provider(
    *,
    algorithms: tuple[str, ...] = ("RS256",),
    claims: ClaimMapping | None = None,
    jwks_cache_ttl_seconds: int = 300,
) -> JwtAuthnProvider:
    return JwtAuthnProvider(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=JWKS_URL,
        algorithms=algorithms,
        claims=claims,
        jwks_cache_ttl_seconds=jwks_cache_ttl_seconds,
    )


def _mock_jwks(router: respx.MockRouter, *jwks: dict[str, object]) -> respx.Route:
    return router.get(JWKS_URL).mock(
        return_value=httpx.Response(200, json={"keys": list(jwks)})
    )


async def test_valid_token_returns_expected_user_identity() -> None:
    provider = _provider()
    token = _sign(_payload())

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        identity = await provider.authenticate({"Authorization": f"Bearer {token}"})

    assert identity == UserIdentity(
        id="user-42", organization="org-acme", roles=["admin", "auditor"]
    )


async def test_missing_authorization_header_raises() -> None:
    provider = _provider()

    with pytest.raises(AuthenticationError):
        await provider.authenticate({})


async def test_malformed_authorization_header_raises() -> None:
    provider = _provider()

    with pytest.raises(AuthenticationError):
        await provider.authenticate({"Authorization": "not-a-bearer-token"})


async def test_expired_token_raises_authentication_error() -> None:
    provider = _provider()
    now = int(time.time())
    token = _sign(_payload(iat=now - 700, exp=now - 400, nbf=now - 700))

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        with pytest.raises(AuthenticationError):
            await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_wrong_audience_raises_authentication_error() -> None:
    provider = _provider()
    token = _sign(_payload(aud="someone-else"))

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        with pytest.raises(AuthenticationError):
            await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_wrong_issuer_raises_authentication_error() -> None:
    provider = _provider()
    token = _sign(_payload(iss="https://not-the-idp.example.com/"))

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        with pytest.raises(AuthenticationError):
            await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_alg_none_is_rejected() -> None:
    """The critical case: a caller cannot force the framework to skip verification."""
    provider = _provider()
    # An empty string key produces a syntactically valid, entirely unsigned token.
    token = jwt.encode(_payload(), key="", algorithm="none")

    with pytest.raises(AuthenticationError):
        await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_token_signed_by_a_different_key_is_rejected() -> None:
    """Same `kid` as the trusted key, but actually signed with another private key."""
    provider = _provider()
    token = _sign(_payload(), key=OTHER_KEY, kid="primary-key")

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        with pytest.raises(AuthenticationError):
            await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_algorithm_outside_allowlist_is_rejected() -> None:
    """RS512 is asymmetric and legitimately signed, but this deployment only allows RS256.

    No JWKS mock is installed: the allowlist check happens before any JWKS
    lookup, so a disallowed algorithm must be rejected without a network call.
    """
    provider = _provider(algorithms=("RS256",))
    token = _sign(_payload(), algorithm="RS512")

    with pytest.raises(AuthenticationError):
        await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_keycloak_style_nested_roles_claim() -> None:
    provider = _provider(
        claims=ClaimMapping(subject="sub", organization="org_id", roles="realm_access.roles")
    )
    token = _sign(
        _payload(roles=None, realm_access={"roles": ["gaia-user", "gaia-approver"]})
    )

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        identity = await provider.authenticate({"Authorization": f"Bearer {token}"})

    assert identity == UserIdentity(
        id="user-42", organization="org-acme", roles=["gaia-user", "gaia-approver"]
    )


async def test_entra_style_flat_groups_claim() -> None:
    provider = _provider(
        claims=ClaimMapping(subject="sub", organization="org_id", roles="groups")
    )
    token = _sign(_payload(roles=None, groups=["00000000-group-a", "00000000-group-b"]))

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        identity = await provider.authenticate({"Authorization": f"Bearer {token}"})

    assert identity == UserIdentity(
        id="user-42",
        organization="org-acme",
        roles=["00000000-group-a", "00000000-group-b"],
    )


async def test_okta_style_custom_claim() -> None:
    provider = _provider(
        claims=ClaimMapping(subject="sub", organization="org_id", roles="myapp_roles")
    )
    token = _sign(_payload(roles=None, myapp_roles=["viewer"]))

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        identity = await provider.authenticate({"Authorization": f"Bearer {token}"})

    assert identity == UserIdentity(id="user-42", organization="org-acme", roles=["viewer"])


async def test_missing_mapped_claim_names_it_in_the_error() -> None:
    provider = _provider(
        claims=ClaimMapping(subject="sub", organization="org_id", roles="realm_access.roles")
    )
    token = _sign(_payload())  # no `realm_access` claim at all

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        with pytest.raises(AuthenticationError, match="realm_access.roles"):
            await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_malformed_shaped_roles_claim_names_it_in_the_error() -> None:
    provider = _provider()
    token = _sign(_payload(roles="admin"))  # a string, not a list

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        with pytest.raises(AuthenticationError, match="roles"):
            await provider.authenticate({"Authorization": f"Bearer {token}"})


async def test_jwks_cache_does_not_refetch_within_ttl() -> None:
    provider = _provider(jwks_cache_ttl_seconds=300)
    token = _sign(_payload())

    with respx.mock() as router:
        route = _mock_jwks(router, PRIMARY_JWK)
        await provider.authenticate({"Authorization": f"Bearer {token}"})
        await provider.authenticate({"Authorization": f"Bearer {token}"})

    assert route.call_count == 1


async def test_jwks_url_derived_from_issuer_discovery_document() -> None:
    provider = JwtAuthnProvider(issuer=ISSUER, audience=AUDIENCE, algorithms=("RS256",))
    token = _sign(_payload())

    with respx.mock() as router:
        router.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(200, json={"jwks_uri": JWKS_URL})
        )
        _mock_jwks(router, PRIMARY_JWK)
        identity = await provider.authenticate({"Authorization": f"Bearer {token}"})

    assert identity is not None
    assert identity.id == "user-42"


def test_settings_reject_symmetric_algorithms() -> None:
    with pytest.raises(ValueError, match="asymmetric"):
        AuthnSettings(
            provider="oidc",
            issuer=ISSUER,
            audience=AUDIENCE,
            algorithms=("HS256",),
        )


def test_settings_reject_none_algorithm() -> None:
    with pytest.raises(ValueError, match="asymmetric"):
        AuthnSettings(
            provider="oidc",
            issuer=ISSUER,
            audience=AUDIENCE,
            algorithms=("none",),
        )


def test_settings_require_issuer_and_audience_for_oidc() -> None:
    with pytest.raises(ValueError):
        AuthnSettings(provider="oidc")


async def test_from_settings_applies_the_configured_claim_mapping() -> None:
    settings = AuthnSettings(
        provider="oidc",
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=JWKS_URL,
        claims=ClaimMappingSettings(
            subject="sub", organization="org_id", roles="realm_access.roles"
        ),
    )
    provider = JwtAuthnProvider.from_settings(settings)
    token = _sign(_payload(roles=None, realm_access={"roles": ["gaia-user"]}))

    with respx.mock() as router:
        _mock_jwks(router, PRIMARY_JWK)
        identity = await provider.authenticate({"Authorization": f"Bearer {token}"})

    assert identity == UserIdentity(id="user-42", organization="org-acme", roles=["gaia-user"])


def _run_body() -> dict[str, object]:
    return {
        "scenario_id": "oidc-wiring-whoami",
        "mode": "mock",
        "user": {"id": "u", "organization": "o", "roles": ["user"]},
        "request": {"text": "hi"},
    }


def test_create_app_wires_jwt_provider_from_gaia_yaml_config(tmp_path: Path) -> None:
    """`authn.provider: oidc` in config, no explicit `authn=`, wires a JwtAuthnProvider.

    Sending only `X-Gaia-Api-Key` (no `Authorization` header) proves this: the
    default `ApiKeyAuthnProvider` would accept it outright, but a wired-in
    `JwtAuthnProvider` only looks at `Authorization` and must reject.
    """
    config = GaiaApplicationConfig(
        authn=AuthnSettings(provider="oidc", issuer=ISSUER, audience=AUDIENCE, jwks_url=JWKS_URL)
    )
    runtime = CreateCaptureRuntime()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=GaiaApplication(config),
        dependencies=capture_api_dependencies(runtime),
        api_key="gaia-dev-key",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "oidc-wiring-0001", "X-Gaia-Api-Key": "gaia-dev-key"},
            json=_run_body(),
        )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_create_app_default_authn_is_unchanged_when_authn_disabled(tmp_path: Path) -> None:
    """`authn` defaults to `provider: "disabled"`: nothing changes for existing apps."""
    config = GaiaApplicationConfig(
        runtime={"execution": {"provider": "temporal"}}
    )
    runtime = CreateCaptureRuntime()

    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaia.db",
        gaia_application=GaiaApplication(config),
        dependencies=capture_api_dependencies(runtime),
        api_key="gaia-dev-key",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "oidc-wiring-0002", "X-Gaia-Api-Key": "gaia-dev-key"},
            json=_run_body(),
        )

    assert response.status_code == 201
    assert len(runtime.requests) == 1
