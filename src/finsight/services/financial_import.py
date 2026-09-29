"""Atomic import of one normalized financial data batch."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from finsight.domain.financial_data import (
    FinancialQuery,
    ImportJobStatus,
    ImportJobType,
    MarketPriceQuery,
)
from finsight.infrastructure.database.models import (
    Company,
    DataSource,
    FinancialIndicator,
    FinancialStatement,
    ImportJob,
    MarketPrice,
    Security,
)
from finsight.infrastructure.database.repositories import (
    CompanyRepository,
    DataSourceRepository,
    FinancialIndicatorRepository,
    FinancialStatementRepository,
    ImportJobRepository,
    MarketPriceRepository,
    SecurityRepository,
)
from finsight.services.data_quality import FinancialDataBatch, validate_financial_batch
from finsight.services.financial_data_provider import FinancialDataProvider

SessionProvider = Callable[[], Session]


class FinancialImportError(RuntimeError):
    """A batch could not be imported safely."""


class FinancialImportService:
    """Own the transaction; repositories only flush and query."""

    def __init__(self, session_provider: SessionProvider) -> None:
        self._session_provider = session_provider

    def import_from_provider(
        self,
        provider: FinancialDataProvider,
        *,
        company_codes: Sequence[str],
        market_query: MarketPriceQuery,
        financial_query: FinancialQuery,
        idempotency_key: str,
    ) -> int:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency_key must be 1-128 characters")
        if not provider.source_code.strip():
            raise ValueError("provider source_code must not be empty")
        with self._session_provider() as session:
            if ImportJobRepository(session).get_by_idempotency_key(idempotency_key) is not None:
                raise FinancialImportError("idempotency_key already exists")
        try:
            batch = FinancialDataBatch(
                companies=tuple(provider.fetch_companies(company_codes)),
                securities=tuple(provider.fetch_securities(company_codes)),
                market_prices=tuple(provider.fetch_market_prices(market_query)),
                financial_statements=tuple(provider.fetch_financial_statements(financial_query)),
                financial_indicators=tuple(provider.fetch_financial_indicators(financial_query)),
            )
        except Exception as exc:
            self._record_provider_failure(provider.source_code, idempotency_key, type(exc).__name__)
            raise FinancialImportError("Provider fetch failed; no business rows written") from exc
        return self.import_batch(
            batch, source_code=provider.source_code, idempotency_key=idempotency_key
        )

    def _record_provider_failure(
        self, source_code: str, idempotency_key: str, error_type: str
    ) -> None:
        with self._session_provider() as session, session.begin():
            sources = DataSourceRepository(session)
            source = sources.get_by_code(source_code)
            if source is None:
                source = sources.add(
                    DataSource(code=source_code, name=source_code, provider_type="provider")
                )
            ImportJobRepository(session).add(
                ImportJob(
                    data_source_id=source.id,
                    idempotency_key=idempotency_key,
                    job_type=ImportJobType.FINANCIAL_DATA_BATCH,
                    status=ImportJobStatus.FAILED,
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    rows_received=0,
                    error_message=f"Provider fetch failed: {error_type}",
                )
            )

    def import_batch(
        self,
        batch: FinancialDataBatch,
        *,
        source_code: str,
        idempotency_key: str,
    ) -> int:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency_key must be 1-128 characters")
        report = validate_financial_batch(batch, source_code)
        received = report.checked_rows

        with self._session_provider() as session, session.begin():
            jobs = ImportJobRepository(session)
            if jobs.get_by_idempotency_key(idempotency_key) is not None:
                raise FinancialImportError("idempotency_key already exists")
            sources = DataSourceRepository(session)
            source = sources.get_by_code(source_code)
            if source is None:
                source = sources.add(
                    DataSource(code=source_code, name=source_code, provider_type="provider")
                )
            job = jobs.add(
                ImportJob(
                    data_source_id=source.id,
                    idempotency_key=idempotency_key,
                    job_type=ImportJobType.FINANCIAL_DATA_BATCH,
                    status=ImportJobStatus.RUNNING,
                    started_at=datetime.now(UTC),
                    rows_received=received,
                )
            )
            job_id = job.id

        if not report.is_valid:
            self._mark_failed(job_id, f"Quality validation failed: {report.error_count} errors")
            raise FinancialImportError(f"Quality validation failed: {report.error_count} errors")

        try:
            with self._session_provider() as session, session.begin():
                inserted, updated = self._upsert_rows(session, batch, source_code)
                completed_job = ImportJobRepository(session).get(job_id)
                if completed_job is None:
                    raise FinancialImportError("Import job disappeared")
                completed_job.status = ImportJobStatus.SUCCEEDED
                completed_job.rows_inserted = inserted
                completed_job.rows_updated = updated
                completed_job.finished_at = datetime.now(UTC)
        except Exception as exc:
            self._mark_failed(job_id, f"Import failed: {type(exc).__name__}")
            raise FinancialImportError("Financial batch rolled back") from exc
        return job_id

    def _mark_failed(self, job_id: int, message: str) -> None:
        with self._session_provider() as session, session.begin():
            job = ImportJobRepository(session).get(job_id)
            if job is None:
                raise FinancialImportError("Import job disappeared")
            job.status = ImportJobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_message = message

    @staticmethod
    def _update_fields(entity: object, values: dict[str, object]) -> bool:
        changed = False
        for field, value in values.items():
            if getattr(entity, field) != value:
                setattr(entity, field, value)
                changed = True
        return changed

    @classmethod
    def _upsert_rows(
        cls, session: Session, batch: FinancialDataBatch, source_code: str
    ) -> tuple[int, int]:
        companies = CompanyRepository(session)
        securities = SecurityRepository(session)
        sources = DataSourceRepository(session)
        source = sources.get_by_code(source_code)
        if source is None:
            raise FinancialImportError("Data source disappeared")

        inserted = 0
        updated = 0
        for company_record in batch.companies:
            values: dict[str, object] = {
                "legal_name": company_record.legal_name,
                "short_name": company_record.short_name,
                "unified_social_credit_code": company_record.unified_social_credit_code,
                "industry": company_record.industry,
                "country": company_record.country,
                "established_date": company_record.established_date,
                "status": company_record.status,
            }
            company = companies.get_by_code(company_record.company_code)
            if company is None:
                companies.add(Company(company_code=company_record.company_code, **values))
                inserted += 1
            elif cls._update_fields(company, values):
                updated += 1

        for security_record in batch.securities:
            company = companies.get_by_code(security_record.company_code)
            if company is None:
                raise FinancialImportError(f"Unknown company: {security_record.company_code}")
            values = {
                "company_id": company.id,
                "name": security_record.name,
                "security_type": security_record.security_type,
                "currency": security_record.currency,
                "listing_date": security_record.listing_date,
                "delisting_date": security_record.delisting_date,
                "is_active": security_record.is_active,
            }
            security = securities.get_by_symbol(security_record.exchange, security_record.ticker)
            if security is None:
                securities.add(
                    Security(
                        exchange=security_record.exchange,
                        ticker=security_record.ticker,
                        **values,
                    )
                )
                inserted += 1
            elif cls._update_fields(security, values):
                updated += 1

        prices = MarketPriceRepository(session)
        for price_record in batch.market_prices:
            security = securities.get_by_symbol(price_record.exchange, price_record.ticker)
            if security is None:
                raise FinancialImportError(
                    f"Unknown security: {price_record.exchange}/{price_record.ticker}"
                )
            values = {
                "open_price": price_record.open_price,
                "high_price": price_record.high_price,
                "low_price": price_record.low_price,
                "close_price": price_record.close_price,
                "volume": price_record.volume,
                "amount": price_record.amount,
            }
            price = prices.get_by_business_key(
                security.id, price_record.trade_date, price_record.adjustment_type,
                source.id, price_record.data_version,
            )
            if price is None:
                prices.add(
                    MarketPrice(
                        security_id=security.id,
                        data_source_id=source.id,
                        trade_date=price_record.trade_date,
                        adjustment_type=price_record.adjustment_type,
                        data_version=price_record.data_version,
                        **values,
                    )
                )
                inserted += 1
            elif cls._update_fields(price, values):
                price.ingested_at = datetime.now(UTC)
                updated += 1

        statements = FinancialStatementRepository(session)
        for statement_record in batch.financial_statements:
            company = companies.get_by_code(statement_record.company_code)
            if company is None:
                raise FinancialImportError(f"Unknown company: {statement_record.company_code}")
            values = {
                "item_name": statement_record.item_name,
                "value": statement_record.value,
                "currency": statement_record.currency,
                "unit": statement_record.unit,
            }
            statement = statements.get_by_business_key(
                company.id, statement_record.report_date, statement_record.period_type,
                statement_record.statement_type, statement_record.item_code,
                statement_record.consolidation_scope, source.id, statement_record.data_version,
            )
            if statement is None:
                statements.add(
                    FinancialStatement(
                        company_id=company.id,
                        data_source_id=source.id,
                        report_date=statement_record.report_date,
                        period_type=statement_record.period_type,
                        statement_type=statement_record.statement_type,
                        item_code=statement_record.item_code,
                        consolidation_scope=statement_record.consolidation_scope,
                        data_version=statement_record.data_version,
                        **values,
                    )
                )
                inserted += 1
            elif cls._update_fields(statement, values):
                statement.ingested_at = datetime.now(UTC)
                updated += 1

        indicators = FinancialIndicatorRepository(session)
        for indicator_record in batch.financial_indicators:
            company = companies.get_by_code(indicator_record.company_code)
            if company is None:
                raise FinancialImportError(f"Unknown company: {indicator_record.company_code}")
            values = {
                "indicator_name": indicator_record.indicator_name,
                "value": indicator_record.value,
                "unit": indicator_record.unit,
                "calculation_method": indicator_record.calculation_method,
            }
            indicator = indicators.get_by_business_key(
                company.id, indicator_record.report_date, indicator_record.period_type,
                indicator_record.indicator_code, source.id, indicator_record.data_version,
            )
            if indicator is None:
                indicators.add(
                    FinancialIndicator(
                        company_id=company.id,
                        data_source_id=source.id,
                        report_date=indicator_record.report_date,
                        period_type=indicator_record.period_type,
                        indicator_code=indicator_record.indicator_code,
                        data_version=indicator_record.data_version,
                        **values,
                    )
                )
                inserted += 1
            elif cls._update_fields(indicator, values):
                indicator.ingested_at = datetime.now(UTC)
                updated += 1
        return inserted, updated
