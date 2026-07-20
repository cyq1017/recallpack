import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from recallpack.observe import ObserveRequest
from recallpack.storage import SqliteEventStore


def request(
    event_id: str,
    sequence_no: int,
    text: str = "Use three attempts with a fixed 100 ms delay in the retry helper.",
) -> ObserveRequest:
    return ObserveRequest(
        project_id="project-a",
        session_id="session-a",
        event_id=event_id,
        sequence_no=sequence_no,
        actor="user",
        kind="message",
        observed_at="2026-06-24T00:00:00Z",
        text=text,
    )


def no_op_result(reason: str = "non_memory_event") -> dict[str, object]:
    return {"operation": "no_op", "reason": reason, "memory": None}


class SqliteEventStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "events.sqlite3"
        self.store = SqliteEventStore(self.db_path, lease_seconds=30)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _observe_runs(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                "SELECT * FROM observe_runs ORDER BY attempt_no"
            ).fetchall()

    def _event_row(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                "SELECT * FROM session_events WHERE external_event_id = 'turn-001'"
            ).fetchone()

    def test_first_claim_persists_one_running_attempt(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)

        runs = self._observe_runs()
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0]["id"].startswith("run_"))
        self.assertEqual(runs[0]["event_internal_id"], claim.event_internal_id)
        self.assertEqual(runs[0]["attempt_no"], 1)
        self.assertEqual(runs[0]["state"], "running")
        self.assertEqual(runs[0]["provider_mode"], "fake")
        self.assertEqual(runs[0]["model_calls_json"], "[]")
        self.assertEqual(runs[0]["embedding_calls_json"], "[]")

    def test_expiry_without_takeover_does_not_revoke_current_attempt(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)

        still_owned = self.store.owns_event_attempt(
            claim.event_internal_id,
            claim.lease_token,
            claim.attempt_no,
        )

        self.assertTrue(still_owned)
        runs = self._observe_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["state"], "running")

    def test_takeover_closes_predecessor_and_retains_both_attempts(self):
        first = self.store.claim_event(request("turn-001", 1), now=100)
        second = self.store.claim_event(request("turn-001", 1), now=131)

        runs = self._observe_runs()
        self.assertEqual([run["attempt_no"] for run in runs], [1, 2])
        self.assertEqual(runs[0]["state"], "lost_lease")
        self.assertEqual(runs[0]["failure_code"], "lease_expired")
        self.assertIsNotNone(runs[0]["finished_at"])
        self.assertGreaterEqual(runs[0]["duration_ms"], 0)
        self.assertEqual(runs[1]["state"], "running")
        self.assertNotEqual(second.lease_token, first.lease_token)
        self.assertFalse(
            self.store.owns_event_attempt(
                first.event_internal_id,
                first.lease_token,
                first.attempt_no,
            )
        )

    def test_completed_event_sets_v4_result_version_and_terminal_run(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)
        final_result = {
            "operation": "no_op",
            "reason": "non_memory_event",
            "memory": None,
        }

        self.assertTrue(
            self.store.complete_event(
                claim.event_internal_id,
                claim.lease_token,
                claim.attempt_no,
                final_result,
            )
        )

        event = self._event_row()
        runs = self._observe_runs()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(event["result_schema_version"], 4)
        self.assertEqual(run["state"], "semantic_no_op")
        self.assertIsNotNone(run["finished_at"])
        self.assertGreaterEqual(run["duration_ms"], 0)

    def test_retryable_failure_terminalizes_run_without_advancing_cursor(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)

        self.assertTrue(
            self.store.fail_retryable_event(
                claim.event_internal_id,
                claim.lease_token,
                claim.attempt_no,
                "provider_timeout",
            )
        )

        runs = self._observe_runs()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["state"], "failed_retryable")
        self.assertEqual(run["failure_code"], "provider_timeout")
        self.assertIsNotNone(run["finished_at"])
        blocked = self.store.claim_event(request("turn-002", 2), now=101)
        self.assertEqual(blocked.error, "prior_event_incomplete")

    def test_shape_incompatible_legacy_result_is_not_replayed_as_v4(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)
        self.assertTrue(
            self.store.complete_event(
                claim.event_internal_id,
                claim.lease_token,
                claim.attempt_no,
                {
                    "operation": "no_op",
                    "reason": "non_memory_event",
                    "memory": None,
                },
            )
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE session_events SET result_schema_version = NULL "
                "WHERE internal_id = ?",
                (claim.event_internal_id,),
            )

        replay = self.store.claim_event(request("turn-001", 1), now=101)

        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.error, "legacy_result_incompatible")

    def test_claims_first_event_and_replays_pending_without_new_attempt(self):
        first = self.store.claim_event(request("turn-001", 1), now=100)
        second = self.store.claim_event(request("turn-001", 1), now=101)

        self.assertEqual(first.status, "pending")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.attempt_no, 1)
        self.assertIsNotNone(first.lease_token)
        self.assertEqual(second.status, "pending")
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.attempt_no, 1)
        self.assertEqual(self.store.attempt_count("project-a", "session-a", "turn-001"), 1)

    def test_rejects_next_event_while_previous_event_is_pending(self):
        self.store.claim_event(request("turn-001", 1), now=100)

        response = self.store.claim_event(request("turn-002", 2), now=101)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.error, "prior_event_incomplete")
        self.assertFalse(self.store.has_event("project-a", "session-a", "turn-002"))

    def test_rejects_same_sequence_new_event_while_original_event_is_pending(self):
        self.store.claim_event(request("turn-001", 1), now=100)

        response = self.store.claim_event(request("turn-001b", 1), now=101)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.error, "prior_event_incomplete")
        self.assertFalse(self.store.has_event("project-a", "session-a", "turn-001b"))

    def test_completed_event_replay_returns_final_result_and_advances_sequence(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)
        completed = self.store.complete_event(
            event_internal_id=claim.event_internal_id,
            lease_token=claim.lease_token,
            attempt_no=claim.attempt_no,
            final_result=no_op_result(),
        )

        replay = self.store.claim_event(request("turn-001", 1), now=110)
        next_claim = self.store.claim_event(request("turn-002", 2), now=111)

        self.assertTrue(completed)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.final_result, no_op_result())
        self.assertEqual(next_claim.status_code, 202)
        self.assertEqual(next_claim.attempt_no, 1)

    def test_expired_pending_lease_can_be_taken_over_with_new_attempt(self):
        first = self.store.claim_event(request("turn-001", 1), now=100)
        second = self.store.claim_event(request("turn-001", 1), now=131)

        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.attempt_no, 2)
        self.assertNotEqual(second.lease_token, first.lease_token)
        self.assertEqual(self.store.attempt_count("project-a", "session-a", "turn-001"), 2)

    def test_lost_lease_attempt_cannot_commit_final_result(self):
        old = self.store.claim_event(request("turn-001", 1), now=100)
        new = self.store.claim_event(request("turn-001", 1), now=131)

        old_commit = self.store.complete_event(
            event_internal_id=old.event_internal_id,
            lease_token=old.lease_token,
            attempt_no=old.attempt_no,
            final_result=no_op_result("stale_attempt_must_not_commit"),
        )
        new_commit = self.store.complete_event(
            event_internal_id=new.event_internal_id,
            lease_token=new.lease_token,
            attempt_no=new.attempt_no,
            final_result=no_op_result(),
        )
        replay = self.store.claim_event(request("turn-001", 1), now=140)

        self.assertFalse(old_commit)
        self.assertTrue(new_commit)
        self.assertEqual(replay.final_result, no_op_result())

    def test_same_event_id_with_different_payload_is_conflict(self):
        self.store.claim_event(request("turn-001", 1), now=100)

        response = self.store.claim_event(
            request("turn-001", 1, text="Use five attempts with exponential backoff."),
            now=101,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.error, "idempotency_conflict")

    def test_new_event_with_completed_old_sequence_is_rejected(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)
        self.store.complete_event(
            event_internal_id=claim.event_internal_id,
            lease_token=claim.lease_token,
            attempt_no=claim.attempt_no,
            final_result=no_op_result(),
        )

        response = self.store.claim_event(request("turn-001b", 1), now=110)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.error, "sequence_conflict")
        self.assertFalse(self.store.has_event("project-a", "session-a", "turn-001b"))

    def test_retryable_failure_does_not_advance_cursor_and_can_be_retried(self):
        claim = self.store.claim_event(request("turn-001", 1), now=100)

        failed = self.store.fail_retryable_event(
            event_internal_id=claim.event_internal_id,
            lease_token=claim.lease_token,
            attempt_no=claim.attempt_no,
            error="temporary qwen timeout",
        )
        blocked_next = self.store.claim_event(request("turn-002", 2), now=111)
        retry = self.store.claim_event(request("turn-001", 1), now=112)

        self.assertTrue(failed)
        self.assertEqual(blocked_next.status_code, 409)
        self.assertEqual(blocked_next.error, "prior_event_incomplete")
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(retry.attempt_no, 2)
        self.assertNotEqual(retry.lease_token, claim.lease_token)

    def test_lost_lease_attempt_cannot_mark_retryable_failure(self):
        old = self.store.claim_event(request("turn-001", 1), now=100)
        new = self.store.claim_event(request("turn-001", 1), now=131)

        old_failure = self.store.fail_retryable_event(
            event_internal_id=old.event_internal_id,
            lease_token=old.lease_token,
            attempt_no=old.attempt_no,
            error="old attempt timeout",
        )
        new_failure = self.store.fail_retryable_event(
            event_internal_id=new.event_internal_id,
            lease_token=new.lease_token,
            attempt_no=new.attempt_no,
            error="new attempt timeout",
        )
        retry = self.store.claim_event(request("turn-001", 1), now=132)

        self.assertFalse(old_failure)
        self.assertTrue(new_failure)
        self.assertEqual(retry.attempt_no, 3)


if __name__ == "__main__":
    unittest.main()
