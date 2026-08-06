import base64

from gaia.observability.langfuse import langfuse_headers, langfuse_otlp_endpoint


def test_langfuse_otlp_contract_uses_v4_realtime_ingestion() -> None:
    headers = langfuse_headers("pk-test", "sk-test")

    assert langfuse_otlp_endpoint("https://langfuse.example.com/") == (
        "https://langfuse.example.com/api/public/otel/v1/traces"
    )
    assert headers == {
        "Authorization": "Basic "
        + base64.b64encode(b"pk-test:sk-test").decode(),
        "x-langfuse-ingestion-version": "4",
    }
