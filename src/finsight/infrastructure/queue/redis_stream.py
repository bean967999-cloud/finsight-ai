"""Project-namespaced Redis Stream with consumer-group acknowledgments."""

import re
from typing import cast

from redis import Redis
from redis.exceptions import ResponseError

from finsight.services.async_job_queue import QueueMessage

STREAM_NAME = "finsight:async_jobs:v1"
GROUP_NAME = "finsight:workers:v1"
_HASH = re.compile(r"^[0-9a-f]{64}$")


class QueueMessageError(ValueError):
    """A stream entry is malformed and must not execute a job."""


class RedisStreamQueue:
    def __init__(
        self,
        client: Redis,
        *,
        stream: str = STREAM_NAME,
        group: str = GROUP_NAME,
    ) -> None:
        self._client = client
        self._stream = stream
        self._group = group

    def ensure_group(self) -> None:
        try:
            self._client.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, job_id: int, request_sha256: str) -> str:
        if job_id < 1 or _HASH.fullmatch(request_sha256) is None:
            raise ValueError("queue message requires a job ID and request digest")
        message_id = self._client.xadd(
            self._stream,
            {"job_id": str(job_id), "request_sha256": request_sha256},
        )
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    def read_new(self, consumer: str, *, block_ms: int = 1000) -> QueueMessage | None:
        if not consumer.strip() or block_ms < 1:
            raise ValueError("consumer and positive block_ms are required")
        batches = cast(
            list[tuple[str | bytes, list[tuple[str | bytes, dict[str | bytes, str | bytes]]]]],
            self._client.xreadgroup(
                self._group,
                consumer,
                {self._stream: ">"},
                count=1,
                block=block_ms,
            ),
        )
        if not batches:
            return None
        _, messages = batches[0]
        return self._decode(messages[0])

    def reclaim_stale(self, consumer: str, *, min_idle_ms: int) -> QueueMessage | None:
        if not consumer.strip() or min_idle_ms < 1:
            raise ValueError("consumer and positive min_idle_ms are required")
        response = cast(
            tuple[str | bytes, list[tuple[str | bytes, dict[str | bytes, str | bytes]]], list],
            self._client.xautoclaim(
                self._stream, self._group, consumer, min_idle_ms, start_id="0-0", count=1
            ),
        )
        _, messages, _ = response
        return self._decode(messages[0]) if messages else None

    @staticmethod
    def _decode(raw: tuple) -> QueueMessage:
        message_id, raw_fields = raw
        fields = {
            key.decode() if isinstance(key, bytes) else key: value.decode()
            if isinstance(value, bytes)
            else value
            for key, value in raw_fields.items()
        }
        try:
            job_id = int(fields["job_id"])
            digest = fields["request_sha256"]
        except (KeyError, TypeError, ValueError) as exc:
            raise QueueMessageError("stream message lacks a valid job reference") from exc
        if job_id < 1 or _HASH.fullmatch(digest) is None:
            raise QueueMessageError("stream message has an invalid job reference")
        return QueueMessage(
            message_id=message_id.decode() if isinstance(message_id, bytes) else message_id,
            job_id=job_id,
            request_sha256=digest,
        )

    def acknowledge(self, message_id: str) -> None:
        self._client.xack(self._stream, self._group, message_id)
