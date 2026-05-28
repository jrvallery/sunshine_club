"""SQLite-backed cache for local model call outputs."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


class SQLiteModelCallCache:
    """Small local JSON cache keyed by provider/model input hashes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def get_json(self, namespace: str, cache_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "select payload_json from model_call_cache where namespace = ? and cache_key = ?",
                (namespace, cache_key),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        return payload if isinstance(payload, dict) else None

    def set_json(self, namespace: str, cache_key: str, payload: dict[str, Any]) -> None:
        now = int(time.time())
        payload_json = json.dumps(payload, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                insert into model_call_cache(namespace, cache_key, payload_json, created_at, updated_at, hit_count)
                values (?, ?, ?, ?, ?, 0)
                on conflict(namespace, cache_key) do update set
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (namespace, cache_key, payload_json, now, now),
            )

    def record_hit(self, namespace: str, cache_key: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update model_call_cache
                set hit_count = hit_count + 1, last_hit_at = ?
                where namespace = ? and cache_key = ?
                """,
                (int(time.time()), namespace, cache_key),
            )

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists model_call_cache (
                    namespace text not null,
                    cache_key text not null,
                    payload_json text not null,
                    created_at integer not null,
                    updated_at integer not null,
                    last_hit_at integer,
                    hit_count integer not null default 0,
                    primary key(namespace, cache_key)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def model_call_cache_from_env() -> SQLiteModelCallCache | None:
    configured = os.environ.get("SUNSHINE_MODEL_CACHE_PATH", "").strip()
    if not configured:
        return None
    return SQLiteModelCallCache(configured)


__all__ = ["SQLiteModelCallCache", "model_call_cache_from_env"]
