"""Semantic index status helpers for API routes."""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import selectors
import sqlite3
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import Any

from sunshine_api.review_store import ReviewStore


def _semantic_index_status(index_db: str | Path) -> dict[str, Any]:
    path = Path(index_db)
    status: dict[str, Any] = {
        "index_db": str(path),
        "exists": path.exists(),
        "indexed": 0,
        "updated_at": None,
        "embedding_provider": None,
        "embedding_model": None,
        "embedding_dimensions": None,
        "semantic_quality": None,
    }
    if not path.exists():
        return status
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                select count(*) as indexed,
                       max(updated_at) as updated_at,
                       max(embedding_provider) as embedding_provider,
                       max(embedding_model) as embedding_model,
                       max(embedding_dimensions) as embedding_dimensions,
                       min(semantic_quality) as semantic_quality
                from semantic_index
                """
            ).fetchone()
    except sqlite3.Error as error:
        status["error"] = str(error)
        return status
    if row:
        status.update(
            {
                "indexed": int(row["indexed"] or 0),
                "updated_at": row["updated_at"],
                "embedding_provider": row["embedding_provider"],
                "embedding_model": row["embedding_model"],
                "embedding_dimensions": row["embedding_dimensions"],
                "semantic_quality": bool(row["semantic_quality"]) if row["semantic_quality"] is not None else None,
            }
        )
    return status

