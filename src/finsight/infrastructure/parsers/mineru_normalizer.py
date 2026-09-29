"""Map MinerU 3.4 page content into the platform document contract."""

import json
import re
from typing import Any

from pydantic import ValidationError

from finsight.domain.parsed_document import (
    ParsedBlock,
    ParsedBlockType,
    ParsedDocument,
    ParsedPage,
    TableFormat,
)
from finsight.services.document_parser import DocumentParseResultError, ParserOutput

TEXT_TYPES = {"text", "header", "footer", "page_number", "aside_text", "page_footnote"}


def normalize_mineru_output(output: ParserOutput, *, document_id: int) -> ParsedDocument:
    """Normalize page text, headings, HTML tables, and image references."""
    try:
        content_list = json.loads(output.content_list_json)
        middle_json = json.loads(output.middle_json)
    except ValueError as exc:
        raise DocumentParseResultError("MinerU structured output is invalid JSON") from exc
    if not isinstance(content_list, list) or not isinstance(middle_json, dict):
        raise DocumentParseResultError("MinerU structured output has invalid top-level types")

    pdf_info = middle_json.get("pdf_info")
    if not isinstance(pdf_info, list) or not pdf_info:
        raise DocumentParseResultError("MinerU did not report PDF pages")
    for index, page in enumerate(pdf_info):
        if not isinstance(page, dict) or page.get("page_idx") != index:
            raise DocumentParseResultError("MinerU PDF pages are missing or out of order")

    page_blocks: list[list[ParsedBlock]] = [[] for _ in pdf_info]
    heading_stack: list[tuple[int, str]] = []
    previous_page_idx = 0
    for item in content_list:
        if not isinstance(item, dict):
            raise DocumentParseResultError("MinerU content item is not an object")
        page_idx = item.get("page_idx")
        if type(page_idx) is not int or not 0 <= page_idx < len(pdf_info):
            raise DocumentParseResultError("MinerU content has an invalid page index")
        if page_idx < previous_page_idx:
            raise DocumentParseResultError("MinerU content is out of page order")
        previous_page_idx = page_idx

        item_type = item.get("type")
        block_index = len(page_blocks[page_idx])
        if item_type in TEXT_TYPES:
            content = item.get("text")
            if not isinstance(content, str) or not content.strip():
                raise DocumentParseResultError("MinerU text content is empty")
            content = content.strip()
            level = _heading_level(item) if item_type == "text" else None
            if level is not None:
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, content))
            block_values: dict[str, Any] = {
                "block_type": ParsedBlockType.HEADING if level is not None else ParsedBlockType.TEXT,
                "content": content,
                "heading_level": level,
            }
        elif item_type == "table":
            body = item.get("table_body")
            if (
                not isinstance(body, str)
                or not re.search(r"<table\b", body, flags=re.IGNORECASE)
                or not re.search(r"</table\s*>", body, flags=re.IGNORECASE)
            ):
                raise DocumentParseResultError("MinerU table has no HTML body")
            block_values = {
                "block_type": ParsedBlockType.TABLE,
                "content": body.strip(),
                "table_format": TableFormat.HTML,
                "caption": _first_caption(item, "table_caption"),
                "footnotes": _notes(item, "table_footnote"),
            }
        elif item_type in {"image", "chart"}:
            image_path = item.get("img_path")
            if not isinstance(image_path, str) or not image_path.strip():
                raise DocumentParseResultError("MinerU image has no asset path")
            caption_key = "chart_caption" if item_type == "chart" else "image_caption"
            footnote_key = "chart_footnote" if item_type == "chart" else "image_footnote"
            image_content = item.get("content", "")
            if not isinstance(image_content, str):
                raise DocumentParseResultError("MinerU image content is not text")
            block_values = {
                "block_type": ParsedBlockType.IMAGE,
                "content": image_content.strip(),
                "asset_path": _asset_path(image_path),
                "caption": _first_caption(item, caption_key),
                "footnotes": _notes(item, footnote_key),
            }
        else:
            raise DocumentParseResultError(f"MinerU content type {item_type!r} is unsupported")
        try:
            page_blocks[page_idx].append(
                ParsedBlock(
                    block_index=block_index,
                    section_path=tuple(title for _, title in heading_stack),
                    **block_values,
                )
            )
        except ValidationError as exc:
            raise DocumentParseResultError("MinerU block violates document contract") from exc

    markdown = output.markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not markdown:
        raise DocumentParseResultError("MinerU Markdown is empty")
    pages = tuple(
        ParsedPage(page_number=index + 1, blocks=tuple(blocks))
        for index, blocks in enumerate(page_blocks)
    )
    try:
        return ParsedDocument(
            document_id=document_id,
            source_sha256=output.source_sha256,
            parser_name=output.parser_name,
            parser_version=output.parser_version,
            page_count=len(pages),
            pages=pages,
            markdown=markdown,
        )
    except ValueError as exc:
        raise DocumentParseResultError("MinerU output violates document contract") from exc


def _heading_level(item: dict[str, Any]) -> int | None:
    level = item.get("text_level")
    if level is None:
        return None
    if type(level) is not int or not 1 <= level <= 6:
        raise DocumentParseResultError("MinerU heading level must be between 1 and 6")
    return level


def _notes(item: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = item.get(key, [])
    if not isinstance(raw, list) or any(not isinstance(note, str) for note in raw):
        raise DocumentParseResultError(f"MinerU {key} must be a list of text")
    return tuple(note.strip() for note in raw if note.strip())


def _first_caption(item: dict[str, Any], key: str) -> str | None:
    captions = _notes(item, key)
    return "\n".join(captions) if captions else None


def _asset_path(raw_path: str) -> str:
    # MinerU 3.4 builds local references as "{bucket}/{filename}" even for an empty bucket.
    normalized = raw_path.removeprefix("/")
    if not normalized or raw_path.startswith("//"):
        raise DocumentParseResultError("MinerU image path is invalid")
    return normalized
