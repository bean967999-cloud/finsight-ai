"""Optional public-evidence selection after local financial/source verification."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.evidence import CitationStatus
from finsight.domain.generation import GenerationStatus, PublicEvidenceExcerpt
from finsight.domain.grounded_document_answer import GenerationReport
from finsight.services.generation_boundary import ReviewedPublicEvidence, build_public_request


@dataclass(frozen=True)
class AuthorizedGenerationScope:
    """Created only after HTTP authentication and knowledge-base authorization."""

    knowledge_base_id: UUID


_SCOPE: ContextVar[AuthorizedGenerationScope | None] = ContextVar("generation_scope", default=None)


@contextmanager
def authorized_generation_scope(knowledge_base_id):
    token = _SCOPE.set(
        AuthorizedGenerationScope(knowledge_base_id) if knowledge_base_id is not None else None
    )
    try:
        yield
    finally:
        _SCOPE.reset(token)


class PublicSourceApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_year: int = Field(ge=1900, le=2100)


class PublicGenerationRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: int = Field(ge=1, le=1)
    queries: tuple[str, ...]
    sources: tuple[PublicSourceApproval, ...]

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class EvidenceGenerationAnswerService:
    """The model cannot replace the local verifier or expand approved financial claims.

    This synchronous port is used by research tool threads. Evaluations deliberately
    retain the original local service; they do not implicitly spend provider quota.
    """

    def __init__(self, local, client, settings, registry, sessions):
        self.local = local
        self.client = client
        self.settings = settings
        self.registry = registry
        self.sessions = sessions

    def answer(self, query, knowledge_base_id, *, criteria=None):
        baseline = self.local.answer(query, knowledge_base_id, criteria=criteria)
        if baseline is None:
            return None  # No verified financial fact means no provider request.

        def finish(mode, reason, attempts=0):
            return baseline.model_copy(update={"generation": GenerationReport(
                mode=mode, reason=reason, attempts=attempts,
            )})

        if not self.settings.enabled:
            return finish("local", "disabled")
        if not self.settings.api_key.get_secret_value():
            return finish("fallback", "key_missing")
        scope = _SCOPE.get()
        if scope is None or scope.knowledge_base_id != knowledge_base_id:
            return finish("local", "scope_not_authorized")
        if self.registry is None or query.strip() not in self.registry.queries:
            return finish("local", "public_query_not_approved")
        try:
            from finsight.infrastructure.database.models import Document

            reviewed = []
            with self.sessions() as session:
                for citation in baseline.citations:
                    candidate = citation.evidence.candidate
                    document = session.get(Document, candidate.document_id)
                    if document is None or not any(
                        item.file_sha256 == document.content_sha256
                        and item.report_year == candidate.report_year
                        for item in self.registry.sources
                    ):
                        return finish("local", "public_source_not_approved")
                    reviewed.append(ReviewedPublicEvidence(
                        excerpt=PublicEvidenceExcerpt(
                            citation_id=citation.citation_id, title=candidate.document_title,
                            report_year=candidate.report_year, page_number=candidate.page_start,
                            quote=citation.quoted_text,
                        ),
                        public_source_approved=True, actor_authorized=True,
                        source_anchored=citation.status == CitationStatus.VERIFIED,
                    ))
            request = build_public_request(query, tuple(reviewed), public_query_approved=True)
        except Exception:  # noqa: BLE001 - never leak rejected document or query text
            return finish("local", "export_boundary_rejected")
        try:
            outcome = asyncio.run(self.client.generate(request))
        except Exception:  # noqa: BLE001 - preserve the verified local answer on provider failure
            return finish("fallback", "provider_unavailable")
        if outcome.error_code is not None or outcome.answer is None:
            return finish("fallback", "provider_failed", outcome.attempts)
        if outcome.answer.status != GenerationStatus.ANSWERED:
            return finish("fallback", "model_refused", outcome.attempts)
        expected = {item.citation_id: item.quote for item in request.evidence}
        actual = {item.citation_id: item.quoted_text for item in outcome.answer.quotes}
        if actual != expected:
            # Exact complete claims, not merely a number stripped of its year/unit.
            return finish("fallback", "claim_changed", outcome.attempts)
        # The model selects evidence, while the trusted local renderer controls prose.
        # Preserve the same independently verified citations and financial meaning.
        return finish("generated", "verified_evidence_selection", outcome.attempts)
