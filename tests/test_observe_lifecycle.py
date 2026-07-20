import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

from recallpack.observe import (
    ObserveRequest,
    ObserveRuntime,
    RetryableObserveError,
    TerminalObserveError,
)
from recallpack.providers import (
    DeterministicKeywordEmbeddingProvider,
    FakeEmbeddingProvider,
)
from recallpack.storage import SqliteEventStore


def request(
    event_id: str,
    sequence_no: int,
    actor: str = "user",
    text: str = "Use three attempts with a fixed 100 ms delay in the retry helper.",
    session_id: str = "session-a",
) -> ObserveRequest:
    return ObserveRequest(
        project_id="project-a",
        session_id=session_id,
        event_id=event_id,
        sequence_no=sequence_no,
        actor=actor,
        kind="message",
        observed_at="2026-06-24T00:00:00Z",
        text=text,
    )


class QueueDecider:
    def __init__(self, *operations):
        self._operations = list(operations)
        self.calls = []

    def decide_memory_operation(self, request, candidates):
        self.calls.append(candidates)
        if not self._operations:
            raise AssertionError("decider called more times than expected")
        return self._operations.pop(0)


class FailingDecider:
    def decide_memory_operation(self, request, candidates):
        raise RetryableObserveError("temporary qwen timeout")


class TerminalFailingDecider:
    def decide_memory_operation(self, request, candidates):
        raise TerminalObserveError("incorrect api key")


