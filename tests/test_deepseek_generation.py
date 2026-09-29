import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from test_generation_contract import request

from finsight.core.generation_config import GenerationSettings, load_generation_settings
from finsight.infrastructure.providers.deepseek_generation import DeepSeekGenerationClient
from finsight.services.generation_budget import RedisDailyGenerationBudget


class Budget:
    def __init__(self, allowed=True):
        self.calls = 0
        self.allowed = allowed

    def reserve(self, limit):
        assert limit == 20
        self.calls += 1
        return self.allowed


def settings(**values):
    return GenerationSettings(enabled=True, api_key="fake-test-secret", **values)


def response(content=None, **changes):
    data = {
        "choices": [{"finish_reason": "stop", "message": {"content": content or json.dumps({
            "status": "answered", "quotes": [{"citation_id": "C1", "quoted_text": "HK$6.50"}],
        })}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30},
    }
    data.update(changes)
    return httpx.Response(200, json=data)


def run(handler, *, config=None, budget=None):
    return asyncio.run(DeepSeekGenerationClient(
        config or settings(), budget or Budget(), transport=httpx.MockTransport(handler),
    ).generate(request()))


def test_success_uses_fixed_origin_minimal_json_and_safe_usage():
    def handler(req):
        assert str(req.url) == "https://api.deepseek.com/chat/completions"
        assert req.headers["Authorization"] == "Bearer fake-test-secret"
        payload = json.loads(req.content)
        assert payload["max_tokens"] == 512 and payload["model"] == "deepseek-flash"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert not payload["stream"] and len(payload["messages"]) == 2
        assert "fake-test-secret" not in req.content.decode()
        return response()

    result = run(handler)
    assert result.answer and result.error_code is None
    assert result.attempts == 1 and result.completion_tokens == 30
    assert "fake-test-secret" not in repr(result)


@pytest.mark.parametrize("config,code", [
    (GenerationSettings(), "generation_disabled"),
    (GenerationSettings(enabled=True), "generation_key_missing"),
    (GenerationSettings(enabled=True, api_key="fake\nsecret"), "generation_key_invalid"),
])
def test_disabled_or_missing_key_never_reserves_or_sends(config, code):
    budget = Budget()
    result = run(lambda req: pytest.fail("must not send"), config=config, budget=budget)
    assert result.error_code == code and result.attempts == budget.calls == 0


def test_quota_exhaustion_and_redis_failure_never_send():
    result = run(lambda req: pytest.fail("must not send"), budget=Budget(False))
    assert result.error_code == "generation_budget_exhausted" and result.attempts == 0

    class BrokenBudget:
        def reserve(self, limit):
            raise RuntimeError("redis://private-secret@private-host")

    result = run(lambda req: pytest.fail("must not send"), budget=BrokenBudget())
    assert result.error_code == "generation_budget_unavailable"
    assert "private-secret" not in repr(result)


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 301, 302, 307])
def test_auth_payment_bad_request_and_redirect_do_not_retry(status):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(status, headers={"Location": "https://unapproved.example"},
                              text="fake-test-secret private error body")

    result = run(handler)
    assert len(calls) == result.attempts == 1
    assert result.answer is None and "private" not in repr(result)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_status_retry_is_bounded_and_counted(status):
    budget = Budget()
    result = run(lambda req: httpx.Response(status), budget=budget)
    assert result.error_code == "generation_transient_failure"
    assert result.attempts == budget.calls == 2


def test_temporary_failure_can_recover_within_limit():
    count = 0

    def handler(req):
        nonlocal count
        count += 1
        return httpx.Response(503) if count == 1 else response()

    result = run(handler)
    assert result.answer and result.attempts == 2


def test_retry_must_reserve_again_and_can_be_blocked():
    class LastAttemptBudget(Budget):
        def reserve(self, limit):
            self.calls += 1
            return self.calls == 1

    result = run(lambda req: httpx.Response(503), budget=LastAttemptBudget())
    assert result.error_code == "generation_budget_exhausted" and result.attempts == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_network_errors_retry_without_error_text(error):
    def handler(req):
        raise error("fake-test-secret private network details")

    result = run(handler)
    assert result.error_code == "generation_transient_failure" and result.attempts == 2
    assert "fake-test-secret" not in repr(result)


