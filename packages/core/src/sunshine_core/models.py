from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    NAS = "nas"
    UPLOAD = "upload"


class SourceCollection(str, Enum):
    SUNSHINE_SHARED_FOLDERS = "sunshine_shared_folders"
    FROM_MAC_PASS = "from_mac_pass"
    PAIGE_AGENT_FILES = "paige_agent_files"
    GOOGLE_DRIVE_DELTA = "google_drive_delta"
    ARCHIVE = "archive"
    MANIFEST = "manifest"
    OTHER = "other"


class FileContentClass(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    SCANNED_DOCUMENT = "scanned_document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    EMAIL = "email"
    GOOGLE_NATIVE_EXPORT = "google_native_export"
    MANIFEST = "manifest"
    CODE_OR_WORKSPACE_ARTIFACT = "code_or_workspace_artifact"
    BINARY_OR_UNKNOWN = "binary_or_unknown"


class ExtractionQuality(str, Enum):
    STUB = "stub"
    EMPTY = "empty"
    OK = "ok"
    POOR = "poor"


class DocumentStatus(str, Enum):
    DISCOVERED = "discovered"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    ROUTED = "routed"
    IGNORED = "ignored"
    DUPLICATE_HOLD = "duplicate_hold"
    FAILED = "failed"


class TagKind(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class PlacementRuleType(str, Enum):
    FLAT = "flat"
    BY_YEAR = "by_year"
    BY_YEAR_MONTH = "by_year_month"


class DateSource(str, Enum):
    DOCUMENT_DATE = "document_date"
    CAPTURED_DATE = "captured_date"
    UPLOAD_DATE = "upload_date"


class ReviewTaskType(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    DUPLICATE_REVIEW = "duplicate_review"
    MISFILED_FILE = "misfiled_file"
    MISSING_DESTINATION = "missing_destination"
    MAPPING_MIGRATION = "mapping_migration"


class ActionType(str, Enum):
    MOVE = "move"
    IMPORT_TO_DRIVE = "import_to_drive"
    ROLLBACK_MOVE = "rollback_move"


class StagedFileRecord(BaseModel):
    source_type: SourceType = SourceType.NAS
    source_collection: SourceCollection = SourceCollection.OTHER
    source_path: str
    name: str
    mime_type: str
    extension: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    source_mtime: datetime | None = None
    content_class: FileContentClass = FileContentClass.BINARY_OR_UNKNOWN
    checksum: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRecord(StagedFileRecord):
    id: UUID
    status: DocumentStatus = DocumentStatus.DISCOVERED
    is_canonical: bool = False


class ExtractedDocument(BaseModel):
    document_id: UUID
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    extraction_quality: ExtractionQuality = ExtractionQuality.STUB


class ExtractionArtifact(BaseModel):
    document_id: UUID
    extractor: str
    extractor_version: str | None = None
    content_class_before: FileContentClass
    content_class_after: FileContentClass
    text: str
    normalized_payload: dict[str, Any] = Field(default_factory=dict)
    quality: ExtractionQuality
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ControlledTag(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    tag_kind: TagKind
    is_active: bool = True


class FolderTarget(BaseModel):
    id: UUID
    name: str
    drive_folder_file_id: str
    path_hint: str
    is_active: bool = True


class TagFolderMapping(BaseModel):
    tag_id: UUID
    folder_id: UUID
    is_active: bool = True


class PlacementRule(BaseModel):
    tag_id: UUID
    rule_type: PlacementRuleType
    date_source: DateSource
    is_active: bool = True


class ClassificationCandidate(BaseModel):
    tag_id: UUID
    tag_name: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    document_id: UUID
    model: str
    top_candidates: list[ClassificationCandidate]
    top_score: float = Field(ge=0, le=1)
    runner_up_score: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    explanation: str
    extraction_quality: str


class RoutingPolicy(BaseModel):
    min_confidence: float = Field(default=0.8, ge=0, le=1)
    min_margin: float = Field(default=0.15, ge=0, le=1)


class DestinationResolution(BaseModel):
    folder_id: UUID
    drive_folder_file_id: str
    destination_path: str
    rule_type: PlacementRuleType


class ReviewTaskRecord(BaseModel):
    id: UUID
    document_id: UUID
    task_type: ReviewTaskType
    status: Literal["open", "in_progress", "resolved", "dismissed"] = "open"
    payload: dict[str, Any] = Field(default_factory=dict)


class DriveActionRecord(BaseModel):
    id: UUID
    document_id: UUID
    action_type: ActionType
    status: Literal["pending", "applied", "failed", "rolled_back"] = "pending"
    from_path: str | None = None
    to_path: str
    payload: dict[str, Any] = Field(default_factory=dict)


class FoundationRunRequest(BaseModel):
    staged_file: StagedFileRecord
    tags: list[ControlledTag]
    folders: list[FolderTarget]
    mappings: list[TagFolderMapping]
    placement_rules: list[PlacementRule]
    routing_policy: RoutingPolicy = Field(default_factory=RoutingPolicy)
    duplicate_candidates: list[UUID] = Field(default_factory=list)


class ThinSliceOutcome(BaseModel):
    document: DocumentRecord
    extraction: ExtractedDocument
    classification: ClassificationResult
    destination: DestinationResolution | None = None
    review_task: ReviewTaskRecord | None = None
    drive_action: DriveActionRecord | None = None
