"""Authoritative resource ownership checks before document operations."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from finsight.infrastructure.database.models.knowledge_base import KnowledgeBase


class KnowledgeScopeService:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def workspace_for(self, knowledge_base_id: UUID) -> UUID | None:
        with self._session_factory() as session:
            base = session.get(KnowledgeBase, knowledge_base_id)
            return base.workspace_id if base is not None else None
