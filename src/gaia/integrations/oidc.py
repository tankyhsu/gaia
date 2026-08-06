"""`AuthnProvider` binding for enterprise IdPs that issue OIDC/JWT tokens.

**Gaia does not build an identity system.** Enterprises already run an IdP --
Keycloak, Okta, Entra ID, Ping, or similar -- that authenticates end users,
manages their lifecycle, and grants roles. `JwtAuthnProvider` is the consumer
side only: it validates a Bearer JWT's signature and standard claims against
that IdP's published keys, and maps the claims it finds onto a
`gaia.contracts.models.UserIdentity`. Token issuance, user lifecycle, and role
administration stay with the IdP; Gaia never mints, stores, or edits either.
See `docs/施工图/09-Runtime安全边界与Sandbox.md` for the boundary statement in
the framework's usual voice, and `developer-docs/http-api.md` for the
configuration surface (`gaia.yaml`'s `authn:` section).

This module has no top-level dependency on `pyjwt` -- it can always be
imported. `JwtAuthnProvider` only needs `pyjwt` (with the `crypto` extra, for
RS/ES/PS signature verification) when actually constructed; without
`gaia-framework[oidc]` installed, construction raises
`CONFIG_OPTIONAL_DEPENDENCY_MISSING:oidc` rather than an import error deep in
some unrelated code path.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from gaia.config.models import OIDC_ASYMMETRIC_ALGORITHMS, AuthnSettings
from gaia.contracts.models import UserIdentity
from gaia.spi.auth import AuthenticationError

_DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ClaimMapping:
    """Dotted-path locations of identity fields within a validated token's claims.

    A dotted path (`"realm_access.roles"`) walks nested objects; a bare name
    (`"groups"`) addresses a top-level claim. There is no vendor-specific
    default baked in beyond the field name most IdPs happen to share (`sub`
    for subject) -- `organization` and `roles` locations vary enough between
    IdPs that guessing wrong would silently authenticate someone with the
    wrong (or no) authority, so callers are expected to set these explicitly
    for anything other than the most generic OIDC claim layout.
    """

    subject: str = "sub"
    organization: str = "org_id"
    roles: str = "roles"


def _reject_unsafe_algorithms(algorithms: Sequence[str]) -> None:
    if not algorithms:
        raise ValueError("JwtAuthnProvider requires at least one algorithm")
    for algorithm in algorithms:
        if algorithm not in OIDC_ASYMMETRIC_ALGORITHMS:
            raise ValueError(
                "JwtAuthnProvider only accepts asymmetric-signature algorithms "
                f"({sorted(OIDC_ASYMMETRIC_ALGORITHMS)}); rejected {algorithm!r}. "
                "Symmetric algorithms and 'none' would let a caller who only has "
                "the (public) JWKS forge or skip the signature."
            )


def _extract_bearer_token(headers: Mapping[str, str]) -> str:
    """Read the Bearer token from `Authorization`, case-insensitively.

    `headers` may be a plain `dict` (as in tests) or Starlette's `Headers`
    (already case-insensitive in production); matching case-insensitively by
    hand keeps this function correct for both without depending on Starlette.
    """

    value: str | None = None
    for key, candidate in headers.items():
        if key.lower() == "authorization":
            value = candidate
            break
    if not value:
        raise AuthenticationError("missing Authorization header")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Authorization header must be a Bearer token")
    return token


def _resolve_claim(claims: Mapping[str, Any], path: str) -> Any:
    node: Any = claims
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise AuthenticationError(f"token is missing required claim {path!r}")
        node = node[part]
    return node


def _require_str_claim(claims: Mapping[str, Any], path: str) -> str:
    value = _resolve_claim(claims, path)
    if not isinstance(value, str) or not value:
        raise AuthenticationError(f"token claim {path!r} must be a non-empty string")
    return value


def _require_role_list_claim(claims: Mapping[str, Any], path: str) -> list[str]:
    value = _resolve_claim(claims, path)
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise AuthenticationError(f"token claim {path!r} must be a non-empty list of strings")
    return value


class _JwksCache:
    """Fetches and caches JWKS signing keys with a TTL and a failure backoff.

    An unreachable or misbehaving IdP must not turn every incoming request
    into a fresh HTTP round trip -- that is a self-inflicted denial of
    service against both the IdP and this process. A successful fetch is
    cached for `ttl_seconds`. A *failed* fetch starts a `backoff_seconds`
    window during which no further fetch is attempted at all: requests reuse
    the last known-good keys if any exist (a brief JWKS outage should not
    reject tokens signed under keys we already validated fine a minute ago),
    and only fail with `AuthenticationError` if no keys have ever been
    fetched successfully.
    """

    def __init__(
        self,
        *,
        jwks_url: str | None,
        issuer: str,
        ttl_seconds: float,
        backoff_seconds: float,
        http_timeout_seconds: float = _DEFAULT_HTTP_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._resolved_jwks_url = jwks_url
        self._issuer = issuer
        self._ttl_seconds = ttl_seconds
        self._backoff_seconds = backoff_seconds
        self._http_timeout_seconds = http_timeout_seconds
        self._clock = clock
        self._keys: dict[str, dict[str, Any]] | None = None
        self._fetched_at: float = float("-inf")
        self._backoff_until: float = float("-inf")
        self._lock = asyncio.Lock()
        # Exposed for tests that assert the cache does not refetch within the TTL.
        self.fetch_count = 0

    async def get_signing_key(self, kid: str | None) -> Any:
        now = self._clock()
        if self._keys is None or now >= self._fetched_at + self._ttl_seconds:
            await self._refresh()
        if self._keys is None:
            raise AuthenticationError("JWKS unavailable: no signing keys could be fetched")
        return self._select(kid)

    async def _refresh(self) -> None:
        async with self._lock:
            now = self._clock()
            # Re-check inside the lock: a concurrent caller may have already
            # refreshed (or just started a backoff window) while we waited.
            if self._keys is not None and now < self._fetched_at + self._ttl_seconds:
                return
            if now < self._backoff_until:
                return
            try:
                keys = await self._fetch()
            except Exception:
                self._backoff_until = self._clock() + self._backoff_seconds
                return
            self._keys = keys
            self._fetched_at = self._clock()
            self._backoff_until = float("-inf")

    async def _fetch(self) -> dict[str, dict[str, Any]]:
        self.fetch_count += 1
        async with httpx.AsyncClient(timeout=self._http_timeout_seconds) as client:
            jwks_url = await self._resolve_jwks_url(client)
            response = await client.get(jwks_url)
            response.raise_for_status()
            payload = response.json()
        keys: dict[str, dict[str, Any]] = {}
        for jwk in payload.get("keys", ()):
            kid = jwk.get("kid")
            if isinstance(kid, str) and kid:
                keys[kid] = jwk
        return keys

    async def _resolve_jwks_url(self, client: httpx.AsyncClient) -> str:
        if self._resolved_jwks_url:
            return self._resolved_jwks_url
        discovery_url = f"{self._issuer.rstrip('/')}/.well-known/openid-configuration"
        response = await client.get(discovery_url)
        response.raise_for_status()
        jwks_uri = response.json().get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise RuntimeError("discovery document is missing jwks_uri")
        self._resolved_jwks_url = jwks_uri
        return jwks_uri

    def _select(self, kid: str | None) -> Any:
        assert self._keys is not None
        from jwt.algorithms import ECAlgorithm, RSAAlgorithm

        jwk: dict[str, Any] | None = None
        if kid is not None:
            jwk = self._keys.get(kid)
        elif len(self._keys) == 1:
            jwk = next(iter(self._keys.values()))
        if jwk is None:
            raise AuthenticationError(f"no JWKS signing key found for kid={kid!r}")
        kty = jwk.get("kty")
        if kty == "RSA":
            return RSAAlgorithm.from_jwk(jwk)
        if kty == "EC":
            return ECAlgorithm.from_jwk(jwk)
        raise AuthenticationError(f"unsupported JWKS key type {kty!r}")


class JwtAuthnProvider:
    """`AuthnProvider` that validates Bearer JWTs issued by an external IdP.

    Behaviour, matching `gaia.spi.auth.AuthnProvider`'s three-outcome contract
    exactly:

    - missing/malformed `Authorization` header, expired/not-yet-valid token,
      wrong `iss`/`aud`, disallowed/absent algorithm, bad signature, or a
      claim mapping that is missing or the wrong shape -> `AuthenticationError`;
    - a token that passes all of the above -> a `UserIdentity` built from the
      mapped claims. This provider never returns `None`: a JWT always either
      fails validation or names an end-user, so there is no "authenticated
      trusted service, no end-user identity" case for it to represent -- that
      case is `ApiKeyAuthnProvider`'s.

    **Algorithm confusion**: `algorithms` is a fixed, server-side allowlist of
    asymmetric algorithms (see `gaia.config.models.OIDC_ASYMMETRIC_ALGORITHMS`)
    supplied at construction time. The token's own header `alg` is read only
    to select a fetched JWKS key and to fail fast before doing any network or
    cryptographic work; the actual verification algorithm is always exactly
    the `algorithms=` list passed to `jwt.decode`, which pyjwt cross-checks
    against the token's header itself -- the token never gets to pick its own
    verification algorithm. This is what stops both the "alg: none" bypass and
    the classic RS256/HS256 key-confusion attack (an attacker who only has the
    IdP's public JWKS cannot forge an HS256 token once HS256 is not in the
    allowlist, regardless of what "key" a naive verifier might otherwise have
    tried).
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: Sequence[str] = ("RS256",),
        jwks_url: str | None = None,
        leeway_seconds: int = 30,
        jwks_cache_ttl_seconds: int = 300,
        jwks_fetch_backoff_seconds: int = 30,
        claims: ClaimMapping | None = None,
    ) -> None:
        try:
            import jwt  # noqa: F401  -- presence probe; see module docstring.
        except ModuleNotFoundError as error:
            raise RuntimeError("CONFIG_OPTIONAL_DEPENDENCY_MISSING:oidc") from error
        _reject_unsafe_algorithms(algorithms)
        self._issuer = issuer
        self._audience = audience
        self._algorithms = tuple(algorithms)
        self._leeway_seconds = leeway_seconds
        self._claims = claims or ClaimMapping()
        self._jwks = _JwksCache(
            jwks_url=jwks_url,
            issuer=issuer,
            ttl_seconds=jwks_cache_ttl_seconds,
            backoff_seconds=jwks_fetch_backoff_seconds,
        )

    @classmethod
    def from_settings(cls, settings: AuthnSettings) -> JwtAuthnProvider:
        if not settings.issuer or not settings.audience:
            raise ValueError("oidc authn requires authn.issuer and authn.audience")
        return cls(
            issuer=settings.issuer,
            audience=settings.audience,
            algorithms=settings.algorithms,
            jwks_url=settings.jwks_url,
            leeway_seconds=settings.leeway_seconds,
            jwks_cache_ttl_seconds=settings.jwks_cache_ttl_seconds,
            jwks_fetch_backoff_seconds=settings.jwks_fetch_backoff_seconds,
            claims=ClaimMapping(
                subject=settings.claims.subject,
                organization=settings.claims.organization,
                roles=settings.claims.roles,
            ),
        )

    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
        import jwt

        token = _extract_bearer_token(headers)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as error:
            raise AuthenticationError("malformed JWT header") from error

        alg = header.get("alg")
        # Fail fast, before any JWKS lookup or cryptography: reject `none` and
        # anything outside our fixed allowlist. This does not by itself do the
        # verification -- `algorithms=self._algorithms` below is the actual
        # enforcement pyjwt performs -- but it means an attacker cannot even
        # cause a JWKS fetch by tampering with `alg`.
        if not isinstance(alg, str) or alg not in self._algorithms:
            raise AuthenticationError(f"token alg {alg!r} is not in the configured allowlist")

        key = await self._jwks.get_signing_key(header.get("kid"))
        try:
            claims = jwt.decode(
                token,
                key=key,
                # Never `algorithms=[alg]` from the token's own header -- that
                # is exactly the bug that makes algorithm confusion possible.
                # This is always our fixed, server-side configuration.
                algorithms=list(self._algorithms),
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway_seconds,
                options={"require": ["exp"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError("token has expired") from error
        except jwt.ImmatureSignatureError as error:
            raise AuthenticationError("token is not yet valid (nbf)") from error
        except jwt.InvalidAudienceError as error:
            raise AuthenticationError("token audience does not match") from error
        except jwt.InvalidIssuerError as error:
            raise AuthenticationError("token issuer does not match") from error
        except jwt.InvalidAlgorithmError as error:
            raise AuthenticationError("token algorithm is not permitted") from error
        except jwt.PyJWTError as error:
            raise AuthenticationError(f"token failed verification: {error}") from error

        return self._map_identity(claims)

    def _map_identity(self, claims: Mapping[str, Any]) -> UserIdentity:
        subject = _require_str_claim(claims, self._claims.subject)
        organization = _require_str_claim(claims, self._claims.organization)
        roles = _require_role_list_claim(claims, self._claims.roles)
        try:
            return UserIdentity(id=subject, organization=organization, roles=roles)
        except ValidationError as error:
            raise AuthenticationError(
                f"token claims failed identity validation: {error}"
            ) from error
