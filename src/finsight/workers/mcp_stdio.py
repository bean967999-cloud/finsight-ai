"""Start the local stdio tool service with server-resolved identity and audit."""

from __future__ import annotations

import os
from pathlib import Path

from finsight.agents.checkpoints import (
    ResearchCheckpointService,
    make_research_saver,
    project_checkpoint_connection,
)
from finsight.agents.graph import build_research_graph
from finsight.agents.tools import ResearchToolAdapter
from finsight.core.config import get_settings
from finsight.infrastructure.database.session import SessionFactory
from finsight.infrastructure.embedding.bge_m3 import BGEM3EmbeddingProvider
from finsight.infrastructure.embedding.bge_reranker import BGERerankerProvider
from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore
from finsight.services.document_retrieval import DocumentRetrievalService
from finsight.services.evidence_reranking import EvidenceRerankingService
from finsight.services.evidence_search import EvidenceSearchService
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.knowledge_scope import KnowledgeScopeService
from finsight.services.mcp_brief_tool import ResearchBriefTool
from finsight.services.mcp_document_tool import FinancialDocumentTool
from finsight.services.mcp_query_tool import FinancialQueryTool
from finsight.services.mcp_risk_tool import PortfolioRiskTool
from finsight.services.mcp_server import McpToolDependencies, build_mcp_server
from finsight.services.operation_audit import OperationAuditService
from finsight.services.read_only_query_executor import ReadOnlyQueryExecutor
from finsight.services.structured_query import StructuredQueryService


class ProcessTokenPrincipal:
    """Re-resolve a short-lived process token on every call, including current grants."""

    def __init__(self, authentication: AuthenticationService, token: str) -> None:
        self._authentication = authentication
        self._token = token

    def resolve(self):
        return self._authentication.resolve(self._token)


class UnconfiguredDocumentSearch:
    def search(self, query, *, criteria=None):
        raise ConnectionError("document retrieval is not configured")


def make_document_search(settings):
    embedding_path = os.environ.get("FINSIGHT_BGE_M3_PATH", "")
    reranker_path = os.environ.get("FINSIGHT_RERANKER_PATH", "")
    reranker_version = os.environ.get("FINSIGHT_RERANKER_VERSION", "")
    if not any((embedding_path, reranker_path, reranker_version)):
        return UnconfiguredDocumentSearch()
    if not all((embedding_path, reranker_path, reranker_version)):
        raise ValueError("document retrieval configuration is incomplete")
    if not Path(embedding_path).is_dir() or not Path(reranker_path).is_dir():
        raise ValueError("local document models are unavailable")
    embeddings = BGEM3EmbeddingProvider(
        Path(embedding_path), device=os.environ.get("FINSIGHT_BGE_DEVICE", "cpu")
    )
    vectors = MilvusHybridVectorStore(
        settings.milvus_uri, collection_name=settings.milvus_collection,
        dimension=settings.embedding_dimension,
    )
    reranker = BGERerankerProvider(
        Path(reranker_path), model_version=reranker_version,
        device=os.environ.get("FINSIGHT_RERANKER_DEVICE", "cpu"),
    )
    return EvidenceSearchService(
        DocumentRetrievalService(SessionFactory, embeddings, vectors),
        EvidenceRerankingService(reranker, candidate_top_k=20, final_top_n=5),
    )


def main() -> int:
    settings = get_settings()
    token = os.environ.get("FINSIGHT_MCP_ACCESS_TOKEN", "")
    secret = settings.auth_jwt_secret.get_secret_value()
    if not token or not secret:
        raise SystemExit("MCP identity configuration unavailable")
    authentication = AuthenticationService(
        IdentityService(SessionFactory),
        TokenCodec(secret, ttl_minutes=settings.auth_token_minutes),
    )
    principal_provider = ProcessTokenPrincipal(authentication, token)
    try:
        principal_provider.resolve()
    except Exception:  # noqa: BLE001 - never expose token or database internals
        raise SystemExit("MCP identity could not be verified") from None

    audit = OperationAuditService(SessionFactory)
    ownership = KnowledgeScopeService(SessionFactory)
    structured = StructuredQueryService(ReadOnlyQueryExecutor(SessionFactory))

    try:
        documents = make_document_search(settings)
        with project_checkpoint_connection(settings.database_url) as connection:
            saver = make_research_saver(connection)
            saver.setup()
            research_tools = ResearchToolAdapter(
                document_search=documents, structured_query=structured
            )
            checkpoints = ResearchCheckpointService(
                saver, research_tools,
                database_url=settings.database_url,
            )
            server = build_mcp_server(McpToolDependencies(
                principal_provider=principal_provider,
                documents=FinancialDocumentTool(audit, ownership, documents),
                financial_data=FinancialQueryTool(audit, structured),
                risk=PortfolioRiskTool(audit),
                brief=ResearchBriefTool(
                    audit, build_research_graph(research_tools),
                    ownership, checkpoints,
                ),
            ))
            server.run(transport="stdio")
    except Exception:  # noqa: BLE001 - stdout belongs exclusively to protocol messages
        raise SystemExit("MCP service dependencies unavailable") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
