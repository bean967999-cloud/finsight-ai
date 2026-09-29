from fastapi import APIRouter, Depends

from finsight.api.routes.auth import require_active_principal
from finsight.domain.schemas import RiskMetrics, RiskRequest
from finsight.services.risk_engine import RiskEngine

router = APIRouter(
    prefix="/api/v1/risk", tags=["risk"],
    dependencies=[Depends(require_active_principal)],
)


@router.post("/analyze", response_model=RiskMetrics)
def analyze_risk(request: RiskRequest) -> RiskMetrics:
    return RiskEngine.analyze(
        prices=request.prices,
        confidence=request.confidence,
        trading_days=request.trading_days,
        risk_free_rate=request.risk_free_rate,
    )
