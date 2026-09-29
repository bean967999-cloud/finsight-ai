"""Application service composing retrieval, reranking, and pending citations."""

from dataclasses import dataclass
from hashlib import sha256

from finsight.domain.evidence import Citation, EvidenceBundle
from finsight.services.document_retrieval import (
    DocumentRetrievalService,
    RetrievalTrace,
    RetrievedChunk,
)
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.evidence_reranking import (
    EvidenceRerankingService,
    RerankingTrace,
)


@dataclass(frozen=True, slots=True)
class EvidenceSearchResult:
    bundle: EvidenceBundle
    retrieval_trace: RetrievalTrace
    reranking_trace: RerankingTrace
    retrieved: tuple[RetrievedChunk, ...] = ()


class EvidenceSearchService:
    def __init__(
        self,
        retrieval: DocumentRetrievalService,
        reranking: EvidenceRerankingService,
    ) -> None:
        self._retrieval = retrieval
        self._reranking = reranking

    def search(
        self,
        query: str,
        *,
        criteria: DocumentSearchFilter | None = None,
    ) -> EvidenceSearchResult:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        retrieval = self._retrieval.retrieve(
            query,
            criteria=criteria,
            limit=self._reranking.candidate_top_k,
        )
        reranked = self._reranking.rerank(query, retrieval.chunks)
        citations = tuple(
            Citation(
                citation_id=f"C{index}",
                evidence=item,
                quoted_text=item.candidate.content,
            )
            for index, item in enumerate(reranked.evidence, start=1)
        )
        bundle = EvidenceBundle(
            query_sha256=sha256(query.encode("utf-8")).hexdigest(),
            candidate_count=reranked.trace.candidate_count,
            citations=citations,
        )
        return EvidenceSearchResult(bundle, retrieval.trace, reranked.trace, retrieval.chunks)
