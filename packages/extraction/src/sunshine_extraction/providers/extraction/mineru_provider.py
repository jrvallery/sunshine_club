"""MinerU extraction provider boundary."""

from sunshine_extraction.providers.extraction.optional_local import OptionalLocalExtractionProvider


class MinerUExtractionProvider(OptionalLocalExtractionProvider):
    provider_name = "mineru"
    package_name = "mineru"
    not_enabled_warning = "mineru_provider_not_enabled"


__all__ = ["MinerUExtractionProvider"]
