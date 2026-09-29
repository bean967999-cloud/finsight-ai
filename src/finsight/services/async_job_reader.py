"""Read the durable state of one logical background job."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from finsight.domain.async_job import AsyncJobSnapshot
from finsight.infrastructure.database.models import AsyncJob
from finsight.services.async_job_submission import AsyncJobSubmissionService


class AsyncJobReader:
    def __init__(self, sessions: Callable[[], Session]) -> None:
        self._sessions = sessions

    def get(self, job_id: int) -> AsyncJobSnapshot | None:
        with self._sessions() as session:
            job = session.get(AsyncJob, job_id)
            return AsyncJobSubmissionService._snapshot(job) if job is not None else None
