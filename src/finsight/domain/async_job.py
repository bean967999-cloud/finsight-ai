"""Durable-task contract, separate from domain-specific processing attempts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AsyncJobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentParseTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["document_parse"] = "document_parse"
    schema_version: Literal[1] = 1
    document_id: int = Field(gt=0)


class ChunkIndexTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["chunk_index"] = "chunk_index"
    schema_version: Literal[1] = 1
    parse_job_id: int = Field(gt=0)
    chunk_version: int = Field(default=1, gt=0)


TaskPayload = Annotated[DocumentParseTask | ChunkIndexTask, Field(discriminator="kind")]


class AsyncJobSubmission(BaseModel):
    """One logical request; the same key may replay only the same payload."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=1, max_length=128)
    knowledge_base_id: UUID | None = None
    task: TaskPayload
    max_attempts: int = Field(default=3, ge=1, le=10)

    @property
    def request_sha256(self) -> str:
        source = {"task": self.task.model_dump(mode="json"), "max_attempts": self.max_attempts}
        if self.knowledge_base_id is not None:
            source["knowledge_base_id"] = str(self.knowledge_base_id)
        payload = json.dumps(
            source,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()


class AsyncJobSnapshot(BaseModel):
    """Read model for one orchestration job, not a document parse/import record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    knowledge_base_id: UUID | None = None
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task: TaskPayload
    status: AsyncJobStatus = AsyncJobStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    result_ref: str | None = Field(default=None, min_length=1, max_length=200)
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    next_retry_at: datetime | None = None

    @model_validator(mode="after")
    def validate_state(self) -> AsyncJobSnapshot:
        if (
            self.request_sha256
            != AsyncJobSubmission(
                idempotency_key=self.idempotency_key,
                knowledge_base_id=self.knowledge_base_id,
                task=self.task,
                max_attempts=self.max_attempts,
            ).request_sha256
        ):
            raise ValueError("request digest does not match task payload")
        if self.attempt_count > self.max_attempts:
            raise ValueError("attempt_count must not exceed max_attempts")
        if (
            self.status
            in {
                AsyncJobStatus.RUNNING,
                AsyncJobStatus.RETRY_WAIT,
                AsyncJobStatus.SUCCEEDED,
                AsyncJobStatus.FAILED,
            }
            and self.attempt_count == 0
        ):
            raise ValueError("started or finished job requires an attempt")
        if self.status == AsyncJobStatus.PENDING and self.attempt_count != 0:
            raise ValueError("pending job must not have attempts")
        if self.status == AsyncJobStatus.RETRY_WAIT:
            if self.next_retry_at is None or self.attempt_count >= self.max_attempts:
                raise ValueError("retry_wait requires another attempt and a retry time")
            if self.error_code is None:
                raise ValueError("retry_wait requires the previous failure code")
        elif self.next_retry_at is not None:
            raise ValueError("next_retry_at is only valid in retry_wait")
        if self.next_retry_at is not None and self.next_retry_at.tzinfo is None:
            raise ValueError("next_retry_at must include timezone")
        if (self.status == AsyncJobStatus.SUCCEEDED) != (self.result_ref is not None):
            raise ValueError("result_ref is required only for succeeded jobs")
        if self.status == AsyncJobStatus.FAILED and self.error_code is None:
            raise ValueError("failed job requires error_code")
        if (
            self.status
            in {
                AsyncJobStatus.PENDING,
                AsyncJobStatus.QUEUED,
                AsyncJobStatus.RUNNING,
                AsyncJobStatus.SUCCEEDED,
            }
            and self.error_code
        ):
            raise ValueError("error_code is invalid for this job status")
        return self


_TRANSITIONS: dict[AsyncJobStatus, frozenset[AsyncJobStatus]] = {
    AsyncJobStatus.PENDING: frozenset({AsyncJobStatus.QUEUED}),
    AsyncJobStatus.QUEUED: frozenset({AsyncJobStatus.RUNNING}),
    AsyncJobStatus.RUNNING: frozenset(
        {
            AsyncJobStatus.RETRY_WAIT,
            AsyncJobStatus.SUCCEEDED,
            AsyncJobStatus.FAILED,
        }
    ),
    AsyncJobStatus.RETRY_WAIT: frozenset({AsyncJobStatus.QUEUED}),
    AsyncJobStatus.SUCCEEDED: frozenset(),
    AsyncJobStatus.FAILED: frozenset(),
}


def assert_job_transition(job: AsyncJobSnapshot, target: AsyncJobStatus) -> None:
    """Reject impossible state changes before any future database write."""
    if target not in _TRANSITIONS[job.status]:
        raise ValueError(f"invalid job transition: {job.status} -> {target}")
    if target == AsyncJobStatus.RETRY_WAIT and job.attempt_count >= job.max_attempts:
        raise ValueError("retry limit reached; job must fail")
