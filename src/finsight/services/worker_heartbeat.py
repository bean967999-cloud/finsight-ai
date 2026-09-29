"""Iteration heartbeat, not proof of job success or instantaneous process liveness."""


def heartbeat_key(hostname, role):
    if role not in {"worker", "dispatcher", "both"}:
        raise ValueError("unsupported worker role")
    return f"finsight:deployment:heartbeat:{hostname}:{role}"


def pulse(client, hostname, role):
    client.set(heartbeat_key(hostname, role), "alive", ex=900 if role != "dispatcher" else 30)


def is_alive(client, hostname, role):
    return client.get(heartbeat_key(hostname, role)) in {"alive", b"alive"}
