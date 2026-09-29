import json
from dataclasses import replace

import pytest

from finsight.domain.parsed_document import ParsedBlockType, TableFormat
from finsight.infrastructure.parsers.mineru_normalizer import normalize_mineru_output
from finsight.services.document_parser import DocumentParseResultError, ParserOutput


def output_for(
    content: list[dict[str, object]],
    *,
    page_count: int = 2,
    markdown: str = "# 年报\r\n\r\n正文",
) -> ParserOutput:
    return ParserOutput(
        source_sha256="a" * 64,
        task_id="12345678-1234-5678-1234-567812345678",
        parser_name="mineru",
        parser_version="3.4.5",
        backend="pipeline",
        markdown=markdown,
        content_list_json=json.dumps(content, ensure_ascii=False),
        middle_json=json.dumps(
            {"pdf_info": [{"page_idx": i} for i in range(page_count)]}
        ),
    )


def test_normalizes_headings_pages_and_markdown() -> None:
    output = output_for(
        [
            {"type": "text", "text": "年度报告", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "概览", "text_level": 2, "page_idx": 0},
            {"type": "text", "text": "公司概况", "page_idx": 0},
            {"type": "text", "text": "财务数据", "text_level": 2, "page_idx": 1},
            {"type": "text", "text": "营业收入", "page_idx": 1},
        ]
    )
    parsed = normalize_mineru_output(output, document_id=7)

    assert parsed.document_id == 7
    assert parsed.page_count == 2
    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert [block.block_index for block in parsed.pages[0].blocks] == [0, 1, 2]
    assert parsed.pages[0].blocks[1].heading_level == 2
    assert parsed.pages[0].blocks[2].section_path == ("年度报告", "概览")
    assert parsed.pages[1].blocks[0].section_path == ("年度报告", "财务数据")
    assert parsed.pages[1].blocks[1].section_path == ("年度报告", "财务数据")
    assert parsed.markdown == "# 年报\n\n正文"


def test_keeps_blank_pages_and_heading_context_across_pages() -> None:
    output = output_for(
        [
            {"type": "text", "text": "总览", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "第三页正文", "page_idx": 2},
        ],
        page_count=3,
    )
    parsed = normalize_mineru_output(output, document_id=1)

    assert parsed.pages[1].blocks == ()
    assert parsed.pages[2].blocks[0].section_path == ("总览",)


def test_lower_level_heading_replaces_previous_section() -> None:
    output = output_for(
        [
            {"type": "text", "text": "一", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "一.一", "text_level": 2, "page_idx": 0},
            {"type": "text", "text": "二", "text_level": 1, "page_idx": 1},
        ]
    )
    parsed = normalize_mineru_output(output, document_id=1)
    assert parsed.pages[1].blocks[0].section_path == ("二",)


def test_page_header_and_footer_remain_text_with_page_trace() -> None:
    output = output_for(
        [
            {"type": "header", "text": "2025 年年度报告", "page_idx": 0},
            {"type": "text", "text": "正文", "page_idx": 0},
            {"type": "page_number", "text": "1", "page_idx": 0},
        ]
    )
    parsed = normalize_mineru_output(output, document_id=1)
    assert [block.content for block in parsed.pages[0].blocks] == ["2025 年年度报告", "正文", "1"]
    assert all(block.heading_level is None for block in parsed.pages[0].blocks)


def test_table_retains_html_caption_footnote_page_and_section() -> None:
    table_html = "<table><tr><td>收入</td><td>120</td></tr></table>"
    output = output_for(
        [
            {"type": "text", "text": "财务数据", "text_level": 1, "page_idx": 0},
            {
                "type": "table", "table_body": table_html, "page_idx": 1,
                "table_caption": ["表 1：主要财务指标"],
                "table_footnote": ["单位：亿元"],
            },
        ]
    )
    parsed = normalize_mineru_output(output, document_id=8)
    table = parsed.pages[1].blocks[0]
    assert table.block_type == ParsedBlockType.TABLE
    assert table.table_format == TableFormat.HTML
    assert table.content == table_html
    assert table.caption == "表 1：主要财务指标"
    assert table.footnotes == ("单位：亿元",)
    assert table.section_path == ("财务数据",)
    assert parsed.pages[1].page_number == 2


def test_image_and_chart_keep_safe_references_and_captions() -> None:
    output = output_for(
        [
            {"type": "image", "img_path": "/images/chart-1.png", "page_idx": 0,
             "image_caption": ["收入趋势"], "image_footnote": ["仅为演示"]},
            {"type": "chart", "img_path": "images/chart-2.png", "page_idx": 1,
             "chart_caption": ["利润趋势"]},
        ]
    )
    parsed = normalize_mineru_output(output, document_id=8)
    image = parsed.pages[0].blocks[0]
    chart = parsed.pages[1].blocks[0]
    assert image.block_type == ParsedBlockType.IMAGE
    assert image.asset_path == "images/chart-1.png"
    assert image.caption == "收入趋势"
    assert image.footnotes == ("仅为演示",)
    assert chart.asset_path == "images/chart-2.png"
    assert chart.caption == "利润趋势"


@pytest.mark.parametrize(
    "content, message",
    [
        ([{"type": "text", "text": "正文", "page_idx": 2}], "invalid page index"),
        ([{"type": "text", "text": "正文", "page_idx": True}], "invalid page index"),
        ([{"type": "text", "text": "正文", "page_idx": 0, "text_level": 7}], "heading level"),
        ([{"type": "text", "text": "", "page_idx": 0}], "text content is empty"),
        ([{"type": "table", "table_body": "", "page_idx": 0}], "no HTML body"),
        ([{"type": "table", "table_body": "plain text", "page_idx": 0}], "no HTML body"),
        ([{"type": "image", "img_path": "", "page_idx": 0}], "no asset path"),
        ([{"type": "image", "img_path": "../outside.png", "page_idx": 0}], "violates document contract"),
        ([{"type": "image", "img_path": "C:/outside.png", "page_idx": 0}], "violates document contract"),
        ([{"type": "image", "img_path": "//outside.png", "page_idx": 0}], "image path is invalid"),
        ([{"type": "equation", "text": "E=mc^2", "page_idx": 0}], "unsupported"),
        (
            [
                {"type": "text", "text": "后", "page_idx": 1},
                {"type": "text", "text": "前", "page_idx": 0},
            ],
            "out of page order",
        ),
    ],
)
def test_rejects_bad_or_not_yet_supported_content(content, message) -> None:
    with pytest.raises(DocumentParseResultError, match=message):
        normalize_mineru_output(output_for(content), document_id=1)


def test_rejects_missing_middle_pages() -> None:
    output = output_for([{"type": "text", "text": "正文", "page_idx": 0}])
    output = replace(output, middle_json='{"pdf_info":[{"page_idx":0},{"page_idx":2}]}')
    with pytest.raises(DocumentParseResultError, match="out of order"):
        normalize_mineru_output(output, document_id=1)


def test_rejects_no_content_in_all_pages() -> None:
    with pytest.raises(DocumentParseResultError, match="violates document contract"):
        normalize_mineru_output(output_for([]), document_id=1)
