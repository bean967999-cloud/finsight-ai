from hashlib import sha256
from uuid import UUID

import httpx
import pytest

from finsight.infrastructure.parsers.mineru import MinerUDocumentParser
from finsight.services.document_parser import (
    DocumentParser,
    DocumentParseResultError,
    DocumentParseServiceError,
    DocumentParseTimeout,
)

TASK_ID = str(UUID("12345678-1234-5678-1234-567812345678"))
PDF = b"%PDF-1.7\nsynthetic request bytes"


def parser_with_handler(handler, **kwargs) -> MinerUDocumentParser:
    transport = httpx.MockTransport(handler)
    return MinerUDocumentParser(
        "http://mineru.test",
        client_factory=lambda: httpx.Client(
            base_url="http://mineru.test", transport=transport
        ),
        poll_interval_seconds=0.01,
        sleeper=lambda _seconds: None,
        **kwargs,
    )


def completed_payload(**file_changes):
    file_result = {
        "md_content": "# 演示年报\n\n正文",
        "content_list": '[{"type":"title","page_idx":0}]',
        "middle_json": '{"pdf_info":[]}',
    }
    file_result.update(file_changes)
    return {
        "backend": "pipeline",
        "version": "3.4.5",
        "results": {"uploaded_name": file_result},
    }


def test_adapter_submits_pdf_polls_and_returns_raw_outputs() -> None:
    paths: list[str] = []
    status_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_reads
        paths.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            body = request.content
            assert request.url.path == "/tasks"
            assert f'{sha256(PDF).hexdigest()}.pdf'.encode() in body
            assert b'name="return_md"' in body
            assert b'name="return_content_list"' in body
            assert b'name="return_middle_json"' in body
            assert b'pipeline' in body
            return httpx.Response(202, json={"task_id": TASK_ID})
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json=completed_payload())
        status_reads += 1
        return httpx.Response(
            200, json={"status": "pending" if status_reads == 1 else "completed"}
        )

    parser = parser_with_handler(handler)
    assert isinstance(parser, DocumentParser)
    result = parser.parse_pdf(PDF)

    assert result.source_sha256 == sha256(PDF).hexdigest()
    assert result.task_id == TASK_ID
    assert result.parser_name == "mineru"
    assert result.parser_version == "3.4.5"
    assert result.markdown.startswith("# 演示年报")
    assert "page_idx" in result.content_list_json
    assert paths == [
        "POST /tasks", f"GET /tasks/{TASK_ID}", f"GET /tasks/{TASK_ID}",
        f"GET /tasks/{TASK_ID}/result",
    ]


def test_invalid_pdf_is_rejected_before_network_request() -> None:
    parser = parser_with_handler(lambda _request: pytest.fail("network must not be called"))
    with pytest.raises(ValueError, match="PDF header"):
        parser.parse_pdf(b"not a PDF")


def test_failed_remote_task_is_translated_to_service_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": TASK_ID})
        return httpx.Response(200, json={"status": "failed", "error": "private details"})

    with pytest.raises(DocumentParseServiceError, match="task failed") as error:
        parser_with_handler(handler).parse_pdf(PDF)
    assert "private details" not in str(error.value)


def test_http_timeout_is_translated() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private endpoint details")

    with pytest.raises(DocumentParseTimeout, match="HTTP request timed out") as error:
        parser_with_handler(handler).parse_pdf(PDF)
    assert "private endpoint details" not in str(error.value)


def test_wait_deadline_is_enforced() -> None:
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": TASK_ID})
        return httpx.Response(200, json={"status": "processing"})

    transport = httpx.MockTransport(handler)
    parser = MinerUDocumentParser(
        "http://mineru.test",
        max_wait_seconds=1,
        poll_interval_seconds=0.1,
        client_factory=lambda: httpx.Client(base_url="http://mineru.test", transport=transport),
        clock=lambda: now[0],
        sleeper=lambda _seconds: now.__setitem__(0, 2.0),
    )
    with pytest.raises(DocumentParseTimeout, match=TASK_ID):
        parser.parse_pdf(PDF)


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"task_id": "not-a-uuid"}, "invalid task ID"),
        ({"unexpected": "value"}, "did not return a task ID"),
    ],
)
def test_submit_response_requires_valid_task_id(payload, message) -> None:
    parser = parser_with_handler(lambda _request: httpx.Response(202, json=payload))
    with pytest.raises(DocumentParseResultError, match=message):
        parser.parse_pdf(PDF)


@pytest.mark.parametrize(
    "file_changes, message",
    [
        ({"md_content": None}, "missing required content"),
        ({"content_list": "not JSON"}, "invalid structured JSON"),
        ({"middle_json": "[]"}, "invalid structured JSON"),
    ],
)
def test_incomplete_or_malformed_result_is_rejected(file_changes, message) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": TASK_ID})
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json=completed_payload(**file_changes))
        return httpx.Response(200, json={"status": "completed"})

    with pytest.raises(DocumentParseResultError, match=message):
        parser_with_handler(handler).parse_pdf(PDF)


def test_server_error_is_sanitized() -> None:
    parser = parser_with_handler(
        lambda _request: httpx.Response(503, text="private server path /secret")
    )
    with pytest.raises(DocumentParseServiceError, match="HTTP 503") as error:
        parser.parse_pdf(PDF)
    assert "/secret" not in str(error.value)
