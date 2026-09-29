from pathlib import Path

import pytest

from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.services.object_storage import (
    InvalidObjectKeyError,
    ObjectNotFoundError,
    ObjectStorage,
)


def test_local_storage_implements_contract_and_round_trips_bytes(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path / "objects")
    content = b"%PDF-1.7\nfinancial report"

    stored = storage.put("reports/CMB/2025/annual.pdf", content)

    assert isinstance(storage, ObjectStorage)
    assert stored.key == "reports/CMB/2025/annual.pdf"
    assert stored.size_bytes == len(content)
    assert storage.exists(stored.key)
    assert storage.get(stored.key) == content


def test_put_replaces_an_object_without_leaving_temporary_files(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    key = "reports/example.pdf"

    storage.put(key, b"old")
    storage.put(key, b"new content")

    assert storage.get(key) == b"new content"
    assert list((tmp_path / "reports").glob("*.tmp")) == []


def test_delete_removes_an_existing_object(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    storage.put("reports/example.pdf", b"content")

    storage.delete("reports/example.pdf")

    assert not storage.exists("reports/example.pdf")


@pytest.mark.parametrize(
    "key",
    ["", "../secret.pdf", "reports/../../secret.pdf", "/absolute.pdf", "reports\\bad.pdf"],
)
def test_storage_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    storage = LocalObjectStorage(tmp_path)

    with pytest.raises(InvalidObjectKeyError):
        storage.put(key, b"content")


def test_get_and_delete_report_missing_objects(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)

    with pytest.raises(ObjectNotFoundError, match="missing.pdf"):
        storage.get("reports/missing.pdf")
    with pytest.raises(ObjectNotFoundError, match="missing.pdf"):
        storage.delete("reports/missing.pdf")
