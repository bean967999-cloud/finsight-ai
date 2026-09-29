"""Tushare HTTP adapter for the normalized financial data contract."""

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from finsight.domain.financial_data import (
    CompanyRecord,
    FinancialIndicatorRecord,
    FinancialQuery,
    FinancialStatementRecord,
    MarketPriceQuery,
    MarketPriceRecord,
    ReportingPeriodType,
    SecurityRecord,
    StatementType,
)

ApiCall = Callable[[str, Mapping[str, str], str], list[dict[str, Any]]]
_EXCHANGES = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}


class TushareDataError(RuntimeError):
    """Tushare failed or returned data that cannot be mapped safely."""


class TusharePermissionError(TushareDataError):
    """The account is not allowed to use the requested endpoint."""


class TushareHttpClient:
    """Small HTTP client; the token is kept in memory and never logged."""

    def __init__(self, token: str, timeout: float = 15.0) -> None:
        if not token.strip():
            raise ValueError("Tushare token is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._token = token.strip()
        self._timeout = timeout

    def query(self, api_name: str, params: Mapping[str, str], fields: str) -> list[dict[str, Any]]:
        payload = json.dumps(
            {"api_name": api_name, "token": self._token, "params": dict(params), "fields": fields}
        ).encode("utf-8")
        request = Request(
            "https://api.tushare.pro",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise TushareDataError(f"Tushare request failed: {api_name}") from exc

        if not isinstance(result, dict):
            raise TushareDataError(f"Invalid Tushare response: {api_name}")
        if result.get("code") == 2002:
            raise TusharePermissionError(f"Tushare permission denied: {api_name}")
        if result.get("code") != 0:
            raise TushareDataError(f"Tushare API error: {api_name}: {result.get('msg')}")
        data = result.get("data")
        if not isinstance(data, dict):
            raise TushareDataError(f"Missing Tushare data: {api_name}")
        columns, items = data.get("fields"), data.get("items")
        if not isinstance(columns, list) or not isinstance(items, list):
            raise TushareDataError(f"Invalid Tushare table: {api_name}")
        if len(columns) != len(set(columns)) or any(not isinstance(c, str) for c in columns):
            raise TushareDataError(f"Invalid Tushare columns: {api_name}")
        if any(not isinstance(item, list) or len(item) != len(columns) for item in items):
            raise TushareDataError(f"Invalid Tushare row: {api_name}")
        return [dict(zip(columns, item, strict=True)) for item in items]


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) != 8 or not text.isdigit():
        raise TushareDataError(f"Invalid Tushare date: {text}")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError as exc:
        raise TushareDataError(f"Invalid Tushare date: {text}") from exc


def _symbol_parts(value: Any) -> tuple[str, str]:
    if not isinstance(value, str) or "." not in value:
        raise TushareDataError(f"Invalid Tushare symbol: {value}")
    ticker, suffix = value.split(".", maxsplit=1)
    if not ticker or suffix not in _EXCHANGES:
        raise TushareDataError(f"Unsupported Tushare symbol: {value}")
    return _EXCHANGES[suffix], ticker


def _decimal(value: Any, multiplier: int = 1) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)) * multiplier
    except (ValueError, ArithmeticError) as exc:
        raise TushareDataError(f"Invalid Tushare number: {value}") from exc


def _required(value: Any, field: str) -> Any:
    if value in (None, ""):
        raise TushareDataError(f"Missing Tushare field: {field}")
    return value


