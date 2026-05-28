from __future__ import annotations

import json
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

from sunshine_extraction.embeddings import EmbeddingProviderError, PlaceholderEmbeddingProvider
from sunshine_extraction.sample_pipeline import (
    CortexNativeOcrExecutor,
    EscalatingOcrExecutor,
    ExtractionResult,
    LLMTagInspector,
    OcrDocumentResult,
    OcrExecutor,
    OcrPageResult,
    OpenAICompatibleLLMTagInspector,
    SampleFile,
    TaxonomyOptions,
    _chat_response_usage_fields,
    assign_tag_candidates,
    build_llm_tag_prompt,
    build_ocr_summary,
    calibrate_tag_confidence,
    chunk_content,
    combine_tag_candidates,
    embed_chunks,
    embed_chunks_with_fallback,
    extract_content,
    extraction_quality_gate,
    llm_tag_inspector_from_env,
    load_pipeline_env,
    ocr_executor_from_env,
    resolve_route_or_review,
    run_sample_pipeline,
    validate_extracted_text,
    validate_and_repair_extraction,
    write_pipeline_result,
)


class _FailingEmbeddingProvider(PlaceholderEmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("configured provider failed")


class _TeaLLMTagInspector(LLMTagInspector):
    model = "test-llm"

    def inspect(self, **_kwargs):
        return {
            "llm_status": "inspected",
            "model": self.model,
            "primary_tag": "annual_spring_tea",
            "secondary_tags": ["event_material", "drive_search"],
            "confidence": 0.91,
            "evidence": ["filename mentions tea", "path is in Teas"],
            "rationale": "Tea evidence is strong.",
            "needs_review": False,
            "warning": None,
        }


class _UsageResponse:
    usage_metadata = {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    response_metadata = {}


class _TokenUsageResponse:
    usage_metadata = None
    response_metadata = {"token_usage": {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18}}


def test_llm_usage_helpers_normalize_openai_compatible_tokens() -> None:
    assert _chat_response_usage_fields(_UsageResponse()) == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert _chat_response_usage_fields(_TokenUsageResponse()) == {
        "input_tokens": 13,
        "output_tokens": 5,
        "total_tokens": 18,
    }


class _MissingOcrExecutor(OcrExecutor):
    def dependency_status(self) -> dict:
        return {"missing": ["tesseract"]}

    def ocr_sample(self, sample: SampleFile, plan: dict) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        return (
            OcrDocumentResult(
                source_path=sample.source_path,
                relative_path=sample.relative_path,
                sample_path=str(sample.sample_path),
                ocr_status="deferred",
                page_count=0,
                pages_ok=0,
                pages_failed=0,
                total_text_length=0,
                mean_confidence=None,
                quality="deferred",
                seconds=0,
                warnings=["ocr_executor_not_installed", "missing:tesseract"],
            ),
            [],
        )


class _SuccessfulOcrExecutor(OcrExecutor):
    def dependency_status(self) -> dict:
        return {"missing": [], "engine": "test-ocr"}

    def ocr_sample(self, sample: SampleFile, plan: dict) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        text = "Annual tea meeting minutes dental report " * 5
        page = OcrPageResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            page_number=1,
            page_count=1,
            ocr_engine="test-ocr",
            ocr_engine_version="1",
            ocr_status="ok",
            text=text,
            text_length=len(text),
            mean_confidence=91.0,
            word_count=len(text.split()),
            image_width=100,
            image_height=100,
            seconds=0.01,
            warnings=[],
        )
        document = OcrDocumentResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            ocr_status="ok",
            page_count=1,
            pages_ok=1,
            pages_failed=0,
            total_text_length=len(text),
            mean_confidence=91.0,
            quality="ok",
            seconds=0.01,
            warnings=[],
        )
        return document, [page]


class _PoorOcrExecutor(OcrExecutor):
    def dependency_status(self) -> dict:
        return {"missing": [], "engine": "poor-test-ocr"}

    def ocr_sample(self, sample: SampleFile, plan: dict) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        page = OcrPageResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            page_number=1,
            page_count=1,
            ocr_engine="poor-test-ocr",
            ocr_engine_version="1",
            ocr_status="ok",
            text="xqz",
            text_length=3,
            mean_confidence=40.0,
            word_count=1,
            image_width=100,
            image_height=100,
            seconds=0.01,
            warnings=[],
        )
        document = OcrDocumentResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            ocr_status="poor",
            page_count=1,
            pages_ok=1,
            pages_failed=0,
            total_text_length=3,
            mean_confidence=40.0,
            quality="poor",
            seconds=0.01,
            warnings=["ocr_confidence_below_threshold"],
        )
        return document, [page]


class _CountingFallbackOcrExecutor(_SuccessfulOcrExecutor):
    engine_name = "fallback-test-ocr"

    def __init__(self) -> None:
        self.calls = 0

    def dependency_status(self) -> dict:
        return {"missing": [], "engine": self.engine_name}

    def ocr_sample(self, sample: SampleFile, plan: dict) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        self.calls += 1
        return super().ocr_sample(sample, plan)


