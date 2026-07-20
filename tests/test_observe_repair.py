import json
import sqlite3
from contextlib import closing
import tempfile
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
    ProviderError,
    ProviderMemoryDecider,
    QwenEmbeddingProvider,
    QwenMemoryDecisionProvider,
    TEXT_EMBEDDING_MODEL,
    TEXT_MODEL,
)
from recallpack.storage import SqliteEventStore


def request() -> ObserveRequest:
    return ObserveRequest(
        project_id="project-a",
        session_id="session-a",
        event_id="turn-001",
        sequence_no=1,
        actor="user",
        kind="message",
        observed_at="2026-07-10T00:00:00Z",
        text="Use five attempts with exponential backoff in retry.",
    )


def no_op(reason: str) -> dict[str, object]:
    return {
        "operation": "no_op",
        "memory": None,
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def invalid_write(memory_type: str = "unknown") -> dict[str, object]:
    return {
        "operation": "write",
        "memory": {
            "type": memory_type,
            "subject": "retry_policy",
            "text": "Use five attempts with exponential backoff.",
            "scope_level": "component",
            "component": "retry",
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": "updated_retry_policy",
    }


def valid_write() -> dict[str, object]:
    return invalid_write(memory_type="decision")


def cache_write() -> dict[str, object]:
    operation = valid_write()
    operation["memory"] = {
        "type": "decision",
        "subject": "cache_policy",
        "text": "Cache successful responses for sixty seconds.",
        "scope_level": "component",
        "component": "cache",
    }
    operation["reason"] = "cache_policy_recorded"
    return operation


def next_request(sequence_no: int, text: str | None = None) -> ObserveRequest:
    return ObserveRequest(
        **{
            **request().__dict__,
            "event_id": f"turn-{sequence_no:03d}",
            "sequence_no": sequence_no,
            "text": text or request().text,
        }
    )


class ScriptedRepairDecider:
    def __init__(self, initial, repaired) -> None:
        self.initial = initial
        self.repaired = repaired
        self.initial_calls = 0
        self.repair_calls = 0
        self.repair_errors = []

    def decide_memory_operation(self, request, candidates):
        self.initial_calls += 1
        if isinstance(self.initial, Exception):
            raise self.initial
        return self.initial

    def repair_memory_operation(self, request, candidates, validation_errors):
        self.repair_calls += 1
        self.repair_errors.append(list(validation_errors))
        if isinstance(self.repaired, Exception):
            raise self.repaired
        return self.repaired


class FailingDocumentEmbeddingProvider(DeterministicKeywordEmbeddingProvider):
    is_live = True

    def embed_document(self, text):
        raise ProviderError.retryable(
            provider_name="qwen-cloud",
            model_id=TEXT_EMBEDDING_MODEL,
            message="temporary embedding timeout",
            request_id="req-embedding-private",
            usage={"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5},
            code="provider_timeout",
        )


class RaisingDecisionProvider:
    def __init__(self, error) -> None:
        self.error = error

    def decide_memory_operation(self, event_text, candidate_payloads, tool_schema):
        raise self.error


class ScriptedQwenClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = 0

    def post_json(self, **kwargs):
        self.calls += 1
        return self.responses.pop(0), {}


def qwen_decision_body(arguments, request_id):
    content = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {
        "id": request_id,
        "model": TEXT_MODEL,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }


class BusyOnCompleteStore(SqliteEventStore):
    def complete_event(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")


class ObserveRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "events.sqlite3"
        self.store = SqliteEventStore(self.db_path, lease_seconds=30)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _runtime(self, decider, embedding_provider=None) -> ObserveRuntime:
        return ObserveRuntime(
            store=self.store,
            decider=decider,
            embedding_provider=(
                embedding_provider or DeterministicKeywordEmbeddingProvider()
            ),
        )

    def _relation_count(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            return conn.execute("SELECT COUNT(*) FROM memory_relations").fetchone()[0]

    def _run_row(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM observe_runs").fetchone()

    def test_retryable_provider_failure_persists_sanitized_call_evidence(self):
        secret = "sk-" + "sensitive-unit-test-token"
        provider = RaisingDecisionProvider(
            ProviderError.retryable(
                provider_name="qwen-cloud",
                model_id=TEXT_MODEL,
                message=(
                    f"upstream timeout while using {secret} "
                    "request_id=req-private-123 password=hunter2 "
                    "Authorization: Bearer bearer-private-888"
                ),
                request_id="req-private-123",
                usage={"prompt_tokens": 7, "completion_tokens": 0, "total_tokens": 7},
                code="provider_timeout",
            )
        )

        response = self._runtime(ProviderMemoryDecider(provider)).observe(
            request(), now=100
        )

        run = self._run_row()
        calls = json.loads(run["model_calls_json"])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.error, "provider_timeout")
        self.assertEqual(run["state"], "failed_retryable")
        self.assertEqual(run["failure_code"], "provider_timeout")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["role"], "memory_decision")
        self.assertTrue(calls[0]["request_id_present"])
        self.assertEqual(calls[0]["token_usage"]["total_tokens"], 7)
        self.assertNotIn("req-private-123", run["model_calls_json"])
        detail = run["error_detail"] or ""
        self.assertNotIn(secret, detail)
        self.assertNotIn("req-private-123", detail)
        self.assertNotIn("hunter2", detail)
        self.assertNotIn("bearer-private-888", detail)

    def test_qwen_unparseable_initial_output_receives_exactly_one_repair(self):
        client = ScriptedQwenClient(
            [
                qwen_decision_body("{bad}", "req-initial"),
                qwen_decision_body(no_op("repaired_non_memory_event"), "req-repair"),
            ]
        )
        decider = ProviderMemoryDecider(
            QwenMemoryDecisionProvider(client, "https://unused.invalid")
        )

        response = self._runtime(decider).observe(request(), now=100)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.repaired)
        self.assertEqual(response.final_result["reason"], "repaired_non_memory_event")
        self.assertEqual(client.calls, 2)

    def test_qwen_parseable_invalid_repair_becomes_terminal_semantic_no_op(self):
        parseable_invalid = valid_write()
        parseable_invalid["memory"] = 42
        client = ScriptedQwenClient(
            [
                qwen_decision_body(parseable_invalid, "req-initial"),
                qwen_decision_body(parseable_invalid, "req-repair"),
            ]
        )
        decider = ProviderMemoryDecider(
            QwenMemoryDecisionProvider(client, "https://unused.invalid")
        )

        response = self._runtime(decider).observe(request(), now=100)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.repaired)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "invalid_tool_output")
        self.assertEqual(client.calls, 2)

    def test_qwen_false_duplicate_index_is_repaired_without_selecting_candidate_zero(self):
        self._runtime(
            ScriptedRepairDecider(valid_write(), no_op("must_not_run"))
        ).observe(request(), now=100)
        active_before = self.store.active_memories("project-a")
        invalid_duplicate = {
            "operation": "duplicate",
            "memory": None,
            "duplicate_of_candidate_index": False,
            "supersedes_candidate_indexes": [],
            "reason": "model_returned_boolean_index",
        }
        client = ScriptedQwenClient(
            [
                qwen_decision_body(invalid_duplicate, "req-initial"),
                qwen_decision_body(no_op("repaired_boolean_index"), "req-repair"),
            ]
        )

        response = self._runtime(
            ProviderMemoryDecider(
                QwenMemoryDecisionProvider(client, "https://unused.invalid")
            )
        ).observe(next_request(2), now=101)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.repaired)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "repaired_boolean_index")
        self.assertEqual(client.calls, 2)
        self.assertEqual(self.store.active_memories("project-a"), active_before)
        self.assertEqual(self._relation_count(), 0)

    def test_qwen_true_duplicate_index_is_repaired_even_with_two_candidates(self):
        self._runtime(
            ScriptedRepairDecider(valid_write(), no_op("must_not_run"))
        ).observe(request(), now=100)
        self._runtime(
            ScriptedRepairDecider(cache_write(), no_op("must_not_run"))
        ).observe(
            next_request(2, "Cache successful responses for sixty seconds."),
            now=101,
        )
        active_before = self.store.active_memories("project-a")
        invalid_duplicate = {
            "operation": "duplicate",
            "memory": None,
            "duplicate_of_candidate_index": True,
            "supersedes_candidate_indexes": [],
            "reason": "model_returned_boolean_index",
        }
        client = ScriptedQwenClient(
            [
                qwen_decision_body(invalid_duplicate, "req-initial"),
                qwen_decision_body(no_op("repaired_boolean_index"), "req-repair"),
            ]
        )

        response = self._runtime(
            ProviderMemoryDecider(
                QwenMemoryDecisionProvider(client, "https://unused.invalid")
            )
        ).observe(next_request(3), now=102)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.repaired)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(client.calls, 2)
        self.assertEqual(self.store.active_memories("project-a"), active_before)
        self.assertEqual(self._relation_count(), 0)

    def test_qwen_mixed_boolean_supersession_indexes_are_repaired_without_mutation(self):
        self._runtime(
            ScriptedRepairDecider(valid_write(), no_op("must_not_run"))
        ).observe(request(), now=100)
        second_retry_policy = valid_write()
        second_retry_policy["memory"] = {
            **second_retry_policy["memory"],
            "text": "Use three attempts with a fixed 100 ms delay.",
        }
        self._runtime(
            ScriptedRepairDecider(second_retry_policy, no_op("must_not_run"))
        ).observe(
            next_request(2, "Use three attempts with a fixed 100 ms delay."),
            now=101,
        )
        active_before = self.store.active_memories("project-a")
        self.assertEqual(len(active_before), 2)
        invalid_supersession = valid_write()
        invalid_supersession["memory"] = {
            **invalid_supersession["memory"],
            "text": "Use exponential backoff for retry attempts.",
        }
        invalid_supersession["supersedes_candidate_indexes"] = [0, True]
        client = ScriptedQwenClient(
            [
                qwen_decision_body(invalid_supersession, "req-initial"),
                qwen_decision_body(no_op("repaired_boolean_index"), "req-repair"),
            ]
        )

        response = self._runtime(
            ProviderMemoryDecider(
                QwenMemoryDecisionProvider(client, "https://unused.invalid")
            )
        ).observe(
            next_request(3, "Use exponential backoff for retry attempts."),
            now=102,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.repaired)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(client.calls, 2)
        self.assertEqual(self.store.active_memories("project-a"), active_before)
        self.assertEqual(self._relation_count(), 0)

    def test_raw_qwen_embedding_success_is_persisted_without_wrapper(self):
        vector = [0.0] * 1024
        vector[0] = 1.0
        client = ScriptedQwenClient(
            [
                {
                    "id": "req-embedding-private",
                    "model": TEXT_EMBEDDING_MODEL,
                    "data": [{"embedding": vector}],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 0,
                        "total_tokens": 5,
                    },
                }
            ]
        )

        response = self._runtime(
            ScriptedRepairDecider(valid_write(), no_op("must_not_run")),
            embedding_provider=QwenEmbeddingProvider(
                client,
                "https://unused.invalid",
            ),
        ).observe(request(), now=100)

        run = self._run_row()
        calls = json.loads(run["embedding_calls_json"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.provider_mode, "live")
        self.assertTrue(response.request_id_present)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["role"], "embedding")
        self.assertEqual(calls[0]["latency_ms"], 0)
        self.assertEqual(calls[0]["token_usage"]["total_tokens"], 5)
        self.assertNotIn("req-embedding-private", run["embedding_calls_json"])

    def test_sqlite_busy_during_final_commit_returns_retryable_without_cursor_advance(self):
        busy_store = BusyOnCompleteStore(self.db_path, lease_seconds=30)
        runtime = ObserveRuntime(
            store=busy_store,
            decider=ScriptedRepairDecider(
                initial=no_op("non_memory_event"),
                repaired=no_op("must_not_run"),
            ),
            embedding_provider=DeterministicKeywordEmbeddingProvider(),
        )

        try:
            response = runtime.observe(request(), now=100)
        except sqlite3.OperationalError as exc:
            self.fail(f"SQLite error escaped observe boundary: {exc}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.error, "sqlite_busy")
        self.assertTrue(response.run_id.startswith("run_"))
        blocked = busy_store.claim_event(
            ObserveRequest(
                **{**request().__dict__, "event_id": "turn-002", "sequence_no": 2}
            ),
            now=101,
        )
        self.assertEqual(blocked.error, "prior_event_incomplete")

    def test_parseable_invalid_initial_result_receives_one_successful_repair(self):
        decider = ScriptedRepairDecider(
            initial=invalid_write(),
            repaired=no_op("repaired_non_memory_event"),
        )

        response = self._runtime(decider).observe(request(), now=100)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "repaired_non_memory_event")
        self.assertEqual(decider.initial_calls, 1)
        self.assertEqual(decider.repair_calls, 1)
        self.assertIn("invalid_memory_type", decider.repair_errors[0])
        self.assertEqual(self.store.memory_count("project-a"), 0)

    def test_completed_replay_restores_repaired_flag_from_durable_validation(self):
        original = request()
        first = self._runtime(
            ScriptedRepairDecider(
                initial=invalid_write(),
                repaired=no_op("repaired_non_memory_event"),
            )
        ).observe(original, now=100)

        replay = self._runtime(
            ScriptedRepairDecider(
                initial=no_op("must_not_run"),
                repaired=no_op("must_not_run"),
            )
        ).observe(original, now=101)

        self.assertTrue(first.repaired)
        self.assertTrue(replay.replayed)
        self.assertTrue(replay.repaired)
        self.assertEqual(replay.run_id, first.run_id)

    def test_parseable_invalid_repair_becomes_terminal_semantic_no_op(self):
        decider = ScriptedRepairDecider(
            initial=invalid_write(),
            repaired=invalid_write(memory_type="still-invalid"),
        )

        response = self._runtime(decider).observe(request(), now=100)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.final_result["operation"], "no_op")
        self.assertEqual(response.final_result["reason"], "invalid_memory_type")
        self.assertEqual(decider.initial_calls, 1)
        self.assertEqual(decider.repair_calls, 1)
        self.assertEqual(self.store.memory_count("project-a"), 0)
        next_event = self.store.claim_event(
            ObserveRequest(**{**request().__dict__, "event_id": "turn-002", "sequence_no": 2}),
            now=101,
        )
        self.assertEqual(next_event.status_code, 202)

    def test_unparseable_initial_and_repair_remains_retryable(self):
        decider = ScriptedRepairDecider(
            initial=RetryableObserveError("model_output_unparseable"),
            repaired=RetryableObserveError("model_output_unparseable"),
        )

        response = self._runtime(decider).observe(request(), now=100)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.error, "model_output_unparseable_after_repair")
        self.assertEqual(decider.initial_calls, 1)
        self.assertEqual(decider.repair_calls, 1)
        self.assertEqual(self.store.memory_count("project-a"), 0)
        blocked = self.store.claim_event(
            ObserveRequest(**{**request().__dict__, "event_id": "turn-002", "sequence_no": 2}),
            now=101,
        )
        self.assertEqual(blocked.error, "prior_event_incomplete")

    def test_provider_operator_action_is_retryable_without_repair_or_mutation(self):
        decider = ScriptedRepairDecider(
            initial=TerminalObserveError("invalid provider credentials"),
            repaired=no_op("must_not_run"),
        )

        response = self._runtime(decider).observe(request(), now=100)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.error, "provider_operator_action_required")
        self.assertEqual(decider.repair_calls, 0)
        self.assertEqual(self.store.memory_count("project-a"), 0)
        self.assertEqual(self._relation_count(), 0)

    def test_document_embedding_failure_leaves_no_partial_lifecycle_write(self):
        decider = ScriptedRepairDecider(
            initial=valid_write(),
            repaired=no_op("must_not_run"),
        )

        response = self._runtime(
            decider,
            embedding_provider=FailingDocumentEmbeddingProvider(),
        ).observe(request(), now=100)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.error, "provider_timeout")
        self.assertEqual(decider.repair_calls, 0)
        self.assertEqual(self.store.memory_count("project-a"), 0)
        self.assertEqual(self._relation_count(), 0)
        run = self._run_row()
        calls = json.loads(run["embedding_calls_json"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["role"], "embedding")
        self.assertTrue(calls[0]["request_id_present"])
        self.assertEqual(calls[0]["token_usage"]["total_tokens"], 5)
        self.assertNotIn("req-embedding-private", run["embedding_calls_json"])


if __name__ == "__main__":
    unittest.main()
