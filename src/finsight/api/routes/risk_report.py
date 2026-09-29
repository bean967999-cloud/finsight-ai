"""Versioned endpoints for dated risk reports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from finsight.api.routes.auth import require_active_principal
from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.services.market_price_reader import (
    MarketPriceNotFound,
    MarketPriceReader,
    MarketPriceSelection,
)
from finsight.services.portfolio_risk import PortfolioPosition
from finsight.services.risk_analysis import (
    AssetRiskReport,
    PortfolioRiskReport,
    RiskAnalysisService,
)

router = APIRouter(
    prefix="/api/v1/risk", tags=["risk-report"],
    dependencies=[Depends(require_active_principal)],
)
service = RiskAnalysisService()


class PricePointInput(BaseModel):
    trade_date: date
    close_price: Decimal = Field(gt=0)


class PriceSeriesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ticker: str = Field(min_length=1, max_length=32)
    adjustment_type: str = Field(min_length=1, max_length=16)
    data_source: str = Field(min_length=1, max_length=50)
    data_version: int = Field(ge=1)
    points: tuple[PricePointInput, ...] = Field(min_length=2, max_length=5001)

    def to_domain(self) -> PriceSeries:
        return PriceSeries(
            ticker=self.ticker,
            adjustment_type=self.adjustment_type,
            data_source=self.data_source,
            data_version=self.data_version,
            points=tuple(PricePoint(point.trade_date, point.close_price) for point in self.points),
        )


class AssetRiskRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    asset: PriceSeriesInput
    benchmark: PriceSeriesInput | None = None
    confidence: float = Field(default=0.95, gt=0.5, lt=1)
    holding_period: int = Field(default=1, ge=1, le=252)
    minimum_observations: int = Field(default=20, ge=2, le=5000)
    annual_risk_free_rate: float = Field(default=0.0, gt=-1)
    trading_days_per_year: int = Field(default=252, ge=1, le=366)


class PortfolioPositionInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    prices: PriceSeriesInput
    weight: float = Field(ge=0, le=1)


class PortfolioRiskRequest(BaseModel):
    positions: tuple[PortfolioPositionInput, ...] = Field(min_length=1, max_length=30)
    trading_days_per_year: int = Field(default=252, ge=1, le=366)


class MarketPriceSelectionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    exchange: str = Field(min_length=1, max_length=16)
    ticker: str = Field(min_length=1, max_length=32)
    source_code: str = Field(min_length=1, max_length=50)
    adjustment_type: str = Field(min_length=1, max_length=16)
    data_version: int = Field(ge=1)
    start_date: date
    end_date: date

    def to_domain(self) -> MarketPriceSelection:
        return MarketPriceSelection(**self.model_dump())


class DatabaseAssetRiskRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    asset: MarketPriceSelectionInput
    benchmark: MarketPriceSelectionInput | None = None
    confidence: float = Field(default=0.95, gt=0.5, lt=1)
    holding_period: int = Field(default=1, ge=1, le=252)
    minimum_observations: int = Field(default=20, ge=2, le=5000)
    annual_risk_free_rate: float = Field(default=0.0, gt=-1)
    trading_days_per_year: int = Field(default=252, ge=1, le=366)


class DatabasePortfolioPositionInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    selection: MarketPriceSelectionInput
    weight: float = Field(ge=0, le=1)


class DatabasePortfolioRiskRequest(BaseModel):
    positions: tuple[DatabasePortfolioPositionInput, ...] = Field(min_length=1, max_length=30)
    trading_days_per_year: int = Field(default=252, ge=1, le=366)


def get_market_price_reader(request: Request) -> MarketPriceReader:
    reader = getattr(request.app.state, "market_price_reader", None)
    if reader is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="market price reader is not configured",
        )
    return reader


@router.post("/asset-report", response_model=AssetRiskReport)
def analyze_asset(payload: AssetRiskRequest) -> AssetRiskReport:
    try:
        return service.analyze_asset(
            payload.asset.to_domain(),
            benchmark=payload.benchmark.to_domain() if payload.benchmark else None,
            confidence=payload.confidence,
            holding_period=payload.holding_period,
            minimum_observations=payload.minimum_observations,
            annual_risk_free_rate=payload.annual_risk_free_rate,
            trading_days_per_year=payload.trading_days_per_year,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/portfolio-report", response_model=PortfolioRiskReport)
def analyze_portfolio(payload: PortfolioRiskRequest) -> PortfolioRiskReport:
    try:
        return service.analyze_portfolio(
            tuple(
                PortfolioPosition(position.prices.to_domain(), position.weight)
                for position in payload.positions
            ),
            trading_days_per_year=payload.trading_days_per_year,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/asset-report/from-db", response_model=AssetRiskReport)
def analyze_asset_from_db(
    payload: DatabaseAssetRiskRequest,
    reader: Annotated[MarketPriceReader, Depends(get_market_price_reader)],
) -> AssetRiskReport:
    try:
        asset = reader.load(payload.asset.to_domain())
        benchmark = reader.load(payload.benchmark.to_domain()) if payload.benchmark else None
        if benchmark is not None and asset.currency != benchmark.currency:
            raise ValueError("asset and benchmark currencies must match")
        return service.analyze_asset(
            asset.prices,
            benchmark=benchmark.prices if benchmark else None,
            confidence=payload.confidence,
            holding_period=payload.holding_period,
            minimum_observations=payload.minimum_observations,
            annual_risk_free_rate=payload.annual_risk_free_rate,
            trading_days_per_year=payload.trading_days_per_year,
            database_verified=True,
        )
    except MarketPriceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="market price database is unavailable",
        ) from exc


@router.post("/portfolio-report/from-db", response_model=PortfolioRiskReport)
def analyze_portfolio_from_db(
    payload: DatabasePortfolioRiskRequest,
    reader: Annotated[MarketPriceReader, Depends(get_market_price_reader)],
) -> PortfolioRiskReport:
    try:
        loaded = tuple(reader.load(item.selection.to_domain()) for item in payload.positions)
        if len({item.currency for item in loaded}) != 1:
            raise ValueError("portfolio currencies must match")
        positions = tuple(
            PortfolioPosition(item.prices, request.weight)
            for item, request in zip(loaded, payload.positions, strict=True)
        )
        return service.analyze_portfolio(
            positions, trading_days_per_year=payload.trading_days_per_year,
            database_verified=True,
        )
    except MarketPriceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="market price database is unavailable",
        ) from exc