def _sample(path: Path, *, source_path: str = "/source/file", relative_path: str = "Sunshine shared folders/file") -> SampleFile:
    return SampleFile(
        sample_path=path,
        source_path=source_path,
        relative_path=relative_path,
        sample_group="accepted-image-random-100",
        sample_number=1,
        index_row={"metadata": {}},
    )


def _plan(strategy: str, **overrides) -> dict:
    row = {"strategy": strategy, "document_subtype": None, "defer_reason": None}
    row.update(overrides)
    return row


def test_text_extraction_plain_text_path(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes text", encoding="utf-8")

    extraction = extract_content(_sample(source), _plan("text_extraction"))
    quality = extraction_quality_gate(extraction)

    assert extraction.extraction_status == "extracted"
    assert extraction.text == "Meeting minutes text"
    assert quality["quality"] == "ok"


def test_photo_metadata_path(tmp_path: Path) -> None:
    image = tmp_path / "photo.jpg"
    Image.new("RGB", (320, 240), color="white").save(image)

    extraction = extract_content(_sample(image), _plan("photo_metadata"))
    quality = extraction_quality_gate(extraction)

    assert extraction.extraction_status == "metadata_extracted"
    assert extraction.metadata["width"] == 320
    assert extraction.metadata["height"] == 240
    assert quality["quality"] == "metadata_only"


def test_ocr_engine_missing_deferred_path(tmp_path: Path) -> None:
    image = tmp_path / "scan.jpg"
    Image.new("RGB", (320, 240), color="white").save(image)

    extraction = extract_content(
        _sample(image),
        _plan("ocr_page_level", document_subtype="scrapbook"),
        ocr_executor=_MissingOcrExecutor(),
    )
    quality = extraction_quality_gate(extraction)
    chunks = chunk_content(extraction, quality)

    assert extraction.extraction_status == "deferred_extractor"
    assert quality["quality"] == "deferred"
    assert chunks[0]["chunk_kind"] == "metadata"
    assert "ocr_executor_not_installed" in extraction.warnings


def test_image_ocr_success_path_chunks_text(tmp_path: Path) -> None:
    image = tmp_path / "scan.jpg"
    Image.new("RGB", (320, 240), color="white").save(image)

    extraction = extract_content(_sample(image), _plan("ocr_page_level"), ocr_executor=_SuccessfulOcrExecutor())
    quality = extraction_quality_gate(extraction)
    chunks = chunk_content(extraction, quality)

    assert extraction.extraction_status == "extracted"
    assert quality["quality"] == "ok"
    assert chunks[0]["chunk_kind"] == "text"
    assert "Annual tea meeting minutes" in chunks[0]["text"]


def test_ocr_escalates_poor_local_result_to_fallback(tmp_path: Path) -> None:
    image = tmp_path / "scan.jpg"
    Image.new("RGB", (320, 240), color="white").save(image)
    fallback = _CountingFallbackOcrExecutor()

    extraction = extract_content(
        _sample(image),
        _plan("ocr_page_level"),
        ocr_executor=EscalatingOcrExecutor(_PoorOcrExecutor(), fallback),
    )
    quality = extraction_quality_gate(extraction)

    assert fallback.calls == 1
    assert extraction.extraction_status == "extracted"
    assert quality["quality"] == "ok"
    assert "Annual tea meeting minutes" in extraction.text
    assert "ocr_fallback_used:fallback-test-ocr" in extraction.warnings
    assert "ocr_fallback_reason:poor" in extraction.warnings
    assert "ocr_original_snippet:xqz" in extraction.warnings
    assert any(warning.startswith("ocr_fallback_snippet:Annual tea meeting minutes") for warning in extraction.warnings)
    result = write_pipeline_result(
        _sample(image),
        {"final_class": "scanned_document"},
        _plan("ocr_page_level"),
        extraction,
        quality,
        chunks=[],
        embeddings=[],
        tag_candidates=[{"tag": "meeting_records", "confidence": 0.91, "evidence": [], "secondary_tags": []}],
        route={"route_status": "route_candidate", "review_reason": None},
        llm_inspection={"llm_status": "skipped"},
    )
    assert result["ocr_evidence"]["fallback_used"] is True
    assert result["ocr_evidence"]["fallback_provider"] == "fallback-test-ocr"
    assert result["ocr_evidence"]["fallback_reason"] == "poor"
    assert result["ocr_evidence"]["original_text_snippet"] == "xqz"
    assert "Annual tea meeting minutes" in result["ocr_evidence"]["fallback_text_snippet"]


def test_write_pipeline_result_quarantines_placement_when_route_requires_review(tmp_path: Path) -> None:
    source = tmp_path / "1992 minutes.txt"
    source.write_text("1992 Sunshine Club meeting minutes.", encoding="utf-8")
    extraction = ExtractionResult(
        sample=_sample(source, relative_path="Minutes/1992 minutes.txt"),
        plan=_plan("text_extraction"),
        extraction_status="extracted",
        text="1992 Sunshine Club meeting minutes.",
        metadata={},
        page_count=None,
        warnings=[],
    )
    result = write_pipeline_result(
        _sample(source, relative_path="Minutes/1992 minutes.txt"),
        {"final_class": "document"},
        _plan("text_extraction"),
        extraction,
        {"quality": "ok"},
        chunks=[],
        embeddings=[],
        tag_candidates=[{"tag": "meeting_records", "confidence": 0.61, "evidence": ["minutes"], "secondary_tags": []}],
        route={"route_status": "review_low_confidence_tag", "review_reason": "tag_confidence_below_threshold"},
        llm_inspection={"llm_status": "skipped"},
    )

    assert result["placement_status"] == "needs_review"
    assert result["destination_path"] == "90_Intake_Needs_Review/01_Governance_Admin"
    assert result["placement"]["blocked_destination_path"] == "01_Governance_Admin/1992"
    assert result["placement"]["placement_blocked_by_route"] is True
    assert result["placement"]["review_reason"] == "tag_confidence_below_threshold"


def test_ocr_does_not_escalate_good_local_result(tmp_path: Path) -> None:
    image = tmp_path / "scan.jpg"
    Image.new("RGB", (320, 240), color="white").save(image)
    fallback = _CountingFallbackOcrExecutor()

    extraction = extract_content(
        _sample(image),
        _plan("ocr_page_level"),
        ocr_executor=EscalatingOcrExecutor(_SuccessfulOcrExecutor(), fallback),
    )

    assert fallback.calls == 0
    assert extraction.extraction_status == "extracted"
    assert "ocr_fallback_used:fallback-test-ocr" not in extraction.warnings


def test_gibberish_pdf_text_layer_falls_back_to_ocr(tmp_path: Path) -> None:
    pdf = tmp_path / "scan-text-layer.pdf"
    pdf.write_bytes(b"fake pdf bytes handled by injected ocr executor")
    sample = _sample(pdf)
    original = ExtractionResult(
        sample=sample,
        plan=_plan("text_extraction"),
        extraction_status="extracted",
        text=("• I r/l -> B-e !!. t· . ----: '> - . . . • ' .. ,_ Membership ~Mor~ of\\ " * 8),
        metadata={"mime_type": "application/pdf"},
        page_count=1,
        warnings=[],
    )

    repaired = validate_and_repair_extraction(
        sample,
        original.plan,
        original,
        ocr_executor=_SuccessfulOcrExecutor(),
    )
    quality = extraction_quality_gate(repaired)

    assert repaired.plan["strategy"] == "ocr_page_level"
    assert repaired.metadata["original_extraction"]["strategy"] == "text_extraction"
    assert repaired.metadata["original_extraction"]["text_snippet"].startswith("• I r/l")
    assert "text_validation_failed:gibberish_suspected" in repaired.warnings
    assert "text_extraction_fallback_to_ocr:text_extraction" in repaired.warnings
    assert "Annual tea meeting minutes" in repaired.text
    assert quality["quality"] == "ok"


def test_gibberish_non_ocr_text_routes_to_text_quality_review(tmp_path: Path) -> None:
    text_file = tmp_path / "bad.txt"
    text_file.write_text("bad", encoding="utf-8")
    sample = _sample(text_file)
    original = ExtractionResult(
        sample=sample,
        plan=_plan("text_extraction"),
        extraction_status="extracted",
        text=("• I r/l -> B-e !!. t· . ----: '> - . . . • ' .. ,_ Membership ~Mor~ of\\ " * 8),
        metadata={"mime_type": "text/plain"},
        page_count=None,
        warnings=[],
    )

    repaired = validate_and_repair_extraction(sample, original.plan, original, ocr_executor=_SuccessfulOcrExecutor())
    quality = extraction_quality_gate(repaired)
    route = resolve_route_or_review([], quality, repaired.plan)

    assert repaired.plan["strategy"] == "text_extraction"
    assert quality["quality"] == "poor"
    assert route == {"route_status": "review_text_quality", "review_reason": "text_quality_not_trusted"}


def test_table_distorted_text_layer_fails_validation(tmp_path: Path) -> None:
    source = tmp_path / "budget.pdf"
    source.write_text("fake pdf", encoding="utf-8")
    distorted_table = "\n".join(
        [
            "__| __| wr Ler'ee | oreer've | eresy'ee | ossatre | oo'sey've | ELORb'ye |",
            "ZS89V'ST_ LSBOV'ST | LL 09ST | LLO9H'ST | LLOSH'ST | SOESH'ST |",
            "__| v8r | OBL _ wz | OL | 1982 Zo8t _ 350109U| = | 866TH'ST |",
            "soueje Suwuidag| Runosoy suit Jojwadg| 820'% SeBzO | ET BLOG |",
            "_SONVIVE ONIONS - if | ee | _ dl SAVILNO W101 (0068s) |",
            "looses) Buppayp oy saysuedt | ISAVILNO| t t | vee wo wo v0 zo",
            "WONT W101) vee 20 a |v0 wo | evo 0 | eo st0 eo wo 920",
            "99IU| cose i_ | 00'sZ s[euOUlaW | x '3WOONI | Lesess's seez0e",
        ]
        * 3
    )
    extraction = ExtractionResult(
        sample=_sample(source),
        plan=_plan("text_extraction"),
        extraction_status="extracted",
        text=distorted_table,
        metadata={},
        page_count=1,
        warnings=[],
    )

    validation = validate_extracted_text(extraction)
    repaired = validate_and_repair_extraction(_sample(source), _plan("text_extraction"), extraction, ocr_executor=None)
    quality = extraction_quality_gate(repaired)

    assert validation == {"status": "failed", "reason": "table_distortion_suspected"}
    assert repaired.plan["strategy"] == "ocr_page_level"
    assert quality["quality"] == "deferred"
    assert quality["requires_review"] is True
    assert "text_validation_failed:table_distortion_suspected" in repaired.warnings


def test_ocr_summary_records_failed_page_rate() -> None:
    summary = build_ocr_summary(
        [
            {"ocr_status": "ok", "seconds": 1.0, "warnings": []},
            {"ocr_status": "failed", "seconds": 1.5, "warnings": ["ocr_page_failed"]},
        ],
        [{"ocr_status": "poor", "quality": "poor", "seconds": 2.5, "warnings": ["ocr_confidence_below_threshold"]}],
    )

    assert summary["ocr_page_rows"] == 2
    assert summary["failed_page_rate"] == 0.5
    assert summary["by_quality"]["poor"] == 1


def test_ocr_quality_warning_splits_sparse_text_from_low_confidence(tmp_path: Path) -> None:
    sample = _sample(tmp_path / "scan.jpg")
    short_high_confidence = [
        OcrPageResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            page_number=1,
            page_count=1,
            ocr_engine="test",
            ocr_engine_version="1",
            ocr_status="ok",
            text="short text",
            text_length=10,
            mean_confidence=95.0,
            word_count=2,
            image_width=100,
            image_height=100,
            seconds=0.1,
            warnings=[],
        )
    ]
    from sunshine_extraction.sample_pipeline import _ocr_document_from_pages

    doc = _ocr_document_from_pages(sample, short_high_confidence, 0.1)

    assert doc.quality == "poor"
    assert doc.warnings == ["ocr_sparse_text_below_threshold"]