def test_overall_deadline_cancels_slow_response():
    async def handler(req):
        await asyncio.sleep(2)
        return response()

    result = run(handler, config=settings(request_timeout_seconds=1, total_timeout_seconds=1))
    assert result.error_code == "generation_deadline_exceeded" and result.attempts == 1
    assert result.duration_ms < 1600


@pytest.mark.parametrize("content", [
    "not JSON", '{"status":"answered"}',
    '{"status":"answered","status":"refused"}',
    json.dumps({"status": "answered", "quotes": [{"citation_id": "C2", "quoted_text": "HK$6.50"}]}),
    json.dumps({"status": "answered", "quotes": [{"citation_id": "C1", "quoted_text": "HK$9.99"}]}),
])
def test_invalid_outputs_do_not_retry_or_release_raw_content(content):
    budget = Budget()
    result = run(lambda req: response(content), budget=budget)
    assert result.error_code == "generation_invalid_output"
    assert result.attempts == budget.calls == 1 and result.answer is None


def test_truncated_output_is_not_accepted_even_if_json_is_valid():
    result = run(lambda req: response(choices=[{
        "finish_reason": "length", "message": {"content": "{}"},
    }]))
    assert result.error_code == "generation_incomplete_output" and result.attempts == 1


@pytest.mark.parametrize("usage", [
    {"completion_tokens": 513}, {"prompt_tokens": -1}, {"completion_tokens": True},
    {"prompt_tokens": "100"},
])
def test_invalid_or_over_limit_usage_is_rejected(usage):
    result = run(lambda req: response(usage=usage))
    assert result.error_code == "generation_invalid_output"


def test_response_size_cap():
    result = run(lambda req: httpx.Response(200, content=b"x" * 65_537))
    assert result.error_code == "generation_response_too_large"


def test_refusal_is_distinct_from_transport_failure():
    result = run(lambda req: response(json.dumps({
        "status": "refused", "refusal_reason": "insufficient_evidence",
    })))
    assert result.answer.status == "refused" and result.error_code is None


def test_key_excluded_from_repr_and_serialization():
    config = settings()
    assert "fake-test-secret" not in repr(config)
    assert "api_key" not in config.model_dump()


def test_bad_secret_file_never_leaks_validation_input(tmp_path):
    path = tmp_path / "DeepSeek.env"
    path.write_text("FINSIGHT_GENERATION_MAX_ATTEMPTS=fake-private-value", encoding="utf-8")
    with pytest.raises(ValueError, match="generation_configuration_invalid") as error:
        load_generation_settings(path)
    assert "fake-private-value" not in str(error.value)


def test_secret_config_can_be_loaded_without_enabling(tmp_path):
    path = tmp_path / "DeepSeek.env"
    path.write_text("FINSIGHT_GENERATION_API_KEY=fake-local-test-key\n"
                    "FINSIGHT_GENERATION_ENABLED=false\n", encoding="utf-8")
    config = load_generation_settings(path)
    assert not config.enabled and config.api_key.get_secret_value() == "fake-local-test-key"


def test_client_rechecks_sensitive_input_before_sending():
    from hashlib import sha256

    values = request().model_dump()
    values.update(query="password=fake", query_sha256=sha256(b"password=fake").hexdigest())
    from finsight.domain.generation import PublicGenerationRequest

    budget = Budget()
    result = asyncio.run(DeepSeekGenerationClient(
        settings(), budget, transport=httpx.MockTransport(lambda req: pytest.fail("must not send")),
    ).generate(PublicGenerationRequest(**values)))
    assert result.error_code == "generation_input_invalid" and budget.calls == 0


@pytest.mark.parametrize("result", [-1, "1", None, 21])
def test_budget_invalid_counter_fails_closed(result):
    class RedisStub:
        def eval(self, *args):
            return result

    with pytest.raises(RuntimeError, match="generation_budget_invalid"):
        RedisDailyGenerationBudget(RedisStub()).reserve(20)


def test_budget_uses_fixed_shared_key_with_shanghai_day():
    class RedisStub:
        def eval(self, script, number, key, limit):
            assert "INCR" in script and "EXPIRE" in script and number == 1
            assert key == "finsight:generation:attempts:2026-09-30"
            assert limit == 20
            return 1

    clock = lambda: datetime(2026, 9, 29, 17, tzinfo=UTC)
    assert RedisDailyGenerationBudget(RedisStub(), now=clock).reserve(20)
