"""Opt-in Redis Stream test using a uniquely named temporary stream."""

import os
from time import sleep
from uuid import uuid4

import pytest
from redis import Redis

from finsight.core.config import get_settings
from finsight.infrastructure.queue.redis_stream import RedisStreamQueue

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_REDIS_INTEGRATION") != "1",
    reason="Set FINSIGHT_REDIS_INTEGRATION=1 to test the project Redis container",
)


def test_publish_consume_and_ack_in_project_redis() -> None:
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    stream = f"finsight:test:async_jobs:{uuid4().hex}"
    group = f"finsight:test:workers:{uuid4().hex}"
    try:
        queue = RedisStreamQueue(client, stream=stream, group=group)
        queue.ensure_group()
        queue.ensure_group()
        message_id = queue.publish(42, "a" * 64)
        message = queue.read_new("integration-worker", block_ms=100)
        assert message is not None
        assert message.message_id == message_id
        assert message.job_id == 42
        assert message.request_sha256 == "a" * 64
        assert client.xpending(stream, group)["pending"] == 1
        queue.acknowledge(message.message_id)
        assert client.xpending(stream, group)["pending"] == 0
    finally:
        client.delete(stream)
        client.close()


def test_reclaim_unacknowledged_message_in_project_redis() -> None:
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    stream = f"finsight:test:async_jobs:{uuid4().hex}"
    group = f"finsight:test:workers:{uuid4().hex}"
    try:
        queue = RedisStreamQueue(client, stream=stream, group=group)
        queue.ensure_group()
        message_id = queue.publish(42, "a" * 64)
        assert queue.read_new("lost-worker", block_ms=100) is not None
        assert queue.reclaim_stale("replacement", min_idle_ms=60_000) is None
        sleep(0.01)
        reclaimed = queue.reclaim_stale("replacement", min_idle_ms=1)
        assert reclaimed is not None and reclaimed.message_id == message_id
        queue.acknowledge(reclaimed.message_id)
        assert client.xpending(stream, group)["pending"] == 0
    finally:
        client.delete(stream)
        client.close()