def test_ocr_text_is_passed_into_llm_tag_prompt(tmp_path: Path) -> None:
    image = tmp_path / "scan.jpg"
    Image.new("RGB", (320, 240), color="white").save(image)
    sample = _sample(image, relative_path="Sunshine shared folders/Minutes/scan.jpg")
    extraction = ExtractionResult(sample, _plan("ocr_page_level"), "extracted", "OCR text about meeting minutes", {}, 1, [])
    taxonomy = TaxonomyOptions(
        primary_tags=["meeting_records"],
        secondary_tags=["meeting_minutes"],
        primary_definitions={"meeting_records": "Meeting records"},
    )

    prompt = build_llm_tag_prompt(sample, {"final_class": "scanned_document"}, _plan("ocr_page_level"), extraction, taxonomy, [])

    assert "OCR text about meeting minutes" in prompt
    assert "competing_tags" in prompt
    assert "review_reason" in prompt


def test_spreadsheet_metadata_path(tmp_path: Path) -> None:
    workbook = tmp_path / "report.xlsm"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet />")
        archive.writestr("xl/vbaProject.bin", b"macro")

    extraction = extract_content(_sample(workbook), _plan("spreadsheet_table_extraction"))

    assert extraction.extraction_status == "metadata_extracted"
    assert extraction.metadata["sheet_entry_count"] == 1
    assert extraction.metadata["has_macros"] is True


