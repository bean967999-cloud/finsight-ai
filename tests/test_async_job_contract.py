from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from finsight.domain.async_job import (
    AsyncJobSnapshot,
    AsyncJobStatus,
    AsyncJobSubmission,
    ChunkIndexTask,
    DocumentParseTask,
    assert_job_transition,
)


def submission() -> AsyncJobSubmission:
    return AsyncJobSubmission(
        idempotency_key="parse-2024-report", task=DocumentParseTask(document_id=7)
    )


def snapshot(**updates: object) -> AsyncJobSnapshot:
    request = submission()
    fields = {
        "job_id": 12,
        "idempotency_key": request.idempotency_key,
        "request_sha256": request.request_sha256,
        "task": request.task,
    }
    fields.update(updates)
    if "request_sha256" not in updates:
        fields["request_sha256"] = AsyncJobSubmission(
            idempotency_key=request.idempotency_key,
            task=request.task,
            max_attempts=int(fields.get("max_attempts", 3)),
        ).request_sha256
    return AsyncJobSnapshot(**fields)


def test_same_task_has_stable_digest_and_changed_payload_has_different_digest() -> None:
    first = submission()
    replay = AsyncJobSubmission(
        idempotency_key=first.idempotency_key, task=DocumentParseTask(document_id=7)
    )
    other = AsyncJobSubmission(
        idempotency_key=first.idempotency_key, task=DocumentParseTask(document_id=8)
    )
    assert first.request_sha256 == replay.request_sha256
    assert first.request_sha256 != other.request_sha256
    more_retries = AsyncJobSubmission(
        idempotency_key=first.idempotency_key,
        task=first.task,
        max_attempts=4,
    )
    assert first.request_sha256 != more_retries.request_sha256
    assert len(first.request_sha256) == 64


def test_pilot_task_types_reject_unknown_or_invalid_payloads() -> None:
    assert ChunkIndexTask(parse_job_id=3, chunk_version=2).kind == "chunk_index"
    with pytest.raises(ValidationError, match="document_id"):
        DocumentParseTask(document_id=0)
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        AsyncJobSubmission.model_validate(
            {
                "idempotency_key": "unknown",
                "task": {"kind": "external_transfer", "amount": 100},
            }
        )
    with pytest.raises(ValidationError, match="idempotency_key"):
        AsyncJobSubmission(idempotency_key=" ", task=DocumentParseTask(document_id=7))


def test_valid_lifecycle_and_terminal_states() -> None:
    pending = snapshot()
    assert_job_transition(pending, AsyncJobStatus.QUEUED)
    queued = snapshot(status=AsyncJobStatus.QUEUED)
    assert_job_transition(queued, AsyncJobStatus.RUNNING)
    running = snapshot(status=AsyncJobStatus.RUNNING, attempt_count=1)
    assert_job_transition(running, AsyncJobStatus.SUCCEEDED)
    succeeded = snapshot(
        status=AsyncJobStatus.SUCCEEDED, attempt_count=1, result_ref="parse_job:18"
    )
    with pytest.raises(ValueError, match="invalid job transition"):
        assert_job_transition(succeeded, AsyncJobStatus.QUEUED)
    failed = snapshot(status=AsyncJobStatus.FAILED, attempt_count=1, error_code="INVALID_DOCUMENT")
    with pytest.raises(ValueError, match="invalid job transition"):
        assert_job_transition(failed, AsyncJobStatus.RUNNING)


def test_retry_requires_budget_and_timezone_aware_schedule() -> None:
    started = snapshot(status=AsyncJobStatus.RUNNING, attempt_count=1, max_attempts=2)
    assert_job_transition(started, AsyncJobStatus.RETRY_WAIT)
    retry_wait = snapshot(
        status=AsyncJobStatus.RETRY_WAIT,
        attempt_count=1,
        max_attempts=2,
        next_retry_at=datetime(2026, 1, 1, tzinfo=UTC),
        error_code="SERVICE_UNAVAILABLE",
    )
    assert_job_transition(retry_wait, AsyncJobStatus.QUEUED)
    exhausted = snapshot(status=AsyncJobStatus.RUNNING, attempt_count=2, max_attempts=2)
    with pytest.raises(ValueError, match="retry limit"):
        assert_job_transition(exhausted, AsyncJobStatus.RETRY_WAIT)
    with pytest.raises(ValidationError, match="timezone"):
        snapshot(
            status=AsyncJobStatus.RETRY_WAIT,
            attempt_count=1,
            next_retry_at=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            error_code="SERVICE_UNAVAILABLE",
        )
    with pytest.raises(ValidationError, match="failure code"):
        snapshot(
            status=AsyncJobStatus.RETRY_WAIT,
            attempt_count=1,
            next_retry_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_snapshot_rejects_inconsistent_payload_and_result_state() -> None:
    with pytest.raises(ValidationError, match="digest"):
        snapshot(request_sha256="0" * 64)
    with pytest.raises(ValidationError, match="result_ref"):
        snapshot(status=AsyncJobStatus.SUCCEEDED, attempt_count=1)
    with pytest.raises(ValidationError, match="attempt"):
        snapshot(status=AsyncJobStatus.RUNNING)
    with pytest.raises(ValidationError, match="error_code"):
        snapshot(status=AsyncJobStatus.FAILED, attempt_count=1)
