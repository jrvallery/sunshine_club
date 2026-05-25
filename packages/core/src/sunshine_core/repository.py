from uuid import uuid4

from sunshine_core.models import (
    ActionType,
    DocumentRecord,
    DocumentStatus,
    DriveActionRecord,
    ReviewTaskRecord,
    ReviewTaskType,
    StagedFileRecord,
)


class InMemoryFoundationRepository:
    """Temporary repository for the foundation slice.

    Postgres is the target source of truth. This repository keeps the first
    contract runnable before the SQL persistence adapter is implemented.
    """

    def __init__(self) -> None:
        self.documents: dict[str, DocumentRecord] = {}
        self.review_tasks: dict[str, ReviewTaskRecord] = {}
        self.drive_actions: dict[str, DriveActionRecord] = {}

    def create_document(self, staged_file: StagedFileRecord) -> DocumentRecord:
        document = DocumentRecord(id=uuid4(), **staged_file.model_dump())
        self.documents[str(document.id)] = document
        return document

    def update_document_status(self, document: DocumentRecord, status: DocumentStatus) -> DocumentRecord:
        updated = document.model_copy(update={"status": status})
        self.documents[str(updated.id)] = updated
        return updated

    def create_review_task(
        self,
        document: DocumentRecord,
        task_type: ReviewTaskType,
        payload: dict,
    ) -> ReviewTaskRecord:
        task = ReviewTaskRecord(
            id=uuid4(),
            document_id=document.id,
            task_type=task_type,
            payload=payload,
        )
        self.review_tasks[str(task.id)] = task
        return task

    def create_drive_action(
        self,
        document: DocumentRecord,
        action_type: ActionType,
        to_path: str,
        payload: dict,
    ) -> DriveActionRecord:
        action = DriveActionRecord(
            id=uuid4(),
            document_id=document.id,
            action_type=action_type,
            from_path=document.source_path,
            to_path=to_path,
            payload=payload,
        )
        self.drive_actions[str(action.id)] = action
        return action
