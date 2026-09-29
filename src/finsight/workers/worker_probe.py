"""Healthcheck subprocess shares container hostname, not parent process PID."""

import os
import sys
from socket import gethostname

from finsight.services.worker_heartbeat import is_alive


def main():
    from redis import Redis

    if len(sys.argv) != 2 or sys.argv[1] not in {"worker", "dispatcher"}:
        return 2
    try:
        with Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2,
                            socket_connect_timeout=2) as client:
            return 0 if is_alive(client, gethostname(), sys.argv[1]) else 1
    except Exception:  # noqa: BLE001 - health does not log secret-bearing connection errors
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
