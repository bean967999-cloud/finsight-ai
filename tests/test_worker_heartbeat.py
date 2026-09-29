import pytest

from finsight.services.worker_heartbeat import heartbeat_key, is_alive, pulse


def test_host_role_isolation_and_expiry_configuration():
    class Client:
        def __init__(self):
            self.records = {}
            self.ttl = {}

        def set(self, key, value, *, ex):
            self.records[key] = value
            self.ttl[key] = ex

        def get(self, key):
            return self.records.get(key)

    client = Client()
    assert not is_alive(client, "container-a", "worker")
    pulse(client, "container-a", "worker")
    assert is_alive(client, "container-a", "worker")
    assert not is_alive(client, "container-b", "worker")
    assert not is_alive(client, "container-a", "dispatcher")
    assert client.ttl[heartbeat_key("container-a", "worker")] == 900
    pulse(client, "container-a", "dispatcher")
    assert client.ttl[heartbeat_key("container-a", "dispatcher")] == 30
    del client.records[heartbeat_key("container-a", "worker")]
    assert not is_alive(client, "container-a", "worker")


def test_invalid_role():
    with pytest.raises(ValueError):
        heartbeat_key("container-a", "unknown")
