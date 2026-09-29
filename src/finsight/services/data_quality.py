"""Cross-record checks after provider normalization and before persistence."""

from dataclasses import dataclass

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialStatementRecord,
    MarketPriceRecord,
    SecurityRecord,
)


@dataclass(frozen=True)
class FinancialDataBatch:
    companies: tuple[CompanyRecord, ...] = ()
    securities: tuple[SecurityRecord, ...] = ()
    market_prices: tuple[MarketPriceRecord, ...] = ()
    financial_statements: tuple[FinancialStatementRecord, ...] = ()
    financial_indicators: tuple[FinancialIndicatorRecord, ...] = ()


@dataclass(frozen=True)
class DataQualityIssue:
    level: str
    collection: str
    index: int
    message: str


@dataclass(frozen=True)
class DataQualityReport:
    checked_rows: int
    issues: tuple[DataQualityIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    @property
    def error_count(self) -> int:
        return sum(issue.level == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.level == "warning" for issue in self.issues)


def validate_financial_batch(
    batch: FinancialDataBatch, source_code: str
) -> DataQualityReport:
    """Check source, relationships, duplicates, units, and missing values without writes."""
    if not source_code.strip():
        raise ValueError("source_code must not be empty")

    issues: list[DataQualityIssue] = []
    collections = (
        ("companies", batch.companies),
        ("securities", batch.securities),
        ("market_prices", batch.market_prices),
        ("financial_statements", batch.financial_statements),
        ("financial_indicators", batch.financial_indicators),
    )
    company_codes = {record.company_code for record in batch.companies}
    security_keys = {(record.exchange, record.ticker) for record in batch.securities}

    def add(level: str, collection: str, index: int, message: str) -> None:
        issues.append(DataQualityIssue(level, collection, index, message))

    for name, records in collections:
        for index, record in enumerate(records):
            if record.source_code != source_code:
                add("error", name, index, "source_code differs from the import source")
            if record.source_record_id is None:
                add("warning", name, index, "source_record_id is missing")

    seen_companies: set[str] = set()
    for index, record in enumerate(batch.companies):
        if record.company_code in seen_companies:
            add("error", "companies", index, "duplicate company_code in batch")
        seen_companies.add(record.company_code)

    seen_securities: set[tuple[str, str]] = set()
    for index, record in enumerate(batch.securities):
        security_key = (record.exchange, record.ticker)
        if security_key in seen_securities:
            add("error", "securities", index, "duplicate exchange/ticker in batch")
        seen_securities.add(security_key)
        if company_codes and record.company_code not in company_codes:
            add("error", "securities", index, "company_code is absent from batch")
        if record.currency != "CNY":
            add("error", "securities", index, "first import supports CNY securities only")

    seen_prices: set[tuple[str, str, object, str, int]] = set()
    for index, record in enumerate(batch.market_prices):
        price_key = (
            record.exchange, record.ticker, record.trade_date,
            record.adjustment_type, record.data_version,
        )
        if price_key in seen_prices:
            add("error", "market_prices", index, "duplicate price business key in batch")
        seen_prices.add(price_key)
        if security_keys and (record.exchange, record.ticker) not in security_keys:
            add("error", "market_prices", index, "security is absent from batch")
        if record.adjustment_type != "none":
            add("error", "market_prices", index, "first import supports unadjusted prices only")

    seen_statements: set[tuple[object, ...]] = set()
    for index, record in enumerate(batch.financial_statements):
        statement_key = (
            record.company_code, record.report_date, record.period_type,
            record.statement_type, record.item_code, record.consolidation_scope,
            record.data_version,
        )
        if statement_key in seen_statements:
            add("error", "financial_statements", index, "duplicate statement business key")
        seen_statements.add(statement_key)
        if company_codes and record.company_code not in company_codes:
            add("error", "financial_statements", index, "company_code is absent from batch")
        if record.currency != "CNY" or record.unit != "yuan":
            add("error", "financial_statements", index, "expected CNY and yuan")
        if record.value is None:
            add("warning", "financial_statements", index, "statement value is missing")

    seen_indicators: set[tuple[object, ...]] = set()
    for index, record in enumerate(batch.financial_indicators):
        indicator_key = (
            record.company_code, record.report_date, record.period_type,
            record.indicator_code, record.data_version,
        )
        if indicator_key in seen_indicators:
            add("error", "financial_indicators", index, "duplicate indicator business key")
        seen_indicators.add(indicator_key)
        if company_codes and record.company_code not in company_codes:
            add("error", "financial_indicators", index, "company_code is absent from batch")
        if record.indicator_code in {"roe", "debt_to_assets"} and record.unit != "%":
            add("error", "financial_indicators", index, "expected percent unit")
        if record.value is None:
            add("warning", "financial_indicators", index, "indicator value is missing")

    return DataQualityReport(
        checked_rows=sum(len(records) for _, records in collections),
        issues=tuple(issues),
    )