def test_deferred_technical_path_has_no_chunks(tmp_path: Path) -> None:
    source = tmp_path / "file.pub"
    source.write_bytes(b"publisher")

    extraction = extract_content(_sample(source), _plan("deferred_technical", defer_reason="publisher_conversion_required"))
    quality = extraction_quality_gate(extraction)

    assert extraction.extraction_status == "deferred_technical"
    assert quality["can_chunk"] is False
    assert chunk_content(extraction, quality) == []


def test_deterministic_tag_assignment_and_route() -> None:
    sample = _sample(Path("tea.pdf"), relative_path="Sunshine shared folders/Teas/2007 tea guest list.pdf")
    extraction = ExtractionResult(sample, _plan("text_extraction"), "extracted", "guest list", {}, None, [])

    candidates = assign_tag_candidates(sample, {"review_notes": None}, _plan("text_extraction"), extraction)
    route = resolve_route_or_review(candidates, {"quality": "ok"}, _plan("text_extraction"))

    assert candidates[0]["tag"] == "annual_spring_tea"
    assert route["route_status"] == "route_candidate"


def test_historical_club_summary_beats_incidental_tea_reference() -> None:
    sample = _sample(
        Path("page-24.png"),
        relative_path="google-drive-delta-2026-05-25/Sunshine/Sunshine in Progress/Emily's Presidential Ideas/Bylaws and policies update/Current yearbook /Kathy Caldwell 2026 proof review/rendered-pages/page-24.png",
    )
    text = """
    Founders of Sunshine Club Emily Barclay Antels Ethel Reeder Dickens Harriet Secor Flanders Mary Smith
    Clara Donovan Witherow Clara H. Donovan, sponsor. Sunshine Club was organized in 1902 for helping poor people.
    The membership has grown to a limited quota of 50 active members. The club focuses on emergency dental care for
    school children and a program to assist local seniors with needed dental care. Chief sources of revenue are from
    the annual Sunshine Tea, the Sunshine Memorial Fund, and financial gifts.
    """
    extraction = ExtractionResult(sample, _plan("ocr_page_level"), "extracted", text, {}, 1, [])

    candidates = assign_tag_candidates(sample, {"review_notes": None}, _plan("ocr_page_level"), extraction)

    assert candidates[0]["tag"] == "history_archive_general"
    assert candidates[0]["secondary_tags"] == ["history_archive", "programs_mission"]
    assert "annual_spring_tea" not in {candidate["tag"] for candidate in candidates}


