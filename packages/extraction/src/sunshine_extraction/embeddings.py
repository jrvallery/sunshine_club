"""Embedding providers and smoke-test CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_PLACEHOLDER_DIMENSIONS = 64
DEFAULT_GEMINI_MODEL = "gemini-embedding-2"
DEFAULT_GEMINI_DIMENSIONS = 3072
DEFAULT_CORTEX_BASE_URL = "https://cortex.vallery.net"
DEFAULT_CORTEX_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_CORTEX_EMBEDDING_DIMENSIONS = 1024
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_OPENAI_EMBEDDING_DIMENSIONS = 3072
GEMINI_EMBEDDING_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"


class EmbeddingConfigurationError(RuntimeError):
    """Raised when embedding provider configuration is missing or invalid."""


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider fails."""

    def __init__(self, message: str, *, status_code: int | None = None, status: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.status = status


@dataclass(frozen=True)
class EmbeddingResult:
    text_index: int
    embedding: list[float]
    embedding_status: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    semantic_quality: bool

    def as_row(self) -> dict[str, Any]:
        return {
            "text_index": self.text_index,
            "embedding_status": self.embedding_status,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "semantic_quality": self.semantic_quality,
            "embedding": self.embedding,
        }


class EmbeddingProvider:
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class PlaceholderEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, dimensions: int = DEFAULT_PLACEHOLDER_DIMENSIONS) -> None:
        self.model = "local-placeholder"
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_stable_placeholder_vector(text, self.dimensions) for text in texts]


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        dimensions: int = DEFAULT_GEMINI_DIMENSIONS,
        timeout_seconds: float = 30,
    ) -> None:
        if not api_key:
            raise EmbeddingConfigurationError("GEMINI_API_KEY is required for Gemini embeddings")
        if dimensions <= 0:
            raise EmbeddingConfigurationError("SUNSHINE_EMBEDDING_DIMENSIONS must be greater than zero")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        payload = {
            "content": {"parts": [{"text": text}]},
            "output_dimensionality": self.dimensions,
        }
        request = urllib.request.Request(
            GEMINI_EMBEDDING_URL_TEMPLATE.format(model=self.model),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            message, status = _google_error_message(body)
            raise EmbeddingProviderError(
                f"Gemini embedding request failed: HTTP {error.code}: {message}",
                status_code=error.code,
                status=status,
            ) from error
        except urllib.error.URLError as error:
            raise EmbeddingProviderError(f"Gemini embedding request failed: {error.reason}") from error

        values = response_payload.get("embedding", {}).get("values")
        if not isinstance(values, list) or not all(isinstance(value, int | float) for value in values):
            raise EmbeddingProviderError("Gemini embedding response did not include numeric embedding.values")
        if len(values) != self.dimensions:
            raise EmbeddingProviderError(
                f"Gemini returned {len(values)} dimensions, expected {self.dimensions}; "
                "check SUNSHINE_EMBEDDING_DIMENSIONS"
            )
        return [float(value) for value in values]


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider_name: str,
        dimensions: int,
        timeout_seconds: float = 60,
    ) -> None:
        if not api_key:
            raise EmbeddingConfigurationError(f"{provider_name} API key is required for embeddings")
        if not model:
            raise EmbeddingConfigurationError(f"{provider_name} embedding model is required")
        if dimensions <= 0:
            raise EmbeddingConfigurationError("SUNSHINE_EMBEDDING_DIMENSIONS must be greater than zero")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            message, status = _openai_error_message(body)
            raise EmbeddingProviderError(
                f"{self.provider_name} embedding request failed: HTTP {error.code}: {message}",
                status_code=error.code,
                status=status,
            ) from error
        except urllib.error.URLError as error:
            raise EmbeddingProviderError(f"{self.provider_name} embedding request failed: {error.reason}") from error

        rows = response_payload.get("data")
        if not isinstance(rows, list):
            raise EmbeddingProviderError(f"{self.provider_name} embedding response did not include data rows")
        rows_by_index = sorted(rows, key=lambda row: row.get("index", 0) if isinstance(row, dict) else 0)
        vectors: list[list[float]] = []
        for row in rows_by_index:
            if not isinstance(row, dict):
                raise EmbeddingProviderError(f"{self.provider_name} embedding data row was not an object")
            values = row.get("embedding")
            if not isinstance(values, list) or not all(isinstance(value, int | float) for value in values):
                raise EmbeddingProviderError(f"{self.provider_name} embedding response did not include numeric embedding")
            if len(values) != self.dimensions:
                raise EmbeddingProviderError(
                    f"{self.provider_name} returned {len(values)} dimensions, expected {self.dimensions}; "
                    "check SUNSHINE_EMBEDDING_DIMENSIONS"
                )
            vectors.append([float(value) for value in values])
        return vectors


