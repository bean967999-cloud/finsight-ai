"""Opt-in real PDF-to-reranked-evidence acceptance with isolated stores."""

import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from pymilvus import MilvusClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.document_data import DocumentType
from finsight.domain.evaluation import (
    EvaluationObservation,
    GoldenQuestionSet,
    ObservedEvidence,
)
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import DocumentIngestionJob
from finsight.infrastructure.embedding.bge_m3 import BGEM3EmbeddingProvider
from finsight.infrastructure.embedding.bge_reranker import BGERerankerProvider
from finsight.infrastructure.parsers.mineru import MinerUDocumentParser
from finsight.infrastructure.parsers.mineru_normalizer import normalize_mineru_output
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore
from finsight.services.citation_verification import CitationVerifier
from finsight.services.document_chunk_indexing import DocumentChunkIndexingService
from finsight.services.document_chunk_persistence import DocumentChunkPersistenceService
from finsight.services.document_chunk_source import ChunkSourceLoader
from finsight.services.document_ingestion import DocumentIngestionService
from finsight.services.document_parser import ParserOutput
from finsight.services.document_parsing import DocumentParsingService
from finsight.services.document_retrieval import DocumentRetrievalService, RetrievedChunk
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.evidence_reranking import EvidenceRerankingService
from finsight.services.financial_chunker import FinancialTextChunker
from finsight.services.retrieval_suite_evaluation import RetrievalSuiteEvaluator

pytestmark = pytest.mark.skipif(
    any(os.environ.get(name) != "1" for name in (
        "FINSIGHT_PG_INTEGRATION", "FINSIGHT_MILVUS_INTEGRATION",
        "FINSIGHT_MINERU_INTEGRATION", "FINSIGHT_BGE_INTEGRATION",
        "FINSIGHT_RERANKER_INTEGRATION", "FINSIGHT_REAL_PDF_INTEGRATION",
    )),
    reason="Enable all document, vector, reranker, and real-PDF integration flags",
)


def _normalize(output: ParserOutput, document_id: int):
    return normalize_mineru_output(output, document_id=document_id)


def _observed(chunk: RetrievedChunk) -> ObservedEvidence:
    return ObservedEvidence(
        content=chunk.content, page_start=chunk.page_start, page_end=chunk.page_end,
        document_title=chunk.document_title,
    )


def _relevant(question, item: ObservedEvidence) -> bool:
    return any(
        all(fragment in item.content for fragment in expected.contains_all)
        and (expected.page_number is None or item.page_start <= expected.page_number <= item.page_end)
        for expected in question.expected_evidence
    )


