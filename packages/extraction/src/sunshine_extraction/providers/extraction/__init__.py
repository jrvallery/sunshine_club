"""Extraction provider interfaces and local provider implementations."""

from sunshine_extraction.providers.extraction.base import ExtractionProvider, ExtractionProviderAttempt


def __getattr__(name: str):
    if name == "CurrentExtractionProvider":
        from sunshine_extraction.providers.extraction.current import CurrentExtractionProvider

        return CurrentExtractionProvider
    if name == "DoclingExtractionProvider":
        from sunshine_extraction.providers.extraction.docling_provider import DoclingExtractionProvider

        return DoclingExtractionProvider
    if name == "HostedOpenAIOcrExecutor":
        from sunshine_extraction.providers.extraction.openai_ocr import HostedOpenAIOcrExecutor

        return HostedOpenAIOcrExecutor
    if name == "OpenAIVisionOcrExecutor":
        from sunshine_extraction.providers.extraction.openai_ocr import OpenAIVisionOcrExecutor

        return OpenAIVisionOcrExecutor
    if name == "MinerUExtractionProvider":
        from sunshine_extraction.providers.extraction.mineru_provider import MinerUExtractionProvider

        return MinerUExtractionProvider
    if name == "RAGFlowDeepDocExtractionProvider":
        from sunshine_extraction.providers.extraction.ragflow_deepdoc_provider import RAGFlowDeepDocExtractionProvider

        return RAGFlowDeepDocExtractionProvider
    if name == "UnstructuredExtractionProvider":
        from sunshine_extraction.providers.extraction.unstructured_provider import UnstructuredExtractionProvider

        return UnstructuredExtractionProvider
    if name == "CortexNativeOcrExecutor":
        from sunshine_extraction.providers.extraction.cortex_ocr import CortexNativeOcrExecutor

        return CortexNativeOcrExecutor
    if name == "LocalTesseractOcrExecutor":
        from sunshine_extraction.providers.extraction.tesseract_ocr import LocalTesseractOcrExecutor

        return LocalTesseractOcrExecutor
    if name == "extraction_provider_from_env":
        from sunshine_extraction.providers.extraction.factory import extraction_provider_from_env

        return extraction_provider_from_env
    if name == "extract_text":
        from sunshine_extraction.providers.extraction.native_text import extract_text

        return extract_text
    if name == "extract_photo_metadata":
        from sunshine_extraction.providers.extraction.photo_metadata import extract_photo_metadata

        return extract_photo_metadata
    if name == "extract_spreadsheet_metadata":
        from sunshine_extraction.providers.extraction.spreadsheet import extract_spreadsheet_metadata

        return extract_spreadsheet_metadata
    raise AttributeError(name)

__all__ = [
    "CurrentExtractionProvider",
    "CortexNativeOcrExecutor",
    "DoclingExtractionProvider",
    "ExtractionProvider",
    "ExtractionProviderAttempt",
    "HostedOpenAIOcrExecutor",
    "LocalTesseractOcrExecutor",
    "MinerUExtractionProvider",
    "OpenAIVisionOcrExecutor",
    "RAGFlowDeepDocExtractionProvider",
    "UnstructuredExtractionProvider",
    "extract_photo_metadata",
    "extract_spreadsheet_metadata",
    "extract_text",
    "extraction_provider_from_env",
]
