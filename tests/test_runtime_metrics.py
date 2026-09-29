"""Day16 Step5: runtime denominators and absent-data boundaries."""

from uuid import UUID

import pytest

from finsight.services.runtime_metrics import aggregate_runtime_metrics
from finsight.services.structured_trace import TraceEvent, TraceKind
from finsight.workers.report_runtime_metrics import report_file


def event(number: int, kind: TraceKind, **fields: object) -> TraceEvent:
    return TraceEvent.model_validate({"request_id": UUID(int=number), "kind": kind, **fields})


def test_runtime_report_separates_http_tool_and_research_denominators() -> None:
    events = [
        event(1, TraceKind.RESEARCH_PLAN, intent="risk_analysis"),
        event(1, TraceKind.TOOL_COMPLETED, tool="risk_calculation", tool_status="succeeded", duration_ms=5),
        event(1, TraceKind.RESEARCH_COMPLETED, answer_status="answered", review_pending=False),
        event(1, TraceKind.HTTP_COMPLETED, status_code=200, duration_ms=20),
        event(2, TraceKind.TOOL_COMPLETED, tool="document_search", tool_status="unavailable", duration_ms=7),
        event(2, TraceKind.RESEARCH_COMPLETED, answer_status="insufficient_evidence", review_pending=True),
        event(2, TraceKind.HTTP_COMPLETED, status_code=200, duration_ms=80),
        event(3, TraceKind.HTTP_COMPLETED, status_code=401, duration_ms=10),
        event(4, TraceKind.HTTP_COMPLETED, status_code=500, duration_ms=90),
    ]
    report = aggregate_runtime_metrics(events)
    assert (report.http_requests, report.http_2xx, report.http_4xx, report.http_5xx) == (4, 2, 1, 1)
    assert report.http_5xx_rate == 0.25
    assert report.http_duration_p50_ms == 20
    assert report.http_duration_p95_ms == 90
    assert (report.research_completed, report.research_answered, report.review_pending) == (2, 1, 1)
    assert report.research_insufficient_evidence == 1
    assert (report.tool_executions, report.tool_unavailable, report.tool_failed) == (2, 1, 0)
    assert report.token_usage is None and report.estimated_cost is None
    assert report.incomplete_request_ids == 0


def test_empty_and_partial_traces_do_not_invent_success_or_latency() -> None:
    empty = aggregate_runtime_metrics(())
    assert empty.http_requests == 0 and empty.http_5xx_rate is None
    assert empty.http_duration_p95_ms is None
    partial = aggregate_runtime_metrics((event(1, TraceKind.RESEARCH_PLAN),))
    assert partial.incomplete_request_ids == 1
    assert partial.http_requests == 0


def test_duplicate_or_incomplete_completion_is_rejected() -> None:
    completed = event(1, TraceKind.HTTP_COMPLETED, status_code=200, duration_ms=1)
    with pytest.raises(ValueError, match="duplicate HTTP"):
        aggregate_runtime_metrics((completed, completed))
    with pytest.raises(ValueError, match="lacks status"):
        aggregate_runtime_metrics((event(1, TraceKind.HTTP_COMPLETED),))
    with pytest.raises(ValueError, match="lacks tool"):
        aggregate_runtime_metrics((event(1, TraceKind.TOOL_COMPLETED),))


def test_jsonl_report_rejects_raw_or_malformed_lines_without_echoing_content(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text(
        event(1, TraceKind.HTTP_COMPLETED, status_code=200, duration_ms=3).model_dump_json()
        + "\n", encoding="utf-8"
    )
    assert report_file(path).http_requests == 1
    path.write_text('{"raw_query":"PRIVATE_FINANCIAL_CONTENT"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1") as error:
        report_file(path)
    assert "PRIVATE_FINANCIAL_CONTENT" not in str(error.value)
