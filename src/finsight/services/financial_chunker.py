"""Deterministic financial document chunking with source-block provenance."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from finsight.domain.document_chunking import ChunkDraft, ChunkKind, SourceBlockRef
from finsight.domain.parsed_document import ParsedBlock, ParsedBlockType, TableFormat
from finsight.services.document_chunk_source import ChunkSource


class UnsupportedChunkBlockError(ValueError):
    """A parsed block needs a dedicated chunk strategy before it can be indexed."""


@dataclass(frozen=True, slots=True)
class _TextUnit:
    content: str
    reference: SourceBlockRef


class FinancialTextChunker:
    def __init__(self, *, max_chars: int = 800, overlap_chars: int = 100) -> None:
        if max_chars < 16:
            raise ValueError("max_chars must be at least 16")
        if overlap_chars < 0 or overlap_chars > max_chars // 2:
            raise ValueError("overlap_chars must be between 0 and half of max_chars")
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    def chunk(self, source: ChunkSource, *, chunk_version: int = 1) -> tuple[ChunkDraft, ...]:
        """Preserve section boundaries and keep special blocks independent."""
        if chunk_version <= 0:
            raise ValueError("chunk_version must be positive")
        if source.document_id != source.parsed_document.document_id:
            raise ValueError("chunk source document_id does not match parsed document")
        if source.source_sha256 != source.parsed_document.source_sha256:
            raise ValueError("chunk source digest does not match parsed document")

        chunks: list[ChunkDraft] = []
        section_path: tuple[str, ...] | None = None
        heading_stack: list[tuple[int, str]] = []
        units: list[_TextUnit] = []

        def flush() -> None:
            if units:
                chunks.extend(
                    self._chunk_section(
                        source,
                        section_path or (),
                        units,
                        start_index=len(chunks),
                        chunk_version=chunk_version,
                    )
                )
                units.clear()

        for page in source.parsed_document.pages:
            for block in page.blocks:
                if block.block_type == ParsedBlockType.HEADING:
                    assert block.heading_level is not None
                    while heading_stack and heading_stack[-1][0] >= block.heading_level:
                        heading_stack.pop()
                    heading_stack.append((block.heading_level, block.content))
                current_path = block.section_path or tuple(title for _, title in heading_stack)
                if section_path is not None and current_path != section_path:
                    flush()
                section_path = current_path
                reference = SourceBlockRef(
                    page_number=page.page_number,
                    block_index=block.block_index,
                )
                if block.block_type in {ParsedBlockType.HEADING, ParsedBlockType.TEXT}:
                    units.append(_TextUnit(content=block.content, reference=reference))
                    continue
                flush()
                if block.block_type == ParsedBlockType.TABLE:
                    contents = self._table_contents(block)
                    kind = ChunkKind.TABLE
                elif block.block_type == ParsedBlockType.IMAGE:
                    contents = [self._image_content(block)]
                    kind = ChunkKind.IMAGE_REFERENCE
                elif block.block_type == ParsedBlockType.FORMULA:
                    contents = [f"公式：{block.content}"]
                    kind = ChunkKind.FORMULA
                else:
                    raise UnsupportedChunkBlockError(
                        f"block type {block.block_type.value} has no chunk strategy"
                    )
                for content in contents:
                    chunks.append(
                        ChunkDraft(
                            document_id=source.document_id,
                            parse_job_id=source.parse_job_id,
                            chunk_index=len(chunks),
                            chunk_version=chunk_version,
                            kind=kind,
                            content=content,
                            page_start=page.page_number,
                            page_end=page.page_number,
                            section_path=current_path,
                            source_blocks=(reference,),
                            table_format=block.table_format if kind == ChunkKind.TABLE else None,
                            asset_path=block.asset_path if kind == ChunkKind.IMAGE_REFERENCE else None,
                        )
                    )
        flush()
        return tuple(chunks)

    def _table_contents(self, block: ParsedBlock) -> list[str]:
        full = self._with_table_context(block, block.content)
        if len(full) <= self._max_chars:
            return [full]
        if block.table_format == TableFormat.HTML:
            rows = self._html_rows(block.content)
            if rows is None:
                return [full]
            opening, headers, data_rows = rows
            render = lambda items: self._with_table_context(
                block, f"{opening}{''.join(items)}</table>"
            )
            return self._split_table_rows(headers, data_rows, render)
        if block.table_format == TableFormat.MARKDOWN:
            lines = [line for line in block.content.splitlines() if line.strip()]
            if len(lines) < 3 or not re.fullmatch(r"[\s|:\-]+", lines[1]):
                return [full]
            render = lambda items: self._with_table_context(block, "\n".join(items))
            return self._split_table_rows(lines[:2], lines[2:], render)
        raise UnsupportedChunkBlockError("table format has no chunk strategy")

    def _split_table_rows(
        self,
        header: list[str],
        rows: list[str],
        render: Callable[[list[str]], str],
    ) -> list[str]:
        if not rows:
            return [render(header)]
        pieces: list[str] = []
        current: list[str] = []
        for row in rows:
            if current and len(render([*header, *current, row])) > self._max_chars:
                pieces.append(render([*header, *current]))
                current = []
            current.append(row)
        if current:
            pieces.append(render([*header, *current]))
        return pieces

    @staticmethod
    def _html_rows(body: str) -> tuple[str, list[str], list[str]] | None:
        if re.search(r"\b(?:rowspan|colspan)\s*=", body, flags=re.IGNORECASE):
            return None
        if len(re.findall(r"<table\b", body, flags=re.IGNORECASE)) != 1:
            return None
        opening = re.match(r"\s*(<table\b[^>]*>)", body, flags=re.IGNORECASE)
        if opening is None or not re.search(r"</table\s*>\s*$", body, flags=re.IGNORECASE):
            return None
        rows = re.findall(r"<tr\b[^>]*>.*?</tr\s*>", body, flags=re.IGNORECASE | re.DOTALL)
        if len(rows) < 2:
            return None
        remainder = re.sub(
            r"<tr\b[^>]*>.*?</tr\s*>", "", body, flags=re.IGNORECASE | re.DOTALL
        )
        remainder = re.sub(
            r"</?(?:table|thead|tbody|tfoot)\b[^>]*>", "", remainder, flags=re.IGNORECASE
        )
        if remainder.strip():
            return None
        table_head = re.search(
            r"<thead\b[^>]*>(.*?)</thead\s*>", body, flags=re.IGNORECASE | re.DOTALL
        )
        header_count = 1
        if table_head is not None:
            header_count = len(re.findall(r"<tr\b", table_head.group(1), flags=re.IGNORECASE))
        if not 1 <= header_count < len(rows):
            return None
        return opening.group(1), rows[:header_count], rows[header_count:]

    @staticmethod
    def _with_table_context(block: ParsedBlock, table: str) -> str:
        parts = []
        if block.caption:
            parts.append(f"表题：{block.caption}")
        parts.append(table)
        parts.extend(f"表注：{note}" for note in block.footnotes)
        return "\n".join(parts)

    @staticmethod
    def _image_content(block: ParsedBlock) -> str:
        parts = [f"图片引用：{block.asset_path}"]
        if block.caption:
            parts.append(f"图注：{block.caption}")
        if block.content:
            parts.append(f"图中文字：{block.content}")
        parts.extend(f"图注释：{note}" for note in block.footnotes)
        return "\n".join(parts)

    def _chunk_section(
        self,
        source: ChunkSource,
        section_path: tuple[str, ...],
        units: list[_TextUnit],
        *,
        start_index: int,
        chunk_version: int,
    ) -> list[ChunkDraft]:
        parts: list[str] = []
        spans: list[tuple[int, int, SourceBlockRef]] = []
        cursor = 0
        for unit in units:
            if parts:
                parts.append("\n\n")
                cursor += 2
            start = cursor
            parts.append(unit.content)
            cursor += len(unit.content)
            spans.append((start, cursor, unit.reference))
        text = "".join(parts)

        chunks: list[ChunkDraft] = []
        window_start = 0
        while window_start < len(text):
            window_end = self._window_end(text, window_start)
            content = text[window_start:window_end].strip()
            references = tuple(
                reference
                for start, end, reference in spans
                if end > window_start and start < window_end
            )
            if content and references:
                chunks.append(
                    ChunkDraft(
                        document_id=source.document_id,
                        parse_job_id=source.parse_job_id,
                        chunk_index=start_index + len(chunks),
                        chunk_version=chunk_version,
                        kind=ChunkKind.TEXT,
                        content=content,
                        page_start=references[0].page_number,
                        page_end=references[-1].page_number,
                        section_path=section_path,
                        source_blocks=references,
                    )
                )
            if window_end == len(text):
                break
            window_start = window_end - self._overlap_chars
        return chunks

    def _window_end(self, text: str, start: int) -> int:
        hard_end = min(start + self._max_chars, len(text))
        if hard_end == len(text):
            return hard_end
        lower_bound = start + self._max_chars * 2 // 3
        boundaries = "\n。！？；.!?; "
        for index in range(hard_end - 1, lower_bound - 1, -1):
            if text[index] in boundaries:
                return index + 1
        return hard_end
