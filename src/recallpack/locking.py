from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProjectTurn:
    project_id: str
    project_event_seq: int
    attempt_no: int
    lease_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("project_id_required")
        if self.project_event_seq < 1:
            raise ValueError("project_event_seq_must_be_positive")
        if self.attempt_no < 1:
            raise ValueError("attempt_no_must_be_positive")
        if not self.lease_token:
            raise ValueError("lease_token_required")


class ProjectTurnTicket:
    def __init__(self, registry: ProjectTurnstileRegistry, turn: ProjectTurn) -> None:
        self._registry = registry
        self.turn = turn
        self._state = "registered"

    def __enter__(self) -> ProjectTurn:
        self._registry._enter(self)
        return self.turn

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._registry._release(self)

    def cancel(self) -> None:
        self._registry._cancel(self)


class ProjectTurnstileRegistry:
    """Orders registered lifecycle work while allowing projects to run independently."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: dict[str, list[ProjectTurnTicket]] = {}
        self._active: dict[str, ProjectTurnTicket] = {}

    def register(self, turn: ProjectTurn) -> ProjectTurnTicket:
        ticket = ProjectTurnTicket(self, turn)
        with self._condition:
            project_tickets = self._pending.setdefault(turn.project_id, [])
            if any(_same_attempt(item.turn, turn) for item in project_tickets):
                raise ValueError("project_turn_already_registered")
            active = self._active.get(turn.project_id)
            if active is not None and _same_attempt(active.turn, turn):
                raise ValueError("project_turn_already_registered")
            project_tickets.append(ticket)
            project_tickets.sort(key=_ticket_order)
            self._condition.notify_all()
        return ticket

    def registered_count(self, project_id: str) -> int:
        with self._condition:
            return len(self._pending.get(project_id, ())) + int(project_id in self._active)

    def _enter(self, ticket: ProjectTurnTicket) -> None:
        with self._condition:
            if ticket._state != "registered":
                raise RuntimeError(f"project_turn_not_enterable: state={ticket._state}")
            project_id = ticket.turn.project_id
            try:
                self._condition.wait_for(lambda: self._can_enter(ticket))
            except BaseException:
                if ticket._state == "registered":
                    self._remove_pending(ticket)
                    ticket._state = "cancelled"
                    self._condition.notify_all()
                raise
            if ticket._state == "cancelled":
                raise RuntimeError("project_turn_cancelled")
            pending = self._pending[project_id]
            pending.remove(ticket)
            if not pending:
                del self._pending[project_id]
            self._active[project_id] = ticket
            ticket._state = "active"

    def _can_enter(self, ticket: ProjectTurnTicket) -> bool:
        if ticket._state != "registered":
            return True
        project_id = ticket.turn.project_id
        pending = self._pending.get(project_id, ())
        return (
            project_id not in self._active
            and bool(pending)
            and pending[0] is ticket
        )

    def _release(self, ticket: ProjectTurnTicket) -> None:
        with self._condition:
            if ticket._state != "active":
                raise RuntimeError(f"project_turn_not_active: state={ticket._state}")
            project_id = ticket.turn.project_id
            if self._active.get(project_id) is not ticket:
                raise RuntimeError("project_turn_ownership_lost")
            del self._active[project_id]
            ticket._state = "released"
            self._condition.notify_all()

    def _cancel(self, ticket: ProjectTurnTicket) -> None:
        with self._condition:
            if ticket._state != "registered":
                raise RuntimeError(f"project_turn_not_cancellable: state={ticket._state}")
            self._remove_pending(ticket)
            ticket._state = "cancelled"
            self._condition.notify_all()

    def _remove_pending(self, ticket: ProjectTurnTicket) -> None:
        pending = self._pending[ticket.turn.project_id]
        pending.remove(ticket)
        if not pending:
            del self._pending[ticket.turn.project_id]


def _ticket_order(ticket: ProjectTurnTicket) -> tuple[int, int]:
    return ticket.turn.project_event_seq, ticket.turn.attempt_no


def _same_attempt(left: ProjectTurn, right: ProjectTurn) -> bool:
    return (
        left.project_event_seq == right.project_event_seq
        and left.attempt_no == right.attempt_no
    )
