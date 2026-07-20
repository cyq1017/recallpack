import unittest

from backend_policy import backend_for_example


class BackendPolicyHiddenTests(unittest.TestCase):
    def test_new_example_uses_maintained_backend(self):
        self.assertEqual(backend_for_example("new_example"), "neo4j")

    def test_new_example_avoids_deprecated_backend(self):
        self.assertNotEqual(backend_for_example("new_example"), "kuzu")

    def test_legacy_compatibility_remains_available(self):
        self.assertEqual(backend_for_example("legacy_compatibility"), "kuzu")
