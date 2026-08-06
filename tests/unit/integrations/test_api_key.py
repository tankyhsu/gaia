from __future__ import annotations

import pytest

from gaia.integrations.api_key import ApiKeyAuthnProvider
from gaia.spi.auth import AuthenticationError


async def test_valid_key_authenticates_as_trusted_service_with_no_identity() -> None:
    provider = ApiKeyAuthnProvider("secret-key")

    identity = await provider.authenticate({"X-Gaia-Api-Key": "secret-key"})

    assert identity is None


async def test_missing_key_raises_authentication_error() -> None:
    provider = ApiKeyAuthnProvider("secret-key")

    with pytest.raises(AuthenticationError):
        await provider.authenticate({})


async def test_wrong_key_raises_authentication_error() -> None:
    provider = ApiKeyAuthnProvider("secret-key")

    with pytest.raises(AuthenticationError):
        await provider.authenticate({"X-Gaia-Api-Key": "wrong-key"})


async def test_custom_header_name_is_honored() -> None:
    provider = ApiKeyAuthnProvider("secret-key", header_name="X-Custom-Key")

    identity = await provider.authenticate({"X-Custom-Key": "secret-key"})

    assert identity is None
    with pytest.raises(AuthenticationError):
        await provider.authenticate({"X-Gaia-Api-Key": "secret-key"})
