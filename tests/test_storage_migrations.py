import hashlib
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from recallpack.storage import IntegrityAuditError, MigrationError, SqliteEventStore


LEGACY_SCHEMA = """
CREATE TABLE session_cursors (
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    next_expected_sequence_no INTEGER NOT NULL,
    PRIMARY KEY (project_id, session_id)
);

CREATE TABLE session_events (
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
);

CREATE TABLE memories (
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
    FOREIGN KEY (source_event_internal_id) REFERENCES session_events(internal_id)
);

CREATE TABLE memory_relations (
    prior_memory_id TEXT NOT NULL,
    successor_memory_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    source_event_internal_id TEXT NOT NULL,
    UNIQUE (prior_memory_id),
    FOREIGN KEY (prior_memory_id) REFERENCES memories(id),
    FOREIGN KEY (successor_memory_id) REFERENCES memories(id),
    FOREIGN KEY (source_event_internal_id) REFERENCES session_events(internal_id)
);
"""


def _insert_legacy_event(
    conn: sqlite3.Connection,
    *,
    internal_id: str = "evt_legacy",
    session_id: str = "session-a",
    event_id: str = "turn-001",
    project_event_seq: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO session_events (
            internal_id, project_id, session_id, external_event_id,
            sequence_no, project_event_seq, actor, kind, observed_at, text,
            payload_hash, processing_state, failure_kind, attempt_count,
            lease_token, lease_expires_at, last_error, final_result_json
        ) VALUES (?, 'project-a', ?, ?, 1, ?, 'user', 'message',
                  '2026-06-24T00:00:00Z', 'legacy decision', 'legacy-hash',
                  'completed', NULL, 1, NULL, NULL, NULL,
                  '{"operation":"no_op"}')
        """,
        (internal_id, session_id, event_id, project_event_seq),
    )


def _insert_valid_v4_event_and_run(
    conn: sqlite3.Connection,
    *,
    run_state: str = "semantic_no_op",
    run_attempt_no: int = 1,
) -> None:
    event = {
        "actor": "user",
        "kind": "message",
        "observed_at": "2026-06-24T00:00:00Z",
        "sequence_no": 1,
        "text": "Keep retry behavior dependency-free.",
    }
    canonical = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    final_result = json.dumps(
        {
            "operation": "no_op",
            "reason": "non_memory_event",
            "memory": None,
        },
        sort_keys=True,
    )
    conn.execute(
        """
        INSERT INTO session_events (
            internal_id, project_id, session_id, external_event_id,
            sequence_no, project_event_seq, actor, kind, observed_at, text,
            payload_hash, processing_state, failure_kind, attempt_count,
            lease_token, lease_expires_at, last_error, final_result_json,
            result_schema_version
        ) VALUES (
            'evt_valid', 'project-a', 'session-a', 'turn-001',
            1, 1, ?, ?, ?, ?, ?, 'completed', NULL, 1,
            NULL, NULL, NULL, ?, 4
        )
        """,
        (
            event["actor"],
            event["kind"],
            event["observed_at"],
            event["text"],
            payload_hash,
            final_result,
        ),
    )
    terminal = run_state != "running"
    conn.execute(
        """
        INSERT INTO observe_runs (
            id, event_internal_id, attempt_no, state, provider_mode,
            model_calls_json, embedding_calls_json, tool_arguments_json,
            validation_json, failure_code, error_detail, started_at,
            finished_at, duration_ms
        ) VALUES (
            'run_valid', 'evt_valid', ?, ?, 'fake',
            '[]', '[]', NULL, '[]', NULL, NULL,
            '2026-06-24T00:00:00Z', ?, ?
        )
        """,
        (
            run_attempt_no,
            run_state,
            "2026-06-24T00:00:01Z" if terminal else None,
            1000 if terminal else None,
        ),
    )


def _insert_v4_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    attempt_no: int,
    state: str,
    failure_code: object = None,
    error_detail: object = None,
) -> None:
    terminal = state != "running"
    conn.execute(
        """
        INSERT INTO observe_runs (
            id, event_internal_id, attempt_no, state, provider_mode,
            model_calls_json, embedding_calls_json, tool_arguments_json,
            validation_json, failure_code, error_detail, started_at,
            finished_at, duration_ms
        ) VALUES (
            ?, 'evt_valid', ?, ?, 'fake',
            '[]', '[]', NULL, '[]', ?, ?,
            '2026-06-24T00:00:00Z', ?, ?
        )
        """,
        (
            run_id,
            attempt_no,
            state,
            failure_code,
            error_detail,
            "2026-06-24T00:00:01Z" if terminal else None,
            1000 if terminal else None,
        ),
    )


class StorageMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "recallpack.sqlite3"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _create_legacy_db(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript(LEGACY_SCHEMA)

    def test_legacy_rows_survive_additive_migrations_with_nullable_v4_metadata(self):
        self._create_legacy_db()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_legacy_event(conn)
            conn.execute(
                """
                INSERT INTO memories (
                    id, project_id, type, subject, text, scope_level, component,
                    source_actor, source_session_id, source_event_id,
                    source_event_internal_id, source_project_event_seq, embedding_json
                ) VALUES (
                    'mem_legacy', 'project-a', 'decision', 'retry policy',
                    'Use three attempts.', 'project', NULL, 'user', 'session-a',
                    'turn-001', 'evt_legacy', 1, '[]'
                )
                """
            )

        SqliteEventStore(self.db_path)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            event = conn.execute(
                "SELECT * FROM session_events WHERE internal_id = 'evt_legacy'"
            ).fetchone()
            memory = conn.execute(
                "SELECT * FROM memories WHERE id = 'mem_legacy'"
            ).fetchone()
            migrations = conn.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            observe_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(observe_runs)")
            }

        self.assertIsNotNone(event)
        self.assertIsNone(event["result_schema_version"])
        self.assertIsNotNone(memory)
        self.assertIsNone(memory["embedding_model"])
        self.assertIsNone(memory["embedding_dimension"])
        self.assertIsNone(memory["embedding_document_hash"])
        self.assertIsNone(memory["record_schema_version"])
        self.assertGreaterEqual(len(migrations), 4)
        self.assertTrue(all(row["checksum"] for row in migrations))
        self.assertTrue(
            {
                "id",
                "event_internal_id",
                "attempt_no",
                "state",
                "provider_mode",
                "model_calls_json",
                "embedding_calls_json",
                "tool_arguments_json",
                "validation_json",
                "failure_code",
                "error_detail",
                "started_at",
                "finished_at",
                "duration_ms",
            }.issubset(observe_columns)
        )

    def test_migrations_are_idempotent_and_checksum_mismatch_fails_startup(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            before = conn.execute(
                "SELECT version, name, applied_at, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()

        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            after = conn.execute(
                "SELECT version, name, applied_at, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            conn.execute(
                "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1"
            )

        self.assertEqual(before, after)
        with self.assertRaisesRegex(MigrationError, "migration_checksum_mismatch"):
            SqliteEventStore(self.db_path)

    def test_startup_rejects_unknown_applied_migration_version(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at, checksum)
                VALUES (5, 'future_migration', '2026-06-24T00:00:00Z', 'future')
                """
            )

        with self.assertRaisesRegex(MigrationError, "unknown_applied_migration"):
            SqliteEventStore(self.db_path)

    def test_duplicate_project_sequence_preflight_leaves_legacy_schema_unchanged(self):
        self._create_legacy_db()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_legacy_event(conn)
            _insert_legacy_event(
                conn,
                internal_id="evt_duplicate",
                session_id="session-b",
                event_id="turn-002",
                project_event_seq=1,
            )
            before_sql = conn.execute(
                "SELECT name, sql FROM sqlite_master ORDER BY name"
            ).fetchall()

        with self.assertRaisesRegex(MigrationError, "duplicate_project_event_seq"):
            SqliteEventStore(self.db_path)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            after_sql = conn.execute(
                "SELECT name, sql FROM sqlite_master ORDER BY name"
            ).fetchall()
            event_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(session_events)")
            }

        self.assertEqual(before_sql, after_sql)
        self.assertNotIn("result_schema_version", event_columns)

    def test_startup_integrity_rejects_malformed_v4_memory(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_legacy_event(conn)
            conn.execute(
                """
                INSERT INTO memories (
                    id, project_id, type, subject, text, scope_level, component,
                    source_actor, source_session_id, source_event_id,
                    source_event_internal_id, source_project_event_seq, embedding_json,
                    record_schema_version
                ) VALUES (
                    'mem_invalid_v4', 'project-a', 'decision', 'retry policy',
                    'Use five attempts.', 'project', NULL, 'user', 'session-a',
                    'turn-001', 'evt_legacy', 1, '[]', 4
                )
                """
            )

        with self.assertRaisesRegex(IntegrityAuditError, "malformed_v4_memory"):
            SqliteEventStore(self.db_path)

    def test_startup_integrity_rejects_v4_embedding_document_hash_mismatch(self):
        SqliteEventStore(self.db_path)
        vector_json = "[" + ",".join("1.0" for _ in range(1024)) + "]"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_legacy_event(conn)
            conn.execute(
                """
                INSERT INTO memories (
                    id, project_id, type, subject, text, scope_level, component,
                    source_actor, source_session_id, source_event_id,
                    source_event_internal_id, source_project_event_seq, embedding_json,
                    embedding_model, embedding_dimension, embedding_document_hash,
                    record_schema_version
                ) VALUES (
                    'mem_hash_mismatch', 'project-a', 'decision', 'retry_policy',
                    'Use five attempts.', 'component', 'retry', 'user', 'session-a',
                    'turn-001', 'evt_legacy', 1, ?, 'text-embedding-v4', 1024,
                    ?, 4
                )
                """,
                (vector_json, "0" * 64),
            )

        with self.assertRaisesRegex(IntegrityAuditError, "malformed_v4_memory"):
            SqliteEventStore(self.db_path)

    def test_startup_integrity_rejects_impossible_v4_event_state(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_legacy_event(conn)
            conn.execute(
                """
                UPDATE session_events
                SET result_schema_version = 4,
                    lease_token = 'lease_must_not_survive_completion',
                    lease_expires_at = 999
                WHERE internal_id = 'evt_legacy'
                """
            )

        with self.assertRaisesRegex(IntegrityAuditError, "malformed_v4_event"):
            SqliteEventStore(self.db_path)

    def test_startup_integrity_accepts_complete_consistent_v4_event_and_run(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_valid_v4_event_and_run(conn)

        SqliteEventStore(self.db_path)

    def test_startup_integrity_rejects_corrupt_v4_event_fields_and_result(self):
        corruptions = [
            ("external_event_id", "", "event_id"),
            ("actor", "intruder", "actor"),
            ("kind", "bogus", "kind"),
            ("observed_at", "2026-06-24T00:00:00", "timestamp"),
            ("text", "", "text"),
            ("payload_hash", "not-a-hash", "hash"),
            ("final_result_json", "{}", "result"),
        ]
        for column, value, label in corruptions:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "corrupt.sqlite3"
                SqliteEventStore(db_path)
                with closing(sqlite3.connect(db_path)) as conn, conn:
                    _insert_valid_v4_event_and_run(conn)
                    conn.execute(
                        f"UPDATE session_events SET {column} = ? WHERE internal_id = 'evt_valid'",
                        (value,),
                    )

                with self.assertRaisesRegex(
                    IntegrityAuditError,
                    "malformed_v4_event",
                ):
                    SqliteEventStore(db_path)

    def test_startup_integrity_rejects_event_current_run_inconsistency(self):
        cases = [
            ("running", 1, "state"),
            ("semantic_no_op", 2, "attempt"),
        ]
        for run_state, run_attempt_no, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "inconsistent.sqlite3"
                SqliteEventStore(db_path)
                with closing(sqlite3.connect(db_path)) as conn, conn:
                    _insert_valid_v4_event_and_run(
                        conn,
                        run_state=run_state,
                        run_attempt_no=run_attempt_no,
                    )

                with self.assertRaisesRegex(
                    IntegrityAuditError,
                    "inconsistent_v4_event_run",
                ):
                    SqliteEventStore(db_path)

    def test_startup_integrity_rejects_gapped_or_terminal_predecessor_attempts(self):
        cases = [
            (
                [(2, "semantic_no_op"), (3, "failed_retryable")],
                "future_attempt",
            ),
            (
                [(1, "succeeded"), (2, "semantic_no_op")],
                "terminal_predecessor",
            ),
        ]
        for runs, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "attempt-history.sqlite3"
                SqliteEventStore(db_path)
                with closing(sqlite3.connect(db_path)) as conn, conn:
                    _insert_valid_v4_event_and_run(conn)
                    conn.execute("DELETE FROM observe_runs WHERE id = 'run_valid'")
                    conn.execute(
                        "UPDATE session_events SET attempt_count = 2 WHERE internal_id = 'evt_valid'"
                    )
                    for index, (attempt_no, state) in enumerate(runs):
                        _insert_v4_run(
                            conn,
                            run_id=f"run_history_{index}",
                            attempt_no=attempt_no,
                            state=state,
                            failure_code=(
                                "provider_timeout"
                                if state == "failed_retryable"
                                else None
                            ),
                        )

                with self.assertRaisesRegex(
                    IntegrityAuditError,
                    "inconsistent_v4_event_run",
                ):
                    SqliteEventStore(db_path)

    def test_startup_integrity_accepts_retryable_predecessor_then_current_success(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_valid_v4_event_and_run(conn)
            conn.execute("DELETE FROM observe_runs WHERE id = 'run_valid'")
            conn.execute(
                "UPDATE session_events SET attempt_count = 2 WHERE internal_id = 'evt_valid'"
            )
            _insert_v4_run(
                conn,
                run_id="run_retryable",
                attempt_no=1,
                state="failed_retryable",
                failure_code="provider_timeout",
            )
            _insert_v4_run(
                conn,
                run_id="run_current",
                attempt_no=2,
                state="semantic_no_op",
            )

        SqliteEventStore(self.db_path)

    def test_startup_integrity_rejects_non_text_or_oversized_run_failure_fields(self):
        cases = [
            (sqlite3.Binary(b"provider_timeout"), None, "failure_code_type"),
            ("7", None, "failure_code_syntax"),
            (
                "provider_timeout",
                sqlite3.Binary(b"timeout"),
                "error_detail_type",
            ),
            ("provider_timeout", "x" * 1001, "error_detail_size"),
        ]
        for failure_code, error_detail, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "run-fields.sqlite3"
                SqliteEventStore(db_path)
                with closing(sqlite3.connect(db_path)) as conn, conn:
                    _insert_legacy_event(conn)
                    conn.execute(
                        """
                        INSERT INTO observe_runs (
                            id, event_internal_id, attempt_no, state, provider_mode,
                            model_calls_json, embedding_calls_json, tool_arguments_json,
                            validation_json, failure_code, error_detail, started_at,
                            finished_at, duration_ms
                        ) VALUES (
                            'run_bad_fields', 'evt_legacy', 1, 'failed_retryable',
                            'fake', '[]', '[]', NULL, '[]', ?, ?,
                            '2026-06-24T00:00:00Z',
                            '2026-06-24T00:00:01Z', 1000
                        )
                        """,
                        (failure_code, error_detail),
                    )

                with self.assertRaisesRegex(
                    IntegrityAuditError,
                    "malformed_v4_observe_run",
                ):
                    SqliteEventStore(db_path)

    def test_startup_integrity_rejects_impossible_v4_observe_run_state(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            _insert_legacy_event(conn)
            conn.execute(
                """
                INSERT INTO observe_runs (
                    id, event_internal_id, attempt_no, state, provider_mode,
                    model_calls_json, embedding_calls_json, tool_arguments_json,
                    validation_json, failure_code, error_detail, started_at,
                    finished_at, duration_ms
                ) VALUES (
                    'run_invalid', 'evt_legacy', 1, 'succeeded', 'fake',
                    '[]', '[]', NULL, '[]', NULL, NULL,
                    '2026-06-24T00:00:00Z', NULL, NULL
                )
                """
            )

        with self.assertRaisesRegex(IntegrityAuditError, "malformed_v4_observe_run"):
            SqliteEventStore(self.db_path)

    def test_startup_integrity_rejects_foreign_key_corruption(self):
        SqliteEventStore(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                INSERT INTO memories (
                    id, project_id, type, subject, text, scope_level, component,
                    source_actor, source_session_id, source_event_id,
                    source_event_internal_id, source_project_event_seq, embedding_json
                ) VALUES (
                    'mem_orphan', 'project-a', 'lesson', 'retry tests',
                    'Keep a retry regression test.', 'project', NULL, 'assistant',
                    'session-a', 'turn-404', 'evt_missing', 1, '[]'
                )
                """
            )

        with self.assertRaisesRegex(IntegrityAuditError, "foreign_key_corruption"):
            SqliteEventStore(self.db_path)

    def test_every_store_connection_enables_required_sqlite_pragmas(self):
        store = SqliteEventStore(self.db_path)

        with store._connect() as conn:
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(foreign_keys, 1)
        self.assertGreaterEqual(busy_timeout, 5_000)
        self.assertEqual(journal_mode, "wal")


if __name__ == "__main__":
    unittest.main()
