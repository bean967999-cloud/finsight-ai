"""Day17 Step6: an actual MCP client discovers and calls the four tools in memory."""

import sys
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from mcp import Client, StdioServerParameters

from finsight.agents.graph import build_research_graph
from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.domain.evidence import EvidenceBundle
from finsight.domain.query_execution import QueryExecutionResult
from finsight.services.mcp_brief_tool import ResearchBriefTool
from finsight.services.mcp_document_tool import FinancialDocumentTool
from finsight.services.mcp_query_tool import FinancialQueryTool
from finsight.services.mcp_risk_tool import PortfolioRiskTool
from finsight.services.mcp_server import McpToolDependencies, build_mcp_server
from finsight.services.structured_query import StructuredQueryService

WORKSPACE = UUID(int=61)
KNOWLEDGE = UUID(int=62)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FixedPrincipal:
    def __init__(self, role=Role.RESEARCHER, *, fail=False) -> None:
        self.role = role
        self.fail = fail

    def resolve(self):
        if self.fail:
            raise RuntimeError("private credential details")
        return Principal(user_id=UUID(int=60), memberships=(WorkspaceMembership(
            workspace_id=WORKSPACE, role=self.role, knowledge_base_ids=(KNOWLEDGE,),
        ),))


class MemoryAudit:
    def __init__(self) -> None:
        self.actions = []

    def begin(self, request_id, *, action, method, route_pattern, target_id) -> None:
        self.actions.append(action)

    def finish(self, request_id, *, status_code, actor_user_id=None, workspace_id=None, knowledge_base_id=None) -> None:
        pass


class Ownership:
    def workspace_for(self, knowledge_base_id):
        return WORKSPACE


class EmptySearch:
    def search(self, query, *, criteria=None):
        class Result:
            bundle = EvidenceBundle(
                query_sha256=sha256(query.encode()).hexdigest(), candidate_count=0,
            )
        return Result()


class FakeExecutor:
    def execute(self, guarded):
        columns = guarded.compiled.selected_columns
        return QueryExecutionResult(
            query_sha256=guarded.compiled.query_sha256,
            sql_sha256="a" * 64, columns=columns,
            rows=({column: None for column in columns},), row_count=1, execution_ms=1.0,
        )


def server_for(principal):
    audit = MemoryAudit()
    ownership = Ownership()
    structured = StructuredQueryService(FakeExecutor())
    server = build_mcp_server(McpToolDependencies(
        principal_provider=principal,
        documents=FinancialDocumentTool(audit, ownership, EmptySearch()),
        financial_data=FinancialQueryTool(audit, structured),
        risk=PortfolioRiskTool(audit),
        brief=ResearchBriefTool(audit, build_research_graph(), ownership),
    ))
    return server, audit


@pytest.mark.anyio
async def test_client_discovers_and_calls_all_four_tools_without_a_port() -> None:
    server, audit = server_for(FixedPrincipal())
    async with Client(server, raise_exceptions=True) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert names == {
            "search_financial_documents", "query_financial_data",
            "calculate_portfolio_risk", "generate_research_brief",
        }
        risk = await client.call_tool("calculate_portfolio_risk", {
            "payload": {"workspace_id": str(WORKSPACE), "prices": [100, 90, 99]}
        })
        assert risk.is_error is False
        assert risk.structured_content["source"] == "caller_supplied_prices"

        query = await client.call_tool("query_financial_data", {
            "payload": {
                "workspace_id": str(WORKSPACE), "query": "查询公司列表",
                "intent": "company_lookup", "limit": 1,
            }
        })
        assert query.is_error is False
        assert query.structured_content["row_count"] == 1

        documents = await client.call_tool("search_financial_documents", {
            "payload": {
                "workspace_id": str(WORKSPACE), "knowledge_base_id": str(KNOWLEDGE),
                "query": "查询年报原文",
            }
        })
        assert documents.is_error is False
        assert documents.structured_content["references"] == []

        brief = await client.call_tool("generate_research_brief", {
            "payload": {
                "workspace_id": str(WORKSPACE), "query": "计算价格波动率",
                "prices": [100, 90, 99],
            }
        })
        assert brief.is_error is False
        assert brief.structured_content["answer_status"] == "insufficient_evidence"
    assert set(audit.actions) == names


@pytest.mark.anyio
async def test_client_sees_safe_errors_for_denied_and_unresolved_identity() -> None:
    server, _ = server_for(FixedPrincipal(Role.VIEWER))
    async with Client(server, raise_exceptions=True) as client:
        denied = await client.call_tool("calculate_portfolio_risk", {
            "payload": {"workspace_id": str(WORKSPACE), "prices": [100, 90, 99]}
        })
        assert denied.is_error is True
        assert "access_denied" in str(denied.content)

    server, _ = server_for(FixedPrincipal(fail=True))
    async with Client(server, raise_exceptions=True) as client:
        invalid = await client.call_tool("calculate_portfolio_risk", {
            "payload": {"workspace_id": str(WORKSPACE), "prices": [100, 90, 99]}
        })
        assert invalid.is_error is True
        assert "private credential" not in str(invalid.content)


@pytest.mark.anyio
async def test_stdio_client_can_launch_server_and_call_tool_without_a_port() -> None:
    parameters = StdioServerParameters(
        command=sys.executable, args=[str(Path(__file__).resolve())],
        cwd=Path(__file__).resolve().parents[1],
    )
    async with Client(parameters, read_timeout_seconds=10) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert "calculate_portfolio_risk" in names
        result = await client.call_tool("calculate_portfolio_risk", {
            "payload": {"workspace_id": str(WORKSPACE), "prices": [100, 90, 99]}
        })
        assert result.is_error is False
        assert result.structured_content["source"] == "caller_supplied_prices"


if __name__ == "__main__":
    server_for(FixedPrincipal())[0].run(transport="stdio")
