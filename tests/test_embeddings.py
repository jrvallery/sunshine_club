from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    GeminiEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    PlaceholderEmbeddingProvider,
    embed_texts,
    provider_from_env,
    run_smoke_test,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_placeholder_embeddings_are_deterministic_and_marked_non_semantic() -> None:
    provider = PlaceholderEmbeddingProvider(dimensions=8)

    first = embed_texts(["hello"], provider)
    second = embed_texts(["hello"], provider)

    assert first[0].embedding == second[0].embedding
    assert first[0].embedding_status == "placeholder"
    assert first[0].embedding_provider == "local"
    assert first[0].embedding_model == "local-placeholder"
    assert first[0].embedding_dimensions == 8
    assert first[0].semantic_quality is False


def test_provider_from_env_selects_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_MODEL", "gemini-embedding-2")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_DIMENSIONS", "3")

    provider = provider_from_env()

    assert isinstance(provider, GeminiEmbeddingProvider)
    assert provider.model == "gemini-embedding-2"
    assert provider.dimensions == 3


def test_provider_from_env_selects_cortex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "cortex")
    monkeypatch.setenv("CORTEX_BASE_URL", "https://cortex.vallery.net")
    monkeypatch.setenv("CORTEX_API_KEY", "test-cortex-key")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_DIMENSIONS", "3")

    provider = provider_from_env()

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert provider.model == "Qwen/Qwen3-Embedding-0.6B"
    assert provider.base_url == "https://cortex.vallery.net/v1"
    assert provider.dimensions == 3


def test_provider_from_env_selects_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API", "test-openai-key")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_DIMENSIONS", "3")

    provider = provider_from_env()

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert provider.model == "text-embedding-3-large"
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.dimensions == 3


def test_cortex_provider_calls_openai_compatible_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response({"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="test-key",
        model="Qwen/Qwen3-Embedding-0.6B",
        base_url="https://cortex.vallery.net/v1",
        provider_name="cortex",
        dimensions=3,
    )

    [result] = embed_texts(["Sunshine Club"], provider)

    assert captured["url"] == "https://cortex.vallery.net/v1/embeddings"
    assert captured["payload"]["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert captured["payload"]["input"] == ["Sunshine Club"]
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert result.embedding == [0.1, 0.2, 0.3]
    assert result.embedding_provider == "cortex"
    assert result.embedding_status == "embedded"


def test_gemini_provider_calls_rest_api_and_validates_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response({"embedding": {"values": [0.1, 0.2, 0.3]}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = GeminiEmbeddingProvider(api_key="test-key", model="gemini-embedding-2", dimensions=3)

    [result] = embed_texts(["Sunshine Club"], provider)

    assert captured["url"].endswith("/models/gemini-embedding-2:embedContent")
    assert captured["payload"]["content"]["parts"][0]["text"] == "Sunshine Club"
    assert captured["payload"]["output_dimensionality"] == 3
    assert captured["headers"]["X-goog-api-key"] == "test-key"
    assert result.embedding == [0.1, 0.2, 0.3]
    assert result.embedding_status == "embedded"
    assert result.embedding_provider == "gemini"
    assert result.semantic_quality is True


def test_gemini_provider_fails_when_dimensions_do_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response({"embedding": {"values": [0.1]}}))
    provider = GeminiEmbeddingProvider(api_key="test-key", model="gemini-embedding-001", dimensions=3)

    with pytest.raises(EmbeddingProviderError, match="returned 1 dimensions"):
        provider.embed(["Sunshine Club"])


def test_gemini_provider_surfaces_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"error":"bad model"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = GeminiEmbeddingProvider(api_key="test-key", model="bad-model", dimensions=3)

    with pytest.raises(EmbeddingProviderError, match="bad model") as error:
        provider.embed(["Sunshine Club"])

    assert error.value.status_code == 400


def test_gemini_provider_requires_api_key() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="GEMINI_API_KEY"):
        GeminiEmbeddingProvider(api_key="")


def test_smoke_test_returns_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUNSHINE_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.setenv("SUNSHINE_EMBEDDING_DIMENSIONS", "5")

    summary = run_smoke_test(["one", "two"])

    assert summary == {
        "provider": "local",
        "model": "local-placeholder",
        "dimensions": 5,
        "embedding_status": {"placeholder": 2},
        "text_count": 2,
    }


def test_gemini_provider_extracts_resource_exhausted_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="https://example.test",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=BytesIO(
                b'{"error":{"message":"Your prepayment credits are depleted.","status":"RESOURCE_EXHAUSTED"}}'
            ),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = GeminiEmbeddingProvider(api_key="test-key", model="gemini-embedding-2", dimensions=3)

    with pytest.raises(EmbeddingProviderError, match="prepayment credits") as error:
        provider.embed(["Sunshine Club"])

    assert error.value.status_code == 429
    assert error.value.status == "RESOURCE_EXHAUSTED"
