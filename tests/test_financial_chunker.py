from dataclasses import replace

import pytest

from finsight.domain.document_chunking import ChunkKind
from finsight.domain.document_data import DocumentType
from finsight.domain.parsed_document import ParsedBlock, ParsedDocument, ParsedPage
from finsight.services.document_chunk_source import ChunkSource
from finsight.services.financial_chunker import FinancialTextChunker


def source_for(*pages: ParsedPage) -> ChunkSource:
    parsed = ParsedDocument(
        document_id=7,
        source_sha256="a" * 64,
        parser_name="fixture",
        parser_version="1",
        page_count=len(pages),
        pages=pages,
        markdown="sample",
    )
    return ChunkSource(
        parse_job_id=11,
        document_id=7,
        source_sha256="a" * 64,
        parsed_document=parsed,
        title="Test report",
        document_type=DocumentType.ANNOUNCEMENT,
        company_code=None,
        security_symbol=None,
        report_year=None,
        report_period_end=None,
        source_url=None,
    )


def test_section_boundaries_prevent_unrelated_text_from_mixing() -> None:
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(
                ParsedBlock(block_index=0, block_type="heading", content="概览", heading_level=1),
                ParsedBlock(block_index=1, block_type="text", content="公司经营情况。"),
            ),
        ),
        ParsedPage(
            page_number=2,
            blocks=(
                ParsedBlock(block_index=0, block_type="heading", content="风险", heading_level=1),
                ParsedBlock(block_index=1, block_type="text", content="流动性风险情况。"),
            ),
        ),
    )

    chunks = FinancialTextChunker(max_chars=100, overlap_chars=10).chunk(source)

    assert len(chunks) == 2
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert chunks[0].section_path == ("概览",)
    assert chunks[1].section_path == ("风险",)
    assert "风险" not in chunks[0].content
    assert "概览" not in chunks[1].content
    assert chunks[0].page_start == chunks[0].page_end == 1
    assert chunks[1].page_start == chunks[1].page_end == 2
    assert [(ref.page_number, ref.block_index) for ref in chunks[0].source_blocks] == [
        (1, 0), (1, 1)
    ]


def test_overlap_preserves_long_text_without_crossing_section() -> None:
    content = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwx"
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(block_index=0, block_type="text", content=content),),
        )
    )

    chunks = FinancialTextChunker(max_chars=20, overlap_chars=5).chunk(source, chunk_version=2)

    assert len(chunks) == 3
    assert all(len(chunk.content) <= 20 for chunk in chunks)
    assert [chunk.chunk_version for chunk in chunks] == [2, 2, 2]
    assert chunks[0].content[-5:] == chunks[1].content[:5]
    assert chunks[1].content[-5:] == chunks[2].content[:5]
    reconstructed = chunks[0].content + "".join(chunk.content[5:] for chunk in chunks[1:])
    assert reconstructed == content
    assert all(chunk.source_blocks[0].block_index == 0 for chunk in chunks)


def test_same_section_can_span_pages_with_exact_source_references() -> None:
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(
                ParsedBlock(block_index=0, block_type="heading", content="经营分析", heading_level=1),
                ParsedBlock(block_index=1, block_type="text", content="第一部分。"),
            ),
        ),
        ParsedPage(
            page_number=2,
            blocks=(ParsedBlock(block_index=0, block_type="text", content="第二部分。"),),
        ),
    )
    chunks = FinancialTextChunker(max_chars=100, overlap_chars=0).chunk(source)

    assert len(chunks) == 1
    assert chunks[0].page_start == 1 and chunks[0].page_end == 2
    assert [(ref.page_number, ref.block_index) for ref in chunks[0].source_blocks] == [
        (1, 0), (1, 1), (2, 0)
    ]


