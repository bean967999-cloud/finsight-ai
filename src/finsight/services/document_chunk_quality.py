"""Read-only quality audit for one generated document chunk batch."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from finsight.domain.document_chunking import ChunkDraft, ChunkKind, SourceBlockRef
from finsight.domain.parsed_document import ParsedBlockType
from finsight.services.document_chunk_source import ChunkSource

_KIND_BY_BLOCK = {
    ParsedBlockType.HEADING: ChunkKind.TEXT,
    ParsedBlockType.TEXT: ChunkKind.TEXT,
    ParsedBlockType.TABLE: ChunkKind.TABLE,
    ParsedBlockType.IMAGE: ChunkKind.IMAGE_REFERENCE,
    ParsedBlockType.FORMULA: ChunkKind.FORMULA,
}


@dataclass(frozen=True, slots=True)
class ChunkQualityReport:
    document_id: int
    parse_job_id: int
    chunk_version: int | None
    chunk_count: int
    source_block_count: int
    covered_block_count: int
    missing_source_blocks: tuple[SourceBlockRef, ...]
    page_count: int
    covered_page_count: int
    kind_counts: dict[ChunkKind, int]
    average_chars: float
    max_chars_observed: int
    oversized_text_count: int
    oversized_special_count: int
    duplicate_content_count: int
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues

    @property
    def block_coverage_ratio(self) -> float:
        return self.covered_block_count / self.source_block_count


def audit_chunks(
    source: ChunkSource, chunks: Sequence[ChunkDraft], *, max_chars: int = 800
) -> ChunkQualityReport:
    """Check provenance/structure and expose size and duplicate diagnostics."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    expected = {
        SourceBlockRef(page_number=page.page_number, block_index=block.block_index):
        _KIND_BY_BLOCK[block.block_type]
        for page in source.parsed_document.pages
        for block in page.blocks
    }
    seen: set[SourceBlockRef] = set()
    issues: list[str] = []
    version = chunks[0].chunk_version if chunks else None
    if not chunks:
        issues.append("no chunks generated")
    for index, chunk in enumerate(chunks):
        if (
            chunk.document_id != source.document_id
            or chunk.parse_job_id != source.parse_job_id
            or chunk.chunk_version != version
        ):
            issues.append(f"chunk {index}: provenance or version mismatch")
        if chunk.chunk_index != index:
            issues.append(f"chunk {index}: noncontiguous index")
        for ref in chunk.source_blocks:
            expected_kind = expected.get(ref)
            if expected_kind is None:
                issues.append(f"chunk {index}: nonexistent source block {ref.page_number}:{ref.block_index}")
            elif expected_kind != chunk.kind:
                issues.append(f"chunk {index}: source block kind mismatch")
            else:
                seen.add(ref)
        if chunk.kind == ChunkKind.TEXT and len(chunk.content) > max_chars:
            issues.append(f"chunk {index}: text exceeds max_chars")
    missing = tuple(sorted(set(expected) - seen, key=lambda ref: (ref.page_number, ref.block_index)))
    if missing:
        issues.append(f"{len(missing)} source blocks are not covered")
    lengths = [len(chunk.content) for chunk in chunks]
    counts = Counter(chunk.kind for chunk in chunks)
    digest_counts = Counter(chunk.content_sha256 for chunk in chunks)
    return ChunkQualityReport(
        document_id=source.document_id,
        parse_job_id=source.parse_job_id,
        chunk_version=version,
        chunk_count=len(chunks),
        source_block_count=len(expected),
        covered_block_count=len(seen),
        missing_source_blocks=missing,
        page_count=source.parsed_document.page_count,
        covered_page_count=len({ref.page_number for ref in seen}),
        kind_counts=dict(counts),
        average_chars=sum(lengths) / len(lengths) if lengths else 0.0,
        max_chars_observed=max(lengths, default=0),
        oversized_text_count=sum(
            chunk.kind == ChunkKind.TEXT and len(chunk.content) > max_chars for chunk in chunks
        ),
        oversized_special_count=sum(
            chunk.kind != ChunkKind.TEXT and len(chunk.content) > max_chars for chunk in chunks
        ),
        duplicate_content_count=sum(count - 1 for count in digest_counts.values() if count > 1),
        issues=tuple(issues),
    )
