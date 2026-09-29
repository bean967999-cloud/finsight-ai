from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database.models import ImportJob
from finsight.infrastructure.database.models.enums import ImportJobStatus
from finsight.infrastructure.database.repositories.base import BaseRepository


class ImportJobRepository(BaseRepository[ImportJob]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ImportJob)

    def get_by_idempotency_key(self, idempotency_key: str) -> ImportJob | None:
        statement = select(ImportJob).where(ImportJob.idempotency_key == idempotency_key)
        return self.session.scalar(statement)

    def list_by_status(self, status: ImportJobStatus, *, limit: int = 100) -> list[ImportJob]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

        statement = (
            select(ImportJob)
            .where(ImportJob.status == status)
            .order_by(ImportJob.created_at)
            .limit(limit)
        )
        return list(self.session.scalars(statement))
