from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database.models import Document
from finsight.infrastructure.database.repositories.base import BaseRepository
from finsight.services.document_deduplication import ExistingDocument


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Document)

    def get_by_content_sha256(self, digest: str) -> ExistingDocument | None:
        document = self.session.scalar(
            select(Document).where(Document.content_sha256 == digest)
        )
        if document is None:
            return None
        return ExistingDocument(
            document_id=document.id,
            content_sha256=document.content_sha256,
            file_size_bytes=document.file_size_bytes,
            object_key=document.object_key,
        )
