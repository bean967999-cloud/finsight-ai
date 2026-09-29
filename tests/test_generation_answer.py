from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from test_grounded_document_answer import candidate

from finsight.agents.checkpoints import _ALLOWED_CHECKPOINT_TYPES
from finsight.agents.graph import build_research_graph
from finsight.agents.tools import ResearchToolAdapter
from finsight.core.generation_config import GenerationSettings
from finsight.domain.generation import GeneratedEvidenceAnswer, GeneratedQuote, GenerationStatus
from finsight.domain.grounded_document_answer import GroundedDocumentAnswer
from finsight.infrastructure.providers.deepseek_generation import GenerationOutcome
from finsight.services.generation_answer import (
    EvidenceGenerationAnswerService,
    PublicGenerationRegistry,
    authorized_generation_scope,
)
from finsight.services.grounded_document_answer import GroundedDocumentAnswerService

QUERY = "根据公告，恒生银行2024年每股全年股息是多少？"
QUOTE = "Total dividend distribution for 2024 was HK$6.80 per share, an improvement of 1% year-on-year."
HASH = "626f5a5e948772a92977f958c446e01f63d03a2a82cb7140a79bf1ac17c45130"


def setup_service(*, enabled=True, key="test-only", file_hash=HASH, anchored=True):
    citation = candidate(QUOTE)
    search = SimpleNamespace(search=lambda *args, **kwargs: SimpleNamespace(
        bundle=SimpleNamespace(citations=(citation,)),
    ))
    local = GroundedDocumentAnswerService(search, None, None)
    local._anchored = lambda item: anchored

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args):
            return SimpleNamespace(content_sha256=file_hash)

    class Client:
        def __init__(self):
            self.requests = []
            self.outcome = GenerationOutcome(answer=GeneratedEvidenceAnswer(
                status=GenerationStatus.ANSWERED,
                quotes=(GeneratedQuote(citation_id="C1", quoted_text=QUOTE),),
            ), attempts=1)

        async def generate(self, request):
            self.requests.append(request)
            return self.outcome

    client = Client()
    registry = PublicGenerationRegistry.load(Path("Evaluation/PublicGenerationPolicyV1.json"))
    settings = GenerationSettings(enabled=enabled, api_key=key)
    return EvidenceGenerationAnswerService(local, client, settings, registry, Session), client


def test_verified_public_answer_calls_model_and_preserves_complete_claim():
    service, client = setup_service()
    kb = uuid4()
    with authorized_generation_scope(kb):
        answer = service.answer(QUERY, kb)
    assert answer.generation.mode == "generated"
    assert answer.generation.attempts == 1
    assert answer.citations[0].quoted_text == QUOTE
    assert len(client.requests) == 1
    exported = client.requests[0].model_dump_json()
    assert str(kb) not in exported
    assert "document_id" not in exported and "test-only" not in exported
    assert "source_url" not in exported and "object_key" not in exported


@pytest.mark.parametrize("query", [
    "根据公告，恒生银行2022年每股全年股息是多少？",
    "根据公告，招商银行2024年每股全年股息是多少？",
    "根据公告，恒生银行2024年第四次中期股息是多少？",
    "根据公告，恒生银行2024年股息率是多少？",
    "根据公告，恒生银行2024年和2023年每股全年股息是多少？",
])
def test_wrong_year_company_metric_or_ambiguous_question_never_calls_model(query):
    service, client = setup_service()
    kb = uuid4()
    with authorized_generation_scope(kb):
        assert service.answer(query, kb) is None
    assert client.requests == []


def test_unanchored_source_never_calls_model():
    service, client = setup_service(anchored=False)
    kb = uuid4()
    with authorized_generation_scope(kb):
        assert service.answer(QUERY, kb) is None
    assert client.requests == []


