from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType
from finsight.domain.parsed_document import ParsedBlock, ParsedDocument, ParsedPage
from finsight.services.document_chunk_quality import audit_chunks
from finsight.services.document_chunk_source import ChunkSource
from finsight.services.financial_chunker import FinancialTextChunker


def source_for(*blocks: ParsedBlock) -> ChunkSource:
    parsed = ParsedDocument(
        document_id=7, source_sha256="a" * 64, parser_name="fixture",
        parser_version="1", page_count=1,
        pages=(ParsedPage(page_number=1, blocks=blocks),), markdown="sample",
    )
    return ChunkSource(
        parse_job_id=11, document_id=7, source_sha256="a" * 64,
        parsed_document=parsed, title="Test report",
        document_type=DocumentType.ANNOUNCEMENT, company_code=None,
        security_symbol=None, report_year=None, report_period_end=None, source_url=None,
    )


def test_generated_text_and_table_cover_every_source_block() -> None:
    source = source_for(
        ParsedBlock(block_index=0, block_type="heading", content="摘要", heading_level=1),
        ParsedBlock(block_index=1, block_type="text", content="本年收入增长。" * 12),
        ParsedBlock(
            block_index=2, block_type="table", table_format="markdown",
            content="|项目|2024|\n|---|---|\n|收入|100|",
        ),
    )
    chunks = FinancialTextChunker(max_chars=40, overlap_chars=5).chunk(source)
    report = audit_chunks(source, chunks, max_chars=40)

    assert report.passed
    assert report.block_coverage_ratio == 1
    assert report.covered_page_count == 1
    assert report.kind_counts[ChunkKind.TABLE] == 1
    assert report.kind_counts[ChunkKind.TEXT] >= 2
    assert report.oversized_text_count == 0
    assert report.oversized_special_count == 0
    assert report.average_chars > 0


def test_missing_source_block_fails_quality_gate() -> None:
    source = source_for(
        ParsedBlock(block_index=0, block_type="text", content="第一段"),
        ParsedBlock(block_index=1, block_type="text", content="第二段"),
    )
    chunks = FinancialTextChunker().chunk(source)
    report = audit_chunks(source, chunks[:0])

    assert not report.passed
    assert report.source_block_count == 2
    assert report.covered_block_count == 0
    assert report.missing_source_blocks == (SourceBlockRef(page_number=1, block_index=0), SourceBlockRef(page_number=1, block_index=1))


def test_wrong_kind_or_missing_coordinate_is_reported() -> None:
    source = source_for(ParsedBlock(block_index=0, block_type="text", content="正文"))
    chunk = FinancialTextChunker().chunk(source)[0]
    wrong = chunk.model_copy(update={"kind": ChunkKind.FORMULA})
    report = audit_chunks(source, (wrong,))
    assert not report.passed
    assert "source block kind mismatch" in report.issues[0]
    assert report.covered_block_count == 0

    missing_ref = chunk.model_copy(update={"source_blocks": (SourceBlockRef(page_number=2, block_index=0),)})
    report = audit_chunks(source, (missing_ref,))
    assert not report.passed
    assert any("nonexistent source block" in issue for issue in report.issues)


def test_oversized_complex_table_is_diagnostic_not_failure() -> None:
    source = source_for(ParsedBlock(
        block_index=0, block_type="table", table_format="html",
        content="<table><tr><td rowspan='2'>项目</td><td>2024</td></tr>"
        "<tr><td>100</td></tr></table>",
    ))
    chunks = FinancialTextChunker(max_chars=32, overlap_chars=0).chunk(source)
    report = audit_chunks(source, chunks, max_chars=32)
    assert report.passed
    assert report.oversized_special_count == 1
    assert report.oversized_text_count == 0


def test_duplicate_content_is_counted_and_index_gap_fails() -> None:
    source = source_for(ParsedBlock(block_index=0, block_type="text", content="正文"))
    chunk = FinancialTextChunker().chunk(source)[0]
    second = chunk.model_copy(update={"chunk_index": 2})
    report = audit_chunks(source, (chunk, second))
    assert not report.passed
    assert report.duplicate_content_count == 1
    assert any("noncontiguous index" in issue for issue in report.issues)
