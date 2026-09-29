"""Global daily attempt reservation with a fixed key and atomic Redis script."""

from datetime import datetime, timedelta, timezone

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

_RESERVE = """
local value = tonumber(redis.call('GET', KEYS[1]) or '0')
if not value or value < 0 then return -1 end
if value >= tonumber(ARGV[1]) then return 0 end
local result = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 604800)
return result
"""


class RedisDailyGenerationBudget:
    """Every provider attempt consumes quota, including failures and retries.

    Redis durability depends on deployment AOF/backup handling. Restoring an old
    snapshot can rewind counts; this is not a provider-side currency hard cap.
    """

    def __init__(self, client, *, now=None):
        self._client = client
        self._now = now or (lambda: datetime.now(timezone(timedelta(hours=8))))

    def reserve(self, limit: int) -> bool:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("invalid_generation_budget_limit")
        day = self._now().astimezone(timezone(timedelta(hours=8))).date().isoformat()
        result = self._client.eval(_RESERVE, 1, f"finsight:generation:attempts:{day}", limit)
        if type(result) is not int or not 0 <= result <= limit:
            raise RuntimeError("generation_budget_invalid")
        return result > 0


def create_generation_budget(redis_url: str) -> RedisDailyGenerationBudget:
    # Bound synchronous reservations too; asyncio cancellation cannot stop a worker thread.
    client = Redis.from_url(
        redis_url, socket_connect_timeout=1, socket_timeout=1,
        retry=Retry(NoBackoff(), 0),
    )
    return RedisDailyGenerationBudget(client)