def write_decision(text, *, supersedes=None):
    return {
        "operation": "write",
        "memory": {
            "type": "decision",
            "subject": "retry_policy",
            "text": text,
            "scope_level": "component",
            "component": "retry",
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": list(supersedes or []),
        "reason": "retry_policy_changed",
    }


class ClaimSignalingStore:
    """Expose that a later turn is owned without letting tests inspect internals."""

    def __init__(self, store, event_id, claimed):
        self._store = store
        self._event_id = event_id
        self._claimed = claimed

    def claim_event(self, request, now, provider_mode="fake"):
        result = self._store.claim_event(
            request,
            now=now,
            provider_mode=provider_mode,
        )
        if request.event_id == self._event_id and result.status_code == 202:
            self._claimed.set()
        return result

    def __getattr__(self, name):
        return getattr(self._store, name)


class BlockingQueueDecider(QueueDecider):
    def __init__(self, release, operation):
        super().__init__(operation)
        self._release = release
        self.entered = threading.Event()

    def decide_memory_operation(self, request, candidates):
        self.entered.set()
        if not self._release.wait(timeout=5):
            raise AssertionError("blocked observe decision was not released")
        return super().decide_memory_operation(request, candidates)


class EnteredQueueDecider(QueueDecider):
    def __init__(self, operation):
        super().__init__(operation)
        self.entered = threading.Event()

    def decide_memory_operation(self, request, candidates):
        self.entered.set()
        return super().decide_memory_operation(request, candidates)


class ObserveLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "recallpack.sqlite3"
        self.store = SqliteEventStore(self.db_path, lease_seconds=30)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_completed_results_use_only_durable_v4_contract_fields(self):
        first = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                write_decision("Use three attempts with a fixed 100 ms delay.")
            ),
        ).observe(request("turn-001", 1), now=101)
        duplicate = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "duplicate",
                    "memory": None,
                    "duplicate_of_candidate_index": 0,
                    "supersedes_candidate_indexes": [],
                    "reason": "equivalent_active_memory",
                }
            ),
        ).observe(request("turn-002", 2), now=102)
        no_op = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "no_op",
                    "memory": None,
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "non_memory_event",
                }
            ),
        ).observe(request("turn-003", 3, text="Thanks."), now=103)

        self.assertEqual(
            set(first.final_result),
            {"operation", "reason", "memory", "superseded_memory_ids"},
        )
        self.assertEqual(
            set(first.final_result["memory"]),
            {
                "id",
                "type",
                "subject",
                "text",
                "scope_level",
                "component",
                "source_ref",
            },
        )
        self.assertEqual(
            first.final_result["memory"]["source_ref"],
            {"session_id": "session-a", "event_id": "turn-001"},
        )
        self.assertEqual(
            set(duplicate.final_result),
            {"operation", "reason", "memory", "duplicate_of_memory_id"},
        )
        self.assertEqual(
            duplicate.final_result["duplicate_of_memory_id"],
            first.final_result["memory"]["id"],
        )
        self.assertEqual(
            set(no_op.final_result),
            {"operation", "reason", "memory"},
        )

    def test_valid_no_op_completes_event_and_advances_cursor(self):
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "no_op",
                    "memory": None,
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "non_memory_event",
                }
            ),
        )

        response = runtime.observe(request("turn-001", 1), now=100)
        next_claim = self.store.claim_event(request("turn-002", 2), now=101)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "non_memory_event")
        self.assertEqual(self.store.memory_count("project-a"), 0)
        self.assertEqual(next_claim.status_code, 202)

    def test_write_operation_inserts_one_active_memory(self):
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use three attempts with a fixed 100 ms delay.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "new_decision",
                }
            ),
        )

        response = runtime.observe(request("turn-001", 1), now=100)
        active = self.store.active_memories("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "write")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].type, "decision")
        self.assertEqual(active[0].subject, "retry_policy")
        self.assertEqual(active[0].scope_level, "component")
        self.assertEqual(active[0].component, "retry")
        self.assertEqual(active[0].source_actor, "user")
        self.assertEqual(active[0].source_project_event_seq, 1)

    def test_write_persists_valid_document_embedding_before_lifecycle_commit(self):
        text = "Use three attempts with a fixed 100 ms delay."
        document = (
            "type=decision\n"
            "scope=component:retry\n"
            "subject=retry_policy\n"
            f"memory={text}"
        )
        vector = [1.0] + [0.0] * 1023
        embeddings = FakeEmbeddingProvider(vectors={f"document:{document}": vector})
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(write_decision(text)),
            embedding_provider=embeddings,
        )

        response = runtime.observe(request("turn-001", 1, text=text), now=100)
        active = self.store.active_memories("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([call["operation"] for call in embeddings.calls], ["embed_document"])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].embedding, vector)
        self.assertEqual(active[0].embedding_model, "text-embedding-v4")
        self.assertEqual(active[0].embedding_dimension, 1024)
        self.assertEqual(
            active[0].embedding_document_hash,
            hashlib.sha256(document.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(active[0].record_schema_version, 4)

    def test_write_response_matches_completed_replay_result(self):
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use three attempts with a fixed 100 ms delay.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "new_decision",
                }
            ),
        )
        original_request = request("turn-001", 1)

        response = runtime.observe(original_request, now=100)
        replay = runtime.observe(original_request, now=101)

        self.assertTrue(response.final_result["memory"]["id"].startswith("mem_"))
        self.assertEqual(response.final_result, replay.final_result)

    def test_duplicate_operation_completes_without_inserting_memory(self):
        first_decider = QueueDecider(
            {
                "operation": "write",
                "memory": {
                    "type": "decision",
                    "subject": "retry_policy",
                    "text": "Use three attempts with a fixed 100 ms delay.",
                    "scope_level": "component",
                    "component": "retry",
                },
                "duplicate_of_candidate_index": None,
                "supersedes_candidate_indexes": [],
                "reason": "new_decision",
            }
        )
        ObserveRuntime(store=self.store, decider=first_decider).observe(
            request("turn-001", 1),
            now=100,
        )
        duplicate_decider = QueueDecider(
            {
                "operation": "duplicate",
                "memory": None,
                "duplicate_of_candidate_index": 0,
                "supersedes_candidate_indexes": [],
                "reason": "same_decision",
            }
        )
        runtime = ObserveRuntime(store=self.store, decider=duplicate_decider)

        response = runtime.observe(request("turn-002", 2), now=101)
        next_claim = self.store.claim_event(request("turn-003", 3), now=102)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "duplicate")
        self.assertEqual(self.store.memory_count("project-a"), 1)
        self.assertEqual(duplicate_decider.calls[0][0]["candidate_index"], 0)
        self.assertEqual(next_claim.status_code, 202)

    def test_duplicate_candidate_index_must_be_allowlisted(self):
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "duplicate",
                    "memory": None,
                    "duplicate_of_candidate_index": 0,
                    "supersedes_candidate_indexes": [],
                    "reason": "same_decision",
                }
            ),
        )

        response = runtime.observe(request("turn-001", 1), now=100)
        next_claim = self.store.claim_event(request("turn-002", 2), now=101)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "candidate_index_out_of_range")
        self.assertEqual(self.store.memory_count("project-a"), 0)
        self.assertEqual(next_claim.status_code, 202)

    def test_write_with_supersession_makes_prior_memory_inactive(self):
        initial_decider = QueueDecider(
            {
                "operation": "write",
                "memory": {
                    "type": "decision",
                    "subject": "retry_policy",
                    "text": "Use three attempts with a fixed 100 ms delay.",
                    "scope_level": "component",
                    "component": "retry",
                },
                "duplicate_of_candidate_index": None,
                "supersedes_candidate_indexes": [],
                "reason": "new_decision",
            }
        )
        ObserveRuntime(store=self.store, decider=initial_decider).observe(
            request("turn-001", 1),
            now=100,
        )
        prior = self.store.active_memories("project-a")[0]
        replacement_decider = QueueDecider(
            {
                "operation": "write",
                "memory": {
                    "type": "decision",
                    "subject": "retry_policy",
                    "text": "Use five attempts with exponential backoff.",
                    "scope_level": "component",
                    "component": "retry",
                },
                "duplicate_of_candidate_index": None,
                "supersedes_candidate_indexes": [0],
                "reason": "supersedes_old_retry_policy",
            }
        )

        response = ObserveRuntime(store=self.store, decider=replacement_decider).observe(
            request("turn-002", 2, text="Use five attempts with exponential backoff."),
            now=101,
        )
        active = self.store.active_memories("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "write")
        self.assertEqual(self.store.memory_count("project-a"), 2)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].text, "Use five attempts with exponential backoff.")
        self.assertEqual(self.store.supersession_successor_id(prior.id), active[0].id)

    def test_new_session_sequence_one_can_supersede_older_project_memory(self):
        ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use three attempts with a fixed 100 ms delay.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "new_decision",
                }
            ),
        ).observe(request("turn-001", 1, session_id="session-a"), now=100)
        prior = self.store.active_memories("project-a")[0]

        response = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use five attempts with exponential backoff.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [0],
                    "reason": "supersedes_old_retry_policy",
                }
            ),
        ).observe(
            request(
                "turn-001",
                1,
                text="Use five attempts with exponential backoff.",
                session_id="session-b",
            ),
            now=101,
        )
        active = self.store.active_memories("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "write")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].text, "Use five attempts with exponential backoff.")
        self.assertGreater(active[0].source_project_event_seq, prior.source_project_event_seq)
        self.assertEqual(self.store.supersession_successor_id(prior.id), active[0].id)

    def test_active_supersession_chain_leaves_only_latest_memory_active(self):
        first = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(write_decision("Use three attempts with fixed delay.")),
        ).observe(request("turn-a", 1, session_id="session-a"), now=100)
        memory_a = self.store.active_memories("project-a")[0]
        second = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                write_decision("Use five attempts with exponential backoff.", supersedes=[0])
            ),
        ).observe(
            request(
                "turn-b",
                1,
                session_id="session-b",
                text="Use five attempts with exponential backoff.",
            ),
            now=101,
        )
        memory_b = self.store.active_memories("project-a")[0]
        third = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                write_decision("Use seven attempts with capped backoff.", supersedes=[0])
            ),
        ).observe(
            request(
                "turn-c",
                1,
                session_id="session-c",
                text="Replace retry policy with seven attempts and capped backoff.",
            ),
            now=102,
        )
        active = self.store.active_memories("project-a")

        self.assertEqual([first.status_code, second.status_code, third.status_code], [200, 200, 200])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].text, "Use seven attempts with capped backoff.")
        self.assertEqual(self.store.supersession_successor_id(memory_a.id), memory_b.id)
        self.assertEqual(self.store.supersession_successor_id(memory_b.id), active[0].id)

    def test_assistant_cannot_supersede_user_authoritative_decision(self):
        ObserveRuntime(
            store=self.store,
            decider=QueueDecider(write_decision("Use three attempts with fixed delay.")),
        ).observe(request("turn-001", 1), now=100)
        prior = self.store.active_memories("project-a")[0]

        response = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                write_decision("Use five attempts with exponential backoff.", supersedes=[0])
            ),
        ).observe(
            request(
                "turn-002",
                2,
                actor="assistant",
                text="I will replace retry policy with exponential backoff.",
            ),
            now=101,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "decision_requires_user")
        self.assertEqual([memory.id for memory in self.store.active_memories("project-a")], [prior.id])
        self.assertIsNone(self.store.supersession_successor_id(prior.id))

    def test_delayed_lower_project_sequence_write_cannot_shadow_newer_active_key(self):
        lower_request = request("turn-low", 1, session_id="session-low")
        failed = ObserveRuntime(store=self.store, decider=FailingDecider()).observe(
            lower_request,
            now=100,
        )
        newer_embeddings = DeterministicKeywordEmbeddingProvider()
        newer = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(write_decision("Use five attempts with exponential backoff.")),
            embedding_provider=newer_embeddings,
        ).observe(
            request(
                "turn-high",
                1,
                session_id="session-high",
                text="Use five attempts with exponential backoff.",
            ),
            now=101,
        )

        delayed_embeddings = DeterministicKeywordEmbeddingProvider()
        delayed = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(write_decision("Use three attempts with fixed delay.")),
            embedding_provider=delayed_embeddings,
        ).observe(lower_request, now=102)
        active = self.store.active_memories("project-a")

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(newer.status_code, 200)
        self.assertEqual(delayed.status_code, 200)
        self.assertEqual(delayed.final_result["operation"], "no_op")
        self.assertEqual(delayed.final_result["reason"], "stale_project_event")
        self.assertEqual(
            [call["operation"] for call in delayed_embeddings.calls],
            ["embed_query"],
            "stale lifecycle writes must be rejected before document embedding",
        )
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].text, "Use five attempts with exponential backoff.")

    def test_same_project_race_second_turn_observes_first_committed_lifecycle(self):
        second_claimed = threading.Event()
        release_first = threading.Event()
        signaling_store = ClaimSignalingStore(self.store, "turn-second", second_claimed)
        first_decider = BlockingQueueDecider(
            release_first,
            write_decision("Use three attempts with fixed delay."),
        )
        first_runtime = ObserveRuntime(
            store=signaling_store,
            decider=first_decider,
        )
        second_decider = EnteredQueueDecider(
            write_decision("Use five attempts with exponential backoff.", supersedes=[0])
        )
        second_runtime = ObserveRuntime(store=signaling_store, decider=second_decider)
        responses = {}

        first_thread = threading.Thread(
            target=lambda: responses.setdefault(
                "first",
                first_runtime.observe(
                    request("turn-first", 1, session_id="session-first"),
                    now=100,
                ),
            )
        )
        second_thread = threading.Thread(
            target=lambda: responses.setdefault(
                "second",
                second_runtime.observe(
                    request(
                        "turn-second",
                        1,
                        session_id="session-second",
                        text="Use five attempts with exponential backoff.",
                    ),
                    now=101,
                ),
            )
        )
        first_thread.start()
        self.assertTrue(first_decider.entered.wait(timeout=5), "first observe did not reach decision")
        second_thread.start()
        self.assertTrue(second_claimed.wait(timeout=5), "second observe was not claimed")
        overlapped_first_lifecycle = second_decider.entered.wait(timeout=0.1)
        release_first.set()
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)
        self.assertFalse(first_thread.is_alive(), "first observe thread did not finish")
        self.assertFalse(second_thread.is_alive(), "second observe thread did not finish")

        active = self.store.active_memories("project-a")
        self.assertFalse(
            overlapped_first_lifecycle,
            "same-project second decision ran before the first lifecycle committed",
        )
        self.assertEqual(responses["first"].status_code, 200)
        self.assertEqual(responses["second"].status_code, 200)
        self.assertEqual(responses["second"].final_result["operation"], "write")
        self.assertEqual(len(second_decider.calls[0]), 1)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].text, "Use five attempts with exponential backoff.")

    def test_invalid_semantic_write_becomes_terminal_no_op(self):
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "billing_policy",
                        "text": "Use Stripe retries.",
                        "scope_level": "component",
                        "component": "billing",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "new_decision",
                }
            ),
        )

        response = runtime.observe(request("turn-001", 1), now=100)
        next_claim = self.store.claim_event(request("turn-002", 2), now=101)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "invalid_component")
        self.assertEqual(self.store.memory_count("project-a"), 0)
        self.assertEqual(next_claim.status_code, 202)

    def test_assistant_preference_and_public_supersede_become_no_op(self):
        preference_runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "preference",
                        "subject": "dependencies",
                        "text": "Do not add dependencies.",
                        "scope_level": "project",
                        "component": None,
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "new_preference",
                }
            ),
        )
        supersede_runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "supersede",
                    "memory": None,
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [0],
                    "reason": "bad_public_operation",
                }
            ),
        )

        preference = preference_runtime.observe(
            request("turn-001", 1, actor="assistant"),
            now=100,
        )
        public_supersede = supersede_runtime.observe(request("turn-002", 2), now=101)

        self.assertEqual(preference.final_result["operation"], "no_op")
        self.assertEqual(preference.final_result["reason"], "preference_requires_user")
        self.assertEqual(public_supersede.final_result["operation"], "no_op")
        self.assertEqual(public_supersede.final_result["reason"], "invalid_tool_output")
        self.assertEqual(self.store.memory_count("project-a"), 0)

    def test_tool_result_cannot_write_project_decision(self):
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Retry tests may fail if rate limits last too long.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "test_observation",
                }
            ),
        )

        response = runtime.observe(
            request(
                "turn-004",
                1,
                actor="tool",
                text="The last retry test failed because rate limits lasted longer than 300 ms.",
            ),
            now=100,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "decision_requires_user")
        self.assertEqual(self.store.memory_count("project-a"), 0)

    def test_equivalent_retry_policy_write_becomes_duplicate_not_new_source(self):
        ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use five attempts with exponential backoff.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "updated_retry_policy",
                }
            ),
        ).observe(
            request(
                "turn-005",
                1,
                text="After the rate-limit failures, use five attempts with exponential backoff in the retry helper.",
            ),
            now=100,
        )
        prior = self.store.active_memories("project-a")[0]
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use five attempts with exponential backoff.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [0],
                    "reason": "restate_current_retry_policy",
                }
            ),
        )

        response = runtime.observe(
            request(
                "turn-007",
                2,
                text="That retry policy update replaces the earlier fixed-delay retry decision.",
            ),
            now=101,
        )
        active = self.store.active_memories("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "duplicate")
        self.assertEqual(response.final_result["duplicate_of_memory_id"], prior.id)
        self.assertEqual(self.store.memory_count("project-a"), 1)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, prior.id)
        self.assertEqual(active[0].source_ref.event_id, "turn-005")

    def test_incomplete_retry_restatement_cannot_supersede_more_specific_policy(self):
        ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use five attempts with exponential backoff in the retry helper.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "updated_retry_policy",
                }
            ),
        ).observe(
            request(
                "turn-005",
                1,
                text="After the rate-limit failures, use five attempts with exponential backoff in the retry helper.",
            ),
            now=100,
        )
        prior = self.store.active_memories("project-a")[0]
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "text": "Use exponential backoff instead of fixed-delay for retry policy.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [0],
                    "reason": "restate_current_retry_policy",
                }
            ),
        )

        response = runtime.observe(
            request(
                "turn-007",
                2,
                text="That retry policy update replaces the earlier fixed-delay retry decision.",
            ),
            now=101,
        )
        active = self.store.active_memories("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "duplicate")
        self.assertEqual(response.final_result["duplicate_of_memory_id"], prior.id)
        self.assertEqual(self.store.memory_count("project-a"), 1)
        self.assertEqual(active[0].id, prior.id)
        self.assertEqual(active[0].source_ref.event_id, "turn-005")

    def test_dependency_restriction_write_becomes_duplicate_of_project_preference(self):
        ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "preference",
                        "subject": "dependency_policy",
                        "text": "Do not add new dependencies.",
                        "scope_level": "project",
                        "component": None,
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "dependency_preference",
                }
            ),
        ).observe(
            request(
                "turn-003",
                1,
                text="For this project, keep retry behavior dependency-free.",
            ),
            now=100,
        )
        prior = self.store.active_memories("project-a")[0]
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "preference",
                        "subject": "dependency_policy",
                        "text": "Do not change pyproject.toml for this retry change.",
                        "scope_level": "project",
                        "component": None,
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "dependency_preference",
                }
            ),
        )

        response = runtime.observe(
            request(
                "turn-008",
                2,
                text="Do not change pyproject.toml for this retry change.",
            ),
            now=101,
        )
        active = self.store.active_memories("project-a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "duplicate")
        self.assertEqual(response.final_result["duplicate_of_memory_id"], prior.id)
        self.assertEqual(self.store.memory_count("project-a"), 1)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, prior.id)
        self.assertEqual(active[0].source_ref.event_id, "turn-003")

    def test_component_policy_subject_must_match_component(self):
        runtime = ObserveRuntime(
            store=self.store,
            decider=QueueDecider(
                {
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "auth_policy",
                        "text": "Auth uses bearer token validation; it is not part of the retry task.",
                        "scope_level": "component",
                        "component": "retry",
                    },
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "auth_policy",
                }
            ),
        )

        response = runtime.observe(
            request(
                "turn-010",
                1,
                text="Auth uses bearer token validation; it is not part of the retry task.",
            ),
            now=100,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "subject_component_mismatch")
        self.assertEqual(self.store.memory_count("project-a"), 0)

    def test_retryable_decider_failure_does_not_advance_cursor(self):
        runtime = ObserveRuntime(store=self.store, decider=FailingDecider())

        response = runtime.observe(request("turn-001", 1), now=100)
        blocked_next = self.store.claim_event(request("turn-002", 2), now=101)
        retry = self.store.claim_event(request("turn-001", 1), now=102)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.error, "provider_network_error")
        self.assertEqual(blocked_next.status_code, 409)
        self.assertEqual(blocked_next.error, "prior_event_incomplete")
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(retry.attempt_no, 2)

    def test_operator_action_provider_failure_remains_retryable_and_blocks_cursor(self):
        runtime = ObserveRuntime(store=self.store, decider=TerminalFailingDecider())

        response = runtime.observe(request("turn-001", 1), now=100)
        retry = self.store.claim_event(request("turn-001", 1), now=101)
        blocked_next = self.store.claim_event(request("turn-002", 2), now=102)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.error, "provider_operator_action_required")
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(retry.attempt_no, 2)
        self.assertEqual(blocked_next.status_code, 409)
        self.assertEqual(blocked_next.error, "prior_event_incomplete")


if __name__ == "__main__":
    unittest.main()
