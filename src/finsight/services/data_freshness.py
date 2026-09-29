"""Describe observation freshness without confusing it with fetch time."""

from dataclasses import dataclass
from datetime import date

from finsight.domain.financial_data import FinancialIndicatorRecord, FinancialStatementRecord
from finsight.services.data_quality import FinancialDataBatch


@dataclass(frozen=True)
class FreshnessItem:
    category: str
    key: str
    latest_date: date | None
    status: str


@dataclass(frozen=True)
class FreshnessReport:
    as_of: date
    items: tuple[FreshnessItem, ...]

    @property
    def has_stale_or_missing(self) -> bool:
        return any(item.status != "fresh" for item in self.items)


def assess_batch_freshness(
    batch: FinancialDataBatch,
    *,
    as_of: date,
    max_market_age_days: int = 5,
    max_annual_age_days: int = 550,
) -> FreshnessReport:
    """Check latest observation dates, not when CSV or API rows were fetched."""
    if max_market_age_days < 0 or max_annual_age_days < 0:
        raise ValueError("freshness limits must be non-negative")

    market_dates: dict[str, date] = {}
    for record in batch.market_prices:
        symbol = f"{record.exchange}/{record.ticker}"
        market_dates[symbol] = max(market_dates.get(symbol, record.trade_date), record.trade_date)

    annual_dates: dict[str, date] = {}
    financial_records: tuple[FinancialStatementRecord | FinancialIndicatorRecord, ...] = (
        *batch.financial_statements,
        *batch.financial_indicators,
    )
    for financial_record in financial_records:
        if financial_record.period_type.value != "annual":
            continue
        annual_dates[financial_record.company_code] = max(
            annual_dates.get(financial_record.company_code, financial_record.report_date),
            financial_record.report_date,
        )

    items: list[FreshnessItem] = []
    market_keys = set(market_dates) | {
        f"{security.exchange}/{security.ticker}" for security in batch.securities
    }
    for symbol in sorted(market_keys):
        latest = market_dates.get(symbol)
        status = _status(latest, as_of, max_market_age_days)
        items.append(FreshnessItem("market_price", symbol, latest, status))

    company_keys = set(annual_dates) | {company.company_code for company in batch.companies}
    for company_code in sorted(company_keys):
        latest = annual_dates.get(company_code)
        status = _status(latest, as_of, max_annual_age_days)
        items.append(FreshnessItem("annual_financial", company_code, latest, status))

    return FreshnessReport(as_of=as_of, items=tuple(items))


def _status(latest: date | None, as_of: date, max_age_days: int) -> str:
    if latest is None:
        return "missing"
    age = (as_of - latest).days
    if age < 0:
        return "future"
    return "fresh" if age <= max_age_days else "stale"
