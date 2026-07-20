import threading
import unittest
from unittest.mock import patch

from recallpack.locking import ProjectTurn, ProjectTurnstileRegistry


def _turn(project: str, sequence: int, attempt: int = 1) -> ProjectTurn:
    return ProjectTurn(
        project_id=project,
        project_event_seq=sequence,
        attempt_no=attempt,
        lease_token=f"secret-{project}-{sequence}-{attempt}",
    )


class ProjectTurnstileRegistryTests(unittest.TestCase):
    def test_reverse_scheduled_turns_enter_in_project_sequence_order(self):
        registry = ProjectTurnstileRegistry()
        second = registry.register(_turn("project-a", 2))
        first = registry.register(_turn("project-a", 1))
        entered: list[int] = []
        first_entered = threading.Event()
        release_first = threading.Event()

        def run(ticket, sequence: int) -> None:
            with ticket:
                entered.append(sequence)
                if sequence == 1:
                    first_entered.set()
                    release_first.wait(timeout=2)

        second_thread = threading.Thread(target=run, args=(second, 2))
        first_thread = threading.Thread(target=run, args=(first, 1))
        second_thread.start()
        first_thread.start()

        self.assertTrue(first_entered.wait(timeout=2))
        self.assertEqual(entered, [1])
        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(entered, [1, 2])

    def test_same_project_turns_never_overlap(self):
        registry = ProjectTurnstileRegistry()
        first = registry.register(_turn("project-a", 1))
        second = registry.register(_turn("project-a", 2))
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def run_first() -> None:
            with first:
                first_entered.set()
                release_first.wait(timeout=2)

        def run_second() -> None:
            with second:
                second_entered.set()

        first_thread = threading.Thread(target=run_first)
        second_thread = threading.Thread(target=run_second)
        first_thread.start()
        self.assertTrue(first_entered.wait(timeout=2))
        second_thread.start()

        self.assertFalse(second_entered.wait(timeout=0.1))
        release_first.set()
        self.assertTrue(second_entered.wait(timeout=2))
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

    def test_different_projects_can_execute_concurrently(self):
        registry = ProjectTurnstileRegistry()
        project_a = registry.register(_turn("project-a", 1))
        project_b = registry.register(_turn("project-b", 1))
        a_entered = threading.Event()
        b_entered = threading.Event()
        release = threading.Event()

        def run(ticket, entered: threading.Event) -> None:
            with ticket:
                entered.set()
                release.wait(timeout=2)

        threads = [
            threading.Thread(target=run, args=(project_a, a_entered)),
            threading.Thread(target=run, args=(project_b, b_entered)),
        ]
        for thread in threads:
            thread.start()

        self.assertTrue(a_entered.wait(timeout=2))
        self.assertTrue(b_entered.wait(timeout=2))
        release.set()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_cancelled_gap_does_not_block_higher_sequence_or_restart(self):
        registry = ProjectTurnstileRegistry()
        abandoned = registry.register(_turn("project-a", 3))
        later = registry.register(_turn("project-a", 9))
        abandoned.cancel()

        with later:
            self.assertEqual(later.turn.project_event_seq, 9)

        restarted_registry = ProjectTurnstileRegistry()
        after_restart = restarted_registry.register(_turn("project-a", 12))
        with after_restart:
            self.assertEqual(after_restart.turn.project_event_seq, 12)

    def test_newer_attempt_for_same_sequence_waits_for_registered_old_attempt(self):
        registry = ProjectTurnstileRegistry()
        old_attempt = registry.register(_turn("project-a", 4, attempt=1))
        new_attempt = registry.register(_turn("project-a", 4, attempt=2))
        order: list[int] = []

        with old_attempt:
            order.append(old_attempt.turn.attempt_no)
        with new_attempt:
            order.append(new_attempt.turn.attempt_no)

        self.assertEqual(order, [1, 2])

    def test_exception_releases_turn_and_notifies_waiters(self):
        registry = ProjectTurnstileRegistry()
        failing = registry.register(_turn("project-a", 1))
        next_ticket = registry.register(_turn("project-a", 2))

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with failing:
                raise RuntimeError("boom")

        with next_ticket:
            self.assertEqual(next_ticket.turn.project_event_seq, 2)

        self.assertEqual(registry.registered_count("project-a"), 0)

    def test_cancelling_waiting_ticket_wakes_waiter_with_stable_error(self):
        registry = ProjectTurnstileRegistry()
        active = registry.register(_turn("project-a", 1))
        waiting = registry.register(_turn("project-a", 2))
        active_entered = threading.Event()
        release_active = threading.Event()
        waiting_started = threading.Event()
        waiting_errors: list[str] = []

        def hold_active() -> None:
            with active:
                active_entered.set()
                release_active.wait(timeout=2)

        def enter_waiting() -> None:
            waiting_started.set()
            try:
                with waiting:
                    pass
            except RuntimeError as exc:
                waiting_errors.append(str(exc))

        active_thread = threading.Thread(target=hold_active)
        waiting_thread = threading.Thread(target=enter_waiting)
        active_thread.start()
        self.assertTrue(active_entered.wait(timeout=2))
        waiting_thread.start()
        self.assertTrue(waiting_started.wait(timeout=2))

        waiting.cancel()
        waiting_thread.join(timeout=2)
        release_active.set()
        active_thread.join(timeout=2)

        self.assertFalse(waiting_thread.is_alive())
        self.assertEqual(waiting_errors, ["project_turn_cancelled"])
        self.assertEqual(registry.registered_count("project-a"), 0)

    def test_turn_repr_does_not_expose_lease_token(self):
        turn = _turn("project-a", 1)

        self.assertNotIn("secret-project-a", repr(turn))

    def test_wait_interruption_removes_registered_ticket(self):
        registry = ProjectTurnstileRegistry()
        ticket = registry.register(_turn("project-a", 1))

        with patch.object(
            registry._condition,
            "wait_for",
            side_effect=RuntimeError("wait interrupted"),
        ):
            with self.assertRaisesRegex(RuntimeError, "wait interrupted"):
                with ticket:
                    pass

        self.assertEqual(registry.registered_count("project-a"), 0)


if __name__ == "__main__":
    unittest.main()
