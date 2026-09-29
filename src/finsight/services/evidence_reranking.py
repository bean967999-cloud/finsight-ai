"""Candidate top-k selection, independent reranking, and redundancy control."""

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite

from finsight.domain.evidence import EvidenceCandidate, RerankedEvidence
from finsight.domain.reranking import Reranker
from finsight.services.document_retrieval import RetrievedChunk


@dataclass(frozen=True, slots=True)
class RerankingTrace:
    input_count: int
    candidate_count: int
    scored_chunk_ids: tuple[int, ...]
    selected_chunk_ids: tuple[int, ...]
    duplicate_chunk_ids: tuple[int, ...]
    redundant_chunk_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RerankingResult:
    evidence: tuple[RerankedEvidence, ...]
    trace: RerankingTrace


class EvidenceRerankingService:
    def __init__(
        self,
        reranker: Reranker,
        *,
        candidate_top_k: int = 20,
        final_top_n: int = 5,
        redundancy_threshold: float = 0.90,
    ) -> None:
        if not 1 <= candidate_top_k <= 100:
            raise ValueError("candidate_top_k must be between 1 and 100")
        if not 1 <= final_top_n <= candidate_top_k:
            raise ValueError("final_top_n must be between 1 and candidate_top_k")
        if not 0.0 <= redundancy_threshold <= 1.0:
            raise ValueError("redundancy_threshold must be between 0 and 1")
        self._reranker = reranker
        self._candidate_top_k = candidate_top_k
        self._final_top_n = final_top_n
        self._redundancy_threshold = redundancy_threshold

    @property
    def candidate_top_k(self) -> int:
        return self._candidate_top_k

    @property
    def final_top_n(self) -> int:
        return self._final_top_n

    def rerank(self, query: str, chunks: tuple[RetrievedChunk, ...]) -> RerankingResult:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")

        candidates: list[EvidenceCandidate] = []
        duplicate_ids: list[int] = []
        seen_chunk_ids: set[int] = set()
        seen_hashes: set[str] = set()
        for rank, chunk in enumerate(chunks[: self._candidate_top_k], start=1):
            digest = sha256(chunk.content.encode("utf-8")).hexdigest()
            if chunk.chunk_id in seen_chunk_ids or digest in seen_hashes:
                duplicate_ids.append(chunk.chunk_id)
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            seen_hashes.add(digest)
            candidates.append(self._to_candidate(chunk, rank, digest))

        if not candidates:
            return RerankingResult((), RerankingTrace(
                input_count=len(chunks), candidate_count=0, scored_chunk_ids=(),
                selected_chunk_ids=(), duplicate_chunk_ids=tuple(duplicate_ids),
                redundant_chunk_ids=(),
            ))

        scores = self._reranker.score(query, tuple(item.content for item in candidates))
        if len(scores) != len(candidates) or any(not isfinite(score) for score in scores):
            raise ValueError("reranker returned incomplete, misaligned, or non-finite scores")
        ranked = sorted(
            zip(candidates, scores, strict=True),
            key=lambda pair: (-pair[1], pair[0].retrieval_rank, pair[0].chunk_id),
        )

        selected: list[tuple[EvidenceCandidate, float]] = []
        redundant_ids: list[int] = []
        for candidate, score in ranked:
            if any(self._is_redundant(candidate, chosen) for chosen, _ in selected):
                redundant_ids.append(candidate.chunk_id)
                continue
            selected.append((candidate, score))
            if len(selected) == self._final_top_n:
                break

        evidence = tuple(
            RerankedEvidence(
                candidate=candidate,
                reranker_name=self._reranker.name,
                reranker_version=self._reranker.version,
                rerank_score=score,
                final_rank=rank,
            )
            for rank, (candidate, score) in enumerate(selected, start=1)
        )
        return RerankingResult(evidence, RerankingTrace(
            input_count=len(chunks), candidate_count=len(candidates),
            scored_chunk_ids=tuple(item.chunk_id for item in candidates),
            selected_chunk_ids=tuple(item.candidate.chunk_id for item in evidence),
            duplicate_chunk_ids=tuple(duplicate_ids),
            redundant_chunk_ids=tuple(redundant_ids),
        ))

    @staticmethod
    def _to_candidate(chunk: RetrievedChunk, rank: int, digest: str) -> EvidenceCandidate:
        return EvidenceCandidate(
            vector_id=chunk.vector_id, document_id=chunk.document_id, chunk_id=chunk.chunk_id,
            parse_job_id=chunk.parse_job_id, chunk_version=chunk.chunk_version, kind=chunk.kind,
            content=chunk.content, content_sha256=digest, page_start=chunk.page_start,
            page_end=chunk.page_end, section_path=chunk.section_path,
            source_blocks=chunk.source_blocks, document_title=chunk.document_title,
            document_type=chunk.document_type, company_code=chunk.company_code,
            report_year=chunk.report_year, source_url=chunk.source_url,
            retrieval_rank=rank, retrieval_score=chunk.score,
        )

    def _is_redundant(self, left: EvidenceCandidate, right: EvidenceCandidate) -> bool:
        if left.document_id != right.document_id:
            return False
        left_grams = self._character_ngrams(left.content)
        right_grams = self._character_ngrams(right.content)
        if not left_grams or not right_grams:
            return left.content == right.content
        similarity = len(left_grams & right_grams) / len(left_grams | right_grams)
        return similarity >= self._redundancy_threshold

    @staticmethod
    def _character_ngrams(text: str, size: int = 3) -> set[str]:
        normalized = "".join(text.split()).lower()
        if len(normalized) < size:
            return {normalized} if normalized else set()
        return {normalized[index:index + size] for index in range(len(normalized) - size + 1)}
