from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from finsight.domain.evidence import Citation
from finsight.domain.grounded_document_answer import GenerationReport
from finsight.domain.query_plan import StructuredQueryPlan
from finsight.domain.research_flow import AnswerStatus, ResearchQuestion


class RiskRequest(BaseModel):
    prices: list[float] = Field(min_length=3)
    confidence: float = 0.95
    trading_days: int = 252
    risk_free_rate: float = 0.0

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.5 < value < 1:
            raise ValueError("confidence must be between 0.5 and 1.0")
        return value


class RiskMetrics(BaseModel):
    observations: int
    cumulative_return: float
    annualized_volatility: float
    max_drawdown: float
    historical_var: float
    historical_cvar: float
    sharpe_ratio: float | None


class AgentRequest(ResearchQuestion):
    """HTTP input follows the same validation contract as the research planner."""

    structured_plan: StructuredQueryPlan | None = None
    workspace_id: UUID | None = None
    knowledge_base_id: UUID | None = None
    release_requested: bool = False


class AgentResponse(BaseModel):
    thread_id: str | None = None
    review_pending: bool = False
    review_request: dict[str, object] | None = None
    intent: str
    answer: str
    answer_status: AnswerStatus
    limitations: tuple[str, ...] = ()
    risk_metrics: RiskMetrics | None = None
    evidence: list[str] = []
    citations: tuple[Citation, ...] = ()
    generation: GenerationReport | None = None
