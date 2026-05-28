"""Domain contracts shared by graph nodes, providers, and services."""

from sunshine_extraction.domain.documents import IMAGE_EXTENSIONS, SPREADSHEET_EXTENSIONS, TEXT_EXTENSIONS, SampleFile
from sunshine_extraction.domain.extraction import ExtractionResult, OcrArtifacts, OcrDocumentResult, OcrExecutor, OcrPageResult

__all__ = [
    "IMAGE_EXTENSIONS",
    "SPREADSHEET_EXTENSIONS",
    "TEXT_EXTENSIONS",
    "ExtractionResult",
    "OcrArtifacts",
    "OcrDocumentResult",
    "OcrExecutor",
    "OcrPageResult",
    "SampleFile",
]
