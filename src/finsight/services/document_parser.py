"""Parser-neutral output contract before page and section normalization."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class DocumentParseError(RuntimeError):
    """Base error exposed by document parser adapters."""


class DocumentParseTimeout(DocumentParseError):
    """A parse operation exceeded its wait or HTTP timeout."""


class DocumentParseServiceError(DocumentParseError):
    """The parser service is unavailable or rejected the task."""


class DocumentParseResultError(DocumentParseError):
    """The parser returned an incomplete or malformed result."""


@dataclass(frozen=True, slots=True)
class ParserOutput:
    source_sha256: str
    task_id: str
    parser_name: str
    parser_version: str
    backend: str
    markdown: str
    content_list_json: str
    middle_json: str


@runtime_checkable
class DocumentParser(Protocol):
    def parse_pdf(self, content: bytes) -> ParserOutput: ...
