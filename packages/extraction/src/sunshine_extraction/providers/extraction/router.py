"""Deterministic local extraction-provider selection."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.domain.extraction_provider_selection import ExtractionProviderSelection
from sunshine_extraction.providers.extraction.base import ExtractionProvider
from sunshine_extraction.providers.extraction.docling_provider import DoclingExtractionProvider
from sunshine_extraction.services.content import SampleFile


def select_extraction_provider(
    sample: SampleFile,
    plan: dict[str, Any],
    file_probe: dict[str, Any],
    configured_provider: ExtractionProvider,
) -> dict[str, Any]:
    configured_name = _provider_name(configured_provider)
    hints = plan.get("provider_hints") if isinstance(plan.get("provider_hints"), dict) else {}
    preferred = str(hints.get("preferred_parser") or _preferred_provider(plan, file_probe))
    chain = _provider_chain(preferred, configured_name, plan)
    skipped: list[dict[str, Any]] = []

    selected = configured_name
    reason = "configured_provider_selected"
    if configured_name == preferred:
        selected = configured_name
        reason = "configured_provider_matches_preferred"
    elif preferred == "docling":
        docling_status = DoclingExtractionProvider().dependency_status()
        if docling_status.get("available"):
            selected = "docling"
            reason = "preferred_docling_available"
        else:
            selected = configured_name
            reason = "preferred_docling_unavailable_fell_back_to_configured"
            skipped.append({"provider": "docling", "reason": "dependency_unavailable", "status": docling_status})
    elif preferred == "current":
        selected = "current" if configured_name in {"current", "docling"} else configured_name
        reason = "preferred_current_for_native_text"

    selection = ExtractionProviderSelection(
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        sample_path=str(sample.sample_path),
        selected_provider=selected,
        provider_chain=chain,
        provider_selection_reason=reason,
        preferred_provider=preferred,
        configured_provider=configured_name,
        local_only_required=True,
        skipped_providers=skipped,
        metadata={
            "strategy": plan.get("strategy"),
            "document_subtype": plan.get("document_subtype"),
            "probe_status": file_probe.get("status"),
            "media_type": file_probe.get("media_type"),
            "image_only_pdf_likelihood": file_probe.get("image_only_pdf_likelihood"),
            "provider_hints": hints,
        },
    )
    return selection.as_row()


def _provider_name(provider: ExtractionProvider) -> str:
    return str(getattr(provider, "provider_name", provider.__class__.__name__)).lower()


def _preferred_provider(plan: dict[str, Any], file_probe: dict[str, Any]) -> str:
    if plan.get("strategy") == "ocr_page_level":
        return "docling"
    if file_probe.get("media_type") == "pdf" and file_probe.get("image_only_pdf_likelihood", 0) >= 0.8:
        return "docling"
    return "current"


def _provider_chain(preferred: str, configured: str, plan: dict[str, Any]) -> list[str]:
    chain = [preferred]
    fallback = "current"
    if plan.get("strategy") == "ocr_page_level":
        chain.append("cortex_ocr")
    if configured not in chain:
        chain.append(configured)
    if fallback not in chain:
        chain.append(fallback)
    return chain
