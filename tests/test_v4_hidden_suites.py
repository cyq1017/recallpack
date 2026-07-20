from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "evaluation" / "runner" / "run_tests.py"
HIDDEN_ROOT = ROOT / "evaluation" / "hidden-tests"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "recallpack_v4_hidden_suite_runner", RUNNER_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("runner module is not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V4HiddenSuiteTests(unittest.TestCase):
    def test_three_scenario_suites_have_closed_three_test_manifests(self):
        runner = _load_runner()
        for scenario_id in ("projectodyssey", "deepagents", "graphiti"):
            with self.subTest(scenario_id=scenario_id):
                scenario_root = HIDDEN_ROOT / scenario_id
                manifest = json.loads((scenario_root / "manifest.json").read_text())
                inventory = runner._static_hidden_test_inventory(scenario_root)

                self.assertEqual(manifest, {"version": "1.0", "tests": inventory})
                self.assertEqual(len(inventory), 3)
                self.assertEqual(len(inventory), len(set(inventory)))


if __name__ == "__main__":
    unittest.main()