def test_ocr_metadata_only_routes_to_review() -> None:
    route = resolve_route_or_review(
        [{"tag": "scrapbooks", "confidence": 0.92, "evidence": []}],
        {"quality": "metadata_only"},
        _plan("ocr_page_level"),
    )

    assert route["route_status"] == "review_ocr_no_text"


def test_llm_tag_inspection_boosts_matching_deterministic_candidate() -> None:
    deterministic = [
        {
            "source_path": "/source/tea.pdf",
            "relative_path": "Sunshine shared folders/Teas/tea.pdf",
            "tag": "annual_spring_tea",
            "confidence": 0.88,
            "evidence": ["tea/guest-list evidence"],
            "secondary_tags": [],
            "assignment_source": "deterministic",
        }
    ]
    llm = {
        "llm_status": "inspected",
        "primary_tag": "annual_spring_tea",
        "secondary_tags": ["event_material"],
        "confidence": 0.92,
        "evidence": ["path contains Tea"],
    }

    [combined] = combine_tag_candidates(deterministic, llm)

    assert combined["tag"] == "annual_spring_tea"
    assert combined["confidence"] > deterministic[0]["confidence"]
    assert combined["secondary_tags"] == ["event_material"]
    assert combined["assignment_source"] == "deterministic+llm"


def test_llm_tag_schema_payload_is_normalized() -> None:
    taxonomy = TaxonomyOptions(
        primary_tags=["annual_spring_tea"],
        secondary_tags=["event_material"],
        primary_definitions={"annual_spring_tea": "Tea files"},
    )
    from sunshine_extraction.sample_pipeline import normalize_llm_inspection

    normalized = normalize_llm_inspection(
        {
            "primary_tag": "annual_spring_tea",
            "secondary_tags": ["event_material", "not_allowed"],
            "confidence": 1.2,
            "evidence": ["tea"],
            "competing_tags": ["annual_spring_tea", "not_allowed"],
            "rationale": "Strong evidence",
            "needs_review": True,
            "review_reason": "",
        },
        taxonomy,
        model="test-model",
    )

    assert normalized["llm_status"] == "inspected_with_invalid_fields"
    assert normalized["secondary_tags"] == ["event_material"]
    assert normalized["invalid_secondary_tags"] == ["not_allowed"]
    assert normalized["competing_tags"] == []
    assert normalized["invalid_competing_tags"] == ["not_allowed"]
    assert normalized["confidence"] == 1.0
    assert normalized["review_reason"] == "llm_requested_review"
    assert normalized["warnings"] == [
        "llm_invalid_secondary_tags:not_allowed",
        "llm_invalid_competing_tags:not_allowed",
    ]


