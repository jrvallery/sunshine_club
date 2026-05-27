"""Command builders for dashboard-triggered pipeline runs."""

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


def _batch_command(
    *,
    input_root: str,
    output_dir: str,
    embedding_provider: str | None,
    enable_llm_tags: bool,
    llm_tag_provider: str | None,
    ocr_fallback_provider: str | None,
    semantic_index_path: str | None,
) -> list[str]:
    command = [
        ".venv/bin/python",
        "-m",
        "sunshine_extraction.langgraph_pipeline",
        "--input-root",
        input_root,
        "--output-dir",
        output_dir,
        "--retry-attempts",
        "1",
    ]
    if embedding_provider:
        command.extend(["--embedding-provider", embedding_provider])
    if enable_llm_tags:
        command.append("--enable-llm-tags")
    if llm_tag_provider:
        command.extend(["--llm-tag-provider", llm_tag_provider])
    if ocr_fallback_provider:
        command.extend(["--ocr-fallback-provider", ocr_fallback_provider])
    if semantic_index_path:
        command.extend(["--semantic-index-path", semantic_index_path])
    return command


def _single_file_command(
    *,
    input_file: str,
    source_path: str,
    relative_path: str,
    output_dir: str,
    embedding_provider: str | None,
    enable_llm_tags: bool,
    llm_tag_provider: str | None,
    ocr_fallback_provider: str | None,
    semantic_index_path: str | None,
) -> list[str]:
    command = [
        ".venv/bin/python",
        "-m",
        "sunshine_extraction.langgraph_pipeline",
        "--input-file",
        input_file,
        "--source-path",
        source_path,
        "--relative-path",
        relative_path,
        "--output-dir",
        output_dir,
        "--retry-attempts",
        "1",
    ]
    if embedding_provider:
        command.extend(["--embedding-provider", embedding_provider])
    if enable_llm_tags:
        command.append("--enable-llm-tags")
    if llm_tag_provider:
        command.extend(["--llm-tag-provider", llm_tag_provider])
    if ocr_fallback_provider:
        command.extend(["--ocr-fallback-provider", ocr_fallback_provider])
    if semantic_index_path:
        command.extend(["--semantic-index-path", semantic_index_path])
    return command


def _batch_input_sample_count(input_root: str) -> int:
    input_path = Path(input_root)
    if not input_path.exists() or not input_path.is_dir():
        return 0
    count = 0
    for index_path in input_path.glob("*/index.jsonl"):
        try:
            with index_path.open("r", encoding="utf-8") as input_file:
                count += sum(1 for line in input_file if line.strip())
        except OSError:
            continue
    return count

