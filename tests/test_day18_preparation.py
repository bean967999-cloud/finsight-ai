"""Check public fixture normalization without network or production writes."""

import json

import pytest

from finsight.workers import prepare_day18 as preparation


def test_cached_public_prices_keep_source_and_decimal_precision(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "ROOT", tmp_path)
    lines = [f"2025-01-{day:02d},10.01,10.02,10.03,10.00,100,1000,0" for day in range(1, 31)]
    preparation.save(tmp_path / "Eastmoney600519.json", {"fetched_at": "2026-09-28T00:00:00+00:00", "response": {"data": {"code": "600519", "klines": lines}}})
    records = preparation.fetch("600519")
    assert len(records) == 30
    assert str(records[0].close_price) == "10.02"
    assert records[0].source_code == "eastmoney_public"
    assert records[0].adjustment_type == "none"


@pytest.mark.parametrize("code, lines", [("600036", []), ("600519", [])])
def test_missing_or_mismatched_public_data_is_not_imported(tmp_path, monkeypatch, code, lines):
    monkeypatch.setattr(preparation, "ROOT", tmp_path)
    preparation.save(tmp_path / "Eastmoney600519.json", {"fetched_at": "2026-09-28T00:00:00+00:00", "response": {"data": {"code": code, "klines": lines}}})
    with pytest.raises(ValueError):
        preparation.fetch("600519")


def test_manifest_write_can_be_read_back_without_temporary_file(tmp_path):
    target = tmp_path / "Preparation.json"
    preparation.save(target, {"document_id": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"document_id": 1}
    assert not target.with_suffix(".tmp").exists()