@pytest.mark.parametrize("option,reason", [
    ({"enabled": False}, "disabled"),
    ({"key": ""}, "key_missing"),
    ({"file_hash": "a" * 64}, "public_source_not_approved"),
])
def test_local_or_fallback_does_not_export(option, reason):
    service, client = setup_service(**option)
    kb = uuid4()
    with authorized_generation_scope(kb):
        answer = service.answer(QUERY, kb)
    assert answer.generation.reason == reason
    assert answer.generation.attempts == 0
    assert client.requests == []


def test_missing_wrong_and_reset_scopes_cannot_export():
    service, client = setup_service()
    kb = uuid4()
    assert service.answer(QUERY, kb).generation.reason == "scope_not_authorized"
    with authorized_generation_scope(uuid4()):
        assert service.answer(QUERY, kb).generation.reason == "scope_not_authorized"
    with authorized_generation_scope(kb), authorized_generation_scope(None):
        assert service.answer(QUERY, kb).generation.reason == "scope_not_authorized"
    assert service.answer(QUERY, kb).generation.reason == "scope_not_authorized"
    assert not client.requests


def test_scope_propagates_only_when_copied_to_tool_thread():
    service, client = setup_service()
    kb = uuid4()
    with authorized_generation_scope(kb), ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(service.answer, QUERY, kb).result().generation.mode == "local"
        context = copy_context()
        assert pool.submit(context.run, service.answer, QUERY, kb).result().generation.mode == "generated"
    assert len(client.requests) == 1


def test_private_question_suffix_never_exported_even_with_public_evidence():
    service, client = setup_service()
    kb = uuid4()
    with authorized_generation_scope(kb):
        answer = service.answer(QUERY + "我的内部仓位很高", kb)
    assert answer.generation.reason == "public_query_not_approved"
    assert not client.requests


@pytest.mark.parametrize("code", [
    "generation_auth_failed", "generation_budget_exhausted", "generation_budget_unavailable",
    "generation_deadline_exceeded", "generation_invalid_output", "generation_transient_failure",
])
def test_provider_failure_returns_same_verified_local_answer(code):
    service, client = setup_service()
    client.outcome = GenerationOutcome(error_code=code, attempts=1)
    kb = uuid4()
    with authorized_generation_scope(kb):
        answer = service.answer(QUERY, kb)
    assert answer.generation.mode == "fallback"
    assert answer.text == service.local.answer(QUERY, kb).text
    assert QUOTE in answer.text


@pytest.mark.parametrize("output", [
    GeneratedEvidenceAnswer(status="refused", refusal_reason="insufficient_evidence"),
    GeneratedEvidenceAnswer(status="answered", quotes=(GeneratedQuote(citation_id="C1", quoted_text="6.80"),)),
    GeneratedEvidenceAnswer(status="answered", quotes=(GeneratedQuote(citation_id="C2", quoted_text=QUOTE),)),
])
def test_refusal_or_partial_claim_falls_back(output):
    service, client = setup_service()
    client.outcome = GenerationOutcome(answer=output, attempts=1)
    kb = uuid4()
    with authorized_generation_scope(kb):
        answer = service.answer(QUERY, kb)
    assert answer.generation.mode == "fallback"
    assert answer.citations[0].quoted_text == QUOTE


def test_graph_and_checkpoint_serialization_preserve_generation_status():
    service, client = setup_service()
    graph = build_research_graph(ResearchToolAdapter(document_answer=service, document_search=service.local.search))
    kb = uuid4()
    with authorized_generation_scope(kb):
        result = graph.invoke({"query": QUERY, "knowledge_base_id": str(kb)})
    assert result["answer_result"].status == "answered"
    item = result["tool_results"][0]
    assert item.document_answer.generation.mode == "generated"
    serializer = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_CHECKPOINT_TYPES)
    recovered = serializer.loads_typed(serializer.dumps_typed(item))
    assert recovered.document_answer.generation.mode == "generated"
    assert GroundedDocumentAnswer.model_validate_json(item.document_answer.model_dump_json()).generation.attempts == 1
    assert len(client.requests) == 1
