"""Configuration failures and provider errors remain safe at the HTTP boundary."""

import httpx
import pytest
from google import genai
from google.genai import types

from app.core.config import Settings
from app.main import create_app
from app.services.gemma import GemmaService


async def test_missing_key_disables_only_gemma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main.settings", Settings(_env_file=None, GOOGLE_API_KEY=None))
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/v1/health")).status_code == 200
            response = await client.post("/api/v1/gemma/generate", json={"prompt": "hello"})
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "gemma_not_configured"


@pytest.mark.parametrize(
    ("upstream_status", "http_status", "code"),
    [
        (400, 400, "gemma_invalid_request"),
        (403, 502, "gemma_provider"),
        (429, 429, "gemma_rate_limited"),
        (503, 502, "gemma_provider"),
        (504, 504, "gemma_timeout"),
    ],
)
async def test_provider_errors_do_not_expose_upstream_credentials(
    monkeypatch: pytest.MonkeyPatch, upstream_status: int, http_status: int, code: str
) -> None:
    secret = "unit-test-key-never-return-this"

    async def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            upstream_status,
            json={"error": {"code": upstream_status, "message": f"Provider details: {secret}"}},
        )

    monkeypatch.setattr("app.main.settings", Settings(_env_file=None, GOOGLE_API_KEY=None))
    app = create_app()
    async with app.router.lifespan_context(app):
        sdk = genai.Client(
            api_key=secret,
            vertexai=False,
            http_options=types.HttpOptions(
                httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        service = GemmaService(Settings(_env_file=None, GOOGLE_API_KEY=secret), client=sdk)
        app.state.gemma = service
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/gemma/generate", json={"prompt": "hello"})
            assert response.status_code == http_status
            assert response.json()["detail"]["code"] == code
            assert secret not in response.text
            assert "Provider details" not in response.text
        finally:
            await service.aclose()


@pytest.mark.parametrize(
    ("primary", "secondary", "expected"),
    [
        ("", "alias-test-key", "alias-test-key"),
        ("primary-test-key", "alias-test-key", "primary-test-key"),
    ],
)
def test_key_alias_fallback_and_precedence(
    monkeypatch: pytest.MonkeyPatch, primary: str, secondary: str, expected: str
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", primary)
    monkeypatch.setenv("GEMINI_API_KEY", secondary)
    key = Settings(_env_file=None).GOOGLE_API_KEY
    assert key is not None
    assert key.get_secret_value() == expected
