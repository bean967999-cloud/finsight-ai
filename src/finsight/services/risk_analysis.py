"""Orchestrate dated single-asset and portfolio risk calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finsight.domain.return_series import PriceSeries
from finsight.services.historical_tail_risk import (
    HistoricalTailRisk,
    calculate_historical_tail_risk,
)
from finsight.services.market_sensitivity import (
    BetaResult,
    SharpeResult,
    calculate_beta,
    calculate_sharpe,
)
from finsight.services.portfolio_risk import (
    PortfolioPosition,
    PortfolioRiskResult,
    calculate_portfolio_risk,
)
from finsight.services.price_risk import (
    DrawdownResult,
    VolatilityResult,
    calculate_drawdown,
    calculate_volatility,
)


@dataclass(frozen=True)
class RiskValueUnits:
    returns_and_volatility: str = "fraction"
    covariance: str = "fraction_squared"
    sharpe_beta_correlation: str = "dimensionless"
    contribution_share: str = "fraction"


@dataclass(frozen=True)
class AssetRiskReport:
    ticker: str
    adjustment_type: str
    data_source: str
    data_version: int
    price_observations: int
    start_date: date
    end_date: date
    volatility: VolatilityResult
    drawdown: DrawdownResult
    tail_risk: HistoricalTailRisk
    sharpe: SharpeResult
    beta: BetaResult | None
    units: RiskValueUnits
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioRiskReport:
    portfolio: PortfolioRiskResult
    sources: tuple[tuple[str, str, int], ...]
    units: RiskValueUnits
    warnings: tuple[str, ...]


class RiskAnalysisService:
    def analyze_asset(
        self,
        prices: PriceSeries,
        *,
        benchmark: PriceSeries | None = None,
        confidence: float = 0.95,
        holding_period: int = 1,
        minimum_observations: int = 20,
        annual_risk_free_rate: float = 0.0,
        trading_days_per_year: int = 252,
        database_verified: bool = False,
    ) -> AssetRiskReport:
        volatility = calculate_volatility(prices, trading_days_per_year=trading_days_per_year)
        drawdown = calculate_drawdown(prices)
        tail_risk = calculate_historical_tail_risk(
            prices,
            confidence=confidence,
            holding_period=holding_period,
            minimum_observations=minimum_observations,
        )
        sharpe = calculate_sharpe(
            prices,
            annual_risk_free_rate=annual_risk_free_rate,
            trading_days_per_year=trading_days_per_year,
        )
        beta = calculate_beta(prices, benchmark) if benchmark is not None else None

        warnings = [
            "Trading-calendar gaps have not been verified.",
            "Historical risk estimates do not bound future losses.",
        ]
        if not database_verified:
            warnings.extend((
                "Prices and source labels were supplied by the caller and have not been verified.",
                "Currency compatibility has not been verified.",
            ))
        if benchmark is None:
            warnings.append("Beta was not calculated because no benchmark was supplied.")
        return AssetRiskReport(
            ticker=prices.ticker,
            adjustment_type=prices.adjustment_type,
            data_source=prices.data_source,
            data_version=prices.data_version,
            price_observations=len(prices.points),
            start_date=prices.points[0].trade_date,
            end_date=prices.points[-1].trade_date,
            volatility=volatility,
            drawdown=drawdown,
            tail_risk=tail_risk,
            sharpe=sharpe,
            beta=beta,
            units=RiskValueUnits(),
            warnings=tuple(warnings),
        )

    def analyze_portfolio(
        self,
        positions: tuple[PortfolioPosition, ...],
        *,
        trading_days_per_year: int = 252,
        database_verified: bool = False,
    ) -> PortfolioRiskReport:
        portfolio = calculate_portfolio_risk(
            positions, trading_days_per_year=trading_days_per_year
        )
        warnings = [
            "Target weights are restored each observed period; trading costs are excluded.",
            "Trading-calendar gaps have not been verified.",
        ]
        if not database_verified:
            warnings.extend((
                "Prices and source labels were supplied by the caller and have not been verified.",
                "Currency compatibility has not been verified.",
            ))
        return PortfolioRiskReport(
            portfolio=portfolio,
            sources=tuple(
                (position.prices.ticker, position.prices.data_source, position.prices.data_version)
                for position in positions
            ),
            units=RiskValueUnits(),
            warnings=tuple(warnings),
        )
