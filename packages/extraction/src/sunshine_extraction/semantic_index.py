"""Build and query a semantic index from reviewed golden labels."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sunshine_extraction.embeddings import EmbeddingProvider, embed_texts, provider_from_env
from sunshine_extraction.services.env import load_pipeline_env


DEFAULT_LABELS_DB = ".local/sunshine-review.sqlite"
DEFAULT_INDEX_DB = ".local/sunshine-semantic-index.sqlite"


@dataclass(frozen=True)
class GoldenLabel:
    id: int | str
    source_path: str
    relative_path: str
    sample_path: str | None
    extracted_text_snippet: str | None
    correct_primary_tag: str
    correct_secondary_tags: list[str]
    notes: str | None


def build_semantic_index(
    labels_db: str | Path = DEFAULT_LABELS_DB,
    output_db: str | Path = DEFAULT_INDEX_DB,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    labels = load_golden_labels(labels_db, limit=limit)
    output_path = Path(output_db)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    provider = embedding_provider or provider_from_env()
    texts = [_index_text(label) for label in labels]
    embeddings = embed_texts(texts, provider) if texts else []

    with sqlite3.connect(output_path) as connection:
        connection.executescript(
            """
            create table if not exists semantic_index (
                source_path text primary key,
                golden_label_id text not null,
                relative_path text not null,
                sample_path text,
                correct_primary_tag text not null,
                correct_secondary_tags_json text not null default '[]',
                extracted_text_snippet text,
                notes text,
                index_text text not null,
                embedding_json text not null,
                embedding_provider text not null,
                embedding_model text not null,
                embedding_dimensions integer not null,
                semantic_quality integer not null,
                updated_at text not null default (datetime('now'))
            );
            """
        )
        for label, index_text, embedding in zip(labels, texts, embeddings, strict=True):
            connection.execute(
                """
                insert into semantic_index (
                    source_path, golden_label_id, relative_path, sample_path, correct_primary_tag,
                    correct_secondary_tags_json, extracted_text_snippet, notes, index_text, embedding_json,
                    embedding_provider, embedding_model, embedding_dimensions, semantic_quality, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                on conflict(source_path) do update set
                    golden_label_id=excluded.golden_label_id,
                    relative_path=excluded.relative_path,
                    sample_path=excluded.sample_path,
                    correct_primary_tag=excluded.correct_primary_tag,
                    correct_secondary_tags_json=excluded.correct_secondary_tags_json,
                    extracted_text_snippet=excluded.extracted_text_snippet,
                    notes=excluded.notes,
                    index_text=excluded.index_text,
                    embedding_json=excluded.embedding_json,
                    embedding_provider=excluded.embedding_provider,
                    embedding_model=excluded.embedding_model,
                    embedding_dimensions=excluded.embedding_dimensions,
                    semantic_quality=excluded.semantic_quality,
                    updated_at=datetime('now')
                """,
                (
                    label.source_path,
                    label.id,
                    label.relative_path,
                    label.sample_path,
                    label.correct_primary_tag,
                    json.dumps(label.correct_secondary_tags, sort_keys=True),
                    label.extracted_text_snippet,
                    label.notes,
                    index_text,
                    json.dumps(embedding.embedding),
                    embedding.embedding_provider,
                    embedding.embedding_model,
                    embedding.embedding_dimensions,
                    1 if embedding.semantic_quality else 0,
                ),
            )

    return {
        "labels_db": str(labels_db),
        "output_db": str(output_path),
        "indexed": len(labels),
        "embedding_provider": embeddings[0].embedding_provider if embeddings else provider.__class__.__name__,
        "embedding_model": embeddings[0].embedding_model if embeddings else provider.model,
        "embedding_dimensions": embeddings[0].embedding_dimensions if embeddings else provider.dimensions,
        "semantic_quality": bool(embeddings[0].semantic_quality) if embeddings else False,
    }


def search_semantic_index(
    index_db: str | Path,
    query_text: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    provider = embedding_provider or provider_from_env()
    query_embedding = embed_texts([query_text], provider)[0].embedding
    with sqlite3.connect(index_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            select source_path, relative_path, sample_path, correct_primary_tag, correct_secondary_tags_json,
                   extracted_text_snippet, notes, index_text, embedding_json, embedding_provider,
                   embedding_model, embedding_dimensions, semantic_quality
            from semantic_index
            """
        ).fetchall()
    ranked = []
    for row in rows:
        embedding = [float(value) for value in json.loads(row["embedding_json"])]
        score = _cosine_similarity(query_embedding, embedding)
        ranked.append(
            {
                "score": score,
                "source_path": row["source_path"],
                "relative_path": row["relative_path"],
                "sample_path": row["sample_path"],
                "correct_primary_tag": row["correct_primary_tag"],
                "correct_secondary_tags": _json_list(row["correct_secondary_tags_json"]),
                "extracted_text_snippet": row["extracted_text_snippet"],
                "notes": row["notes"],
                "embedding_provider": row["embedding_provider"],
                "embedding_model": row["embedding_model"],
                "embedding_dimensions": row["embedding_dimensions"],
                "semantic_quality": bool(row["semantic_quality"]),
            }
        )
    return sorted(ranked, key=lambda result: result["score"], reverse=True)[:limit]


def load_golden_labels(labels_db: str | Path, *, limit: int | None = None) -> list[GoldenLabel]:
    query = """
        select id, source_path, relative_path, sample_path, extracted_text_snippet,
               correct_primary_tag, correct_secondary_tags_json, notes
        from golden_labels
        order by updated_at desc, id desc
    """
    params: list[Any] = []
    if limit is not None:
        query += " limit ?"
        params.append(limit)
    with sqlite3.connect(labels_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, params).fetchall()
    return [
        GoldenLabel(
            id=row["id"],
            source_path=row["source_path"],
            relative_path=row["relative_path"],
            sample_path=row["sample_path"],
            extracted_text_snippet=row["extracted_text_snippet"],
            correct_primary_tag=row["correct_primary_tag"],
            correct_secondary_tags=_json_list(row["correct_secondary_tags_json"]),
            notes=row["notes"],
        )
        for row in rows
    ]


def _index_text(label: GoldenLabel) -> str:
    parts = [
        f"relative_path: {label.relative_path}",
        f"correct_primary_tag: {label.correct_primary_tag}",
    ]
    if label.correct_secondary_tags:
        parts.append(f"correct_secondary_tags: {', '.join(label.correct_secondary_tags)}")
    if label.extracted_text_snippet:
        parts.append(f"extracted_text: {label.extracted_text_snippet}")
    if label.notes:
        parts.append(f"review_notes: {label.notes}")
    return "\n".join(parts)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or query the Sunshine semantic tag index.")
    parser.add_argument("--labels", "--labels-db", dest="labels_db", default=DEFAULT_LABELS_DB)
    parser.add_argument("--output", "--output-db", dest="output_db", default=DEFAULT_INDEX_DB)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--query", help="Optional query text to search after building the index.")
    parser.add_argument("--query-limit", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    load_pipeline_env()
    args = _parse_args()
    summary = build_semantic_index(args.labels_db, args.output_db, limit=args.limit)
    output: dict[str, Any] = {"ok": True, **summary}
    if args.query:
        output["matches"] = search_semantic_index(args.output_db, args.query, limit=args.query_limit)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
