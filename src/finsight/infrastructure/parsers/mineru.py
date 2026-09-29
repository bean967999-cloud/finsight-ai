"""MinerU 3.4 asynchronous task adapter for original PDF bytes."""

import json
from collections.abc import Callable
from time import monotonic, sleep
from typing import Any
from uuid import UUID

import httpx

from finsight.services.document_deduplication import fingerprint_document
from finsight.services.document_parser import (
    DocumentParseResultError,
    DocumentParseServiceError,
    DocumentParseTimeout,
    ParserOutput,
)


class MinerUDocumentParser:
    def __init__(
        self,
        base_url: str,
        *,
        backend: str = "pipeline",
        max_wait_seconds: float = 600,
        request_timeout_seconds: float = 60,
        poll_interval_seconds: float = 2,
        client_factory: Callable[[], httpx.Client] | None = None,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if backend not in {"pipeline", "hybrid-engine", "vlm-engine"}:
            raise ValueError("unsupported MinerU backend")
        if min(max_wait_seconds, request_timeout_seconds, poll_interval_seconds) <= 0:
            raise ValueError("timeouts and poll interval must be positive")
        self._backend = backend
        self._max_wait_seconds = max_wait_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._clock = clock
        self._sleep = sleeper
        self._client_factory = client_factory or (
            lambda: httpx.Client(base_url=base_url, timeout=request_timeout_seconds)
        )

    def parse_pdf(self, content: bytes) -> ParserOutput:
        if not content.startswith(b"%PDF-"):
            raise ValueError("content must start with a PDF header")
        fingerprint = fingerprint_document(content)
        filename = f"{fingerprint.content_sha256}.pdf"
        deadline = self._clock() + self._max_wait_seconds

        with self._client_factory() as client:
            submitted = self._request_json(
                client,
                "POST",
                "/tasks",
                files={"files": (filename, content, "application/pdf")},
                data={
                    "backend": self._backend,
                    "parse_method": "auto",
                    "return_md": "true",
                    "return_content_list": "true",
                    "return_middle_json": "true",
                    "return_images": "false",
                    "response_format_zip": "false",
                },
                expected_status=202,
            )
            task_id = submitted.get("task_id")
            if not isinstance(task_id, str):
                raise DocumentParseResultError("MinerU did not return a task ID")
            try:
                task_id = str(UUID(task_id))
            except ValueError as exc:
                raise DocumentParseResultError("MinerU returned an invalid task ID") from exc

            while True:
                if self._clock() >= deadline:
                    raise DocumentParseTimeout(f"MinerU task timed out: {task_id}")
                status = self._request_json(
                    client, "GET", f"/tasks/{task_id}", expected_status=200
                ).get("status")
                if status == "completed":
                    result = self._request_json(
                        client, "GET", f"/tasks/{task_id}/result", expected_status=200
                    )
                    return self._parse_output(result, fingerprint.content_sha256, task_id)
                if status == "failed":
                    raise DocumentParseServiceError(f"MinerU task failed: {task_id}")
                if status not in {"pending", "processing"}:
                    raise DocumentParseResultError("MinerU returned an unknown task status")
                self._sleep(min(self._poll_interval_seconds, max(0.0, deadline - self._clock())))

    @staticmethod
    def _request_json(
        client: httpx.Client,
        method: str,
        path: str,
        *,
        expected_status: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise DocumentParseTimeout("MinerU HTTP request timed out") from exc
        except httpx.RequestError as exc:
            raise DocumentParseServiceError("MinerU service is unavailable") from exc
        if response.status_code != expected_status:
            raise DocumentParseServiceError(
                f"MinerU returned HTTP {response.status_code} for {method} {path.split('?')[0]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DocumentParseResultError("MinerU returned non-JSON data") from exc
        if not isinstance(payload, dict):
            raise DocumentParseResultError("MinerU returned a non-object response")
        return payload

    @staticmethod
    def _parse_output(payload: dict[str, Any], digest: str, task_id: str) -> ParserOutput:
        results = payload.get("results")
        if not isinstance(results, dict) or len(results) != 1:
            raise DocumentParseResultError("MinerU must return exactly one file result")
        file_result = next(iter(results.values()))
        if not isinstance(file_result, dict):
            raise DocumentParseResultError("MinerU file result must be an object")
        markdown = file_result.get("md_content")
        content_list = file_result.get("content_list")
        middle_json = file_result.get("middle_json")
        version = payload.get("version")
        backend = payload.get("backend")
        if (
            not isinstance(markdown, str) or not markdown.strip()
            or not isinstance(content_list, str) or not content_list.strip()
            or not isinstance(middle_json, str) or not middle_json.strip()
            or not isinstance(version, str) or not version.strip()
            or not isinstance(backend, str) or not backend.strip()
        ):
            raise DocumentParseResultError("MinerU result is missing required content")
        try:
            parsed_content_list = json.loads(content_list)
            parsed_middle_json = json.loads(middle_json)
        except ValueError as exc:
            raise DocumentParseResultError("MinerU returned invalid structured JSON") from exc
        if not isinstance(parsed_content_list, list) or not isinstance(parsed_middle_json, dict):
            raise DocumentParseResultError("MinerU returned invalid structured JSON types")
        return ParserOutput(
            source_sha256=digest,
            task_id=task_id,
            parser_name="mineru",
            parser_version=version,
            backend=backend,
            markdown=markdown,
            content_list_json=content_list,
            middle_json=middle_json,
        )
