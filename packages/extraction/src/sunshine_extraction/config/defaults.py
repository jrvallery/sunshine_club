"""Shared configuration defaults for Sunshine extraction workflows."""

from __future__ import annotations

from pathlib import Path

DEFAULT_MANIFEST_ROOT = Path("/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25")
DEFAULT_INPUT_ROOT = DEFAULT_MANIFEST_ROOT / "qa samples"
DEFAULT_OUTPUT_DIR = DEFAULT_MANIFEST_ROOT / "sample-pipeline"
DEFAULT_CORRECTED_PATH = DEFAULT_MANIFEST_ROOT / "corrected-content-classes.jsonl"
DEFAULT_PLAN_PATH = DEFAULT_MANIFEST_ROOT / "extraction-plan.jsonl"
DEFAULT_TAXONOMY_PATH = Path("docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json")

DEFAULT_CORTEX_BASE_URL = "https://cortex.vallery.net"
DEFAULT_CORTEX_MODEL = "gemma4-26b"
DEFAULT_CORTEX_OCR_MODEL = "paddleocr-ppocr-cpu"
DEFAULT_OPENAI_TAG_MODEL = "disabled-hosted-openai"
DEFAULT_OPENAI_OCR_MODEL = "gpt-4.1-mini"

EXPECTED_STRATEGIES = {
    "ocr_page_level",
    "photo_metadata",
    "text_extraction",
    "spreadsheet_table_extraction",
    "deferred_technical",
}

INITIAL_SAMPLE_LIMITS = {
    "accepted-image-random-100": 10,
    "accepted-scanned-document-random-100": 10,
    "changed-image-to-scanned_document-image_scan_policy_path_or_name": 5,
    "changed-scanned_document-to-document-pdf_extractable_text_detected": 5,
    "changed-document-to-scanned_document-pdf_image_only_or_empty_text": 5,
    "changed-binary_or_unknown-to-spreadsheet-macro_enabled_spreadsheet_review": 1,
}
