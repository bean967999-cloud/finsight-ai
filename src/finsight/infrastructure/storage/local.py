import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from finsight.services.object_storage import (
    InvalidObjectKeyError,
    ObjectNotFoundError,
    StoredObject,
)


class LocalObjectStorage:
    """Filesystem-backed object storage for development and tests."""

    def __init__(self, root_directory: str | Path) -> None:
        self._root = Path(root_directory).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, content: bytes) -> StoredObject:
        target = self._resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")

        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

        return StoredObject(key=key, size_bytes=len(content))

    def get(self, key: str) -> bytes:
        target = self._resolve_key(key)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(f"Object does not exist: {key}") from exc

    def exists(self, key: str) -> bool:
        return self._resolve_key(key).is_file()

    def delete(self, key: str) -> None:
        target = self._resolve_key(key)
        try:
            target.unlink()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(f"Object does not exist: {key}") from exc

    def _resolve_key(self, key: str) -> Path:
        if not key or "\\" in key:
            raise InvalidObjectKeyError("Object key must be a non-empty POSIX path")

        parsed = PurePosixPath(key)
        if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
            raise InvalidObjectKeyError("Object key must be a safe relative path")

        resolved = self._root.joinpath(*parsed.parts).resolve()
        if not resolved.is_relative_to(self._root):
            raise InvalidObjectKeyError("Object key escapes the storage root")
        return resolved
