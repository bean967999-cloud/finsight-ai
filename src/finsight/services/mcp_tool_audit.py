"""Minimal audit dependency shared by local financial-tool adapters."""

from typing import Protocol
from uuid import UUID


class ToolAudit(Protocol):
    def begin(
        self, request_id: UUID, *, action: str, method: str,
        route_pattern: str, target_id: str | None,
    ) -> None: ...

    def finish(
        self, request_id: UUID, *, status_code: int,
        actor_user_id: UUID | None = None, workspace_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> None: ...
