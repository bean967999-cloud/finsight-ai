"""Contracts for independent query-passage relevance scoring."""

from typing import Protocol


class Reranker(Protocol):
    """Scores query-passage pairs independently from first-stage retrieval."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def score(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]: ...
