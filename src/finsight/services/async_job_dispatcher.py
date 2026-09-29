"""Publish durable pending jobs; a duplicate message is safe to claim later."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from finsight.domain.async_job import AsyncJobStatus, assert_job_transition
from finsight.infrastructure.database.models import AsyncJob
from finsight.services.async_job_queue import AsyncJobQueue
from finsight.services.async_job_submission import AsyncJobSubmissionService

SessionProvider = Callable[[], Session]


class AsyncJobDispatcher:
    def __init__(self, sessions: SessionProvider, queue: AsyncJobQueue) -> None:
        self._sessions = sessions
        self._queue = queue

    def dispatch_pending(self, *, limit: int = 50, now: datetime | None = None) -> tuple[int, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("dispatch limit must be between 1 and 500")
        published: list[int] = []
        due = now or datetime.now(UTC)
        with self._sessions() as session, session.begin():
            jobs = list(
                session.scalars(
                    select(AsyncJob)
                    .where(
                        or_(
                            AsyncJob.status == AsyncJobStatus.PENDING,
                            and_(
                                AsyncJob.status == AsyncJobStatus.RETRY_WAIT,
                                AsyncJob.next_retry_at <= due,
                            ),
                        )
                    )
                    .order_by(AsyncJob.created_at, AsyncJob.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for job in jobs:
                assert_job_transition(
                    AsyncJobSubmissionService._snapshot(job),
                    AsyncJobStatus.QUEUED,
                )
                self._queue.publish(job.id, job.request_sha256)
                job.status = AsyncJobStatus.QUEUED
                job.next_retry_at = None
                job.error_code = None
                published.append(job.id)
        return tuple(published)
