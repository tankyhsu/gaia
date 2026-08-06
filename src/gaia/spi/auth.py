"""Authentication SPI: resolve the caller identity for one HTTP request.

Concrete authentication providers live under ``gaia.integrations``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from gaia.contracts.models import UserIdentity


class AuthenticationError(Exception):
    """Credentials are missing, malformed, or rejected."""


class AuthnProvider(Protocol):
    """Resolve the caller identity for one HTTP request.

    Three outcomes, deliberately distinct:
      raise AuthenticationError -> authentication FAILED; reject the request (401).
      return UserIdentity       -> authenticated AND carries an end-user identity;
                                   this identity is the single source of truth.
      return None               -> authenticated as a TRUSTED SERVICE with no
                                   end-user identity; RunRequest.user applies.

    **These three outcomes must stay distinct.** In particular, "authentication
    failed" and "authenticated but carries no end-user identity" must never
    collapse onto the same return value (e.g. `None` for both): one code path
    would then have to handle both, and the correct response is opposite in
    each case -- the first must reject the request, the second must let it
    proceed and trust `RunRequest.user`. Merging them is exactly how a failed
    authentication ends up being treated as a trusted service call, silently.
    Use the exception to signal failure and the return value to signal
    identity-or-absence; do not repurpose either channel for the other case.

    Identity authority rule: when `authenticate` returns a `UserIdentity`, that
    identity is the single source of truth for the request. It overrides
    `RunRequest.user` -- callers must not merge fields from the request body
    into it. If the request body's `user` disagrees with the authenticated
    identity, the request is rejected (`IDENTITY_MISMATCH`) rather than
    silently overridden: silent override would leave the caller believing it
    acted as the identity it claimed, when it was actually recorded as
    someone else. `RunRequest.user` is client-submitted, untrusted input --
    its `roles` field feeds directly into `gaia.runtime.safety.validate_roles`
    and per-tool `required_roles` checks, so treating it as authoritative
    without an authenticated identity behind it would let a caller grant
    itself arbitrary roles.
    """

    async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None: ...
