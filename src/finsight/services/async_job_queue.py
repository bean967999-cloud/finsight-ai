"""Minimal queue boundary: messages identify jobs, not trusted task payloads."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class QueueMessage:
    message_id: str
    job_id: int
    request_sha256: str


class AsyncJobQueue(Protocol):
    def publish(self, job_id: int, request_sha256: str) -> str: ...

    def read_new(self, consumer: str, *, block_ms: int = 1000) -> QueueMessage | None: ...

    def reclaim_stale(self, consumer: str, *, min_idle_ms: int) -> QueueMessage | None: ...

    def acknowledge(self, message_id: str) -> None: ...
