"""Opt-in real PostgreSQL checkpointer, isolated from application tables."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from psycopg import Connection
from psycopg.rows import dict_row
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from finsight.agents.checkpoints import (
    ResearchCheckpointService,
    ReviewConflictError,
    make_research_saver,
)
from finsight.agents.snapshot import ResearchPhase
from finsight.core.config import get_settings
from finsight.domain.research_review import ReviewChoice, ReviewDecision

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 to run against local PostgreSQL",
)


def test_postgres_checkpoint_survives_new_connection_and_graph_instance() -> None:
    schema = f"finsight_checkpoint_{uuid4().hex[:12]}"
    database_url = get_settings().database_url
    admin = create_engine(database_url)
    psycopg_url = make_url(database_url).set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True

        def connect() -> Connection:
            return Connection.connect(
                psycopg_url,
                options=f"-csearch_path={schema}",
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
            )

        with connect() as connection:
            saver = make_research_saver(connection)
            saver.setup()
            first = ResearchCheckpointService(saver, database_url=database_url)
            run = first.start(
                {"query": "计算价格波动率", "prices": [100, 102, 101, 105]}
            )
            assert run.snapshot.phase == ResearchPhase.FINISHED
            assert run.snapshot.risk_metrics is not None
            pending = first.start(
                {
                    "query": "计算价格波动率",
                    "prices": [100, 102, 101, 105],
                    "release_requested": True,
                }
            )
            assert pending.snapshot.phase == ResearchPhase.AWAITING_REVIEW
            concurrent_pending = first.start(
                {
                    "query": "计算价格波动率",
                    "prices": [100, 102, 101, 105],
                    "release_requested": True,
                }
            )

        # A new connection and graph instance must load the same durable thread.
        with connect() as connection:
            rebuilt = ResearchCheckpointService(
                make_research_saver(connection), database_url=database_url
            )
            loaded = rebuilt.get(run.thread_id)
            assert loaded == run.snapshot
            assert loaded is not None
            assert loaded.output_summaries
            assert loaded.answer_result is not None
            restored_pending = rebuilt.get(pending.thread_id)
            assert restored_pending == pending.snapshot
            completed = rebuilt.resume(
                pending.thread_id,
                ReviewDecision(choice=ReviewChoice.REJECTED, note="样本来源待复核"),
            )
            assert completed.snapshot.phase == ResearchPhase.FINISHED
            assert completed.snapshot.review_outcome == {
                "choice": "rejected", "note": "样本来源待复核"
            }

        def decide_once() -> str:
            with connect() as worker_connection:
                worker = ResearchCheckpointService(
                    make_research_saver(worker_connection), database_url=database_url
                )
                try:
                    worker.resume(
                        concurrent_pending.thread_id,
                        ReviewDecision(choice=ReviewChoice.CONFIRMED),
                    )
                except ReviewConflictError:
                    return "conflict"
                return "completed"

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: decide_once(), range(2))) == [
                "completed", "conflict"
            ]
    finally:
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