def provider_from_env() -> EmbeddingProvider:
    provider_name = os.environ.get("SUNSHINE_EMBEDDING_PROVIDER", "placeholder").strip().lower()
    if provider_name in {"", "placeholder", "local"}:
        dimensions = _env_int("SUNSHINE_EMBEDDING_DIMENSIONS", DEFAULT_PLACEHOLDER_DIMENSIONS)
        return PlaceholderEmbeddingProvider(dimensions=dimensions)
    if provider_name == "gemini":
        return GeminiEmbeddingProvider(
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            model=os.environ.get("SUNSHINE_EMBEDDING_MODEL", DEFAULT_GEMINI_MODEL),
            dimensions=_env_int("SUNSHINE_EMBEDDING_DIMENSIONS", DEFAULT_GEMINI_DIMENSIONS),
        )
    if provider_name in {"cortex", "openai-compatible"}:
        cortex_base_url = os.environ.get("CORTEX_OPENAI_BASE_URL") or _openai_base_url_from_cortex_base(
            os.environ.get("CORTEX_BASE_URL", DEFAULT_CORTEX_BASE_URL)
        )
        return OpenAICompatibleEmbeddingProvider(
            api_key=os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY", ""),
            model=os.environ.get("SUNSHINE_EMBEDDING_MODEL", DEFAULT_CORTEX_EMBEDDING_MODEL),
            base_url=cortex_base_url,
            provider_name="cortex",
            dimensions=_env_int("SUNSHINE_EMBEDDING_DIMENSIONS", DEFAULT_CORTEX_EMBEDDING_DIMENSIONS),
        )
    if provider_name == "openai":
        return OpenAICompatibleEmbeddingProvider(
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API", ""),
            model=os.environ.get("SUNSHINE_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBEDDING_MODEL),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            provider_name="openai",
            dimensions=_env_int("SUNSHINE_EMBEDDING_DIMENSIONS", DEFAULT_OPENAI_EMBEDDING_DIMENSIONS),
        )
    raise EmbeddingConfigurationError(f"Unsupported SUNSHINE_EMBEDDING_PROVIDER={provider_name!r}")


def embed_texts(texts: list[str], provider: EmbeddingProvider | None = None) -> list[EmbeddingResult]:
    active_provider = provider or provider_from_env()
    vectors = active_provider.embed(texts)
    if len(vectors) != len(texts):
        raise EmbeddingProviderError(f"Provider returned {len(vectors)} vectors for {len(texts)} texts")

    is_placeholder = isinstance(active_provider, PlaceholderEmbeddingProvider)
    provider_name = _embedding_provider_name(active_provider)
    return [
        EmbeddingResult(
            text_index=index,
            embedding=vector,
            embedding_status="placeholder" if is_placeholder else "embedded",
            embedding_provider="local" if is_placeholder else provider_name,
            embedding_model=active_provider.model,
            embedding_dimensions=len(vector),
            semantic_quality=not is_placeholder,
        )
        for index, vector in enumerate(vectors)
    ]


def run_smoke_test(texts: list[str]) -> dict[str, Any]:
    if not texts:
        raise EmbeddingConfigurationError("At least one smoke-test text is required")
    results = embed_texts(texts)
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.embedding_status] = status_counts.get(result.embedding_status, 0) + 1
    return {
        "provider": results[0].embedding_provider,
        "model": results[0].embedding_model,
        "dimensions": results[0].embedding_dimensions,
        "embedding_status": dict(sorted(status_counts.items())),
        "text_count": len(results),
    }


