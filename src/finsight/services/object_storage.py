from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ObjectStorageError(Exception):
    """Base exception raised by object storage adapters."""


class InvalidObjectKeyError(ObjectStorageError):
    """Raised when an object key is unsafe or malformed."""


class ObjectNotFoundError(ObjectStorageError):
    """Raised when a requested object does not exist."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int


@runtime_checkable
class ObjectStorage(Protocol):
    """Storage-neutral contract for original document bytes."""

    def put(self, key: str, content: bytes) -> StoredObject: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...
