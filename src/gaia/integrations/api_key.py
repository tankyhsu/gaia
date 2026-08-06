"""Shared API-key authentication for trusted service callers."""

from __future__ import annotations

from collections.abc import Mapping

from gaia.contracts.models import UserIdentity
from gaia.spi.auth import AuthenticationError


class ApiKeyAuthnProvider:
    """Authenticate one trusted service without asserting an end-user identity.

    A valid key returns ``None`` so the trusted caller remains responsible for
    the ``RunRequest.user`` it submits. Deployments that need end-user identity
    enforcement must configure a provider that returns ``UserIdentity``.
    """

    def __init__(self, api_key: str, *, header_name: str = "X-Gaia-Api-Key") -> None:
        self._api_key = api_key
        self._header_name = header_name

    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
        if headers.get(self._header_name) != self._api_key:
            raise AuthenticationError("missing or invalid API key")
        return None