def test_heading_levels_replace_previous_section_path() -> None:
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(
                ParsedBlock(block_index=0, block_type="heading", content="总览", heading_level=1),
                ParsedBlock(block_index=1, block_type="heading", content="收入", heading_level=2),
                ParsedBlock(block_index=2, block_type="text", content="收入正文。"),
                ParsedBlock(block_index=3, block_type="heading", content="利润", heading_level=2),
                ParsedBlock(block_index=4, block_type="text", content="利润正文。"),
            ),
        )
    )
    chunks = FinancialTextChunker(max_chars=100, overlap_chars=0).chunk(source)

    assert [chunk.section_path for chunk in chunks] == [
        ("总览",), ("总览", "收入"), ("总览", "利润")
    ]
    assert "收入正文" not in chunks[2].content


@pytest.mark.parametrize(
    "block_type, kind",
    [
        ("table", ChunkKind.TABLE),
        ("image", ChunkKind.IMAGE_REFERENCE),
        ("formula", ChunkKind.FORMULA),
    ],
)
def test_special_blocks_are_not_silently_dropped(block_type: str, kind: ChunkKind) -> None:
    values = {"block_index": 1, "block_type": block_type, "content": "内容"}
    if block_type == "table":
        values.update(content="<table><tr><td>金额</td></tr></table>", table_format="html")
    if block_type == "image":
        values["asset_path"] = "images/chart.png"
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(
                ParsedBlock(block_index=0, block_type="text", content="前文"),
                ParsedBlock(**values),
            ),
        )
    )
    chunks = FinancialTextChunker().chunk(source)
    assert [chunk.kind for chunk in chunks] == [ChunkKind.TEXT, kind]
    assert chunks[1].source_blocks[0].block_index == 1


def test_short_table_keeps_original_html_caption_and_footnote() -> None:
    html = "<table><tr><td>项目</td><td>2024</td></tr><tr><td>收入</td><td>120</td></tr></table>"
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(
                ParsedBlock(block_index=0, block_type="heading", content="财务数据", heading_level=1),
                ParsedBlock(
                    block_index=1,
                    block_type="table",
                    content=html,
                    table_format="html",
                    caption="主要指标",
                    footnotes=("单位：亿元",),
                ),
            ),
        )
    )

    chunks = FinancialTextChunker(max_chars=300).chunk(source)

    assert [chunk.kind for chunk in chunks] == [ChunkKind.TEXT, ChunkKind.TABLE]
    assert html in chunks[1].content
    assert chunks[1].table_format.value == "html"
    assert "表题：主要指标" in chunks[1].content
    assert "表注：单位：亿元" in chunks[1].content
    assert chunks[1].section_path == ("财务数据",)
    assert chunks[1].source_blocks[0].block_index == 1


def test_long_simple_html_table_splits_by_rows_and_repeats_header() -> None:
    header = "<tr><td>项目</td><td>2024</td><td>2023</td></tr>"
    data_rows = [
        f"<tr><td>指标{i}</td><td>{i}20</td><td>{i}10</td></tr>"
        for i in range(1, 5)
    ]
    html = f"<table>{header}{''.join(data_rows)}</table>"
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(
                block_index=0, block_type="table", content=html,
                table_format="html", caption="对比表", footnotes=("单位：亿元",),
            ),),
        )
    )

    chunks = FinancialTextChunker(max_chars=165, overlap_chars=0).chunk(source)

    assert len(chunks) > 1
    assert all(chunk.kind == ChunkKind.TABLE for chunk in chunks)
    assert all(header in chunk.content for chunk in chunks)
    assert all("表题：对比表" in chunk.content for chunk in chunks)
    assert all("表注：单位：亿元" in chunk.content for chunk in chunks)
    assert all(len(chunk.content) <= 165 for chunk in chunks)
    for row in data_rows:
        assert sum(row in chunk.content for chunk in chunks) == 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_multirow_html_thead_is_repeated_in_every_table_part() -> None:
    first_header = "<tr><th>财务指标</th><th>金额</th></tr>"
    second_header = "<tr><th>项目</th><th>2024</th></tr>"
    rows = [f"<tr><td>项目{i}</td><td>{i}00</td></tr>" for i in range(1, 6)]
    html = f"<table><thead>{first_header}{second_header}</thead><tbody>{''.join(rows)}</tbody></table>"
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(
                block_index=0, block_type="table", content=html, table_format="html"
            ),),
        )
    )
    chunks = FinancialTextChunker(max_chars=130, overlap_chars=0).chunk(source)
    assert len(chunks) > 1
    assert all(first_header in chunk.content and second_header in chunk.content for chunk in chunks)
    for row in rows:
        assert sum(row in chunk.content for chunk in chunks) == 1


