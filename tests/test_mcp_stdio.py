"""The process entrypoint refuses missing identity and incomplete document setup."""

import pytest

from finsight.core.config import get_settings
from finsight.workers.mcp_stdio import UnconfiguredDocumentSearch, main, make_document_search


def test_missing_process_token_refuses_to_start(monkeypatch) -> None:
    monkeypatch.delenv("FINSIGHT_MCP_ACCESS_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="identity configuration unavailable"):
        main()


def test_document_service_is_explicitly_unavailable_without_local_models(monkeypatch) -> None:
    for name in ("FINSIGHT_BGE_M3_PATH", "FINSIGHT_RERANKER_PATH", "FINSIGHT_RERANKER_VERSION"):
        monkeypatch.delenv(name, raising=False)
    result = make_document_search(get_settings())
    assert isinstance(result, UnconfiguredDocumentSearch)
    with pytest.raises(ConnectionError, match="not configured"):
        result.search("年报")
    monkeypatch.setenv("FINSIGHT_BGE_M3_PATH", "somewhere")
    with pytest.raises(ValueError, match="incomplete"):
        make_document_search(get_settings())
