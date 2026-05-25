from uuid import uuid4

from sunshine_core.models import (
    ControlledTag,
    DateSource,
    FolderTarget,
    FoundationRunRequest,
    PlacementRule,
    PlacementRuleType,
    StagedFileRecord,
    TagFolderMapping,
    TagKind,
)
from sunshine_core.repository import InMemoryFoundationRepository
from sunshine_core.thin_slice import run_foundation_slice


def test_foundation_slice_emits_pending_action_for_high_confidence_file() -> None:
    tag_id = uuid4()
    folder_id = uuid4()
    request = FoundationRunRequest(
        staged_file=StagedFileRecord(
            source_path="sunshineclub/inbox/receipt-2026.pdf",
            name="receipt-2026.pdf",
            mime_type="application/pdf",
            raw_metadata={"upload_date": "2026-05-24"},
        ),
        tags=[ControlledTag(id=tag_id, name="receipt", tag_kind=TagKind.PRIMARY)],
        folders=[
            FolderTarget(
                id=folder_id,
                name="Receipts",
                drive_folder_file_id="drive-folder-1",
                path_hint="Receipts",
            )
        ],
        mappings=[TagFolderMapping(tag_id=tag_id, folder_id=folder_id)],
        placement_rules=[
            PlacementRule(
                tag_id=tag_id,
                rule_type=PlacementRuleType.BY_YEAR,
                date_source=DateSource.UPLOAD_DATE,
            )
        ],
    )

    outcome = run_foundation_slice(request, InMemoryFoundationRepository())

    assert outcome.destination is not None
    assert outcome.destination.destination_path == "Receipts/2026"
    assert outcome.drive_action is not None
    assert outcome.drive_action.status == "pending"
    assert outcome.review_task is None


def test_foundation_slice_emits_review_for_low_confidence_file() -> None:
    request = FoundationRunRequest(
        staged_file=StagedFileRecord(
            source_path="sunshineclub/inbox/unknown.pdf",
            name="unknown.pdf",
            mime_type="application/pdf",
        ),
        tags=[ControlledTag(id=uuid4(), name="receipt", tag_kind=TagKind.PRIMARY)],
        folders=[],
        mappings=[],
        placement_rules=[],
    )

    outcome = run_foundation_slice(request, InMemoryFoundationRepository())

    assert outcome.review_task is not None
    assert outcome.review_task.task_type == "low_confidence"
    assert outcome.drive_action is None
