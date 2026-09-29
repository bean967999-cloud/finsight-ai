"""Traceable, parser-neutral contracts for future document chunks."""

from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.parsed_document import TableFormat


class ChunkKind(StrEnum):
    TEXT = "text"
    TABLE = "table"
    IMAGE_REFERENCE = "image_reference"
    FORMULA = "formula"


class SourceBlockRef(BaseModel):
    """One source block in a one-based PDF page."""

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(gt=0)
    block_index: int = Field(ge=0)


class ChunkDraft(BaseModel):
    """A generated chunk before object storage and database persistence."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    document_id: int = Field(gt=0)
    parse_job_id: int = Field(gt=0)
    chunk_index: int = Field(ge=0)
    chunk_version: int = Field(default=1, gt=0)
    kind: ChunkKind
    content: str = Field(min_length=1)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    section_path: tuple[str, ...] = ()
    source_blocks: tuple[SourceBlockRef, ...] = Field(min_length=1)
    table_format: TableFormat | None = None
    asset_path: str | None = None

    @model_validator(mode="after")
    def validate_trace(self) -> "ChunkDraft":
        if any(not title.strip() for title in self.section_path):
            raise ValueError("section_path must not contain empty titles")
        coordinates = [(ref.page_number, ref.block_index) for ref in self.source_blocks]
        if coordinates != sorted(set(coordinates)):
            raise ValueError("source_blocks must be unique and in reading order")
        if self.page_start != coordinates[0][0] or self.page_end != coordinates[-1][0]:
            raise ValueError("page range must match source_blocks")
        if (self.kind == ChunkKind.TABLE) != (self.table_format is not None):
            raise ValueError("table_format is required only for table chunks")
        if (self.kind == ChunkKind.IMAGE_REFERENCE) != (self.asset_path is not None):
            raise ValueError("asset_path is required only for image-reference chunks")
        if self.asset_path is not None:
            path = PurePosixPath(self.asset_path)
            if (
                not self.asset_path
                or "\\" in self.asset_path
                or ":" in self.asset_path
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise ValueError("asset_path must be a safe relative path")
        return self

    @property
    def content_sha256(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()
