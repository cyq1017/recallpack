import unittest

from ci_policy import handle_jit_crash


class CiPolicyHiddenTests(unittest.TestCase):
    def setUp(self):
        self.policy = handle_jit_crash("jit crash")

    def test_fail_and_fix_forward(self):
        self.assertEqual(self.policy["action"], "fail_and_fix_forward")

    def test_no_retry_skip_or_continue_workaround(self):
        self.assertFalse(self.policy["retry"])
        self.assertEqual(self.policy["retry_attempts"], 0)
        self.assertFalse(self.policy["skip"])
        self.assertFalse(self.policy["continue_on_error"])

    def test_requires_minimal_reproducer(self):
        self.assertTrue(self.policy["minimal_reproducer_required"])