def test_invalid_llm_primary_tag_is_rejected_before_candidate_merge() -> None:
    taxonomy = TaxonomyOptions(
        primary_tags=["annual_spring_tea"],
        secondary_tags=["event_material"],
        primary_definitions={"annual_spring_tea": "Tea files"},
    )
    from sunshine_extraction.sample_pipeline import normalize_llm_inspection

    normalized = normalize_llm_inspection(
        {
            "primary_tag": "not_a_real_primary",
            "secondary_tags": ["event_material"],
            "confidence": 0.99,
            "evidence": ["model invented a tag"],
            "competing_tags": ["annual_spring_tea"],
            "rationale": "Invalid response",
            "needs_review": False,
            "review_reason": "",
        },
        taxonomy,
        model="test-model",
    )
    deterministic = [
        {
            "source_path": "/source/tea.pdf",
            "relative_path": "Sunshine shared folders/Teas/tea.pdf",
            "tag": "annual_spring_tea",
            "confidence": 0.88,
            "evidence": ["tea/guest-list evidence"],
            "secondary_tags": [],
            "assignment_source": "deterministic",
        }
    ]

    combined = combine_tag_candidates(deterministic, normalized)
    calibrated, calibration = calibrate_tag_confidence(
        combined,
        {"quality": "ok"},
        _plan("text_extraction"),
        llm_inspection=normalized,
    )
    route = resolve_route_or_review(calibrated, {"quality": "ok"}, _plan("text_extraction"))

    assert normalized["llm_status"] == "invalid"
    assert normalized["primary_tag"] is None
    assert normalized["review_reason"] == "llm_primary_tag_invalid"
    assert normalized["warnings"] == ["llm_primary_tag_invalid"]
    assert [candidate["tag"] for candidate in combined] == ["annual_spring_tea"]
    assert "not_a_real_primary" not in json.dumps(combined)
    assert calibration["requires_review"] is True
    assert calibration["review_reason"] == "llm_primary_tag_invalid"
    assert route["route_status"] == "review_tag_confidence_calibration"
    assert route["review_reason"] == "llm_primary_tag_invalid"


def test_invalid_llm_structured_fields_force_review() -> None:
    deterministic = [
        {
            "source_path": "/source/tea.pdf",
            "relative_path": "Sunshine shared folders/Teas/tea.pdf",
            "tag": "annual_spring_tea",
            "confidence": 0.88,
            "evidence": ["tea/guest-list evidence"],
            "secondary_tags": [],
            "assignment_source": "deterministic",
        }
    ]
    llm = {
        "llm_status": "inspected_with_invalid_fields",
        "primary_tag": "annual_spring_tea",
        "secondary_tags": ["event_material"],
        "confidence": 0.92,
        "evidence": ["path contains Tea"],
        "warnings": ["llm_invalid_secondary_tags:not_allowed"],
    }

    combined = combine_tag_candidates(deterministic, llm)
    calibrated, calibration = calibrate_tag_confidence(
        combined,
        {"quality": "ok"},
        _plan("text_extraction"),
        llm_inspection=llm,
    )
    route = resolve_route_or_review(calibrated, {"quality": "ok"}, _plan("text_extraction"))
    result = write_pipeline_result(
        _sample(Path("tea.pdf"), relative_path="Sunshine shared folders/Teas/tea.pdf"),
        {"final_class": "document"},
        _plan("text_extraction"),
        ExtractionResult(
            _sample(Path("tea.pdf"), relative_path="Sunshine shared folders/Teas/tea.pdf"),
            _plan("text_extraction"),
            "extracted",
            "Annual Sunshine Tea material.",
            {},
            None,
            [],
        ),
        {"quality": "ok"},
        chunks=[],
        embeddings=[],
        tag_candidates=calibrated,
        route=route,
        llm_inspection=llm,
    )

    assert calibrated[0]["tag"] == "annual_spring_tea"
    assert calibration["requires_review"] is True
    assert calibration["review_reason"] == "llm_structured_output_invalid"
    assert route["route_status"] == "review_tag_confidence_calibration"
    assert route["review_reason"] == "llm_structured_output_invalid"
    assert result["llm_status"] == "inspected_with_invalid_fields"
    assert result["warnings"] == ["llm_invalid_secondary_tags:not_allowed"]


def test_failed_llm_tag_inspection_forces_review() -> None:
    candidates = [
        {
            "source_path": "/source/tea.pdf",
            "relative_path": "Sunshine shared folders/Teas/tea.pdf",
            "tag": "annual_spring_tea",
            "confidence": 0.91,
            "evidence": ["tea/guest-list evidence"],
            "secondary_tags": [],
            "assignment_source": "deterministic",
        }
    ]
    llm = {
        "llm_status": "failed",
        "primary_tag": None,
        "confidence": 0.0,
        "needs_review": True,
        "warning": "llm_tag_inspection_failed:TimeoutError",
    }

    calibrated, calibration = calibrate_tag_confidence(
        candidates,
        {"quality": "ok"},
        _plan("text_extraction"),
        llm_inspection=llm,
    )
    route = resolve_route_or_review(calibrated, {"quality": "ok"}, _plan("text_extraction"))

    assert calibration["requires_review"] is True
    assert calibration["review_reason"] == "llm_structured_output_unusable"
    assert route["route_status"] == "review_tag_confidence_calibration"
    assert "llm_structured_output_unusable:failed" in calibrated[0]["confidence_calibration_factors"]


def test_openai_compatible_llm_response_json_is_normalized() -> None:
    taxonomy = TaxonomyOptions(
        primary_tags=["annual_spring_tea"],
        secondary_tags=["event_material"],
        primary_definitions={"annual_spring_tea": "Tea files"},
    )
    from sunshine_extraction.sample_pipeline import _extract_json_object

    payload = _extract_json_object(
        '```json\n{"primary_tag":"annual_spring_tea","secondary_tags":["event_material"],'
        '"confidence":0.9,"evidence":["tea"],"rationale":"Tea evidence","needs_review":false}\n```'
    )

    assert json.loads(payload)["primary_tag"] == "annual_spring_tea"
    assert "secondary_tags" in payload