def test_merged_cell_table_remains_atomic_even_when_over_limit() -> None:
    html = (
        "<table><tr><td rowspan=\"2\">项目</td><td>2024</td></tr>"
        "<tr><td>120</td></tr><tr><td>脚注说明</td><td>100</td></tr></table>"
    )
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(
                block_index=0, block_type="table", content=html, table_format="html"
            ),),
        )
    )
    chunks = FinancialTextChunker(max_chars=64, overlap_chars=0).chunk(source)

    assert len(chunks) == 1
    assert chunks[0].content == html
    assert len(chunks[0].content) > 64


def test_long_markdown_table_repeats_header_and_separator() -> None:
    header = "| 项目 | 2024 | 2023 |"
    divider = "| --- | ---: | ---: |"
    rows = [f"| 指标{i} | {i}20 | {i}10 |" for i in range(1, 7)]
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(
                block_index=0, block_type="table",
                content="\n".join([header, divider, *rows]), table_format="markdown",
            ),),
        )
    )
    chunks = FinancialTextChunker(max_chars=80, overlap_chars=0).chunk(source)

    assert len(chunks) > 1
    assert all(chunk.content.startswith(f"{header}\n{divider}") for chunk in chunks)
    for row in rows:
        assert sum(row in chunk.content for chunk in chunks) == 1


def test_image_reference_and_formula_keep_metadata_without_claiming_image_bytes() -> None:
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(
                ParsedBlock(
                    block_index=0, block_type="image", asset_path="images/chart.png",
                    content="增长趋势", caption="营业收入", footnotes=("单位：亿元",),
                ),
                ParsedBlock(block_index=1, block_type="formula", content="ROE = 净利润 / 净资产"),
            ),
        )
    )
    chunks = FinancialTextChunker().chunk(source)

    assert [chunk.kind for chunk in chunks] == [ChunkKind.IMAGE_REFERENCE, ChunkKind.FORMULA]
    assert "图片引用：images/chart.png" in chunks[0].content
    assert chunks[0].asset_path == "images/chart.png"
    assert "图注：营业收入" in chunks[0].content
    assert "图中文字：增长趋势" in chunks[0].content
    assert "图注释：单位：亿元" in chunks[0].content
    assert chunks[1].content == "公式：ROE = 净利润 / 净资产"


def test_chunking_is_deterministic() -> None:
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(block_index=0, block_type="text", content="正文" * 40),),
        )
    )
    chunker = FinancialTextChunker(max_chars=40, overlap_chars=6)
    assert chunker.chunk(source) == chunker.chunk(source)


@pytest.mark.parametrize(
    "max_chars, overlap_chars",
    [(15, 0), (20, -1), (20, 11)],
)
def test_invalid_window_configuration_is_rejected(max_chars: int, overlap_chars: int) -> None:
    with pytest.raises(ValueError):
        FinancialTextChunker(max_chars=max_chars, overlap_chars=overlap_chars)


def test_source_identity_and_version_are_checked() -> None:
    source = source_for(
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(block_index=0, block_type="text", content="正文"),),
        )
    )
    chunker = FinancialTextChunker()
    with pytest.raises(ValueError, match="chunk_version"):
        chunker.chunk(source, chunk_version=0)
    with pytest.raises(ValueError, match="document_id"):
        chunker.chunk(replace(source, document_id=8))
    with pytest.raises(ValueError, match="digest"):
        chunker.chunk(replace(source, source_sha256="b" * 64))
