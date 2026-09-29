"""Local CSV adapter implementing the source-neutral financial data contract."""

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialQuery,
    FinancialRecord,
    FinancialStatementRecord,
    MarketPriceQuery,
    MarketPriceRecord,
    SecurityRecord,
)

RecordT = TypeVar("RecordT", bound=FinancialRecord)
_EXCHANGE_SUFFIX = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}


class CsvDataError(ValueError):
    """A CSV file is missing, malformed, or violates the normalized contract."""


class CsvFinancialDataProvider:
    """Read five UTF-8 CSV files from one directory without network access."""

    def __init__(self, directory: Path, source_code: str = "csv_demo") -> None:
        if not source_code or not source_code.strip():
            raise ValueError("source_code must not be empty")
        self.directory = Path(directory)
        self._source_code = source_code.strip()

    @property
    def source_code(self) -> str:
        return self._source_code

    def _read(self, name: str, record_type: type[RecordT]) -> list[RecordT]:
        path = self.directory / f"{name}.csv"
        if not path.is_file():
            raise CsvDataError(f"Missing CSV file: {path}")

        records: list[RecordT] = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                headers = reader.fieldnames
                if not headers or len(headers) != len(set(headers)) or any(
                    not header for header in headers
                ):
                    raise CsvDataError(f"Invalid CSV header: {path}")
                required = {
                    field_name
                    for field_name, field in record_type.model_fields.items()
                    if field.is_required() and field_name != "source_code"
                }
                missing = required - set(headers)
                if missing:
                    raise CsvDataError(f"Missing columns in {path}: {', '.join(sorted(missing))}")

                for line_number, row in enumerate(reader, start=2):
                    if None in row:
                        raise CsvDataError(f"Extra columns in {path}, line {line_number}")
                    values = {key: value if value != "" else None for key, value in row.items()}
                    values["source_code"] = self.source_code
                    values.setdefault("source_record_id", f"{name}:{line_number}")
                    try:
                        records.append(record_type.model_validate(values))
                    except ValidationError as exc:
                        raise CsvDataError(
                            f"Invalid data in {path}, line {line_number}: {exc.errors()[0]['msg']}"
                        ) from exc
        except UnicodeError as exc:
            raise CsvDataError(f"CSV must be UTF-8: {path}") from exc
        return records

    def fetch_companies(self, company_codes: Sequence[str]) -> list[CompanyRecord]:
        wanted = set(company_codes)
        return [
            record
            for record in self._read("companies", CompanyRecord)
            if record.company_code in wanted
        ]

    def fetch_securities(self, company_codes: Sequence[str]) -> list[SecurityRecord]:
        wanted = set(company_codes)
        return [
            record
            for record in self._read("securities", SecurityRecord)
            if record.company_code in wanted
        ]

    def fetch_market_prices(self, query: MarketPriceQuery) -> list[MarketPriceRecord]:
        wanted = set(query.symbols)
        return [
            record
            for record in self._read("market_prices", MarketPriceRecord)
            if f"{record.ticker}.{_EXCHANGE_SUFFIX.get(record.exchange, record.exchange)}"
            in wanted
            and query.start_date <= record.trade_date <= query.end_date
            and record.adjustment_type == query.adjustment_type
        ]

    def fetch_financial_statements(
        self, query: FinancialQuery
    ) -> list[FinancialStatementRecord]:
        wanted = set(query.company_codes)
        return [
            record
            for record in self._read("financial_statements", FinancialStatementRecord)
            if record.company_code in wanted
            and query.start_date <= record.report_date <= query.end_date
            and record.period_type in query.period_types
        ]

    def fetch_financial_indicators(
        self, query: FinancialQuery
    ) -> list[FinancialIndicatorRecord]:
        wanted = set(query.company_codes)
        return [
            record
            for record in self._read("financial_indicators", FinancialIndicatorRecord)
            if record.company_code in wanted
            and query.start_date <= record.report_date <= query.end_date
            and record.period_type in query.period_types
        ]
