"""RAGFlow DeepDoc extraction provider boundary."""

from sunshine_extraction.providers.extraction.optional_local import OptionalLocalExtractionProvider


class RAGFlowDeepDocExtractionProvider(OptionalLocalExtractionProvider):
    provider_name = "ragflow_deepdoc"
    package_name = "deepdoc"
    not_enabled_warning = "ragflow_deepdoc_provider_not_enabled"


__all__ = ["RAGFlowDeepDocExtractionProvider"]
