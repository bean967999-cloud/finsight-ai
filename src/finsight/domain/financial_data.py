from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompanyStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SecurityType(StrEnum):
    STOCK = "stock"
    FUND = "fund"
    BOND = "bond"
    INDEX = "index"


class StatementType(StrEnum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW_STATEMENT = "cash_flow_statement"


class ReportingPeriodType(StrEnum):
    ANNUAL = "annual"
    SEMIANNUAL = "semiannual"
    QUARTERLY = "quarterly"


class ImportJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ImportJobType(StrEnum):
    FINANCIAL_DATA_BATCH = "financial_data_batch"
    COMPANY = "company"
    SECURITY = "security"
    MARKET_PRICE = "market_price"
    FINANCIAL_STATEMENT = "financial_statement"
    FINANCIAL_INDICATOR = "financial_indicator"


class FinancialRecord(BaseModel):
    """Immutable normalized record returned by every financial data provider."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    source_code: str = Field(min_length=1, max_length=50)
    source_record_id: str | None = Field(default=None, max_length=255)
    data_version: int = Field(default=1, ge=1)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompanyRecord(FinancialRecord):
    company_code: str = Field(min_length=1, max_length=32)
    legal_name: str = Field(min_length=1, max_length=255)
    short_name: str | None = Field(default=None, max_length=100)
    unified_social_credit_code: str | None = Field(default=None, max_length=32)
    industry: str | None = Field(default=None, max_length=100)
    country: str = Field(default="CN", min_length=2, max_length=2)
    established_date: date | None = None
    status: CompanyStatus = CompanyStatus.ACTIVE


class SecurityRecord(FinancialRecord):
    company_code: str = Field(min_length=1, max_length=32)
    exchange: str = Field(min_length=1, max_length=16)
    ticker: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    security_type: SecurityType = SecurityType.STOCK
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    listing_date: date | None = None
    delisting_date: date | None = None
    is_active: bool = True


class MarketPriceRecord(FinancialRecord):
    exchange: str = Field(min_length=1, max_length=16)
    ticker: str = Field(min_length=1, max_length=32)
    trade_date: date
    open_price: Decimal = Field(gt=0)
    high_price: Decimal = Field(gt=0)
    low_price: Decimal = Field(gt=0)
    close_price: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    amount: Decimal | None = Field(default=None, ge=0)
    adjustment_type: str = Field(default="none", min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_ohlc_range(self) -> "MarketPriceRecord":
        if self.high_price < max(self.open_price, self.low_price, self.close_price):
            raise ValueError("high_price must cover open, low, and close prices")
        if self.low_price > min(self.open_price, self.high_price, self.close_price):
            raise ValueError("low_price must cover open, high, and close prices")
        return self


class FinancialStatementRecord(FinancialRecord):
    company_code: str = Field(min_length=1, max_length=32)
    report_date: date
    period_type: ReportingPeriodType
    statement_type: StatementType
    item_code: str = Field(min_length=1, max_length=100)
    item_name: str = Field(min_length=1, max_length=255)
    value: Decimal | None
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    unit: str = Field(default="yuan", min_length=1, max_length=32)
    consolidation_scope: str = Field(default="consolidated", min_length=1, max_length=16)


class FinancialIndicatorRecord(FinancialRecord):
    company_code: str = Field(min_length=1, max_length=32)
    report_date: date
    period_type: ReportingPeriodType
    indicator_code: str = Field(min_length=1, max_length=100)
    indicator_name: str = Field(min_length=1, max_length=255)
    value: Decimal | None
    unit: str = Field(min_length=1, max_length=32)
    calculation_method: str | None = Field(default=None, max_length=500)


class MarketPriceQuery(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    symbols: tuple[str, ...] = Field(min_length=1)
    start_date: date
    end_date: date
    adjustment_type: str = Field(default="none", min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_date_range(self) -> "MarketPriceQuery":
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class FinancialQuery(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    company_codes: tuple[str, ...] = Field(min_length=1)
    start_date: date
    end_date: date
    period_types: tuple[ReportingPeriodType, ...] = (ReportingPeriodType.ANNUAL,)

    @model_validator(mode="after")
    def validate_date_range(self) -> "FinancialQuery":
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self
