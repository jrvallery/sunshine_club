"""Extraction provider interfaces and local provider implementations."""

from sunshine_extraction.providers.extraction.base import ExtractionProvider, ExtractionProviderAttempt
from sunshine_extraction.providers.extraction.current import CurrentExtractionProvider
from sunshine_extraction.providers.extraction.docling_provider import DoclingExtractionProvider
from sunshine_extraction.providers.extraction.factory import extraction_provider_from_env

__all__ = [
    "CurrentExtractionProvider",
    "DoclingExtractionProvider",
    "ExtractionProvider",
    "ExtractionProviderAttempt",
    "extraction_provider_from_env",
]
