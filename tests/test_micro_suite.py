import unittest
import json
import tempfile
from pathlib import Path

from recallpack.evaluation import evaluate_micro_suite, load_micro_suite


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "micro-suite"


class MicroSuiteEvaluatorTests(unittest.TestCase):
    def test_micro_suite_has_required_distribution_and_coverage(self):
        suite = load_micro_suite(FIXTURE_ROOT)

        self.assertEqual(len(suite.cases), 32)
        self.assertEqual(suite.operation_counts["no_op"], 8)
        self.assertEqual(suite.operation_counts["duplicate"], 4)
        self.assertEqual(suite.operation_counts["write_independent"], 10)
        self.assertEqual(suite.operation_counts["write_superseding"], 10)
        self.assertGreaterEqual(len(suite.gold_edges), 10)
        self.assertGreaterEqual(len(suite.recall_goals), 8)
        self.assertGreaterEqual(suite.coverage_counts["project_scope_preference"], 3)
        self.assertGreaterEqual(suite.coverage_counts["component_collision"], 3)
        self.assertGreaterEqual(suite.coverage_counts["assistant_vs_user_authority"], 2)
        self.assertIn("hackathon evidence suite", suite.positioning)
        self.assertIn("not a broad benchmark", suite.positioning)

    def test_micro_suite_evaluator_reports_counts_before_rates(self):
        report = evaluate_micro_suite(FIXTURE_ROOT)

        self.assertEqual(report.prediction_evidence["prediction_source"], "behavioral_runtime")
        self.assertFalse(report.prediction_evidence["used_fixture_predictions"])
        self.assertEqual(report.prediction_evidence["case_count"], 32)
        self.assertEqual(report.raw_counts["tp"], 20)
        self.assertEqual(report.raw_counts["fp"], 0)
        self.assertEqual(report.raw_counts["fn"], 0)
        self.assertEqual(report.confusion_matrix["write_superseding"]["write_superseding"], 10)
        self.assertEqual(report.confusion_matrix["no_op"]["no_op"], 8)
        self.assertEqual(report.edge_counts["gold"], 10)
        self.assertEqual(report.edge_counts["predicted"], 10)
        self.assertEqual(report.edge_counts["correct"], 10)
        self.assertEqual(report.metrics["should_create_memory_precision"], 1.0)
        self.assertEqual(report.metrics["should_create_memory_recall"], 1.0)
        self.assertEqual(report.metrics["should_create_memory_f1"], 1.0)
        self.assertEqual(report.metrics["edge_f1"], 1.0)
        self.assertEqual(report.metrics["memory_type_accuracy"], 1.0)
        self.assertEqual(report.metrics["required_memory_recall_at_512"], 1.0)
        self.assertEqual(report.metrics["stale_selected_items"], 0)
        self.assertLessEqual(report.metrics["memory_segment_tokens"], 512)
        self.assertLess(report.sections.index("raw_counts"), report.sections.index("rates"))
        self.assertIn("not a broad benchmark", report.positioning)

    def test_micro_suite_evaluator_ignores_deprecated_prediction_fields(self):
        original = evaluate_micro_suite(FIXTURE_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            mutated_root = Path(tmp)
            payload = json.loads((FIXTURE_ROOT / "suite.json").read_text())
            for case in payload["cases"]:
                case["predicted_operation"] = "write_independent"
                case["predicted_memory_type"] = "preference"
                case["predicted_edge"] = ["wrong_prior", case["id"]]
            (mutated_root / "suite.json").write_text(json.dumps(payload))

            mutated = evaluate_micro_suite(mutated_root)

        self.assertEqual(original.raw_counts, mutated.raw_counts)
        self.assertEqual(original.confusion_matrix, mutated.confusion_matrix)
        self.assertEqual(original.edge_counts, mutated.edge_counts)
        self.assertEqual(original.metrics, mutated.metrics)
        self.assertFalse(mutated.prediction_evidence["used_fixture_predictions"])

    def test_wrong_behavioral_decider_changes_micro_suite_metrics(self):
        wrong_report = evaluate_micro_suite(
            FIXTURE_ROOT,
            decider_overrides={
                "write_01": {
                    "operation": "no_op",
                    "memory": None,
                    "duplicate_of_candidate_index": None,
                    "supersedes_candidate_indexes": [],
                    "reason": "forced_wrong_decider_output",
                }
            },
        )

        self.assertLess(wrong_report.raw_counts["tp"], 20)
        self.assertGreater(wrong_report.raw_counts["fn"], 0)
        self.assertEqual(
            wrong_report.prediction_evidence["prediction_source"],
            "behavioral_runtime",
        )


if __name__ == "__main__":
    unittest.main()
