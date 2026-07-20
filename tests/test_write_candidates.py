import hashlib
import math
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from recallpack import write_candidates
from recallpack.memory import MemoryRecord, SourceRef
from recallpack.providers import document_for_candidate
from recallpack.storage import SqliteEventStore
from recallpack.write_candidates import build_candidate_payloads


EMBEDDING_DIMENSION = 1024


class RecordingQueryEmbeddingProvider:
    def __init__(self, vector):
        self._vector = list(vector)
        self.calls = []

    def embed_query(self, text):
        self.calls.append(("query", text))
        return SimpleNamespace(embedding=list(self._vector), trace={"role": "embedding"})

    def embed_document(self, text):
        self.calls.append(("document", text))
        raise AssertionError("stored memory documents must not be re-embedded")


class ActiveMemoryStore:
    def __init__(self, memories):
        self._memories = list(memories)
        self.projects = []

    def active_memories(self, project_id):
        self.projects.append(project_id)
        return list(self._memories)


def unit_vector(cosine):
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[0] = cosine
    vector[1] = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return vector


def memory_record(
    memory_id,
    *,
    score=1.0,
    sequence=1,
    scope_level="component",
    component="retry",
    embedding=None,
    embedding_model="text-embedding-v4",
    embedding_dimension=EMBEDDING_DIMENSION,
    embedding_document_hash=None,
):
    memory = SimpleNamespace(
        id=memory_id,
        project_id="fresh-project",
        type="preference" if scope_level == "project" else "decision",
        subject=f"subject_{memory_id}",
        text=f"Memory text for {memory_id}.",
        scope_level=scope_level,
        component=component,
        source_actor="user",
        source_ref=SourceRef(session_id="session-a", event_id=f"turn-{sequence}"),
        source_project_event_seq=sequence,
        embedding=list(embedding if embedding is not None else unit_vector(score)),
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        embedding_document_hash=embedding_document_hash,
        record_schema_version=4,
    )
    if memory.embedding_document_hash is None:
        memory.embedding_document_hash = hashlib.sha256(
            document_for_candidate(memory).encode("utf-8")
        ).hexdigest()
    return memory


class WriteCandidatePayloadTests(unittest.TestCase):
    def test_candidate_payload_contains_authority_and_scope_fields(self):
        memory = MemoryRecord(
            id="mem_retry_policy_v1",
            project_id="project-a",
            type="decision",
            subject="retry_policy",
            text="Use three attempts with a fixed 100 ms delay in the retry helper.",
            scope_level="component",
            component="retry",
            source_actor="user",
            source_ref=SourceRef(session_id="session-a", event_id="turn-001"),
            source_project_event_seq=1,
            embedding=[0.1, 0.2, 0.3],
        )

        payloads = build_candidate_payloads(
            scored_memories=[(memory, 0.83)],
            limit=8,
        )

        self.assertEqual(
            payloads,
            [
                {
                    "candidate_index": 0,
                    "memory_id": "mem_retry_policy_v1",
                    "type": "decision",
                    "subject": "retry_policy",
                    "text": "Use three attempts with a fixed 100 ms delay in the retry helper.",
                    "scope_level": "component",
                    "component": "retry",
                    "source_actor": "user",
                    "source_ref": {"session_id": "session-a", "event_id": "turn-001"},
                    "source_project_event_seq": 1,
                    "similarity": 0.83,
                }
            ],
        )


