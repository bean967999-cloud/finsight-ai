from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol


class EmptyDocumentError(ValueError):
    """An empty payload cannot be registered as a document."""


@dataclass(frozen=True, slots=True)
class DocumentFingerprint:
    content_sha256: str
    file_size_bytes: int
    object_key: str


@dataclass(frozen=True, slots=True)
class ExistingDocument:
    document_id: int
    content_sha256: str
    file_size_bytes: int
    object_key: str


@dataclass(frozen=True, slots=True)
class DuplicateCheckResult:
    fingerprint: DocumentFingerprint
    existing_document: ExistingDocument | None

    @property
    def is_duplicate(self) -> bool:
        return self.existing_document is not None


class DocumentLookup(Protocol):
    def get_by_content_sha256(self, digest: str) -> ExistingDocument | None: ...


def fingerprint_document(content: bytes) -> DocumentFingerprint:
    """Build a stable identity and storage key from the original file bytes."""
    if not content:
        raise EmptyDocumentError("Document content must not be empty")
    digest = sha256(content).hexdigest()
    return DocumentFingerprint(
        content_sha256=digest,
        file_size_bytes=len(content),
        object_key=f"documents/sha256/{digest[:2]}/{digest}.pdf",
    )


class DocumentDuplicateChecker:
    def __init__(self, lookup: DocumentLookup) -> None:
        self._lookup = lookup

    def check(self, content: bytes) -> DuplicateCheckResult:
        fingerprint = fingerprint_document(content)
        existing = self._lookup.get_by_content_sha256(fingerprint.content_sha256)
        return DuplicateCheckResult(fingerprint=fingerprint, existing_document=existing)
