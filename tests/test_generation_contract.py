from dataclasses import replace
from hashlib import sha256

import pytest
from pydantic import ValidationError

from finsight.domain.generation import (
    GeneratedEvidenceAnswer,
    GenerationPolicy,
    PublicEvidenceExcerpt,
    PublicGenerationRequest,
)
from finsight.services.generation_boundary import (
    GenerationBoundaryError,
    ReviewedPublicEvidence,
    build_public_request,
    validate_generated_quotes,
)


def reviewed(**changes):
    excerpt = PublicEvidenceExcerpt(
        citation_id="C1", title="Public results 2023", report_year=2023,
        page_number=1, quote="Total dividends of HK$6.50 per share for 2023.",
    )
    return replace(ReviewedPublicEvidence(excerpt, True, True, True), **changes)


def request():
    return build_public_request(
        "2023年全年每股股息是多少？", (reviewed(),), public_query_approved=True,
    )


def test_default_policy_disabled_and_bounded():
    policy = GenerationPolicy()
    assert not policy.enabled
    assert policy.max_attempts == 2 and policy.max_daily_attempts == 20
    assert policy.max_output_tokens == 512


@pytest.mark.parametrize("updates", [
    {"provider": "other"}, {"endpoint": "http://api.deepseek.com/chat/completions"},
    {"endpoint": "https://proxy.example/chat/completions"}, {"max_attempts": 3},
    {"max_daily_attempts": 21}, {"max_output_tokens": 513},
    {"request_timeout_seconds": 21}, {"total_timeout_seconds": 46},
    {"total_timeout_seconds": 10}, {"max_attempts": "2"}, {"api_key": "fake"},
])
def test_policy_rejects_unapproved_or_unbounded_settings(updates):
    with pytest.raises(ValidationError):
        GenerationPolicy(**updates)


@pytest.mark.parametrize("field", [
    "public_source_approved", "actor_authorized", "source_anchored",
])
def test_all_server_decisions_required(field):
    with pytest.raises(GenerationBoundaryError, match="evidence_not_approved_for_export"):
        build_public_request("2023年全年股息", (reviewed(**{field: False}),),
                             public_query_approved=True)


def test_private_or_unreviewed_query_blocked():
    with pytest.raises(GenerationBoundaryError, match="query_not_approved_for_export"):
        build_public_request("私有研究记录", (reviewed(),), public_query_approved=False)


@pytest.mark.parametrize("text", [
    "Bearer fake-token", "sk-fake-secret", "password=fake", "API_KEY=fake",
    "someone@example.com", "13800138000", "110101199001010011",
    "E:\\Private\\file", "https://example.com?token=fake",
    "-----BEGIN PRIVATE KEY-----",
])
@pytest.mark.parametrize("location", ["query", "quote", "title"])
def test_sensitive_content_blocked_in_all_export_text(text, location):
    item = reviewed()
    query = "2023年全年股息"
    if location == "query":
        query = text
    else:
        values = item.excerpt.model_dump()
        values[location] = text
        item = replace(item, excerpt=PublicEvidenceExcerpt(**values))
    with pytest.raises(GenerationBoundaryError, match="sensitive_content_detected") as error:
        build_public_request(query, (item,), public_query_approved=True)
    assert text not in str(error.value)


@pytest.mark.parametrize("field", ["user_id", "knowledge_base_id", "object_key", "api_key"])
def test_export_dto_rejects_internal_fields(field):
    with pytest.raises(ValidationError):
        PublicEvidenceExcerpt(**reviewed().excerpt.model_dump(), **{field: "fake"})


def test_export_is_allowlisted_and_digest_bound():
    envelope = request()
    assert set(envelope.model_dump()) == {"query", "query_sha256", "evidence"}
    assert envelope.query_sha256 == sha256(envelope.query.encode()).hexdigest()
    with pytest.raises(ValidationError):
        PublicGenerationRequest(**{**envelope.model_dump(), "query_sha256": "a" * 64})


def test_cross_year_and_duplicate_sources_rejected():
    values = request().model_dump()
    with pytest.raises(ValidationError):
        PublicGenerationRequest(**{**values, "evidence": values["evidence"] * 2})
    another = {**values["evidence"][0], "citation_id": "C2", "report_year": 2024}
    with pytest.raises(ValidationError):
        PublicGenerationRequest(**{**values, "evidence": [*values["evidence"], another]})


@pytest.mark.parametrize("query,count", [("x" * 501, 1), ("2023年股息", 0),
                                        ("2023年股息", 4)])
def test_oversized_export_rejected(query, count):
    with pytest.raises((GenerationBoundaryError, ValidationError)):
        build_public_request(query, (reviewed(),) * count, public_query_approved=True)


def test_valid_generated_quote_is_still_only_a_draft():
    answer = GeneratedEvidenceAnswer.model_validate({
        "status": "answered", "quotes": [{"citation_id": "C1", "quoted_text": "HK$6.50"}],
    })
    assert validate_generated_quotes(request(), answer) == answer


@pytest.mark.parametrize("citation,quote,reason", [
    ("C2", "HK$6.50", "unknown_citation"),
    ("C1", "HK$9.99", "quote_not_in_exported_source"),
])
def test_fabricated_citation_or_quote_rejected(citation, quote, reason):
    answer = GeneratedEvidenceAnswer.model_validate({
        "status": "answered", "quotes": [{"citation_id": citation, "quoted_text": quote}],
    })
    with pytest.raises(GenerationBoundaryError, match=reason):
        validate_generated_quotes(request(), answer)


@pytest.mark.parametrize("values", [
    {"status": "answered"}, {"status": "refused"},
    {"status": "refused", "refusal_reason": "insufficient_evidence",
     "quotes": [{"citation_id": "C1", "quoted_text": "HK$6.50"}]},
    {"status": "answered", "quotes": [{"citation_id": "C1", "quoted_text": "HK$6.50"}],
     "sql": "DROP TABLE documents"},
])
def test_incoherent_or_extra_model_fields_rejected(values):
    with pytest.raises(ValidationError):
        GeneratedEvidenceAnswer.model_validate(values)


def test_supported_refusal_shape():
    answer = GeneratedEvidenceAnswer.model_validate({
        "status": "refused", "refusal_reason": "insufficient_evidence",
    })
    assert validate_generated_quotes(request(), answer) == answer
