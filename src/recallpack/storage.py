from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from recallpack.memory import MemoryRecord, SourceRef
from recallpack.observe import ObserveRequest


class MigrationError(RuntimeError):
    """Raised when the persistent schema cannot be upgraded safely."""


class IntegrityAuditError(RuntimeError):
    """Raised when persisted V4 state violates a startup invariant."""


_BASE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS session_cursors (
        project_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        next_expected_sequence_no INTEGER NOT NULL,
        PRIMARY KEY (project_id, session_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_events (
        internal_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        external_event_id TEXT NOT NULL,
        sequence_no INTEGER NOT NULL,
        project_event_seq INTEGER NOT NULL,
        actor TEXT NOT NULL,
        kind TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        text TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        processing_state TEXT NOT NULL,
        failure_kind TEXT,
        attempt_count INTEGER NOT NULL,
        lease_token TEXT,
        lease_expires_at INTEGER,
        last_error TEXT,
        final_result_json TEXT,
        UNIQUE (project_id, session_id, external_event_id),
        UNIQUE (project_id, session_id, sequence_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        type TEXT NOT NULL,
        subject TEXT NOT NULL,
        text TEXT NOT NULL,
        scope_level TEXT NOT NULL,
        component TEXT,
        source_actor TEXT NOT NULL,
        source_session_id TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        source_event_internal_id TEXT NOT NULL,
        source_project_event_seq INTEGER NOT NULL,
        embedding_json TEXT NOT NULL,
        FOREIGN KEY (source_event_internal_id)
            REFERENCES session_events(internal_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memories_project_scope_component
    ON memories(project_id, scope_level, component)
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_relations (
        prior_memory_id TEXT NOT NULL,
        successor_memory_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        source_event_internal_id TEXT NOT NULL,
        UNIQUE (prior_memory_id),
        FOREIGN KEY (prior_memory_id) REFERENCES memories(id),
        FOREIGN KEY (successor_memory_id) REFERENCES memories(id),
        FOREIGN KEY (source_event_internal_id)
            REFERENCES session_events(internal_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_relations_successor
    ON memory_relations(successor_memory_id)
    """,
)

_OBSERVE_RUNS_STATEMENT = """
CREATE TABLE IF NOT EXISTS observe_runs (
    id TEXT PRIMARY KEY,
    event_internal_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    state TEXT NOT NULL,
    provider_mode TEXT NOT NULL,
    model_calls_json TEXT NOT NULL,
    embedding_calls_json TEXT NOT NULL,
    tool_arguments_json TEXT,
    validation_json TEXT NOT NULL,
    failure_code TEXT,
    error_detail TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    UNIQUE (event_internal_id, attempt_no),
    FOREIGN KEY (event_internal_id) REFERENCES session_events(internal_id)
)
"""

_MIGRATION_DEFINITIONS = (
    (1, "v3_baseline", "\n".join(_BASE_SCHEMA_STATEMENTS)),
    (
        2,
        "v4_nullable_metadata",
        "session_events.result_schema_version INTEGER;"
        "memories.embedding_model TEXT;"
        "memories.embedding_dimension INTEGER;"
        "memories.embedding_document_hash TEXT;"
        "memories.record_schema_version INTEGER",
    ),
    (3, "v4_observe_runs", _OBSERVE_RUNS_STATEMENT),
    (
        4,
        "v4_unique_project_event_seq",
        "CREATE UNIQUE INDEX ux_session_events_project_event_seq "
        "ON session_events(project_id, project_event_seq)",
    ),
)


@dataclass(frozen=True)
class ClaimResult:
    status: str
    status_code: int
    error: str | None = None
    event_internal_id: str | None = None
    project_event_seq: int | None = None
    lease_token: str | None = None
    attempt_no: int | None = None
    final_result: dict[str, Any] | None = None
    run_id: str | None = None
    provider_mode: str | None = None
    repaired: bool = False
    request_id_present: bool = False
    owns_attempt: bool = False


class SqliteEventStore:
    def __init__(self, db_path: str | Path, lease_seconds: int = 30) -> None:
        self._db_path = str(db_path)
        self._lease_seconds = lease_seconds
        self._init_db()

    def claim_event(
        self,
        request: ObserveRequest,
        now: int,
        provider_mode: str = "fake",
    ) -> ClaimResult:
        if provider_mode not in {"fake", "live"}:
            raise ValueError("invalid_provider_mode")
        observed_at = _canonical_utc_timestamp(request.observed_at)
        if observed_at is None:
            raise ValueError("invalid_timestamp")
        payload_hash = _payload_hash(request)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = self._event_by_key(conn, request)
            if existing is not None:
                return self._claim_existing(
                    conn,
                    existing,
                    payload_hash,
                    now,
                    provider_mode,
                )

            cursor = self._cursor_for(conn, request.project_id, request.session_id)
            expected = int(cursor["next_expected_sequence_no"])
            blocking = self._blocking_event(conn, request.project_id, request.session_id)
            if request.sequence_no < expected:
                conn.commit()
                return ClaimResult(status="rejected", status_code=409, error="sequence_conflict")
            if blocking is not None:
                conn.commit()
                return ClaimResult(
                    status="rejected",
                    status_code=409,
                    error="prior_event_incomplete",
                )
            if request.sequence_no > expected:
                conn.commit()
                return ClaimResult(status="rejected", status_code=409, error="out_of_order")

            event_internal_id = _new_id("evt")
            lease_token = _new_id("lease")
            run_id = _new_id("run")
            project_event_seq = self._next_project_event_seq(conn, request.project_id)
            conn.execute(
                """
                INSERT INTO session_events (
                    internal_id, project_id, session_id, external_event_id,
                    sequence_no, project_event_seq, actor, kind, observed_at, text,
                    payload_hash, processing_state, failure_kind, attempt_count,
                    lease_token, lease_expires_at, last_error, final_result_json,
                    result_schema_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, 1, ?, ?, NULL, NULL, 4)
                """,
                (
                    event_internal_id,
                    request.project_id,
                    request.session_id,
                    request.event_id,
                    request.sequence_no,
                    project_event_seq,
                    request.actor,
                    request.kind,
                    observed_at,
                    request.text,
                    payload_hash,
                    lease_token,
                    now + self._lease_seconds,
                ),
            )
            self._insert_running_run(
                conn,
                run_id=run_id,
                event_internal_id=event_internal_id,
                attempt_no=1,
                provider_mode=provider_mode,
            )
            conn.commit()
            return ClaimResult(
                status="pending",
                status_code=202,
                event_internal_id=event_internal_id,
                project_event_seq=project_event_seq,
                lease_token=lease_token,
                attempt_no=1,
                run_id=run_id,
                provider_mode=provider_mode,
                owns_attempt=True,
            )

    def complete_event(
        self,
        event_internal_id: str | None,
        lease_token: str | None,
        attempt_no: int | None,
        final_result: dict[str, Any],
        run_evidence: dict[str, Any] | None = None,
    ) -> bool:
        if event_internal_id is None or lease_token is None or attempt_no is None:
            return False
        final_result_json = json.dumps(final_result, ensure_ascii=False, sort_keys=True)
        if not _valid_v4_final_result(final_result_json):
            return False
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            event = self._pending_event_for_attempt(
                conn, event_internal_id, lease_token, attempt_no
            )
            if event is None:
                conn.rollback()
                return False
            if not self._complete_pending_event(
                conn,
                event,
                event_internal_id,
                lease_token,
                attempt_no,
                final_result,
                run_evidence=run_evidence,
            ):
                conn.rollback()
                return False
            conn.commit()
            return True

    def complete_observe_operation(
        self,
        event_internal_id: str | None,
        lease_token: str | None,
        attempt_no: int | None,
        final_result: dict[str, Any],
        memory: dict[str, object],
        supersedes_memory_ids: list[str],
        embedding: dict[str, object],
        run_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if event_internal_id is None or lease_token is None or attempt_no is None:
            return None
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            event = self._pending_event_for_attempt(
                conn, event_internal_id, lease_token, attempt_no
            )
            if event is None:
                conn.rollback()
                return None

            stale_memory = self._newer_active_lifecycle_memory(
                conn,
                project_id=str(event["project_id"]),
                project_event_seq=int(event["project_event_seq"]),
                memory=memory,
            )
            if stale_memory is not None:
                stale_result = _terminal_no_op_result("stale_project_event")
                if not self._complete_pending_event(
                    conn,
                    event,
                    event_internal_id,
                    lease_token,
                    attempt_no,
                    stale_result,
                    run_evidence=run_evidence,
                ):
                    conn.rollback()
                    return None
                conn.commit()
                return stale_result

            relation_error = self._supersession_validation_error(
                conn,
                event,
                memory,
                supersedes_memory_ids,
            )
            if relation_error is not None:
                rejected_result = _terminal_no_op_result(relation_error)
                if not self._complete_pending_event(
                    conn,
                    event,
                    event_internal_id,
                    lease_token,
                    attempt_no,
                    rejected_result,
                    run_evidence=run_evidence,
                ):
                    conn.rollback()
                    return None
                conn.commit()
                return rejected_result

            try:
                memory_id = self._insert_memory(conn, event, memory, embedding)
                self._insert_supersession_edges(
                    conn, supersedes_memory_ids, memory_id, event["internal_id"]
                )
                final_result = dict(final_result)
                final_result["memory"] = _memory_summary(
                    memory_id=memory_id,
                    memory=memory,
                    session_id=str(event["session_id"]),
                    event_id=str(event["external_event_id"]),
                )
                final_result["superseded_memory_ids"] = list(
                    supersedes_memory_ids
                )
                committed = self._complete_pending_event(
                    conn,
                    event,
                    event_internal_id,
                    lease_token,
                    attempt_no,
                    final_result,
                    run_evidence=run_evidence,
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return None
            if not committed:
                conn.rollback()
                return None
            conn.commit()
            return final_result

    def owns_event_attempt(
        self,
        event_internal_id: str | None,
        lease_token: str | None,
        attempt_no: int | None,
    ) -> bool:
        if event_internal_id is None or lease_token is None or attempt_no is None:
            return False
        with self._connect() as conn:
            return (
                self._pending_event_for_attempt(
                    conn,
                    event_internal_id,
                    lease_token,
                    attempt_no,
                )
                is not None
            )

    def has_newer_active_lifecycle_memory(
        self,
        project_id: str,
        project_event_seq: int,
        memory: dict[str, object],
    ) -> bool:
        with self._connect() as conn:
            return (
                self._newer_active_lifecycle_memory(
                    conn,
                    project_id=project_id,
                    project_event_seq=project_event_seq,
                    memory=memory,
                )
                is not None
            )

    def _pending_event_for_attempt(
        self,
        conn: sqlite3.Connection,
        event_internal_id: str,
        lease_token: str,
        attempt_no: int,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM session_events
            WHERE internal_id = ?
              AND processing_state = 'pending'
              AND lease_token = ?
              AND attempt_count = ?
            """,
            (event_internal_id, lease_token, attempt_no),
        ).fetchone()

    def _insert_running_run(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        event_internal_id: str,
        attempt_no: int,
        provider_mode: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO observe_runs (
                id, event_internal_id, attempt_no, state, provider_mode,
                model_calls_json, embedding_calls_json, tool_arguments_json,
                validation_json, failure_code, error_detail, started_at,
                finished_at, duration_ms
            ) VALUES (?, ?, ?, 'running', ?, '[]', '[]', NULL, '[]', NULL, NULL, ?, NULL, NULL)
            """,
            (
                run_id,
                event_internal_id,
                attempt_no,
                provider_mode,
                _utc_now(),
            ),
        )

    def _finish_run(
        self,
        conn: sqlite3.Connection,
        *,
        event_internal_id: str,
        attempt_no: int,
        state: str,
        run_evidence: dict[str, Any] | None = None,
        failure_code: str | None = None,
        error_detail: str | None = None,
    ) -> bool:
        evidence = _normalized_run_evidence(run_evidence)
        finished_at = _utc_now()
        row = conn.execute(
            """
            SELECT started_at
            FROM observe_runs
            WHERE event_internal_id = ? AND attempt_no = ? AND state = 'running'
            """,
            (event_internal_id, attempt_no),
        ).fetchone()
        if row is None:
            return False
        updated = conn.execute(
            """
            UPDATE observe_runs
            SET state = ?,
                model_calls_json = ?,
                embedding_calls_json = ?,
                tool_arguments_json = ?,
                validation_json = ?,
                failure_code = ?,
                error_detail = ?,
                finished_at = ?,
                duration_ms = ?
            WHERE event_internal_id = ?
              AND attempt_no = ?
              AND state = 'running'
            """,
            (
                state,
                json.dumps(evidence["model_calls"], ensure_ascii=False, sort_keys=True),
                json.dumps(
                    evidence["embedding_calls"], ensure_ascii=False, sort_keys=True
                ),
                (
                    json.dumps(
                        evidence["tool_arguments"],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if evidence["tool_arguments"] is not None
                    else None
                ),
                json.dumps(evidence["validation"], ensure_ascii=False, sort_keys=True),
                failure_code,
                _bounded_detail(error_detail),
                finished_at,
                _duration_ms(str(row["started_at"]), finished_at),
                event_internal_id,
                attempt_no,
            ),
        )
        return updated.rowcount == 1

    def _insert_memory(
        self,
        conn: sqlite3.Connection,
        event: sqlite3.Row,
        memory: dict[str, object],
        embedding: dict[str, object],
    ) -> str:
        if not _valid_embedding_payload(memory, embedding):
            raise ValueError("invalid_document_embedding")
        memory_id = _new_id("mem")
        conn.execute(
            """
            INSERT INTO memories (
                id, project_id, type, subject, text, scope_level,
                component, source_actor, source_session_id,
                source_event_id, source_event_internal_id,
                source_project_event_seq, embedding_json,
                embedding_model, embedding_dimension,
                embedding_document_hash, record_schema_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                event["project_id"],
                memory["type"],
                memory["subject"],
                memory["text"],
                memory["scope_level"],
                memory["component"],
                event["actor"],
                event["session_id"],
                event["external_event_id"],
                event["internal_id"],
                int(event["project_event_seq"]),
                json.dumps(
                    embedding["vector"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                embedding["model"],
                embedding["dimension"],
                embedding["document_hash"],
                embedding["record_schema_version"],
            ),
        )
        return memory_id

    def _newer_active_lifecycle_memory(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        project_event_seq: int,
        memory: dict[str, object],
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT memories.id
            FROM memories
            LEFT JOIN memory_relations
              ON memory_relations.prior_memory_id = memories.id
            WHERE memories.project_id = ?
              AND memories.type = ?
              AND memories.subject = ?
              AND memories.scope_level = ?
              AND memories.component IS ?
              AND memories.source_project_event_seq > ?
              AND memory_relations.prior_memory_id IS NULL
            ORDER BY memories.source_project_event_seq DESC, memories.id ASC
            LIMIT 1
            """,
            (
                project_id,
                memory["type"],
                memory["subject"],
                memory["scope_level"],
                memory["component"],
                project_event_seq,
            ),
        ).fetchone()

    def _supersession_validation_error(
        self,
        conn: sqlite3.Connection,
        event: sqlite3.Row,
        memory: dict[str, object],
        prior_memory_ids: list[str],
    ) -> str | None:
        if len(prior_memory_ids) != len(set(prior_memory_ids)):
            return "invalid_tool_output"
        if not prior_memory_ids:
            return None
        if memory["type"] == "lesson":
            return "forbidden_lesson_supersession"

        placeholders = ",".join("?" for _ in prior_memory_ids)
        rows = conn.execute(
            f"""
            SELECT memories.*
            FROM memories
            LEFT JOIN memory_relations
              ON memory_relations.prior_memory_id = memories.id
            WHERE memories.id IN ({placeholders})
              AND memory_relations.prior_memory_id IS NULL
            """,
            prior_memory_ids,
        ).fetchall()
        if len(rows) != len(prior_memory_ids):
            return "inactive_supersession_target"
        for prior in rows:
            if prior["project_id"] != event["project_id"]:
                return "cross_project_candidate"
            if int(prior["source_project_event_seq"]) >= int(
                event["project_event_seq"]
            ):
                return "supersession_requires_older_prior"
            if any(
                prior[field] != memory[field]
                for field in ("type", "subject", "scope_level", "component")
            ):
                return "supersession_scope_mismatch"
        return None

    def _insert_supersession_edges(
        self,
        conn: sqlite3.Connection,
        prior_memory_ids: list[str],
        successor_memory_id: str,
        source_event_internal_id: str,
    ) -> None:
        for prior_id in prior_memory_ids:
            conn.execute(
                """
                INSERT INTO memory_relations (
                    prior_memory_id, successor_memory_id,
                    relation_type, source_event_internal_id
                )
                VALUES (?, ?, 'supersedes', ?)
                """,
                (prior_id, successor_memory_id, source_event_internal_id),
            )

    def _complete_pending_event(
        self,
        conn: sqlite3.Connection,
        event: sqlite3.Row,
        event_internal_id: str,
        lease_token: str,
        attempt_no: int,
        final_result: dict[str, Any],
        run_evidence: dict[str, Any] | None = None,
    ) -> bool:
        final_result_json = json.dumps(final_result, ensure_ascii=False, sort_keys=True)
        if not _valid_v4_final_result(final_result_json):
            return False
        updated = conn.execute(
            """
            UPDATE session_events
            SET processing_state = 'completed',
                final_result_json = ?,
                lease_token = NULL,
                lease_expires_at = NULL,
                last_error = NULL,
                result_schema_version = 4
            WHERE internal_id = ?
              AND processing_state = 'pending'
              AND lease_token = ?
              AND attempt_count = ?
            """,
            (final_result_json, event_internal_id, lease_token, attempt_no),
        )
        if updated.rowcount != 1:
            return False
        run_state = (
            "succeeded" if final_result.get("operation") == "write" else "semantic_no_op"
        )
        if not self._finish_run(
            conn,
            event_internal_id=event_internal_id,
            attempt_no=attempt_no,
            state=run_state,
            run_evidence=run_evidence,
        ):
            return False
        conn.execute(
            """
            UPDATE session_cursors
            SET next_expected_sequence_no = ?
            WHERE project_id = ? AND session_id = ?
            """,
            (int(event["sequence_no"]) + 1, event["project_id"], event["session_id"]),
        )
        return True

    def fail_retryable_event(
        self,
        event_internal_id: str | None,
        lease_token: str | None,
        attempt_no: int | None,
        error: str,
        run_evidence: dict[str, Any] | None = None,
        error_detail: str | None = None,
    ) -> bool:
        if event_internal_id is None or lease_token is None or attempt_no is None:
            return False
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            failure_code = error if _valid_failure_code(error) else "provider_network_error"
            updated = conn.execute(
                """
                UPDATE session_events
                SET processing_state = 'failed',
                    failure_kind = 'retryable',
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    last_error = ?
                WHERE internal_id = ?
                  AND processing_state = 'pending'
                  AND lease_token = ?
                  AND attempt_count = ?
                """,
                (failure_code, event_internal_id, lease_token, attempt_no),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return False
            if not self._finish_run(
                conn,
                event_internal_id=event_internal_id,
                attempt_no=attempt_no,
                state="failed_retryable",
                run_evidence=run_evidence,
                failure_code=failure_code,
                error_detail=error_detail or (error if error != failure_code else None),
            ):
                conn.rollback()
                return False
            conn.commit()
            return True

    def fail_terminal_event(
        self,
        event_internal_id: str | None,
        lease_token: str | None,
        attempt_no: int | None,
        error: str,
        final_result: dict[str, Any],
    ) -> bool:
        if event_internal_id is None or lease_token is None or attempt_no is None:
            return False
        final_result_json = json.dumps(final_result, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            event = conn.execute(
                """
                SELECT project_id, session_id, sequence_no
                FROM session_events
                WHERE internal_id = ?
                  AND processing_state = 'pending'
                  AND lease_token = ?
                  AND attempt_count = ?
                """,
                (event_internal_id, lease_token, attempt_no),
            ).fetchone()
            if event is None:
                conn.rollback()
                return False
            updated = conn.execute(
                """
                UPDATE session_events
                SET processing_state = 'failed',
                    failure_kind = 'terminal',
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    last_error = ?,
                    final_result_json = ?
                WHERE internal_id = ?
                  AND processing_state = 'pending'
                  AND lease_token = ?
                  AND attempt_count = ?
                """,
                (error, final_result_json, event_internal_id, lease_token, attempt_no),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return False
            conn.execute(
                """
                UPDATE session_cursors
                SET next_expected_sequence_no = ?
                WHERE project_id = ? AND session_id = ?
                """,
                (
                    int(event["sequence_no"]) + 1,
                    event["project_id"],
                    event["session_id"],
                ),
            )
            conn.commit()
            return True

    def attempt_count(self, project_id: str, session_id: str, event_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT attempt_count
                FROM session_events
                WHERE project_id = ? AND session_id = ? AND external_event_id = ?
                """,
                (project_id, session_id, event_id),
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            return int(row["attempt_count"])

    def has_event(self, project_id: str, session_id: str, event_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM session_events
                WHERE project_id = ? AND session_id = ? AND external_event_id = ?
                """,
                (project_id, session_id, event_id),
            ).fetchone()
            return row is not None

    def memory_count(self, project_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM memories
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            assert row is not None
            return int(row["count"])

    def active_memories(self, project_id: str) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memories.*
                FROM memories
                LEFT JOIN memory_relations
                  ON memory_relations.prior_memory_id = memories.id
                WHERE memories.project_id = ?
                  AND memory_relations.prior_memory_id IS NULL
                ORDER BY memories.source_project_event_seq DESC, memories.id ASC
                """,
                (project_id,),
            ).fetchall()
            return [_memory_from_row(row) for row in rows]

    def supersession_successor_id(self, prior_memory_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT successor_memory_id
                FROM memory_relations
                WHERE prior_memory_id = ?
                """,
                (prior_memory_id,),
            ).fetchone()
            if row is None:
                return None
            return str(row["successor_memory_id"])

    def _claim_existing(
        self,
        conn: sqlite3.Connection,
        existing: sqlite3.Row,
        payload_hash: str,
        now: int,
        provider_mode: str,
    ) -> ClaimResult:
        if existing["payload_hash"] != payload_hash:
            conn.commit()
            return ClaimResult(
                status="rejected",
                status_code=409,
                error="idempotency_conflict",
            )
        if existing["processing_state"] == "completed":
            if existing["result_schema_version"] != 4 or not _valid_v4_final_result(
                existing["final_result_json"]
            ):
                conn.commit()
                return ClaimResult(
                    status="rejected",
                    status_code=409,
                    error="legacy_result_incompatible",
                )
            run = self._run_for_attempt(
                conn,
                str(existing["internal_id"]),
                int(existing["attempt_count"]),
            )
            if run is None:
                conn.commit()
                return ClaimResult(
                    status="rejected",
                    status_code=409,
                    error="legacy_result_incompatible",
                )
            conn.commit()
            return ClaimResult(
                status="completed",
                status_code=200,
                event_internal_id=existing["internal_id"],
                project_event_seq=int(existing["project_event_seq"]),
                final_result=json.loads(existing["final_result_json"]),
                attempt_no=int(existing["attempt_count"]),
                **_claim_run_summary(run),
            )
        if existing["processing_state"] == "pending":
            lease_expires_at = int(existing["lease_expires_at"])
            if lease_expires_at > now:
                run = self._run_for_attempt(
                    conn,
                    str(existing["internal_id"]),
                    int(existing["attempt_count"]),
                )
                conn.commit()
                return ClaimResult(
                    status="pending",
                    status_code=202,
                    event_internal_id=existing["internal_id"],
                    project_event_seq=int(existing["project_event_seq"]),
                    lease_token=existing["lease_token"],
                    attempt_no=int(existing["attempt_count"]),
                    owns_attempt=False,
                    **(_claim_run_summary(run) if run is not None else {}),
                )
            return self._take_over_lease(conn, existing, now, provider_mode)
        if existing["processing_state"] == "failed" and existing["failure_kind"] == "retryable":
            return self._take_over_lease(conn, existing, now, provider_mode)
        conn.commit()
        return ClaimResult(status="rejected", status_code=409, error="event_not_retryable")

    def _take_over_lease(
        self,
        conn: sqlite3.Connection,
        existing: sqlite3.Row,
        now: int,
        provider_mode: str,
    ) -> ClaimResult:
        attempt_no = int(existing["attempt_count"]) + 1
        lease_token = _new_id("lease")
        run_id = _new_id("run")
        if existing["processing_state"] == "pending" and not self._finish_run(
            conn,
            event_internal_id=str(existing["internal_id"]),
            attempt_no=int(existing["attempt_count"]),
            state="lost_lease",
            failure_code="lease_expired",
        ):
            conn.rollback()
            return ClaimResult(
                status="rejected",
                status_code=409,
                error="lease_lost",
            )
        updated = conn.execute(
            """
            UPDATE session_events
            SET processing_state = 'pending',
                failure_kind = NULL,
                attempt_count = ?,
                lease_token = ?,
                lease_expires_at = ?,
                last_error = NULL
            WHERE internal_id = ?
              AND attempt_count = ?
              AND processing_state = ?
              AND lease_token IS ?
            """,
            (
                attempt_no,
                lease_token,
                now + self._lease_seconds,
                existing["internal_id"],
                int(existing["attempt_count"]),
                existing["processing_state"],
                existing["lease_token"],
            ),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return ClaimResult(
                status="rejected",
                status_code=409,
                error="lease_lost",
            )
        self._insert_running_run(
            conn,
            run_id=run_id,
            event_internal_id=str(existing["internal_id"]),
            attempt_no=attempt_no,
            provider_mode=provider_mode,
        )
        conn.commit()
        return ClaimResult(
            status="pending",
            status_code=202,
            event_internal_id=existing["internal_id"],
            project_event_seq=int(existing["project_event_seq"]),
            lease_token=lease_token,
            attempt_no=attempt_no,
            run_id=run_id,
            provider_mode=provider_mode,
            owns_attempt=True,
        )

    def _run_for_attempt(
        self,
        conn: sqlite3.Connection,
        event_internal_id: str,
        attempt_no: int,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM observe_runs
            WHERE event_internal_id = ? AND attempt_no = ?
            """,
            (event_internal_id, attempt_no),
        ).fetchone()

    def _next_project_event_seq(self, conn: sqlite3.Connection, project_id: str) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(project_event_seq), 0) + 1 AS next_seq
            FROM session_events
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        assert row is not None
        return int(row["next_seq"])

    def _event_by_key(
        self, conn: sqlite3.Connection, request: ObserveRequest
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM session_events
            WHERE project_id = ? AND session_id = ? AND external_event_id = ?
            """,
            (request.project_id, request.session_id, request.event_id),
        ).fetchone()

    def _cursor_for(
        self, conn: sqlite3.Connection, project_id: str, session_id: str
    ) -> sqlite3.Row:
        conn.execute(
            """
            INSERT OR IGNORE INTO session_cursors (
                project_id, session_id, next_expected_sequence_no
            )
            VALUES (?, ?, 1)
            """,
            (project_id, session_id),
        )
        row = conn.execute(
            """
            SELECT *
            FROM session_cursors
            WHERE project_id = ? AND session_id = ?
            """,
            (project_id, session_id),
        ).fetchone()
        assert row is not None
        return row

    def _blocking_event(
        self, conn: sqlite3.Connection, project_id: str, session_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM session_events
            WHERE project_id = ?
              AND session_id = ?
              AND processing_state IN ('pending', 'failed')
              AND (failure_kind IS NULL OR failure_kind = 'retryable')
            ORDER BY sequence_no
            LIMIT 1
            """,
            (project_id, session_id),
        ).fetchone()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            self._preflight_project_event_sequences(conn)
            self._ensure_migration_table(conn)
            self._apply_migrations(conn)
            self._audit_integrity(conn)

    def _preflight_project_event_sequences(self, conn: sqlite3.Connection) -> None:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'session_events'"
        ).fetchone()
        if table_exists is None:
            return
        duplicate = conn.execute(
            """
            SELECT project_id, project_event_seq, COUNT(*) AS duplicate_count
            FROM session_events
            GROUP BY project_id, project_event_seq
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate is not None:
            raise MigrationError(
                "duplicate_project_event_seq: "
                f"project={duplicate['project_id']} sequence={duplicate['project_event_seq']}"
            )

    def _ensure_migration_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL,
                checksum TEXT NOT NULL
            )
            """
        )

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        self._validate_applied_migrations(conn)
        for version, name, definition in _MIGRATION_DEFINITIONS:
            checksum = hashlib.sha256(definition.encode("utf-8")).hexdigest()
            existing = conn.execute(
                "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if existing is not None:
                if existing["name"] != name or existing["checksum"] != checksum:
                    raise MigrationError(
                        f"migration_checksum_mismatch: version={version} name={name}"
                    )
                continue

            conn.execute("BEGIN IMMEDIATE")
            try:
                self._apply_migration(conn, version)
                conn.execute(
                    """
                    INSERT INTO schema_migrations (version, name, applied_at, checksum)
                    VALUES (?, ?, ?, ?)
                    """,
                    (version, name, _utc_now(), checksum),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _validate_applied_migrations(self, conn: sqlite3.Connection) -> None:
        applied = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        known = {
            version: (name, hashlib.sha256(definition.encode("utf-8")).hexdigest())
            for version, name, definition in _MIGRATION_DEFINITIONS
        }
        versions = [int(row["version"]) for row in applied]
        unknown = [version for version in versions if version not in known]
        if unknown:
            raise MigrationError(
                f"unknown_applied_migration: versions={unknown}"
            )
        if versions != list(range(1, len(versions) + 1)):
            raise MigrationError(f"migration_history_gap: versions={versions}")
        for row in applied:
            expected_name, expected_checksum = known[int(row["version"])]
            if row["name"] != expected_name or row["checksum"] != expected_checksum:
                raise MigrationError(
                    "migration_checksum_mismatch: "
                    f"version={row['version']} name={expected_name}"
                )

    def _apply_migration(self, conn: sqlite3.Connection, version: int) -> None:
        if version == 1:
            for statement in _BASE_SCHEMA_STATEMENTS:
                conn.execute(statement)
            return
        if version == 2:
            _add_column_if_missing(
                conn, "session_events", "result_schema_version", "INTEGER"
            )
            _add_column_if_missing(conn, "memories", "embedding_model", "TEXT")
            _add_column_if_missing(conn, "memories", "embedding_dimension", "INTEGER")
            _add_column_if_missing(
                conn, "memories", "embedding_document_hash", "TEXT"
            )
            _add_column_if_missing(conn, "memories", "record_schema_version", "INTEGER")
            return
        if version == 3:
            conn.execute(_OBSERVE_RUNS_STATEMENT)
            return
        if version == 4:
            conn.execute(
                """
                CREATE UNIQUE INDEX ux_session_events_project_event_seq
                ON session_events(project_id, project_event_seq)
                """
            )
            return
        raise MigrationError(f"unknown_migration: version={version}")

    def _audit_integrity(self, conn: sqlite3.Connection) -> None:
        foreign_key_failure = conn.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_failure is not None:
            raise IntegrityAuditError(
                "foreign_key_corruption: "
                f"table={foreign_key_failure[0]} rowid={foreign_key_failure[1]}"
            )

        duplicate_relation = conn.execute(
            """
            SELECT prior_memory_id
            FROM memory_relations
            GROUP BY prior_memory_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate_relation is not None:
            raise IntegrityAuditError(
                f"duplicate_active_relation: memory={duplicate_relation['prior_memory_id']}"
            )

        event_rows = conn.execute(
            """
            SELECT internal_id, project_id, session_id, external_event_id,
                   sequence_no, project_event_seq, actor, kind, observed_at,
                   text, payload_hash, processing_state,
                   failure_kind, attempt_count, lease_token, lease_expires_at,
                   last_error, final_result_json, result_schema_version
            FROM session_events
            WHERE result_schema_version IS NOT NULL
            """
        ).fetchall()
        for row in event_rows:
            if not _valid_v4_event_state(row):
                raise IntegrityAuditError(
                    f"malformed_v4_event: event={row['internal_id']}"
                )

        run_rows = conn.execute("SELECT * FROM observe_runs").fetchall()
        for row in run_rows:
            if not _valid_v4_observe_run(row):
                raise IntegrityAuditError(
                    f"malformed_v4_observe_run: run={row['id']}"
                )
        self._audit_v4_event_run_consistency(conn, event_rows)

        memory_rows = conn.execute(
            """
            SELECT id, type, subject, text, scope_level, component,
                   embedding_json, embedding_model, embedding_dimension,
                   embedding_document_hash, record_schema_version
            FROM memories
            WHERE record_schema_version IS NOT NULL
            """
        ).fetchall()
        for row in memory_rows:
            if not _valid_v4_memory_embedding(row):
                raise IntegrityAuditError(f"malformed_v4_memory: memory={row['id']}")

    def _audit_v4_event_run_consistency(
        self,
        conn: sqlite3.Connection,
        event_rows: list[sqlite3.Row],
    ) -> None:
        for event in event_rows:
            runs = conn.execute(
                """
                SELECT attempt_no, state
                FROM observe_runs
                WHERE event_internal_id = ?
                ORDER BY attempt_no
                """,
                (event["internal_id"],),
            ).fetchall()
            attempt_count = int(event["attempt_count"])
            attempt_numbers = [int(row["attempt_no"]) for row in runs]
            if attempt_numbers != list(range(1, attempt_count + 1)):
                raise IntegrityAuditError(
                    f"inconsistent_v4_event_run: event={event['internal_id']}"
                )
            current = next(
                (row for row in runs if int(row["attempt_no"]) == attempt_count),
                None,
            )
            if len(runs) != attempt_count or current is None:
                raise IntegrityAuditError(
                    f"inconsistent_v4_event_run: event={event['internal_id']}"
                )
            if any(
                row["state"] == "running" and int(row["attempt_no"]) != attempt_count
                for row in runs
            ):
                raise IntegrityAuditError(
                    f"inconsistent_v4_event_run: event={event['internal_id']}"
                )
            if any(
                row["state"] not in {"failed_retryable", "lost_lease"}
                for row in runs[:-1]
            ):
                raise IntegrityAuditError(
                    f"inconsistent_v4_event_run: event={event['internal_id']}"
                )

            expected_state = _expected_current_run_state(event)
            if current["state"] != expected_state:
                raise IntegrityAuditError(
                    f"inconsistent_v4_event_run: event={event['internal_id']}"
                )


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_utc_timestamp(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _duration_ms(started_at: str, finished_at: str) -> int:
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((finished - started).total_seconds() * 1000))


def _bounded_detail(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[redacted]", value)
    sanitized = re.sub(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\b(request[_ -]?id|password|passwd|credential)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\bauthorization\s*:\s*bearer\s+\S+",
        "Authorization: Bearer [redacted]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}",
        "Bearer [redacted]",
        sanitized,
    )
    return sanitized[:1000]


def _normalized_run_evidence(
    value: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = value or {}
    model_calls = evidence.get("model_calls", [])
    embedding_calls = evidence.get("embedding_calls", [])
    tool_arguments = evidence.get("tool_arguments")
    validation = evidence.get("validation", [])
    return {
        "model_calls": model_calls if isinstance(model_calls, list) else [],
        "embedding_calls": (
            embedding_calls if isinstance(embedding_calls, list) else []
        ),
        "tool_arguments": (
            tool_arguments if isinstance(tool_arguments, dict) else None
        ),
        "validation": validation if isinstance(validation, (list, dict)) else [],
    }


def _claim_run_summary(run: sqlite3.Row) -> dict[str, Any]:
    try:
        model_calls = json.loads(run["model_calls_json"])
        embedding_calls = json.loads(run["embedding_calls_json"])
        validation = json.loads(run["validation_json"])
    except (TypeError, json.JSONDecodeError):
        model_calls = []
        embedding_calls = []
        validation = []
    calls = [
        call
        for call in [*model_calls, *embedding_calls]
        if isinstance(call, dict)
    ]
    return {
        "run_id": str(run["id"]),
        "provider_mode": str(run["provider_mode"]),
        "repaired": len(model_calls) > 1
        or (
            isinstance(validation, list)
            and any(
                isinstance(item, dict) and item.get("stage") == "repair"
                for item in validation
            )
        ),
        "request_id_present": any(
            call.get("request_id_present") is True for call in calls
        ),
    }


def _valid_v4_memory_embedding(row: sqlite3.Row) -> bool:
    if row["record_schema_version"] != 4:
        return False
    if row["embedding_model"] != "text-embedding-v4":
        return False
    if row["embedding_dimension"] != 1024:
        return False
    document_hash = row["embedding_document_hash"]
    if (
        not isinstance(document_hash, str)
        or len(document_hash) != 64
        or any(character not in "0123456789abcdef" for character in document_hash)
    ):
        return False
    scope = (
        "project"
        if row["scope_level"] == "project"
        else f"{row['scope_level']}:{row['component']}"
    )
    embedding_document = (
        f"type={row['type']}\n"
        f"scope={scope}\n"
        f"subject={row['subject']}\n"
        f"memory={row['text']}"
    )
    expected_hash = hashlib.sha256(embedding_document.encode("utf-8")).hexdigest()
    if document_hash != expected_hash:
        return False
    try:
        embedding = json.loads(row["embedding_json"])
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(embedding, list) or len(embedding) != 1024:
        return False
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in embedding):
        return False
    return any(float(value) != 0.0 for value in embedding)


def _valid_embedding_payload(
    memory: dict[str, object],
    embedding: dict[str, object],
) -> bool:
    if set(embedding) != {
        "vector",
        "model",
        "dimension",
        "document_hash",
        "record_schema_version",
    }:
        return False
    if (
        embedding["model"] != "text-embedding-v4"
        or embedding["dimension"] != 1024
        or embedding["record_schema_version"] != 4
    ):
        return False
    scope = (
        "project"
        if memory["scope_level"] == "project"
        else f"{memory['scope_level']}:{memory['component']}"
    )
    document = (
        f"type={memory['type']}\n"
        f"scope={scope}\n"
        f"subject={memory['subject']}\n"
        f"memory={memory['text']}"
    )
    if embedding["document_hash"] != hashlib.sha256(
        document.encode("utf-8")
    ).hexdigest():
        return False
    vector = embedding["vector"]
    return (
        isinstance(vector, list)
        and len(vector) == 1024
        and all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            for value in vector
        )
        and any(float(value) != 0.0 for value in vector)
    )


def _terminal_no_op_result(reason: str) -> dict[str, Any]:
    return {
        "operation": "no_op",
        "memory": None,
        "reason": reason,
    }


def _memory_summary(
    *,
    memory_id: str,
    memory: dict[str, object],
    session_id: str,
    event_id: str,
) -> dict[str, object]:
    return {
        "id": memory_id,
        "type": memory["type"],
        "subject": memory["subject"],
        "text": memory["text"],
        "scope_level": memory["scope_level"],
        "component": memory["component"],
        "source_ref": {"session_id": session_id, "event_id": event_id},
    }


def _valid_v4_event_state(row: sqlite3.Row) -> bool:
    if row["result_schema_version"] != 4:
        return False
    if not _valid_internal_id(row["internal_id"], "evt"):
        return False
    if not all(
        isinstance(row[field], str) and bool(row[field])
        for field in ("project_id", "session_id", "external_event_id")
    ):
        return False
    if row["actor"] not in {"user", "assistant", "tool"}:
        return False
    if row["kind"] not in {"message", "test_result", "command_result"}:
        return False
    if not _valid_utc_timestamp(row["observed_at"]):
        return False
    if not isinstance(row["text"], str) or not 1 <= len(row["text"]) <= 20_000:
        return False
    if not _valid_sha256(row["payload_hash"]):
        return False
    if row["payload_hash"] != _event_row_payload_hash(row):
        return False
    if (
        isinstance(row["sequence_no"], bool)
        or not isinstance(row["sequence_no"], int)
        or row["sequence_no"] < 1
        or isinstance(row["project_event_seq"], bool)
        or not isinstance(row["project_event_seq"], int)
        or row["project_event_seq"] < 1
    ):
        return False
    if (
        isinstance(row["attempt_count"], bool)
        or not isinstance(row["attempt_count"], int)
        or row["attempt_count"] < 1
    ):
        return False
    state = row["processing_state"]
    if state == "pending":
        return (
            row["failure_kind"] is None
            and isinstance(row["lease_token"], str)
            and bool(row["lease_token"])
            and not isinstance(row["lease_expires_at"], bool)
            and isinstance(row["lease_expires_at"], int)
            and row["last_error"] is None
            and row["final_result_json"] is None
        )
    if state == "completed":
        return (
            row["failure_kind"] is None
            and row["lease_token"] is None
            and row["lease_expires_at"] is None
            and row["last_error"] is None
            and _valid_v4_final_result(row["final_result_json"])
        )
    if state == "failed":
        return (
            row["failure_kind"] == "retryable"
            and row["lease_token"] is None
            and row["lease_expires_at"] is None
            and isinstance(row["last_error"], str)
            and bool(row["last_error"])
            and row["final_result_json"] is None
        )
    return False


def _valid_v4_observe_run(row: sqlite3.Row) -> bool:
    if not _valid_internal_id(row["id"], "run"):
        return False
    if not _valid_internal_id(row["event_internal_id"], "evt"):
        return False
    if (
        isinstance(row["attempt_no"], bool)
        or not isinstance(row["attempt_no"], int)
        or row["attempt_no"] < 1
        or row["provider_mode"] not in {"fake", "live"}
    ):
        return False
    if not _valid_utc_timestamp(row["started_at"]):
        return False
    if not _json_value_has_type(row["model_calls_json"], list):
        return False
    if not _json_value_has_type(row["embedding_calls_json"], list):
        return False
    if not _json_value_has_type(row["validation_json"], (list, dict)):
        return False
    if row["tool_arguments_json"] is not None and not _json_value_has_type(
        row["tool_arguments_json"], dict
    ):
        return False
    failure_code = row["failure_code"]
    if failure_code is not None and not _valid_failure_code(failure_code):
        return False
    error_detail = row["error_detail"]
    if error_detail is not None and (
        not isinstance(error_detail, str) or len(error_detail) > 1000
    ):
        return False

    state = row["state"]
    terminal_states = {"succeeded", "semantic_no_op", "failed_retryable", "lost_lease"}
    if state == "running":
        return (
            row["finished_at"] is None
            and row["duration_ms"] is None
            and row["failure_code"] is None
            and row["error_detail"] is None
        )
    if state not in terminal_states:
        return False
    if not _valid_utc_timestamp(row["finished_at"]):
        return False
    duration_ms = row["duration_ms"]
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
        return False
    if state == "lost_lease" and failure_code != "lease_expired":
        return False
    if state == "failed_retryable" and not _valid_failure_code(failure_code):
        return False
    if state in {"succeeded", "semantic_no_op"} and (
        failure_code is not None or error_detail is not None
    ):
        return False
    return True


def _expected_current_run_state(event: sqlite3.Row) -> str:
    if event["processing_state"] == "pending":
        return "running"
    if event["processing_state"] == "failed":
        return "failed_retryable"
    final_result = json.loads(event["final_result_json"])
    return "succeeded" if final_result["operation"] == "write" else "semantic_no_op"


def _valid_v4_final_result(raw: Any) -> bool:
    if not isinstance(raw, str):
        return False
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(result, dict):
        return False
    operation = result.get("operation")
    if operation == "no_op":
        return (
            set(result) == {"operation", "reason", "memory"}
            and _nonempty_text(result.get("reason"))
            and result.get("memory") is None
        )
    if operation == "duplicate":
        return (
            set(result)
            == {"operation", "reason", "memory", "duplicate_of_memory_id"}
            and _nonempty_text(result.get("reason"))
            and result.get("memory") is None
            and _nonempty_text(result.get("duplicate_of_memory_id"))
        )
    if operation == "write":
        superseded = result.get("superseded_memory_ids")
        return (
            set(result)
            == {"operation", "reason", "memory", "superseded_memory_ids"}
            and _nonempty_text(result.get("reason"))
            and _valid_memory_summary(result.get("memory"))
            and isinstance(superseded, list)
            and all(_nonempty_text(item) for item in superseded)
            and len(superseded) == len(set(superseded))
        )
    return False


def _valid_memory_summary(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "id",
        "type",
        "subject",
        "text",
        "scope_level",
        "component",
        "source_ref",
    }:
        return False
    if not all(_nonempty_text(value.get(field)) for field in ("id", "subject", "text")):
        return False
    if value.get("type") not in {"decision", "preference", "lesson"}:
        return False
    scope_level = value.get("scope_level")
    component = value.get("component")
    if scope_level == "project" and component is not None:
        return False
    if scope_level == "component" and not _nonempty_text(component):
        return False
    if scope_level not in {"project", "component"}:
        return False
    source_ref = value.get("source_ref")
    return (
        isinstance(source_ref, dict)
        and set(source_ref) == {"session_id", "event_id"}
        and _nonempty_text(source_ref.get("session_id"))
        and _nonempty_text(source_ref.get("event_id"))
    )


def _valid_internal_id(value: Any, prefix: str) -> bool:
    return isinstance(value, str) and value.startswith(f"{prefix}_") and len(value) > len(prefix) + 1


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _valid_failure_code(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value[0].isalpha()
        and value[0].isascii()
        and value == value.lower()
        and all(character.isascii() and (character.isalnum() or character == "_") for character in value)
    )


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0


def _event_row_payload_hash(row: sqlite3.Row) -> str:
    payload = {
        "actor": row["actor"],
        "kind": row["kind"],
        "observed_at": row["observed_at"],
        "sequence_no": row["sequence_no"],
        "text": row["text"],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_value_has_type(raw: Any, expected_type: type | tuple[type, ...]) -> bool:
    if not isinstance(raw, str):
        return False
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(value, expected_type)


def _payload_hash(request: ObserveRequest) -> str:
    observed_at = _canonical_utc_timestamp(request.observed_at)
    if observed_at is None:
        raise ValueError("invalid_timestamp")
    payload = {
        "actor": request.actor,
        "kind": request.kind,
        "observed_at": observed_at,
        "sequence_no": request.sequence_no,
        "text": request.text,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _memory_from_row(row: sqlite3.Row) -> MemoryRecord:
    try:
        embedding = json.loads(row["embedding_json"])
    except (TypeError, json.JSONDecodeError):
        embedding = []
    return MemoryRecord(
        id=row["id"],
        project_id=row["project_id"],
        type=row["type"],
        subject=row["subject"],
        text=row["text"],
        scope_level=row["scope_level"],
        component=row["component"],
        source_actor=row["source_actor"],
        source_ref=SourceRef(
            session_id=row["source_session_id"],
            event_id=row["source_event_id"],
        ),
        source_project_event_seq=int(row["source_project_event_seq"]),
        embedding=embedding,
        embedding_model=row["embedding_model"],
        embedding_dimension=row["embedding_dimension"],
        embedding_document_hash=row["embedding_document_hash"],
        record_schema_version=row["record_schema_version"],
        source_event_internal_id=row["source_event_internal_id"],
    )
