from pathlib import Path

import pytest
from pydantic import ValidationError

from finsight.domain.parsed_document import (
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
)

FIXTURE = Path(__file__).parent / "Fixtures" / "Parsing" / "AnnualReportResult.json"


def test_annual_report_fixture_keeps_pages_headings_and_table() -> None:
    parsed = ParsedDocument.model_validate_json(FIXTURE.read_text(encoding="utf-8"))

    assert parsed.page_count == 2
    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert parsed.pages[0].blocks[0].heading_level == 1
    assert parsed.pages[1].blocks[0].heading_level == 2
    assert parsed.pages[1].blocks[1].table_format.value == "markdown"
    assert parsed.pages[1].blocks[1].section_path[-1] == "主要财务数据"
    assert "营业收入（演示） | 120 | 100" in parsed.markdown
    assert parsed.pages[1].blocks[2].asset_path == "images/chart-1.png"


@pytest.mark.parametrize(
    "change, message",
    [
        ({"page_count": 3}, "pages must cover every PDF page"),
        ({"source_sha256": "wrong"}, "source_sha256"),
        ({"markdown": ""}, "markdown"),
        ({"pages": []}, "pages"),
    ],
)
def test_document_rejects_incomplete_or_untraceable_result(change, message) -> None:
    parsed = ParsedDocument.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    values = parsed.model_dump()
    values.update(change)

    with pytest.raises(ValidationError, match=message):
        ParsedDocument.model_validate(values)


def test_page_requires_block_reading_order() -> None:
    with pytest.raises(ValidationError, match="block_index must be contiguous"):
        ParsedPage(
            page_number=1,
            blocks=(ParsedBlock(block_index=1, block_type="text", content="正文"),),
        )


@pytest.mark.parametrize(
    "values, message",
    [
        ({"block_type": "heading", "content": "标题"}, "heading_level"),
        ({"block_type": "table", "content": "| A |"}, "table_format"),
        ({"block_type": "text", "content": ""}, "content"),
        ({"block_type": "image", "asset_path": "../outside.png"}, "asset_path"),
        ({"block_type": "image", "asset_path": "C:/outside.png"}, "asset_path"),
        ({"block_type": "text", "content": "正文", "section_path": ("",)}, "section_path"),
    ],
)
def test_block_rejects_missing_structure_or_unsafe_asset(values, message) -> None:
    with pytest.raises(ValidationError, match=message):
        ParsedBlock(block_index=0, **values)


def test_blank_page_is_allowed_if_document_has_content_elsewhere() -> None:
    parsed = ParsedDocument(
        document_id=1,
        source_sha256="a" * 64,
        parser_name="fixture",
        parser_version="1",
        page_count=2,
        pages=(
            ParsedPage(page_number=1, blocks=()),
            ParsedPage(
                page_number=2,
                blocks=(ParsedBlock(block_index=0, block_type="text", content="正文"),),
            ),
        ),
        markdown="正文",
    )
    assert parsed.pages[0].blocks == ()


def test_parsed_result_is_immutable() -> None:
    parsed = ParsedDocument.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        parsed.markdown = "changed"


def test_table_and_image_metadata_are_type_specific() -> None:
    table = ParsedBlock(
        block_index=0,
        block_type="table",
        content="<table><tr><td>120</td></tr></table>",
        table_format="html",
        caption="营业收入",
        footnotes=("单位：亿元",),
    )
    assert table.caption == "营业收入"
    assert table.footnotes == ("单位：亿元",)

    with pytest.raises(ValidationError, match="caption is only valid"):
        ParsedBlock(block_index=0, block_type="text", content="正文", caption="不适用")
    with pytest.raises(ValidationError, match="footnotes are only valid"):
        ParsedBlock(block_index=0, block_type="text", content="正文", footnotes=("不适用",))
