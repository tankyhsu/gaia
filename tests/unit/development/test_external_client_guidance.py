from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[3]


def test_external_client_guidance_uses_the_generated_openapi_contract() -> None:
    guidance = (PROJECT_ROOT / "developer-docs" / "client-sdks.md").read_text(
        encoding="utf-8"
    )
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "Gaia 不提供手写的 Client SDK" in guidance
    assert "`gaia` 顶层编写 API" in guidance
    assert "`gaia.spi` 协议" in guidance
    assert "specs/openapi.json" in guidance
    assert "Idempotency-Key" in guidance
    assert "/events/stream" in guidance
    assert "client-check:" not in makefile
    assert "java-client-check:" not in makefile
