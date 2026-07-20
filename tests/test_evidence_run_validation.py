import copy
import unittest

from recallpack.tokenization import default_tokenizer
from tests.v4_evidence_fixtures import (
    DEFAULT_CONTEXT_TEXT,
    build_artifact_bytes,
    build_evaluation_run,
    build_full_execution_manifest,
    build_relation_label_ledgers,
    build_relation_opportunity,
    build_run_output_artifact_catalog,
    build_simulated_external_holdout_bundle,
    build_source_ledgers,
    canonical_sha256,
    sha256_hex_bytes,
)


class EvaluationRunPrerequisiteTests(unittest.TestCase):
    def _build_recallpack_packet(
        self,
        *,
        context_text: str | None = None,
        first_source_ref: str | None = None,
    ):
        source_ledgers = build_source_ledgers()
        if first_source_ref is not None:
            source_ledgers["projectodyssey"]["entries"][0]["source_ref"] = (
                first_source_ref
            )
        relation_label_ledgers = build_relation_label_ledgers(source_ledgers)
        simulated_external_holdout = build_simulated_external_holdout_bundle()
        manifest = build_full_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_label_ledgers,
            simulated_external_holdout=simulated_external_holdout,
        )
        ledger_entries = relation_label_ledgers["projectodyssey"]["entries"]
        relation_opportunities = [
            build_relation_opportunity(
                opportunity_id=entry["opportunity_id"],
                scenario_id="projectodyssey",
                relation_kind=entry["relation_kind"],
                decision=(
                    "keep_independent"
                    if entry["relation_kind"] == "hard_negative"
                    else "inactivate_prior"
                ),
                outcome="correct",
                prior_source_ref=entry["prior_source_ref"],
                candidate_source_ref=entry["candidate_source_ref"],
            )
            for entry in ledger_entries
        ]
        output_catalog = None
        exact_token_count = None
        artifact_context_text = None
        if context_text is not None:
            output_catalog = build_run_output_artifact_catalog(context_text=context_text)
            exact_token_count = default_tokenizer().count(context_text)
            artifact_context_text = context_text
        run = build_evaluation_run(
            manifest,
            run_id="eval_RP1",
            variant_id="recallpack",
            relation_opportunities=relation_opportunities,
            output_catalog=output_catalog,
            exact_token_count=exact_token_count,
        )
        if first_source_ref is not None:
            run["selected_sources"] = [first_source_ref]
        artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[run],
            context_text=artifact_context_text or DEFAULT_CONTEXT_TEXT,
        )
        return {
            "manifest": manifest,
            "source_ledgers": source_ledgers,
            "relation_label_ledgers": relation_label_ledgers,
            "run": run,
            "artifact_bytes": artifact_bytes,
            "simulated_external_holdout": simulated_external_holdout,
            "test_only_simulation_marker": simulated_external_holdout["custody_kind"],
        }

    def _assert_semantic_reject(self, run, manifest, *, artifact_bytes, source_ledger, code, **kwargs):
        from recallpack.evidence import (
            validate_legacy_evaluation_run_diagnostic as validate_evaluation_run,
        )

        with self.assertRaisesRegex(ValueError, code):
            validate_evaluation_run(
                run,
                manifest,
                artifact_bytes=artifact_bytes,
                source_ledger=source_ledger,
                **kwargs,
            )

    def _assert_semantic_reject_detail(
        self,
        run,
        manifest,
        *,
        artifact_bytes,
        source_ledger,
        code,
        pointer,
        detail,
        **kwargs,
    ):
        from recallpack.evidence import (
            validate_legacy_evaluation_run_diagnostic as validate_evaluation_run,
        )

        with self.assertRaises(ValueError) as excinfo:
            validate_evaluation_run(
                run,
                manifest,
                artifact_bytes=artifact_bytes,
                source_ledger=source_ledger,
                **kwargs,
            )
        message = str(excinfo.exception)
        self.assertIn(code, message)
        self.assertIn(pointer, message)
        self.assertIn(detail, message)

    def _refreeze_manifest_input_artifact(self, packet, artifact_id, payload):
        refrozen = copy.deepcopy(packet)
        refrozen["artifact_bytes"][artifact_id] = payload
        refrozen["manifest"]["input_artifact_catalog"][artifact_id]["bytes"] = len(payload)
        refrozen["manifest"]["input_artifact_catalog"][artifact_id]["sha256"] = (
            sha256_hex_bytes(payload)
        )
        refrozen["run"]["execution_manifest_sha256"] = canonical_sha256(refrozen["manifest"])
        return refrozen

    def _refreeze_relation_label_ledger(self, packet, relation_label_ledger):
        refrozen = copy.deepcopy(packet)
        refrozen["relation_label_ledgers"]["projectodyssey"] = relation_label_ledger
        relation_hash = canonical_sha256(relation_label_ledger)
        scenario = next(
            item
            for item in refrozen["manifest"]["evidence_scenarios"]
            if item["scenario_slot"] == "projectodyssey"
        )
        scenario["relation_label_ledger_sha256"] = relation_hash
        refrozen["manifest"]["label_hashes"]["projectodyssey"] = relation_hash
        refrozen["artifact_bytes"]["label_projectodyssey"] = relation_hash.encode("utf-8")
        refrozen["manifest"]["input_artifact_catalog"]["label_projectodyssey"]["bytes"] = 64
        refrozen["manifest"]["input_artifact_catalog"]["label_projectodyssey"]["sha256"] = (
            sha256_hex_bytes(refrozen["artifact_bytes"]["label_projectodyssey"])
        )
        refrozen["run"]["execution_manifest_sha256"] = canonical_sha256(refrozen["manifest"])
        return refrozen

    def test_recallpack_headline_relation_opportunities_require_exact_frozen_label_ledger(self):
        packet = self._build_recallpack_packet()
        from recallpack.evidence import (
            validate_legacy_evaluation_run_diagnostic as validate_evaluation_run,
        )

        validate_evaluation_run(
            packet["run"],
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
        )

        missing_ledger = copy.deepcopy(packet["run"])
        self._assert_semantic_reject(
            missing_ledger,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        non_recallpack = build_evaluation_run(
            packet["manifest"],
            run_id="eval_SR1",
            variant_id="semantic_rerank",
            relation_opportunities=copy.deepcopy(packet["run"]["relation_opportunities"]),
        )
        non_recallpack_artifact_bytes = build_artifact_bytes(
            packet["manifest"],
            source_ledgers=packet["source_ledgers"],
            simulated_external_holdout=packet["simulated_external_holdout"],
            run_records=[non_recallpack],
        )
        self._assert_semantic_reject(
            non_recallpack,
            packet["manifest"],
            artifact_bytes=non_recallpack_artifact_bytes,
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        missing_opportunity = copy.deepcopy(packet["run"])
        missing_opportunity["relation_opportunities"] = missing_opportunity["relation_opportunities"][
            :-1
        ]
        self._assert_semantic_reject(
            missing_opportunity,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        shifted_endpoint = copy.deepcopy(packet["run"])
        shifted_endpoint["relation_opportunities"][0]["candidate_source_ref"] = (
            "projectodyssey:turn-004"
        )
        self._assert_semantic_reject(
            shifted_endpoint,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

    def test_relation_labels_and_ledger_payload_must_stay_out_of_model_visible_context(self):
        packet = self._build_recallpack_packet(
            context_text="Leaked opp_projectodyssey_hard_1 into model-visible context."
        )
        self._assert_semantic_reject(
            packet["run"],
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        payload_packet = self._build_recallpack_packet(
            context_text='{"entries":[{"opportunity_id":"opp_projectodyssey_hard_1"}]}'
        )
        self._assert_semantic_reject(
            payload_packet["run"],
            payload_packet["manifest"],
            artifact_bytes=payload_packet["artifact_bytes"],
            source_ledger=payload_packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=payload_packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        endpoint_roles = self._build_recallpack_packet(
            context_text=(
                '{"prior_source_ref":"projectodyssey:turn-001",'
                '"candidate_source_ref":"projectodyssey:turn-004"}'
            )
        )
        self._assert_semantic_reject(
            endpoint_roles["run"],
            endpoint_roles["manifest"],
            artifact_bytes=endpoint_roles["artifact_bytes"],
            source_ledger=endpoint_roles["source_ledgers"]["projectodyssey"],
            relation_label_ledger=endpoint_roles["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

    def test_standalone_source_refs_remain_model_visible_provenance(self):
        packet = self._build_recallpack_packet(
            context_text=(
                "Inspect projectodyssey:turn-001 and projectodyssey:turn-004 "
                "as independently sourced events."
            )
        )
        from recallpack.evidence import (
            validate_legacy_evaluation_run_diagnostic as validate_evaluation_run,
        )

        validate_evaluation_run(
            packet["run"],
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
        )

    def test_source_refs_containing_relation_tokens_remain_visible_provenance(self):
        from recallpack.evidence import (
            validate_legacy_evaluation_run_diagnostic as validate_evaluation_run,
        )

        for source_ref in (
            "hard_negative:foo",
            "projectodyssey:opp_projectodyssey_hard_1",
        ):
            with self.subTest(source_ref=source_ref):
                packet = self._build_recallpack_packet(
                    first_source_ref=source_ref,
                    context_text=f"Inspect {source_ref} as an independently sourced event.",
                )

                validate_evaluation_run(
                    packet["run"],
                    packet["manifest"],
                    artifact_bytes=packet["artifact_bytes"],
                    source_ledger=packet["source_ledgers"]["projectodyssey"],
                    relation_label_ledger=packet["relation_label_ledgers"][
                        "projectodyssey"
                    ],
                )

    def test_source_ref_masking_rejects_relation_tokens_inside_larger_tokens(self):
        for source_ref, context_text in (
            ("hard_negative:foo", "Wrapped xhard_negative:fooy around text."),
            (
                "projectodyssey:opp_projectodyssey_hard_1",
                "Wrapped xprojectodyssey:opp_projectodyssey_hard_1y around text.",
            ),
        ):
            with self.subTest(source_ref=source_ref):
                packet = self._build_recallpack_packet(
                    first_source_ref=source_ref,
                    context_text=context_text,
                )

                self._assert_semantic_reject(
                    packet["run"],
                    packet["manifest"],
                    artifact_bytes=packet["artifact_bytes"],
                    source_ledger=packet["source_ledgers"]["projectodyssey"],
                    relation_label_ledger=packet["relation_label_ledgers"][
                        "projectodyssey"
                    ],
                    code="invalid_relation_evidence",
                )

    def test_relation_label_entries_require_distinct_endpoints(self):
        source_ledgers = build_source_ledgers()
        relation_label_ledgers = build_relation_label_ledgers(source_ledgers)
        simulated_external_holdout = build_simulated_external_holdout_bundle()
        relation_label_ledgers["projectodyssey"]["entries"][0]["candidate_source_ref"] = (
            relation_label_ledgers["projectodyssey"]["entries"][0]["prior_source_ref"]
        )
        manifest = build_full_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_label_ledgers,
            simulated_external_holdout=simulated_external_holdout,
        )
        relation_opportunities = [
            build_relation_opportunity(
                opportunity_id=entry["opportunity_id"],
                scenario_id="projectodyssey",
                relation_kind=entry["relation_kind"],
                decision=(
                    "keep_independent"
                    if entry["relation_kind"] == "hard_negative"
                    else "inactivate_prior"
                ),
                outcome="correct",
                prior_source_ref=entry["prior_source_ref"],
                candidate_source_ref=entry["candidate_source_ref"],
            )
            for entry in relation_label_ledgers["projectodyssey"]["entries"]
        ]
        run = build_evaluation_run(
            manifest,
            run_id="eval_RP2",
            variant_id="recallpack",
            relation_opportunities=relation_opportunities,
        )
        artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[run],
        )
        self._assert_semantic_reject(
            run,
            manifest,
            artifact_bytes=artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
            relation_label_ledger=relation_label_ledgers["projectodyssey"],
            code="invalid_relation_evidence",
        )

    def test_relation_ledger_exactness_rejects_duplicate_ids_extra_entries_relabels_and_wrong_source_hash(self):
        packet = self._build_recallpack_packet()

        duplicate_run_id = copy.deepcopy(packet["run"])
        duplicate_run_id["relation_opportunities"].append(
            copy.deepcopy(duplicate_run_id["relation_opportunities"][0])
        )
        self._assert_semantic_reject(
            duplicate_run_id,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        duplicate_ledger_id = copy.deepcopy(packet["relation_label_ledgers"]["projectodyssey"])
        duplicate_ledger_id["entries"][1]["opportunity_id"] = duplicate_ledger_id["entries"][0][
            "opportunity_id"
        ]
        refrozen_duplicate_ledger = self._refreeze_relation_label_ledger(
            packet, duplicate_ledger_id
        )
        self._assert_semantic_reject_detail(
            refrozen_duplicate_ledger["run"],
            refrozen_duplicate_ledger["manifest"],
            artifact_bytes=refrozen_duplicate_ledger["artifact_bytes"],
            source_ledger=refrozen_duplicate_ledger["source_ledgers"]["projectodyssey"],
            relation_label_ledger=refrozen_duplicate_ledger["relation_label_ledgers"][
                "projectodyssey"
            ],
            code="invalid_relation_evidence",
            pointer="/relation_opportunities/1/opportunity_id",
            detail="relation_label_ledger opportunity_id values must be unique",
        )

        extra_entry = copy.deepcopy(packet["run"])
        extra_entry["relation_opportunities"].append(
            build_relation_opportunity(
                opportunity_id="opp_projectodyssey_extra_1",
                scenario_id="projectodyssey",
                relation_kind="hard_negative",
                decision="keep_independent",
                outcome="correct",
                prior_source_ref="projectodyssey:turn-002",
                candidate_source_ref="projectodyssey:turn-003",
            )
        )
        self._assert_semantic_reject(
            extra_entry,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        relabeled = copy.deepcopy(packet["run"])
        relabeled["relation_opportunities"][0]["relation_kind"] = "true_supersession"
        relabeled["relation_opportunities"][0]["decision"] = "inactivate_prior"
        relabeled["relation_opportunities"][0]["outcome"] = "correct"
        self._assert_semantic_reject(
            relabeled,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
        )

        wrong_source_hash = copy.deepcopy(packet["relation_label_ledgers"]["projectodyssey"])
        wrong_source_hash["source_ledger_sha256"] = "0" * 64
        refrozen_wrong_source_hash = self._refreeze_relation_label_ledger(
            packet, wrong_source_hash
        )
        self._assert_semantic_reject_detail(
            refrozen_wrong_source_hash["run"],
            refrozen_wrong_source_hash["manifest"],
            artifact_bytes=refrozen_wrong_source_hash["artifact_bytes"],
            source_ledger=refrozen_wrong_source_hash["source_ledgers"]["projectodyssey"],
            relation_label_ledger=refrozen_wrong_source_hash["relation_label_ledgers"][
                "projectodyssey"
            ],
            code="invalid_relation_evidence",
            pointer="/relation_opportunities",
            detail="relation_label_ledger must bind the frozen scenario source ledger hash",
        )

    def test_failed_suite_cannot_be_labeled_success_and_patch_stage_truth_table_is_closed(self):
        source_ledgers = build_source_ledgers()
        relation_label_ledgers = build_relation_label_ledgers(source_ledgers)
        simulated_external_holdout = build_simulated_external_holdout_bundle()
        manifest = build_full_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_label_ledgers,
            simulated_external_holdout=simulated_external_holdout,
        )

        failed_suite = build_evaluation_run(
            manifest,
            run_id="eval_TS1",
            full_suite_passed=False,
        )
        failed_suite["outcome"] = {
            "status": "completed",
            "stage": "complete",
            "code": "success",
        }
        failed_artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[failed_suite],
        )
        self._assert_semantic_reject(
            failed_suite,
            manifest,
            artifact_bytes=failed_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
            code="invalid_run_outcome|invalid_test_result",
        )

        rejected_patch = build_evaluation_run(manifest, run_id="eval_TS2")
        rejected_patch["patch"]["accepted"] = False
        rejected_patch["patch"]["validation_status"] = "rejected"
        rejected_patch["patch"]["files"] = []
        rejected_patch["test_result"] = None
        rejected_patch["outcome"] = {
            "status": "adverse",
            "stage": "patch_generation",
            "code": "patch_rejected",
        }
        rejected_artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[rejected_patch],
        )
        from recallpack.evidence import (
            validate_legacy_evaluation_run_diagnostic as validate_evaluation_run,
        )

        with self.assertRaisesRegex(ValueError, "invalid_artifact_reference"):
            validate_evaluation_run(
                rejected_patch,
                manifest,
                artifact_bytes=rejected_artifact_bytes,
                source_ledger=source_ledgers["projectodyssey"],
            )

        rejected_patch["patch"]["original_files"] = []
        for artifact_id in ("original_file_retry", "patched_file_retry"):
            rejected_patch["run_output_artifact_catalog"].pop(artifact_id)
            rejected_patch["artifact_hashes"].pop(artifact_id)
        with self.assertRaisesRegex(ValueError, "invalid_artifact_reference"):
            validate_evaluation_run(
                rejected_patch,
                manifest,
                artifact_bytes=rejected_artifact_bytes,
                source_ledger=source_ledgers["projectodyssey"],
            )
        rejected_patch["patch"]["diff_artifact_id"] = None
        rejected_patch["patch"]["diff_sha256"] = None
        rejected_patch["run_output_artifact_catalog"].pop("patch_diff")
        rejected_patch["artifact_hashes"].pop("patch_diff")
        validate_evaluation_run(
            rejected_patch,
            manifest,
            artifact_bytes=rejected_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
        )

        empty_patch = build_evaluation_run(manifest, run_id="eval_TS3")
        empty_patch["patch"] = None
        empty_patch["test_result"] = None
        empty_patch["outcome"] = {
            "status": "adverse",
            "stage": "patch_generation",
            "code": "empty_patch",
        }
        empty_artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[empty_patch],
        )
        with self.assertRaisesRegex(ValueError, "invalid_artifact_reference"):
            validate_evaluation_run(
                empty_patch,
                manifest,
                artifact_bytes=empty_artifact_bytes,
                source_ledger=source_ledgers["projectodyssey"],
            )
        for artifact_id in (
            "patch_diff",
            "original_file_retry",
            "patched_file_retry",
        ):
            empty_patch["run_output_artifact_catalog"].pop(artifact_id)
            empty_patch["artifact_hashes"].pop(artifact_id)
        validate_evaluation_run(
            empty_patch,
            manifest,
            artifact_bytes=empty_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
        )

        mislabeled_empty_patch = copy.deepcopy(empty_patch)
        mislabeled_empty_patch["outcome"] = {
            "status": "completed",
            "stage": "complete",
            "code": "success",
        }
        self._assert_semantic_reject(
            mislabeled_empty_patch,
            manifest,
            artifact_bytes=empty_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
            code="invalid_run_outcome",
        )

        passed_as_failed = build_evaluation_run(manifest, run_id="eval_TS4")
        passed_as_failed["outcome"] = {
            "status": "adverse",
            "stage": "hidden_test",
            "code": "hidden_tests_failed",
        }
        passed_as_failed_artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[passed_as_failed],
        )
        self._assert_semantic_reject(
            passed_as_failed,
            manifest,
            artifact_bytes=passed_as_failed_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
            code="invalid_run_outcome",
        )

        accepted_patch_without_test = build_evaluation_run(manifest, run_id="eval_TS5")
        accepted_patch_without_test["test_result"] = None
        accepted_patch_without_test["outcome"] = {
            "status": "completed",
            "stage": "complete",
            "code": "success",
        }
        accepted_patch_without_test_artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[accepted_patch_without_test],
        )
        self._assert_semantic_reject(
            accepted_patch_without_test,
            manifest,
            artifact_bytes=accepted_patch_without_test_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
            code="invalid_run_outcome",
        )

        technical_with_completed_suite = build_evaluation_run(
            manifest,
            run_id="eval_TS5Technical",
            full_suite_passed=True,
        )
        technical_with_completed_suite["designation"] = "invalidated_technical"
        technical_with_completed_suite["outcome"] = {
            "status": "invalidated",
            "stage": "sandbox",
            "code": "technical_failure",
        }
        technical_with_completed_suite["failure"] = {
            "code": "sandbox_timeout",
            "detail": "contradictory completed suite",
            "evidence_sha256": "9" * 64,
        }
        technical_artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[technical_with_completed_suite],
        )
        self._assert_semantic_reject(
            technical_with_completed_suite,
            manifest,
            artifact_bytes=technical_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
            code="invalid_run_outcome",
        )

        test_without_patch = build_evaluation_run(manifest, run_id="eval_TS6")
        test_without_patch["patch"] = None
        test_without_patch_artifact_bytes = build_artifact_bytes(
            manifest,
            source_ledgers=source_ledgers,
            simulated_external_holdout=simulated_external_holdout,
            run_records=[test_without_patch],
        )
        self._assert_semantic_reject(
            test_without_patch,
            manifest,
            artifact_bytes=test_without_patch_artifact_bytes,
            source_ledger=source_ledgers["projectodyssey"],
            code="invalid_run_outcome|invalid_artifact_reference",
        )

    def test_relation_leakage_scan_covers_model_visible_snapshot_and_prompt_template(self):
        snapshot_packet = self._refreeze_manifest_input_artifact(
            self._build_recallpack_packet(),
            "model_visible_snapshot",
            b"Leaked opp_projectodyssey_hard_1 into the frozen snapshot.",
        )
        self._assert_semantic_reject_detail(
            snapshot_packet["run"],
            snapshot_packet["manifest"],
            artifact_bytes=snapshot_packet["artifact_bytes"],
            source_ledger=snapshot_packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=snapshot_packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
            pointer="/input_artifact_catalog/model_visible_snapshot",
            detail="relation evidence must stay out of model-visible artifacts",
        )

        prompt_packet = self._refreeze_manifest_input_artifact(
            self._build_recallpack_packet(),
            "prompt_template",
            b'{"opportunity_id":"opp_projectodyssey_hard_1"}',
        )
        self._assert_semantic_reject_detail(
            prompt_packet["run"],
            prompt_packet["manifest"],
            artifact_bytes=prompt_packet["artifact_bytes"],
            source_ledger=prompt_packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=prompt_packet["relation_label_ledgers"]["projectodyssey"],
            code="invalid_relation_evidence",
            pointer="/input_artifact_catalog/prompt_template",
            detail="relation evidence must stay out of model-visible artifacts",
        )

        tampered_snapshot_packet = self._build_recallpack_packet()
        tampered_snapshot_packet["artifact_bytes"]["model_visible_snapshot"] = (
            b"sanitized replacement that no longer matches the frozen manifest hash"
        )
        self._assert_semantic_reject_detail(
            tampered_snapshot_packet["run"],
            tampered_snapshot_packet["manifest"],
            artifact_bytes=tampered_snapshot_packet["artifact_bytes"],
            source_ledger=tampered_snapshot_packet["source_ledgers"]["projectodyssey"],
            relation_label_ledger=tampered_snapshot_packet["relation_label_ledgers"][
                "projectodyssey"
            ],
            code="invalid_relation_evidence",
            pointer="/input_artifact_catalog/model_visible_snapshot",
            detail="model-visible artifact bytes must match the frozen manifest catalog",
        )


if __name__ == "__main__":
    unittest.main()