class TushareFinancialDataProvider:
    """Map selected A-share Tushare endpoints to the provider contract."""

    source_code = "tushare"

    def __init__(self, query_api: ApiCall) -> None:
        self._query = query_api

    def _rows(self, name: str, params: Mapping[str, str], fields: str) -> list[dict[str, Any]]:
        return self._query(name, params, fields)

    def fetch_companies(self, company_codes: Sequence[str]) -> list[CompanyRecord]:
        records = []
        for code in company_codes:
            rows = self._rows(
                "stock_company", {"ts_code": code}, "ts_code,com_name,com_id,setup_date"
            )
            for row in rows:
                try:
                    records.append(
                        CompanyRecord(
                            source_code=self.source_code,
                            source_record_id=code,
                            company_code=row["ts_code"],
                            legal_name=_required(row.get("com_name"), "com_name"),
                            unified_social_credit_code=row.get("com_id") or None,
                            established_date=_parse_date(row.get("setup_date")),
                        )
                    )
                except (KeyError, ValidationError) as exc:
                    raise TushareDataError(f"Invalid stock_company row: {code}") from exc
        return records

    def fetch_securities(self, company_codes: Sequence[str]) -> list[SecurityRecord]:
        records = []
        for code in company_codes:
            rows = self._rows(
                "stock_basic",
                {"ts_code": code},
                "ts_code,symbol,name,exchange,curr_type,list_date,delist_date,list_status",
            )
            for row in rows:
                exchange, ticker = _symbol_parts(row.get("ts_code"))
                try:
                    records.append(
                        SecurityRecord(
                            source_code=self.source_code,
                            source_record_id=row["ts_code"],
                            company_code=row["ts_code"],
                            exchange=exchange,
                            ticker=ticker,
                            name=_required(row.get("name"), "name"),
                            currency=row.get("curr_type") or "CNY",
                            listing_date=_parse_date(row.get("list_date")),
                            delisting_date=_parse_date(row.get("delist_date")),
                            is_active=row.get("list_status") == "L",
                        )
                    )
                except (KeyError, ValidationError) as exc:
                    raise TushareDataError(f"Invalid stock_basic row: {code}") from exc
        return records

    def fetch_market_prices(self, query: MarketPriceQuery) -> list[MarketPriceRecord]:
        if query.adjustment_type != "none":
            raise TushareDataError("Tushare daily supports unadjusted prices only")
        records = []
        for symbol in query.symbols:
            _symbol_parts(symbol)
            rows = self._rows(
                "daily",
                {
                    "ts_code": symbol,
                    "start_date": query.start_date.strftime("%Y%m%d"),
                    "end_date": query.end_date.strftime("%Y%m%d"),
                },
                "ts_code,trade_date,open,high,low,close,vol,amount",
            )
            for row in rows:
                exchange, ticker = _symbol_parts(row.get("ts_code"))
                try:
                    records.append(
                        MarketPriceRecord(
                            source_code=self.source_code,
                            source_record_id=f"{row['ts_code']}:{row['trade_date']}:none",
                            exchange=exchange,
                            ticker=ticker,
                            trade_date=_required(_parse_date(row.get("trade_date")), "trade_date"),
                            open_price=_required(_decimal(row.get("open")), "open"),
                            high_price=_required(_decimal(row.get("high")), "high"),
                            low_price=_required(_decimal(row.get("low")), "low"),
                            close_price=_required(_decimal(row.get("close")), "close"),
                            volume=_required(_decimal(row.get("vol"), 100), "vol"),
                            amount=_decimal(row.get("amount"), 1000),
                            adjustment_type="none",
                        )
                    )
                except (KeyError, ValidationError) as exc:
                    raise TushareDataError(f"Invalid daily row: {symbol}") from exc
        return records

    def fetch_financial_statements(
        self, query: FinancialQuery
    ) -> list[FinancialStatementRecord]:
        if any(period.value != "annual" for period in query.period_types):
            raise TushareDataError("First Tushare mapping supports annual reports only")
        records = []
        for code in query.company_codes:
            rows = self._rows(
                "income",
                {"ts_code": code, "report_type": "1"},
                "ts_code,ann_date,end_date,report_type,comp_type,revenue,total_revenue,n_income_attr_p",
            )
            for row in rows:
                report_date = _parse_date(row.get("end_date"))
                if not report_date or report_date.month != 12 or report_date.day != 31:
                    continue
                if not query.start_date <= report_date <= query.end_date:
                    continue
                if str(row.get("report_type")) != "1":
                    continue
                for field, label in (
                    ("revenue", "营业收入"),
                    ("total_revenue", "营业总收入"),
                    ("n_income_attr_p", "归母净利润"),
                ):
                    if row.get(field) is None:
                        continue
                    try:
                        records.append(
                            FinancialStatementRecord(
                                source_code=self.source_code,
                                source_record_id=(
                                    f"{code}:{report_date.isoformat()}:{row.get('ann_date')}:{field}"
                                ),
                                company_code=code,
                                report_date=report_date,
                                period_type=ReportingPeriodType.ANNUAL,
                                statement_type=StatementType.INCOME_STATEMENT,
                                item_code=field,
                                item_name=label,
                                value=_decimal(row[field]),
                                currency="CNY",
                                unit="yuan",
                                consolidation_scope="consolidated",
                            )
                        )
                    except ValidationError as exc:
                        raise TushareDataError(f"Invalid income row: {code}") from exc
        return records

    def fetch_financial_indicators(
        self, query: FinancialQuery
    ) -> list[FinancialIndicatorRecord]:
        if any(period.value != "annual" for period in query.period_types):
            raise TushareDataError("First Tushare mapping supports annual reports only")
        records = []
        for code in query.company_codes:
            rows = self._rows(
                "fina_indicator",
                {"ts_code": code, "start_date": query.start_date.strftime("%Y%m%d"),
                 "end_date": query.end_date.strftime("%Y%m%d")},
                "ts_code,ann_date,end_date,roe,debt_to_assets",
            )
            for row in rows:
                report_date = _parse_date(row.get("end_date"))
                if not report_date or report_date.month != 12 or report_date.day != 31:
                    continue
                if not query.start_date <= report_date <= query.end_date:
                    continue
                for field, label in (("roe", "净资产收益率"), ("debt_to_assets", "资产负债率")):
                    if row.get(field) is None:
                        continue
                    try:
                        records.append(
                            FinancialIndicatorRecord(
                                source_code=self.source_code,
                                source_record_id=(
                                    f"{code}:{report_date.isoformat()}:{row.get('ann_date')}:{field}"
                                ),
                                company_code=code,
                                report_date=report_date,
                                period_type=ReportingPeriodType.ANNUAL,
                                indicator_code=field,
                                indicator_name=label,
                                value=_decimal(row[field]),
                                unit="%",
                                calculation_method=f"Tushare fina_indicator.{field}",
                            )
                        )
                    except ValidationError as exc:
                        raise TushareDataError(f"Invalid fina_indicator row: {code}") from exc
        return records
