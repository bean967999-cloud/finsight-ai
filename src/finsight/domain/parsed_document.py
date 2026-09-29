"""Parser-neutral contracts for a complete PDF parsing result."""

from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ParsedBlockType(StrEnum):
    HEADING = "heading"
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"


class TableFormat(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"


class ParsedBlock(BaseModel):
    """One ordered content unit, still attached to its source page."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    block_index: int = Field(ge=0)
    block_type: ParsedBlockType
    content: str = ""
    section_path: tuple[str, ...] = ()
    heading_level: int | None = Field(default=None, ge=1, le=6)
    table_format: TableFormat | None = None
    asset_path: str | None = None
    caption: str | None = None
    footnotes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_block_fields(self) -> "ParsedBlock":
        if any(not section for section in self.section_path):
            raise ValueError("section_path must not contain empty headings")
        if self.block_type == ParsedBlockType.IMAGE:
            if self.asset_path is None:
                raise ValueError("image block requires asset_path")
            path = PurePosixPath(self.asset_path)
            if (
                not self.asset_path
                or "\\" in self.asset_path
                or ":" in self.asset_path
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise ValueError("asset_path must be a safe relative path")
        elif self.asset_path is not None:
            raise ValueError("only image blocks may have asset_path")
        elif not self.content:
            raise ValueError("non-image block content must not be empty")

        if (self.block_type == ParsedBlockType.HEADING) != (self.heading_level is not None):
            raise ValueError("heading_level is required only for headings")
        if (self.block_type == ParsedBlockType.TABLE) != (self.table_format is not None):
            raise ValueError("table_format is required only for tables")
        if self.caption is not None and self.block_type not in {
            ParsedBlockType.TABLE, ParsedBlockType.IMAGE
        }:
            raise ValueError("caption is only valid for tables or images")
        if self.footnotes and self.block_type not in {
            ParsedBlockType.TABLE, ParsedBlockType.IMAGE
        }:
            raise ValueError("footnotes are only valid for tables or images")
        if self.caption is not None and not self.caption:
            raise ValueError("caption must not be empty")
        if any(not note for note in self.footnotes):
            raise ValueError("footnotes must not contain empty items")
        return self


class ParsedPage(BaseModel):
    """A one-based PDF page and its original reading order."""

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(gt=0)
    blocks: tuple[ParsedBlock, ...] = ()

    @model_validator(mode="after")
    def validate_block_order(self) -> "ParsedPage":
        if [block.block_index for block in self.blocks] != list(range(len(self.blocks))):
            raise ValueError("block_index must be contiguous and in reading order")
        return self


class ParsedDocument(BaseModel):
    """Full-document Markdown plus page-level structure for later citations."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    document_id: int = Field(gt=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_name: str = Field(min_length=1, max_length=100)
    parser_version: str = Field(min_length=1, max_length=50)
    page_count: int = Field(gt=0)
    pages: tuple[ParsedPage, ...] = Field(min_length=1)
    markdown: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_complete_page_coverage(self) -> "ParsedDocument":
        if [page.page_number for page in self.pages] != list(range(1, self.page_count + 1)):
            raise ValueError("pages must cover every PDF page in order")
        if not any(page.blocks for page in self.pages):
            raise ValueError("parsed document must contain at least one block")
        return self