def _stable_placeholder_vector(text: str, dimensions: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dimensions:
        for byte in digest:
            values.append((byte / 127.5) - 1)
            if len(values) == dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return values


def _embedding_provider_name(provider: EmbeddingProvider) -> str:
    if isinstance(provider, PlaceholderEmbeddingProvider):
        return "local"
    if isinstance(provider, GeminiEmbeddingProvider):
        return "gemini"
    if isinstance(provider, OpenAICompatibleEmbeddingProvider):
        return provider.provider_name
    return provider.__class__.__name__


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise EmbeddingConfigurationError(f"{name} must be an integer") from error


def _load_embedding_env(env_path: str = ".env") -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except Exception:  # noqa: BLE001 - .env support is best-effort for CLI convenience.
        pass
    cortex_base = os.environ.get("CORTEX_BASE_URL")
    if cortex_base and not os.environ.get("CORTEX_OPENAI_BASE_URL"):
        os.environ["CORTEX_OPENAI_BASE_URL"] = _openai_base_url_from_cortex_base(cortex_base)
    cortex_api = os.environ.get("CORTEX_API_KEY")
    if cortex_api and not os.environ.get("CORTEX_OPENAI_API_KEY"):
        os.environ["CORTEX_OPENAI_API_KEY"] = cortex_api


def _google_error_message(body: str) -> tuple[str, str | None]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body, None
    error = payload.get("error")
    if not isinstance(error, dict):
        return body, None
    message = error.get("message")
    status = error.get("status")
    if isinstance(message, str):
        return message, status if isinstance(status, str) else None
    return body, status if isinstance(status, str) else None


def _openai_error_message(body: str) -> tuple[str, str | None]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body, None
    error = payload.get("error")
    if not isinstance(error, dict):
        return body, None
    message = error.get("message")
    status = error.get("code") or error.get("type")
    return (
        message if isinstance(message, str) else body,
        status if isinstance(status, str) else None,
    )


def _openai_base_url_from_cortex_base(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an embedding provider smoke test.")
    parser.add_argument(
        "--text",
        action="append",
        dest="texts",
        default=[],
        help="Text to embed. Can be repeated.",
    )
    parser.add_argument(
        "--jsonl-output",
        help="Optional path to write full embedding rows as JSONL. Do not commit this file.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _load_embedding_env()
    texts = args.texts or ["Sunshine Club embedding smoke test."]
    try:
        results = embed_texts(texts)
    except (EmbeddingConfigurationError, EmbeddingProviderError) as error:
        output: dict[str, Any] = {
            "ok": False,
            "error": str(error),
            "error_type": type(error).__name__,
        }
        if isinstance(error, EmbeddingProviderError):
            output["status_code"] = error.status_code
            output["provider_status"] = error.status
            if error.status_code == 429 or error.status == "RESOURCE_EXHAUSTED":
                output["action_required"] = "Enable billing or add Gemini API credits for this API key's project."
        print(json.dumps(output, indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from error

    if args.jsonl_output:
        with open(args.jsonl_output, "w", encoding="utf-8") as output_file:
            for result in results:
                output_file.write(json.dumps(result.as_row(), sort_keys=True) + "\n")

    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.embedding_status] = status_counts.get(result.embedding_status, 0) + 1
    summary = {
        "ok": True,
        "provider": results[0].embedding_provider,
        "model": results[0].embedding_model,
        "dimensions": results[0].embedding_dimensions,
        "embedding_status": dict(sorted(status_counts.items())),
        "text_count": len(results),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
