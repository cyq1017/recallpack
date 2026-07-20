import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from recallpack.observe import ObserveRequest, ObserveRuntime
from recallpack.storage import SqliteEventStore


def request(
    event_id: str = "turn-001",
    sequence_no: int = 1,
    *,
    observed_at: str = "2026-07-10T00:00:00Z",
    text: str = "Use three attempts with a fixed 100 ms delay in retry.",
) -> ObserveRequest:
    return ObserveRequest(
        project_id="project-a",
        session_id="session-a",
        event_id=event_id,
        sequence_no=sequence_no,
        actor="user",
        kind="message",
        observed_at=observed_at,
        text=text,
    )


class _Ticket:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _CountingTurnstiles:
    def __init__(self) -> None:
        self.turns = []

    def register(self, turn):
        self.turns.append(turn)
        return _Ticket()


class _CountingNoOpDecider:
    def __init__(self) -> None:
        self.calls = 0

    def decide_memory_operation(self, request, candidates):
        self.calls += 1
        return {
            "operation": "no_op",
            "memory": None,
            "duplicate_of_candidate_index": None,
            "supersedes_candidate_indexes": [],
            "reason": "non_memory_event",
        }


class ObserveIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "events.sqlite3"
        self.store = SqliteEventStore(self.db_path, lease_seconds=30)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_unexpired_pending_duplicate_returns_before_project_turnstile(self):
        original = request()
        first = self.store.claim_event(original, now=100)
        turnstiles = _CountingTurnstiles()
        decider = _CountingNoOpDecider()
        runtime = ObserveRuntime(
            store=self.store,
            decider=decider,
            turnstile_registry=turnstiles,
        )

        duplicate = runtime.observe(original, now=101)

        self.assertEqual(first.attempt_no, 1)
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(self.store.attempt_count("project-a", "session-a", "turn-001"), 1)
        self.assertEqual(turnstiles.turns, [])
        self.assertEqual(decider.calls, 0)

    def test_equivalent_timestamp_offsets_share_one_canonical_pending_event(self):
        offset = request(observed_at="2026-07-10T08:00:00+08:00")
        utc = request(observed_at="2026-07-10T00:00:00Z")

        first = self.store.claim_event(offset, now=100)
        replay = self.store.claim_event(utc, now=101)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            stored_timestamp = conn.execute(
                "SELECT observed_at FROM session_events WHERE internal_id = ?",
                (first.event_internal_id,),
            ).fetchone()[0]
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.attempt_no, 1)
        self.assertEqual(stored_timestamp, "2026-07-10T00:00:00Z")

    def test_payload_change_under_same_event_identity_conflicts(self):
        self.store.claim_event(request(), now=100)

        conflict = self.store.claim_event(
            request(text="Use five attempts with exponential backoff in retry."),
            now=101,
        )

        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.error, "idempotency_conflict")
        self.assertEqual(self.store.attempt_count("project-a", "session-a", "turn-001"), 1)

    def test_out_of_order_event_is_rejected_without_persisting_it(self):
        response = self.store.claim_event(request("turn-002", 2), now=100)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.error, "out_of_order")
        self.assertFalse(self.store.has_event("project-a", "session-a", "turn-002"))

    def test_new_event_is_blocked_while_prior_event_is_retryable(self):
        first = self.store.claim_event(request(), now=100)
        self.assertTrue(
            self.store.fail_retryable_event(
                first.event_internal_id,
                first.lease_token,
                first.attempt_no,
                "provider_timeout",
            )
        )

        blocked = self.store.claim_event(request("turn-002", 2), now=101)

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.error, "prior_event_incomplete")
        self.assertFalse(self.store.has_event("project-a", "session-a", "turn-002"))

    def test_completed_replay_uses_durable_result_and_attempt_without_provider_work(self):
        original = request()
        first = self.store.claim_event(original, now=100)
        final_result = {
            "operation": "no_op",
            "reason": "non_memory_event",
            "memory": None,
        }
        self.assertTrue(
            self.store.complete_event(
                first.event_internal_id,
                first.lease_token,
                first.attempt_no,
                final_result,
            )
        )
        turnstiles = _CountingTurnstiles()
        decider = _CountingNoOpDecider()
        runtime = ObserveRuntime(
            store=self.store,
            decider=decider,
            turnstile_registry=turnstiles,
        )

        replay = runtime.observe(original, now=101)

        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.final_result, final_result)
        self.assertEqual(replay.attempt_no, 1)
        self.assertEqual(turnstiles.turns, [])
        self.assertEqual(decider.calls, 0)

    def test_cursor_advances_only_after_terminal_completion(self):
        first = self.store.claim_event(request(), now=100)
        blocked = self.store.claim_event(request("turn-002", 2), now=101)
        self.assertEqual(blocked.error, "prior_event_incomplete")

        self.assertTrue(
            self.store.complete_event(
                first.event_internal_id,
                first.lease_token,
                first.attempt_no,
                {
                    "operation": "no_op",
                    "reason": "non_memory_event",
                    "memory": None,
                },
            )
        )
        second = self.store.claim_event(request("turn-002", 2), now=102)

        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.attempt_no, 1)


if __name__ == "__main__":
    unittest.main()
