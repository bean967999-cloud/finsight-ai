from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database import Base


class BaseRepository[ModelT: Base]:
    """Shared persistence operations without owning the transaction boundary."""

    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def get(self, entity_id: int) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelT]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

        statement = select(self.model).offset(offset).limit(limit)
        return list(self.session.scalars(statement))
