"""Native local file probing with no model calls."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from sunshine_extraction.domain.file_probe import FileProbe
from sunshine_extraction.services.content import IMAGE_EXTENSIONS
from sunshine_extraction.services.content import SampleFile


class NativeFileProbeProvider:
    provider = "native"

    def probe(self, sample: SampleFile) -> dict[str, Any]:
        path = sample.sample_path
        suffix = path.suffix.lower()
        mime_type = mimetypes.guess_type(path.name)[0]
        size_bytes = path.stat().st_size
        base = {
            "source_path": sample.source_path,
            "relative_path": sample.relative_path,
            "sample_path": str(path),
            "provider": self.provider,
            "mime_type": mime_type,
            "extension": suffix,
            "size_bytes": size_bytes,
        }
        if suffix == ".pdf":
            return self._probe_pdf(path, base).as_row()
        if suffix in IMAGE_EXTENSIONS:
            return self._probe_image(path, base).as_row()
        return FileProbe(
            **base,
            status="probed",
            media_type=_media_type(suffix, mime_type),
            page_count=None,
            embedded_text_chars=None,
            image_only_pdf_likelihood=None,
            encrypted=None,
            width=None,
            height=None,
            warnings=[],
            metadata={"local_only": True},
        ).as_row()

    def _probe_pdf(self, path: Path, base: dict[str, Any]) -> FileProbe:
        warnings: list[str] = []
        page_count: int | None = None
        embedded_text_chars: int | None = None
        encrypted: bool | None = None
        image_only_pdf_likelihood: float | None = None
        metadata: dict[str, Any] = {"local_only": True}
        status = "probed"
        try:
            reader = PdfReader(str(path))
            encrypted = bool(reader.is_encrypted)
            if encrypted:
                try:
                    reader.decrypt("")
                except Exception as error:  # noqa: BLE001 - pypdf has multiple encryption errors.
                    warnings.append("pdf_encrypted_or_locked")
                    metadata["probe_error"] = str(error)
            if not warnings:
                page_count = len(reader.pages)
                sampled_pages = min(page_count, 3)
                text = "".join(page.extract_text() or "" for page in reader.pages[:sampled_pages])
                embedded_text_chars = len(text.strip())
                metadata["sampled_pages"] = sampled_pages
                if page_count == 0:
                    warnings.append("pdf_has_no_pages")
                    image_only_pdf_likelihood = 0.0
                elif embedded_text_chars == 0:
                    image_only_pdf_likelihood = 0.95
                elif embedded_text_chars < 100:
                    image_only_pdf_likelihood = 0.55
                    warnings.append("pdf_sparse_embedded_text")
                else:
                    image_only_pdf_likelihood = 0.05
        except Exception as error:  # noqa: BLE001 - probe failures should be captured.
            status = "failed"
            warnings.append("pdf_probe_failed")
            metadata["probe_error"] = str(error)
            metadata["exception_type"] = type(error).__name__
        return FileProbe(
            **base,
            status=status,
            media_type="pdf",
            page_count=page_count,
            embedded_text_chars=embedded_text_chars,
            image_only_pdf_likelihood=image_only_pdf_likelihood,
            encrypted=encrypted,
            width=None,
            height=None,
            warnings=warnings,
            metadata=metadata,
        )

    def _probe_image(self, path: Path, base: dict[str, Any]) -> FileProbe:
        warnings: list[str] = []
        width: int | None = None
        height: int | None = None
        metadata: dict[str, Any] = {"local_only": True}
        status = "probed"
        try:
            with Image.open(path) as image:
                width = image.width
                height = image.height
                metadata.update(
                    {
                        "image_format": image.format,
                        "mode": image.mode,
                        "frame_count": getattr(image, "n_frames", 1),
                    }
                )
        except UnidentifiedImageError as error:
            status = "failed"
            warnings.append("image_probe_failed")
            metadata["probe_error"] = str(error)
            metadata["exception_type"] = type(error).__name__
        return FileProbe(
            **base,
            status=status,
            media_type="image",
            page_count=None,
            embedded_text_chars=None,
            image_only_pdf_likelihood=None,
            encrypted=None,
            width=width,
            height=height,
            warnings=warnings,
            metadata=metadata,
        )


def _media_type(suffix: str, mime_type: str | None) -> str:
    if mime_type:
        return mime_type.split("/", 1)[0]
    if suffix in {".mov", ".mp4", ".m4v", ".avi"}:
        return "video"
    if suffix in {".xls", ".xlsx", ".xlsm", ".csv"}:
        return "spreadsheet"
    if suffix in {".txt", ".md", ".rtf", ".doc", ".docx"}:
        return "document"
    return "unknown"
