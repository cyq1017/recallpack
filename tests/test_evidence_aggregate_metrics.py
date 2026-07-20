import copy
import unittest

from recallpack.evidence import (
    validate_legacy_aggregate_report_diagnostic as validate_aggregate_report,
)
from tests.v4_evidence_fixtures import (
    build_aggregate_report,
    build_test_only_simulated_false_supersession_scope_packet,
    build_test_only_simulated_runtime_contract_scope_packet,
)


class AggregateMetricTests(unittest.TestCase):
    def _validate_kwargs(self, packet):
        return {
            "execution_manifest": packet["manifest"],
            "retained_attempt_loader": packet["retained_attempt_loader"],
            "artifact_bytes": packet["artifact_bytes"],
            "source_ledgers": packet["all_source_ledgers"],
            "relation_label_ledgers": packet["all_relation_label_ledgers"],
        }

    def _metric_report(
        self,
        packet,
        *,
        metric_id,
        n,
        numerator,
        denominator,
        rate,
        claim_id="claim_structural_runtime",
        claim_type="structural_runtime",
    ):
        return build_aggregate_report(
            packet["manifest"],
            claim_id=claim_id,
            claim_type=claim_type,
            run_records=packet["contributors"],
            run_ids=[run["run_id"] for run in packet["contributors"]],
            adverse_run_ids=[
                run["run_id"]
                for run in packet["contributors"]
                if run["outcome"]["status"] == "adverse"
            ],
            scope=copy.deepcopy(packet["aggregate"]["scope"]),
            metrics=[
                {
                    "metric_id": metric_id,
                    "n": n,
                    "numerator": numerator,
                    "denominator": denominator,
                    "rate": rate,
                }
            ],
        )

    def test_every_supported_metric_is_recomputed_and_rate_is_exact(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        runs = packet["contributors"]
        arithmetic = {
            "runtime_contract_success": (len(runs), len(runs), len(runs)),
            "stale_leakage_rate": (
                sum(run["metrics"]["selected_total"] for run in runs),
                sum(run["metrics"]["stale_selected"] for run in runs),
                sum(run["metrics"]["selected_total"] for run in runs),
            ),
            "active_memory_recall_at_budget": (
                sum(run["metrics"]["required_total"] for run in runs),
                sum(run["metrics"]["required_selected"] for run in runs),
                sum(run["metrics"]["required_total"] for run in runs),
            ),
            "supersession_prior_candidate_recall_at_8": (
                sum(run["metrics"]["candidate_prior_total"] for run in runs),
                sum(run["metrics"]["candidate_prior_selected"] for run in runs),
                sum(run["metrics"]["candidate_prior_total"] for run in runs),
            ),
            "downstream_full_suite_success": (
                len(runs),
                sum(run["test_result"]["full_suite_passed"] for run in runs),
                len(runs),
            ),
        }
        for metric_id, (n, numerator, denominator) in arithmetic.items():
            claim_id = "claim_structural_runtime"
            claim_type = "structural_runtime"
            if metric_id == "downstream_full_suite_success":
                claim_id = "claim_downstream_superiority"
                claim_type = "downstream_superiority"
            valid = self._metric_report(
                packet,
                metric_id=metric_id,
                n=n,
                numerator=numerator,
                denominator=denominator,
                rate=None if denominator == 0 else numerator / denominator,
                claim_id=claim_id,
                claim_type=claim_type,
            )
            validate_aggregate_report(valid, **self._validate_kwargs(packet))

            wrong = copy.deepcopy(valid)
            wrong["metrics"][0]["numerator"] = numerator + 1
            with self.assertRaises(ValueError) as excinfo:
                validate_aggregate_report(wrong, **self._validate_kwargs(packet))
            message = str(excinfo.exception)
            self.assertIn("/metrics/0/numerator", message)
            self.assertIn(
                f"{metric_id} numerator must equal recomputed arithmetic",
                message,
            )

        false_packet = build_test_only_simulated_false_supersession_scope_packet()
        validate_aggregate_report(
            false_packet["aggregate"],
            **self._validate_kwargs(false_packet),
        )
        wrong_false = copy.deepcopy(false_packet["aggregate"])
        wrong_false["metrics"][0]["n"] += 1
        with self.assertRaisesRegex(ValueError, "unique opportunity count"):
            validate_aggregate_report(
                wrong_false,
                **self._validate_kwargs(false_packet),
            )

        invalid_rate = copy.deepcopy(packet["aggregate"])
        invalid_rate["metrics"][0]["rate"] = None
        with self.assertRaisesRegex(ValueError, "None is not of type 'number'"):
            validate_aggregate_report(
                invalid_rate,
                **self._validate_kwargs(packet),
            )


if __name__ == "__main__":
    unittest.main()
