import copy
import unittest

from recallpack.evidence import (
    validate_legacy_aggregate_report_diagnostic as validate_aggregate_report,
)
from tests.v4_evidence_fixtures import (
    TestOnlyTrustedRetainedAttemptLoader,
    build_aggregate_report,
    build_aggregate_scope,
    build_artifact_bytes,
    build_evaluation_run,
    build_test_only_retained_attempt_authority,
    build_test_only_simulated_runtime_contract_scope_packet,
    canonical_sha256,
)


class AggregateEdgeCaseTests(unittest.TestCase):
    def _validate_kwargs(self, packet):
        return {
            "execution_manifest": packet["manifest"],
            "retained_attempt_loader": packet["retained_attempt_loader"],
            "artifact_bytes": packet["artifact_bytes"],
            "source_ledgers": packet["all_source_ledgers"],
            "relation_label_ledgers": packet["all_relation_label_ledgers"],
        }

    def test_revealed_blind_holdout_source_ledger_must_match_frozen_hash(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        source_ledgers = copy.deepcopy(packet["all_source_ledgers"])
        source_ledgers["holdout-a"]["entries"][0]["event_sha256"] = "0" * 64
        kwargs = self._validate_kwargs(packet)
        kwargs["source_ledgers"] = source_ledgers

        with self.assertRaises(ValueError) as excinfo:
            validate_aggregate_report(packet["aggregate"], **kwargs)
        message = str(excinfo.exception)
        self.assertIn("invalid_aggregate", message)
        self.assertIn("/source_ledgers/holdout-a", message)
        self.assertIn(
            "revealed blind holdout source ledger must match the frozen source_ledger_hash",
            message,
        )

    def test_downstream_metric_counts_pretest_adverse_run_as_not_passed(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        target_id = packet["contributors"][0]["run_id"]
        target = next(run for run in packet["all_runs"] if run["run_id"] == target_id)
        target["patch"]["accepted"] = False
        target["patch"]["validation_status"] = "rejected"
        target["patch"]["diff_artifact_id"] = None
        target["patch"]["diff_sha256"] = None
        target["patch"]["original_files"] = []
        target["patch"]["files"] = []
        for artifact_id in (
            "patch_diff",
            "original_file_retry",
            "patched_file_retry",
        ):
            target["run_output_artifact_catalog"].pop(artifact_id)
            target["artifact_hashes"].pop(artifact_id)
        target["test_result"] = None
        target["outcome"] = {
            "status": "adverse",
            "stage": "patch_generation",
            "code": "patch_rejected",
        }
        contributors = [
            run
            for run in packet["all_runs"]
            if run["scenario_id"] == "projectodyssey"
            and run["variant_id"] == "semantic_rerank"
        ]
        packet["artifact_bytes"] = build_artifact_bytes(
            packet["manifest"],
            source_ledgers=packet["all_source_ledgers"],
            simulated_external_holdout=packet["simulated_external_holdout"],
            run_records=packet["all_runs"],
        )
        authority = build_test_only_retained_attempt_authority(
            packet["manifest"], packet["all_runs"]
        )
        packet["retained_attempt_loader"] = TestOnlyTrustedRetainedAttemptLoader(
            authority
        )
        report = build_aggregate_report(
            packet["manifest"],
            claim_id="claim_downstream_superiority",
            claim_type="downstream_superiority",
            run_records=contributors,
            run_ids=[run["run_id"] for run in contributors],
            adverse_run_ids=[target_id],
            scope=build_aggregate_scope(
                contributors,
                designation="headline",
                scenario_ids=["projectodyssey"],
                variant_ids=["semantic_rerank"],
            ),
            metrics=[
                {
                    "metric_id": "downstream_full_suite_success",
                    "n": 3,
                    "numerator": 2,
                    "denominator": 3,
                    "rate": 2 / 3,
                }
            ],
        )

        validate_aggregate_report(report, **self._validate_kwargs(packet))

    def test_non_authoritative_adverse_attempt_cannot_be_replaced_by_later_success(
        self,
    ):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        target_id = packet["contributors"][0]["run_id"]
        target = next(run for run in packet["all_runs"] if run["run_id"] == target_id)
        target["patch"]["accepted"] = False
        target["patch"]["validation_status"] = "rejected"
        target["patch"]["diff_artifact_id"] = None
        target["patch"]["diff_sha256"] = None
        target["patch"]["original_files"] = []
        target["patch"]["files"] = []
        for artifact_id in (
            "patch_diff",
            "original_file_retry",
            "patched_file_retry",
        ):
            target["run_output_artifact_catalog"].pop(artifact_id)
            target["artifact_hashes"].pop(artifact_id)
        target["test_result"] = None
        target["outcome"] = {
            "status": "adverse",
            "stage": "patch_generation",
            "code": "patch_rejected",
        }
        replacement = build_evaluation_run(
            packet["manifest"],
            run_id="eval_CherryPickedPassingReplacement",
            scenario_id=target["scenario_id"],
            variant_id=target["variant_id"],
            slot_index=target["slot_index"],
            attempt_no=target["attempt_no"] + 100,
            designation=target["designation"],
        )
        retained_runs = [*packet["all_runs"], replacement]
        contributors = [
            replacement if run["run_id"] == target_id else run
            for run in packet["contributors"]
        ]
        packet["artifact_bytes"] = build_artifact_bytes(
            packet["manifest"],
            source_ledgers=packet["all_source_ledgers"],
            simulated_external_holdout=packet["simulated_external_holdout"],
            run_records=retained_runs,
        )
        authority = build_test_only_retained_attempt_authority(
            packet["manifest"],
            retained_runs,
            finalization_states={
                target_id: "retained_non_authoritative",
                replacement["run_id"]: "accepted",
            },
        )
        packet["retained_attempt_loader"] = TestOnlyTrustedRetainedAttemptLoader(
            authority
        )
        report = build_aggregate_report(
            packet["manifest"],
            claim_id="claim_downstream_superiority",
            claim_type="downstream_superiority",
            run_records=contributors,
            run_ids=[run["run_id"] for run in contributors],
            adverse_run_ids=[],
            scope=build_aggregate_scope(
                contributors,
                designation="headline",
                scenario_ids=["projectodyssey"],
                variant_ids=["semantic_rerank"],
            ),
            metrics=[
                {
                    "metric_id": "downstream_full_suite_success",
                    "n": 3,
                    "numerator": 3,
                    "denominator": 3,
                    "rate": 1.0,
                }
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "non-authoritative attempt cannot precede an accepted same-slot replacement",
        ):
            validate_aggregate_report(report, **self._validate_kwargs(packet))

    def test_manual_abort_cannot_be_replaced_by_later_success(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        target_id = packet["contributors"][0]["run_id"]
        target = next(run for run in packet["all_runs"] if run["run_id"] == target_id)
        aborted = build_evaluation_run(
            packet["manifest"],
            run_id="eval_ManualAbortBeforeReplacement",
            scenario_id=target["scenario_id"],
            variant_id=target["variant_id"],
            slot_index=target["slot_index"],
            attempt_no=target["attempt_no"],
            designation="invalidated_abort",
        )
        replacement = build_evaluation_run(
            packet["manifest"],
            run_id="eval_ReplacementAfterManualAbort",
            scenario_id=target["scenario_id"],
            variant_id=target["variant_id"],
            slot_index=target["slot_index"],
            attempt_no=target["attempt_no"] + 100,
            designation=target["designation"],
        )
        retained_runs = [
            aborted if run["run_id"] == target_id else run
            for run in packet["all_runs"]
        ]
        retained_runs.append(replacement)
        contributors = [
            replacement if run["run_id"] == target_id else run
            for run in packet["contributors"]
        ]
        packet["artifact_bytes"] = build_artifact_bytes(
            packet["manifest"],
            source_ledgers=packet["all_source_ledgers"],
            simulated_external_holdout=packet["simulated_external_holdout"],
            run_records=retained_runs,
        )
        authority = build_test_only_retained_attempt_authority(
            packet["manifest"], retained_runs
        )
        packet["retained_attempt_loader"] = TestOnlyTrustedRetainedAttemptLoader(
            authority
        )
        report = build_aggregate_report(
            packet["manifest"],
            claim_id="claim_downstream_superiority",
            claim_type="downstream_superiority",
            run_records=contributors,
            run_ids=[run["run_id"] for run in contributors],
            adverse_run_ids=[],
            scope=build_aggregate_scope(
                contributors,
                designation="headline",
                scenario_ids=["projectodyssey"],
                variant_ids=["semantic_rerank"],
            ),
            metrics=[
                {
                    "metric_id": "downstream_full_suite_success",
                    "n": 3,
                    "numerator": 3,
                    "denominator": 3,
                    "rate": 1.0,
                }
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "manual-abort attempt cannot precede an accepted same-slot replacement",
        ):
            validate_aggregate_report(report, **self._validate_kwargs(packet))

    def test_duplicate_immutable_attempt_cannot_carry_conflicting_finalization(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        authority = copy.deepcopy(packet["retained_attempt_authority"])
        duplicate = copy.deepcopy(authority["entries"][0])
        duplicate["registration_order"] = len(authority["entries"])
        duplicate["finalization_state"] = "retained_non_authoritative"
        authority["entries"].append(duplicate)
        authority["entry_count"] = len(authority["entries"])
        authority["population_sha256"] = canonical_sha256(authority["entries"])
        kwargs = self._validate_kwargs(packet)
        kwargs["retained_attempt_loader"] = TestOnlyTrustedRetainedAttemptLoader(
            authority
        )

        with self.assertRaises(ValueError) as excinfo:
            validate_aggregate_report(packet["aggregate"], **kwargs)
        message = str(excinfo.exception)
        self.assertIn("invalid_aggregate", message)
        self.assertIn("/retained_attempt_authority/entries/60", message)
        self.assertIn(
            "retained attempt identity must be unique across finalized authority entries",
            message,
        )

    def test_slot_and_attempt_identity_cannot_name_two_distinct_run_artifacts(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        alternate = copy.deepcopy(packet["all_runs"][0])
        alternate["run_id"] = "eval_DistinctArtifactSameAttempt"
        retained_runs = packet["all_runs"] + [alternate]
        packet["artifact_bytes"] = build_artifact_bytes(
            packet["manifest"],
            source_ledgers=packet["all_source_ledgers"],
            simulated_external_holdout=packet["simulated_external_holdout"],
            run_records=retained_runs,
        )
        authority = build_test_only_retained_attempt_authority(
            packet["manifest"],
            retained_runs,
            finalization_states={
                alternate["run_id"]: "retained_non_authoritative",
            },
        )
        kwargs = self._validate_kwargs(packet)
        kwargs["retained_attempt_loader"] = TestOnlyTrustedRetainedAttemptLoader(
            authority
        )

        with self.assertRaisesRegex(
            ValueError,
            "retained attempt identity must be unique across finalized authority entries",
        ):
            validate_aggregate_report(packet["aggregate"], **kwargs)

    def test_accepted_attempt_cannot_be_followed_by_same_slot_invalidation(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        accepted = packet["all_runs"][0]
        invalidated = build_evaluation_run(
            packet["manifest"],
            run_id="eval_InvalidationAfterAcceptedAttempt",
            scenario_id=accepted["scenario_id"],
            variant_id=accepted["variant_id"],
            slot_index=accepted["slot_index"],
            attempt_no=accepted["attempt_no"] + 100,
            designation="invalidated_technical",
        )
        retained_runs = packet["all_runs"] + [invalidated]
        packet["artifact_bytes"] = build_artifact_bytes(
            packet["manifest"],
            source_ledgers=packet["all_source_ledgers"],
            simulated_external_holdout=packet["simulated_external_holdout"],
            run_records=retained_runs,
        )
        authority = build_test_only_retained_attempt_authority(
            packet["manifest"],
            retained_runs,
        )
        kwargs = self._validate_kwargs(packet)
        kwargs["retained_attempt_loader"] = TestOnlyTrustedRetainedAttemptLoader(
            authority
        )

        with self.assertRaisesRegex(
            ValueError,
            "accepted retained attempt cannot be followed by a same-slot invalidation",
        ):
            validate_aggregate_report(packet["aggregate"], **kwargs)

    def test_journal_transitions_follow_registration_order_not_array_order(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        contributor_ids = {run["run_id"] for run in packet["contributors"]}
        accepted_index, accepted = next(
            (index, copy.deepcopy(run))
            for index, run in enumerate(packet["all_runs"])
            if run["run_id"] not in contributor_ids
        )
        accepted["attempt_no"] += 100
        retained_runs = list(packet["all_runs"])
        retained_runs[accepted_index] = accepted
        invalidated = build_evaluation_run(
            packet["manifest"],
            run_id="eval_RegistrationOrderedInvalidationAfterAccepted",
            scenario_id=accepted["scenario_id"],
            variant_id=accepted["variant_id"],
            slot_index=accepted["slot_index"],
            attempt_no=accepted["attempt_no"] - 100,
            designation="invalidated_technical",
        )
        retained_runs.append(invalidated)
        packet["artifact_bytes"] = build_artifact_bytes(
            packet["manifest"],
            source_ledgers=packet["all_source_ledgers"],
            simulated_external_holdout=packet["simulated_external_holdout"],
            run_records=retained_runs,
        )
        authority = build_test_only_retained_attempt_authority(
            packet["manifest"], retained_runs
        )
        invalidated_entry = authority["entries"].pop()
        physical_accepted_index = next(
            index
            for index, entry in enumerate(authority["entries"])
            if entry["run_id"] == accepted["run_id"]
        )
        authority["entries"].insert(physical_accepted_index, invalidated_entry)
        authority["population_sha256"] = canonical_sha256(authority["entries"])
        kwargs = self._validate_kwargs(packet)
        kwargs["retained_attempt_loader"] = TestOnlyTrustedRetainedAttemptLoader(
            authority
        )

        with self.assertRaisesRegex(
            ValueError,
            "accepted retained attempt cannot be followed by a same-slot invalidation",
        ):
            validate_aggregate_report(packet["aggregate"], **kwargs)


if __name__ == "__main__":
    unittest.main()
