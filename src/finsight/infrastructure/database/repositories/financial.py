from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database.models import FinancialIndicator, FinancialStatement
from finsight.infrastructure.database.models.enums import ReportingPeriodType, StatementType
from finsight.infrastructure.database.repositories.base import BaseRepository


class FinancialStatementRepository(BaseRepository[FinancialStatement]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, FinancialStatement)

    def get_by_business_key(
        self,
        company_id: int,
        report_date: date,
        period_type: ReportingPeriodType,
        statement_type: StatementType,
        item_code: str,
        consolidation_scope: str,
        data_source_id: int,
        data_version: int,
    ) -> FinancialStatement | None:
        statement = select(FinancialStatement).where(
            FinancialStatement.company_id == company_id,
            FinancialStatement.report_date == report_date,
            FinancialStatement.period_type == period_type,
            FinancialStatement.statement_type == statement_type,
            FinancialStatement.item_code == item_code,
            FinancialStatement.consolidation_scope == consolidation_scope,
            FinancialStatement.data_source_id == data_source_id,
            FinancialStatement.data_version == data_version,
        )
        return self.session.scalar(statement)

    def list_by_company(
        self,
        company_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period_type: ReportingPeriodType | None = None,
        statement_type: StatementType | None = None,
        item_codes: list[str] | None = None,
    ) -> list[FinancialStatement]:
        statement = select(FinancialStatement).where(
            FinancialStatement.company_id == company_id
        )
        if start_date:
            statement = statement.where(FinancialStatement.report_date >= start_date)
        if end_date:
            statement = statement.where(FinancialStatement.report_date <= end_date)
        if period_type:
            statement = statement.where(FinancialStatement.period_type == period_type)
        if statement_type:
            statement = statement.where(FinancialStatement.statement_type == statement_type)
        if item_codes:
            statement = statement.where(FinancialStatement.item_code.in_(item_codes))

        statement = statement.order_by(
            FinancialStatement.report_date,
            FinancialStatement.item_code,
        )
        return list(self.session.scalars(statement))


class FinancialIndicatorRepository(BaseRepository[FinancialIndicator]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, FinancialIndicator)

    def get_by_business_key(
        self,
        company_id: int,
        report_date: date,
        period_type: ReportingPeriodType,
        indicator_code: str,
        data_source_id: int,
        data_version: int,
    ) -> FinancialIndicator | None:
        statement = select(FinancialIndicator).where(
            FinancialIndicator.company_id == company_id,
            FinancialIndicator.report_date == report_date,
            FinancialIndicator.period_type == period_type,
            FinancialIndicator.indicator_code == indicator_code,
            FinancialIndicator.data_source_id == data_source_id,
            FinancialIndicator.data_version == data_version,
        )
        return self.session.scalar(statement)

    def list_by_company(
        self,
        company_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period_type: ReportingPeriodType | None = None,
        indicator_codes: list[str] | None = None,
    ) -> list[FinancialIndicator]:
        statement = select(FinancialIndicator).where(
            FinancialIndicator.company_id == company_id
        )
        if start_date:
            statement = statement.where(FinancialIndicator.report_date >= start_date)
        if end_date:
            statement = statement.where(FinancialIndicator.report_date <= end_date)
        if period_type:
            statement = statement.where(FinancialIndicator.period_type == period_type)
        if indicator_codes:
            statement = statement.where(FinancialIndicator.indicator_code.in_(indicator_codes))

        statement = statement.order_by(
            FinancialIndicator.report_date,
            FinancialIndicator.indicator_code,
        )
        return list(self.session.scalars(statement))