def test_llm_tag_inspector_factory_creates_cortex_provider(monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_LLM_TAG_PROVIDER", "cortex")
    monkeypatch.setenv("CORTEX_BASE_URL", "https://cortex.vallery.net")
    monkeypatch.setenv("CORTEX_MODEL", "gemma4-26b")
    monkeypatch.setenv("CORTEX_API_KEY", "test-cortex-key")

    inspector = llm_tag_inspector_from_env()

    assert isinstance(inspector, OpenAICompatibleLLMTagInspector)
    assert inspector.model == "gemma4-26b"
    assert inspector.base_url == "https://cortex.vallery.net/v1"


def test_llm_tag_inspector_auto_does_not_select_gemini(monkeypatch) -> None:
    monkeypatch.delenv("CORTEX_API_KEY", raising=False)
    monkeypatch.delenv("CORTEX_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CORTEX_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    inspector = llm_tag_inspector_from_env(provider_override="auto")

    assert isinstance(inspector, LLMTagInspector)
    assert not isinstance(inspector, OpenAICompatibleLLMTagInspector)
    assert inspector.model == "disabled"


def test_load_pipeline_env_normalizes_cortex_aliases(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CORTEX_BASE_URL=https://cortex.vallery.net\nCORTEX_API_KEY=test-secret\n", encoding="utf-8")
    monkeypatch.delenv("CORTEX_BASE_URL", raising=False)
    monkeypatch.delenv("CORTEX_API_KEY", raising=False)
    monkeypatch.delenv("CORTEX_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("CORTEX_OPENAI_API_KEY", raising=False)

    load_pipeline_env(env_file)

    assert __import__("os").environ["CORTEX_OPENAI_API_KEY"] == "test-secret"
    assert __import__("os").environ["CORTEX_OPENAI_BASE_URL"] == "https://cortex.vallery.net/v1"


def test_ocr_executor_factory_uses_cortex_native_ocr(monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_OCR_FALLBACK_PROVIDER", "cortex")
    monkeypatch.setenv("CORTEX_API_KEY", "test-cortex-key")
    monkeypatch.setenv("CORTEX_BASE_URL", "https://cortex.vallery.net")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API", raising=False)

    executor = ocr_executor_from_env()

    assert isinstance(executor, CortexNativeOcrExecutor)
    assert executor.base_url == "https://cortex.vallery.net"


def test_ocr_executor_factory_uses_cortex_primary_with_openai_escalation(monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_OCR_FALLBACK_PROVIDER", "cortex")
    monkeypatch.setenv("CORTEX_API_KEY", "test-cortex-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    executor = ocr_executor_from_env()

    assert isinstance(executor, EscalatingOcrExecutor)
    assert isinstance(executor.primary, CortexNativeOcrExecutor)
    assert executor.fallback.engine_name == "openai:gpt-4.1-mini"


def test_cortex_native_ocr_uploads_file_and_maps_pages(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "scan.png"
    Image.new("RGB", (16, 16), color="white").save(image)
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({"pages": [{"page_number": 1, "text": "Meeting minutes", "confidence": 0.93}]}).encode("utf-8")

    def fake_urlopen(request: urllib.request.Request, timeout: float):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    executor = CortexNativeOcrExecutor(api_key="test-cortex-key", base_url="https://cortex.vallery.net")

    document, pages = executor.ocr_sample(_sample(image), _plan("ocr_page_level"))

    assert captured["url"] == "https://cortex.vallery.net/v1/ocr"
    assert captured["headers"]["Authorization"] == "Bearer test-cortex-key"
    assert b'name="file"; filename="scan.png"' in captured["body"]
    assert document.quality == "poor"
    assert pages[0].text == "Meeting minutes"
    assert pages[0].mean_confidence == 93.0
    assert pages[0].ocr_engine == "cortex:paddleocr-ppocr-cpu"
    assert "ocr_model_used:cortex:paddleocr-ppocr-cpu" in pages[0].warnings


def test_load_pipeline_env_normalizes_openai_api_alias(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API=test-secret\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    load_pipeline_env(env_file)

    assert "OPENAI_API_KEY" in __import__("os").environ


def test_embedding_rows_are_joined_to_chunks() -> None:
    chunk = {
        "source_path": "/source/file",
        "relative_path": "Sunshine shared folders/file",
        "chunk_id": "chunk-1",
        "text": "hello",
    }

    [row] = embed_chunks([chunk], PlaceholderEmbeddingProvider(dimensions=4))

    assert row["chunk_id"] == "chunk-1"
    assert row["embedding_status"] == "placeholder"
    assert len(row["embedding"]) == 4


def test_embedding_provider_failure_falls_back_to_placeholder() -> None:
    chunk = {
        "source_path": "/source/file",
        "relative_path": "Sunshine shared folders/file",
        "chunk_id": "chunk-1",
        "text": "hello",
    }

    rows, warnings = embed_chunks_with_fallback([chunk], _FailingEmbeddingProvider(dimensions=4))

    assert rows[0]["embedding_status"] == "placeholder"
    assert warnings == ["embedding_provider_failed_fell_back_to_placeholder"]


def test_one_input_sample_produces_one_pipeline_result(tmp_path: Path) -> None:
    input_root = tmp_path / "qa samples"
    group = input_root / "accepted-image-random-100"
    group.mkdir(parents=True)
    image = group / "001 - 2006_May_Sunshine_Tea_2006_0014_a.jpg"
    Image.new("RGB", (100, 100), color="white").save(image)
    source_path = "/mnt/source/tea.jpg"
    relative_path = "Sunshine shared folders/Teas/tea.jpg"
    (group / "index.jsonl").write_text(
        json.dumps({"link_name": image.name, "source_path": source_path, "relative_path": relative_path, "number": 1}) + "\n",
        encoding="utf-8",
    )
    corrected = tmp_path / "corrected.jsonl"
    plan = tmp_path / "plan.jsonl"
    corrected.write_text(
        json.dumps({"source_path": source_path, "relative_path": relative_path, "final_class": "image", "final_status": "accepted"}) + "\n",
        encoding="utf-8",
    )
    plan.write_text(
        json.dumps({"source_path": source_path, "relative_path": relative_path, "strategy": "photo_metadata", "document_subtype": None}) + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    summary = run_sample_pipeline(
        input_root,
        output_dir=output_dir,
        corrected_path=corrected,
        plan_path=plan,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=_TeaLLMTagInspector(),
    )

    results = [json.loads(line) for line in (output_dir / "sample-pipeline-results.jsonl").read_text().splitlines()]
    embeddings = [json.loads(line) for line in (output_dir / "sample-embeddings.jsonl").read_text().splitlines()]
    llm_rows = [json.loads(line) for line in (output_dir / "sample-llm-tag-inspections.jsonl").read_text().splitlines()]

    assert summary["selected_sample_count"] == 1
    assert len(results) == 1
    assert results[0]["extraction_status"] == "metadata_extracted"
    assert results[0]["chunk_count"] == 1
    assert results[0]["llm_status"] == "inspected"
    assert results[0]["tag_assignment_source"] == "deterministic+llm"
    assert results[0]["secondary_tags"] == ["event_material", "drive_search"]
    assert embeddings[0]["embedding_status"] == "placeholder"
    assert llm_rows[0]["primary_tag"] == "annual_spring_tea"


def test_one_scanned_input_produces_ocr_rows_chunks_and_result(tmp_path: Path) -> None:
    input_root = tmp_path / "qa samples"
    group = input_root / "accepted-scanned-document-random-100"
    group.mkdir(parents=True)
    image = group / "001 - scan.jpg"
    Image.new("RGB", (100, 100), color="white").save(image)
    source_path = "/mnt/source/scan.jpg"
    relative_path = "Sunshine shared folders/Minutes/scan.jpg"
    (group / "index.jsonl").write_text(
        json.dumps({"link_name": image.name, "source_path": source_path, "relative_path": relative_path, "number": 1}) + "\n",
        encoding="utf-8",
    )
    corrected = tmp_path / "corrected.jsonl"
    plan = tmp_path / "plan.jsonl"
    corrected.write_text(
        json.dumps({"source_path": source_path, "relative_path": relative_path, "final_class": "scanned_document", "final_status": "accepted"}) + "\n",
        encoding="utf-8",
    )
    plan.write_text(
        json.dumps({"source_path": source_path, "relative_path": relative_path, "strategy": "ocr_page_level", "document_subtype": "scanned_or_photographed_document"}) + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    summary = run_sample_pipeline(
        input_root,
        output_dir=output_dir,
        corrected_path=corrected,
        plan_path=plan,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        ocr_executor=_SuccessfulOcrExecutor(),
    )

    ocr_pages = [json.loads(line) for line in (output_dir / "sample-ocr-pages.jsonl").read_text().splitlines()]
    ocr_docs = [json.loads(line) for line in (output_dir / "sample-ocr-documents.jsonl").read_text().splitlines()]
    results = [json.loads(line) for line in (output_dir / "sample-pipeline-results.jsonl").read_text().splitlines()]
    ocr_summary = json.loads((output_dir / "sample-ocr-summary.json").read_text())

    assert summary["selected_sample_count"] == 1
    assert len(ocr_pages) == 1
    assert len(ocr_docs) == 1
    assert ocr_docs[0]["ocr_status"] == "ok"
    assert results[0]["extraction_status"] == "extracted"
    assert results[0]["ocr_status"] == "ok"
    assert ocr_summary["ocr_document_rows"] == 1
