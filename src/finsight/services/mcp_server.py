"""Register the four guarded financial tools on a local MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from finsight.domain.access_control import Principal
from finsight.domain.mcp_tool_contracts import (
    CalculatePortfolioRiskInput,
    CalculatePortfolioRiskOutput,
    GenerateResearchBriefInput,
    GenerateResearchBriefOutput,
    QueryFinancialDataInput,
    QueryFinancialDataOutput,
    SearchFinancialDocumentsInput,
    SearchFinancialDocumentsOutput,
    ToolCallContext,
    ToolFailure,
)
from finsight.services.mcp_brief_tool import ResearchBriefTool
from finsight.services.mcp_document_tool import FinancialDocumentTool
from finsight.services.mcp_query_tool import FinancialQueryTool
from finsight.services.mcp_risk_tool import PortfolioRiskTool


class PrincipalProvider(Protocol):
    def resolve(self) -> Principal: ...


@dataclass(frozen=True, slots=True)
class McpToolDependencies:
    principal_provider: PrincipalProvider
    documents: FinancialDocumentTool
    financial_data: FinancialQueryTool
    risk: PortfolioRiskTool
    brief: ResearchBriefTool


def _safe_result[ResultT](result: ResultT | ToolFailure) -> ResultT:
    if isinstance(result, ToolFailure):
        raise ToolError(f"{result.code.value}: {result.message}")
    return result


def build_mcp_server(dependencies: McpToolDependencies) -> MCPServer:
    server = MCPServer(
        name="FinSight Financial Tools",
        instructions=(
            "Tool results are not independently verified investment conclusions. "
            "Respect limitation and review status fields."
        ),
    )

    def call_context() -> ToolCallContext:
        try:
            principal = dependencies.principal_provider.resolve()
            return ToolCallContext(principal=principal, request_id=uuid4())
        except Exception:  # noqa: BLE001 - deny without exposing identity internals
            raise ToolError("access_denied: Access denied") from None

    @server.tool()
    def search_financial_documents(
        payload: SearchFinancialDocumentsInput,
    ) -> SearchFinancialDocumentsOutput:
        """Retrieve bounded, source-linked excerpts from an authorized knowledge base."""
        return _safe_result(dependencies.documents.execute(call_context(), payload))

    @server.tool()
    def query_financial_data(payload: QueryFinancialDataInput) -> QueryFinancialDataOutput:
        """Run a bounded, guarded read-only financial query; never accept raw SQL."""
        return _safe_result(dependencies.financial_data.execute(call_context(), payload))

    @server.tool()
    def calculate_portfolio_risk(
        payload: CalculatePortfolioRiskInput,
    ) -> CalculatePortfolioRiskOutput:
        """Calculate deterministic risk metrics from caller-supplied portfolio values."""
        return _safe_result(dependencies.risk.execute(call_context(), payload))

    @server.tool()
    def generate_research_brief(
        payload: GenerateResearchBriefInput,
    ) -> GenerateResearchBriefOutput:
        """Run conservative research; release requests pause for human review."""
        return _safe_result(dependencies.brief.execute(call_context(), payload))

    return server
