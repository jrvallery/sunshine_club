from sunshine_core.models import (
    ActionType,
    ClassificationCandidate,
    ClassificationResult,
    DocumentStatus,
    ExtractedDocument,
    FoundationRunRequest,
    ReviewTaskType,
    TagKind,
    ThinSliceOutcome,
)
from sunshine_core.path_resolution import PlacementResolutionError, resolve_destination
from sunshine_core.repository import InMemoryFoundationRepository


def run_foundation_slice(
    request: FoundationRunRequest,
    repository: InMemoryFoundationRepository,
) -> ThinSliceOutcome:
    document = repository.create_document(request.staged_file)
    document = repository.update_document_status(document, DocumentStatus.PROCESSING)

    extraction = _stub_extract(document.id, request.staged_file.name, request.staged_file.raw_metadata)
    classification = _stub_classify(extraction, request)

    if request.duplicate_candidates:
        document = repository.update_document_status(document, DocumentStatus.DUPLICATE_HOLD)
        review_task = repository.create_review_task(
            document,
            ReviewTaskType.DUPLICATE_REVIEW,
            {"duplicate_candidates": [str(candidate) for candidate in request.duplicate_candidates]},
        )
        return ThinSliceOutcome(
            document=document,
            extraction=extraction,
            classification=classification,
            review_task=review_task,
        )

    if (
        classification.top_score < request.routing_policy.min_confidence
        or classification.margin < request.routing_policy.min_margin
    ):
        document = repository.update_document_status(document, DocumentStatus.AWAITING_REVIEW)
        review_task = repository.create_review_task(
            document,
            ReviewTaskType.LOW_CONFIDENCE,
            {
                "top_score": classification.top_score,
                "margin": classification.margin,
                "candidates": [candidate.model_dump(mode="json") for candidate in classification.top_candidates],
            },
        )
        return ThinSliceOutcome(
            document=document,
            extraction=extraction,
            classification=classification,
            review_task=review_task,
        )

    primary_candidate = classification.top_candidates[0]
    mapping = next((item for item in request.mappings if item.tag_id == primary_candidate.tag_id and item.is_active), None)
    folder = next((item for item in request.folders if mapping and item.id == mapping.folder_id and item.is_active), None)
    placement_rule = next(
        (item for item in request.placement_rules if item.tag_id == primary_candidate.tag_id and item.is_active),
        None,
    )

    if mapping is None or folder is None or placement_rule is None:
        document = repository.update_document_status(document, DocumentStatus.AWAITING_REVIEW)
        review_task = repository.create_review_task(
            document,
            ReviewTaskType.MISSING_DESTINATION,
            {"tag_id": str(primary_candidate.tag_id), "tag_name": primary_candidate.tag_name},
        )
        return ThinSliceOutcome(
            document=document,
            extraction=extraction,
            classification=classification,
            review_task=review_task,
        )

    try:
        destination = resolve_destination(folder, placement_rule, extraction.metadata)
    except PlacementResolutionError as error:
        document = repository.update_document_status(document, DocumentStatus.AWAITING_REVIEW)
        review_task = repository.create_review_task(
            document,
            ReviewTaskType.MISSING_DESTINATION,
            {"reason": str(error), "tag_id": str(primary_candidate.tag_id)},
        )
        return ThinSliceOutcome(
            document=document,
            extraction=extraction,
            classification=classification,
            review_task=review_task,
        )

    document = repository.update_document_status(document, DocumentStatus.ROUTED)
    drive_action = repository.create_drive_action(
        document,
        ActionType.IMPORT_TO_DRIVE,
        destination.destination_path,
        {
            "drive_folder_file_id": destination.drive_folder_file_id,
            "primary_tag_id": str(primary_candidate.tag_id),
            "source_type": document.source_type.value,
        },
    )
    return ThinSliceOutcome(
        document=document,
        extraction=extraction,
        classification=classification,
        destination=destination,
        drive_action=drive_action,
    )


def _stub_extract(document_id, name: str, metadata: dict) -> ExtractedDocument:
    text = metadata.get("stub_text") or name
    extracted_metadata = dict(metadata)
    extracted_metadata.setdefault("upload_date", metadata.get("upload_date"))
    return ExtractedDocument(
        document_id=document_id,
        text=text,
        metadata=extracted_metadata,
        extraction_quality="stub",
    )


def _stub_classify(extraction: ExtractedDocument, request: FoundationRunRequest) -> ClassificationResult:
    primary_tags = [tag for tag in request.tags if tag.tag_kind == TagKind.PRIMARY and tag.is_active]
    haystack = f"{request.staged_file.name} {extraction.text}".lower()
    candidates: list[ClassificationCandidate] = []

    for tag in primary_tags:
        tag_name = tag.name.lower()
        if tag_name in haystack:
            confidence = 0.92
            evidence = [f"Matched controlled tag name '{tag.name}' in staged file text."]
        else:
            confidence = 0.25
            evidence = ["No deterministic stub match."]
        candidates.append(
            ClassificationCandidate(
                tag_id=tag.id,
                tag_name=tag.name,
                confidence=confidence,
                evidence=evidence,
            )
        )

    candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
    top_score = candidates[0].confidence if candidates else 0
    runner_up_score = candidates[1].confidence if len(candidates) > 1 else 0

    return ClassificationResult(
        document_id=extraction.document_id,
        model="stub-deterministic-classifier-v0",
        top_candidates=candidates[:5],
        top_score=top_score,
        runner_up_score=runner_up_score,
        margin=max(top_score - runner_up_score, 0),
        explanation="Stub classifier uses controlled tag-name matches only.",
        extraction_quality=extraction.extraction_quality,
    )
