from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database.models import Company, DataSource, Security
from finsight.infrastructure.database.repositories.base import BaseRepository


class CompanyRepository(BaseRepository[Company]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Company)

    def get_by_code(self, company_code: str) -> Company | None:
        statement = select(Company).where(Company.company_code == company_code)
        return self.session.scalar(statement)


class SecurityRepository(BaseRepository[Security]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Security)

    def get_by_symbol(self, exchange: str, ticker: str) -> Security | None:
        statement = select(Security).where(
            Security.exchange == exchange,
            Security.ticker == ticker,
        )
        return self.session.scalar(statement)

    def list_by_company(self, company_id: int) -> list[Security]:
        statement = (
            select(Security)
            .where(Security.company_id == company_id)
            .order_by(Security.exchange, Security.ticker)
        )
        return list(self.session.scalars(statement))


class DataSourceRepository(BaseRepository[DataSource]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DataSource)

    def get_by_code(self, code: str) -> DataSource | None:
        statement = select(DataSource).where(DataSource.code == code)
        return self.session.scalar(statement)
