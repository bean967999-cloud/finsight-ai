"""Atomically save one traceable chunk version for a parsed document."""

from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.domain.document_chunking import ChunkDraft
from finsight.domain.document_data import DocumentParseStatus
from finsight.infrastructure.database.models import Document, DocumentChunk, DocumentParseJob
from finsight.services.document_chunk_source import ChunkSource

SessionProvider = Callable[[], Session]


class ChunkPersistenceError(RuntimeError):
    """A chunk batch is invalid or conflicts with an existing version."""


class DocumentChunkPersistenceService:
    def __init__(self, session_provider: SessionProvider) -> None:
        self._sessions = session_provider

    def save(self, source: ChunkSource, chunks: Sequence[ChunkDraft]) -> tuple[int, ...]:
        """Save all chunks once; an identical retry returns the original IDs."""
        if not chunks:
            raise ChunkPersistenceError("Chunk batch must not be empty")
        version = chunks[0].chunk_version
        coordinates = {
            (page.page_number, block.block_index)
            for page in source.parsed_document.pages
            for block in page.blocks
        }
        for index, chunk in enumerate(chunks):
            if (
                chunk.document_id != source.document_id
                or chunk.parse_job_id != source.parse_job_id
                or chunk.chunk_version != version
                or chunk.chunk_index != index
            ):
                raise ChunkPersistenceError("Chunk batch has mixed provenance or noncontiguous indices")
            if any(
                (ref.page_number, ref.block_index) not in coordinates
                for ref in chunk.source_blocks
            ):
                raise ChunkPersistenceError("Chunk refers to a missing source block")

        with self._sessions() as session, session.begin():
            # Serialize writers for one document before checking the unique version key.
            document = session.scalar(
                select(Document).where(Document.id == source.document_id).with_for_update()
            )
            job = session.get(DocumentParseJob, source.parse_job_id)
            if (
                document is None
                or job is None
                or job.document_id != document.id
                or job.status != DocumentParseStatus.SUCCEEDED
                or job.source_sha256 != source.source_sha256
                or document.content_sha256 != source.source_sha256
            ):
                raise ChunkPersistenceError("Source document or parse job is no longer valid")
            existing = list(
                session.scalars(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_id == source.document_id,
                        DocumentChunk.chunk_version == version,
                    )
                    .order_by(DocumentChunk.chunk_index)
                )
            )
            if existing:
                if len(existing) != len(chunks) or any(
                    self._signature(row) != self._draft_signature(draft)
                    for row, draft in zip(existing, chunks, strict=True)
                ):
                    raise ChunkPersistenceError("Chunk version already contains different data")
                return tuple(row.id for row in existing)

            rows = [
                DocumentChunk(
                    document_id=draft.document_id,
                    parse_job_id=draft.parse_job_id,
                    chunk_index=draft.chunk_index,
                    chunk_version=draft.chunk_version,
                    kind=draft.kind.value,
                    content=draft.content,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    section_title=draft.section_path[-1] if draft.section_path else None,
                    section_path=list(draft.section_path),
                    source_blocks=[ref.model_dump() for ref in draft.source_blocks],
                    table_format=draft.table_format.value if draft.table_format else None,
                    asset_path=draft.asset_path,
                    content_sha256=draft.content_sha256,
                )
                for draft in chunks
            ]
            session.add_all(rows)
            session.flush()
            return tuple(row.id for row in rows)

    @staticmethod
    def _draft_signature(draft: ChunkDraft) -> tuple[object, ...]:
        return (
            draft.parse_job_id, draft.chunk_index, draft.kind.value, draft.content,
            draft.page_start, draft.page_end, list(draft.section_path),
            [ref.model_dump() for ref in draft.source_blocks],
            draft.table_format.value if draft.table_format else None, draft.asset_path,
            draft.content_sha256,
        )

    @staticmethod
    def _signature(row: DocumentChunk) -> tuple[object, ...]:
        return (
            row.parse_job_id, row.chunk_index, row.kind, row.content,
            row.page_start, row.page_end, row.section_path, row.source_blocks,
            row.table_format, row.asset_path, row.content_sha256,
        )
