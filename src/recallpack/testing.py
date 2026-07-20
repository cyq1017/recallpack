from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from recallpack.observe import ObserveRequest


@dataclass
class _EventState:
    payload_hash: str
    processing_state: str
    attempt_count: int


class BlockingMemoryDecider:
    """Fake decider that keeps events pending for idempotency tests."""


class InMemoryStore:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str, str], _EventState] = {}
        self._next_sequence: dict[tuple[str, str], int] = {}

    def claim_event(self, request: ObserveRequest) -> str:
        key = (request.project_id, request.session_id, request.event_id)
        payload_hash = _payload_hash(request)
        existing = self._events.get(key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                return "idempotency_conflict"
            if existing.processing_state == "pending":
                return "pending"
            return existing.processing_state

        expected = self._next_sequence.get((request.project_id, request.session_id), 1)
        if request.sequence_no != expected:
            return "out_of_order"

        self._events[key] = _EventState(
            payload_hash=payload_hash,
            processing_state="pending",
            attempt_count=1,
        )
        return "pending"

    def attempt_count(self, project_id: str, session_id: str, event_id: str) -> int:
        return self._events[(project_id, session_id, event_id)].attempt_count

    def has_event(self, project_id: str, session_id: str, event_id: str) -> bool:
        return (project_id, session_id, event_id) in self._events


def _payload_hash(request: ObserveRequest) -> str:
    payload = {
        "actor": request.actor,
        "kind": request.kind,
        "observed_at": request.observed_at,
        "sequence_no": request.sequence_no,
        "text": request.text,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
