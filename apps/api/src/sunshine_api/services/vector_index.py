"""Vector-index rebuild services for local Qdrant collections."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Protocol

from sunshine_extraction.providers.vectorstores import QdrantVectorStoreProvider, VectorStoreProvider


class PostgresConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        ...

    def close(self) -> None:
        ...


ConnectFactory = Callable[[str], PostgresConnection]


def rebuild_qdrant_from_postgres(
    *,
    database_url: str | None = None,
    run_key: str | None = None,
    collection: str | None = None,
    limit: int | None = None,
    vector_store: VectorStoreProvider | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    """Replay semantic-quality Postgres embeddings into the configured Qdrant collection."""

    resolved_database_url = database_url or os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
    if not resolved_database_url:
        raise ValueError("DATABASE_URL or SUNSHINE_DATABASE_URL is required to rebuild the Qdrant index")
    connection = (connect_factory or _connect_with_psycopg)(resolved_database_url)
    try:
        rows = _fetch_index_rows(connection, run_key=run_key, limit=limit)
    finally:
        connection.close()

    chunks = [_chunk_row(row) for row in rows]
    embeddings = [_embedding_row(row) for row in rows]
    active_vector_store = vector_store or QdrantVectorStoreProvider(collection=collection)
    result = active_vector_store.upsert_embeddings(chunks, embeddings)
    return {
        "ok": result.status in {"indexed", "skipped"},
        "run_key": run_key,
        "collection": collection or result.collection,
        "requested_limit": limit,
        "source_row_count": len(rows),
        "vector_store": result.as_row(),
    }


def _fetch_index_rows(connection: PostgresConnection, *, run_key: str | None, limit: int | None) -> list[dict[str, Any]]:
    where = ["e.embedding_status = 'embedded'", "e.semantic_quality = true", "e.embedding is not null"]
    params: list[Any] = []
    if run_key:
        where.append("r.run_key = %s")
        params.append(run_key)
    limit_sql = ""
    if limit is not None:
        limit_sql = "limit %s"
        params.append(limit)
    cursor = connection.execute(
        f"""
        select
            r.run_key,
            c.source_path,
            c.relative_path,
            c.sample_path,
            c.chunk_id,
            c.chunk_index,
            c.chunk_kind,
            c.content,
            c.metadata as chunk_metadata,
            e.embedding_provider,
            e.embedding_model,
            e.embedding_dimensions,
            e.embedding_status,
            e.semantic_quality,
            e.embedding::text as embedding
        from pipeline_chunk_embeddings e
        join pipeline_chunks c on c.run_id = e.run_id and c.chunk_id = e.chunk_id
        join pipeline_runs r on r.id = e.run_id
        where {" and ".join(where)}
        order by r.created_at desc, c.chunk_index asc
        {limit_sql}
        """,
        tuple(params),
    )
    fetched = cursor.fetchall()
    return [_row_to_dict(row) for row in fetched]


def _chunk_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": row.get("source_path"),
        "relative_path": row.get("relative_path"),
        "sample_path": row.get("sample_path"),
        "chunk_id": row.get("chunk_id"),
        "chunk_index": row.get("chunk_index"),
        "chunk_kind": row.get("chunk_kind"),
        "text": row.get("content") or "",
        "metadata": _json_value(row.get("chunk_metadata")),
        "run_key": row.get("run_key"),
    }


def _embedding_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": row.get("source_path"),
        "relative_path": row.get("relative_path"),
        "chunk_id": row.get("chunk_id"),
        "embedding_provider": row.get("embedding_provider"),
        "embedding_model": row.get("embedding_model"),
        "embedding_dimensions": row.get("embedding_dimensions"),
        "embedding_status": row.get("embedding_status"),
        "semantic_quality": bool(row.get("semantic_quality")),
        "embedding": _vector_value(row.get("embedding")),
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"Unsupported Postgres row type: {type(row).__name__}")


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _vector_value(value: Any) -> list[float]:
    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, str):
        cleaned = value.strip().removeprefix("[").removesuffix("]")
        if not cleaned:
            return []
        return [float(item) for item in cleaned.split(",")]
    return []


def _connect_with_psycopg(database_url: str) -> PostgresConnection:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


__all__ = ["rebuild_qdrant_from_postgres"]
