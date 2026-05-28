"""Unstructured extraction provider boundary."""

from sunshine_extraction.providers.extraction.optional_local import OptionalLocalExtractionProvider


class UnstructuredExtractionProvider(OptionalLocalExtractionProvider):
    provider_name = "unstructured"
    package_name = "unstructured"
    not_enabled_warning = "unstructured_provider_not_enabled"


__all__ = ["UnstructuredExtractionProvider"]
