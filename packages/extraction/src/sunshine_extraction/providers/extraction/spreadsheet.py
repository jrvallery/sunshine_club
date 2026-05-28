"""Spreadsheet metadata extraction helpers."""

from __future__ import annotations

import zipfile
from typing import Any

from sunshine_extraction.domain.extraction import ExtractionResult
from sunshine_extraction.services.content import SPREADSHEET_EXTENSIONS, SampleFile


def extract_spreadsheet_metadata(sample: SampleFile, plan: dict[str, Any]) -> ExtractionResult:
    metadata: dict[str, Any] = {"suffix": sample.sample_path.suffix.lower(), "size_bytes": sample.sample_path.stat().st_size}
    warnings: list[str] = []
    if sample.sample_path.suffix.lower() in SPREADSHEET_EXTENSIONS:
        try:
            with zipfile.ZipFile(sample.sample_path) as workbook:
                names = workbook.namelist()
                metadata["zip_entry_count"] = len(names)
                metadata["sheet_entry_count"] = len([name for name in names if name.startswith("xl/worksheets/")])
                metadata["has_macros"] = "xl/vbaProject.bin" in names
        except zipfile.BadZipFile:
            warnings.append("spreadsheet_zip_metadata_failed")
    else:
        warnings.append("spreadsheet_parser_not_installed")
    return ExtractionResult(sample, plan, "metadata_extracted", "", metadata, None, warnings)
