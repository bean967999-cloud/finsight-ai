"""Helpers for creating traceable structured query plans."""

from hashlib import sha256

from finsight.domain.query_plan import StructuredQueryPlan


def query_digest(query: str) -> str:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    return sha256(query.encode("utf-8")).hexdigest()


def build_query_plan(query: str, **plan_fields: object) -> StructuredQueryPlan:
    """Attach a normalized query digest and validate the complete plan."""
    return StructuredQueryPlan.model_validate({
        "query_sha256": query_digest(query),
        **plan_fields,
    })
