from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRef:
    session_id: str
    event_id: str

    def to_dict(self) -> dict[str, str]:
        return {"session_id": self.session_id, "event_id": self.event_id}


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    project_id: str
    type: str
    subject: str
    text: str
    scope_level: str
    component: str | None
    source_actor: str
    source_ref: SourceRef
    source_project_event_seq: int
    embedding: list[float]
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    embedding_document_hash: str | None = None
    record_schema_version: int | None = None
    source_event_internal_id: str | None = None