class WriteCandidateRetrievalV4Tests(unittest.TestCase):
    def select(self, store, provider, *, limit=8):
        selector = getattr(write_candidates, "select_write_candidates", None)
        self.assertTrue(
            callable(selector),
            "T018 requires select_write_candidates over active stored vectors",
        )
        return selector(
            store=store,
            project_id="fresh-project",
            raw_event="Replace retry behavior with exponential backoff.",
            embedding_provider=provider,
            limit=limit,
        )

    def test_all_active_same_project_scopes_and_components_are_scanned(self):
        memories = [
            memory_record("mem_retry", score=0.9, sequence=1),
            memory_record(
                "mem_project_preference",
                score=0.8,
                sequence=2,
                scope_level="project",
                component=None,
            ),
            memory_record("mem_auth", score=0.7, sequence=3, component="auth"),
        ]
        store = ActiveMemoryStore(memories)
        provider = RecordingQueryEmbeddingProvider(unit_vector(1.0))

        scored = self.select(store, provider)

        self.assertEqual(store.projects, ["fresh-project"])
        self.assertEqual([memory.id for memory, _ in scored], [
            "mem_retry",
            "mem_project_preference",
            "mem_auth",
        ])
        self.assertEqual(provider.calls, [
            ("query", "Replace retry behavior with exponential backoff."),
        ])

    def test_invalid_stored_vectors_and_metadata_fail_closed(self):
        invalid_memories = [
            memory_record("mem_zero", embedding=[0.0] * EMBEDDING_DIMENSION),
            memory_record("mem_short", embedding=[1.0, 0.0], embedding_dimension=2),
            memory_record("mem_nonfinite", embedding=[float("nan")] + [0.0] * 1023),
            memory_record("mem_model", embedding_model="other-embedding-model"),
            memory_record("mem_hash", embedding_document_hash="0" * 64),
        ]
        for invalid in invalid_memories:
            with self.subTest(memory_id=invalid.id):
                provider = RecordingQueryEmbeddingProvider(unit_vector(1.0))
                with self.assertRaisesRegex(ValueError, "memory_embedding_backfill_required"):
                    self.select(ActiveMemoryStore([invalid]), provider)
                self.assertEqual(
                    provider.calls,
                    [],
                    "stored vectors must fail closed before query embedding",
                )

    def test_malformed_legacy_embedding_json_maps_to_backfill_before_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.sqlite3"
            store = SqliteEventStore(db_path)
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO session_events (
                        internal_id, project_id, session_id, external_event_id,
                        sequence_no, project_event_seq, actor, kind, observed_at,
                        text, payload_hash, processing_state, failure_kind,
                        attempt_count, lease_token, lease_expires_at, last_error,
                        final_result_json
                    ) VALUES (
                        'evt_legacy', 'fresh-project', 'session-a', 'turn-001',
                        1, 1, 'user', 'message', '2026-07-10T00:00:00Z',
                        'Legacy retry policy', ?, 'completed', NULL, 1, NULL,
                        NULL, NULL, '{"operation":"write"}'
                    )
                    """,
                    ("0" * 64,),
                )
                conn.execute(
                    """
                    INSERT INTO memories (
                        id, project_id, type, subject, text, scope_level,
                        component, source_actor, source_session_id,
                        source_event_id, source_event_internal_id,
                        source_project_event_seq, embedding_json
                    ) VALUES (
                        'mem_legacy', 'fresh-project', 'decision',
                        'retry_policy', 'Legacy retry policy', 'component',
                        'retry', 'user', 'session-a', 'turn-001', 'evt_legacy',
                        1, 'not-json'
                    )
                    """
                )

            provider = RecordingQueryEmbeddingProvider(unit_vector(1.0))
            with self.assertRaisesRegex(ValueError, "memory_embedding_backfill_required"):
                self.select(store, provider)
            self.assertEqual(provider.calls, [])

    def test_exact_cosine_selects_top_eight_and_uses_frozen_tie_break(self):
        memories = [
            memory_record("mem_low", score=0.05, sequence=99),
            memory_record("mem_90", score=0.90, sequence=2),
            memory_record("mem_80", score=0.80, sequence=3),
            memory_record("mem_70", score=0.70, sequence=4),
            memory_record("mem_60", score=0.60, sequence=5),
            memory_record("mem_50", score=0.50, sequence=6),
            memory_record("mem_40", score=0.40, sequence=7),
            memory_record("mem_tie_b", score=0.30, sequence=8),
            memory_record("mem_tie_a", score=0.30, sequence=8),
        ]

        scored = self.select(
            ActiveMemoryStore(memories),
            RecordingQueryEmbeddingProvider(unit_vector(1.0)),
        )

        self.assertEqual([memory.id for memory, _ in scored], [
            "mem_90",
            "mem_80",
            "mem_70",
            "mem_60",
            "mem_50",
            "mem_40",
            "mem_tie_a",
            "mem_tie_b",
        ])
        self.assertNotIn("mem_low", [memory.id for memory, _ in scored])
        self.assertAlmostEqual(scored[0][1], 0.90)

    def test_relevant_supersession_prior_older_than_newest_eight_is_recalled(self):
        prior = memory_record("mem_old_prior", score=1.0, sequence=1)
        distractors = [
            memory_record(f"mem_new_{index}", score=0.8 - index * 0.05, sequence=index + 2)
            for index in range(8)
        ]

        scored = self.select(
            ActiveMemoryStore(distractors + [prior]),
            RecordingQueryEmbeddingProvider(unit_vector(1.0)),
        )

        self.assertEqual(scored[0][0].id, "mem_old_prior")
        self.assertEqual(len(scored), 8)


if __name__ == "__main__":
    unittest.main()
