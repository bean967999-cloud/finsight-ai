"""Fail-closed export boundary for separately authorized public evidence."""

import re
from dataclasses import dataclass
from hashlib import sha256

from finsight.domain.generation import (
    GeneratedEvidenceAnswer,
    PublicEvidenceExcerpt,
    PublicGenerationRequest,
)

_SENSITIVE = re.compile(
    r"\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]+|-----BEGIN[^\n]*PRIVATE KEY-----"
    r"|\b(?:api[_ -]?key|password|passwd|secret|token)\s*[:=]"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|\b1[3-9]\d{9}\b|\b\d{17}[\dXx]\b"
    r"|[A-Za-z]:[\\/]|https?://[^\s]+",
    re.IGNORECASE,
)


class GenerationBoundaryError(ValueError):
    """Safe reason codes only; never interpolate rejected input."""


def validate_export_content(request: PublicGenerationRequest) -> None:
    texts = (request.query, *(text for item in request.evidence for text in (
        item.title, item.quote,
    )))
    if any(_SENSITIVE.search(text) for text in texts):
        raise GenerationBoundaryError("sensitive_content_detected")


@dataclass(frozen=True)
class ReviewedPublicEvidence:
    """Server-only decisions; never populated from browser request booleans.

    Public provenance approval is separate from knowledge-base authorization.
    An upstream service must resolve these against server-controlled records.
    """

    excerpt: PublicEvidenceExcerpt
    public_source_approved: bool
    actor_authorized: bool
    source_anchored: bool


def build_public_request(
    query: str, evidence: tuple[ReviewedPublicEvidence, ...], *, public_query_approved: bool
) -> PublicGenerationRequest:
    if not public_query_approved:
        raise GenerationBoundaryError("query_not_approved_for_export")
    if not 1 <= len(evidence) <= 3:
        raise GenerationBoundaryError("evidence_count_out_of_bounds")
    for item in evidence:
        if not (item.public_source_approved and item.actor_authorized and item.source_anchored):
            raise GenerationBoundaryError("evidence_not_approved_for_export")
    query = query.strip()
    request = PublicGenerationRequest(
        query=query, query_sha256=sha256(query.encode()).hexdigest(),
        evidence=tuple(item.excerpt for item in evidence),
    )
    validate_export_content(request)
    return request


def validate_generated_quotes(
    request: PublicGenerationRequest, answer: GeneratedEvidenceAnswer,
) -> GeneratedEvidenceAnswer:
    sources = {item.citation_id: item.quote for item in request.evidence}
    for quote in answer.quotes:
        if quote.citation_id not in sources:
            raise GenerationBoundaryError("unknown_citation")
        if quote.quoted_text not in sources[quote.citation_id]:
            raise GenerationBoundaryError("quote_not_in_exported_source")
    # Substring agreement does NOT prove that the quote answers the question.
    # Business year/company/metric gates must still run before rendering.
    return answer