def test_real_pdf_retrieval_reranking_citations_and_metrics(tmp_path: Path) -> None:
    settings = get_settings()
    dataset = GoldenQuestionSet.load(
        Path(__file__).parents[1] / "Evaluation" / "GoldenQuestionsV1.json"
    )
    pdf = Path(os.environ["FINSIGHT_REAL_PDF_PATH"]).read_bytes()
    embedding_path = Path(os.environ["FINSIGHT_BGE_MODEL_PATH"])
    reranker_path = Path(os.environ["FINSIGHT_RERANKER_MODEL_PATH"])
    schema = f"finsight_evidence_{uuid4().hex[:12]}"
    collection = f"finsight_evidence_{uuid4().hex[:12]}"
    admin_engine = create_engine(settings.database_url)
    test_engine = None
    schema_created = False
    client = MilvusClient(uri=settings.milvus_uri)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            schema_created = True
        test_engine = create_engine(
            settings.database_url, connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        storage = LocalObjectStorage(tmp_path / "objects")
        upload_id = DocumentIngestionService(sessions, storage).ingest(
            pdf, idempotency_key="day8-public-excerpt",
            title="Public financial disclosure excerpt (two-page test sample)",
            document_type=DocumentType.ANNOUNCEMENT,
            company_code="PUBLIC_SAMPLE", report_year=2024,
        )
        with sessions() as session:
            upload = session.get(DocumentIngestionJob, upload_id)
            assert upload is not None and upload.document_id is not None
            document_id = upload.document_id
        parse_job_id = DocumentParsingService(
            sessions, storage,
            MinerUDocumentParser(settings.mineru_api_url, max_wait_seconds=600),
            _normalize,
        ).parse_document(document_id)
        source = ChunkSourceLoader(sessions, storage).load(parse_job_id)
        drafts = FinancialTextChunker().chunk(source)
        chunk_ids = DocumentChunkPersistenceService(sessions).save(source, drafts)

        embeddings = BGEM3EmbeddingProvider(
            embedding_path, device=os.environ.get("FINSIGHT_BGE_DEVICE", "cpu"), batch_size=2,
        )
        vectors = MilvusHybridVectorStore(
            settings.milvus_uri, collection_name=collection, client=client,
        )
        indexed = DocumentChunkIndexingService(
            sessions, embeddings, vectors, batch_size=2,
        ).index_parse_job(parse_job_id)
        assert len(indexed.vector_ids) == len(chunk_ids)

        retrieval = DocumentRetrievalService(sessions, embeddings, vectors)
        reranker = BGERerankerProvider(
            reranker_path,
            model_version="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
            device=os.environ.get("FINSIGHT_RERANKER_DEVICE", "cpu"), batch_size=2,
        )
        reranking = EvidenceRerankingService(
            reranker, candidate_top_k=dataset.retrieval_k, final_top_n=dataset.rerank_n,
        )
        verifier = CitationVerifier()
        observations: list[EvaluationObservation] = []

        for question in dataset.questions:
            started = perf_counter()
            criteria = DocumentSearchFilter(
                company_code=question.filters.company_code,
                document_type=question.filters.document_type,
                report_year=question.filters.report_year,
            )
            retrieved = retrieval.retrieve(
                question.query, criteria=criteria, limit=dataset.retrieval_k,
            )
            ranked = reranking.rerank(question.query, retrieved.chunks)
            observed_retrieved = tuple(_observed(item) for item in retrieved.chunks)
            observed_ranked = tuple(_observed(item.candidate) for item in ranked.evidence)
            relevant = next((
                (item, observed_item)
                for item, observed_item in zip(ranked.evidence, observed_ranked, strict=True)
                if _relevant(question, observed_item)
            ), None)
            citation_status = None
            cited_evidence = None
            if relevant is not None:
                ranked_item, cited_evidence = relevant
                claim = " ".join(question.expected_evidence[0].contains_all)
                citation_status = verifier.verify(
                    citation_id="C1", evidence=ranked_item,
                    claim_text=claim, quoted_text=ranked_item.candidate.content,
                ).citation.status
            observations.append(EvaluationObservation(
                question_id=question.question_id,
                retrieved=observed_retrieved,
                reranked=observed_ranked,
                citation_status=citation_status,
                cited_evidence=cited_evidence,
                refused=not ranked.evidence,
                latency_ms=(perf_counter() - started) * 1000,
            ))

        report = RetrievalSuiteEvaluator(
            EvaluationSuite.load(
                Path(__file__).parents[1] / "Evaluation" / "ResearchSuiteV1.json"
            ),
            dataset,
        ).report(tuple(observations))
        assert report.metrics is not None
        metrics = report.metrics
        print(f"Day8 real evidence metrics: {metrics.model_dump_json()}")
        assert metrics.retrieval_recall_at_k == 1.0
        assert metrics.rerank_hit_rate_at_n >= 2 / 3
        assert metrics.citation_correctness >= 2 / 3
        assert metrics.refusal_accuracy == 1.0
        assert metrics.unexpected_refusal_rate == 0.0
    finally:
        if client.has_collection(collection_name=collection):
            client.drop_collection(collection_name=collection)
        if test_engine is not None:
            test_engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
