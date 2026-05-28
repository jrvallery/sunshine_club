"""Document segmentation services."""

from sunshine_extraction.services.segmentation.page_grouping import attach_segment_ids_to_chunks, propose_document_segments

__all__ = ["attach_segment_ids_to_chunks", "propose_document_segments"]
