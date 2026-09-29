from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database.models import DocumentIngestionJob
from finsight.infrastructure.database.repositories.base import BaseRepository


class DocumentIngestionJobRepository(BaseRepository[DocumentIngestionJob]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DocumentIngestionJob)

    def get_by_idempotency_key(self, key: str) -> DocumentIngestionJob | None:
        return self.session.scalar(
            select(DocumentIngestionJob).where(DocumentIngestionJob.idempotency_key == key)
        )
